# sprout-platform

How [Sprout](https://sainayakk.github.io/sprout-platform/)'s services are put together, released and
proven.

Sprout is a simulated brokerage built from scratch as separate services, each in its own repository
with its own contract. This repository holds what sits between them:

| Path | What |
|---|---|
| `hosts/` | Deployable hosts (`edge`: gateway + identity; `trading`: market data + orders; `money`: ledger, accounts, payments, settlement, statements, recon; `street`: Sprout Bank, the exchange, clearing, the depository). Each `pom.xml` is a **release manifest**: the exact service versions that host runs. `install-services.sh` builds each of those services from its release tag. |
| `preprod/` | The disposable pre-prod environment and `run.sh`, which creates it, tests it and destroys it. |
| `e2e/` | The end-to-end suite, run through the gateway like a real client, and the price fan-out load test. |
| `docs/` | The documentation site, including the evidence from every pre-prod run. |

**Docs:** https://sainayakk.github.io/sprout-platform/

## Run pre-prod locally

Needs Docker, Java 21, Maven, git and Python 3.

```bash
preprod/run.sh                  # create, test, write evidence, destroy
preprod/run.sh --keep           # leave it running on http://localhost:8100
preprod/run.sh --observability  # also Grafana on http://localhost:3000
```

## Related repositories

- [sprout-contracts](https://github.com/SaiNayakk/sprout-contracts): every API and event, versioned
- [sprout-identity](https://github.com/SaiNayakk/sprout-identity): accounts, two-factor, sessions, tokens
- [sprout-gateway](https://github.com/SaiNayakk/sprout-gateway): the public edge
- [sprout-marketdata](https://github.com/SaiNayakk/sprout-marketdata): the simulated market and live prices

## Licence

MIT
