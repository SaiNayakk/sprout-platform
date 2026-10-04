package app.sprout.e2e;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * A Server-Sent Events client, as a browser's would be: opens the stream through the gateway and
 * collects events on a background thread until closed.
 */
final class EventStream implements AutoCloseable {

    record Event(String name, JsonNode data, Instant receivedAt) {}

    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

    final int status;
    final JsonNode error;
    final List<Event> events = new CopyOnWriteArrayList<>();
    private final InputStream body;

    private EventStream(int status, JsonNode error, InputStream body) {
        this.status = status;
        this.error = error;
        this.body = body;
    }

    static EventStream open(String query, String accessToken, String clientIp) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(Client.BASE + "/api/marketdata/v1/stream?" + query))
                .header("Accept", "text/event-stream").header("CF-Connecting-IP", clientIp);
        if (accessToken != null) {
            b.header("Authorization", "Bearer " + accessToken);
        }
        HttpResponse<InputStream> res = HTTP.send(b.build(), HttpResponse.BodyHandlers.ofInputStream());
        if (res.statusCode() != 200) {
            try (InputStream in = res.body()) {
                return new EventStream(res.statusCode(), Client.JSON.readTree(in), null);
            }
        }
        EventStream s = new EventStream(200, null, res.body());
        Thread.ofVirtual().start(s::read);
        return s;
    }

    private void read() {
        try (BufferedReader in = new BufferedReader(new InputStreamReader(body, StandardCharsets.UTF_8))) {
            String name = null;
            String line;
            while ((line = in.readLine()) != null) {
                if (line.startsWith("event:")) {
                    name = line.substring(6).trim();
                } else if (line.startsWith("data:") && name != null) {
                    events.add(new Event(name, Client.JSON.readTree(line.substring(5)), Instant.now()));
                    name = null;
                }
            }
        } catch (Exception e) {
            // closed by the test, or by the server
        }
    }

    List<Event> named(String name) {
        return events.stream().filter(e -> e.name().equals(name)).toList();
    }

    /** Waits until at least {@code n} events called {@code name} have arrived, or the timeout. */
    List<Event> await(String name, int n, Duration timeout) throws InterruptedException {
        Instant end = Instant.now().plus(timeout);
        while (named(name).size() < n && Instant.now().isBefore(end)) {
            Thread.sleep(50);
        }
        return named(name);
    }

    @Override
    public void close() throws Exception {
        if (body != null) {
            body.close();
        }
    }
}
