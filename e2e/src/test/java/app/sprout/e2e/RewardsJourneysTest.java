package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Rewards through the gateway: the vault spends only vested habit points, referrals reward the habit
 * rather than the sign-up, and challenges and Year Wrapped follow from what was bought.
 */
class RewardsJourneysTest {

    final Client c = new Client();

    @Test
    @DisplayName("E2E-95 the vault spends only vested points: a new investor's pending points can't buy anything yet")
    void theVaultSpendsOnlyVestedPoints() throws InterruptedException {
        String token = Customers.funded(c, new BigDecimal("5000.00"));
        Customers.waitForTradingWindow(c);
        Client.Response bought = c.send("POST", "/api/oms/v1/orders", Map.of("symbol", "KOSHA", "side", "BUY", "quantity", 2, "orderType", "MARKET",
                "product", "CNC"), Map.of("Authorization", "Bearer " + token, "Idempotency-Key", UUID.randomUUID().toString()));
        assertThat(bought.status()).isEqualTo(201);
        JsonNode v = c.get("/api/rewards/v1/vault", token).body();
        assertThat(v.path("balance").path("pending").asInt()).as("this month's 100 points wait 30 days").isGreaterThanOrEqualTo(100);
        assertThat(v.path("balance").path("available").asInt()).isZero();
        assertThat(v.path("items").findValuesAsText("brand")).allMatch(b -> b.equals("Sprout") || b.contains("(fictional)"));
        Client.Response r = c.send("POST", "/api/rewards/v1/redemptions", Map.of("itemCode", "THEME_MARIGOLD"),
                Map.of("Authorization", "Bearer " + token, "Idempotency-Key", UUID.randomUUID().toString()));
        assertThat(r.status()).isEqualTo(422);
        assertThat(r.body().path("code").asText()).isEqualTo("NOT_ENOUGH_POINTS");
    }

    @Test
    @DisplayName("E2E-96 a friend's referral code links two customers; nothing is earned until the friend invests for 3 months")
    void referralsWaitForTheHabit() throws InterruptedException {
        String asha = Customers.funded(c, new BigDecimal("1000.00"));
        String ravi = Customers.funded(new Client(), new BigDecimal("1000.00"));
        String code = c.get("/api/rewards/v1/referrals/me", asha).body().path("code").asText();
        Client.Response linked = c.post("/api/rewards/v1/referrals/claim", Map.of("code", code), ravi);
        assertThat(linked.status()).as(linked.body().toString()).isEqualTo(200);
        assertThat(linked.body().path("referredBy").asText()).isEqualTo(code);
        JsonNode mine = c.get("/api/rewards/v1/referrals/me", asha).body();
        assertThat(mine.path("friends")).hasSize(1);
        assertThat(mine.path("friends").get(0).path("rewarded").asBoolean()).isFalse();
        assertThat(mine.path("pointsEarned").asInt()).isZero();
        assertThat(c.post("/api/rewards/v1/referrals/claim", Map.of("code", code), asha).body().path("code").asText()).isEqualTo("INVALID_REFERRAL");
    }

    @Test
    @DisplayName("E2E-97 this month's challenges and the year wrapped follow from what was bought")
    void challengesAndWrappedFollowTrading() throws InterruptedException {
        String token = Customers.funded(c, new BigDecimal("5000.00"));
        Customers.waitForTradingWindow(c);
        for (String symbol : new String[] {"KOSHA", "IRONLEAF", "SUNROOT"}) {
            assertThat(c.send("POST", "/api/oms/v1/orders", Map.of("symbol", symbol, "side", "BUY", "quantity", 1, "orderType", "MARKET",
                    "product", "CNC"), Map.of("Authorization", "Bearer " + token, "Idempotency-Key", UUID.randomUUID().toString())).status())
                    .isEqualTo(201);
        }
        JsonNode ch = c.get("/api/habits/v1/challenges", token).body();
        JsonNode three = ch.path("challenges").get(3);
        assertThat(three.path("code").asText()).isEqualTo("THREE_SHARES");
        assertThat(three.path("completed").asBoolean()).isTrue();
        JsonNode w = c.get("/api/habits/v1/wrapped", token).body();
        assertThat(w.path("monthsInvested").asInt()).isEqualTo(1);
        assertThat(w.path("purchases").asInt()).isEqualTo(3);
        assertThat(w.path("differentShares").asInt()).isEqualTo(3);
        assertThat(w.path("title").asText()).isEqualTo("First Shoots");
    }
}
