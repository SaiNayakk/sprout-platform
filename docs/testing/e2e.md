# End-to-end tests

The end-to-end suite lives in [`e2e/`](https://github.com/SaiNayakk/sprout-platform/tree/main/e2e). It
talks to a running environment **only through the gateway**, exactly as a client would, so it tests
the released services together, not any one service's code.

Each case has a stable id. Ids are grouped: `0x` happy journeys, `1x` input validation, `2x` sign-in
protection, `3x` attacks and the edge, `4x` market data, `5x` money.

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

## Market data

The market in pre-prod runs 30 times faster than real time, so a whole trading day, its close and the
next morning all happen within a run. These cases are written to pass at any moment of that day:
the market may be open, closed, or between sessions when they run.

### E2E-40 { #e2e-40 }
**The market and its instruments are visible before signing in.** `GET /v1/market` says the mode is
`SYNTHETIC` and that the prices aren't real; the instrument list includes at least one index, and an
index is never tradable.

### E2E-41 { #e2e-41 }
**Prices need a signed-in user.** Quotes and candles without a token get `401 UNAUTHENTICATED` at the
gateway.

### E2E-42 { #e2e-42 }
**Quotes come back in the order asked; unknown symbols are named.** Lower-case symbols are accepted;
each quote's last price lies between its day's low and high. Asking for a symbol that doesn't exist
gets `404 UNKNOWN_INSTRUMENT`, and the detail names it.

### E2E-43 { #e2e-43 }
**Candles never show the future.** Every complete one-minute candle ended at or before the market
time, at most one candle is still forming, and the daily history ends at the session being shown.

### E2E-44 { #e2e-44 }
**The price stream starts with the current state, then ticks live with rising `seq`.** Through the
gateway: a `market` event, a `quote` per symbol, then at least 40 ticks. Each tick's `seq` is higher
than the last one for its symbol (and than the opening quote's), and the ticks arrive spread over
time, not in one batch.

### E2E-45 { #e2e-45 }
**Every streamed price lies inside its minute's high and low.** Ticks collected from the stream are
checked against the one-minute candles published afterwards: the live feed and the history agree.

### E2E-46 { #e2e-46 }
**One client can hold at most five price streams.** The sixth gets `429 RATE_LIMITED`.

### E2E-47 { #e2e-47 }
**A bad stream request is refused before it starts.** An unknown symbol gets `404`, more than 50
symbols `400`, and no token `401`, each as a normal JSON problem rather than a broken stream.

## Money

Each case starts with a new customer who has a Sprout Bank account (UPI PIN set) and a Sprout account
linked to it. Pre-prod's bank lets payment requests wait 30 seconds before they expire.

### E2E-50 { #e2e-50 }
**Open a bank account with a UPI PIN, then a Sprout account linked to it.** The bank account starts with
₹1,00,000 of pretend money; the Sprout account is `ACTIVE`, shows the PAN only masked, has no money yet,
and has a demat account at the depository.

### E2E-51 { #e2e-51 }
**KYC refuses the underage, business PANs, unknown UPI addresses and a second account per PAN.**

### E2E-52 { #e2e-52 }
**Add money: approved in the bank with the PIN, it arrives in Sprout.** The deposit waits, the bank shows a
request from "Sprout Investments", the customer approves it with the PIN, and the deposit completes: Sprout
cash up by exactly the amount, the bank balance down by exactly the amount.

### E2E-53 { #e2e-53 }
**Wrong PINs count down; declining ends the deposit; nothing moves.**

### E2E-54 { #e2e-54 }
**Retrying with the same `Idempotency-Key` makes one deposit and one bank request.**

### E2E-55 { #e2e-55 }
**Withdraw: never more than you have; what you take arrives in the bank.**

### E2E-56 { #e2e-56 }
**Ten withdrawals racing for money that covers five: exactly five succeed.** The ledger's locking means no
money is ever spent twice, however the requests interleave.

### E2E-57 { #e2e-57 }
**A forged bank callback is refused.** Even through the gateway with a valid user token, a callback without
the bank's signature changes nothing.

### E2E-58 { #e2e-58 }
**Nobody else can see my payments or approve my bank requests.**

### E2E-59 { #e2e-59 }
**An unanswered payment request expires, and so does the deposit.**

## Trading

Each case starts with a new customer who has added ₹50,000 the Phase 2 way (a deposit approved in Sprout
Bank with the UPI PIN), and waits until the market is open with at least half an hour to the close.
Prices move while the tests run, so they check identities (what was paid equals the value plus charges;
what the customer has equals what they put in plus profit less charges) rather than fixed numbers.

### E2E-60 { #e2e-60 }
**Buy for delivery at the market.** The exchange executes it at the market price; there is no brokerage
but there is STT; cash goes down by exactly the value plus charges; the shares show as T1.

### E2E-61 { #e2e-61 }
**Sell only what you hold; the proceeds wait for settlement.** Selling more than held is rejected; a sale's
value less charges is `unsettled`.

### E2E-62 { #e2e-62 }
**A limit order away from the market rests with its money blocked; cancelling gives back every paisa.**

### E2E-63 { #e2e-63 }
**An order beyond your money is rejected and blocks nothing.**

### E2E-64 { #e2e-64 }
**Intraday round trip.** Buying holds a fifth of the value as margin; selling closes the position, books the
profit or loss and releases the margin; cash + unsettled − dues equals the deposit plus the P&amp;L less both
orders' charges, whichever way the price went.

### E2E-65 { #e2e-65 }
**Intraday lets you sell first and buy back; delivery doesn't let you sell what you don't own.** One order
can't flip a short into a long.

### E2E-66 { #e2e-66 }
**The exchange's rules.** Prices off the tick and outside the day's band are rejected; unknown shares are
refused as `UNKNOWN_INSTRUMENT`.

### E2E-67 { #e2e-67 }
**Retrying an order with the same `Idempotency-Key` places it once.**

### E2E-68 { #e2e-68 }
**Nobody else can see or cancel my orders.**

### E2E-69 { #e2e-69 }
**A forged execution report is refused**, even through the gateway with a valid user token.

## Results

The latest results, case by case, are in each run's evidence page under
[Evidence from runs](../reliability/runs/index.md).
