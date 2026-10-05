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

Today there is one region: the phone. The plan is a second region on the laptop, with Cloudflare
sending traffic to whichever is healthy, and each region owning a slice of users (cells) so that losing
one region affects only its own users until failover. That is CHAOS-09.
