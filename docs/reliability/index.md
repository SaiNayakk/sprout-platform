# Reliability

## Targets

Service level objectives for what users actually feel. Measured at the gateway, over 28 days.

| Journey | Indicator | Objective |
|---|---|---|
| Sign in | Requests answered without a server error (`5xx`), excluding `503` during announced maintenance | 99.5% |
| Sign in | Answered within 800 ms | 99% |
| Any authenticated read | Answered without a server error | 99.5% |
| Any request | Answered within the gateway's 5 s budget (never a hang) | 99.9% |
| Live prices | A price change reaches a streaming client within 250 ms | 99% |

99.5% over 28 days is about **3 hours 20 minutes** of allowed failure: an error budget. A phone on
home Wi-Fi and power will spend some of it, and that is the honest number to aim for until there is a
second region.

## How reliability is designed in

| Failure | What happens | Proven by |
|---|---|---|
| Database unreachable | `503` with `Retry-After` in about 2 s; recovers by itself | [CHAOS-01](../testing/chaos.md#chaos-01) |
| A service is slow | Gateway timeout of 5 s; circuit breaker opens after repeated failures so clients fail fast | Gateway tests; CHAOS-05 planned |
| The trading host dies | Sign-in unaffected (separate JVM); market data `503` fast; open streams end so clients reconnect | [CHAOS-03](../testing/chaos.md#chaos-03) |
| NATS is down | Prices keep streaming; events are dropped and counted, not queued; reconnects by itself | [CHAOS-02](../testing/chaos.md#chaos-02) |
| The bank is unreachable | Withdrawals are held and finished by the reconciler; nothing lost or paid twice | [CHAOS-04](../testing/chaos.md#chaos-04) |
| Payments is down when a customer approves | The bank retries its signed callback; credited exactly once | [CHAOS-05](../testing/chaos.md#chaos-05) |
| Books drift from the bank | Ledger and bank compared to the paisa after every run | [RECON-01](../testing/chaos.md#recon-01) |
| A slow streaming client | Gets the newest prices only (conflation); never slows the market or grows memory | Market data tests; [PERF-03](../testing/performance.md#perf-03) |
| Abuse or a stuck client | Per-client rate limits, tighter on sign-in | [E2E-34](../testing/e2e.md#e2e-34) |
| Stolen refresh token | Reuse detected, whole session ended | [E2E-30](../testing/e2e.md#e2e-30) |
| Memory regression | Hosts run with hard memory limits in pre-prod, the same as production | [PERF-01](../testing/performance.md#perf-01) |
| Bad release | Nothing reaches the phone without passing pre-prod; deploys roll back automatically when smoke tests fail | [Environments](../environments.md) |

## Regions

There are two cells, the phone (A) and the laptop (B), each a whole Sprout with its own database, behind one address
([ADR-027](../decisions.md#adr-027-cells)). A customer belongs to one cell; a new customer's cell is picked from their
email, weighted by what each cell carries. If a cell is lost, the other takes its customers over within minutes:

| What | How | Guarantee |
|---|---|---|
| A cell's database | Copied into the other cell continuously (Postgres logical replication over Cloudflare) | Lags by seconds |
| A customer's write | Journalled in the other cell before it is answered | Never lost once answered; replayed at least once, applied once (idempotency keys) |
| A write refused at the time | Noted in the journal | Stays refused when replayed |
| Two copies acting at once | A cell that can't reach its own address for 60 s fences itself (no writes); the other takes over only after 120 s | One writer per customer |
| Taking over | Promote the copy, start the lost cell's services (with its keys) on it, replay the journal, route its customers there | Customers sign in as before; reconciliation checks the books |

CHAOS-10 kills a cell mid-load and checks that no answered write is missing, none happened twice, and the books agree.
