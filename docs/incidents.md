# Incidents

Blameless write-ups: what happened, why, and what changed so it can't happen the same way again.
These come from the infrastructure Sprout will share with the other apps on the phone.

## 2026-09: a public site's stats were blank on iPhones, fine on desktops

**Impact.** For several days the live server stats on the portfolio site were blank for visitors on
iPhones, while the same page worked on desktop browsers.

**Timeline.**

1. Reported from an iPhone. Desktop checks passed, so it looked like a phone browser problem.
2. A missing CORS header on preflight requests was found and fixed. That was a real bug, but the stats
   stayed blank.
3. An early theory that the iPhone's requests never reached the phone was wrong: the wrong metric was
   being watched.
4. The real cause: **two tunnel processes** were running. One had started before a configuration change
   and still served the old routes, answering some requests with an empty `404`. Which process a request
   reached decided whether it worked, and the pattern happened to line up with device type.

**Root cause.** Nothing stopped a second tunnel starting, and nothing checked for a stale one.

**What changed.**

- The deploy tool refuses to continue when more than one tunnel process is running.
- The process supervisor stops a service's whole process tree, and re-adopts a running process only
  when its process id **and** start time match, so it can't mistake an unrelated process for its own.
- Testing on iPhone browsers (WebKit), including CORS preflight, is part of checking a release.

**Lesson for Sprout.** Two copies of anything that should be single (a tunnel, a scheduler, a matching
engine) are worse than none, because they fail intermittently. Singletons get an explicit check.

## 2026-10: a service merged before its CI had run

**Impact.** None in production. `sprout-gateway`'s first pull request merged with no CI result, because
the workflow file was invalid and branch protection wasn't on yet.

**What changed.** Branch protection is set up before the first merge in every repository, and merges
wait for a green check, not just the absence of a red one.

## 2026-10-05: the first production start found two bugs pre-prod couldn't

**Impact.** Sprout's first deploy to the phone. Nothing was public yet.

1. **The edge host wouldn't start: identity couldn't read its signing key from a file.** Nimbus's PEM
   parser needs BouncyCastle, which isn't a dependency. Every test and pre-prod run had used a generated
   in-memory key, so that path had never run.
   *Changed:* identity `0.2.3` parses the key with the JDK, with a test that loads a key file shaped like
   the phone's; **pre-prod now loads its signing key from a file too**, and immediately reproduced the bug
   with the old version.
2. **Every restart left the old process running.** Backseat, the phone's process supervisor, stopped an
   app by walking its process tree with psutil; on Android that raises `AccessDenied`, and the code then
   gave up on the whole tree, root included. The new copy found its port taken and crash-looped.
   *Changed:* Backseat `v0.3.4` stops an app by signalling its process group, with a test that fakes
   Android's refusal.

**Lesson.** Pre-prod has to mirror production's configuration, not just its code: the same secrets
*shape* (a key in a file, not generated), the same supervisor behaviour. Both bugs were in the gap.

## 2026-10-05: library releases didn't publish

**Impact.** None in production. Four releases (contracts `v0.3.0`, `v0.3.1`; gateway `v0.2.0`, `v0.2.1`)
never became available to the services that depend on them, and the gateway's `v0.2.2` built only when
asked for by commit.

**What happened.** JitPack, which turns git tags into Maven artifacts, started running builds on Java 8
even when Java 21 was selected, so Maven couldn't start. Diagnostic builds on scratch branches found
the cause and a fix (install Java 21 and point `JAVA_HOME` at it explicitly). Builds of the gateway's
tags kept failing intermittently after that, while builds of the very same commits succeeded.

**What changed.**

- Every repository builds on JitPack with the Maven wrapper and Java 21 set explicitly, and the build
  logs the wrapper's steps so a failure can be diagnosed from JitPack's log.
- It recurred: the gateway's `v0.2.4` failed both as a tag and as a commit. So hosts no longer get
  services from JitPack at all; they build each service from its release tag
  ([ADR-011](decisions.md#adr-011-build-from-tags)).
- The contracts moved too: they now publish themselves to a Maven repository on their own GitHub
  Pages, and identity `0.2.2` and market data `0.1.1` take them from there. Nothing in the release path
  uses JitPack.
- Versions that JitPack never published don't matter to hosts any more; they are still listed here:
  contracts `v0.3.0` and `v0.3.1`, gateway `v0.2.0` and `v0.2.1` (use `v0.3.2` and `v0.2.4`).

## 2026-10: a release tagged on a failing commit

**Impact.** None in production. `sprout-identity v0.2.0` was tagged while its CI was failing, because
the release commands were chained so that a failure didn't stop the next step.

**What changed.** The tag was withdrawn and `v0.2.1` released from a green commit. Release steps are
chained so any failure stops everything after it. `v0.2.0` must never be used.

## 2026-10: Phase 3's pre-prod runs found three bugs before release

**Impact.** None outside pre-prod: the gate did its job three times.

1. **The trading host didn't start.** Adding the order service put database libraries on the trading
   host's classpath, so Spring Boot tried to give market data (which has no database) one too, and failed.
   The edge host already guarded the gateway against exactly this; the guard now lives in shared host code
   (`NoDatabase`) and both hosts use it.
2. **An order the exchange never received stayed `PENDING`, its money blocked** (CHAOS-06). The
   reconciler gave up on such an order 30 s after `updated_at`, but asking the exchange about it touches
   `updated_at`, so at the real pace (a question every 10 s) the 30 s never passed. The unit test had moved
   the clock 40 s in one jump and couldn't see it; RECON-02's "nothing left hanging" check used
   `updated_at` too and missed it the same way. Orders now record when they were sent, the give-up counts
   from that, the test runs the risk desk a round per simulated second, and RECON-02 counts from the send.

3. **Placing an order while the exchange was gone took longer than the gateway waits** (CHAOS-06 on CI).
   Locally it answered in 2.1 s; on CI it took over 5 s, so the customer got a `504` while their order
   sat `PENDING` with its money blocked (safe, but invisible to them). Looking up a vanished host's name
   isn't covered by the HTTP client's connect timeout. Every call from the order service now has a hard
   deadline covering everything (3 s; 2 s for the exchange), and a test stalls the exchange to prove the
   customer hears back in time and the order is settled later.

**Lessons.** A timestamp that means "last looked at" can't also mean "how long it's been". Tests of
anything time-based run at the real cadence, not in one jump. A timeout setting isn't a deadline: bound
the whole call.

## 2026-10: a pre-prod test read a list while it was still being written

**Impact.** One red CI run on `main` after the Phase 2 release; nothing reached the phone.

**Cause.** The live-price journey (E2E-44) read a `subList` view of the event list while ticks were still
arriving on another thread, which throws `ConcurrentModificationException` when one lands mid-read. It
passed on the pull request and failed on `main` by timing alone. The test now reads a snapshot. The same
run showed k6 couldn't save its summaries on CI (the output folder belonged to the runner's user);
`run.sh` now opens it up.

## 2026-10: the phone's setup script failed on a typo pre-prod never runs

**Impact.** The first Phase 2 phone setup stopped with a Python `SyntaxError` before changing anything.

**Cause.** A line break inside a Python string embedded in `setup.sh`. Pre-prod builds containers, not
phones, so the phone scripts had no test at all. CI now checks every phone script's shell syntax and
compiles the Python inside them (`deploy/phone/check-scripts.py`), and it fails on the old script.

## 2026-10-08: the phone rebooted itself in a loop after Sprout moved onto it

**Impact.** About an hour with every site on the phone down (Sprout and the other apps it hosts). The phone
had to be booted into safe mode to stop it.

**Timeline.**

1. Sprout moved from the laptop to the phone and ran well: four host JVMs, about 820 MB, 1.3 GB still free.
2. The phone rebooted. At boot, Termux:Boot started Backseat, and Backseat started **every** app at once: the
   phone's own sites, Postgres, NATS and four JVMs warming up. Android rebooted the phone under the load, and the
   next boot did the same.
3. Safe mode (which doesn't run Termux:Boot) and a force stop broke the loop; Sprout's apps were marked stopped.

**Root cause.** Each part of Sprout was its own Backseat app, and Backseat starts all apps together. Starting
everything at once had been tested only on a machine that was already up and idle, never on a phone booting.

**What changed.** Sprout is one Backseat app, `deploy/phone/start.sh`: it waits until the phone has been up five
minutes, starts one piece at a time (each only once the one before is healthy and memory allows), at a lower
priority with fewer JVM threads, restarts a piece that dies, and backs off ten minutes if pieces keep dying.

**Lesson.** A deploy isn't proven until the machine has rebooted with it on.

## 2026-10-08: a rename that passed pre-prod failed on the phone's real data

**Impact.** About 10 minutes of Sprout partly down on the phone (orders and settlement), during the release that
renamed the stock CHAIWALA to BREWBERRY.

**What happened.** Each service that stores the symbol shipped a migration renaming it. Two failed on real rows:
the ledger's journal is immutable and its trigger refused edits to old entry descriptions, and the depository's
movements refer to transfers by instruction id, so renaming the ids broke the foreign key. Postgres rolled both
back. Pre-prod passed both because it starts from an empty database. Worse, the starter reported the street host
healthy because its bank answered, though its depository had failed and the host was exiting.

**What changed.**

- The ledger keeps its journal as posted (a no-op migration explains why); the depository renames only the symbol,
  never instruction ids, which are idempotency keys.
- `deploy/phone/rehearse.py` applies a deploy's pending migrations to a copy of the phone's data before the phone
  does. Run against the failed release, it reports the same foreign-key error.
- The starter calls a host healthy only when every service in it answers, not just the first.

**Lesson.** A data migration is tested on data. An empty database proves only that the SQL parses.

## 2026-10-08: a capacity experiment froze the edge host for ten minutes

**Impact.** About 10 minutes with Sprout's API not answering (the site loaded; signing in, prices and everything
behind them didn't), during a deliberate capacity test on the phone.

**What happened.** To lift the gateway's 32-thread ceiling, every service was switched to Java 21's virtual threads.
Up to 400 test customers it ran as before; at 600 the edge host stopped answering entirely, with its CPU *falling*:
waiting, not working. The JVMs had been capped at two processors (`ActiveProcessorCount=2`, for gentle boots), which
gives virtual threads only two carrier threads, and on Java 21 a virtual thread that blocks inside `synchronized`
code (the HTTP client, the connection pool, logging) pins its carrier. With both pinned, nothing ran. The process
stayed up, so the starter, which only checked that processes were alive, left it hung; it also ignored the polite
stop signal and had to be killed outright.

**What changed.**

- Virtual threads are off; the gateway's ceiling is raised with a larger ordinary thread pool instead, measured
  like every other change. (Java 24 removes this kind of pinning; Sprout runs 21.)
- The starter now treats a piece that stops answering health checks for two minutes as dead, kills it and starts
  it again. The bar is deliberately lenient so a host that is only busy is never killed for it.

**Lesson.** A setting that removes a limit moves the limit somewhere else. Capacity experiments change one thing at a
time, on a path that can be undone in seconds, and watch for the system getting quieter as well as busier.

## 2026-10-09: both cells served the same customers, twice in one hour

**Impact.** Two short split-brains in the cells, both during testing: for 15 minutes cell A's
customers were served by both the phone and a standby on the laptop, and for 5 minutes cell B's by both
the laptop and a standby on the phone. No customer wrote anything in either window. Each cell's
scheduler still ran, though, so 5 goal auto-invest orders and 3 mandate debits were made twice: once in
the real database and once in the standby's copy. The copies were thrown away. Nothing was lost and
nothing reached a customer's books twice.

**Timeline.**

1. **10:51.** `failback.sh b` killed the phone's cellwatch with `pkill -f cellwatch.py` over ssh. The
   pattern matched the ssh shell's own command line, so the script died before it restarted the laptop's
   services.
2. **10:54.** The phone's status file went stale, and the laptop counted cell A as lost after 120 s. It
   took cell A over **while the phone's services were up and serving**: only its watcher was gone.
3. **11:03.** A capacity run pushed the laptop to 800 users. It answered so slowly that its status said
   "unhealthy", and the phone took cell B over 120 s later, with the laptop **still running**.
4. **11:07.** Both cells said HOLDING. Each standby's writes since its takeover were compared with the
   real cell's: only scheduled goals, made in both. Both standbys were stopped, their copies dropped,
   and replication set up again.

**Root cause.** cellwatch treated "the other cell's status is stale or unhealthy" as "the other cell is
gone". Neither a dead watcher nor an overloaded cell means that the cell has stopped writing, and only
a cell that has stopped writing is safe to take over.

**What changed.**

- **A cell is lost only when its public address doesn't answer at all for 120 s.** By then it can't
  reach its own address either, so it has fenced itself (after 60 s). A cell that answers but is sick
  counts as lost only after 10 minutes, and it fences itself after 5.
- The other cell's front door (`/api/marketdata/v1/market`) is checked as well as its status: a cell
  whose services answer is never taken over because its watcher is silent.
- `failback.sh` stops cellwatch before clearing its state (a running one wrote it back), and its `pkill`
  pattern can't match itself.
- The same mistake was found a third time an hour later, in the phone's starter. At 500 users the edge host
  answered its health check too slowly for two minutes, so the starter killed it. It took 126 s to start
  again, and the overload became an outage of 502s. Now a piece that doesn't answer is killed only if it
  has also used under 5 s of CPU in those two minutes: a hung process (2026-10-08) uses none, and a busy
  one uses a lot.

**Lesson.** A failure detector has to tell "gone" from "slow". Taking over something that's slow causes a
bigger outage than the slowness did. Taking over safely needs proof that the other side has stopped,
not just that it has gone quiet. This is the singleton lesson from 2026-09 again: two copies of a
scheduler are worse than none.

## 2026-10-09: a cell that was taken over came back and went on serving, for ten hours

**Impact.** For about ten hours, cell A (the phone) ran on its own database while the laptop also ran it, on the promoted
copy. No customer was affected: nobody signed in or signed up in that time. Both copies went on running their own
schedulers and demo bots, so each booked its own system-generated orders (the 299 on the phone's copy were 137 goal
round-up sweeps, 132 demo-bot orders and 30 plan purchases; the laptop's copy had 302 and 147 mandate debits, the
phone's 147) and the two databases drifted apart.

**Timeline (UTC).**

1. **2026-10-09 16:55.** The phone's public address stops answering (the tunnel's connection dropped). The phone fences
   itself at 16:56:54, after 60 s, as designed.
2. **16:57:50.** The laptop counts the phone as lost (silent for 2 minutes) and starts taking cell A over.
3. **16:57:59.** The phone's address answers again. The phone sees that the laptop is *not yet* holding it (the laptop needs
   about 40 more seconds to promote its copy), so it **unfences itself** and goes back to NORMAL.
4. **16:58:27.** The laptop is HOLDING cell A. The phone never looks at that again: a cell in NORMAL only ever checks
   itself. Both cells now take writes for cell A's customers, whichever one a request reaches.
5. **2026-10-10 03:20.** The tunnel drops again; the phone fences, and this time sees that the laptop holds it. That
   ended the split. It was found at 14:52, when a new test found the phone in TAKEN_OVER.
6. **Repair.** Failback: the laptop's copy became the phone's database, and the phone's own was archived (not merged).
   The 299 orders on it are scheduled and demo-bot work.

**Root cause.** Two rules about a returning cell were each reasonable alone. It unfenced as soon as its address answered and
the other cell was not yet holding it, and it only looked for being held while it was fenced. Together they leave a gap
of the length of a takeover (a minute) in which the returning cell concludes that nothing happened.

**What changed.**

- A cell in **any** state that sees the other cell holding its customers fences itself and becomes TAKEN_OVER.
- A fenced cell unfences only after staying healthy for **210 s** (the 120 s the other cell waits to decide, plus 90 s to
  promote), and never while the other cell holds it.
- [CHAOS-17](testing/chaos.md#chaos-17) reproduces it on purpose: the returning cell now stays out.

**Lesson.** A cell that was replaced must find out that it was replaced. After losing contact, the only safe default is to
stay out of service until the other side says it is fine, not until the lost side thinks it is.

## 2026-10-10: one failed restart stopped all of Sprout on the phone for ten minutes

**Impact.** Found by a test (CHAOS-17), not by a customer. With the phone's web server frozen, the starter killed it, could
not start it again, and stopped every piece of Sprout on the phone, waiting ten minutes before starting them one by one. The cell
was down for about twelve minutes. The laptop was already holding its customers by then.

**Cause.** The starter's liveness check killed the hung nginx's master and its direct children. nginx's workers are children
of the master, so they were orphaned and kept running, holding port 8180. The new nginx could not bind it, `run.sh` exited,
and the starter's rule for a Sprout piece that will not restart is to give up on everything and try again later, so that a
crash loop cannot reboot the phone in a loop (2026-10-08).

**What changed.** The starter kills a hung piece's whole process tree, deepest first, and waits two seconds for the kernel
to free its ports. A failed restart gets one more try after 15 s before it gives up. With that, the same freeze ended in a
restart of the web server in two seconds.

**Lesson.** A rule that is safe for a crash loop (give up, wait) is wrong for the first failure; the second attempt costs nothing.
Killing a process is not the same as freeing what it held.
