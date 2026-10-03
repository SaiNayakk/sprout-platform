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

## Pre-prod fails

1. Open the run's evidence page under [Evidence from runs](reliability/runs/index.md): it says which
   stage failed.
2. Re-run with `preprod/run.sh --keep` and reproduce against `http://localhost:8100`.
3. Never edit thresholds to make a run pass without writing down why in the pull request.
