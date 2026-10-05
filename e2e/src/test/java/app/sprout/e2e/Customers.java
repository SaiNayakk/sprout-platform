package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

/** Customers the journeys start from, made the way a real one is: through the gateway, step by step. */
final class Customers {

    static final String PIN = "2580";

    private Customers() {}

    /**
     * Signs up, opens a Sprout Bank account (UPI PIN set) and a Sprout account linked to it, and adds
     * {@code deposit} by a collect request approved with the PIN. Returns the access token.
     */
    static String funded(Client c, BigDecimal deposit) throws InterruptedException {
        String token = c.account(Client.newEmail()).path("accessToken").asText();
        String vpa = c.post("/api/bank/v1/accounts", Map.of("holderName", "Meera Iyer", "upiPin", PIN), token).body().path("vpa").asText();
        ThreadLocalRandom r = ThreadLocalRandom.current();
        String pan = "AB" + (char) ('A' + r.nextInt(26)) + "P" + (char) ('A' + r.nextInt(26)) + String.format("%04d", r.nextInt(10_000)) + "K";
        assertThat(c.post("/api/accounts/v1/accounts", Map.of("legalName", "Meera Iyer", "dateOfBirth", "1996-08-21", "pan", pan,
                "bankVpa", vpa), token).status()).isEqualTo(201);
        JsonNode d = c.send("POST", "/api/payments/v1/deposits", Map.of("amount", deposit.toPlainString()),
                Map.of("Authorization", "Bearer " + token, "Idempotency-Key", UUID.randomUUID().toString())).body();
        String request = c.get("/api/bank/v1/requests?status=PENDING", token).body().path("requests").get(0).path("id").asText();
        assertThat(c.post("/api/bank/v1/requests/" + request + "/approve", Map.of("upiPin", PIN), token).status()).isEqualTo(200);
        Instant end = Instant.now().plusSeconds(15);
        while (!c.get("/api/payments/v1/deposits/" + d.path("id").asText(), token).body().path("status").asText().equals("COMPLETED")
                && Instant.now().isBefore(end)) {
            Thread.sleep(250);
        }
        assertThat(new BigDecimal(c.get("/api/oms/v1/funds", token).body().path("cash").asText())).isEqualByComparingTo(deposit);
        return token;
    }

    /** Waits until the market is open and not in its last half hour (intraday positions close at 15:20). */
    static void waitForTradingWindow(Client c) throws InterruptedException {
        Instant end = Instant.now().plus(Duration.ofMinutes(3));
        while (Instant.now().isBefore(end)) {
            JsonNode m = c.get("/api/marketdata/v1/market", null).body();
            LocalTime t = OffsetDateTime.parse(m.path("marketTime").asText()).toLocalTime();
            if (m.path("state").asText().equals("OPEN") && t.isBefore(LocalTime.of(15, 0))) {
                return;
            }
            Thread.sleep(500);
        }
        throw new AssertionError("the market didn't reach trading hours in 3 minutes");
    }
}
