# Performance tests

Each test states a hypothesis and the thresholds that decide it. They run with
[k6](https://k6.io/) inside the pre-prod environment, against the gateway, and k6 exits non-zero when a
threshold is crossed, which fails the release.

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

## Planned

| Id | What | When |
|---|---|---|
| PERF-02 | Authenticated reads (`GET /users/me`) at 100/s: the gateway's token verification cost | With the next gateway release |
| PERF-03 | Market data fan-out: ticks per second to many connected clients | Phase 1 (market data) |
| PERF-04 | Order placement through to execution report, end to end | Phase 2 (orders) |
| SOAK-01 | Sign-in at 5/s for 1 hour: memory must stay flat (no leak) | Before the first phone release of each host |
