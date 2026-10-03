# Environments & releases

## From a change to production

```mermaid
flowchart LR
  pr[Pull request] --> ci[CI: build, unit + contract tests,<br/>tests against real Postgres]
  ci --> merge[Merge to main] --> tag[Tag a version] --> pub[Published artifact]
  pub --> manifest[Bump the host's release manifest]
  manifest --> preprod[Pre-prod: create, test, destroy]
  preprod --> prod[Deploy to the phone]
```

1. **Every repository** protects `main`. Changes arrive by pull request and merge only when CI is green.
2. **A release is a tag.** Tags are published as Maven artifacts, so a host can depend on
   `sprout-identity:v0.2.1` exactly.
3. **A host's `pom.xml` is its release manifest**: the exact version of every service it runs. Changing
   a version is a release.
4. **Pre-prod** builds that manifest, tests it and throws it away.
5. **Production** is the phone, deployed only from a manifest that passed pre-prod.

## Pre-prod is disposable

There is no long-lived staging server that drifts from production. For every release,
`preprod/run.sh` creates a fresh environment in Docker from nothing, runs every test, records the
evidence and destroys it, volumes included.

| Container | Purpose | Memory limit |
|---|---|---|
| `postgres` | Postgres 18, the version the phone runs | 256 MB |
| `edge` | The edge host jar, same JVM flags as production | 384 MB |
| `lgtm` | Grafana, Prometheus, Loki and Tempo (with `--observability`) | 1.5 GB |
| `k6` | Load generator for performance tests | n/a |

Limits mirror what the phone can give each host, so a memory regression fails in pre-prod first.

| Stage | Fails the release when |
|---|---|
| Environment | It isn't healthy within the compose health checks |
| [End-to-end](testing/e2e.md) | Any journey or edge case fails |
| [Performance](testing/performance.md) | Any k6 threshold is crossed |
| [Chaos](testing/chaos.md) | Any experiment's hypothesis is disproved |

The evidence from each run is committed under [Evidence from runs](reliability/runs/index.md).

## Production

The phone runs each host as a supervised process behind a Cloudflare tunnel, with structured JSON logs.
Secrets (the two-factor encryption key, the token signing key, database passwords) exist only on the
phone; the repositories are public and contain none.
