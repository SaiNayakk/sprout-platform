package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ThreadLocalRandom;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Money in and out, through the gateway, the way the app and the bank page will do it: a Sprout
 * Bank account with a UPI PIN, a Sprout account, then deposits approved with the PIN and withdrawals.
 */
class MoneyJourneysTest {

    static final String PIN = "2580";
    final Client c = new Client();
    String token;
    String vpa;

    @BeforeEach
    void customerWithBankAndSproutAccounts() {
        token = c.account(Client.newEmail()).path("accessToken").asText();
        Client.Response bank = c.post("/api/bank/v1/accounts", Map.of("holderName", "Asha Rao", "upiPin", PIN), token);
        assertThat(bank.status()).isEqualTo(201);
        vpa = bank.body().path("vpa").asText();
        Client.Response acct = c.post("/api/accounts/v1/accounts", Map.of("legalName", "Asha Rao", "dateOfBirth", "1999-04-12",
                "pan", pan(), "bankVpa", vpa), token);
        assertThat(acct.status()).as(acct.body().toString()).isEqualTo(201);
    }

    static String pan() {
        ThreadLocalRandom r = ThreadLocalRandom.current();
        return "AB" + (char) ('A' + r.nextInt(26)) + "P" + (char) ('A' + r.nextInt(26)) + String.format("%04d", r.nextInt(10_000)) + "K";
    }

    Client.Response pay(String path, String amount, String key) {
        return c.send("POST", path, Map.of("amount", amount), Map.of("Authorization", "Bearer " + token, "Idempotency-Key", key));
    }

    JsonNode deposit(String amount) {
        Client.Response r = pay("/api/payments/v1/deposits", amount, UUID.randomUUID().toString());
        assertThat(r.status()).isEqualTo(201);
        return r.body();
    }

    JsonNode pending() {
        JsonNode reqs = c.get("/api/bank/v1/requests?status=PENDING", token).body().path("requests");
        assertThat(reqs.size()).isGreaterThan(0);
        return reqs.get(0);
    }

    Client.Response approve(String requestId, String pin) {
        return c.post("/api/bank/v1/requests/" + requestId + "/approve", Map.of("upiPin", pin), token);
    }

    String depositStatus(JsonNode d, String waitWhile, Duration timeout) throws InterruptedException {
        Instant end = Instant.now().plus(timeout);
        String status;
        do {
            status = c.get("/api/payments/v1/deposits/" + d.path("id").asText(), token).body().path("status").asText();
            if (!status.equals(waitWhile)) {
                return status;
            }
            Thread.sleep(250);
        } while (Instant.now().isBefore(end));
        return status;
    }

    String available() {
        return c.get("/api/payments/v1/balance", token).body().path("available").asText();
    }

    String bankBalance() {
        return c.get("/api/bank/v1/accounts/me", token).body().path("balance").asText();
    }

    void funded(String amount) throws InterruptedException {
        JsonNode d = deposit(amount);
        assertThat(approve(pending().path("id").asText(), PIN).status()).isEqualTo(200);
        assertThat(depositStatus(d, "AWAITING_APPROVAL", Duration.ofSeconds(15))).isEqualTo("COMPLETED");
    }

    @Test
    @DisplayName("E2E-50 open a bank account with a UPI PIN, then a Sprout account linked to it")
    void onboarding() {
        assertThat(bankBalance()).isEqualTo("100000.00");
        JsonNode me = c.get("/api/accounts/v1/accounts/me", token).body();
        assertThat(me.path("status").asText()).isEqualTo("ACTIVE");
        assertThat(me.path("bankVpa").asText()).isEqualTo(vpa);
        assertThat(me.path("panMasked").asText()).startsWith("XXXXX");
        assertThat(available()).isEqualTo("0.00");
    }

    @Test
    @DisplayName("E2E-51 KYC refuses the underage, business PANs, unknown UPI addresses and a second account per PAN")
    void kycRefusals() {
        String other = new Client().account(Client.newEmail()).path("accessToken").asText();
        String usedPan = pan();
        Map<String, Object> ok = Map.of("legalName", "Ravi Kumar", "dateOfBirth", "1990-01-01", "pan", usedPan, "bankVpa", vpa);
        assertThat(c.post("/api/accounts/v1/accounts", Map.of("legalName", "Ravi Kumar", "dateOfBirth", "2015-01-01", "pan", pan(), "bankVpa", vpa), other)
                .code()).isEqualTo("KYC_REJECTED");
        assertThat(c.post("/api/accounts/v1/accounts", Map.of("legalName", "Ravi Kumar", "dateOfBirth", "1990-01-01", "pan", "ABCCR1234K", "bankVpa", vpa), other)
                .code()).isEqualTo("KYC_REJECTED");
        assertThat(c.post("/api/accounts/v1/accounts", Map.of("legalName", "Ravi Kumar", "dateOfBirth", "1990-01-01", "pan", pan(), "bankVpa", "nobody@sproutbank"), other)
                .code()).isEqualTo("VPA_NOT_FOUND");
        assertThat(c.post("/api/accounts/v1/accounts", ok, other).status()).isEqualTo(201);
        String third = new Client().account(Client.newEmail()).path("accessToken").asText();
        assertThat(c.post("/api/accounts/v1/accounts", ok, third).code()).isEqualTo("PAN_IN_USE");
    }

    @Test
    @DisplayName("E2E-52 add money: approved in the bank with the PIN, it arrives in Sprout")
    void addMoney() throws InterruptedException {
        JsonNode d = deposit("2500.50");
        assertThat(d.path("status").asText()).isEqualTo("AWAITING_APPROVAL");
        JsonNode req = pending();
        assertThat(req.path("amount").asText()).isEqualTo("2500.50");
        assertThat(req.path("payeeName").asText()).isEqualTo("Sprout Investments");
        assertThat(approve(req.path("id").asText(), PIN).status()).isEqualTo(200);
        assertThat(depositStatus(d, "AWAITING_APPROVAL", Duration.ofSeconds(15))).isEqualTo("COMPLETED");
        assertThat(available()).isEqualTo("2500.50");
        assertThat(bankBalance()).isEqualTo("97499.50");
    }

    @Test
    @DisplayName("E2E-53 wrong PINs count down; declining ends the deposit; nothing moves")
    void wrongPinThenDecline() throws InterruptedException {
        JsonNode d = deposit("100");
        String id = pending().path("id").asText();
        Client.Response wrong = approve(id, "1357");
        assertThat(wrong.code()).isEqualTo("INVALID_PIN");
        assertThat(wrong.body().path("attemptsLeft").asInt()).isEqualTo(2);
        assertThat(c.post("/api/bank/v1/requests/" + id + "/decline", Map.of(), token).status()).isEqualTo(200);
        assertThat(depositStatus(d, "AWAITING_APPROVAL", Duration.ofSeconds(15))).isEqualTo("DECLINED");
        assertThat(available()).isEqualTo("0.00");
        assertThat(bankBalance()).isEqualTo("100000.00");
    }

    @Test
    @DisplayName("E2E-54 retrying with the same Idempotency-Key makes one deposit and one bank request")
    void idempotentDeposits() {
        String key = UUID.randomUUID().toString();
        Client.Response first = pay("/api/payments/v1/deposits", "50", key);
        Client.Response again = pay("/api/payments/v1/deposits", "50", key);
        assertThat(first.status()).isEqualTo(201);
        assertThat(again.status()).isEqualTo(200);
        assertThat(again.body().path("id").asText()).isEqualTo(first.body().path("id").asText());
        assertThat(c.get("/api/bank/v1/requests?status=PENDING", token).body().path("requests").size()).isEqualTo(1);
    }

    @Test
    @DisplayName("E2E-55 withdraw: never more than you have; what you take arrives in the bank")
    void withdraw() throws InterruptedException {
        assertThat(pay("/api/payments/v1/withdrawals", "1", UUID.randomUUID().toString()).code()).isEqualTo("INSUFFICIENT_FUNDS");
        funded("800");
        assertThat(pay("/api/payments/v1/withdrawals", "800.01", UUID.randomUUID().toString()).code()).isEqualTo("INSUFFICIENT_FUNDS");
        Client.Response w = pay("/api/payments/v1/withdrawals", "300.25", UUID.randomUUID().toString());
        assertThat(w.status()).isEqualTo(201);
        assertThat(w.body().path("status").asText()).isEqualTo("COMPLETED");
        assertThat(available()).isEqualTo("499.75");
        assertThat(bankBalance()).isEqualTo("99500.25");
    }

    @Test
    @DisplayName("E2E-56 ten withdrawals racing for money that covers five: exactly five succeed")
    void racingWithdrawals() throws InterruptedException {
        funded("500");
        List<CompletableFuture<Integer>> racers = new ArrayList<>();
        for (int i = 0; i < 10; i++) {
            racers.add(CompletableFuture.supplyAsync(() -> pay("/api/payments/v1/withdrawals", "100", UUID.randomUUID().toString()).status()));
        }
        List<Integer> statuses = racers.stream().map(CompletableFuture::join).toList();
        assertThat(statuses.stream().filter(s -> s == 201).count()).isEqualTo(5);
        assertThat(statuses.stream().filter(s -> s == 422).count()).isEqualTo(5);
        assertThat(available()).isEqualTo("0.00");
    }

    @Test
    @DisplayName("E2E-57 a forged bank callback is refused")
    void forgedCallback() {
        JsonNode d = deposit("10");
        Client.Response forged = c.send("POST", "/api/payments/internal/v1/bank-events",
                Map.of("eventId", UUID.randomUUID().toString(), "type", "COLLECT_APPROVED", "requestId", UUID.randomUUID().toString(),
                        "reference", d.path("id").asText(), "amount", "10.00", "occurredAt", "2026-10-05T00:00:00Z"),
                Map.of("Authorization", "Bearer " + token, "X-Bank-Signature", "sha256=" + "0".repeat(64)));
        assertThat(forged.code()).isEqualTo("INVALID_SIGNATURE");
        assertThat(available()).isEqualTo("0.00");
    }

    @Test
    @DisplayName("E2E-58 nobody else can see my payments or approve my bank requests")
    void strangers() {
        JsonNode d = deposit("10");
        String requestId = pending().path("id").asText();
        String stranger = new Client().account(Client.newEmail()).path("accessToken").asText();
        new Client().post("/api/bank/v1/accounts", Map.of("holderName", "Stranger", "upiPin", "8642"), stranger);
        assertThat(c.get("/api/payments/v1/deposits/" + d.path("id").asText(), stranger).status()).isIn(404);
        assertThat(c.post("/api/bank/v1/requests/" + requestId + "/approve", Map.of("upiPin", "8642"), stranger).status()).isEqualTo(404);
    }

    @Test
    @DisplayName("E2E-59 an unanswered payment request expires, and so does the deposit")
    void expiry() throws InterruptedException {
        JsonNode d = deposit("20");
        // pre-prod's bank lets requests wait 30 s
        assertThat(depositStatus(d, "AWAITING_APPROVAL", Duration.ofSeconds(60))).isEqualTo("EXPIRED");
        assertThat(available()).isEqualTo("0.00");
    }
}
