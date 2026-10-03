package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Identity journeys and their edge cases, end to end through the gateway against a deployed
 * environment. Each test's id matches the catalogue in docs/reliability/e2e.md.
 */
class IdentityJourneysTest {

    final Client c = new Client();

    // ── happy paths ──────────────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-01 sign up, sign in and see your account")
    void signUpSignInAndSeeAccount() {
        String email = Client.newEmail();
        assertThat(c.signUp(email, Client.PASSWORD).status()).isEqualTo(201);
        Client.Response in = c.signIn(email, Client.PASSWORD);
        assertThat(in.status()).isEqualTo(200);
        assertThat(in.body().path("status").asText()).isEqualTo("AUTHENTICATED");
        Client.Response me = c.get("/api/identity/v1/users/me", in.body().path("tokens").path("accessToken").asText());
        assertThat(me.status()).isEqualTo(200);
        assertThat(me.body().path("email").asText()).isEqualTo(email);
    }

    @Test
    @DisplayName("E2E-02 turn on two-factor, then sign in with a code")
    void twoFactorJourney() {
        String email = Client.newEmail();
        String access = c.account(email).path("accessToken").asText();
        String secret = c.post("/api/identity/v1/users/me/totp", "", access).body().path("secret").asText();
        assertThat(c.post("/api/identity/v1/users/me/totp/confirm", Map.of("code", Client.totp(secret, Instant.now())), access).status())
                .isEqualTo(204);

        Client.Response challenge = c.signIn(email, Client.PASSWORD);
        assertThat(challenge.body().path("status").asText()).isEqualTo("TOTP_REQUIRED");
        assertThat(challenge.body().has("tokens")).isFalse();

        Client.waitForNextTotpStep(); // the setup code can't be used again
        Client.Response done = c.post("/api/identity/v1/sessions/totp",
                Map.of("challengeId", challenge.body().path("challengeId").asText(), "code", Client.totp(secret, Instant.now())));
        assertThat(done.status()).isEqualTo(200);
        assertThat(done.body().path("status").asText()).isEqualTo("AUTHENTICATED");
    }

    @Test
    @DisplayName("E2E-03 refresh tokens rotate; sign out ends the session")
    void refreshThenSignOut() {
        JsonNode tokens = c.account(Client.newEmail());
        Client.Response rotated = c.post("/api/identity/v1/tokens/refresh", Map.of("refreshToken", tokens.path("refreshToken").asText()));
        assertThat(rotated.status()).isEqualTo(200);
        String access = rotated.body().path("accessToken").asText();
        assertThat(c.send("DELETE", "/api/identity/v1/sessions/current", null, Map.of("Authorization", "Bearer " + access)).status())
                .isEqualTo(204);
        assertThat(c.post("/api/identity/v1/tokens/refresh", Map.of("refreshToken", rotated.body().path("refreshToken").asText())).code())
                .isEqualTo("INVALID_REFRESH_TOKEN");
    }

    // ── edge cases: sign-up ──────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-10 duplicate email, any case or spacing, is refused")
    void duplicateEmail() {
        String email = Client.newEmail();
        c.signUp(email, Client.PASSWORD);
        Client.Response again = c.signUp("  " + email.toUpperCase() + " ", Client.PASSWORD);
        assertThat(again.status()).isEqualTo(409);
        assertThat(again.code()).isEqualTo("EMAIL_TAKEN");
    }

    @Test
    @DisplayName("E2E-11 weak passwords are refused with a reason")
    void weakPasswords() {
        for (String weak : new String[] {"short", "password123", "aaaaaaaaaaaa"}) {
            Client.Response r = c.signUp(Client.newEmail(), weak);
            assertThat(r.status()).as(weak).isEqualTo(400);
            assertThat(r.code()).isEqualTo("WEAK_PASSWORD");
            assertThat(r.body().path("detail").asText()).isNotBlank();
        }
    }

    @Test
    @DisplayName("E2E-12 malformed JSON and unknown fields are refused")
    void malformedRequests() {
        assertThat(c.post("/api/identity/v1/users", "{\"email\":").code()).isEqualTo("VALIDATION_FAILED");
        assertThat(c.post("/api/identity/v1/users", Map.of("email", Client.newEmail(), "password", Client.PASSWORD,
                "displayName", "X", "role", "admin")).code()).isEqualTo("VALIDATION_FAILED");
    }

    // ── edge cases: sign-in ──────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-20 wrong password and unknown email look identical")
    void noAccountEnumeration() {
        String email = Client.newEmail();
        c.signUp(email, Client.PASSWORD);
        Client.Response wrong = c.signIn(email, "not-the-password-1");
        Client.Response unknown = c.signIn(Client.newEmail(), Client.PASSWORD);
        assertThat(wrong.status()).isEqualTo(401).isEqualTo(unknown.status());
        assertThat(wrong.code()).isEqualTo("INVALID_CREDENTIALS").isEqualTo(unknown.code());
        assertThat(wrong.body().path("detail").asText()).isEqualTo(unknown.body().path("detail").asText());
    }

    @Test
    @DisplayName("E2E-21 five wrong passwords lock the account, even for the right one")
    void lockout() {
        String email = Client.newEmail();
        c.signUp(email, Client.PASSWORD);
        for (int i = 1; i <= 4; i++) {
            assertThat(c.signIn(email, "wrong-password-" + i).status()).isEqualTo(401);
        }
        Client.Response locked = c.signIn(email, "wrong-password-5");
        assertThat(locked.status()).isEqualTo(423);
        assertThat(locked.headers()).containsKey("retry-after");
        assertThat(c.signIn(email, Client.PASSWORD).status()).isEqualTo(423);
    }

    @Test
    @DisplayName("E2E-22 a two-factor code works once and a challenge only once")
    void totpReplay() {
        String email = Client.newEmail();
        String access = c.account(email).path("accessToken").asText();
        String secret = c.post("/api/identity/v1/users/me/totp", "", access).body().path("secret").asText();
        c.post("/api/identity/v1/users/me/totp/confirm", Map.of("code", Client.totp(secret, Instant.now())), access);
        Client.waitForNextTotpStep();
        String code = Client.totp(secret, Instant.now());

        String first = c.signIn(email, Client.PASSWORD).body().path("challengeId").asText();
        assertThat(c.post("/api/identity/v1/sessions/totp", Map.of("challengeId", first, "code", code)).status()).isEqualTo(200);
        // the same challenge again
        assertThat(c.post("/api/identity/v1/sessions/totp", Map.of("challengeId", first, "code", code)).code()).isEqualTo("CHALLENGE_EXPIRED");
        // the same code on a new challenge
        String second = c.signIn(email, Client.PASSWORD).body().path("challengeId").asText();
        assertThat(c.post("/api/identity/v1/sessions/totp", Map.of("challengeId", second, "code", code)).code()).isEqualTo("INVALID_TOTP");
    }

    // ── edge cases: tokens and the gateway ───────────────────────────────────

    @Test
    @DisplayName("E2E-30 a stolen refresh token, used after the owner, ends the session")
    void refreshReuse() {
        JsonNode tokens = c.account(Client.newEmail());
        String stolen = tokens.path("refreshToken").asText();
        JsonNode owner = c.post("/api/identity/v1/tokens/refresh", Map.of("refreshToken", stolen)).body();
        Client.Response thief = c.post("/api/identity/v1/tokens/refresh", Map.of("refreshToken", stolen));
        assertThat(thief.code()).isEqualTo("REFRESH_TOKEN_REUSED");
        // the owner's newer tokens die with the session
        assertThat(c.post("/api/identity/v1/tokens/refresh", Map.of("refreshToken", owner.path("refreshToken").asText())).status())
                .isEqualTo(401);
        assertThat(c.get("/api/identity/v1/users/me", owner.path("accessToken").asText()).status()).isEqualTo(401);
    }

    @Test
    @DisplayName("E2E-31 two refreshes racing with one token: exactly one wins")
    void refreshRace() {
        String token = c.account(Client.newEmail()).path("refreshToken").asText();
        List<CompletableFuture<Integer>> racers = new ArrayList<>();
        for (int i = 0; i < 2; i++) {
            racers.add(CompletableFuture.supplyAsync(() ->
                    c.post("/api/identity/v1/tokens/refresh", Map.of("refreshToken", token)).status()));
        }
        List<Integer> statuses = racers.stream().map(CompletableFuture::join).toList();
        assertThat(statuses).containsOnlyOnce(200);
    }

    @Test
    @DisplayName("E2E-32 missing, tampered and junk tokens are refused at the gateway")
    void badTokens() {
        String access = c.account(Client.newEmail()).path("accessToken").asText();
        String tampered = access.substring(0, access.length() - 4) + (access.endsWith("AAAA") ? "BBBB" : "AAAA");
        for (String t : new String[] {null, tampered, "junk"}) {
            Client.Response r = c.get("/api/identity/v1/users/me", t);
            assertThat(r.status()).isEqualTo(401);
            assertThat(r.code()).isEqualTo("UNAUTHENTICATED");
        }
    }

    @Test
    @DisplayName("E2E-33 a client can't pretend to be someone else with X-User-Id")
    void spoofedIdentityHeader() {
        String mine = Client.newEmail();
        String access = c.account(mine).path("accessToken").asText();
        String victimId = c.signUp(Client.newEmail(), Client.PASSWORD).body().path("id").asText();
        Client.Response me = c.send("GET", "/api/identity/v1/users/me", null,
                Map.of("Authorization", "Bearer " + access, "X-User-Id", victimId));
        assertThat(me.body().path("email").asText()).isEqualTo(mine);
    }

    @Test
    @DisplayName("E2E-34 sign-in is rate limited per client")
    void signInRateLimit() {
        Client attacker = new Client();
        int limited = 0;
        for (int i = 0; i < 12; i++) {
            if (attacker.signIn(Client.newEmail(), "guess-" + i + "-password").status() == 429) {
                limited++;
            }
        }
        assertThat(limited).as("10 a minute allowed, the rest refused").isGreaterThanOrEqualTo(2);
        // a different client is unaffected
        assertThat(new Client().signIn(Client.newEmail(), Client.PASSWORD).status()).isEqualTo(401);
    }

    @Test
    @DisplayName("E2E-35 unknown routes, path traversal and oversized bodies are refused")
    void hostileRequests() {
        assertThat(c.get("/api/nope/v1/x", null).status()).isEqualTo(404);
        assertThat(c.get("/api/identity/v1/%2e%2e/actuator/health", null).status()).isEqualTo(404);
        assertThat(c.get("/actuator/health", null).status()).isEqualTo(404);
        assertThat(c.post("/api/identity/v1/sessions", "{\"email\":\"" + "x".repeat(1_100_000) + "\"}").status()).isEqualTo(413);
    }

    @Test
    @DisplayName("E2E-36 one request id follows a request through the gateway and identity")
    void requestIdEndToEnd() {
        Client.Response r = c.send("GET", "/api/identity/v1/users/me", null, Map.of("X-Request-Id", "e2e-trace-7"));
        assertThat(r.headers().get("x-request-id")).isEqualTo("e2e-trace-7");
        assertThat(r.body().path("requestId").asText()).isEqualTo("e2e-trace-7");
        Client.Response signUp = c.send("POST", "/api/identity/v1/users", Map.of("email", "bad", "password", "x", "displayName", "x"),
                Map.of("X-Request-Id", "e2e-trace-8"));
        assertThat(signUp.body().path("requestId").asText()).as("set by identity, behind the gateway").isEqualTo("e2e-trace-8");
    }
}
