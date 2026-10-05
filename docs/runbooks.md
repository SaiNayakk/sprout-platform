# Runbooks

What to do when something specific goes wrong. Each starts from what you'd see.

## Sign-in returns `503 UPSTREAM_UNAVAILABLE`

**Means:** identity can't reach its database. Identity is up; it is refusing fast on purpose.

1. Is Postgres running? On the phone: `pg_ctl status`. In pre-prod: `docker compose ps postgres`.
2. If it is stopped, start it. Identity reconnects by itself within seconds ([CHAOS-01](testing/chaos.md#chaos-01));
   don't restart identity.
3. If it is running, check it accepts connections (`psql -c 'select 1'`) and isn't out of disk.
4. Search the edge logs for the request id from the error to see the underlying exception.

## Requests return `504` or hang

**Means:** something took longer than the gateway's 5 s budget. That should not happen for identity,
which answers within about 2 s even when its database is down.

1. Check the edge host's memory and CPU. A host at its memory limit spends its time in garbage
   collection.
2. Look for the slow requests by request id in the logs.
3. Restart the edge host only if it is unresponsive; note the time for the incident record.

## Prices aren't moving

**Means:** the market is closed, or the market clock has stalled.

1. `GET /api/marketdata/v1/market`. `state: CLOSED` outside 09:15-15:30 IST and at weekends is normal.
2. If it says `OPEN` but `marketTime` isn't advancing, check the trading host's health: the `market`
   component turns `DOWN` when the clock is more than 30 s behind. Restart the trading host; clients
   reconnect and get fresh quotes.

## Price streams keep dropping

1. Is the trading host restarting? Streams end when it does (by design, so clients reconnect).
2. Is something between the app and the gateway buffering or cutting long responses? The gateway sends
   `X-Accel-Buffering: no` and market data sends a heartbeat every 15 s, which is well inside
   Cloudflare's 100 s idle limit.
3. Many `429`s on stream requests mean a client is opening streams without closing old ones.

## A deposit was approved in the bank but isn't in Sprout

1. Is the money host up? The bank keeps the approval and retries its callback (up to a minute apart)
   until payments acknowledges it ([CHAOS-05](testing/chaos.md#chaos-05)).
2. The reconciler also asks the bank about every deposit still waiting after 10 s, so even a lost
   callback is found.
3. Never credit by hand: post nothing to the ledger yourself. When payments sees the approval it
   credits once, with the deposit id as the ledger's idempotency key.

## A withdrawal is stuck in PROCESSING

The money is held (it shows as `withdrawing`), not lost. It means the bank, or the ledger, didn't answer
when payments asked. The reconciler repeats the idempotent payout every few seconds; it completes once
the bank answers ([CHAOS-04](testing/chaos.md#chaos-04)). Check that the street host is up.

## The books don't match the bank

RECON-01 compares the ledger's `sprout:bank` with Sprout's account at Sprout Bank. A difference means
money moved on one side only. Stop withdrawals, list both sides' movements since the last matching
run, and fix with a reversing ledger entry (never an edit; the journal can't be edited).

## An order is stuck in PENDING

Its money is blocked, not lost: the exchange didn't confirm it. The order service asks the exchange about
it every few seconds; if the exchange has it, its state is applied, and if the exchange says it never
got it, the order is rejected and the money released after 30 seconds ([CHAOS-06](testing/chaos.md#chaos-06)).
Check that the street host is up.

## The order service logs "The ledger refused"

An entry the order service decided on (a fill or a release) was refused by the ledger. That is a bug, not
an outage: the entry stays in `oms.ledger_outbox` with `last_error`, retried every round, and nothing after
it is skipped. Find the order by the entry's reference, fix the cause, and the next round posts it.
RECON-02 fails while any entry is unposted.

## A settlement is a break

The clearing corporation's obligation for a trade date didn't match Sprout's books, so the back office
stopped with nothing paid. `GET /v1/settlements` on the settlement service (with the service key) shows
the reason: the money differs, or a client's shares bought or sold do. Compare the clearing
corporation's lines (`GET /member/v1/settlements/{id}`) with the order service's summary of the day.
Usually one side is missing an execution: check the exchange's trade tape and the order service's
outbox. Fix the books (never by editing the journal), then set the settlement back to `RECEIVED` to
check it again.

## A settlement waits for funds

The clearing corporation is `AWAITING_FUNDS` until Sprout's payment appears in its bank statement with the
obligation's reference. The back office pays as soon as the obligation matches; if Sprout Bank refused
(not enough in Sprout's account), the payment is retried every round. Check `sprout@sproutbank`'s balance.

## A customer owes Sprout (dues)

An intraday loss bigger than the customer's money (a gap through the 90% early close) leaves `dues`. The
risk round takes them from the customer's cash whenever there is some, so their next deposit pays them off
first. Nothing to do unless they stay unpaid.

## NATS is down

Prices keep reaching clients; only events for other services stop, and they are dropped rather than
queued. Restart NATS; market data reconnects by itself within seconds
([CHAOS-02](testing/chaos.md#chaos-02)). Check the `nats` component of the trading host's health.

## Many `429 RATE_LIMITED`

**Means:** one client address is over its limit (10 sign-ins a minute, 120 other requests a minute).

1. Check whether the requests share a real address or all appear to come from one place. If every
   request has the same address, the gateway isn't trusting `CF-Connecting-IP`: check
   `GATEWAY_TRUST_CF_IP` is `true` behind Cloudflare, and **only** behind Cloudflare.

## Everyone is signed out (`401` on every refresh)

**Means:** the token signing key changed, or a refresh token was reused and its session ended (that one
affects only one user).

1. Check the signing key file hasn't been replaced (`IDENTITY_SIGNING_KEY_PATH`).
2. If one user reports it, it's reuse detection doing its job ([E2E-30](testing/e2e.md#e2e-30)).

## Finding a service's logs in a host

Several services share each host's JVM and its log. Every JSON line carries the host
(`service.name`, e.g. `edge-host`, and its version) and, for lines written by a service's own code,
which service and version wrote it (`sprout.service`, `sprout.service.version`). Filter on
`sprout.service` to see one service. Lines from Spring or libraries have no `sprout.service`; follow
the `requestId` to connect them to a request.

## Pre-prod fails

1. Open the run's evidence page under [Evidence from runs](reliability/runs/index.md): it says which
   stage failed.
2. Re-run with `preprod/run.sh --keep` and reproduce against `http://localhost:8100`.
3. Never edit thresholds to make a run pass without writing down why in the pull request.
