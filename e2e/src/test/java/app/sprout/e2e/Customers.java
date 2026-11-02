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
        // Each step waits and tries again when told to (429/503), as the web app does: with every service in its own JVM
        // on one machine, setting up dozens of customers at once briefly trips the gateway's circuit breakers.
        Client.Response bank = Client.retrying(() -> c.post("/api/bank/v1/accounts", Map.of("holderName", "Meera Iyer", "upiPin", PIN), token), false);
        assertThat(bank.status()).as(bank.body().toString()).isEqualTo(201);
        String vpa = bank.body().path("vpa").asText();
        ThreadLocalRandom r = ThreadLocalRandom.current();
        String pan = "AB" + (char) ('A' + r.nextInt(26)) + "P" + (char) ('A' + r.nextInt(26)) + String.format("%04d", r.nextInt(10_000)) + "K";
        Client.Response account = Client.retrying(() -> c.post("/api/accounts/v1/accounts", Map.of("legalName", "Meera Iyer", "dateOfBirth", "1996-08-21",
                "pan", pan, "bankVpa", vpa), token), false);
        assertThat(account.status()).as(account.body().toString()).isEqualTo(201);
        String key = UUID.randomUUID().toString();
        JsonNode d = Client.retrying(() -> c.send("POST", "/api/payments/v1/deposits", Map.of("amount", deposit.toPlainString()),
                Map.of("Authorization", "Bearer " + token, "Idempotency-Key", key)), true).body();
        // The collect request reaches the bank a moment after the deposit is made; under load, more than a moment.
        Instant asked = Instant.now().plusSeconds(15);
        JsonNode pending = c.get("/api/bank/v1/requests?status=PENDING", token).body().path("requests");
        while (pending.isEmpty() && Instant.now().isBefore(asked)) {
            Thread.sleep(250);
            pending = c.get("/api/bank/v1/requests?status=PENDING", token).body().path("requests");
        }
        assertThat(pending).as("the deposit's collect request never reached the bank").isNotEmpty();
        String request = pending.get(0).path("id").asText();
        assertThat(Client.retrying(() -> c.post("/api/bank/v1/requests/" + request + "/approve", Map.of("upiPin", PIN), token), false).status())
                .isEqualTo(200);
        Instant end = Instant.now().plusSeconds(Integer.getInteger("e2e.depositWaitSeconds", 15));
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
