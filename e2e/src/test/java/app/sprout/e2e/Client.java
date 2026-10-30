package app.sprout.e2e;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** A client of the deployed system, talking to the gateway like a browser or app would. */
final class Client {

    static final String BASE = System.getProperty("sprout.baseUrl", "http://localhost:8100");
    static final ObjectMapper JSON = new ObjectMapper();
    static final String PASSWORD = "monsoon-mango-42";

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    /** Each test is its own "visitor": the gateway rate-limits per client address. */
    final String clientIp = "198.18." + ThreadLocalRandom.current().nextInt(0, 256) + "." + ThreadLocalRandom.current().nextInt(1, 255);

    record Response(int status, JsonNode body, Map<String, String> headers) {
        String code() {
            return body.path("code").asText();
        }
    }

    Response send(String method, String path, Object body, Map<String, String> headers) {
        try {
            HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(BASE + path)).timeout(Duration.ofSeconds(15))
                    .header("CF-Connecting-IP", clientIp);
            if (body != null) {
                b.header("Content-Type", "application/json")
                        .method(method, HttpRequest.BodyPublishers.ofString(body instanceof String s ? s : JSON.writeValueAsString(body)));
            } else {
                b.method(method, HttpRequest.BodyPublishers.noBody());
            }
            headers.forEach(b::header);
            HttpResponse<String> res = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
            Map<String, String> hs = new LinkedHashMap<>();
            res.headers().map().forEach((k, v) -> hs.put(k.toLowerCase(), String.join(",", v)));
            JsonNode json = res.body().isBlank() ? JSON.nullNode() : JSON.readTree(res.body());
            return new Response(res.statusCode(), json, hs);
        } catch (Exception e) {
            throw new IllegalStateException(method + " " + path + " failed: " + e, e);
        }
    }

    Response post(String path, Object body) {
        return send("POST", path, body, Map.of());
    }

    Response post(String path, Object body, String accessToken) {
        return send("POST", path, body, Map.of("Authorization", "Bearer " + accessToken));
    }

    Response get(String path, String accessToken) {
        return send("GET", path, null, accessToken == null ? Map.of() : Map.of("Authorization", "Bearer " + accessToken));
    }

    // ── identity shortcuts ───────────────────────────────────────────────────

    static String newEmail() {
        return "e2e-" + UUID.randomUUID() + "@example.com";
    }

    Response signUp(String email, String password) {
        return post("/api/identity/v1/users", Map.of("email", email, "password", password, "displayName", "E2E"));
    }

    Response signIn(String email, String password) {
        return post("/api/identity/v1/sessions", Map.of("email", email, "password", password));
    }

    /**
     * Signs up and signs in; returns the token pair. A step that is told to wait (429, or a 503/504 while identity
     * is busy hashing passwords for many sign-ups at once) waits and tries again; any other failure fails here,
     * rather than handing back an empty token that only fails, misleadingly as a 401, on the next call.
     */
    JsonNode account(String email) {
        Response up = retrying(() -> signUp(email, PASSWORD));
        if (up.status() != 409) {   // the address is new to this run: 409 means a try that timed out did create it
            expect(up, 201, "sign-up");
        }
        return expect(retrying(() -> signIn(email, PASSWORD)), 200, "sign-in").body().path("tokens");
    }

    private static Response retrying(java.util.function.Supplier<Response> call) {
        Response r = call.get();
        for (int tries = 0; tries < 8 && (r.status() == 429 || r.status() == 503 || r.status() == 504); tries++) {
            System.out.println("E2E-RETRY " + r.status() + " " + r.code());
            try {
                Thread.sleep(1_000L << Math.min(tries, 4));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return r;
            }
            r = call.get();
        }
        return r;
    }

    private static Response expect(Response r, int status, String step) {
        if (r.status() != status) {
            throw new AssertionError(step + " answered " + r.status() + ": " + r.body());
        }
        return r;
    }

    // ── TOTP for the test's authenticator app ────────────────────────────────

    static String totp(String base32Secret, Instant at) {
        try {
            Mac mac = Mac.getInstance("HmacSHA1");
            mac.init(new SecretKeySpec(base32(base32Secret), "HmacSHA1"));
            byte[] h = mac.doFinal(ByteBuffer.allocate(8).putLong(at.getEpochSecond() / 30).array());
            int o = h[h.length - 1] & 0x0f;
            int bin = ((h[o] & 0x7f) << 24) | ((h[o + 1] & 0xff) << 16) | ((h[o + 2] & 0xff) << 8) | (h[o + 3] & 0xff);
            return String.format("%06d", bin % 1_000_000);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /** Sleeps until the next 30-second TOTP step begins, so a fresh code is available. */
    static void waitForNextTotpStep() {
        long now = System.currentTimeMillis();
        long next = (now / 30_000 + 1) * 30_000 + 1_000;
        try {
            Thread.sleep(next - now);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static byte[] base32(String s) {
        String alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
        ByteBuffer out = ByteBuffer.allocate(s.length() * 5 / 8);
        int buffer = 0, bits = 0;
        for (char c : s.toCharArray()) {
            buffer = (buffer << 5) | alphabet.indexOf(c);
            bits += 5;
            if (bits >= 8) {
                out.put((byte) ((buffer >> (bits - 8)) & 0xff));
                bits -= 8;
            }
        }
        return out.array();
    }
}
