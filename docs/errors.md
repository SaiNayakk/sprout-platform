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
