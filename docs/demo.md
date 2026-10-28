# Demo in five minutes

A walkthrough for showing Sprout to someone live. Run it from the public address; everything here
works without touching either cell's machine directly.

---

## 1. Open the site and place an order

1. Go to **https://sprout-saiworks.nncs.in**.
2. On the home page, click **Try a demo account**. Type any name. The sandbox gives you a named demo
   customer with money already in their account; no sign-up, no real details.
3. Open any stock and buy one share at market. The exchange fills it at the current simulated price.
4. Open your holdings to see the share and the money it cost.

---

## 2. Show the status page

Open **https://sprout-saiworks.nncs.in/status**.

Both regions should show **Up**, "serving normally". Point out the **pill in the
bottom-left corner of every page** on the site — it reads the same status endpoint and turns amber or
red if anything changes.

Explain briefly: Region A is the phone, Region B is the laptop. Each serves its own customers but
holds a copy of the other's database, so if one is lost the other can take over.

---

## 3. Break a cell live

You can take down either cell while the demo customer watches.

**Laptop (Region B):**

```bash
# See deploy/laptop for the compose project name and env-file path.
docker compose --env-file data/.env -f docker-compose.yml stop
```

**Phone (Region A):**

```bash
sprout stop
```

Then watch **/status**:

| Time | What /status shows |
|---|---|
| ~30 s after the stop | The region turns amber: "not responding" |
| ~90 s after silence at the witness | The other cell is granted the right to take over |
| ~3–5 min total | The lost region shows "served by Region X"; the demo customer can trade again from the same address |

The 90 s delay before the witness grants the takeover is intentional: the phone on mobile data
sometimes drops off the network for 30–60 s, and an unnecessary takeover costs minutes of failback.

!!! note
    The demo customer's session is not interrupted. They may see a short window of errors while the
    takeover completes, then orders work again at the same URL.

---

## 4. Bring it back

**Laptop:**

```bash
docker compose --env-file data/.env -f docker-compose.yml start
```

**Phone:**

```bash
sprout start
```

The returning cell first catches up on what happened while it was away, then is given its customers
back automatically. Writes are refused for a few seconds at the cutover. "What happened lately" on
**/status** lists each step, ending with the region "serving its own customers again".

---

## 5. What to say while waiting

- **Why a witness?** Without a third party, each cell can only guess whether the other is gone or
  just unreachable. The witness has seen both; if it still hears the other cell, it vetoes the
  takeover, so a network partition can never cause two cells to serve the same customers at once.
- **Why 90 s and not 30 s?** A phone on mobile data can drop off the network for 30–60 s without
  any failure on Sprout's side. The first time the laptop tried to take over after a 40-second blip
  it cost 12 minutes of failback.
- **Why keep a copy of the other's database?** Logical replication means the other cell already has
  every row when it is needed; there is no backup to restore while customers wait. A journal of
  recent writes covers what replication had not delivered yet.
- **What "fail open" means for the witness?** The witness can only add a veto. If neither cell can
  reach it, they fall back to their own rules and carry on as if it did not exist. The witness being
  down can never block a failover; it can only prevent a premature one.

---

## 6. If something goes wrong

See **[Runbooks](runbooks.md)** for step-by-step guidance on the most common failures: a host not
answering, a stuck order, a settlement break, pre-prod failing.
