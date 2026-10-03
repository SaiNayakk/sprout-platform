# sprout-platform

How [Sprout](https://sainayakk.github.io/sprout-platform/)'s services are put together, released and
proven.

Sprout is a simulated brokerage built from scratch as separate services, each in its own repository
with its own contract. This repository holds what sits between them:

| Path | What |
|---|---|
| `hosts/` | Deployable hosts. Each `pom.xml` is a **release manifest**: the exact service versions that host runs. |
| `preprod/` | The disposable pre-prod environment and `run.sh`, which creates it, tests it and destroys it. |
| `e2e/` | The end-to-end suite, run through the gateway like a real client. |
| `docs/` | The documentation site, including the evidence from every pre-prod run. |

**Docs:** https://sainayakk.github.io/sprout-platform/

## Run pre-prod locally

Needs Docker, Java 21 and Maven.

```bash
preprod/run.sh                  # create, test, write evidence, destroy
preprod/run.sh --keep           # leave it running on http://localhost:8100
preprod/run.sh --observability  # also Grafana on http://localhost:3000
```

## Related repositories

- [sprout-contracts](https://github.com/SaiNayakk/sprout-contracts): every API and event, versioned
- [sprout-identity](https://github.com/SaiNayakk/sprout-identity): accounts, two-factor, sessions, tokens
- [sprout-gateway](https://github.com/SaiNayakk/sprout-gateway): the public edge

## Licence

MIT
