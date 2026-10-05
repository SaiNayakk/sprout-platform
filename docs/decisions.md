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

## ADR-014: A simulated exchange that trades against the simulated market { #adr-014-exchange }

**Decision.** The Sprout Stock Exchange is its own service in the street host, with a member API like a
real exchange's (orders named by the broker's id, signed execution reports). It is a deep market anchored
to the simulated price: every execution is for the whole quantity at the last traded price; limit orders
rest until the price reaches them. It reads prices by polling market data, not from the NATS tick stream.

**Why.** A real order book needs other traders; there are none, so the market itself is the other side.
Keeping the exchange a separate party (its own keys, callbacks and database) means Sprout's order service
has to handle everything a real one does: rejections, lost answers, late callbacks, expiries. Polling gives
the exchange the latest price (all it needs) and lets it notice when it can't trust its prices, and refuse
orders instead of guessing; it doesn't depend on NATS staying up.

**Lost.** Partial fills, queue position and market impact: a big order executes in one go at the last
price. Fine for a simulation of a retail broker; a later phase could add depth.

## ADR-015: Orders and risk in one service, ledger entries through an outbox { #adr-015-oms }

**Decision.** Risk checks live inside the order service (not a separate risk service). Every ledger
movement after placement (fills, releases) is decided in the same database transaction as the order
change that implies it, written to an outbox, and posted to the ledger in order under a fixed
idempotency key. Only the hold at placement is posted directly, because placing depends on its answer;
a hold whose answer was lost is undone by re-posting it (the ledger answers with the original or books
it now) and then releasing it.

**Why.** Risk needs the customer's working orders and positions at the moment of placing, under the same
lock; across services that would be a distributed lock or a race. The outbox means an execution is
never booked without its money moving, or the money moved twice, whatever crashes in between. Entries
never depend on balances read at posting time, so a retry posts exactly what was decided.

**Lost.** The order service is bigger than one responsibility. It can be split (risk as a library or a
service) once there's a reason; the boundary is in the code already.

## ADR-016: Realistic products and charges, settlement later { #adr-016-products }

**Decision.** Both delivery and intraday (5x, shorting, auto square-off at 15:20), market and limit
orders, after-market orders, and a discount broker's real charges. Sale proceeds and today's shares
stay unsettled until T+1, which arrives with clearing in Phase 4.

**Why.** A broker gives its customers the services the market offers, even ones it would rather they
used sparingly; the habit-building features come later as friction, not as missing products. Real
charges make the numbers honest: a customer sees what trading costs.

**Lost.** Until Phase 4, sale proceeds can't be reinvested or withdrawn. Visible in funds as
`unsettled`, so nobody is surprised.
