# Errors

Every error from a Sprout API is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem:

```json
{
  "type": "https://sainayakk.github.io/sprout-platform/errors/#invalid_credentials",
  "title": "Wrong email or password",
  "status": 401,
  "code": "INVALID_CREDENTIALS",
  "detail": "Wrong email or password.",
  "requestId": "3f2b8c1e-6a4d-4f0e-9b7a-2d5c8e1f4a6b"
}
```

Clients should branch on `code`, which never changes meaning. `title` and `detail` are for people and
may be reworded. `requestId` finds the request in the logs of every service it touched.

## From any service

### VALIDATION_FAILED { #validation_failed }
`400`. The request isn't valid: malformed JSON, a missing or unexpected field, or a value out of range.
`detail` says which. Fix the request; retrying it unchanged won't help.

### UNAUTHENTICATED { #unauthenticated }
`401`. No access token, or one that is expired, tampered with or not ours. Refresh the token, or sign
in again.

### NOT_FOUND { #not_found }
`404`. No such route. Also returned for blocked paths, so it doesn't reveal what exists.

### RATE_LIMITED { #rate_limited }
`429`. Too many requests from this client, or too many open price streams (five per client). Wait
for the number of seconds in `Retry-After`, or close a stream you no longer need.

### UPSTREAM_UNAVAILABLE { #upstream_unavailable }
`503`. A service or its database is temporarily unreachable, or too many people are streaming prices.
The request didn't happen; safe to retry after `Retry-After` seconds.

`504` with the same code means something different: the service took too long to answer, so the
request **may** have happened. Check before retrying anything that changes state.
See the [runbook](runbooks.md#sign-in-returns-503-upstream_unavailable).

## Market data

### UNKNOWN_INSTRUMENT { #unknown_instrument }
`404`. No instrument has this symbol. When several symbols were asked for, `detail` names the unknown
ones. `GET /v1/instruments` lists them all.

## Accounts

### ACCOUNT_EXISTS { #account_exists }
`409`. You already have one (a Sprout account, or a Sprout Bank account).

### PAN_IN_USE { #pan_in_use }
`409`. Another Sprout account already uses this PAN. One account per PAN.

### KYC_REJECTED { #kyc_rejected }
`422`. The (simulated) checks failed: under 18, a PAN that isn't an individual's, or not a PAN at all.
`detail` says which.

### VPA_NOT_FOUND { #vpa_not_found }
`422`. No Sprout Bank account has that UPI address.

### NO_ACCOUNT { #no_account }
`404`. Open a Sprout account first.

## Payments and the ledger

### INSUFFICIENT_FUNDS { #insufficient_funds }
`422`. More than your available balance. Nothing moved.

### NOT_FOUND { #not_found_payment }
`404`. No such deposit, withdrawal or bank request of yours.

### INVALID_SIGNATURE { #invalid_signature }
`401`. A bank callback without Sprout Bank's signature. Refused.

### UNBALANCED, UNKNOWN_ACCOUNT, IDEMPOTENCY_CONFLICT { #unbalanced }
Ledger only (services, never the app): an entry whose debits and credits differ, an account name that
isn't a known kind, or an idempotency key reused for a different entry.

## Orders

Most refusals of an order are the order itself, `REJECTED` with a `rejection.code`, as a broker's order
book shows them: `INSUFFICIENT_FUNDS`, `INSUFFICIENT_HOLDINGS`, `MARKET_CLOSED` (place an AMO instead),
`MARKET_OPEN` (an AMO while the market is open), `INTRADAY_CLOSED` (no new intraday positions after 15:20),
`POSITION_FLIP` (close the position before trading the other way), `PRICE_OUT_OF_BAND`, `INVALID_TICK`,
`UNAVAILABLE` (part of Sprout or the exchange couldn't be reached; nothing was placed). The problems below
are requests that were wrong.

### UNKNOWN_INSTRUMENT { #unknown_instrument_order }
No tradable share with that symbol (an index can't be bought).

### ORDER_NOT_OPEN { #order_not_open }
Too late to cancel: the order already executed, expired or was rejected.

## Sprout Stock Exchange (members only)

### DUPLICATE_ORDER_ID { #duplicate_order_id }
A different order already has this `clientOrderId`.

### MARKET_CLOSED, PRICE_OUT_OF_BAND, INVALID_TICK { #exchange_rules }
The exchange's rules; nothing was recorded.

## Sprout Bank

### WEAK_PIN { #weak_pin }
`400`. A UPI PIN is 4 or 6 digits, not all the same and not a run like `1234`.

### INVALID_PIN { #invalid_pin }
`422`. Wrong UPI PIN; `attemptsLeft` says how many tries remain.

### PIN_LOCKED { #pin_locked }
`423`. Three wrong PINs: approvals are locked for 15 minutes (`Retry-After`).

### REQUEST_NOT_PENDING { #request_not_pending }
`409`. The payment request was already approved, declined or expired.

### INSUFFICIENT_BALANCE { #insufficient_balance }
`422`. Not enough money in the bank account for this payment. The request stays waiting.

### INVALID_PARTNER_KEY { #invalid_partner_key }
`401`. A partner call without a valid `X-Partner-Key`.

## Identity

### WEAK_PASSWORD { #weak_password }
`400`. The password breaks a rule: fewer than 10 characters, more than 128, well known, or containing
your email's name. `detail` says which.

### EMAIL_TAKEN { #email_taken }
`409`. An account with this email already exists. Emails compare without regard to case or surrounding
spaces.

### INVALID_CREDENTIALS { #invalid_credentials }
`401`. Wrong email or password. Deliberately the same whether or not the email has an account.

### ACCOUNT_LOCKED { #account_locked }
`423`. Five wrong passwords in a row. Locked for 15 minutes; `Retry-After` says how long is left.

### INVALID_TOTP { #invalid_totp }
`401`. The two-factor code is wrong, from the wrong time, or has already been used.

### CHALLENGE_EXPIRED { #challenge_expired }
`401`. The two-factor step of this sign-in expired (after 5 minutes) or was already completed. Sign in
again.

### INVALID_REFRESH_TOKEN { #invalid_refresh_token }
`401`. The refresh token is unknown, expired, or its session has ended. Sign in again.

### REFRESH_TOKEN_REUSED { #refresh_token_reused }
`401`. A refresh token that had already been used was presented again, which means it was copied. The
whole session is ended for safety. Sign in again.

### TOTP_ALREADY_ENABLED { #totp_already_enabled }
`409`. Two-factor is already on for this account.

### TOTP_NOT_STARTED { #totp_not_started }
`409`. Confirming two-factor before starting setup. Start setup first.
