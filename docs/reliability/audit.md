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
