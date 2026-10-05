package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The habit features through the gateway: a monthly plan whose first instalment is bought at once
 * through the real order service and exchange, the habit picture that follows from it, squads,
 * readiness and Future You.
 */
class HabitsJourneysTest {

    static final BigDecimal DEPOSIT = new BigDecimal("20000.00");
    /** A month's plan: enough for a share of INKWELL (about ₹3,650), and under ₹10,000 invested for the squad range. */
    static final String PLAN = "8000";
    final Client c = new Client();
    String token;

    @BeforeEach
    void aFundedCustomer() throws InterruptedException {
        token = Customers.funded(c, DEPOSIT);
        Customers.waitForTradingWindow(c);
    }

    JsonNode startPlan(String symbol, String amount) {
        Client.Response r = c.send("POST", "/api/plans/v1/plans", Map.of("symbol", symbol, "amount", amount, "dayOfMonth", 5, "startNow", true),
                Map.of("Authorization", "Bearer " + token, "Idempotency-Key", UUID.randomUUID().toString()));
        assertThat(r.status()).as(r.body().toString()).isEqualTo(201);
        return r.body();
    }

    /** Waits for the plan's first instalment to be decided (the plans service looks every couple of seconds). */
    JsonNode firstInstalment(JsonNode plan) throws InterruptedException {
        Instant end = Instant.now().plusSeconds(30);
        while (Instant.now().isBefore(end)) {
            JsonNode p = c.get("/api/plans/v1/plans/" + plan.path("id").asText(), token).body();
            JsonNode i = p.path("instalments");
            if (i.size() > 0 && !i.get(0).path("status").asText().equals("PLACED")) {
                return i.get(0);
            }
            Thread.sleep(500);
        }
        throw new AssertionError("no instalment within 30 s");
    }

    @Test
    @DisplayName("E2E-80 a plan started now buys its first instalment at once, through the real order service")
    void planBuysAtOnce() throws InterruptedException {
        JsonNode plan = startPlan("INKWELL", PLAN);
        JsonNode i = firstInstalment(plan);
        assertThat(i.path("status").asText()).isEqualTo("FILLED");
        long qty = i.path("quantity").asLong();
        assertThat(qty).isPositive();
        assertThat(new BigDecimal(i.path("price").asText()).multiply(BigDecimal.valueOf(qty))).isLessThanOrEqualTo(new BigDecimal(PLAN));
        JsonNode order = c.get("/api/oms/v1/orders/" + i.path("orderId").asText(), token).body();
        assertThat(order.path("tag").asText()).isEqualTo("sip:" + plan.path("id").asText());
        assertThat(order.path("product").asText()).isEqualTo("CNC");
        assertThat(c.get("/api/oms/v1/holdings", token).body().path("holdings").get(0).path("quantity").asLong()).isEqualTo(qty);
    }

    @Test
    @DisplayName("E2E-81 a plan whose amount can't buy one share skips the month and says why")
    void planTooSmall() throws InterruptedException {
        JsonNode plan = startPlan("HARBOR", "100");   // HARBOR trades well above ₹100
        JsonNode i = firstInstalment(plan);
        assertThat(i.path("status").asText()).isEqualTo("SKIPPED");
        assertThat(i.path("reason").asText()).contains("less than one share");
        Client.Response paused = c.send("POST", "/api/plans/v1/plans/" + plan.path("id").asText() + "/pause", null,
                Map.of("Authorization", "Bearer " + token));
        assertThat(paused.body().path("status").asText()).isEqualTo("PAUSED");
    }

    @Test
    @DisplayName("E2E-82 the habit picture follows from what was bought: a streak, badges, pending points")
    void habitsFollowTrading() throws InterruptedException {
        firstInstalment(startPlan("INKWELL", PLAN));
        JsonNode h = c.get("/api/habits/v1/habits/me", token).body();
        assertThat(h.path("streak").path("months").asInt()).isEqualTo(1);
        assertThat(h.path("level").path("name").asText()).isEqualTo("Seedling");
        assertThat(h.path("badges").findValuesAsText("code")).contains("FIRST_INVESTMENT", "FIRST_PLAN_INSTALMENT");
        assertThat(h.path("points").path("pending").asInt()).as("100 for the month, 50 for the instalment, 50 for the plan-on-track challenge")
                .isEqualTo(200);
        assertThat(h.path("points").path("vested").asInt()).isZero();
    }

    @Test
    @DisplayName("E2E-83 squads rank friends by the habit, and show a range only by choice")
    void squads() throws InterruptedException {
        firstInstalment(startPlan("INKWELL", PLAN));
        JsonNode squad = c.post("/api/habits/v1/squads", Map.of("name", "Monsoon savers", "nickname", "Meera"), token).body();
        String friend = Customers.funded(new Client(), new BigDecimal("1000.00"));
        Client.Response joined = c.post("/api/habits/v1/squads/join", Map.of("inviteCode", squad.path("inviteCode").asText(), "nickname", "Ravi"),
                friend);
        assertThat(joined.status()).isEqualTo(200);
        c.send("PUT", "/api/habits/v1/habits/me/privacy", Map.of("showInvestedRange", true), Map.of("Authorization", "Bearer " + token));
        JsonNode board = c.get("/api/habits/v1/squads/" + squad.path("id").asText(), friend).body().path("members");
        assertThat(board.size()).isEqualTo(2);
        assertThat(board.get(0).path("nickname").asText()).as("Meera has a streak; Ravi hasn't invested").isEqualTo("Meera");
        assertThat(board.get(0).path("investedRange").asText()).isEqualTo("under ₹10,000");
        assertThat(board.get(1).path("you").asBoolean()).isTrue();
        assertThat(board.get(1).has("investedRange")).isFalse();
    }

    @Test
    @DisplayName("E2E-84 readiness gives plain advice, and Future You shows what a monthly amount could become")
    void readinessAndFuture() {
        JsonNode r = c.send("PUT", "/api/habits/v1/readiness", Map.of("emergencyFundMonths", 1, "highInterestDebt", false, "horizonYears", 10),
                Map.of("Authorization", "Bearer " + token)).body();
        assertThat(r.path("ready").asBoolean()).isFalse();
        assertThat(r.path("advice").get(0).asText()).contains("emergency fund");
        JsonNode f = c.get("/api/habits/v1/future?monthly=1000&years=10", token).body();
        assertThat(f.path("invested").asText()).isEqualTo("120000.00");
        assertThat(f.path("rates").get(2).path("finalValue").asText()).isEqualTo("230038.69");
    }
}
