# Resilience audit, October 2026

An audit of the cells' failover logic (ADR-027) before go-live: every claim was either **run** against the live pair
(the phone and the laptop, with no customers on them) or **read** in the code, and each finding says which. The scripts are
in [`deploy/cells/audit/`](https://github.com/SaiNayakk/sprout-platform/tree/main/deploy/cells/audit). The decisions it led to
are in the plan at the end.

## What was run

| # | Experiment | Result |
|---|---|---|
| 1 | Replication into the laptop switched off silently; 3 minutes of orders into cell A | **292 orders acknowledged, 0 in the copy. Both cells reported NORMAL and healthy for the whole time.** Nothing notices a dead replication. |
| 2 | The phone's web server frozen 90 s; 12 clients hammer the laptop's own address | **Throughput 40 → 5.8 orders/s, median latency 240 ms → 2,073 ms.** Every write waits out the 2 s timeout of the journal call to the peer. |
| 3 | One-way blindness: the laptop cannot see a healthy phone for 5 minutes | The laptop took cell A over, the phone fenced and became TAKEN_OVER, and **stayed so after the partition healed**. **25 orders acknowledged by the healthy phone are not in the live copy**: they arrived in the 13 s between the journal replay and the phone learning it had been taken over. |
| 4 | Mutual blindness: neither cell can see the other, customers reach both | **Both took the other over within 3 s and ended HOLDING each other.** Four databases live and diverging, no way out. The phone's takeover took 6 minutes (standby start 191 s, then 3,042 writes replayed one at a time in 179 s) and blocked its watcher throughout. |
| 5 | Both addresses silent for 3 minutes (the home internet drops) | Passed: both fenced at about 60 s and **neither took the other over**. But writes were refused for **5.5 minutes**: after the outage each cell waits 210 s of health before it unfences. |
| 6 | A takeover that fails after it disabled replication (the standby container is gone) | **Both cells NORMAL and healthy, replication into the laptop disabled for good.** Nothing re-enables it. |
| 7 | All eleven laptop containers stopped together and started together (a reboot's second half) | Cell B answered customers again 32 s after the start. A real reboot adds Windows sign-in and Docker's engine start. |
| 8 | Stale status after a cleanup | A healthy cell was fenced because the restarted watcher believed the other's last status file (up to 90 s old, written before that watcher was killed). |

## What was read

- **`HOLDING` and `TAKEN_OVER` have no exit, and `HOLDING` ignores a peer that holds it.** Mutual takeover is the result.
- **Failed journal replays are never retried.** On 9 October 17 customer account openings failed and were replayed by hand.
- **The replay window is a fixed 2 hours** and ignores how far the copy is behind. A replication gap longer than that loses writes silently.
- **A failed takeover leaves replication disabled** (the subscription is disabled before the standby is started) and waits 10 minutes before trying again.
- **A takeover blocks the watcher** for its whole length: no fencing and no peer checks during the minutes it takes.
- **Fenced and taken-over cells keep running their background jobs** (the fence stops customer writes at the gateway only). The phone's database took scheduled orders for 11 hours while TAKEN_OVER.
- **Failback is a script**: not resumable, not safe to interrupt, and the other cell is fenced for its whole 6 to 8 minutes with no way back if the restore fails.
- **No alerting anywhere.** The 10-hour split of 9 October was found by accident.
- **Replication has no monitoring** and the phone's WAL has no cap (`max_slot_wal_keep_size = -1`), so a stalled peer grows it without limit.
- **Archived databases and dumps are never removed** (six of about 400 MB on the phone, eight dumps on the laptop's F: drive).

## Plan

The changes, in the order they should land. Each is tested by the experiment above that found it.

1. **Take decisions out of the cells' hands: a lease witness.** A tiny external service (a Cloudflare Worker with a Durable Object, free) holds one lease per cell. Each cell renews its own every 5 s with a 30 s lifetime. A cell takes the other over only by winning a compare-and-set on its lease, and a cell that cannot renew fences itself. This ends mutual takeover, stops a returning cell serving (it finds a higher epoch at once), cuts detection from 120 s to about 30 s, and removes the 210 s unfence wait.
2. **Automatic failback.** First version: the current script as a resumable, idempotent state machine run by cellwatch, started when the returning cell has been healthy and in sync for 5 minutes, with a rollback if it does not come up. Second version: build the new database from the promoted copy by logical replication while it keeps serving, then swap with a short fence (about 30 s of downtime instead of 6 to 8 minutes).
3. **Close the write-loss windows.** The holding cell keeps replaying the journal until the peer confirms it is fenced; replay is retried until zero failures, starts from the copy's own replication position, and runs in parallel per customer.
4. **Decouple the journal.** A circuit breaker, so a slow peer costs nothing after the first few failures; a metric for unprotected writes, with an alert.
5. **A dead host is a dead cell.** Probe all four hosts directly; a host refusing connections for 60 s fences the cell and says why; the peer acts on that announcement (target 3 to 4 minutes, from 13.5).
6. **Fence the background jobs** (or keep them harmless): a TAKEN_OVER cell stops its schedulers.
7. **Make takeover atomic and resumable:** start the standby before disabling the subscription; re-enable it if the takeover aborts; do it in a worker thread so the watcher keeps watching.
8. **Monitor and alert.** Replication lag and state, WAL size, disk, memory, clock skew, battery, the journal's unprotected count, and every state change, pushed to the owner's phone (ntfy), plus an external dead-man's switch.
9. **Housekeeping:** a WAL cap with automatic resync, retention for archives and dumps, a monitored clock, a LAN path between the cells as a second route for health and forwarding.
10. **Boot resilience:** the laptop signs in and starts Docker by itself and does not restart for updates unannounced; the phone stays plugged in and restarts Sprout after a reboot.
11. **A standing resilience suite:** every experiment above, plus CHAOS-12, 16 and 17, run as one command with pass or fail, so none of it can regress.

## What came of it

Each finding was fixed, and the fix is tested by one of the scenarios of the [resilience suite](resilience.md).

| Finding | Now |
|---|---|
| A cell wrongly taken over never got its customers back | **Failback is automatic**: the cell builds a new database from the holder's copy while the holder keeps serving, then a cutover of about 3 s |
| Two cells took each other over for good | A cell finds out that it was replaced; when both took each other over, one gives way. The home network can veto a takeover that only Cloudflare asks for |
| 25 acknowledged orders lost in a false takeover | The journal is replayed for as long as the cell holds the other's customers, not once |
| Replication could stop silently | The watcher switches it back on within 30 s and alerts; a failed takeover rolls back and re-enables it |
| A slow peer cut the healthy cell's throughput by 86% | A circuit on the journal call (gateway 0.5.0): 22.7 orders/s against 23.8 |
| A dead host took 13.5 minutes to replace | The cell fences itself after a minute and says why; the other takes over 30 s later: **orders back in about 3 minutes** |
| Writes refused for 5.5 minutes after the internet dropped | Both unfence 45 s after it is back |
| No alerts anywhere | ntfy pushes for every state change and for replication, disk, clock, battery and unprotected writes |
| Failed journal replays never retried | Retried every few seconds until they succeed |
| A fixed two-hour replay window | From where the copy last heard from the other cell, out of a three-day journal archive |
| A takeover blocked the watcher | It runs in a worker, and rolls back if it fails |
| The holder dying left the cell it held with nobody serving it | The standby journals in the cell it serves; that cell resumes after 5 minutes and replays what was journalled with it |
| The phone's WAL had no cap; archived databases piled up | A cap of 8 GB, and a retention of the newest three or three days |

## Found while building it

The suite found five more bugs in the new code before they could matter; each is now a unit test or a scenario.

- The first automatic failback put the cell back to TAKEN_OVER 14 s after it finished, because the holder's last status (up to 90 s old) still said it held the cell. A claim now counts only if it was published after the cell last became NORMAL, with a margin for the phone's clock, which runs about 9 s ahead of the laptop's.
- Databases that cellwatch created on the phone belonged to the OS user, not to the role the services connect as, so the standby could not start (`permission denied for schema oms`).
- The heartbeat and a failback worker both wrote the status file through the same temporary file name, and one rename lost the race: one failback rolled back.
- Two fenced cells after a shared outage each waited for the other to be NORMAL before using the fast unfence.
- A holder whose cellwatch alone survived (answering over the home network that it was not well) stopped the cell it held from resuming: the home network now only vetoes a holder that is *serving*.
