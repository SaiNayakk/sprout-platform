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

## ADR-017: Settlement through simulated market institutions, checked by a back office { #adr-017-settlement }

**Decision.** T+1 settlement is done the way Indian markets do it, by separate parties: a clearing
corporation that nets each day's trades and settles them step by step, a depository holding every
customer's shares in a demat account, and the bank moving the money. Sprout's side is a back-office
service that checks each obligation against Sprout's own books before paying anything, books every
movement in the ledger at the same time as the bank moves it, and only then settles clients.

**Why.** Settlement is where a broker's books meet the outside world, and where real brokers spend their
operational effort: reconciling, chasing breaks, paying on time. Simulating the institutions (rather than
moving balances inside Sprout) means Sprout's code faces what a real back office faces: asynchronous
news, partial failures, money that hasn't arrived yet, a counterparty that disagrees. Checking before
paying turns a disagreement into a visible break instead of a silent loss.

**Lost.** Simplifications: one member (Sprout) and a float standing for the rest of the market; whole
settlement cycles rather than intraday pay-in deadlines; short deliveries closed out in cash at a fixed
20% rather than through an auction.

## ADR-018: Statements are a read model; reconciliation reads through APIs { #adr-018-records }

**Decision.** The statements service has no database: every statement is built on request from the
services that own the facts. The reconciliation service reads each book through its owner's API (never
its database), compares twice before calling a difference a break, and keeps every run's findings.

**Why.** A copy of the books can drift from them, and then a customer's statement and Sprout's books
disagree, which is exactly what reconciliation exists to catch. Reading through APIs means
reconciliation checks what customers and other services actually see, and keeps every service the only
owner of its data.

**Lost.** Statements cost a few calls each, and a year's P&amp;L reads a customer's whole history. Fine at
Sprout's scale; at a real broker's, statements would be built once a day into a store of their own.

## ADR-019: Habits are computed from trading history, and reward consistency only { #adr-019-habits }

**Decision.** Streaks, levels, badges and points are a pure function of a customer's executions, worked
out each time they're asked for; only choices (squads, privacy, readiness answers) are stored. Only
delivery purchases build the habit; intraday trading never earns anything, points vest only if the money
stays invested, squads rank by consistency and never show amounts.

**Why.** A stored score drifts from what really happened and needs its own reconciliation; computing it
from the executions means the same history always gives the same picture. And rewards shape behaviour:
rewarding activity would push people to trade more, which costs them money. Rewarding regular
investing, with time in the market, pushes the other way.

**Lost.** Each picture reads the customer's history (a year per call). Fine for a squad of 12; at scale,
habits would be kept incrementally from the stream of executions.

## ADR-020: One request, one trace, started at the gateway { #adr-020-one-request-one-trace }

**Decision.** The gateway drops every trace header a client sends and starts the trace itself. Every
service carries the request id and the current trace onward on every call it makes, through one small
`Onward` component per service rather than a shared library.

**Why.** A customer's order touches the gateway, the order service, accounts, the ledger and the exchange;
without one id and one trace across them, a slow or failed order means reading five logs by timestamp.
Accepting a client's trace would let anyone attach their traffic to another request's trace, force
sampling (cost) or carry baggage into every service. Each service keeps its own copy of `Onward`
(about 40 lines) because a shared runtime library would couple every service's release to it, which the
polyrepo exists to avoid.

**Lost.** A browser or partner can't continue its own trace into Sprout. The same few lines exist in
ten repositories.

## ADR-021: Round-ups through a UPI AutoPay mandate and shared spends, read as a feed { #adr-021-round-ups }

**Decision.** Round-ups use a UPI AutoPay mandate the customer approves once in their bank: the bank
reports the customer's spends to Sprout while the mandate is active, and Sprout debits the rounded-up
total under it. Payments keeps the spends in arrival order; goals reads them as a feed from a stored
cursor, and every sweep is one debit whose reference is made before it is asked for.

**Why.** It is how real round-up apps work in India: no PIN for every ₹4, but nothing taken without a
standing permission the customer can see and revoke in their own bank. A feed with a cursor, rather
than payments calling goals, keeps payments from knowing who uses spends, and makes a missed read
harmless (the next one starts from the cursor; a spend's id stops it counting twice). A sweep claims
its round-ups before the debit is asked for, so a debit whose answer was lost is asked again with the
same reference and never taken twice.

**Lost.** Round-ups arrive a few seconds after the spend, not at once. Sweeping waits for ₹100, so small
spenders see round-ups wait. A refused sweep waits an hour, so fixing the mandate isn't instant.

## ADR-022: Rewards spend points habits works out; nothing is stored but choices { #adr-022-rewards }

**Decision.** The rewards service stores only what customers chose (redemptions, referral codes and
links). What they can spend is worked out each time: vested habit points from habits, plus referral
rewards, less what they have spent. A redemption is decided under a per-customer advisory lock.
Referrals are rewarded when either side looks, once the new customer has invested in 3 months.

**Why.** A stored points balance would be a second record of the habit, drifting from the trading
history it is supposed to reflect (ADR-019). Spending is the one thing that must be serialised, and
a lock per customer does that without a balance row to keep right.

**Lost.** Each vault read asks habits for the customer's picture (a year of history). Rewarding
referrals when someone looks means a friend's reward appears the next time either opens rewards, not
the moment the third month's purchase is made.

## ADR-023: The sandbox's history is lived, on a fast clock, never written in { #adr-023-sandbox }

**Decision.** The public sandbox's fictional customers get their history by living it: the sandbox's
market runs 30 times real speed (a trading day in about 13 minutes, a month in about 5 hours), and every
session each person acts through the same APIs as any customer. Nothing is imported or written into a
service's database around its API.

**Why.** Habits, statements, settlement and reconciliation all work from executed trades and the books.
History written in around them would either break reconciliation (trades the exchange never saw) or need
an import path that exists only for the demo. Lived history keeps every number on every screen honest,
and the sandbox exercises the whole system continuously, which pre-prod now does too: it runs as the
sandbox, so the fictional customers live alongside every test and the books must still agree at the end.

**Lost.** Time in the sandbox isn't the calendar: a visitor sees October pass in an afternoon. A new
sandbox needs a few hours before its people have months behind them. Fifteen people acting every session
cost the phone some CPU.
