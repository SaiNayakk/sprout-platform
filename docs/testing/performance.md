# Performance tests

Each test states a hypothesis and the thresholds that decide it. They run inside the pre-prod
environment against the gateway, and a crossed threshold fails the release. Request/response tests use
[k6](https://k6.io/); long-lived price streams, which k6 can't hold open, use a small Java load
generator (`loadgen`) from the end-to-end module.

Load numbers are deliberately far above what a phone-hosted app will see. The point is to know where the
limits are and to catch regressions, not to claim exchange-scale throughput.

## PERF-01: sign-in throughput { #perf-01 }

**Hypothesis.** At a steady 10 sign-ins per second, each from a different client, the edge host keeps
p95 latency under 500 ms and fails fewer than 1% of requests, inside its 384 MB memory limit. While the
JVM is freshly started, latency is worse, but no request comes near the gateway's 5 s timeout.

**Why sign-in.** It is the most expensive request the edge serves: bcrypt is deliberately slow (cost 10),
and every sign-in writes a session and a refresh token. If sign-in holds, cheaper requests will.

| Setting | Value |
|---|---|
| Script | [`preprod/k6/perf-01-signin.js`](https://github.com/SaiNayakk/sprout-platform/blob/main/preprod/k6/perf-01-signin.js) |
| Setup | 50 accounts created before the test starts |
| Warm-up | 30 s, ramping from 2 to 10 sign-ins a second |
| Steady | 60 s at a constant 10 sign-ins a second (about 600): half the host's capacity |
| Clients | A random address per request, so the per-client sign-in limit doesn't apply |

| Phase | Threshold | Pass when |
|---|---|---|
| Steady | `http_req_duration` | p95 < 500 ms and p99 < 1000 ms |
| Steady | `http_req_failed` | rate < 1% |
| Steady | `checks` | > 99% of responses are `200 AUTHENTICATED` |
| Warm-up | `http_req_duration` | p95 < 500 ms and p99 < 1000 ms (since the warm-up fix; was p99 < 3000 ms) |
| Warm-up | `http_req_failed` | rate < 1% |
| Both | Memory (recorded) | Edge host stays under its limit; sampled every 5 s |

### Finding: sign-in capacity is about 20 a second, and the test ran at it { #perf-01-capacity }

Until 2026-10-05 this test ran at 20 sign-ins a second. With the whole pre-prod environment running,
its latency tail came and went between runs (p95 from 160 ms to 920 ms) even on a warm JVM. The CPU
samples explained it: at 20 a second the edge host used **4 to 4.5 cores**. Sign-in is CPU-bound on
purpose (bcrypt is deliberately slow), and the JVM flags that save memory on the phone
(`TieredStopAtLevel=1`, quick compilation only) make it slower still. So 20 a second was the host's
capacity on this laptop, and any other load (Grafana, Windows) made requests queue.

A gate run at capacity measures the machine's mood, not the service. It now runs at 10 a second
(half the capacity, and still about 50 times what the phone will see) with the strict bar on both
phases. Capacity itself is recorded here rather than gated.

Follow-up: measure whether full JIT compilation is worth its extra memory on the phone, where the
CPU is slower and bcrypt's cost matters more.

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

**Fixed.** A deploy put a cold JVM straight into traffic. The edge host now warms itself up before
it reports ready: it holds both services at readiness `REFUSING_TRAFFIC` (so health checks, pre-prod
and the deploy's smoke tests wait), signs in 300 times to an address that can't exist (identity
checks a dummy hash for unknown emails, so the real password, database and JSON paths run and nothing
is created), calls the gateway 100 times, then reports ready.

How much warm-up is enough depends on how busy the machine is. 60 sign-ins (about 3.5 s) passed on a
quiet machine but not with the whole pre-prod environment competing for CPU, where p99 was still
1,050 ms; 300 (about 10 s) gave p95 267 ms and p99 421 ms. So it does 300, and on the slower phone it
simply takes longer to report ready. Both PERF-01
phases are now held to the same bar, and [PERF-02](#perf-02) tests the restart directly.

Lowering bcrypt's cost was rejected: it would trade every user's password strength for a few
seconds after a deploy.

## PERF-02: sign-in straight after a restart { #perf-02 }

**Hypothesis.** Restarted, the edge host takes 10 sign-ins a second from the moment it reports ready
with the same latency as a warm host: p95 under 500 ms, p99 under 1 s.

**Method.** The accounts are created first, in a separate run, because creating them on the fresh
host would warm it up and spoil the measurement. Then the edge host is restarted, pre-prod waits for
it to report ready, and k6 sends 10 sign-ins a second for 30 s
([`perf-02-cold-signin.js`](https://github.com/SaiNayakk/sprout-platform/blob/main/preprod/k6/perf-02-cold-signin.js)).

| Straight after a restart | Median | p95 | p99 | Slowest |
|---|---|---|---|---|
| Before the warm-up (PERF-01's first run) | 135 ms | 878 ms | 1,913 ms | 2,674 ms |
| 60 warm-up sign-ins, quiet machine | 127 ms | 217 ms | 322 ms | 831 ms |
| 60 warm-up sign-ins, full pre-prod running | 207 ms | 825 ms | 1,050 ms | 1,519 ms |
| 300 warm-up sign-ins, full pre-prod running | 128 ms | 267 ms | 421 ms | 847 ms |

These were measured at 20 a second. A later full run at 20 a second failed again (p95 720 ms) for the
reason in the capacity finding above, which is why PERF-02 now runs at 10 a second too.

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

### What the trading host's memory is { #perf-03-memory }

The trading host peaked at about 207 MiB of its 256 MiB limit during PERF-03, so it was measured with
Java's native memory tracking under the same load (committed memory when the test ended):

| Part of the JVM | Committed |
|---|---|
| Java heap | 100 MB (of a 128 MB maximum; 30-70 MB in use, per the dashboard) |
| Class metadata (metaspace) | 34 MB |
| Symbols | 14.5 MB |
| Compiled code | 13 MB |
| Shared classes | 12 MB |
| Threads, GC and the rest | about 10 MB |
| **Total** | **189 MB** |

Nothing grows with time or leaks: most of the headroom is heap the JVM keeps after a burst, by
design. So nothing changes now. When orders and risk join this host (Phase 3), its budget goes to
320 MB with a 160 MB heap; the phone has room for that.

## PERF-04: orders under load { #perf-04 }

**Hypothesis.** 20 funded customers placing market buys at a steady 5 orders a second for 60 s (far
above what the phone will see) all get their orders filled, nothing fails for a server-side reason,
placement p95 stays under 1 s and p99 under 2 s, and afterwards every customer holds exactly the shares
their filled orders bought: nothing lost or doubled under load.

**Why.** An order is the most expensive request Sprout serves: the gateway, the order service's risk
check under a per-customer lock, accounts, the ledger (balance, then the outbox), the exchange and back.
It crosses three hosts.

| Setting | Value |
|---|---|
| Client | [`Perf04OrderLoadTest`](https://github.com/SaiNayakk/sprout-platform/blob/main/e2e/src/test/java/app/sprout/e2e/Perf04OrderLoadTest.java), run by the `loadgen` container |
| Customers | 20, each funded with ₹50,000 through the real deposit flow, all at once, each from its own address |
| Load | 300 market buys of 1 share (8 cheap symbols, chosen at random), 5 a second |
| Checked after | each customer's holdings against what their filled orders bought, share by share |

### Finding: same-name customers raced for one UPI address { #perf-04-vpa-race }

The first trial never reached the orders: funding 20 customers at once failed. Every test customer is
called Meera Iyer, and Sprout Bank chose a UPI address by checking which of `meera.iyer@`,
`meera.iyer1@`, and so on was free, then inserting it. Customers opening at the same moment picked the
same address; the second insert hit the unique key and was told "You already have a Sprout Bank
account", which was untrue. Fixed in bank 0.3.1: the plain name first, then the name with a random
number, and another try if the address was taken meanwhile; a test opens 20 same-name accounts at once.
The old scan also cost one query per earlier customer with the same name.

## Planned

| Id | What | When |
|---|---|---|
| PERF-05 | Authenticated reads (`GET /users/me`) at 100/s: the gateway's token verification cost | With the next gateway release |
| SOAK-01 | Sign-in at 5/s for 1 hour: memory must stay flat (no leak) | Before the first phone release of each host |
