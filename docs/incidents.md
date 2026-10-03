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

## 2026-10: a release tagged on a failing commit

**Impact.** None in production. `sprout-identity v0.2.0` was tagged while its CI was failing, because
the release commands were chained so that a failure didn't stop the next step.

**What changed.** The tag was withdrawn and `v0.2.1` released from a green commit. Release steps are
chained so any failure stops everything after it. `v0.2.0` must never be used.
