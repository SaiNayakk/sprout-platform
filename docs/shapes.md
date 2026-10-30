# One codebase, three shapes: monolith or microservices?

Sprout's 19 services can run as **one JVM**, as **four hosts** (what the phone runs), or as **one JVM per service**.
Nothing about the services changes between the three. Only how they are packed into processes changes. That makes
Sprout a fair place to measure an argument that is usually settled by opinion: what does splitting a system into
processes cost, and what does it buy?

!!! warning "Draft"
    Results below are from the first two runs (2026-10-30). The order-load ladder for the one-JVM-per-service shape is
    still to run: its first two attempts were spoiled by a test bug (see [What the experiment found](#found)).
    Each figure will be the median of three runs before this page is final.

## The three shapes

| Shape | Processes | What it is | Where Sprout uses it |
|---|---|---|---|
| **1 JVM** | 1 | A modular monolith: every service's Spring context in one process | A cell's standby, which serves the other cell's customers after a takeover ([ADR-027](decisions.md#adr-027-cells)) |
| **4 hosts** | 4 | Services grouped by what fails together: edge, trading, money, street | Production, on the phone and the laptop |
| **19 JVMs** | 19 | Microservices: each service alone in its process | Only this experiment |

How it's built, so the comparison is honest:

- **Same code, same releases.** The three shapes run the same service jars, at the versions the hosts' release manifests pin.
- **The packaging is all that changes.** `CellHost` starts all four hosts' services in one JVM. `ServiceHost` starts the one named by `SPROUT_SERVICE`.
- **Same configuration.** `preprod/shapes/render.py` writes all three compose files from pre-prod's. It changes only the packing, and the addresses the services use to find each other.
- **Same JVM settings.** Every JVM gets the same flags, with heap caps high enough never to bind: the experiment measures what each shape uses, not whether it fits a budget.
- **Same machine, one shape at a time.** 8 vCPUs and Docker's 3.7 GB; nothing else in Docker while a shape runs.
- **Same measurements**, by `preprod/shapes/run.sh`:
    - time to healthy from nothing;
    - memory and CPU at idle;
    - an order-load ladder (PERF-04 at 5, 10, 20, 40 and 80 orders a second, 60 s each, after a warm-up);
    - killing the process that runs the ledger: how many services still answer, and how long until it's back.

In every shape the services still call each other over HTTP, even inside one JVM. That isolates the cost of
*processes*; a monolith that calls in-process would be cheaper again (see [Limits](#limits)).

## Results

### Cost: memory and start-up

| | 1 JVM | 4 hosts | 19 JVMs |
|---|---|---|---|
| Memory at idle, all JVMs | **408 MB** | 809 MB | 2,496 MB |
| CPU at idle (of 800%) | **10%** | 18% | 69% (46% in run 2) |
| Healthy from nothing | 50 s | 52 s | 203 s (128 s in run 2) |

Each JVM has a floor of roughly 110-130 MB before it does any work: its own heap, metaspace, code cache, threads
and a copy of Spring. Nineteen floors cost six times one. Idle CPU grows with the number of JVMs too: each runs its
own timers, health checks, connection pools and garbage collector.

### Speed: orders under load (PERF-04, latency to place an order)

| Orders a second | 1 JVM p95 / p99 | 4 hosts p95 / p99 |
|---|---|---|
| 5 | 121 / 652 ms | 88 / 135 ms |
| 10 | 73 / 124 ms | 98 / 146 ms (69 / 80 in run 2) |
| 20 | 62 / 77 ms | 87 / 993 ms (run 2) |
| 40 | 77 / 122 ms (84 / 136 in run 2) | 172 / 304 ms (88 / 136 in run 2) |
| 80 | 207 / 395 ms | 535 / 623 ms |

Every order was filled at every rate up to 40 a second, in both shapes, with nothing lost or doubled. At 80 a second,
which is above what one test customer may send under the gateway's per-customer limit, some orders were turned away
with 429 (as designed) and a few timed out (504). The two runs differ enough at single rates (4 hosts at 40 a second:
p95 172 ms, then 88 ms) that only the trend is solid so far: at 80 orders a second one JVM's p95 was 207 ms against
four hosts' 535 ms, and its p99 395 ms against 623 ms. An order crosses three hosts, and every hop is a real network call with its own thread pools. In one
JVM those hops stay on loopback and share one warm JIT.

### Failure: kill the process that runs the ledger

| | 1 JVM | 4 hosts | 19 JVMs |
|---|---|---|---|
| Services still answering while it's down | **0 of 19** | 10 of 19 | **15-16 of 19** |
| Back and healthy after | 41-44 s | 17-23 s | **13 s** |

Here the order reverses. In one JVM, a fault anywhere is a fault everywhere: sign-in, prices and the status page
go down with the ledger. With 4 hosts, the money host takes its seven services with it. With 19 JVMs only the
ledger goes, and the few services that can't work without it. A small process also restarts faster.

## What the experiment found along the way { #found }

- **A test that hid its own failure.** The load test's helper ignored whether sign-up and sign-in succeeded. When 40
  customers signed up at once, past identity's measured capacity of about 20 sign-ins a second
  ([PERF-01](testing/performance.md#perf-01)), a refused sign-in became an empty token, and the next call failed
  with a misleading `401 Sign in to continue`. It hit the 19-JVM shape first because there identity shares the
  CPU with 18 other JVMs. The helper now checks each step and backs off when told to.
- **A misdiagnosis, and a real hardening.** The first suspect was the gateway's key fetch. Nimbus's defaults give
  identity 500 ms to serve its signing keys, then refuse to refetch for 30 s, during which every token is refused.
  That wasn't this failure. It is still a real risk, fixed in gateway 0.5.1 (v0.19.1):
    - patient timeouts;
    - a refresh in the background before the keys expire;
    - keys kept through an outage;
    - a retryable 503 instead of 401 when the gateway truly can't check a token.
- **A check that tripped its own rate limit.** At 80 orders a second, the after-load holdings check read 0 shares for
  96 customer-symbols. The holdings were fine; the check's own requests were being rate-limited. It now waits its
  turn. The two real mismatches were orders that timed out with 504 but filled: a 504 means "unknown", not "failed".

## Monorepo or many repositories?

This is a separate question from the one above. A monolith can live in many repositories, and microservices in
one. Sprout uses **22 repositories**: one per service, plus contracts, the platform (hosts and deployment) and the
web app. Each is released by tag and pinned by version in a host's release manifest
([ADR-011](decisions.md#adr-011-build-from-tags)). From git history, as of 2026-10-30:

| | |
|---|---|
| Repositories | 22 |
| Commits, all repositories | 400 |
| Release tags, all repositories | 155: one release for every 2.6 commits |
| Services whose version changes in one platform release | 5 on average (21 releases); up to 19 |
| Repositories touched to rename one stock (CHAIWALA to BREWBERRY) | 11 |
| One feature: one demo account per visitor, with the order trace | 5 repositories, 7 pull requests, 4 releases (contracts twice, sandbox, OMS), then the platform and web |

What many repositories bought Sprout:

- **Every service has an exact, tested version.** A host's manifest is the release, so pre-prod tests exactly what will run.
- **Contracts are versioned, and a breaking change fails CI** before any service can depend on it.
- **Each service's CI is small and fast**, about a minute.

What they cost:

- **Coordination.** A cross-cutting change is a chain of releases in dependency order: contracts, then services, then the platform. A rename is a day of pull requests.
- **The release is the slowest step**, not the code: 155 tags for 400 commits.
- **No atomic change.** A refactor across services can't land in one commit, so for a while two versions of a contract must both work.

A monorepo with per-service build targets (Maven modules or Bazel) would keep the exact versions and the
contract checks, and make a cross-cutting change one pull request. The price is CI that must work out what
changed, rather than building everything. For one developer and 19 services the coordination cost is the
larger one: if Sprout started again, it would be one repository with many modules.

## When each shape wins

| If you need... | Choose | Because, measured here |
|---|---|---|
| The least memory and CPU, the simplest operations | **1 JVM** (modular monolith) | 408 MB vs 2.5 GB at idle; fastest under load |
| A fault in one area not to take the rest down | **Split by failure domain** (Sprout's 4 hosts) | 10 of 19 services survive the money host's loss, at 2x the monolith's memory, not 6x |
| Independent scaling, deploys and teams per service; the smallest blast radius | **Microservices** | 15 of 19 services survive; 13 s recovery; at 6x the memory and 4x the start-up |

Sprout runs the middle shape on purpose. A phone can afford four JVMs but not nineteen, and grouping by what
fails together keeps sign-in and prices up when money breaks. Its standby runs the monolith, because a standby is
idle until it is needed and must fit beside a cell's own services.

## Limits { #limits }

- **Not production hardware.** One laptop with 8 vCPUs; every shape shares one Postgres. The relative differences are what carry over.
- **HTTP inside one JVM.** In-process method calls would make the monolith cheaper still; this measures packaging, not a rewrite.
- **Scaling one service out isn't measured yet.** For example, two OMS replicas behind the gateway: the microservices shape's main argument.
- **Two runs so far.** Single-rate figures vary between runs; final figures will be medians of three.
