# One codebase, three shapes: monolith or microservices?

Sprout's 19 services can run as **one JVM**, as **four hosts** (what the phone runs), or as **one JVM per service**.
Nothing about the services changes between the three. Only how they are packed into processes changes. That makes
Sprout a fair place to measure an argument that is usually settled by opinion: what does splitting a system into
processes cost, and what does it buy?

**In short:** on the same laptop, 19 JVMs need **5.5 times the memory** of one JVM and **2.6 times the start-up
time**. They also slow down sooner under load, with p95 at 255 ms against 111 ms at 40 orders a second. In return
they keep **16 of 19 services up** when the ledger's process dies, against **none** in one JVM, and they come back
3 times faster. Sprout's four hosts sit in between: 2 times the monolith's memory, and 10 of 19 services survive.

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
- **Same machine, one shape at a time.** 8 vCPUs and Docker's 3.7 GB, with nothing else in Docker while a shape runs. The load generator runs on the laptop itself, outside Docker, so it doesn't compete with what it measures.
- **Same measurements**, by `preprod/shapes/run.sh`:
    - time to healthy from nothing;
    - memory and CPU at idle;
    - an order-load ladder (PERF-04 at 5, 10, 20, 40 and 80 orders a second, 60 s each, after a warm-up);
    - killing the process that runs the ledger: how many services still answer, and how long until it's back.
- **Three runs of each shape** on 2026-11-02. Every figure below is the median of the three, with the range where the runs disagree. `preprod/shapes/summarize.py` computes them from `preprod/shapes/results/`.

In every shape the services still call each other over HTTP, even inside one JVM. That isolates the cost of
*processes*; a monolith that calls in-process would be cheaper again (see [Limits](#limits)).

## Results

### Cost: memory and start-up

| | 1 JVM | 4 hosts | 19 JVMs |
|---|---|---|---|
| Memory at idle, all JVMs | **448 MB** | 922 MB | 2,479 MB |
| CPU at idle (% of one core) | **11%** | 16% | 36% |
| Healthy from nothing | 47 s | **39 s** | 123 s (119-126) |

Each JVM has a floor of roughly 110-130 MB before it does any work: its own heap, metaspace, code cache, threads
and a copy of Spring. Nineteen floors cost 5.5 times one. Idle CPU grows with the number of JVMs too: each runs its
own timers, health checks, connection pools and garbage collector. Four hosts start fastest because they start in
parallel; nineteen JVMs also start in parallel, but then compete for 8 cores while each warms up.

### Speed: orders under load (PERF-04, latency to place an order)

p95 / p99 in ms, median of three runs (p95 range in brackets where the runs differ by more than 25%):

| Orders a second | 1 JVM | 4 hosts | 19 JVMs |
|---|---|---|---|
| 5 | 102 / 113 | 102 / 122 | 119 / 812 |
| 10 | 108 / 121 | 105 / 114 | 119 / 335 |
| 20 | 100 / 117 | 104 / 124 | 168 / 928 (115-254) |
| 40 | **111 / 152** | 118 / 167 | 255 / 591 (210-478) |
| 80 | **132 / 645** | 725 / 1,197 (136-3,245) | 3,078 / 4,654 |
| Orders filled, all rates | 27,900 of 27,900 | 27,895 of 27,900 | 26,506 of 27,900 |

- **Up to 20 orders a second, the shapes look alike.** About 55-75 ms of every figure is the trip from the load
  generator into Docker's network, the same for all three, so the floor hides small differences.
- **19 JVMs pull away first.** At 40 a second their p95 is more than twice the others', and their p99 goes over half a
  second from the first step. One order crosses gateway, OMS, accounts, ledger and exchange, each in its own JVM
  with its own thread pools and its own share of 8 cores.
- **At 80 a second, only one JVM holds.** Its p95 stays at 132 ms. Four hosts did that in one run of three
  (136 ms) and fell to 725 ms and 3.2 s in the others. 19 JVMs reached p95 over 3 s in every run, and about 1 order
  in 10 didn't fill within the test. The hosts lost 5 of 14,400 orders at that rate to timeouts (504), which the
  test counts as unknown, not failed.

### Failure: kill the process that runs the ledger

| | 1 JVM | 4 hosts | 19 JVMs |
|---|---|---|---|
| Services still answering while it's down | **0 of 19** | 10 of 19 | **16 of 19** |
| Back and healthy after | 38 s | 17 s | **12 s** |

Here the order reverses. In one JVM, a fault anywhere is a fault everywhere: sign-in, prices and the status page
go down with the ledger. With 4 hosts, the money host takes its seven services with it. With 19 JVMs only the
ledger goes, and the few services that can't work without it. A small process also restarts faster. The three
runs agreed on every number here.

## What the experiment found along the way { #found }

- **17 calls that only worked because they shared a JVM.** Each service's default address for some of its
  neighbours is `127.0.0.1`, because in every host the caller and the callee share a process. Pre-prod never sets
  those addresses, so nothing showed it. With each service alone, the calls went nowhere:
    - OMS couldn't fetch prices, so **every order failed** with a 503 within 10 ms;
    - settlement, recon and statements couldn't reach the ledger;
    - clearing couldn't reach the bank, exchange or depository.

  Three 19-JVM runs measured this bug, not the architecture, before it was found. The render now sets all 17
  addresses (`COLOCATED` in `render.py`). This is the hidden coupling a modular monolith accumulates: splitting it
  into processes is the test that finds it.
- **A load generator that took the shape's memory.** Run inside Docker, the load test's two JVMs sized themselves
  to a quarter of the VM each, and the 19-JVM shape ran out of memory (`Cannot allocate memory`). It now runs on the
  laptop, outside Docker, with small fixed heaps.
- **A test that hid its own failure.** The load test's helper ignored whether sign-up and sign-in succeeded. When 40
  customers signed up at once, past identity's measured capacity of about 20 sign-ins a second
  ([PERF-01](testing/performance.md#perf-01)), a refused sign-in became an empty token, and the next call failed
  with a misleading `401 Sign in to continue`. The helper now checks each step and backs off when told to.
- **Setup that gave up too soon.** Setting up customers isn't what's measured, but it has to work on the slowest
  shape. It now waits and tries again when told to (429, 503, or a timeout on a call that's safe to repeat). It
  waits for the bank to receive a deposit's collect request, and sets up four customers at a time.
- **A misdiagnosis, and a real hardening.** The first suspect for the 401s was the gateway's key fetch. Nimbus's
  defaults give identity 500 ms to serve its signing keys, then refuse to refetch for 30 s, during which every
  token is refused. That wasn't this failure. It is still a real risk, fixed in gateway 0.5.1 (v0.19.1):
    - patient timeouts;
    - a refresh in the background before the keys expire;
    - keys kept through an outage;
    - a retryable 503 instead of 401 when the gateway truly can't check a token.
- **A check that tripped its own rate limit.** At 80 orders a second, the after-load holdings check read 0 shares for
  96 customer-symbols. The holdings were fine; the check's own requests were being rate-limited. It now waits its
  turn.

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
| The least memory and CPU, the simplest operations, the most throughput per core | **1 JVM** (modular monolith) | 448 MB against 2.5 GB at idle; the only shape at p95 under 150 ms at 80 orders a second |
| A fault in one area not to take the rest down | **Split by failure domain** (Sprout's 4 hosts) | 10 of 19 services survive the money host's loss, at 2 times the monolith's memory, not 5.5 |
| Independent scaling, deploys and teams per service; the smallest blast radius | **Microservices** | 16 of 19 services survive; back in 12 s; at 5.5 times the memory, 2.6 times the start-up, and the first to slow under load |

Sprout runs the middle shape on purpose. A phone can afford four JVMs but not nineteen, and grouping by what
fails together keeps sign-in and prices up when money breaks. Its standby runs the monolith, because a standby is
idle until it is needed and must fit beside a cell's own services.

## Limits { #limits }

- **Not production hardware.** One laptop with 8 vCPUs; every shape shares one Postgres. The relative differences are what carry over.
- **A shared floor.** The load generator reaches Docker through its port forwarding, which adds about 55-75 ms to every order in every shape. Differences smaller than that are hidden.
- **HTTP inside one JVM.** In-process method calls would make the monolith cheaper still; this measures packaging, not a rewrite.
- **Scaling one service out isn't measured.** For example, two OMS replicas behind the gateway: the microservices shape's main argument, and the one this machine has no room left to test.
- **Three runs.** At 80 orders a second the four-host runs ranged from 136 ms to 3.2 s at p95, so that cell of the table is a median of very different runs.
