package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The public sandbox through the gateway: visitors choose who to explore as, and get an ordinary
 * signed-in session as one of the fictional customers, set up through the same flows as anyone.
 */
class SandboxJourneysTest {

    final Client c = new Client();

    /** Starts a demo in the group, waiting while the sandbox finishes setting its people up. */
    JsonNode demo(String group) throws InterruptedException {
        Instant end = Instant.now().plusSeconds(180);
        Client.Response r = null;
        while (Instant.now().isBefore(end)) {
            r = c.post("/api/sandbox/v1/demo-sessions", Map.of("group", group));
            if (r.status() == 201) {
                return r.body();
            }
            Thread.sleep(2000);
        }
        throw new AssertionError("no demo in " + group + " within 3 minutes: " + (r == null ? "" : r.body()));
    }

    @Test
    @DisplayName("E2E-100 a visitor chooses who to explore as and is signed in as them, a real customer")
    void aVisitorExploresAsAFictionalCustomer() throws InterruptedException {
        JsonNode people = c.get("/api/sandbox/v1/personas", null).body();
        assertThat(people.path("personas")).hasSize(15);
        assertThat(people.path("groups").findValuesAsText("label")).contains("Non-binary or another gender", "No preference");
        JsonNode s = demo("WOMEN");
        String token = s.path("accessToken").asText();
        assertThat(s.path("persona").path("pronouns").asText()).isNotBlank();
        assertThat(c.get("/api/identity/v1/users/me", token).body().path("displayName").asText()).isEqualTo(s.path("persona").path("name").asText());
        assertThat(c.get("/api/oms/v1/funds", token).status()).as("set up as a customer: a Sprout account with money in it").isEqualTo(200);
        assertThat(c.get("/api/payments/v1/deposits", token).body().path("deposits")).isNotEmpty();
        Client.Response twoFactor = c.post("/api/identity/v1/users/me/totp", Map.of(), token);
        assertThat(twoFactor.status()).as("a demo customer can't be locked away from the next visitor").isEqualTo(400);
    }

    @Test
    @DisplayName("E2E-101 visitors in the same group are given different people, least recently explored first")
    void visitorsAreRotatedWithinTheirGroup() throws InterruptedException {
        JsonNode first = demo("NON_BINARY_AND_OTHER");
        JsonNode second = demo("NON_BINARY_AND_OTHER");
        assertThat(second.path("persona").path("id").asText()).isNotEqualTo(first.path("persona").path("id").asText());
        assertThat(second.path("persona").path("group").asText()).isEqualTo("NON_BINARY_AND_OTHER");
        assertThat(c.post("/api/sandbox/v1/demo-sessions", Map.of("group", "SOMEONE")).status()).isEqualTo(400);
    }
}
