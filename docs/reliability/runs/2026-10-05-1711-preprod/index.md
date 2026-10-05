# Pre-prod run 2026-10-05-1711-preprod

A fresh environment built from the pinned releases, tested, then destroyed. Raw evidence sits next to this page.

## Release under test

| Host | Service | Version |
|---|---|---|
| edge | sprout-identity | `0.3.0` |
| edge | sprout-gateway | `0.3.1` |
| edge | sprout-sandbox | `0.1.0` |
| money | sprout-accounts | `0.3.1` |
| money | sprout-payments | `0.3.0` |
| money | sprout-ledger | `0.3.1` |
| money | sprout-settlement | `0.2.1` |
| money | sprout-statements | `0.2.1` |
| money | sprout-recon | `0.2.1` |
| money | sprout-goals | `0.1.0` |
| street | sprout-bank | `0.4.1` |
| street | sprout-exchange | `0.4.1` |
| street | sprout-depository | `0.2.1` |
| street | sprout-clearing | `0.2.1` |
| trading | sprout-marketdata | `0.1.2` |
| trading | sprout-oms | `0.5.1` |
| trading | sprout-plans | `0.2.1` |
| trading | sprout-habits | `0.3.0` |
| trading | sprout-rewards | `0.1.0` |
| | sprout-platform | `v0.8.0-5-g4c88788` |

## Result

| Stage | Result |
|---|---|
| environment | ✅ pass |
| e2e | ✅ pass |
| perf-01 | ✅ pass |
| perf-02 | ✅ pass |
| perf-03 | ✅ pass |
| perf-04 | ✅ pass |
| trace-01 | ✅ pass |
| chaos-01 | ✅ pass |
| chaos-02 | ✅ pass |
| chaos-03 | ✅ pass |
| chaos-04 | ✅ pass |
| chaos-05 | ✅ pass |
| chaos-06 | ✅ pass |
| chaos-07 | ✅ pass |
| settle-01 | ✅ pass |
| recon-01 | ✅ pass |
| recon-02 | ✅ pass |
| recon-03 | ✅ pass |
| recon-04 | ✅ pass |

## End-to-end suite

64 of 64 passed.

| Id | Journey or edge case | Time | Result |
|---|---|---|---|
| [E2E-01](../../../testing/e2e.md#e2e-01) | sign up, sign in and see your account | 0.2 s | ✅ pass |
| [E2E-02](../../../testing/e2e.md#e2e-02) | turn on two-factor, then sign in with a code | 29.7 s | ✅ pass |
| [E2E-03](../../../testing/e2e.md#e2e-03) | refresh tokens rotate; sign out ends the session | 0.2 s | ✅ pass |
| [E2E-10](../../../testing/e2e.md#e2e-10) | duplicate email, any case or spacing, is refused | 0.1 s | ✅ pass |
| [E2E-11](../../../testing/e2e.md#e2e-11) | weak passwords are refused with a reason | 0.0 s | ✅ pass |
| [E2E-12](../../../testing/e2e.md#e2e-12) | malformed JSON and unknown fields are refused | 0.0 s | ✅ pass |
| [E2E-20](../../../testing/e2e.md#e2e-20) | wrong password and unknown email look identical | 0.2 s | ✅ pass |
| [E2E-21](../../../testing/e2e.md#e2e-21) | five wrong passwords lock the account, even for the right one | 0.5 s | ✅ pass |
| [E2E-22](../../../testing/e2e.md#e2e-22) | a two-factor code works once and a challenge only once | 17.7 s | ✅ pass |
| [E2E-30](../../../testing/e2e.md#e2e-30) | a stolen refresh token, used after the owner, ends the session | 0.2 s | ✅ pass |
| [E2E-31](../../../testing/e2e.md#e2e-31) | two refreshes racing with one token: exactly one wins | 0.3 s | ✅ pass |
| [E2E-32](../../../testing/e2e.md#e2e-32) | missing, tampered and junk tokens are refused at the gateway | 0.2 s | ✅ pass |
| [E2E-33](../../../testing/e2e.md#e2e-33) | a client can't pretend to be someone else with X-User-Id | 0.3 s | ✅ pass |
| [E2E-34](../../../testing/e2e.md#e2e-34) | sign-in is rate limited per client | 0.9 s | ✅ pass |
| [E2E-35](../../../testing/e2e.md#e2e-35) | unknown routes, path traversal and oversized bodies are refused | 0.1 s | ✅ pass |
| [E2E-36](../../../testing/e2e.md#e2e-36) | one request id follows a request through the gateway and identity | 0.0 s | ✅ pass |
| [E2E-40](../../../testing/e2e.md#e2e-40) | the market and its instruments are visible before signing in | 0.2 s | ✅ pass |
| [E2E-41](../../../testing/e2e.md#e2e-41) | prices need a signed-in user | 0.2 s | ✅ pass |
| [E2E-42](../../../testing/e2e.md#e2e-42) | quotes come back in the order asked; unknown symbols are named | 0.2 s | ✅ pass |
| [E2E-43](../../../testing/e2e.md#e2e-43) | candles never show the future | 0.2 s | ✅ pass |
| [E2E-44](../../../testing/e2e.md#e2e-44) | the price stream starts with the current state, then ticks live with rising seq | 2.4 s | ✅ pass |
| [E2E-45](../../../testing/e2e.md#e2e-45) | every streamed price lies inside its minute's high and low | 9.7 s | ✅ pass |
| [E2E-46](../../../testing/e2e.md#e2e-46) | one client can hold at most five price streams | 0.3 s | ✅ pass |
| [E2E-47](../../../testing/e2e.md#e2e-47) | a bad stream request is refused before it starts | 0.3 s | ✅ pass |
| [E2E-50](../../../testing/e2e.md#e2e-50) | open a bank account with a UPI PIN, then a Sprout account linked to it, with a demat account | 0.3 s | ✅ pass |
| [E2E-51](../../../testing/e2e.md#e2e-51) | KYC refuses the underage, business PANs, unknown UPI addresses and a second account per PAN | 0.7 s | ✅ pass |
| [E2E-52](../../../testing/e2e.md#e2e-52) | add money: approved in the bank with the PIN, it arrives in Sprout | 1.0 s | ✅ pass |
| [E2E-53](../../../testing/e2e.md#e2e-53) | wrong PINs count down; declining ends the deposit; nothing moves | 1.0 s | ✅ pass |
| [E2E-54](../../../testing/e2e.md#e2e-54) | retrying with the same Idempotency-Key makes one deposit and one bank request | 0.4 s | ✅ pass |
| [E2E-55](../../../testing/e2e.md#e2e-55) | withdraw: never more than you have; what you take arrives in the bank | 1.1 s | ✅ pass |
| [E2E-56](../../../testing/e2e.md#e2e-56) | ten withdrawals racing for money that covers five: exactly five succeed | 0.8 s | ✅ pass |
| [E2E-57](../../../testing/e2e.md#e2e-57) | a forged bank callback is refused | 0.3 s | ✅ pass |
| [E2E-58](../../../testing/e2e.md#e2e-58) | nobody else can see my payments or approve my bank requests | 0.6 s | ✅ pass |
| [E2E-59](../../../testing/e2e.md#e2e-59) | an unanswered payment request expires, and so does the deposit | 33.0 s | ✅ pass |
| [E2E-60](../../../testing/e2e.md#e2e-60) | buy for delivery at the market: executed on the exchange, paid with its charges, held as T1 shares | 1.0 s | ✅ pass |
| [E2E-61](../../../testing/e2e.md#e2e-61) | sell only what you hold; the proceeds wait for settlement | 1.1 s | ✅ pass |
| [E2E-62](../../../testing/e2e.md#e2e-62) | a limit order away from the market rests with its money blocked; cancelling gives back every paisa | 0.8 s | ✅ pass |
| [E2E-63](../../../testing/e2e.md#e2e-63) | an order beyond your money is rejected and blocks nothing | 1.0 s | ✅ pass |
| [E2E-64](../../../testing/e2e.md#e2e-64) | intraday: a fifth as margin, a round trip books its profit or loss, and the books add up | 0.8 s | ✅ pass |
| [E2E-65](../../../testing/e2e.md#e2e-65) | intraday lets you sell first and buy back; delivery doesn't let you sell what you don't own | 1.1 s | ✅ pass |
| [E2E-66](../../../testing/e2e.md#e2e-66) | the exchange's rules: prices on the tick and inside the day's band; unknown shares are refused | 1.0 s | ✅ pass |
| [E2E-67](../../../testing/e2e.md#e2e-67) | retrying an order with the same Idempotency-Key places it once | 1.1 s | ✅ pass |
| [E2E-68](../../../testing/e2e.md#e2e-68) | nobody else can see or cancel my orders | 1.2 s | ✅ pass |
| [E2E-69](../../../testing/e2e.md#e2e-69) | a forged execution report is refused | 1.0 s | ✅ pass |
| [E2E-70](../../../testing/e2e.md#e2e-70) | today's contract note lists every execution and charge, and adds up | 1.4 s | ✅ pass |
| [E2E-71](../../../testing/e2e.md#e2e-71) | the funds statement shows the deposit and every trade, and ends at the cash Sprout shows | 0.9 s | ✅ pass |
| [E2E-72](../../../testing/e2e.md#e2e-72) | profit and loss puts the intraday round trip under intraday, with charges beside | 1.1 s | ✅ pass |
| [E2E-73](../../../testing/e2e.md#e2e-73) | the holdings statement is the depository's record: shares bought today aren't in it until they settle | 0.9 s | ✅ pass |
| [E2E-74](../../../testing/e2e.md#e2e-74) | statements are only for signed-in customers with an account | 1.3 s | ✅ pass |
| [E2E-80](../../../testing/e2e.md#e2e-80) | a plan started now buys its first instalment at once, through the real order service | 2.1 s | ✅ pass |
| [E2E-81](../../../testing/e2e.md#e2e-81) | a plan whose amount can't buy one share skips the month and says why | 2.1 s | ✅ pass |
| [E2E-82](../../../testing/e2e.md#e2e-82) | the habit picture follows from what was bought: a streak, badges, pending points | 1.9 s | ✅ pass |
| [E2E-83](../../../testing/e2e.md#e2e-83) | squads rank friends by the habit, and show a range only by choice | 3.3 s | ✅ pass |
| [E2E-84](../../../testing/e2e.md#e2e-84) | readiness gives plain advice, and Future You shows what a monthly amount could become | 0.7 s | ✅ pass |
| [E2E-90](../../../testing/e2e.md#e2e-90) | AutoPay is asked for by Sprout and approved once in Sprout Bank with the PIN | 2.2 s | ✅ pass |
| [E2E-91](../../../testing/e2e.md#e2e-91) | money put in a pot buys whole shares of its share, tagged with the pot | 2.4 s | ✅ pass |
| [E2E-92](../../../testing/e2e.md#e2e-92) | a UPI spend is rounded up, swept under AutoPay into the pot, and invested | 5.9 s | ✅ pass |
| [E2E-93](../../../testing/e2e.md#e2e-93) | without AutoPay, spends aren't shared and nothing is taken | 1.5 s | ✅ pass |
| [E2E-94](../../../testing/e2e.md#e2e-94) | a UPI payment with the wrong PIN is refused and moves nothing | 1.6 s | ✅ pass |
| [E2E-95](../../../testing/e2e.md#e2e-95) | the vault spends only vested points: a new investor's pending points can't buy anything yet | 1.0 s | ✅ pass |
| [E2E-96](../../../testing/e2e.md#e2e-96) | a friend's referral code links two customers; nothing is earned until the friend invests for 3 months | 2.0 s | ✅ pass |
| [E2E-97](../../../testing/e2e.md#e2e-97) | this month's challenges and the year wrapped follow from what was bought | 0.9 s | ✅ pass |
| [E2E-100](../../../testing/e2e.md#e2e-100) | a visitor chooses who to explore as and is signed in as them, a real customer | 0.2 s | ✅ pass |
| [E2E-101](../../../testing/e2e.md#e2e-101) | visitors in the same group are given different people, least recently explored first | 0.4 s | ✅ pass |

## PERF-01: sign-in throughput

First 30 s: ramp from 2 to 10 sign-ins a second. Then 60 s steady at 10 a second (half the edge host's capacity). Every request from a different client.

| Measure | Warm-up (30 s) | Steady (60 s) |
|---|---|---|
| Median | 98 ms | 96 ms |
| p95 | 114 ms | 114 ms |
| p99 | 120 ms | 128 ms |
| Slowest | 134 ms | 153 ms |
| Requests | 180 | 601 |
| Failed | 0.00% | 0.00% |

| Threshold | Rule | Result |
|---|---|---|
| `http_req_duration{scenario:steady}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:steady}` | `p(99)<1000` | ✅ pass |
| `http_req_duration{scenario:warmup}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:warmup}` | `p(99)<1000` | ✅ pass |
| `http_req_failed{scenario:warmup}` | `rate<0.01` | ✅ pass |
| `checks{scenario:steady}` | `rate>0.99` | ✅ pass |
| `http_req_failed{scenario:steady}` | `rate<0.01` | ✅ pass |

## PERF-02: sign-in straight after a restart

The edge host is restarted (it warms itself up before reporting ready), then gets 10 sign-ins a second for 30 s from the moment it is ready.

| Measure | Value |
|---|---|
| Median / p95 / p99 / slowest | 99 ms / 128 ms / 158 ms / 198 ms |
| Failed | 0.00% |

| Threshold | Rule | Result |
|---|---|---|
| `checks{scenario:cold}` | `rate>0.99` | ✅ pass |
| `http_req_failed{scenario:cold}` | `rate<0.01` | ✅ pass |
| `http_req_duration{scenario:cold}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:cold}` | `p(99)<1000` | ✅ pass |

## PERF-03: price fan-out

200 clients, each streaming 5 symbols through the gateway for 60 s. Latency is from the moment market data produced a tick to the moment a client read it, measured on one clock.

| Measure | Value |
|---|---|
| Streams opened | 200 of 200 |
| Streams that ended early | 0 |
| Ticks delivered | 511,144 (8,519 a second) |
| Delivery latency p50 / p95 / p99 / max | 5 ms / 25 ms / 51 ms / 273 ms |
| Conflated (a client got only the newest price) | 11,716 times, 2.3% of ticks |

Pass when every stream opens and stays open, p95 is under 250 ms and p99 under 1 s.

## PERF-04: orders under load

20 funded customers place market buys through the gateway at a steady 5 orders a second for 60 s, each through the risk checks, the ledger and the exchange. Afterwards every customer's holdings are compared with what their filled orders bought.

| Measure | Value |
|---|---|
| Orders filled | 300 of 300 |
| Placement latency p50 / p95 / p99 / max | 50 ms / 65 ms / 75 ms / 101 ms |
| Server errors / failed calls | 0 / 0 |
| Holdings that don't match what was bought | 0 |

Pass when every order fills, nothing fails server-side, holdings match exactly, p95 is under 1 s and p99 under 2 s.

## Memory under load

| Host | Peak | Limit |
|---|---|---|
| edge | 252 MiB | 384 MiB |
| trading | 248 MiB | 320 MiB |
| money | 234 MiB | 320 MiB |
| street | 202 MiB | 320 MiB |

## TRACE-01: One request, followed through every service

Hypothesis: An order placed with a request id (and a forged trace from the client) can be followed from the gateway through the order service to the exchange: every service's log lines for it carry the same request id and the same trace, and that trace is the gateway's own, never the client's.

| Observed | |
|---|---|
| Order | 201 FILLED |
| Request id echoed by the gateway | trace01-b7cdfadc9812 |
| Log lines with the request id, by host | edge 0, trading 1, money 0, street 1 |
| Services that logged it | sprout-exchange, sprout-oms |
| Trace ids on those lines | 21d202a4302d2f80b959017f59e6e7a8 |

| Check | Result |
|---|---|
| the order filled | ✅ pass |
| the gateway kept the request id | ✅ pass |
| the order service and the exchange both logged it | ✅ pass |
| one trace across every service | ✅ pass |
| the gateway's trace, not the client's | ✅ pass |

## CHAOS-01: The database goes away

Hypothesis: With Postgres stopped, sign-in answers 503 with Retry-After in under 3 s (never hanging until the gateway's 5 s timeout), and recovers within 30 s of Postgres returning, without a restart.

| Observed | |
|---|---|
| Before (wrong password, so 401 is healthy) | 401 in 94 ms |
| Database down, try 1 | 503 in 2,037 ms |
| Database down, try 2 | 503 in 2,016 ms |
| Database down, try 3 | 503 in 2,028 ms |
| Retry-After | 5 |
| Answering normally again after Postgres started | 12.3 s |

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
| Ticks streamed to a client in the 10 s NATS was down | 176 |
| Trading host health while NATS was down | UP |
| Quote while NATS was down | 200 in 11 ms |
| Reconnected after NATS started | 0.6 s |
| Events published in 3 s after reconnecting | 611 |

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
| Sign-in (wrong password, so 401 is healthy) | 401 in 123 ms |
| My account | 200 in 30 ms |
| A quote | 503 in 2,005 ms (UPSTREAM_UNAVAILABLE) |
| Opening a new stream | 503 in 1,585 ms |
| Quotes working again after restart | 17.3 s |
| Edge host | Up 4 minutes (healthy) |

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
| Withdrawal while the bank was down | 201 PROCESSING in 2,016 ms |
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
| Deposit completed after the money host started | 7.1 s |
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
| Order while the exchange was down | 201 PENDING in 1,216 ms, blocked ₹3596.07 |
| Cash / blocked while down | 16403.93 / 3596.07 |
| Ended after the exchange came back | REJECTED after 29.5 s |
| Rejection | UNAVAILABLE |
| Cash / blocked after | 20000.00 / 0.00 |

| Check | Result |
|---|---|
| accepted, money blocked, outcome left open | ✅ pass |
| answered without waiting for the exchange | ✅ pass |
| ended within 120 s of the exchange returning | ✅ pass |
| rejected as never placed (not filled from nowhere) | ✅ pass |
| every paisa back | ✅ pass |

## CHAOS-07: The money host goes away during trading

Hypothesis: With the ledger, accounts and payments unreachable, trading fails safe: a new order is refused at once with a clear 503 and nothing is placed or blocked, while prices and the order book stay readable. When the money host is back, orders go through again within 180 s and the books match every fill to the paisa.

| Observed | |
|---|---|
| Order while the money host was down | 503 UPSTREAM_UNAVAILABLE in 1,026 ms |
| Order list / quotes while down | 200 (1 orders, 1 before) / 200 |
| Orders accepted again after | 6.3 s |
| Orders placed in all | 2 FILLED, 1 FILLED, 2 FILLED |
| Cash / blocked after | 11293.55 / 0.00 (expected cash 11293.55) |

| Check | Result |
|---|---|
| refused as unavailable, not left hanging | ✅ pass |
| answered without waiting | ✅ pass |
| nothing was placed while down | ✅ pass |
| prices kept flowing | ✅ pass |
| trading resumed within 180 s | ✅ pass |
| every order placed filled | ✅ pass |
| nothing blocked is left over | ✅ pass |
| the books match every fill | ✅ pass |

## RECON-01: The books agree with the bank

Hypothesis: After every test and every failure above: the ledger balances (assets equal liabilities), and what it says Sprout holds at the bank is exactly what Sprout Bank says it holds, to the paisa.

| Observed | |
|---|---|
| Ledger assets / liabilities | ₹2,173,442.25 / ₹2,173,442.25 |
| Ledger: Sprout's money at the bank | ₹2,173,442.25 |
| Sprout Bank: Sprout's account | ₹2,173,442.25 |
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
| Orders executed (Sprout) / trades (exchange) | 352 / 352 |
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

## RECON-03: After settlement, shares and money agree everywhere

Hypothesis: For every client, the shares the depository holds in their demat account are exactly the delivered shares Sprout shows them; their unsettled money is exactly the proceeds of days not yet settled; and what the ledger says Sprout owes or is owed by the clearing corporation is exactly the unsettled days' trades.

| Observed | |
|---|---|
| Trade dates settled | 1 |
| Clients whose demat holdings differ from Sprout's | 0 |
| Clients whose unsettled money is wrong | 0 |
| Owed to clearing: ledger / unsettled trades | ₹288.10 / ₹288.10 |
| Owed by clearing: ledger / unsettled trades | ₹0.00 / ₹0.00 |

| Check | Result |
|---|---|
| at least one day settled | ✅ pass |
| demat holdings match | ✅ pass |
| unsettled money matches | ✅ pass |
| clearing balances are only the unsettled days' | ✅ pass |

## RECON-04: Sprout's own reconciliation agrees

Hypothesis: At the end of the run, Sprout's reconciliation service (which reads every book through its owner's API, as it does every day in production) finds every check passing: the ledger, the bank, held and unsettled money, executions against the exchange, demat holdings, and settlements.

| Observed | |
|---|---|
| On-demand run | PASS |
| BANK_MATCHES_LEDGER | PASS: All Sprout's money at the bank agree. |
| DEMAT_MATCHES_HOLDINGS | PASS: All customers' delivered shares agree. |
| HOLDS_MATCH_ORDERS | PASS: All customers' held money agree. |
| LEDGER_BALANCED | PASS: The ledger balances: assets â‚¹2173442.25 = liabilities â‚¹2173442.25. |
| SETTLEMENTS_HEALTHY | PASS: 1 recent settlement(s) completed; none broken or late. |
| TRADES_MATCH_EXCHANGE | PASS: All executions and exchange trades since 2026-10-01 agree. |
| UNSETTLED_MATCHES_ORDERS | PASS: All customers' unsettled money agree. |
| Scheduled runs during the run (sessions past midday) | 2026-10-05 PASS |

| Check | Result |
|---|---|
| the run completed | ✅ pass |
| every check passes | ✅ pass |
| all seven checks ran | ✅ pass |

## SETTLE-01: A trading day settles T+1

Hypothesis: Once the next session begins, the clearing corporation nets the day's trades, takes in the sellers' shares, and tells Sprout what it owes or is owed; Sprout's back office finds that matches its own books exactly (no break), the money moves through Sprout Bank, buyers' shares reach their demat accounts, and clients' sale proceeds become cash. All within one session of the trade date.

| Observed | |
|---|---|
| Trade date | 2026-10-05 |
| Back office | COMPLETED after 669.7 s |
| Clearing corporation (status, funds, paise) | SETTLED PAY 16445800 |
| Lines / delivered / short | 179 / 172 / 0 |
| Breaks | 0 |
| Clients settled for the day | 1 |

| Check | Result |
|---|---|
| settled end to end | ✅ pass |
| the obligation matched Sprout's books (no break) | ✅ pass |
| nobody was short | ✅ pass |
| clients' proceeds and shares released | ✅ pass |

## Files

- `e2e/`: JUnit reports
- `perf-01-k6-summary.json`: every k6 metric
- `perf-02-k6-summary.json`: sign-in straight after a restart
- `perf-03-summary.json`: the fan-out result
- `perf-04-summary.json`: the order load result
- `memory-during.txt`: host memory and CPU every 5 s under load
- `trace-*.json`, `chaos-*.json`, `settle-*.json`, `recon-*.json`: each experiment's observations and checks
- `edge.log`, `trading.log`, `money.log`, `street.log`: the hosts' structured logs for the whole run
