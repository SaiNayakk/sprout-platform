package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * PERF-04: orders under load. Many funded customers place market buys at a steady rate through
 * the gateway, each going through the order service's risk checks, the ledger and the exchange.
 *
 * <p>Hypothesis: at a steady 5 orders a second (far above what the phone will see), p95 placement
 * stays under 1 s, no order fails for a server-side reason, every order fills, and afterwards every
 * customer holds exactly the shares their filled orders bought: nothing lost or doubled under load.
 *
 * <p>Run with {@code -Dgroups=perf-orders}. Settings: {@code perf.customers}, {@code perf.rate}
 * (orders a second), {@code perf.seconds}; the JSON summary goes to {@code PERF04_OUT}.
 */
@Tag("perf-orders")
class Perf04OrderLoadTest {

    static final int CUSTOMERS = Integer.getInteger("perf.customers", 20);
    static final int RATE = Integer.getInteger("perf.rate", 5);
    static final int SECONDS = Integer.getInteger("perf.seconds", 60);
    static final String OUT = System.getenv().getOrDefault("PERF04_OUT", "target/perf-04-summary.json");
    /** Cheap shares, so a customer's deposit covers every order they place. */
    static final List<String> SYMBOLS = List.of("CHAIWALA", "SUNROOT", "KOSHA", "IRONLEAF", "NIGHTOWL", "TEALPWR", "GRIDLINE", "THREADS");

    record Customer(Client client, String token) {}

    final ConcurrentLinkedQueue<Long> latencies = new ConcurrentLinkedQueue<>();
    final Map<Integer, AtomicInteger> statuses = new ConcurrentHashMap<>();
    final Map<String, AtomicInteger> outcomes = new ConcurrentHashMap<>();
    /** customer index -> symbol -> shares their filled orders bought */
    final Map<Integer, Map<String, AtomicInteger>> bought = new ConcurrentHashMap<>();
    final AtomicInteger errors = new AtomicInteger();

    @Test
    void ordersUnderLoad() throws Exception {
        List<Customer> customers = fund();
        Customers.waitForTradingWindow(customers.get(0).client());

        int total = RATE * SECONDS;
        AtomicInteger sent = new AtomicInteger();
        ScheduledExecutorService clock = Executors.newSingleThreadScheduledExecutor();
        var workers = Executors.newVirtualThreadPerTaskExecutor();
        clock.scheduleAtFixedRate(() -> {
            int n = sent.getAndIncrement();
            if (n < total) {
                workers.submit(() -> place(n % CUSTOMERS, customers.get(n % CUSTOMERS)));
            }
        }, 0, 1_000_000 / RATE, TimeUnit.MICROSECONDS);
        while (sent.get() < total) {
            Thread.sleep(200);
        }
        clock.shutdownNow();
        workers.shutdown();
        assertThat(workers.awaitTermination(60, TimeUnit.SECONDS)).as("every order answered").isTrue();

        // afterwards: each customer holds exactly what their filled orders bought
        int mismatched = 0;
        for (int i = 0; i < CUSTOMERS; i++) {
            Customer c = customers.get(i);
            JsonNode holdings = c.client().get("/api/oms/v1/holdings", c.token()).body().path("holdings");
            for (String symbol : SYMBOLS) {
                int held = 0;
                for (JsonNode h : holdings) {
                    if (h.path("symbol").asText().equals(symbol)) {
                        held = h.path("quantity").asInt();
                    }
                }
                int expected = bought.getOrDefault(i, Map.of()).getOrDefault(symbol, new AtomicInteger()).get();
                if (held != expected) {
                    mismatched++;
                    System.out.println("PERF-04 customer " + i + " holds " + held + " " + symbol + ", bought " + expected);
                }
            }
        }

        long[] ms = latencies.stream().mapToLong(Long::longValue).sorted().toArray();
        int serverErrors = statuses.entrySet().stream().filter(e -> e.getKey() >= 500).mapToInt(e -> e.getValue().get()).sum();
        int filled = outcomes.getOrDefault("FILLED", new AtomicInteger()).get();
        ObjectNode summary = Client.JSON.createObjectNode();
        summary.put("customers", CUSTOMERS).put("ordersPerSecond", RATE).put("seconds", SECONDS).put("orders", total)
                .put("filled", filled).put("serverErrors", serverErrors).put("clientErrors", errors.get())
                .put("holdingsMismatched", mismatched)
                .put("p50Ms", Perf03StreamFanoutTest.pct(ms, 50)).put("p95Ms", Perf03StreamFanoutTest.pct(ms, 95))
                .put("p99Ms", Perf03StreamFanoutTest.pct(ms, 99)).put("maxMs", ms.length == 0 ? -1 : ms[ms.length - 1]);
        summary.putPOJO("statuses", statuses);
        summary.putPOJO("outcomes", outcomes);
        Path out = Path.of(OUT);
        Files.createDirectories(out.toAbsolutePath().getParent());
        Files.writeString(out, Client.JSON.writerWithDefaultPrettyPrinter().writeValueAsString(summary));
        System.out.println("PERF-04 " + summary);

        assertThat(serverErrors).as("no order failed for a server-side reason").isZero();
        assertThat(errors.get()).as("no call failed outright").isZero();
        assertThat(filled).as("every order filled").isEqualTo(total);
        assertThat(mismatched).as("holdings match what was bought").isZero();
        assertThat(Perf03StreamFanoutTest.pct(ms, 95)).as("p95 placement").isLessThan(1000);
        assertThat(Perf03StreamFanoutTest.pct(ms, 99)).as("p99 placement").isLessThan(2000);
    }

    /** Funds every customer at once, each from their own client address, as real users. */
    List<Customer> fund() throws Exception {
        List<Customer> customers = new ArrayList<>();
        try (var pool = Executors.newVirtualThreadPerTaskExecutor()) {
            List<java.util.concurrent.Future<Customer>> made = new ArrayList<>();
            for (int i = 0; i < CUSTOMERS; i++) {
                made.add(pool.submit(() -> {
                    Client c = new Client();
                    return new Customer(c, Customers.funded(c, new BigDecimal("50000.00")));
                }));
            }
            for (var f : made) {
                customers.add(f.get(2, TimeUnit.MINUTES));
            }
        }
        return customers;
    }

    void place(int index, Customer c) {
        String symbol = SYMBOLS.get(ThreadLocalRandom.current().nextInt(SYMBOLS.size()));
        long t0 = System.nanoTime();
        try {
            Client.Response r = c.client().send("POST", "/api/oms/v1/orders",
                    Map.of("symbol", symbol, "side", "BUY", "quantity", 1, "orderType", "MARKET", "product", "CNC"),
                    Map.of("Authorization", "Bearer " + c.token(), "Idempotency-Key", UUID.randomUUID().toString()));
            latencies.add(Duration.ofNanos(System.nanoTime() - t0).toMillis());
            statuses.computeIfAbsent(r.status(), k -> new AtomicInteger()).incrementAndGet();
            String status = r.body().path("status").asText("NONE");
            outcomes.computeIfAbsent(status, k -> new AtomicInteger()).incrementAndGet();
            if (status.equals("FILLED")) {
                bought.computeIfAbsent(index, k -> new ConcurrentHashMap<>())
                        .computeIfAbsent(symbol, k -> new AtomicInteger()).addAndGet(r.body().path("filledQuantity").asInt(1));
            }
        } catch (RuntimeException e) {
            errors.incrementAndGet();
            System.out.println("PERF-04 order failed: " + e);
        }
    }
}
