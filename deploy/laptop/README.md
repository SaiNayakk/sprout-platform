# Sprout on a laptop

Runs the whole of Sprout (the four hosts, Postgres, NATS), the web app and a Cloudflare tunnel, so it can be
visited from anywhere for as long as the machine is left on. It is the stand-in for the phone: the same
host jars at the same pinned releases, wired exactly as pre-prod wires them.

```bash
deploy/laptop/up.sh            # build and start everything (safe to run again), then print the address
deploy/laptop/up.sh --local    # without the tunnel: http://localhost:18080, this machine only
deploy/laptop/up.sh --down     # stop everything; the data is kept
```

## What is the same as pre-prod, and what differs

`render.py` writes `docker-compose.yml` **from pre-prod's compose file**, so every service's wiring is the one each
release was tested against. It then changes only what has to differ, and fails loudly if pre-prod's file stops
looking the way it expects:

| Pre-prod | Here |
|---|---|
| Throwaway secrets in the repository | Real secrets, generated once into `data/.env` (never committed, never printed) |
| Everything destroyed after the run | Data on a Docker volume; hosts restart by themselves |
| Ports published for the tests | Only the web app, and only to this machine (`127.0.0.1:18080`); the tunnel reaches it by name |
| The demo market starts when the stack does | Its start date and epoch are fixed once, so a restart or a reboot resumes at the right session (`marketdata` 0.2.0) |
| Bank requests wait 30 seconds | 5 minutes |
| The fictional payroll on the repository's dev keys | On generated keys |

The gateway never forwards `/internal`, `/partner`, `/member`, `/participant` or `/actuator` (gateway 0.3.2), so
the keys that guard them are not the only thing between the internet and those doors.

## What it needs from the machine

- **Docker Desktop**, set to start when you sign in, with about 3 GB for containers (the hosts' memory limits add up to 1.7 GB).
- **The machine awake.** A laptop that sleeps takes the site down, and a lid closed on battery usually sleeps it.
  Power settings are yours to change: *never sleep when plugged in* is what this needs.
- **Cloudflare**: `cloudflared login` once (the certificate in `~/.cloudflared`). The first `up.sh` creates a tunnel
  called `sprout-laptop` and points `SPROUT_HOSTNAME` (in `data/.env`) at it.

## Moving it back to the phone

The phone's hosts are the same jars. Stop this (`up.sh --down`), point the tunnel's hostname back at the phone, and
start the phone's hosts (`deploy/phone/`). Postgres data does not move on its own: a customer made here isn't on the
phone. The sandbox's fictional customers are made again by the sandbox itself.

## Looking after it

```bash
docker compose --env-file data/.env -f docker-compose.yml ps            # what is running and healthy
docker compose --env-file data/.env -f docker-compose.yml logs -f edge  # a host's structured logs
```
