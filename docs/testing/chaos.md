# Chaos tests

A chaos experiment breaks one thing on purpose and checks that the system behaves the way we claim it
does. Each has a **steady state** (what normal looks like), a **hypothesis** (what should happen when
the thing breaks), a **method**, and a pass condition. They run automatically in pre-prod.

## CHAOS-01: the database goes away { #chaos-01 }

| | |
|---|---|
| **Steady state** | A sign-in with a wrong password gets `401` quickly. |
| **Fault** | Stop the Postgres container. |
| **Hypothesis** | Sign-in answers `503 UPSTREAM_UNAVAILABLE` with a `Retry-After` header in **under 3 s**, never hanging until the gateway's 5 s timeout. When Postgres comes back, identity recovers **within 30 s, without a restart**. |
| **Method** | [`preprod/chaos.py`](https://github.com/SaiNayakk/sprout-platform/blob/main/preprod/chaos.py): probe, `docker compose stop postgres`, probe three times, `start postgres`, probe every second until healthy. |

### What happened

The first time this ran (manually, before automation), **the hypothesis was disproved**:

| | Expected | Got |
|---|---|---|
| Status while down | `503` with `Retry-After` | `504` from the gateway |
| Time to answer | under 3 s | 5 s: identity was still waiting for a database connection when the gateway gave up |

The cause was in identity, and fixing it surfaced a second one:

1. The connection pool waited the default 30 s for a connection, so identity never answered before the
   gateway's 5 s timeout.
2. The regression test for the fix (below) then failed in CI with a `500`: depending on timing, the
   error arrives as a failed rollback after a lost connection (`TransactionSystemException` wrapping
   SQL state `08006`), which the problem handler didn't recognise as "database unreachable".

The fix, released as identity `v0.2.1`:

- Pool `connection-timeout` 2 s and `validation-timeout` 1 s, so identity decides well inside the
  gateway's budget.
- The problem handler walks the whole cause chain for any connection failure (SQL state class `08`,
  socket errors, Spring's resource-failure exceptions, and failed rollbacks) and answers
  `503 UPSTREAM_UNAVAILABLE` with `Retry-After: 5`.
- The contract added the `503` first ([contracts `v0.2.0`](../contracts.md#versioning)).
- Unit tests for each wrapped form, and a Testcontainers test that stops a real Postgres mid-test and
  checks for a contract-valid `503` in under 4 s.

Re-run against `v0.2.1`: `503` in about 2.0 s with `Retry-After: 5`, recovery in seconds, no restart.
Every pre-prod run since repeats the experiment; results are in
[Evidence from runs](../reliability/runs/index.md).

## CHAOS-02: NATS goes away { #chaos-02 }

| | |
|---|---|
| **Steady state** | Market data is connected to NATS and publishing a `marketdata.tick` event per price change; clients are streaming prices. |
| **Fault** | Stop the NATS container for 10 seconds. |
| **Hypothesis** | Prices keep streaming to clients, quotes keep working and the trading host stays healthy. When NATS returns, market data reconnects by itself within 30 s and publishes again. |
| **Method** | Open a price stream, stop NATS, count ticks for 10 s, check health and a quote, start NATS, wait for reconnection, then read NATS's own message count to see publishing resume. |

**Why it should hold.** NATS is how other services will hear about prices, but clients are served
directly. Market data connects to NATS in the background, reconnects forever, and while disconnected
drops (and counts) events instead of queueing them: a tick is out of date within seconds, so a backlog
delivered after an outage would be worse than a gap.

In the first trial run: 168 ticks streamed during the outage, quotes answered in 20 ms, the host stayed
`UP`, it reconnected 0.6 s after NATS started, and 564 events were published in the following 3 s.

## CHAOS-03: the trading host dies { #chaos-03 }

| | |
|---|---|
| **Steady state** | A client is signed in and streaming prices. |
| **Fault** | `docker compose kill trading`: the whole JVM, without warning. |
| **Hypothesis** | Sign-in and accounts are unaffected, because they run in a different JVM. Market data answers `503` within 3 s instead of hanging, open price streams end within 5 s so clients know to reconnect, and market data is back within 60 s of the host restarting. |
| **Method** | Open a stream, kill the host, then: time how long the stream takes to end, sign in, read the account, ask for a quote and a new stream, restart the host and poll quotes until they work. |

This is the reason the trading services run in their own host rather than inside the edge host
([ADR-010](../decisions.md#adr-010-trading-host)): a fault in market data, or later in orders, must
never stop people signing in.

### What happened

The first run **disproved part of the hypothesis**. Sign-in, accounts, the open stream ending and the
recovery all passed, but quotes and new streams got **`504` after 2 s** instead of `503`.

| | Expected | Got |
|---|---|---|
| Quote while the host is down | `503` with `Retry-After`: not reachable, safe to retry | `504` "took too long; it may still have happened" |

**Cause.** A killed container's network name still resolves, but nothing answers at that address, so
the gateway's 2 s *connect* timeout expired. The gateway treated that like a *response* timeout. The
two mean different things to a client: after a response timeout the service may have acted on the
request; after a connect timeout it certainly never received it.

**Why it matters.** For prices it's cosmetic. For orders it decides whether a client may simply retry
or must first check whether the order went through. Getting it wrong either way means duplicate
orders or needlessly abandoned ones.

**Fix:** gateway `v0.2.3` answers a connect timeout with `503 UPSTREAM_UNAVAILABLE` and
`Retry-After: 5`, for normal requests and streams, with a regression test against an address that
never answers.

## Planned

| Id | Fault | Hypothesis |
|---|---|---|
| CHAOS-04 | Identity's context crashes inside the edge host | Gateway answers `503` fast; circuit opens after repeated failures and closes after recovery |
| CHAOS-05 | Postgres slows to 3 s per query (network latency injected) | Requests fail inside the gateway budget; no thread pile-up; memory stays under the limit |
| CHAOS-06 | Edge host killed mid-traffic | Supervisor restarts it; clients see errors for under 30 s; no half-written sessions |
| CHAOS-07 | Signing key rotated while tokens are live | Old tokens keep working until they expire; new tokens use the new key |
| CHAOS-08 | Disk fills on the database volume | Writes fail with `503`, reads keep working, nothing corrupts |
| CHAOS-09 | The phone loses its network (region down) | The laptop region takes traffic; see [Reliability](../reliability/index.md) |
| CHAOS-10 | The market clock stalls (engine thread stuck) | Health turns `DOWN` within 30 s; the host is restarted; clients resync |
