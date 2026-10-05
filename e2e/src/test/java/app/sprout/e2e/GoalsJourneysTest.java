package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.function.Predicate;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Goals through the gateway: AutoPay asked for by Sprout and approved in Sprout Bank with the PIN, a pot
 * buying its share through the real order service, and round-ups: a UPI spend at a merchant, shared by
 * the bank, rounded up, swept under AutoPay and invested in the pot.
 */
class GoalsJourneysTest {

    static final BigDecimal DEPOSIT = new BigDecimal("20000.00");
    final Client c = new Client();
    String token;

    @BeforeEach
    void aFundedCustomer() throws InterruptedException {
        token = Customers.funded(c, DEPOSIT);
    }

    Map<String, String> auth() {
        return Map.of("Authorization", "Bearer " + token, "Idempotency-Key", UUID.randomUUID().toString());
    }

    /** Asks for AutoPay and approves it in the bank with the PIN; waits until payments has heard. */
    void autoPay() throws InterruptedException {
        Client.Response asked = c.send("POST", "/api/payments/v1/mandates", Map.of("maxAmount", "500"), auth());
        assertThat(asked.status()).as(asked.body().toString()).isEqualTo(201);
        assertThat(asked.body().path("status").asText()).isEqualTo("AWAITING_APPROVAL");
        JsonNode pending = c.get("/api/bank/v1/mandates?status=PENDING", token).body().path("mandates").get(0);
        assertThat(pending.path("purpose").asText()).contains("Round-ups");
        assertThat(pending.path("shareSpends").asBoolean()).as("the customer sees spends will be shared").isTrue();
        assertThat(c.post("/api/bank/v1/mandates/" + pending.path("id").asText() + "/approve", Map.of("upiPin", Customers.PIN), token).status())
                .isEqualTo(200);
        waitFor("AutoPay active", () -> c.get("/api/payments/v1/mandates/me", token).body(), m -> m.path("status").asText().equals("ACTIVE"));
    }

    JsonNode pot(String symbol, String target) {
        Client.Response r = c.post("/api/goals/v1/pots", Map.of("name", "Goa trip", "target", target, "symbol", symbol), token);
        assertThat(r.status()).as(r.body().toString()).isEqualTo(201);
        return r.body();
    }

    JsonNode show(JsonNode pot) {
        return c.get("/api/goals/v1/pots/" + pot.path("id").asText(), token).body();
    }

    JsonNode pay(String merchant, String amount, String pin) {
        return c.post("/api/bank/v1/payments", Map.of("payeeVpa", merchant, "amount", amount, "upiPin", pin), token).body();
    }

    static JsonNode waitFor(String what, java.util.function.Supplier<JsonNode> read, Predicate<JsonNode> done) throws InterruptedException {
        Instant end = Instant.now().plusSeconds(45);
        JsonNode last = null;
        while (Instant.now().isBefore(end)) {
            last = read.get();
            if (done.test(last)) {
                return last;
            }
            Thread.sleep(500);
        }
        throw new AssertionError(what + " didn't happen within 45 s; last: " + last);
    }

    @Test
    @DisplayName("E2E-90 AutoPay is asked for by Sprout and approved once in Sprout Bank with the PIN")
    void autoPayIsApprovedInTheBank() throws InterruptedException {
        autoPay();
        JsonNode r = c.get("/api/goals/v1/round-ups", token).body();
        assertThat(r.path("autoPay").asText()).isEqualTo("ACTIVE");
    }

    @Test
    @DisplayName("E2E-91 money put in a pot buys whole shares of its share, tagged with the pot")
    void aPotBuysItsShare() throws InterruptedException {
        Customers.waitForTradingWindow(c);
        JsonNode p = pot("KOSHA", "10000");
        Client.Response put = c.send("POST", "/api/goals/v1/pots/" + p.path("id").asText() + "/contributions", Map.of("amount", "2000"), auth());
        assertThat(put.status()).as(put.body().toString()).isEqualTo(201);
        JsonNode shown = waitFor("the pot's share bought", () -> show(p), x -> x.path("quantity").asInt() > 0);
        JsonNode buy = shown.path("movements").get(0);
        assertThat(buy.path("kind").asText()).isEqualTo("PURCHASE");
        assertThat(new BigDecimal(shown.path("invested").asText())).isLessThanOrEqualTo(new BigDecimal("2000"));
        JsonNode order = c.get("/api/oms/v1/orders/" + buy.path("orderId").asText(), token).body();
        assertThat(order.path("tag").asText()).isEqualTo("goal:" + p.path("id").asText());
        assertThat(c.get("/api/oms/v1/holdings", token).body().path("holdings").get(0).path("quantity").asInt())
                .isEqualTo(shown.path("quantity").asInt());
        Client.Response tooMuch = c.send("POST", "/api/goals/v1/pots/" + p.path("id").asText() + "/contributions", Map.of("amount", "50000"), auth());
        assertThat(tooMuch.body().path("code").asText()).isEqualTo("INSUFFICIENT_FUNDS");
    }

    @Test
    @DisplayName("E2E-92 a UPI spend is rounded up, swept under AutoPay into the pot, and invested")
    void roundUpsAreSweptAndInvested() throws InterruptedException {
        autoPay();
        JsonNode p = pot("KOSHA", "25000");
        assertThat(c.send("PUT", "/api/goals/v1/round-ups", Map.of("enabled", true, "roundTo", 100, "multiplier", 3, "potId", p.path("id").asText()),
                Map.of("Authorization", "Bearer " + token)).status()).isEqualTo(200);
        BigDecimal before = new BigDecimal(c.get("/api/bank/v1/accounts/me", token).body().path("balance").asText());
        JsonNode spent = pay("kiranacorner@sproutbank", "701.00", Customers.PIN);
        assertThat(spent.path("description").asText()).contains("Kirana Corner");
        JsonNode r = waitFor("round-ups swept", () -> c.get("/api/goals/v1/round-ups", token).body(),
                x -> x.path("swept").asText().equals("297.00"));
        assertThat(r.path("recent").get(0).path("spent").asText()).isEqualTo("701.00");
        assertThat(r.path("recent").get(0).path("amount").asText()).as("₹99 up to ₹800, three times").isEqualTo("297.00");
        assertThat(show(p).path("saved").asText()).isEqualTo("297.00");
        BigDecimal after = new BigDecimal(c.get("/api/bank/v1/accounts/me", token).body().path("balance").asText());
        assertThat(before.subtract(after)).as("the spend and the round-up, taken once each").isEqualByComparingTo("998.00");
    }

    @Test
    @DisplayName("E2E-93 without AutoPay, spends aren't shared and nothing is taken")
    void withoutAutoPayNothingIsTaken() {
        JsonNode p = pot("KOSHA", "25000");
        c.send("PUT", "/api/goals/v1/round-ups", Map.of("enabled", true, "potId", p.path("id").asText()), Map.of("Authorization", "Bearer " + token));
        pay("monsoonchai@sproutbank", "46.00", Customers.PIN);
        JsonNode r = c.get("/api/goals/v1/round-ups", token).body();
        assertThat(r.path("autoPay").asText()).isEqualTo("NONE");
        assertThat(r.path("waiting").asText()).isEqualTo("0.00");
    }

    @Test
    @DisplayName("E2E-94 a UPI payment with the wrong PIN is refused and moves nothing")
    void aWrongPinMovesNothing() {
        String balance = c.get("/api/bank/v1/accounts/me", token).body().path("balance").asText();
        JsonNode refused = pay("bookworm@sproutbank", "399.00", "1397");
        assertThat(refused.path("code").asText()).isEqualTo("INVALID_PIN");
        assertThat(c.get("/api/bank/v1/accounts/me", token).body().path("balance").asText()).isEqualTo(balance);
    }
}
