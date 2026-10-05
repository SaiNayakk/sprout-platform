# Pre-prod run 2026-10-05-0416-preprod

A fresh environment built from the pinned releases, tested, then destroyed. Raw evidence sits next to this page.

## Release under test

| Host | Service | Version |
|---|---|---|
| edge | sprout-identity | `0.2.3` |
| edge | sprout-gateway | `0.2.4` |
| money | sprout-accounts | `0.1.0` |
| money | sprout-payments | `0.1.0` |
| money | sprout-ledger | `0.2.0` |
| street | sprout-bank | `0.1.0` |
| street | sprout-exchange | `0.1.0` |
| trading | sprout-marketdata | `0.1.1` |
| trading | sprout-oms | `0.1.2` |
| | sprout-platform | `v0.4.2-dirty` |

## Result

| Stage | Result |
|---|---|
| environment | ✅ pass |
| e2e | ✅ pass |
| perf-01 | ✅ pass |
| perf-02 | ✅ pass |
| perf-03 | ✅ pass |
| chaos-01 | ✅ pass |
| chaos-02 | ✅ pass |
| chaos-03 | ✅ pass |
| chaos-04 | ✅ pass |
| chaos-05 | ✅ pass |
| chaos-06 | ✅ pass |
| recon-01 | ✅ pass |
| recon-02 | ✅ pass |

## End-to-end suite

44 of 44 passed.

| Id | Journey or edge case | Time | Result |
|---|---|---|---|
| [E2E-01](../../../testing/e2e.md#e2e-01) | sign up, sign in and see your account | 0.2 s | ✅ pass |
| [E2E-02](../../../testing/e2e.md#e2e-02) | turn on two-factor, then sign in with a code | 29.7 s | ✅ pass |
| [E2E-03](../../../testing/e2e.md#e2e-03) | refresh tokens rotate; sign out ends the session | 0.4 s | ✅ pass |
| [E2E-10](../../../testing/e2e.md#e2e-10) | duplicate email, any case or spacing, is refused | 0.1 s | ✅ pass |
| [E2E-11](../../../testing/e2e.md#e2e-11) | weak passwords are refused with a reason | 0.0 s | ✅ pass |
| [E2E-12](../../../testing/e2e.md#e2e-12) | malformed JSON and unknown fields are refused | 0.0 s | ✅ pass |
| [E2E-20](../../../testing/e2e.md#e2e-20) | wrong password and unknown email look identical | 0.3 s | ✅ pass |
| [E2E-21](../../../testing/e2e.md#e2e-21) | five wrong passwords lock the account, even for the right one | 0.6 s | ✅ pass |
| [E2E-22](../../../testing/e2e.md#e2e-22) | a two-factor code works once and a challenge only once | 24.5 s | ✅ pass |
| [E2E-30](../../../testing/e2e.md#e2e-30) | a stolen refresh token, used after the owner, ends the session | 0.3 s | ✅ pass |
| [E2E-31](../../../testing/e2e.md#e2e-31) | two refreshes racing with one token: exactly one wins | 0.5 s | ✅ pass |
| [E2E-32](../../../testing/e2e.md#e2e-32) | missing, tampered and junk tokens are refused at the gateway | 0.2 s | ✅ pass |
| [E2E-33](../../../testing/e2e.md#e2e-33) | a client can't pretend to be someone else with X-User-Id | 0.3 s | ✅ pass |
| [E2E-34](../../../testing/e2e.md#e2e-34) | sign-in is rate limited per client | 1.0 s | ✅ pass |
| [E2E-35](../../../testing/e2e.md#e2e-35) | unknown routes, path traversal and oversized bodies are refused | 0.4 s | ✅ pass |
| [E2E-36](../../../testing/e2e.md#e2e-36) | one request id follows a request through the gateway and identity | 0.1 s | ✅ pass |
| [E2E-40](../../../testing/e2e.md#e2e-40) | the market and its instruments are visible before signing in | 0.3 s | ✅ pass |
| [E2E-41](../../../testing/e2e.md#e2e-41) | prices need a signed-in user | 0.2 s | ✅ pass |
| [E2E-42](../../../testing/e2e.md#e2e-42) | quotes come back in the order asked; unknown symbols are named | 0.2 s | ✅ pass |
| [E2E-43](../../../testing/e2e.md#e2e-43) | candles never show the future | 0.3 s | ✅ pass |
| [E2E-44](../../../testing/e2e.md#e2e-44) | the price stream starts with the current state, then ticks live with rising seq | 2.2 s | ✅ pass |
| [E2E-45](../../../testing/e2e.md#e2e-45) | every streamed price lies inside its minute's high and low | 9.3 s | ✅ pass |
| [E2E-46](../../../testing/e2e.md#e2e-46) | one client can hold at most five price streams | 0.3 s | ✅ pass |
| [E2E-47](../../../testing/e2e.md#e2e-47) | a bad stream request is refused before it starts | 0.3 s | ✅ pass |
| [E2E-50](../../../testing/e2e.md#e2e-50) | open a bank account with a UPI PIN, then a Sprout account linked to it | 0.4 s | ✅ pass |
| [E2E-51](../../../testing/e2e.md#e2e-51) | KYC refuses the underage, business PANs, unknown UPI addresses and a second account per PAN | 0.8 s | ✅ pass |
| [E2E-52](../../../testing/e2e.md#e2e-52) | add money: approved in the bank with the PIN, it arrives in Sprout | 1.1 s | ✅ pass |
| [E2E-53](../../../testing/e2e.md#e2e-53) | wrong PINs count down; declining ends the deposit; nothing moves | 1.1 s | ✅ pass |
| [E2E-54](../../../testing/e2e.md#e2e-54) | retrying with the same Idempotency-Key makes one deposit and one bank request | 0.4 s | ✅ pass |
| [E2E-55](../../../testing/e2e.md#e2e-55) | withdraw: never more than you have; what you take arrives in the bank | 1.1 s | ✅ pass |
| [E2E-56](../../../testing/e2e.md#e2e-56) | ten withdrawals racing for money that covers five: exactly five succeed | 1.5 s | ✅ pass |
| [E2E-57](../../../testing/e2e.md#e2e-57) | a forged bank callback is refused | 0.4 s | ✅ pass |
| [E2E-58](../../../testing/e2e.md#e2e-58) | nobody else can see my payments or approve my bank requests | 0.7 s | ✅ pass |
| [E2E-59](../../../testing/e2e.md#e2e-59) | an unanswered payment request expires, and so does the deposit | 36.1 s | ✅ pass |
| [E2E-60](../../../testing/e2e.md#e2e-60) | buy for delivery at the market: executed on the exchange, paid with its charges, held as T1 shares | 1.1 s | ✅ pass |
| [E2E-61](../../../testing/e2e.md#e2e-61) | sell only what you hold; the proceeds wait for settlement | 0.9 s | ✅ pass |
| [E2E-62](../../../testing/e2e.md#e2e-62) | a limit order away from the market rests with its money blocked; cancelling gives back every paisa | 1.7 s | ✅ pass |
| [E2E-63](../../../testing/e2e.md#e2e-63) | an order beyond your money is rejected and blocks nothing | 0.9 s | ✅ pass |
| [E2E-64](../../../testing/e2e.md#e2e-64) | intraday: a fifth as margin, a round trip books its profit or loss, and the books add up | 1.2 s | ✅ pass |
| [E2E-65](../../../testing/e2e.md#e2e-65) | intraday lets you sell first and buy back; delivery doesn't let you sell what you don't own | 0.9 s | ✅ pass |
| [E2E-66](../../../testing/e2e.md#e2e-66) | the exchange's rules: prices on the tick and inside the day's band; unknown shares are refused | 1.0 s | ✅ pass |
| [E2E-67](../../../testing/e2e.md#e2e-67) | retrying an order with the same Idempotency-Key places it once | 0.9 s | ✅ pass |
| [E2E-68](../../../testing/e2e.md#e2e-68) | nobody else can see or cancel my orders | 1.4 s | ✅ pass |
| [E2E-69](../../../testing/e2e.md#e2e-69) | a forged execution report is refused | 0.8 s | ✅ pass |

## PERF-01: sign-in throughput

First 30 s: ramp from 2 to 10 sign-ins a second. Then 60 s steady at 10 a second (half the edge host's capacity). Every request from a different client.

| Measure | Warm-up (30 s) | Steady (60 s) |
|---|---|---|
| Median | 108 ms | 112 ms |
| p95 | 138 ms | 136 ms |
| p99 | 154 ms | 155 ms |
| Slowest | 168 ms | 163 ms |
| Requests | 179 | 601 |
| Failed | 0.00% | 0.00% |

| Threshold | Rule | Result |
|---|---|---|
| `http_req_failed{scenario:warmup}` | `rate<0.01` | ✅ pass |
| `checks{scenario:steady}` | `rate>0.99` | ✅ pass |
| `http_req_duration{scenario:steady}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:steady}` | `p(99)<1000` | ✅ pass |
| `http_req_failed{scenario:steady}` | `rate<0.01` | ✅ pass |
| `http_req_duration{scenario:warmup}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:warmup}` | `p(99)<1000` | ✅ pass |

## PERF-02: sign-in straight after a restart

The edge host is restarted (it warms itself up before reporting ready), then gets 10 sign-ins a second for 30 s from the moment it is ready.

| Measure | Value |
|---|---|
| Median / p95 / p99 / slowest | 113 ms / 157 ms / 190 ms / 221 ms |
| Failed | 0.00% |

| Threshold | Rule | Result |
|---|---|---|
| `http_req_failed{scenario:cold}` | `rate<0.01` | ✅ pass |
| `checks{scenario:cold}` | `rate>0.99` | ✅ pass |
| `http_req_duration{scenario:cold}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:cold}` | `p(99)<1000` | ✅ pass |

## PERF-03: price fan-out

200 clients, each streaming 5 symbols through the gateway for 60 s. Latency is from the moment market data produced a tick to the moment a client read it, measured on one clock.

| Measure | Value |
|---|---|
| Streams opened | 200 of 200 |
| Streams that ended early | 0 |
| Ticks delivered | 502,049 (8,367 a second) |
| Delivery latency p50 / p95 / p99 / max | 7 ms / 41 ms / 78 ms / 400 ms |
| Conflated (a client got only the newest price) | 20,702 times, 4.1% of ticks |

Pass when every stream opens and stays open, p95 is under 250 ms and p99 under 1 s.

## Memory under load

| Host | Peak | Limit |
|---|---|---|
| edge | 266 MiB | 384 MiB |
| trading | 220 MiB | 320 MiB |
| money | 206 MiB | 320 MiB |
| street | 204 MiB | 320 MiB |

## CHAOS-01: The database goes away

Hypothesis: With Postgres stopped, sign-in answers 503 with Retry-After in under 3 s (never hanging until the gateway's 5 s timeout), and recovers within 30 s of Postgres returning, without a restart.

| Observed | |
|---|---|
| Before (wrong password, so 401 is healthy) | 401 in 334 ms |
| Database down, try 1 | 503 in 2,022 ms |
| Database down, try 2 | 503 in 2,018 ms |
| Database down, try 3 | 503 in 2,021 ms |
| Retry-After | 5 |
| Answering normally again after Postgres started | 7.3 s |

| Check | Result |
|---|---|
| 503 UPSTREAM_UNAVAILABLE every time | ✅ pass |
| each in under 3 s | ✅ pass |
| with Retry-After | ✅ pass |
| recovered within 30 s without a restart | ✅ pass |

## CHAOS-02: NATS goes away

Hypothesis: With NATS stopped, prices keep streaming to clients and quotes keep working; the trading host stays healthy. When NATS returns, market data reconnects by itself within 30 s and publishes again.

| Observed | |
|---|---|
| NATS connected before | True |
| Ticks streamed to a client in the 10 s NATS was down | 147 |
| Trading host health while NATS was down | UP |
| Quote while NATS was down | 200 in 17 ms |
| Reconnected after NATS started | 2.8 s |
| Events published in 3 s after reconnecting | 608 |

| Check | Result |
|---|---|
| prices kept streaming | ✅ pass |
| the stream stayed open | ✅ pass |
| the host stayed healthy | ✅ pass |
| quotes kept working | ✅ pass |
| reconnected within 30 s | ✅ pass |
| publishing again | ✅ pass |

## CHAOS-03: The trading host dies

Hypothesis: With the trading host killed, sign-in and accounts are unaffected (they run in a different JVM). Market data answers 503 within 3 s instead of hanging, open price streams end within 5 s so clients know to reconnect, and market data is back within 60 s of the host restarting.

| Observed | |
|---|---|
| Open stream ended after the kill | 0.0 s |
| Sign-in (wrong password, so 401 is healthy) | 401 in 132 ms |
| My account | 200 in 28 ms |
| A quote | 503 in 2,024 ms (UPSTREAM_UNAVAILABLE) |
| Opening a new stream | 503 in 2,019 ms |
| Quotes working again after restart | 17.2 s |
| Edge host | Up 3 minutes (healthy) |

| Check | Result |
|---|---|
| sign-in unaffected | ✅ pass |
| accounts unaffected | ✅ pass |
| quotes fail fast with 503 | ✅ pass |
| new streams refused fast | ✅ pass |
| open streams end within 5 s | ✅ pass |
| market data back within 60 s | ✅ pass |

## CHAOS-04: Sprout Bank goes away mid-withdrawal

Hypothesis: With the bank unreachable, a withdrawal is accepted and the money held (never lost, never paid twice); when the bank returns, the reconciler finishes it within 90 s and the money arrives in the bank exactly once.

| Observed | |
|---|---|
| Withdrawal while the bank was down | 201 PROCESSING in 2,060 ms |
| Available / withdrawing / bank balance while down | 600.00 / 400.00 / None |
| Completed after the bank came back | 8.1 s |
| Available / withdrawing / bank balance after | 600.00 / 0.00 / 99400.00 |

| Check | Result |
|---|---|
| accepted and held, not refused or lost | ✅ pass |
| answered without waiting for the bank | ✅ pass |
| completed within 90 s of the bank returning | ✅ pass |
| paid exactly once | ✅ pass |

## CHAOS-05: Payments is down when the customer approves

Hypothesis: The customer approves in the bank while the money host is down. The bank keeps the news and retries; when the money host is back, the deposit completes within 120 s and is credited exactly once.

| Observed | |
|---|---|
| Approval in the bank (money host down) | 200 APPROVED |
| Deposit completed after the money host started | 9.2 s |
| Sprout cash / bank balance | 750.00 / 99250.00 |
| Ledger entries for this deposit | 1 |

| Check | Result |
|---|---|
| the customer could still approve | ✅ pass |
| completed within 120 s of the money host returning | ✅ pass |
| credited exactly once | ✅ pass |
| the bank's side matches | ✅ pass |

## CHAOS-06: The exchange goes away mid-order

Hypothesis: With the exchange unreachable, an order is accepted with its money blocked and left PENDING (its fate unknown, so not guessed); when the exchange is back, the reconciler finds it never arrived, rejects it within 120 s, and every paisa blocked for it is back.

| Observed | |
|---|---|
| Order while the exchange was down | 201 PENDING in 2,149 ms, blocked ₹3593.37 |
| Cash / blocked while down | 16406.63 / 3593.37 |
| Ended after the exchange came back | REJECTED after 28.5 s |
| Rejection | UNAVAILABLE |
| Cash / blocked after | 20000.00 / 0.00 |

| Check | Result |
|---|---|
| accepted, money blocked, outcome left open | ✅ pass |
| answered without waiting for the exchange | ✅ pass |
| ended within 120 s of the exchange returning | ✅ pass |
| rejected as never placed (not filled from nowhere) | ✅ pass |
| every paisa back | ✅ pass |

## RECON-01: The books agree with the bank

Hypothesis: After every test and every failure above: the ledger balances (assets equal liabilities), and what it says Sprout holds at the bank is exactly what Sprout Bank says it holds, to the paisa.

| Observed | |
|---|---|
| Ledger assets / liabilities | ₹534,065.15 / ₹534,065.15 |
| Ledger: Sprout's money at the bank | ₹524,350.25 |
| Sprout Bank: Sprout's account | ₹524,350.25 |
| Withdrawals still in progress | 0 |

| Check | Result |
|---|---|
| the ledger balances | ✅ pass |
| the ledger matches the bank | ✅ pass |
| nothing left in progress | ✅ pass |

## RECON-02: Orders, the exchange and the ledger agree

Hypothesis: After every test and every failure above: each order Sprout booked as executed was executed by the exchange, at the same price and quantity, and nothing the exchange executed is missing from Sprout; the money the ledger holds for each customer is exactly what their working orders and open positions say; every ledger entry Sprout decided on has been posted.

| Observed | |
|---|---|
| Orders executed (Sprout) / trades (exchange) | 8 / 8 |
| Executed orders that differ from the exchange | 0 |
| Exchange executions Sprout hasn't booked | 0 |
| Customers whose held money doesn't match their orders | 0 |
| Ledger entries not yet posted | 0 |
| Orders still waiting on the exchange after 2 minutes | 0 |

| Check | Result |
|---|---|
| every executed order matches the exchange | ✅ pass |
| nothing executed is missing | ✅ pass |
| held money matches orders and positions | ✅ pass |
| every ledger entry posted | ✅ pass |
| nothing left hanging | ✅ pass |

## Files

- `e2e/`: JUnit reports
- `perf-01-k6-summary.json`: every k6 metric
- `perf-02-k6-summary.json`: sign-in straight after a restart
- `perf-03-summary.json`: the fan-out result
- `memory-during.txt`: host memory and CPU every 5 s under load
- `chaos-*.json`: each experiment's observations and checks
- `edge.log`, `trading.log`, `money.log`, `street.log`: the hosts' structured logs for the whole run
