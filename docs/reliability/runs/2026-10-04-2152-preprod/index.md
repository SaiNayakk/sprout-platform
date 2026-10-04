# Pre-prod run 2026-10-04-2152-preprod

A fresh environment built from the pinned releases, tested, then destroyed. Raw evidence sits next to this page.

## Release under test

| Host | Service | Version |
|---|---|---|
| edge | sprout-identity | `0.2.2` |
| edge | sprout-gateway | `0.2.4` |
| trading | sprout-marketdata | `0.1.1` |
| | sprout-platform | `v0.2.0-dirty` |

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

## End-to-end suite

24 of 24 passed.

| Id | Journey or edge case | Time | Result |
|---|---|---|---|
| [E2E-01](../../../testing/e2e.md#e2e-01) | sign up, sign in and see your account | 0.3 s | ✅ pass |
| [E2E-02](../../../testing/e2e.md#e2e-02) | turn on two-factor, then sign in with a code | 29.5 s | ✅ pass |
| [E2E-03](../../../testing/e2e.md#e2e-03) | refresh tokens rotate; sign out ends the session | 0.5 s | ✅ pass |
| [E2E-10](../../../testing/e2e.md#e2e-10) | duplicate email, any case or spacing, is refused | 0.1 s | ✅ pass |
| [E2E-11](../../../testing/e2e.md#e2e-11) | weak passwords are refused with a reason | 0.1 s | ✅ pass |
| [E2E-12](../../../testing/e2e.md#e2e-12) | malformed JSON and unknown fields are refused | 0.1 s | ✅ pass |
| [E2E-20](../../../testing/e2e.md#e2e-20) | wrong password and unknown email look identical | 0.3 s | ✅ pass |
| [E2E-21](../../../testing/e2e.md#e2e-21) | five wrong passwords lock the account, even for the right one | 0.6 s | ✅ pass |
| [E2E-22](../../../testing/e2e.md#e2e-22) | a two-factor code works once and a challenge only once | 20.2 s | ✅ pass |
| [E2E-30](../../../testing/e2e.md#e2e-30) | a stolen refresh token, used after the owner, ends the session | 0.3 s | ✅ pass |
| [E2E-31](../../../testing/e2e.md#e2e-31) | two refreshes racing with one token: exactly one wins | 1.1 s | ✅ pass |
| [E2E-32](../../../testing/e2e.md#e2e-32) | missing, tampered and junk tokens are refused at the gateway | 0.2 s | ✅ pass |
| [E2E-33](../../../testing/e2e.md#e2e-33) | a client can't pretend to be someone else with X-User-Id | 0.3 s | ✅ pass |
| [E2E-34](../../../testing/e2e.md#e2e-34) | sign-in is rate limited per client | 1.2 s | ✅ pass |
| [E2E-35](../../../testing/e2e.md#e2e-35) | unknown routes, path traversal and oversized bodies are refused | 0.8 s | ✅ pass |
| [E2E-36](../../../testing/e2e.md#e2e-36) | one request id follows a request through the gateway and identity | 0.1 s | ✅ pass |
| [E2E-40](../../../testing/e2e.md#e2e-40) | the market and its instruments are visible before signing in | 0.3 s | ✅ pass |
| [E2E-41](../../../testing/e2e.md#e2e-41) | prices need a signed-in user | 0.3 s | ✅ pass |
| [E2E-42](../../../testing/e2e.md#e2e-42) | quotes come back in the order asked; unknown symbols are named | 0.3 s | ✅ pass |
| [E2E-43](../../../testing/e2e.md#e2e-43) | candles never show the future | 0.4 s | ✅ pass |
| [E2E-44](../../../testing/e2e.md#e2e-44) | the price stream starts with the current state, then ticks live with rising seq | 2.5 s | ✅ pass |
| [E2E-45](../../../testing/e2e.md#e2e-45) | every streamed price lies inside its minute's high and low | 9.7 s | ✅ pass |
| [E2E-46](../../../testing/e2e.md#e2e-46) | one client can hold at most five price streams | 0.5 s | ✅ pass |
| [E2E-47](../../../testing/e2e.md#e2e-47) | a bad stream request is refused before it starts | 0.5 s | ✅ pass |

## PERF-01: sign-in throughput

First 30 s: ramp from 2 to 10 sign-ins a second. Then 60 s steady at 10 a second (half the edge host's capacity). Every request from a different client.

| Measure | Warm-up (30 s) | Steady (60 s) |
|---|---|---|
| Median | 116 ms | 114 ms |
| p95 | 178 ms | 317 ms |
| p99 | 343 ms | 743 ms |
| Slowest | 677 ms | 967 ms |
| Requests | 179 | 601 |
| Failed | 0.00% | 0.00% |

| Threshold | Rule | Result |
|---|---|---|
| `checks{scenario:steady}` | `rate>0.99` | ✅ pass |
| `http_req_failed{scenario:warmup}` | `rate<0.01` | ✅ pass |
| `http_req_failed{scenario:steady}` | `rate<0.01` | ✅ pass |
| `http_req_duration{scenario:warmup}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:warmup}` | `p(99)<1000` | ✅ pass |
| `http_req_duration{scenario:steady}` | `p(95)<500` | ✅ pass |
| `http_req_duration{scenario:steady}` | `p(99)<1000` | ✅ pass |

## PERF-02: sign-in straight after a restart

The edge host is restarted (it warms itself up before reporting ready), then gets 10 sign-ins a second for 30 s from the moment it is ready.

| Measure | Value |
|---|---|
| Median / p95 / p99 / slowest | 121 ms / 230 ms / 326 ms / 827 ms |
| Failed | 0.00% |

| Threshold | Rule | Result |
|---|---|---|
| `checks{scenario:cold}` | `rate>0.99` | ✅ pass |
| `http_req_failed{scenario:cold}` | `rate<0.01` | ✅ pass |
| `http_req_duration{scenario:cold}` | `p(99)<1000` | ✅ pass |
| `http_req_duration{scenario:cold}` | `p(95)<500` | ✅ pass |

## PERF-03: price fan-out

200 clients, each streaming 5 symbols through the gateway for 60 s. Latency is from the moment market data produced a tick to the moment a client read it, measured on one clock.

| Measure | Value |
|---|---|
| Streams opened | 200 of 200 |
| Streams that ended early | 0 |
| Ticks delivered | 437,397 (7,290 a second) |
| Delivery latency p50 / p95 / p99 / max | 16 ms / 115 ms / 343 ms / 1,945 ms |
| Conflated (a client got only the newest price) | 45,720 times, 10.5% of ticks |

Pass when every stream opens and stays open, p95 is under 250 ms and p99 under 1 s.

## Memory under load

| Host | Peak | Limit |
|---|---|---|
| edge | 267 MiB | 384 MiB |
| trading | 211 MiB | 256 MiB |

## CHAOS-01: The database goes away

Hypothesis: With Postgres stopped, sign-in answers 503 with Retry-After in under 3 s (never hanging until the gateway's 5 s timeout), and recovers within 30 s of Postgres returning, without a restart.

| Observed | |
|---|---|
| Before (wrong password, so 401 is healthy) | 401 in 412 ms |
| Database down, try 1 | 503 in 2,165 ms |
| Database down, try 2 | 503 in 2,111 ms |
| Database down, try 3 | 503 in 2,108 ms |
| Retry-After | 5 |
| Answering normally again after Postgres started | 6.8 s |

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
| Ticks streamed to a client in the 10 s NATS was down | 152 |
| Trading host health while NATS was down | UP |
| Quote while NATS was down | 200 in 21 ms |
| Reconnected after NATS started | 0.6 s |
| Events published in 3 s after reconnecting | 602 |

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
| Sign-in (wrong password, so 401 is healthy) | 401 in 173 ms |
| My account | 200 in 70 ms |
| A quote | 503 in 2,135 ms (UPSTREAM_UNAVAILABLE) |
| Opening a new stream | 503 in 2,110 ms |
| Quotes working again after restart | 18.1 s |
| Edge host | Up 3 minutes (healthy) |

| Check | Result |
|---|---|
| sign-in unaffected | ✅ pass |
| accounts unaffected | ✅ pass |
| quotes fail fast with 503 | ✅ pass |
| new streams refused fast | ✅ pass |
| open streams end within 5 s | ✅ pass |
| market data back within 60 s | ✅ pass |

## Dashboard

The Grafana dashboard for the whole run, captured automatically.

![Grafana dashboard for this run](grafana-edge.png)

## Files

- `e2e/`: JUnit reports
- `perf-01-k6-summary.json`: every k6 metric
- `perf-02-k6-summary.json`: sign-in straight after a restart
- `perf-03-summary.json`: the fan-out result
- `memory-during.txt`: host memory and CPU every 5 s under load
- `chaos-*.json`: each experiment's observations and checks
- `edge.log`, `trading.log`: the hosts' structured logs for the whole run
- `metrics.jsonl`: counters queried from Prometheus at the end of the run
