# Resilience

What the two cells do when something fails, how fast, and how that is checked. The design is
[ADR-027](../decisions.md#adr-027-cells); the audit that led to this version is [Resilience audit](audit.md).

## What happens, with no hands

| Something fails | What the cells do | Orders work again |
|---|---|---|
| A **host** of one cell stays down | It fences itself after a minute and says why; the other cell takes its customers over 30 s after that announcement; when the host is back and stable for 3 minutes the customers are **given back automatically** (3 s of refused writes) | **175 s** (was 813 s) |
| A host crashes and restarts itself | Nothing: a 30 s blip is not a failure, and nothing is fenced | 27 s |
| A **whole cell** is lost (the phone, or the laptop) | The other cell sees its address go silent and takes over; when the lost cell is back it is given its customers back | **177 s** (phone), **276 s** (laptop) |
| Cloudflare shows each cell silent to the other, but both are fine | The home network shows both up: **nobody takes anybody over** | no interruption |
| The cells cannot see each other at all (both paths), but both reach the witness | The [witness](#the-witness) sees both alive and **forbids any takeover**: nobody leaves NORMAL | no interruption (longest gap between orders 3 s) |
| The cells cannot see each other, and the witness cannot be reached either | Each may take the other over (the old behaviour: the witness is never required); when they can see each other again, **one gives way** and the customers are handed back | back to normal 164 s after healing |
| Both addresses go silent (the home internet drops) | Both fence, neither takes the other over, and both **unfence 45 s after the addresses are back** (was 211 s) | writes refused for the outage plus 45 s |
| A takeover cannot start its standby | It rolls back, puts the replication it paused back on, and tries again in 2 minutes | |
| The cell holding another's customers dies too | The cell it held resumes from its own database after 5 minutes, replays what the holder journalled with it, takes the dead holder over, and gives way when the holder returns | see `holder_dies` in the [suite](../testing/chaos.md#resilience-suite) |
| Replication stops silently | The watcher turns it back on within 30 s and alerts | |
| A slow other cell | The journal's circuit opens after a few failures: the healthy cell keeps its speed (**22.7 orders/s against 23.8**; it was 5.8 against 40) | |

Every one of these ends, by itself, with both cells NORMAL and replicating, and with every order a customer was told
succeeded present exactly once.

## The witness

A small Cloudflare Worker (`deploy/witness`, free plan) that neither cell controls. Each cell tells it every 10 s that it is alive and in
what state; that is its **lease**. The status page shows a region as not responding after 30 s of silence, but another cell may take it
over only after **90 s** (2026-10-20: the phone, on mobile data, went quiet for about 40 s, the laptop took it over, and getting its customers back
took 12 minutes; see [Incidents](../incidents.md)).

- A cell may take the other over only if the witness says the other's lease has lapsed, or that the other declared itself out. A cell
  that both paths show nothing of, but that the witness hears, is alive: that ends the double takeover.
- The witness's word also shortens detection of a dead cell a little (90 s instead of 120 s). End to end the gain is small (177 s and 276 s to
  orders back, against 151 s and 221 s before: the standby's start and the journal's replay take most of the time, and the laptop's figure
  includes Docker). It was 30 s until the phone moved to mobile data, whose short dropouts looked like deaths.
- **It is never required.** If a cell cannot reach it, the cell decides as it did before there was one. So the witness can only add a
  veto or a faster verdict; it cannot stop a failover by being down. The cost is that two failures at once (a blind pair and a dead
  witness) still give the old double takeover, which still heals itself.
- It serves the public status that the website's status pill and `/status` page read, and, once a minute, checks whether both cells are
  silent: if both have been for 3 minutes it pushes an alert to the owner's phone (the dead-man's switch).

## Alerts

Each cell pushes to the owner's phone ([ntfy](https://ntfy.sh), a private topic) for: a fence and why, a takeover and
how long it took, a failure, a failback and its cutover time, a double takeover, replication off or behind, a lost
replication slot, writes that have no copy in the other cell, a nearly full disk, clocks that disagree, and (on the phone)
the battery. Alerts are logged whether or not a topic is set.

## The resilience suite

```
python deploy/cells/resilience/run.py [scenario ...]
```

Needs both cells up. Each scenario creates customers who keep ordering through the public address, breaks something,
waits for the system to repair itself, and checks the time to recover, that **every order acknowledged exists exactly
once**, and that both cells are NORMAL and replicating again. Scenarios: `dead_host`, `kill_cell_a`, `kill_cell_b`,
`cf_blind`, `mutual_blind`, `blind_no_witness`, `both_offline`, `failed_takeover`, `holder_dies`. Results are kept in
[`deploy/cells/results/`](https://github.com/SaiNayakk/sprout-platform/tree/main/deploy/cells/results) (a JSON per run and the
states every few seconds). The rules themselves are tested with `python -m unittest discover -s deploy/cells -p 'test_cw_*.py'`,
which runs in CI: each test is an incident (a returning cell that unfenced too soon, a cell fenced again by a stale status,
two cells holding each other) written down.

## Not done yet

- **Boot.** The laptop starts Docker only after someone signs in to Windows; the phone does not restart Sprout after a
  reboot by itself.
- **A warm standby** (taking over in seconds instead of about 90 s): the standby's start is now most of the time to recover.
- **The phone's cellwatch was killed once without a trace** on 2026-10-11 (the log is silent; the starter had just started it) and
  nothing restarted it until it was started by hand. The witness noticed within 30 s and the laptop began a takeover that its own
  checks aborted, but a watcher of the watcher is needed.
