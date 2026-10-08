# Environments & releases

## From a change to production

```mermaid
flowchart LR
  pr[Pull request] --> ci[CI: build, unit + contract tests,<br/>tests against real Postgres]
  ci --> merge[Merge to main] --> tag[Tag a version]
  tag --> manifest[Bump the host's release manifest]
  manifest --> preprod[Pre-prod: create, test, destroy]
  preprod --> prod[Deploy to the phone]
```

1. **Every repository** protects `main`. Changes arrive by pull request and merge only when CI is green.
2. **A release is a tag**, `vX.Y.Z`.
3. **A host's `pom.xml` is its release manifest**: the exact version of every service it runs. Changing
   a version is a release. Before a host is built, each service is built from its release tag
   ([ADR-011](decisions.md#adr-011-build-from-tags)).
4. **Pre-prod** builds that manifest, tests it and throws it away.
5. **Production** is the phone, deployed only from a manifest that passed pre-prod.

## Pre-prod is disposable

There is no long-lived staging server that drifts from production. For every release,
`preprod/run.sh` creates a fresh environment in Docker from nothing, runs every test, records the
evidence and destroys it, volumes included.

| Container | Purpose | Memory limit |
|---|---|---|
| `postgres` | Postgres 18, the version the phone runs | 256 MB |
| `edge` | The edge host jar (gateway, identity), same JVM flags as production | 384 MB |
| `trading` | The trading host jar (market data), its market running 30 times real speed | 256 MB |
| `money` | The money host jar (ledger, accounts, payments) | 320 MB |
| `street` | The street host jar (Sprout Bank; payment requests expire after 30 s here) | 256 MB |
| `nats` | NATS, for events between services | 64 MB |
| `lgtm` | Grafana, Prometheus, Loki and Tempo (with `--observability`) | 1.5 GB |
| `k6` | Load generator for request/response performance tests | n/a |
| `loadgen` | Java load generator for price streams, on the same clock as the services | n/a |

Pre-prod runs as the public sandbox (`SPROUT_SANDBOX=true`): its demo accounts are set up and live
every session of the fast market while the tests run, so every release is also checked with
real background activity, and reconciliation must still find the books exact at the end.

Limits mirror what the phone can give each host, so a memory regression fails in pre-prod first.
Configuration mirrors production too: identity loads its signing key from a file, as on the phone (a
generated in-memory key once hid a bug in exactly that path; see [Incidents](incidents.md)).

| Stage | Fails the release when |
|---|---|
| Environment | It isn't healthy within the compose health checks |
| [End-to-end](testing/e2e.md) | Any journey or edge case fails |
| [Performance](testing/performance.md) | Any k6 threshold is crossed |
| [Chaos](testing/chaos.md) | Any experiment's hypothesis is disproved |

The evidence from each run is committed under [Evidence from runs](reliability/runs/index.md).

## The laptop (while the phone is away)

`deploy/laptop/up.sh` runs the whole of Sprout, the web app and a Cloudflare tunnel on a laptop, so Sprout can be
visited from anywhere for as long as the machine is left on. It is the phone's stand-in: the same host jars at
the same pinned releases.

Its compose file isn't written by hand: `deploy/laptop/render.py` makes it **from pre-prod's**, so what visitors
use is wired exactly as every release was tested ([ADR-024](decisions.md#adr-024-laptop-from-preprod)). It changes only
what has to differ: real generated secrets in place of the throwaway ones, data on a volume, nothing published except
the web app (to the machine itself; the tunnel reaches it by name), a demo market that resumes after a restart
([ADR-025](decisions.md#adr-025-resumable-market)), and bank requests that wait 5 minutes instead of 30 seconds.

The gateway never forwards `/internal`, `/partner`, `/member`, `/participant` or `/actuator`, so the keys that guard
those doors are not the only thing between the internet and them.

What it can't do alone: a laptop that sleeps takes the site down, so it needs to be left awake and Docker Desktop
set to start with it. Moving back to the phone is stopping this and starting the phone's hosts; data made here
doesn't move (the sandbox's fictional customers are made again by the sandbox).

## Production

The phone runs each host as a supervised process behind a Cloudflare tunnel, with structured JSON logs.
Secrets (the two-factor encryption key, the token signing key, database passwords) exist only on the
phone; the repositories are public and contain none.

The web app runs there too: Termux's nginx (`deploy/phone/web`) serves the built app on `127.0.0.1:8180` with
the same security headers as the web image and forwards `/api` to the gateway, so the tunnel reaches one
address. With `SPROUT_SANDBOX=true` in `~/.sprout.env` the hosts run the 30x demo market and pace their loops
(settlement, reconciliation, plans, goals, the demo accounts) as the laptop and pre-prod do; `MARKETDATA_START_DATE`
and `MARKETDATA_EPOCH` there keep the market's place across restarts, and moving data from the laptop moves them too.

**Starting on the phone, one piece at a time.** Sprout is one Backseat app, `sprout`, running
`deploy/phone/start.sh`. It waits until the phone has been up five minutes, then starts Postgres, NATS,
the four hosts and the web app in turn, each only once the one before answers its health check and enough
memory is free, at a lower priority than the phone's own work. It restarts a piece that dies and backs
off for ten minutes if pieces keep dying. Before this, each piece was its own Backseat app; Backseat starts
all apps together at boot, and the phone rebooted, and rebooted again, under the load (2026-10-08).
