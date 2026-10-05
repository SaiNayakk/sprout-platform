# Sprout

**Grow the habit, not the hype.**

Sprout is a brokerage built from scratch to learn how real ones work at scale: sign-in and two-factor,
market data, orders, execution, money movement and the records behind all of it. It is split into
separate services the way a large institution splits teams, each with its own repository, its own
contract and its own responsibility, and it runs on a phone.

The market is simulated: twenty fictional companies whose prices behave like a real market's. See
[ADR-008](decisions.md#adr-008-simulated-market).

The product is aimed at people investing for the first time. It rewards steady habits (investing
regularly, holding, diversifying) rather than frequent trading.

!!! note "Simulated"
    No real money moves, no real orders reach an exchange, and the companies and their prices are made
    up. Everything is simulated faithfully: the market, and everything a brokerage does with it.

## What exists today

| Piece | Repository | Status |
|---|---|---|
| Contracts: every API and event, versioned | [sprout-contracts](https://github.com/SaiNayakk/sprout-contracts) | `v0.5.0` |
| Identity: accounts, passwords, two-factor, sessions, tokens | [sprout-identity](https://github.com/SaiNayakk/sprout-identity) | `v0.2.3` |
| Gateway: the only public door; auth, rate limits, routing, price streams | [sprout-gateway](https://github.com/SaiNayakk/sprout-gateway) | `v0.2.4` |
| Market data: the simulated market, quotes, candles, live prices | [sprout-marketdata](https://github.com/SaiNayakk/sprout-marketdata) | `v0.1.1` |
| Accounts: opening a Sprout account, simulated KYC | [sprout-accounts](https://github.com/SaiNayakk/sprout-accounts) | `v0.1.0` |
| Ledger: the double-entry books, the source of truth for money | [sprout-ledger](https://github.com/SaiNayakk/sprout-ledger) | `v0.2.0` |
| Payments: adding money by UPI, withdrawing | [sprout-payments](https://github.com/SaiNayakk/sprout-payments) | `v0.1.0` |
| Orders: orders, risk checks, holdings, intraday positions, charges | [sprout-oms](https://github.com/SaiNayakk/sprout-oms) | `v0.1.3` |
| Sprout Bank: a simulated customer bank with UPI PINs (not part of Sprout) | [sprout-bank](https://github.com/SaiNayakk/sprout-bank) | `v0.1.0` |
| Sprout Stock Exchange: a simulated exchange (not part of Sprout) | [sprout-exchange](https://github.com/SaiNayakk/sprout-exchange) | `v0.1.0` |
| Platform: hosts, release manifests, pre-prod, these docs | [sprout-platform](https://github.com/SaiNayakk/sprout-platform) | this site |

Next: settlement (T+1 clearing and the depository), then statements, and the web app.

## How to read this site

- **Overview** explains the shape of the system and how a change reaches production.
- **Testing** catalogues every end-to-end journey and edge case, every performance test and every
  chaos experiment, each with a hypothesis and a pass condition.
- **Reliability** holds the targets, the **evidence** from each pre-prod run (generated, not written by
  hand), runbooks and incident write-ups.
- **Decisions** records why things are the way they are, including the options that lost.
- **Errors** explains every error code an API can return. Error responses link straight to it.

## Run it yourself

You need Docker, Java 21 and Maven.

```bash
git clone https://github.com/SaiNayakk/sprout-platform && cd sprout-platform
preprod/run.sh --keep
```

That builds the release, starts a fresh environment, runs every test against it and writes the
evidence. `--keep` leaves it running at `http://localhost:8100` so you can explore; add
`--observability` for Grafana at `http://localhost:3000`.
