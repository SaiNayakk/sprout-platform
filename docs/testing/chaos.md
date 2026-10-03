# Chaos tests

A chaos experiment breaks one thing on purpose and checks that the system behaves the way we claim it
does. Each has a **steady state** (what normal looks like), a **hypothesis** (what should happen when
the thing breaks), a **method**, and a pass condition. They run automatically in pre-prod.

## CHAOS-01: the database goes away { #chaos-01 }

| | |
|---|---|
| **Steady state** | A sign-in with a wrong password gets `401` quickly. |
| **Fault** | Stop the Postgres container. |
| **Hypothesis** | Sign-in answers `503 UPSTREAM_UNAVAILABLE` with a `Retry-After` header in **under 3 s**, never hanging until the gateway's 5 s timeout. When Postgres comes back, identity recovers **within 30 s, without a restart**. |
| **Method** | [`preprod/run.sh`](https://github.com/SaiNayakk/sprout-platform/blob/main/preprod/run.sh): probe, `docker compose stop postgres`, probe three times, `start postgres`, probe every second until healthy. |

### What happened

The first time this ran (manually, before automation), **the hypothesis was disproved**:

| | Expected | Got |
|---|---|---|
| Status while down | `503` with `Retry-After` | `504` from the gateway |
| Time to answer | under 3 s | 5 s: identity was still waiting for a database connection when the gateway gave up |

The cause was in identity, and fixing it surfaced a second one:

1. The connection pool waited the default 30 s for a connection, so identity never answered before the
   gateway's 5 s timeout.
2. The regression test for the fix (below) then failed in CI with a `500`: depending on timing, the
   error arrives as a failed rollback after a lost connection (`TransactionSystemException` wrapping
   SQL state `08006`), which the problem handler didn't recognise as "database unreachable".

The fix, released as identity `v0.2.1`:

- Pool `connection-timeout` 2 s and `validation-timeout` 1 s, so identity decides well inside the
  gateway's budget.
- The problem handler walks the whole cause chain for any connection failure (SQL state class `08`,
  socket errors, Spring's resource-failure exceptions, and failed rollbacks) and answers
  `503 UPSTREAM_UNAVAILABLE` with `Retry-After: 5`.
- The contract added the `503` first ([contracts `v0.2.0`](../contracts.md#versioning)).
- Unit tests for each wrapped form, and a Testcontainers test that stops a real Postgres mid-test and
  checks for a contract-valid `503` in under 4 s.

Re-run against `v0.2.1`: `503` in about 2.0 s with `Retry-After: 5`, recovery in seconds, no restart.
Every pre-prod run since repeats the experiment; results are in
[Evidence from runs](../reliability/runs/index.md).

## Planned

| Id | Fault | Hypothesis |
|---|---|---|
| CHAOS-02 | Identity's context crashes inside the edge host | Gateway answers `503` fast; circuit opens after repeated failures and closes after recovery |
| CHAOS-03 | Postgres slows to 3 s per query (network latency injected) | Requests fail inside the gateway budget; no thread pile-up; memory stays under the limit |
| CHAOS-04 | Edge host killed mid-traffic | Supervisor restarts it; clients see errors for under 30 s; no half-written sessions |
| CHAOS-05 | Signing key rotated while tokens are live | Old tokens keep working until they expire; new tokens use the new key |
| CHAOS-06 | Disk fills on the database volume | Writes fail with `503`, reads keep working, nothing corrupts |
| CHAOS-07 | The phone loses its network (region down) | The laptop region takes traffic; see [Reliability](../reliability/index.md) |
