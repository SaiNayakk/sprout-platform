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
