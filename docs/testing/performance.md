# Performance tests

Each test states a hypothesis and the thresholds that decide it. They run inside the pre-prod
environment against the gateway, and a crossed threshold fails the release. Request/response tests use
[k6](https://k6.io/); long-lived price streams, which k6 can't hold open, use a small Java load
generator (`loadgen`) from the end-to-end module.

Load numbers are deliberately far above what a phone-hosted app will see. The point is to know where the
limits are and to catch regressions, not to claim exchange-scale throughput.

## PERF-01: sign-in throughput { #perf-01 }

**Hypothesis.** At a steady 20 sign-ins per second, each from a different client, the edge host keeps
p95 latency under 500 ms and fails fewer than 1% of requests, inside its 384 MB memory limit. While the
JVM is freshly started, latency is worse, but no request comes near the gateway's 5 s timeout.

**Why sign-in.** It is the most expensive request the edge serves: bcrypt is deliberately slow (cost 10),
and every sign-in writes a session and a refresh token. If sign-in holds, cheaper requests will.

| Setting | Value |
|---|---|
| Script | [`preprod/k6/perf-01-signin.js`](https://github.com/SaiNayakk/sprout-platform/blob/main/preprod/k6/perf-01-signin.js) |
| Setup | 50 accounts created before the test starts |
| Warm-up | 30 s, ramping from 2 to 20 sign-ins a second, on the JVM pre-prod just started |
| Steady | 60 s at a constant 20 sign-ins a second (about 1,200) |
| Clients | A random address per request, so the per-client sign-in limit doesn't apply |

| Phase | Threshold | Pass when |
|---|---|---|
| Steady | `http_req_duration` | p95 < 500 ms and p99 < 1000 ms |
| Steady | `http_req_failed` | rate < 1% |
| Steady | `checks` | > 99% of responses are `200 AUTHENTICATED` |
| Warm-up | `http_req_duration` | p99 < 3000 ms |
| Warm-up | `http_req_failed` | rate < 1% |
| Both | Memory (recorded) | Edge host stays under its limit; sampled every 5 s |

### Finding: a cold JVM has a slow tail { #perf-01-cold-start }

The first version of this test ran 60 s at 20 a second straight onto a freshly started host, and
**failed**. Median latency was fine, but the tail wasn't. The same test again a minute later, on the now
warm JVM, passed easily:

| Same load, same host | Median | p95 | p99 | Slowest | Failed |
|---|---|---|---|---|---|
| JVM that had only served the E2E suite | 135 ms | 878 ms | 1,913 ms | 2,674 ms | 0% |
| One minute later | 130 ms | 215 ms | 297 ms | 391 ms | 0% |

**Why.** Production JVM flags stop the JIT at its quick first tier to save memory, but even that needs
the hot code to run for a while before it is compiled. bcrypt dominates: at 20 sign-ins a second the
host used about three CPU cores.

**What changed.** The test now measures the two phases separately and holds each to its own bar, rather
than letting a warm run hide the cold-start tail or a cold run fail a healthy steady state.

**Follow-up.** A deploy puts a cold JVM straight into traffic. Options to evaluate: warm the hot paths
before reporting ready, class data sharing (CDS) to cut start-up work, and lowering bcrypt's cost only
if the security trade-off is written down.

**Results of every run:** [Evidence from runs](../reliability/runs/index.md).

## PERF-03: price fan-out { #perf-03 }

**Hypothesis.** 200 clients, each streaming 5 symbols through the gateway at once, all get their
streams, keep them for the whole test, and receive each price change within 250 ms at p95 and 1 s at
p99, inside both hosts' memory limits.

**Why.** Streaming is the opposite load to sign-in: few requests, many open connections, a constant
flow of small writes. It exercises the gateway's stream relay, market data's per-client fan-out and
conflation, and the memory both hold per open stream.

| Setting | Value |
|---|---|
| Client | [`Perf03StreamFanoutTest`](https://github.com/SaiNayakk/sprout-platform/blob/main/e2e/src/test/java/app/sprout/e2e/Perf03StreamFanoutTest.java), run by the `loadgen` container |
| Load | 200 streams, 5 symbols each (all 21 instruments covered), 60 s, opened over 2 s |
| Market | 30 times real speed: about 420 price changes a second across all instruments |
| Clients | A different address per stream, as real users would be |
| Measured | For every tick: the time between market data producing it (`emittedAt`) and the client reading it |

| Threshold | Pass when |
|---|---|
| Streams opened | all 200 |
| Streams ended early | none |
| Delivery latency | p95 < 250 ms and p99 < 1000 ms |
| Memory (recorded) | edge and trading hosts under their limits |

### Finding: measure latency on one clock { #perf-03-one-clock }

The first trial ran the load client on the laptop and reported a **median latency of −122 ms**.
Latency was the client's clock minus the service's clock, and the laptop's clock and the Docker VM's
differ by more than the latency being measured. The load client now runs inside the Docker network
(the `loadgen` container), on the same clock as the services. Measured that way the trial gave p50
7 ms, p95 50 ms and p99 86 ms.

The same applies on the phone: any latency comparing two machines' clocks needs those clocks
synchronised far better than the latency itself, or it measures the clocks.

## Planned

| Id | What | When |
|---|---|---|
| PERF-02 | Authenticated reads (`GET /users/me`) at 100/s: the gateway's token verification cost | With the next gateway release |
| PERF-04 | Order placement through to execution report, end to end | Phase 2 (orders) |
| SOAK-01 | Sign-in at 5/s for 1 hour: memory must stay flat (no leak) | Before the first phone release of each host |
