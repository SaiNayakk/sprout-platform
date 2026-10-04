package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * PERF-03: price fan-out. Many clients hold price streams through the gateway at once; every tick
 * they receive carries the time the market-data service produced it, so the delay to each client
 * is measured directly.
 *
 * <p>Run with {@code -Dgroups=perf}. Settings: {@code perf.clients}, {@code perf.symbols},
 * {@code perf.seconds}, {@code perf.out} (the JSON summary).
 */
@Tag("perf")
class Perf03StreamFanoutTest {

    static final int CLIENTS = Integer.getInteger("perf.clients", 200);
    static final int SYMBOLS = Integer.getInteger("perf.symbols", 5);
    static final int SECONDS = Integer.getInteger("perf.seconds", 60);
    static final String OUT = System.getProperty("perf.out",
            System.getenv().getOrDefault("PERF_OUT", "target/perf-03-summary.json"));

    final AtomicLong events = new AtomicLong();
    final AtomicLong gaps = new AtomicLong();
    final AtomicInteger opened = new AtomicInteger();
    final AtomicInteger failedToOpen = new AtomicInteger();
    final AtomicInteger droppedEarly = new AtomicInteger();
    final ConcurrentLinkedQueue<long[]> latencies = new ConcurrentLinkedQueue<>();

    @Test
    void fanOut() throws Exception {
        Client c = new Client();
        String token = c.account(Client.newEmail()).path("accessToken").asText();
        List<String> symbols = new ArrayList<>();
        c.get("/api/marketdata/v1/instruments", null).body().path("instruments").forEach(i -> symbols.add(i.path("symbol").asText()));

        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        Instant end = Instant.now().plusSeconds(SECONDS + 5);
        List<Thread> threads = new ArrayList<>();
        for (int i = 0; i < CLIENTS; i++) {
            List<String> mine = new ArrayList<>();
            for (int k = 0; k < SYMBOLS; k++) {
                mine.add(symbols.get((i * SYMBOLS + k) % symbols.size()));
            }
            String ip = "198.19." + (i / 250) + "." + (1 + i % 250); // one client address each, as real users
            threads.add(Thread.ofVirtual().start(() -> client(http, token, ip, String.join(",", mine), end)));
            Thread.sleep(10); // ramp up over a couple of seconds
        }
        for (Thread t : threads) {
            t.join(Duration.ofSeconds(SECONDS + 30));
        }

        long[] ms = latencies.stream().flatMapToLong(Arrays::stream).sorted().toArray();
        ObjectNode summary = Client.JSON.createObjectNode();
        summary.put("clients", CLIENTS).put("symbolsPerClient", SYMBOLS).put("seconds", SECONDS)
                .put("opened", opened.get()).put("failedToOpen", failedToOpen.get()).put("endedEarly", droppedEarly.get())
                .put("ticksReceived", events.get()).put("ticksPerSecond", events.get() / (double) SECONDS)
                .put("seqGaps", gaps.get())
                .put("p50Ms", pct(ms, 50)).put("p95Ms", pct(ms, 95)).put("p99Ms", pct(ms, 99)).put("maxMs", ms.length == 0 ? -1 : ms[ms.length - 1]);
        Path out = Path.of(OUT);
        Files.createDirectories(out.toAbsolutePath().getParent());
        Files.writeString(out, Client.JSON.writerWithDefaultPrettyPrinter().writeValueAsString(summary));
        System.out.println("PERF-03 " + summary);

        assertThat(opened.get()).as("every client got a stream").isEqualTo(CLIENTS);
        assertThat(droppedEarly.get()).as("no stream ended early").isZero();
        assertThat(pct(ms, 95)).as("p95 delivery").isLessThan(250);
        assertThat(pct(ms, 99)).as("p99 delivery").isLessThan(1000);
    }

    void client(HttpClient http, String token, String ip, String symbols, Instant end) {
        HttpRequest req = HttpRequest.newBuilder(URI.create(Client.BASE + "/api/marketdata/v1/stream?symbols=" + symbols))
                .header("Accept", "text/event-stream").header("Authorization", "Bearer " + token)
                .header("CF-Connecting-IP", ip).build();
        List<Long> mine = new ArrayList<>();
        Map<String, Long> lastSeq = new HashMap<>();
        try {
            HttpResponse<InputStream> res = http.send(req, HttpResponse.BodyHandlers.ofInputStream());
            if (res.statusCode() != 200) {
                failedToOpen.incrementAndGet();
                res.body().close();
                return;
            }
            opened.incrementAndGet();
            try (InputStream body = res.body();
                 BufferedReader in = new BufferedReader(new InputStreamReader(body, StandardCharsets.UTF_8))) {
                String name = null;
                String line;
                while (Instant.now().isBefore(end)) {
                    line = in.readLine();
                    if (line == null) {
                        droppedEarly.incrementAndGet();
                        break;
                    }
                    if (line.startsWith("event:")) {
                        name = line.substring(6).trim();
                    } else if (line.startsWith("data:") && "tick".equals(name)) {
                        long now = System.currentTimeMillis();
                        JsonNode t = Client.JSON.readTree(line.substring(5));
                        mine.add(now - Instant.parse(t.path("emittedAt").asText()).toEpochMilli());
                        long seq = t.path("seq").asLong();
                        Long prev = lastSeq.put(t.path("symbol").asText(), seq);
                        if (prev != null && seq > prev + 1) {
                            gaps.incrementAndGet(); // conflation: this client was sent the newer price only
                        }
                        events.incrementAndGet();
                    }
                }
            }
        } catch (Exception e) {
            failedToOpen.incrementAndGet();
        }
        latencies.add(mine.stream().mapToLong(Long::longValue).toArray());
    }

    static long pct(long[] sorted, int p) {
        if (sorted.length == 0) {
            return -1;
        }
        return sorted[Math.min(sorted.length - 1, (int) Math.ceil(p / 100.0 * sorted.length) - 1)];
    }
}
