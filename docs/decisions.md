# Decisions

Architecture decision records: the choice, why, and what lost. Newest last.

## ADR-001: Java 21 and Spring Boot { #adr-001-java-and-spring-boot }

**Decision.** Services are Java 21 on Spring Boot 3, with plain JDBC (no JPA) and Flyway migrations.

**Why.** It is what most banks and brokerages run, so the patterns (transactions, connection pools,
observability, contract testing) carry over directly. Plain JDBC keeps every query visible and saves
about 60 MB per service.

**Lost.** Go or Node would use far less memory on a phone. Rejected because learning how large
institutions build is the point.

## ADR-002: One repository per service { #adr-002-polyrepo }

**Decision.** Every service, the contracts and the platform each have their own public repository.
Releases are git tags. (How a host gets a release's code: [ADR-011](#adr-011-build-from-tags).)

**Why.** It forces what a monorepo lets you skip: versioned contracts, explicit dependencies, independent
releases. CI on public repositories and JitPack are free.

**Lost.** A monorepo would mean one pull request per change instead of several. Accepted as the cost of
working the way separate teams do.

## ADR-003: Shared JVM hosts { #adr-003-shared-jvm-hosts }

**Decision.** Services are built separately but deployed together in hosts: one JVM, one Spring context
per service, each with its own config, port and schema.

**Why.** Measured: one tuned JVM per service costs about 147 MB; four services in one JVM cost about
170 MB in total. A phone can't give fifteen services 150 MB each.

**Lost.** A crash or memory leak in one service takes down its host-mates. Mitigated by grouping
services by blast radius (the edge host is gateway and identity, which fail together anyway) and by
memory limits tested in pre-prod.

## ADR-004: Contracts first, enforced in CI { #adr-004-contracts-first }

**Decision.** APIs are OpenAPI and events are JSON Schema, in their own repository. Breaking changes
fail CI. Services validate their real responses against the contract in tests.

**Why.** It is the only way separate services can change independently without breaking each other.

## ADR-005: Disposable pre-prod { #adr-005-disposable-preprod }

**Decision.** Pre-prod is created from scratch for every release, tested, and destroyed.

**Why.** A long-lived staging server drifts from production and collects state that hides bugs. A fresh
environment proves the release can be built and started from nothing, every time.

**Lost.** Each run takes a few minutes longer than testing against an environment that is already up.

## ADR-006: Observability runs locally { #adr-006-local-observability }

**Decision.** Grafana, Prometheus, Loki and Tempo run in a single container (`grafana/otel-lgtm`) on the
laptop when needed, fed by OpenTelemetry.

**Why.** Free, nothing leaves the machine, and the same dashboards work in pre-prod and against the
phone. Hosted free tiers were time-limited or too small to keep.

**Lost.** No always-on dashboard from anywhere. Structured logs on the phone fill the gap.

## ADR-007: An event bus for anything that isn't a question { #adr-007-event-bus }

**Decision (in use since Phase 1 for prices).** Services announce what happened (a user registered, an order filled) as events,
written to an outbox table in the same transaction as the change, then published to NATS.

**Why.** Money movement and records must never disagree with what happened. The outbox makes "change
the data" and "announce it" atomic without distributed transactions. NATS is small enough for a phone.

**Lost.** Kafka is the industry default, but needs far more memory than the phone has.

## ADR-008: A simulated market of fictional companies { #adr-008-simulated-market }

**Decision.** Prices come from a deterministic simulation of twenty fictional companies and an index,
not from a real exchange.

**Why.** Real NSE prices can't be redistributed publicly, so a public demo couldn't show them. Free
intraday history only reaches back about a week and comes from unofficial sources that can break. A
live feed costs money and needs a manual login every day. A simulation has none of those problems and
can do what real data can't: run every weekday forever, replay any day exactly from a seed, and crash
on demand to test risk checks.

To stay believable, every stock's move is market + sector + its own; days have scenarios (normal,
trending, volatile, crash, rally); there are opening gaps, news jumps and U-shaped volume; and every
tick adds up exactly to its minute's candle. Fake prices are only shown under fictional names, so
nobody could mistake them for a real company's.

The default seed (12) was picked from the first 80 for a believable long run: about +38% over the
history (roughly 12% a year), one correction of about 23%, and a mix of winning and losing stocks.

**Lost.** Realism of the very fine structure (real order flow, real news). The API has a `mode`
field, so a replay or live source can be added later without clients changing.

## ADR-009: Server-Sent Events with conflation for live prices { #adr-009-sse-with-conflation }

**Decision.** Live prices are a Server-Sent Events stream through the gateway. Each stream holds at
most one pending tick per symbol; a slow client gets the newest price only.

**Why.** SSE is plain HTTP: it passes through Cloudflare, proxies and the gateway like any request,
browsers reconnect it themselves, and prices only flow one way anyway. Conflation is what real market
data feeds do for slow consumers: it bounds memory per client and means no client can slow the market
down.

**Lost.** WebSockets would allow two-way messages (e.g. changing subscriptions without reconnecting).
Not needed yet; reconnecting with a new symbol list is cheap.

## ADR-010: A separate trading host { #adr-010-trading-host }

**Decision.** Market data runs in its own JVM, the trading host, which orders and risk will join,
rather than inside the edge host.

**Why.** A host is a blast radius. If market data ran next to identity, a stuck market clock, a flood
of price streams or running out of memory would also stop people signing in. CHAOS-03 kills the
trading host and checks that sign-in doesn't notice.

**Lost.** About 130 MB for the extra JVM. The phone has room for the planned five hosts.

## ADR-011: Hosts build services from their release tags { #adr-011-build-from-tags }

**Decision.** A host's release manifest pins each service's version `X.Y.Z`. Before a host is built,
`hosts/install-services.sh` clones tag `vX.Y.Z` of each service, builds it, and installs it into the
local Maven repository; the host builds from that. It always rebuilds, so nothing from a working tree
can stand in for the tag.

**Why.** Releases were published by JitPack, which builds artifacts from git tags. On 2026-10-04/05 its
builds broke: first it ran every build on Java 8, then builds of the gateway's tags and commits failed
intermittently inside Maven itself. Four releases never published and others only by commit (see
[Incidents](incidents.md)). Building from the tag needs nothing but GitHub, is reproducible, and takes
about 40 seconds for three services.

The contracts, which services need at test time, publish themselves instead: every tag of
sprout-contracts is built, tested and deployed by its own workflow into a Maven repository on its
GitHub Pages (`https://sainayakk.github.io/sprout-contracts/maven`). Nothing in Sprout's release path
uses JitPack any more.

**Lost.** Nothing important. A host build takes about 40 seconds longer.

## ADR-012: The money host, and the bank in the street host { #adr-012-money-host }

**Decision.** The ledger, accounts and payments run together in a money host; Sprout Bank runs alone in a
street host, where the other outside parties (exchange, clearing, depository) will join it.

**Why.** A payment needs all three money services: if any is down, money can't move either way, so
separating them would buy no availability and cost memory. The bank is a different organisation in real
life; keeping it in another host (and another trust boundary: partner keys and signed callbacks, not
internal calls) means Sprout's code can never take a shortcut into it.

**Lost.** A bug in accounts can take down payments. Accepted for now; the boundary is the service, not
the JVM, so they can be split later without code changes.

## ADR-013: The ledger is the only place money lives { #adr-013-ledger }

**Decision.** Balances exist only in the ledger, as double-entry postings in paise. Payments records what
happened to each payment, never how much anyone has.

**Why.** One source of truth that can't drift, can be proven to balance at any moment, and can be
reconciled against the bank (RECON-01). Every other service asks it; none keeps its own copy.

**Lost.** An extra call per balance read. Cheap at Sprout's scale; at real scale it would be a read model
fed from the journal.
