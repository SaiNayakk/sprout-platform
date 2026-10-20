/**
 * Automated tests for deploy/witness/src/worker.js
 *
 * Runner:  node --test test/   (Node 22 built-in test runner, ES modules)
 * No npm dependencies.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import workerDefault, { Witness } from '../src/worker.js';

// ── Fake clock ────────────────────────────────────────────────────────────────
//
// worker.js defines:  const now = () => Math.floor(Date.now() / 1000)
//
// Because `now` is a closure that reads Date.now at *call* time (not at
// definition time), replacing Date.now here is picked up by every subsequent
// call to now() inside the module.

let _fakeNow = 100_000; // seconds
Date.now = () => _fakeNow * 1000;
function setTime(s) { _fakeNow = s; }

// ── In-memory Durable Object storage ─────────────────────────────────────────
//
// Deep-cloning on get/put prevents the stored snapshot from being mutated by
// later in-memory changes (mirrors real DO storage semantics).

function makeStorage() {
  const map = new Map();
  return {
    async get(key) {
      return map.has(key) ? structuredClone(map.get(key)) : undefined;
    },
    async put(key, val) {
      map.set(key, structuredClone(val));
    },
  };
}

// ── Witness factory ───────────────────────────────────────────────────────────

function makeWitness(storage, envOverrides = {}) {
  const ctx = { storage };
  const env = { NTFY_TOPIC: 'test-topic', CELL_KEY: 'secret', ...envOverrides };
  return new Witness(ctx, env);
}

// ── Pre-built state: both cells last beat at beatAt ───────────────────────────

function silentBothState(beatAt) {
  return {
    beats: {
      a: { at: beatAt, state: 'NORMAL', healthy: true, holding: null, declared_down: false },
      b: { at: beatAt, state: 'NORMAL', healthy: true, holding: null, declared_down: false },
    },
    holder: {},
    epoch: 0,
    events: [],
    alert: {},
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Test 1 – beat stores cell state; peer view
// ─────────────────────────────────────────────────────────────────────────────
test('1. beat stores cell state; peer is {seen:false} before first beat then shows state and age after', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // ── First beat by 'a' – 'b' has never beaten ──
  let s = await w.load();
  const r1 = await w.beat(s, 'a', { state: 'NORMAL', healthy: true });

  assert.strictEqual(r1.ok, true, 'beat must return ok: true');
  assert.deepStrictEqual(r1.peer, { seen: false },
    'peer must be {seen:false} before b has ever beaten');

  // ── Verify the beat is persisted ──
  const stored = await storage.get('s');
  assert.ok(stored.beats.a, 'beat record for a must be saved to storage');
  assert.strictEqual(stored.beats.a.state, 'NORMAL');
  assert.strictEqual(stored.beats.a.at, 100_000);
  assert.strictEqual(stored.beats.a.healthy, true);

  // ── 'b' beats 5 s later ──
  setTime(100_005);
  s = await w.load();
  await w.beat(s, 'b', { state: 'NORMAL', healthy: true });

  // ── 'a' beats again 3 s after b ──
  setTime(100_008);
  s = await w.load();
  const r3 = await w.beat(s, 'a', { state: 'NORMAL', healthy: true });

  assert.strictEqual(r3.peer.seen, true, 'peer.seen must be true after b has beaten');
  assert.strictEqual(r3.peer.state, 'NORMAL');
  assert.strictEqual(r3.peer.healthy, true);
  assert.strictEqual(r3.peer.age, 3,
    'peer.age must equal now() − b.at = 100_008 − 100_005 = 3');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 2 – beat events: joined / state-change / is back
// ─────────────────────────────────────────────────────────────────────────────
test('2. beat events: first beat logs "joined"; state change logs an event; 30+ s silence logs "is back"', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // ── First beat → "joined" event ──
  let s = await w.load();
  await w.beat(s, 'a', { state: 'NORMAL', healthy: true });

  s = await w.load();
  assert.ok(
    s.events.some(e => e.text.includes('Region A') && e.text.includes('joined')),
    '"joined" event must be logged on a cell\'s very first beat',
  );

  // ── State change NORMAL → FENCED → describe() produces "stopped taking writes" ──
  //    Line 83: case 'FENCED': return `${n} stopped taking writes`
  setTime(100_005);
  s = await w.load();
  await w.beat(s, 'a', { state: 'FENCED', healthy: false });

  s = await w.load();
  assert.ok(
    s.events.some(e => e.text === 'Region A stopped taking writes'),
    'NORMAL → FENCED state change must log the describe() text',
  );

  // ── Beat after exactly 30 s of silence → "is back" ──
  //    prev.at = 100_005; next beat at 100_035; 100_035 − 100_005 = 30 ≥ LEASE(30)
  //    Line 63: else if (now() - prev.at >= LEASE)
  setTime(100_035);
  s = await w.load();
  await w.beat(s, 'a', { state: 'FENCED', healthy: false }); // same state → no state-change event

  s = await w.load();
  assert.ok(
    s.events.some(e => e.text.includes('Region A') && e.text.includes('is back')),
    '"is back" event must be logged when silence ≥ LEASE seconds',
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 3 – takeover denied while other cell's lease is live
// ─────────────────────────────────────────────────────────────────────────────
test('3. takeover is denied while other cell lease is live (last beat < 30 s ago)', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // 'b' beats at T = 100_000
  let s = await w.load();
  await w.beat(s, 'b', { state: 'NORMAL', healthy: true });

  // 29 s later: age = 29 < LEASE = 30  →  lapsed = false
  setTime(100_029);
  s = await w.load();
  const r = await w.takeover(s, 'a');

  assert.strictEqual(r.granted, false, 'takeover must be denied while lease is live');
  assert.ok(
    r.reason.includes('lease is live'),
    `reason must mention "lease is live", got: "${r.reason}"`,
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 4 – takeover granted after 90+ s of silence (not 30: a mobile blip is not a death); epoch increases;
//          repeat by same cell answers granted with reason "already granted"
// ─────────────────────────────────────────────────────────────────────────────
test('4. takeover granted only after 90 s of silence (denied at 89 s); epoch increases; repeat returns "already granted"', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // 'b' beats at T = 100_000
  let s = await w.load();
  await w.beat(s, 'b', { state: 'NORMAL', healthy: true });

  // 89 s later the cell is shown as not responding (30 s) but may not be taken over yet
  setTime(100_089);
  s = await w.load();
  const early = await w.takeover(s, 'a');
  assert.strictEqual(early.granted, false, 'a blip of 89 s must not be taken over');

  // 90 s later: age = 90 ≥ GRANT_AFTER = 90  →  lapsed = true
  setTime(100_090);
  s = await w.load();
  const r1 = await w.takeover(s, 'a');

  assert.strictEqual(r1.granted, true, 'takeover must be granted after lease lapses');
  assert.strictEqual(r1.reason, 'its lease lapsed');
  assert.strictEqual(r1.epoch, 1, 'epoch must increase from 0 to 1 on first grant');

  // ── Repeat by the same cell ──
  s = await w.load();
  const r2 = await w.takeover(s, 'a');

  assert.strictEqual(r2.granted, true, 'repeat request must be granted');
  assert.strictEqual(r2.reason, 'already granted');
  assert.strictEqual(r2.epoch, 1, 'epoch must NOT increase on repeat – already granted');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 5 – takeover granted when other cell declared_down, even with live lease
// ─────────────────────────────────────────────────────────────────────────────
test('5. takeover granted when other cell declared_down even though its lease is still live', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // 'b' beats with declared_down: true at T = 100_000
  let s = await w.load();
  await w.beat(s, 'b', { state: 'NORMAL', healthy: false, declared_down: true });

  // 10 s later: age = 10 < LEASE = 30  →  lease still live, but declared_down is true
  // Line 101: declared = v.seen && v.declared_down && v.age < LEASE  →  true
  setTime(100_010);
  s = await w.load();
  const r = await w.takeover(s, 'a');

  assert.strictEqual(r.granted, true, 'takeover must be granted when target declared_down');
  assert.strictEqual(r.reason, 'it declared itself out');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 6 – takeover denied when other cell has never been seen
// ─────────────────────────────────────────────────────────────────────────────
test('6. takeover is denied when the other cell has never been seen', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // 'b' has never beaten  →  view returns {seen:false}  →  lapsed=false, declared=false
  const s = await w.load();
  const r = await w.takeover(s, 'a');

  assert.strictEqual(r.granted, false, 'takeover must be denied for an unseen peer');
  assert.ok(
    r.reason.includes('never been seen'),
    `reason must mention "never been seen", got: "${r.reason}"`,
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 7 – a second entity cannot take over a target already held by the first
// ─────────────────────────────────────────────────────────────────────────────
test('7. a second cell cannot take over a target that the first already holds', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // In a strict two-cell system the guard on line 96
  //   if (s.holder[target] && s.holder[target] !== cell)
  // cannot be reached via the normal API, because target = other(cell) and
  // every naturally-reachable holder value is either the requesting cell
  // itself (→ "already granted") or undefined.  We inject the state directly
  // to exercise the guard, setting s.holder['b'] = 'b' (b "holds itself"):
  //   cell = 'a', target = other('a') = 'b'
  //   s.holder['b'] = 'b'  ≠  'a'  →  denied
  const injected = {
    beats: {
      b: { at: 100_000 - 35, state: 'NORMAL', healthy: true, holding: null, declared_down: false },
    },
    holder: { b: 'b' }, // some other entity already holds 'b'
    epoch: 1,
    events: [],
    alert: {},
  };
  await storage.put('s', injected);

  const s = await w.load();
  const r = await w.takeover(s, 'a'); // 'a' tries to take over 'b'

  assert.strictEqual(r.granted, false, 'takeover must be denied when another entity already holds the target');
  assert.ok(
    r.reason.includes('already holds it'),
    `reason must mention "already holds it", got: "${r.reason}"`,
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 8 – release by holder clears it and bumps epoch; non-holder changes nothing
// ─────────────────────────────────────────────────────────────────────────────
test('8. release by holder clears it and bumps epoch; release by non-holder changes nothing', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // Establish: 'b' beats, its lease lapses, 'a' takes over 'b'
  // After takeover: s.holder['b'] = 'a', epoch = 1
  let s = await w.load();
  await w.beat(s, 'b', { state: 'NORMAL', healthy: true });
  setTime(100_090);
  s = await w.load();
  await w.takeover(s, 'a');

  // ── Non-holder ('b') tries to release 'a's customers ──
  //    release(s, 'b'): target = other('b') = 'a'; s.holder['a'] is unset → no match
  s = await w.load();
  const epochBefore = s.epoch; // 1
  const rNon = await w.release(s, 'b');

  assert.strictEqual(rNon.ok, true);
  assert.strictEqual(rNon.epoch, epochBefore,
    'epoch must not change when non-holder calls release');
  let snap = await storage.get('s');
  assert.strictEqual(snap.holder.b, 'a',
    'holder must not be cleared by a non-holder release');

  // ── Holder ('a') releases 'b's customers ──
  //    release(s, 'a'): target = other('a') = 'b'; s.holder['b'] === 'a'  ✓
  s = await w.load();
  const rHold = await w.release(s, 'a');

  assert.strictEqual(rHold.ok, true);
  assert.strictEqual(rHold.epoch, epochBefore + 1,
    'epoch must bump when the holder releases');
  snap = await storage.get('s');
  assert.strictEqual(snap.holder.b, undefined,
    'holder must be cleared after a valid release');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 9 – stale holder cleared on NORMAL+healthy beat; fresh active holder kept
// ─────────────────────────────────────────────────────────────────────────────
test('9. NORMAL+healthy beat clears a stale holder; a fresh TAKING_OVER or HOLDING holder is kept', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  const T = 100_000;
  setTime(T);

  // ── Scenario A: holder 'b' is stale (age = 35 ≥ LEASE = 30) → holder cleared ──
  //    Line 71: active = hv.seen && hv.age < LEASE && (TAKING_OVER || HOLDING)
  //             age 35 < 30 is false → active = false → delete s.holder['a'], epoch++
  await storage.put('s', {
    beats: {
      a: { at: T - 5,  state: 'TAKEN_OVER', healthy: false, holding: null, declared_down: false },
      b: { at: T - 35, state: 'TAKING_OVER', healthy: true,  holding: null, declared_down: false },
    },
    holder: { a: 'b' }, // 'b' is recorded as holding 'a'
    epoch: 1,
    events: [],
    alert: {},
  });

  let s = await w.load();
  await w.beat(s, 'a', { state: 'NORMAL', healthy: true });

  let snap = await storage.get('s');
  assert.strictEqual(snap.holder.a, undefined,
    'stale holder must be cleared when cell beats NORMAL+healthy');
  assert.strictEqual(snap.epoch, 2,
    'epoch must increase when stale holder is cleared');

  // ── Scenario B: holder 'b' is fresh (age = 5 < LEASE) and TAKING_OVER → kept ──
  //    active = true → holder is NOT cleared
  await storage.put('s', {
    beats: {
      a: { at: T - 5, state: 'TAKEN_OVER', healthy: false, holding: null, declared_down: false },
      b: { at: T - 5, state: 'TAKING_OVER', healthy: true,  holding: null, declared_down: false },
    },
    holder: { a: 'b' },
    epoch: 2,
    events: [],
    alert: {},
  });

  s = await w.load();
  await w.beat(s, 'a', { state: 'NORMAL', healthy: true });

  snap = await storage.get('s');
  assert.strictEqual(snap.holder.a, 'b',
    'fresh TAKING_OVER holder must NOT be cleared');
  assert.strictEqual(snap.epoch, 2,
    'epoch must not change when an active holder is kept');

  // ── Scenario C: holder 'b' is fresh and HOLDING → kept ──
  await storage.put('s', {
    beats: {
      a: { at: T - 5, state: 'TAKEN_OVER', healthy: false, holding: null, declared_down: false },
      b: { at: T - 5, state: 'HOLDING',    healthy: true,  holding: null, declared_down: false },
    },
    holder: { a: 'b' },
    epoch: 2,
    events: [],
    alert: {},
  });

  s = await w.load();
  await w.beat(s, 'a', { state: 'NORMAL', healthy: true });

  snap = await storage.get('s');
  assert.strictEqual(snap.holder.a, 'b',
    'fresh HOLDING holder must NOT be cleared');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 10 – publicStatus: all scenarios + exact top-level key set
// ─────────────────────────────────────────────────────────────────────────────
test('10. publicStatus: both up / one down / held-by-peer / never-seen / exact key set with no internal fields', () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  const T = 100_000;
  setTime(T);

  // Helper: minimal beat record
  function beat(at, state = 'NORMAL', healthy = true, declared_down = false) {
    return { at, state, healthy, holding: null, declared_down };
  }

  // ── Both regions up ──
  let ps = w.publicStatus({
    beats: { a: beat(T - 5), b: beat(T - 3) },
    holder: {}, epoch: 0, events: [], alert: {},
  });
  assert.strictEqual(ps.overall, 'up');
  assert.strictEqual(ps.customers_served, true);
  assert.strictEqual(ps.summary, 'All systems normal');
  assert.ok(ps.regions.every(r => r.status === 'up'),
    'both regions must report status "up"');

  // ── Region A silent for 31 s → that region "down", overall "down", customers_served false ──
  //    age = 31 ≥ LEASE = 30  →  line 132: status = 'down'
  ps = w.publicStatus({
    beats: { a: beat(T - 31), b: beat(T - 5) },
    holder: {}, epoch: 0, events: [], alert: {},
  });
  const rA_down = ps.regions.find(r => r.id === 'a');
  assert.strictEqual(rA_down.status, 'down',
    'region silent 31 s must report "down"');
  assert.strictEqual(ps.overall, 'down');
  assert.strictEqual(ps.customers_served, false,
    'customers_served must be false when a region is down without a holder');

  // ── Region A held by fresh Region B → status "degraded", detail starts with "served by Region B", customers_served true ──
  //    'b' must be 'up' (NORMAL + healthy + no holder + fresh) for customers_served to be true,
  //    so that regions.every(r => r.status === 'up' || (degraded + 'served by')) holds.
  ps = w.publicStatus({
    beats: {
      a: beat(T - 35, 'FENCED', false), // 'a' silent/down, has a holder
      b: beat(T - 5,  'NORMAL', true),  // 'b' fresh and serving normally
    },
    holder: { a: 'b' },
    epoch: 1, events: [], alert: {},
  });
  const rA_held = ps.regions.find(r => r.id === 'a');
  assert.strictEqual(rA_held.status, 'degraded',
    'held region must report "degraded"');
  assert.ok(
    rA_held.detail.startsWith('served by Region B'),
    `detail must start with "served by Region B", got: "${rA_held.detail}"`,
  );
  assert.strictEqual(ps.customers_served, true,
    'customers_served must be true when the held region is covered by a fresh holder');

  // ── Region B never seen → status "unknown" ──
  ps = w.publicStatus({
    beats: { a: beat(T - 5) }, // only 'a' has ever beaten
    holder: {}, epoch: 0, events: [], alert: {},
  });
  const rB_unseen = ps.regions.find(r => r.id === 'b');
  assert.strictEqual(rB_unseen.status, 'unknown',
    'never-seen region must report "unknown"');

  // ── Exact top-level key set – no address, key, or internal field exposed ──
  const EXPECTED_KEYS = new Set(['overall', 'customers_served', 'summary', 'regions', 'events', 'updated']);
  ps = w.publicStatus({
    beats: { a: beat(T - 5), b: beat(T - 3) },
    holder: {}, epoch: 0, events: [], alert: {},
  });
  assert.deepStrictEqual(
    new Set(Object.keys(ps)),
    EXPECTED_KEYS,
    'publicStatus must expose exactly the six documented top-level keys',
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 11 – cron: ntfy alert, 30-min deduplication, recovery, no-topic guard
// ─────────────────────────────────────────────────────────────────────────────
test('11. cron sends ntfy when both silent 180+ s; no repeat within 30 min; repeats after; recovery once; silent without NTFY_TOPIC', async () => {
  const origFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url: String(url), opts });
    return new Response('ok', { status: 200 });
  };

  try {
    // ── 11a: first alert when both cells have been silent 181 s ──
    {
      const T = 200_000;
      setTime(T);
      const st = makeStorage();
      const w = makeWitness(st);
      await st.put('s', silentBothState(T - 181));

      let s = await w.load();
      await w.cron(s);

      assert.strictEqual(calls.length, 1,
        '11a: exactly one ntfy call when both cells are silent 181 s');
      assert.ok(
        calls[0].url.endsWith('/test-topic'),
        `11a: URL must end with the NTFY_TOPIC, got: "${calls[0].url}"`,
      );
      assert.ok(
        calls[0].opts.headers.Title.includes('Sprout'),
        `11a: Title header must be set and include "Sprout", got: "${calls[0].opts.headers.Title}"`,
      );
    }

    // ── 11b: no repeat within REALERT = 1800 s ──
    {
      // Re-use the same cron witness: the storage already has alert.at = T and alert.open = true.
      // We create a fresh one that shares the same state to keep the sub-test self-contained.
      const T = 200_000;
      setTime(T);
      const st = makeStorage();
      const w = makeWitness(st);
      await st.put('s', silentBothState(T - 181));

      let s = await w.load();
      await w.cron(s);              // fires (call #2)
      assert.strictEqual(calls.length, 2, '11b: first call in this block fires');

      s = await w.load();
      await w.cron(s);              // immediate repeat → must NOT fire
      assert.strictEqual(calls.length, 2,
        '11b: no duplicate ntfy within 30 minutes');

      // ── 11c: repeats after REALERT seconds ──
      setTime(T + 1800);
      s = await w.load();
      await w.cron(s);
      assert.strictEqual(calls.length, 3,
        '11c: second alert must fire after REALERT = 1800 s');
    }

    // ── 11d: recovery message when one cell is back ──
    {
      const T2 = 300_000;
      setTime(T2);
      const st2 = makeStorage();
      const w2 = makeWitness(st2);
      // alert is open (previous alert was sent); cell 'a' just reported back
      await st2.put('s', {
        beats: {
          a: { at: T2 - 5,   state: 'NORMAL', healthy: true,  holding: null, declared_down: false },
          b: { at: T2 - 181, state: 'NORMAL', healthy: true,  holding: null, declared_down: false },
        },
        holder: {}, epoch: 0, events: [],
        alert: { at: T2 - 60, open: true },
      });

      let s2 = await w2.load();
      await w2.cron(s2);
      assert.strictEqual(calls.length, 4,
        '11d: recovery message must be sent when a cell comes back');
      assert.ok(
        calls[3].opts.headers.Title.includes('reporting again'),
        `11d: recovery Title must include "reporting again", got: "${calls[3].opts.headers.Title}"`,
      );

      // no second recovery on the very next cron tick
      s2 = await w2.load();
      await w2.cron(s2);
      assert.strictEqual(calls.length, 4,
        '11d: recovery message must not be duplicated');
    }

    // ── 11e: no NTFY_TOPIC → nothing is sent ──
    {
      const T3 = 400_000;
      setTime(T3);
      const st3 = makeStorage();
      const w3 = makeWitness(st3, { NTFY_TOPIC: undefined });
      await st3.put('s', silentBothState(T3 - 181));
      const s3 = await w3.load();
      await w3.cron(s3);
      assert.strictEqual(calls.length, 4,
        '11e: no ntfy call must be made when env.NTFY_TOPIC is absent');
    }
  } finally {
    globalThis.fetch = origFetch;
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 12 – default export fetch handler: auth / CORS / OPTIONS / 404
// ─────────────────────────────────────────────────────────────────────────────
test('12. default export: 403 without key / wrong key / missing CELL_KEY; GET /status needs no key and has CORS; OPTIONS is 204; unknown path is 404', async () => {
  const storage = makeStorage();
  const w = makeWitness(storage);
  setTime(100_000);

  // Pre-seed state so GET /status returns a real response
  await storage.put('s', {
    beats: {
      a: { at: 99_995, state: 'NORMAL', healthy: true, holding: null, declared_down: false },
      b: { at: 99_997, state: 'NORMAL', healthy: true, holding: null, declared_down: false },
    },
    holder: {}, epoch: 0, events: [], alert: {},
  });

  // Build a fake Cloudflare env that wires the Durable Object stub to our Witness.
  // Overrides are spread after the defaults so individual keys can be replaced.
  function makeEnv(overrides = {}) {
    const stub = { fetch: (req) => w.fetch(req) };
    return {
      CELL_KEY: 'test-key',
      NTFY_TOPIC: 'test-topic',
      WITNESS: { idFromName: () => 'main', get: () => stub },
      ...overrides,
    };
  }

  const BASE = 'https://witness.example.com';
  const h = workerDefault;

  // ── POST /v1/beat with no x-cell-key header → 403 ──
  {
    const res = await h.fetch(
      new Request(`${BASE}/v1/beat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ cell: 'a' }),
      }),
      makeEnv(),
    );
    assert.strictEqual(res.status, 403, 'missing x-cell-key header must return 403');
  }

  // ── POST /v1/beat with wrong x-cell-key → 403 ──
  {
    const res = await h.fetch(
      new Request(`${BASE}/v1/beat`, {
        method: 'POST',
        headers: { 'x-cell-key': 'wrong-key', 'content-type': 'application/json' },
        body: JSON.stringify({ cell: 'a' }),
      }),
      makeEnv(),
    );
    assert.strictEqual(res.status, 403, 'wrong x-cell-key must return 403');
  }

  // ── POST /v1/beat with correct header but env.CELL_KEY absent → 403 ──
  //    Line 177: !env.CELL_KEY → true when CELL_KEY is falsy (undefined / empty string)
  {
    const res = await h.fetch(
      new Request(`${BASE}/v1/beat`, {
        method: 'POST',
        headers: { 'x-cell-key': 'test-key', 'content-type': 'application/json' },
        body: JSON.stringify({ cell: 'a', state: 'NORMAL', healthy: true }),
      }),
      makeEnv({ CELL_KEY: undefined }),
    );
    assert.strictEqual(res.status, 403,
      'absent env.CELL_KEY must return 403 even when the header matches');
  }

  // ── OPTIONS → 204 (no key required) ──
  {
    const res = await h.fetch(
      new Request(`${BASE}/v1/beat`, { method: 'OPTIONS' }),
      makeEnv(),
    );
    assert.strictEqual(res.status, 204, 'OPTIONS must return 204');
  }

  // ── GET /status → 200 with access-control-allow-origin: * (no key required) ──
  {
    const res = await h.fetch(
      new Request(`${BASE}/status`, { method: 'GET' }),
      makeEnv(),
    );
    assert.strictEqual(res.status, 200, 'GET /status must return 200');
    assert.strictEqual(
      res.headers.get('access-control-allow-origin'), '*',
      '/status response must carry access-control-allow-origin: *',
    );
  }

  // ── Unknown path → 404 ──
  {
    const res = await h.fetch(
      new Request(`${BASE}/no-such-path`, { method: 'GET' }),
      makeEnv(),
    );
    assert.strictEqual(res.status, 404, 'unknown path must return 404');
  }
});
