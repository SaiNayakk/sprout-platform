# Decisions

Architecture decision records: the choice, why, and what lost. Newest last.

## ADR-001: Java 21 and Spring Boot { #adr-001-java-and-spring-boot }

**Decision.** Services are Java 21 on Spring Boot 3, with plain JDBC (no JPA) and Flyway migrations.

**Why.** It is what most banks and brokerages run, so the patterns (transactions, connection pools,
observability, contract testing) carry over directly. Plain JDBC keeps every query visible and saves
about 60 MB per service.

**Lost.** Go or Node would use far less memory on a phone. Rejected because learning how large
institutions build is the point.

## ADR-002: One repository per service, released through JitPack { #adr-002-polyrepo }

**Decision.** Every service, the contracts and the platform each have their own public repository.
Releases are git tags, published as Maven artifacts by JitPack.

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

**Decision (planned).** Services announce what happened (a user registered, an order filled) as events,
written to an outbox table in the same transaction as the change, then published to NATS.

**Why.** Money movement and records must never disagree with what happened. The outbox makes "change
the data" and "announce it" atomic without distributed transactions. NATS is small enough for a phone.

**Lost.** Kafka is the industry default, but needs far more memory than the phone has.
