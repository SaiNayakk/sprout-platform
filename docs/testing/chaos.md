# Chaos tests

A chaos experiment breaks one thing on purpose and checks that the system behaves the way we claim it
does. Each has a **steady state** (what normal looks like), a **hypothesis** (what should happen when
the thing breaks), a **method**, and a pass condition. They run automatically in pre-prod.

Every experiment starts from a steady state: the run waits until every host's health check passes
(each checks all the services in that host, not only the first one to start), because the experiment
before may have just restarted one.

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

## CHAOS-04: Sprout Bank goes away mid-withdrawal { #chaos-04 }

| | |
|---|---|
| **Steady state** | A customer has ₹1,000 in Sprout. |
| **Fault** | Stop the street host (Sprout Bank), then withdraw ₹400. |
| **Hypothesis** | The withdrawal is accepted and the money held (available ₹600, withdrawing ₹400): never refused, never lost, never paid twice. When the bank returns, the reconciler finishes it within 90 s and the bank receives ₹400 exactly once. |

First run: accepted as `PROCESSING` in 2.1 s with the money held; completed 9.2 s after the bank came
back; the customer's bank received exactly ₹400.

## CHAOS-05: payments is down when the customer approves { #chaos-05 }

| | |
|---|---|
| **Steady state** | A customer has asked to add ₹750; the request waits in Sprout Bank. |
| **Fault** | Stop the money host, then approve the request in the bank with the PIN. |
| **Hypothesis** | The customer can still approve (the bank is up). The bank keeps the approval and retries telling payments; once the money host is back, the deposit completes within 120 s and is credited exactly once. |

First run: approved while payments was down; completed 10.2 s after the money host started; exactly one
ledger entry for the deposit.

## RECON-01: the books agree with the bank { #recon-01 }

Not a fault but a check, run last, after every test and failure above: the ledger balances (assets equal
liabilities), what the ledger says Sprout holds at the bank equals what Sprout Bank says Sprout holds, to the
paisa, and no withdrawal is left in progress. Real brokers reconcile like this every day; a difference
means money moved on one side only.

## CHAOS-06: the exchange goes away mid-order { #chaos-06 }

| | |
|---|---|
| **Steady state** | A customer has ₹20,000 in Sprout; the market is open. |
| **Fault** | Stop the street host (Sprout Bank and the exchange), then buy 2 shares at the market. |
| **Hypothesis** | The order is accepted with its money blocked and left `PENDING`: Sprout doesn't know whether the exchange got it, so it doesn't guess. When the exchange is back, the order service asks it, learns the order never arrived, rejects it within 120 s and gives back every paisa. |

The first run failed: the order was never given up on, its ₹3,597.77 left blocked (the reconciler measured
its 30 s from a timestamp that asking the exchange kept moving; see
[Incidents](../incidents.md)). After the fix: accepted as `PENDING` in 2.1 s with ₹3,593.37 blocked;
`REJECTED` as `UNAVAILABLE` 28.5 s after the exchange came back; cash back to exactly ₹20,000.00.

## SETTLE-01: a trading day settles T+1 { #settle-01 }

Not a fault but the whole of settlement, run near the end, after the experiments above have stopped
and started every host. The run's first trade date (the E2E suite's) must settle within one session of
it: the clearing corporation nets the day, takes in sellers' shares and sends its obligation; Sprout's
back office finds it matches its books exactly (no break); the money moves through Sprout Bank; buyers'
shares reach their demat accounts; clients' sale proceeds become cash. No client may be short.

## RECON-02: orders, the exchange and the ledger agree { #recon-02 }

Run last, like RECON-01: every order Sprout booked as executed was executed by the exchange at the same
price and quantity, and the exchange executed nothing Sprout hasn't booked; for every customer, the money
the ledger holds for orders equals what their working orders and open positions say; every ledger entry
the order service decided on has been posted; no order is left waiting on the exchange.

## RECON-03: after settlement, shares and money agree everywhere { #recon-03 }

For every client, the shares in their demat account at the depository are exactly the delivered shares
Sprout shows them (holdings less T1); their unsettled money in the ledger is exactly the proceeds of days
not yet settled; and what the ledger says Sprout owes or is owed by the clearing corporation is exactly
the unsettled days' trades.

## RECON-04: Sprout's own reconciliation agrees { #recon-04 }

The last check of a run: Sprout's reconciliation service, which runs every day in production, is asked
to reconcile now. Every one of its seven checks must pass, reading through the services' APIs what the
SQL checks above read from their databases.

## Planned

| Id | Fault | Hypothesis |
|---|---|---|
| CHAOS-07 | Identity's context crashes inside the edge host | Gateway answers `503` fast; circuit opens after repeated failures and closes after recovery |
| CHAOS-08 | Postgres slows to 3 s per query (network latency injected) | Requests fail inside the gateway budget; no thread pile-up; memory stays under the limit |
| CHAOS-09 | Edge host killed mid-traffic | Supervisor restarts it; clients see errors for under 30 s; no half-written sessions |
| CHAOS-10 | Signing key rotated while tokens are live | Old tokens keep working until they expire; new tokens use the new key |
| CHAOS-11 | Disk fills on the database volume | Writes fail with `503`, reads keep working, nothing corrupts |
| CHAOS-12 | The phone loses its network (region down) | The laptop region takes traffic; see [Reliability](../reliability/index.md) |
| CHAOS-13 | The market clock stalls (engine thread stuck) | Health turns `DOWN` within 30 s; the host is restarted; clients resync |
| CHAOS-14 | The order service is down when the exchange executes a resting order | The exchange keeps the execution and retries; once orders is back, it is booked exactly once |
