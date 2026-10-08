package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The public sandbox through the gateway: a visitor types what to call them and gets an ordinary
 * signed-in session in a demo account of their own, set up and living through the same flows as anyone.
 */
class SandboxJourneysTest {

    final Client c = new Client();

    /** Starts a demo called {@code name}, waiting while the sandbox finishes setting its first accounts up. */
    JsonNode demo(String name) throws InterruptedException {
        Instant end = Instant.now().plusSeconds(180);
        Client.Response r = null;
        while (Instant.now().isBefore(end)) {
            r = c.post("/api/sandbox/v3/demo-sessions", Map.of("name", name));
            if (r.status() == 201) {
                return r.body();
            }
            Thread.sleep(2000);
        }
        throw new AssertionError("no demo account within 3 minutes: " + (r == null ? "" : r.body()));
    }

    @Test
    @DisplayName("E2E-100 a visitor names themselves and is signed in to a demo account of their own, a real customer")
    void aVisitorGetsADemoAccountOfTheirOwn() throws InterruptedException {
        assertThat(c.get("/api/sandbox/v3/demo", null).body().path("endsAfterMinutes").asInt()).isPositive();
        JsonNode s = demo("Asha");
        String token = s.path("accessToken").asText();
        assertThat(s.path("name").asText()).isEqualTo("Asha");
        assertThat(Instant.parse(s.path("endsAt").asText())).isAfter(Instant.now().plus(Duration.ofMinutes(30)));
        assertThat(c.get("/api/identity/v1/users/me", token).body().path("displayName").asText()).as("called as they asked").isEqualTo("Asha");
        assertThat(c.get("/api/oms/v1/funds", token).status()).as("set up as a customer: a Sprout account with money in it").isEqualTo(200);
        assertThat(c.get("/api/payments/v1/deposits", token).body().path("deposits")).isNotEmpty();
        assertThat(c.get("/api/goals/v1/pots", token).body().path("pots").findValuesAsText("name")).contains("Holiday fund");
        Client.Response twoFactor = c.post("/api/identity/v1/users/me/totp", Map.of(), token);
        assertThat(twoFactor.status()).as("a demo account can't be locked away by two-factor").isEqualTo(400);
    }

    @Test
    @DisplayName("E2E-101 two visitors get two different accounts, and a name that isn't one is refused")
    void eachVisitorGetsTheirOwn() throws InterruptedException {
        JsonNode first = demo("Ravi");
        JsonNode second = demo("Sam");
        String a = c.get("/api/identity/v1/users/me", first.path("accessToken").asText()).body().path("id").asText();
        String b = c.get("/api/identity/v1/users/me", second.path("accessToken").asText()).body().path("id").asText();
        assertThat(b).as("nobody shares an account").isNotEqualTo(a);
        // while the sandbox was still setting accounts up its "not yet" answers (503) can open the gateway's circuit breaker
        // for the route for a few seconds; a bad name must then be answered by the sandbox itself
        Client.Response bad = c.post("/api/sandbox/v3/demo-sessions", Map.of("name", "<script>"));
        for (int i = 0; i < 20 && bad.status() == 503; i++) {
            Thread.sleep(2000);
            bad = c.post("/api/sandbox/v3/demo-sessions", Map.of("name", "<script>"));
        }
        assertThat(bad.status()).isEqualTo(400);
    }
}
