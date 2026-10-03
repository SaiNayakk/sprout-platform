# End-to-end tests

The end-to-end suite lives in [`e2e/`](https://github.com/SaiNayakk/sprout-platform/tree/main/e2e). It
talks to a running environment **only through the gateway**, exactly as a client would, so it tests
the released services together, not any one service's code.

Each case has a stable id. Ids are grouped: `0x` happy journeys, `1x` input validation, `2x` sign-in
protection, `3x` attacks and the edge.

```bash
mvn -f e2e/pom.xml test -Dsprout.baseUrl=http://localhost:8100
```

Every request comes from a random client address (in the `198.18.0.0/15` benchmarking range) so cases
don't share rate-limit buckets, and every user has a fresh email, so the suite can run against an
environment that already has data.

## Happy journeys

### E2E-01 { #e2e-01 }
**Sign up, sign in and see your account.** Create an account, sign in with the password, call
`GET /users/me` with the access token. The profile shows the account that signed up.

### E2E-02 { #e2e-02 }
**Turn on two-factor, then sign in with a code.** Start enrolment, compute a code from the returned
secret, confirm it. Signing in with the password now returns a challenge instead of tokens; answering it
with a fresh code returns tokens.

### E2E-03 { #e2e-03 }
**Refresh tokens rotate; sign out ends the session.** Refreshing returns a new access token and a new
refresh token. Signing out revokes the session: the refresh token stops working.

## Input validation

### E2E-10 { #e2e-10 }
**Duplicate email, any case or spacing, is refused.** `Ana@Example.com` and ` ana@example.com ` are the
same account: `409 EMAIL_TAKEN`.

### E2E-11 { #e2e-11 }
**Weak passwords are refused with a reason.** Too short (`short`), well known (`password123`) or one
repeated character (`aaaaaaaaaaaa`): `400 WEAK_PASSWORD` with a human reason in `detail`.

### E2E-12 { #e2e-12 }
**Malformed JSON and unknown fields are refused.** Broken JSON and unexpected fields (a client trying to
set `role`) get `400 VALIDATION_FAILED`, never a 500.

## Sign-in protection

### E2E-20 { #e2e-20 }
**Wrong password and unknown email look identical.** Same status, same code, same body, so the API
can't be used to discover who has an account.

### E2E-21 { #e2e-21 }
**Five wrong passwords lock the account, even for the right one.** Attempts one to four get `401`; the
fifth gets `423 ACCOUNT_LOCKED` with `Retry-After`, and so does the correct password straight after.

### E2E-22 { #e2e-22 }
**A two-factor code works once, and a challenge only once.** Answering the same challenge again gets
`CHALLENGE_EXPIRED`; the same code on a fresh challenge gets `INVALID_TOTP`.

## Attacks and the edge

### E2E-30 { #e2e-30 }
**A stolen refresh token, used after the owner, ends the session.** The owner refreshes (rotating the
token). The attacker then uses the old one: `REFRESH_TOKEN_REUSED`. The owner's new refresh token and
access token stop working too, because the session is ended for safety.

### E2E-31 { #e2e-31 }
**Two refreshes racing with one token: exactly one wins.** Two parallel refreshes with the same token
produce exactly one success. Marking a token used is a single atomic update, so there is no window for
both.

### E2E-32 { #e2e-32 }
**Missing, tampered and junk tokens are refused at the gateway.** No token, a token with a broken
signature, and garbage all get `401 UNAUTHENTICATED`.

### E2E-33 { #e2e-33 }
**A client can't pretend to be someone else with `X-User-Id`.** Sending another user's id in
`X-User-Id` alongside your own token still returns your own account: the gateway strips identity headers
from incoming requests and sets them only from a verified token.

### E2E-34 { #e2e-34 }
**Sign-in is rate limited per client.** Twelve sign-ins in a burst from one address: the limit is 10 a
minute, so at least two get `429`. A different address is unaffected.

### E2E-35 { #e2e-35 }
**Unknown routes, path traversal and oversized bodies are refused.** An unknown service, an encoded
`..` reaching for identity's actuator, and the gateway's own `/actuator` all get `404`; a body over 1 MB
gets `413`.

### E2E-36 { #e2e-36 }
**One request id follows a request through the gateway and identity.** A client-supplied
`X-Request-Id` comes back on the response header and in the problem body, both for an error raised by
the gateway and for one raised by identity behind it, so one id finds a request in every service's
logs.

## Results

The latest results, case by case, are in each run's evidence page under
[Evidence from runs](../reliability/runs/index.md).
