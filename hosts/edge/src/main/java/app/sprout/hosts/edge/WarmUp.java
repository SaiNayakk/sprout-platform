package app.sprout.hosts.edge;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * Warms the edge host's hot paths before it reports ready, so the first real users don't pay for
 * a cold JVM (found by PERF-01: p99 1.9 s on a fresh JVM against 0.3 s warm).
 *
 * <p>While it runs, both services report readiness {@code REFUSING_TRAFFIC}, so health checks, the
 * deploy's smoke tests and pre-prod all wait. It signs in to an address that can't exist (identity
 * checks a dummy password hash for unknown emails, so the full password, database and JSON path
 * runs and nothing is created), and calls the gateway's public key endpoint through the gateway.
 * Warm-up failures are logged, never fatal: a cold host is still a working host.
 *
 * <p>300 sign-ins by default: 60 was enough on a quiet machine but not on a busy one (PERF-02).
 */
final class WarmUp {

    private static final Logger log = LoggerFactory.getLogger(WarmUp.class);
    private static final String BODY = "{\"email\":\"warm-up@sprout.invalid\",\"password\":\"warm-up-not-a-password\"}";

    private WarmUp() {}

    static void run(ConfigurableApplicationContext identity, ConfigurableApplicationContext gateway, int signIns) {
        AvailabilityChangeEvent.publish(identity, ReadinessState.REFUSING_TRAFFIC);
        AvailabilityChangeEvent.publish(gateway, ReadinessState.REFUSING_TRAFFIC);
        long start = System.nanoTime();
        try {
            String identityUrl = "http://127.0.0.1:" + identity.getEnvironment().getProperty("local.server.port");
            String gatewayUrl = "http://127.0.0.1:" + gateway.getEnvironment().getProperty("local.server.port");
            HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            List<HttpRequest> requests = new ArrayList<>();
            for (int i = 0; i < signIns; i++) {
                requests.add(HttpRequest.newBuilder(URI.create(identityUrl + "/v1/sessions"))
                        .header("Content-Type", "application/json").header("X-Request-Id", "warm-up")
                        .POST(HttpRequest.BodyPublishers.ofString(BODY)).build());
            }
            for (int i = 0; i < 100; i++) { // under the gateway's 120 a minute for one client
                requests.add(HttpRequest.newBuilder(URI.create(gatewayUrl + "/api/identity/.well-known/jwks.json"))
                        .header("X-Request-Id", "warm-up").GET().build());
            }
            ExecutorService pool = Executors.newFixedThreadPool(4);
            List<Future<HttpResponse<Void>>> results = new ArrayList<>();
            for (HttpRequest r : requests) {
                results.add(pool.submit(() -> http.send(r, HttpResponse.BodyHandlers.discarding())));
            }
            int unexpected = 0;
            for (Future<HttpResponse<Void>> f : results) {
                int status = f.get().statusCode();
                if (status != 401 && status != 200) {
                    unexpected++;
                }
            }
            pool.shutdown();
            log.info("Warmed up in {} ms ({} requests, {} unexpected answers)",
                    (System.nanoTime() - start) / 1_000_000, requests.size(), unexpected);
        } catch (Exception e) {
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            log.warn("Warm-up didn't finish; starting cold", e);
        } finally {
            AvailabilityChangeEvent.publish(identity, ReadinessState.ACCEPTING_TRAFFIC);
            AvailabilityChangeEvent.publish(gateway, ReadinessState.ACCEPTING_TRAFFIC);
        }
    }
}
