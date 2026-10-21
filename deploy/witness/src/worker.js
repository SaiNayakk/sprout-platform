// The witness for Sprout's two cells (ADR-027): a third party that neither cell controls.
//
//   POST /v1/beat      a cell says it is alive, and in what state (every 10 s). The answer says how the other cell looks from here.
//   POST /v1/takeover  a cell asks for the right to take the other over; granted only if the other's lease has lapsed.
//   POST /v1/release   the holder says it has given the customers back.
//   GET  /status       the public view: both regions, who serves them, recent events (no addresses, no keys).
//   cron, every minute: if both cells have been silent for 3 minutes, push an alert to the owner's phone (the dead-man's switch).
//
// A cell's lease is its last beat: it lapses after LEASE seconds of silence. Cells fail open: if this Worker cannot be reached,
// they behave as they did before it existed, so it can only ever add a veto, never block a failover by being down.

const LEASE = 30;            // seconds of silence after which a cell is shown as not responding
const GRANT_AFTER = 90;      // seconds of silence after which another cell may take it over: a phone on mobile data drops off for
                             // 30 to 60 s now and then, and a takeover costs minutes of failback (2026-10-20: a 40 s blip did)
const SILENT_ALERT = 180;    // both cells silent this long: alert
const REALERT = 1800;
const EVENTS_KEEP = 40;
const CELLS = ['a', 'b'];
const NAMES = { a: 'Region A', b: 'Region B' };
const now = () => Math.floor(Date.now() / 1000);
const json = (o, status = 200, extra = {}) =>
  new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...extra } });
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, OPTIONS', 'access-control-allow-headers': 'content-type' };

function other(c) { return c === 'a' ? 'b' : 'a'; }

export class Witness {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; }

  async load() {
    return (await this.ctx.storage.get('s')) || { beats: {}, holder: {}, epoch: 0, events: [], alert: {} };
  }

  async save(s) { await this.ctx.storage.put('s', s); }

  event(s, text) {
    s.events.unshift({ at: now(), text });
    s.events.length = Math.min(s.events.length, EVENTS_KEEP);
  }

  async fetch(req) {
    const url = new URL(req.url);
    const s = await this.load();
    if (url.pathname === '/status') return json(this.publicStatus(s), 200, CORS);
    if (url.pathname === '/cron') { await this.cron(s); return json({ ok: true }); }
    const body = await req.json().catch(() => ({}));
    const cell = body.cell;
    if (!CELLS.includes(cell)) return json({ error: 'cell' }, 400);
    if (url.pathname === '/v1/beat') return json(await this.beat(s, cell, body));
    if (url.pathname === '/v1/takeover') return json(await this.takeover(s, cell));
    if (url.pathname === '/v1/release') return json(await this.release(s, cell));
    return json({ error: 'not found' }, 404);
  }

  view(s, c) {
    const b = s.beats[c];
    if (!b) return { seen: false };
    return { seen: true, age: now() - b.at, state: b.state, healthy: b.healthy, holding: b.holding || null, declared_down: !!b.declared_down };
  }

  async beat(s, cell, body) {
    const prev = s.beats[cell];
    const st = { at: now(), state: String(body.state || ''), healthy: !!body.healthy, holding: body.holding || null, declared_down: !!body.declared_down };
    if (!prev) this.event(s, `${NAMES[cell]} joined`);
    else if (now() - prev.at >= LEASE) this.event(s, `${NAMES[cell]} is back`);
    if (prev && prev.state !== st.state) this.event(s, this.describe(cell, prev.state, st.state));
    if (prev && !prev.declared_down && st.declared_down) this.event(s, `${NAMES[cell]} stopped taking writes: one of its hosts is down`);
    s.beats[cell] = st;
    // a cell that is serving its own customers again, with nobody actively serving them for it (the holder is gone, or gave them back)
    const h = s.holder[cell];
    if (h && st.state === 'NORMAL' && st.healthy) {
      const hv = this.view(s, h);
      const active = hv.seen && hv.age < LEASE && (hv.state === 'TAKING_OVER' || hv.state === 'HOLDING');
      if (!active) { delete s.holder[cell]; s.epoch += 1; }
    }
    // a cell that beats while the other holds its customers is told so: it must not serve them
    const taken_by = s.holder[cell] || null;
    await this.save(s);
    return { ok: true, now: now(), lease: LEASE, taken_by, epoch: s.epoch, peer: this.view(s, other(cell)) };
  }

  describe(cell, from, to) {
    const n = NAMES[cell];
    switch (to) {
      case 'FENCED': return `${n} stopped taking writes`;
      case 'NORMAL': return from === 'FAILING_BACK' ? `${n} is serving its own customers again` : `${n} is serving normally`;
      case 'TAKING_OVER': return `${n} started taking over ${NAMES[other(cell)]}`;
      case 'HOLDING': return `${n} is serving ${NAMES[other(cell)]}'s customers`;
      case 'TAKEN_OVER': return `${NAMES[other(cell)]} is serving ${n}'s customers`;
      case 'FAILING_BACK': return `${n} is taking its customers back`;
      default: return `${n}: ${from || '-'} -> ${to}`;
    }
  }

  async takeover(s, cell) {
    const target = other(cell);
    const v = this.view(s, target);
    if (s.holder[target] && s.holder[target] !== cell) {
      return { granted: false, reason: `${s.holder[target]} already holds it`, epoch: s.epoch };
    }
    if (s.holder[target] === cell) return { granted: true, reason: 'already granted', epoch: s.epoch };
    const lapsed = v.seen && v.age >= GRANT_AFTER;
    const declared = v.seen && v.declared_down && v.age < GRANT_AFTER;     // it says itself it takes no writes
    if (!(lapsed || declared)) {
      return { granted: false, reason: v.seen ? `its lease is live (last beat ${v.age} s ago)` : 'it has never been seen', epoch: s.epoch };
    }
    s.holder[target] = cell;
    s.epoch += 1;
    this.event(s, `${NAMES[cell]} was granted the right to serve ${NAMES[target]}'s customers`);
    await this.save(s);
    return { granted: true, reason: lapsed ? 'its lease lapsed' : 'it declared itself out', epoch: s.epoch };
  }

  async release(s, cell) {
    const target = other(cell);
    if (s.holder[target] === cell) {
      delete s.holder[target];
      s.epoch += 1;
      this.event(s, `${NAMES[cell]} gave ${NAMES[target]}'s customers back`);
      await this.save(s);
    }
    return { ok: true, epoch: s.epoch };
  }

  publicStatus(s) {
    const regions = CELLS.map((c) => {
      const v = this.view(s, c);
      const holder = s.holder[c] || null;
      const hv = holder ? this.view(s, holder) : null;
      let status, detail;
      if (v.seen && v.age < LEASE && v.state === 'HOLDING' && v.healthy) { status = 'up'; detail = `serving normally, and serving ${NAMES[other(c)]}'s customers too`; }
      else if (v.seen && v.age < LEASE && v.state === 'NORMAL' && v.healthy && !holder) { status = 'up'; detail = 'serving normally'; }
      else if (holder && hv && hv.seen && hv.age < LEASE) { status = 'degraded'; detail = `served by ${NAMES[holder]}`; }
      else if (!v.seen) { status = 'unknown'; detail = 'not seen yet'; }
      else if (v.age >= LEASE) { status = 'down'; detail = 'not responding'; }
      else { status = 'degraded'; detail = 'not taking writes'; }
      return { id: c, name: NAMES[c], status, detail, last_seen_s: v.seen ? v.age : null };
    });
    const worst = regions.some((r) => r.status === 'down') ? 'down' : regions.some((r) => r.status !== 'up') ? 'degraded' : 'up';
    // customers are served as long as every region is up or served by the other: say so
    const served = regions.every((r) => r.status === 'up' || (r.status === 'degraded' && r.detail.startsWith('served by')));
    return {
      overall: worst, customers_served: served,
      summary: worst === 'up' ? 'All systems normal' : served ? 'A region is down; its customers are being served by the other' : 'Some customers cannot trade right now',
      regions, events: s.events.slice(0, 12), updated: now(),
    };
  }

  async cron(s) {
    const ages = CELLS.map((c) => { const v = this.view(s, c); return v.seen ? v.age : null; });
    const bothSilent = ages.every((a) => a !== null && a >= SILENT_ALERT);
    const al = s.alert;
    if (bothSilent && (!al.at || now() - al.at >= REALERT)) {
      await this.push('Sprout: both cells are silent', `Neither region has reported for ${Math.min(...ages)} s: the whole system may be down.`, 5, 'rotating_light');
      al.at = now(); al.open = true;
      this.event(s, 'Both regions are silent');
      await this.save(s);
    } else if (!bothSilent && al.open) {
      await this.push('Sprout: the cells are reporting again', 'At least one region is back.', 3, 'white_check_mark');
      al.open = false; al.at = 0;
      await this.save(s);
    }
  }

  async push(title, message, priority, tags) {
    if (!this.env.NTFY_TOPIC) return;
    await fetch(`https://ntfy.sh/${this.env.NTFY_TOPIC}`, {
      method: 'POST', body: message, headers: { Title: title, Priority: String(priority), Tags: tags },
    }).catch(() => {});
  }
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
    const stub = env.WITNESS.get(env.WITNESS.idFromName('main'));
    if (url.pathname === '/status' && req.method === 'GET') return stub.fetch(req);
    if (url.pathname.startsWith('/v1/') && req.method === 'POST') {
      if (!env.CELL_KEY || req.headers.get('x-cell-key') !== env.CELL_KEY) return json({ error: 'forbidden' }, 403);
      return stub.fetch(req);
    }
    return json({ error: 'not found' }, 404);
  },
  async scheduled(event, env, ctx) {
    const stub = env.WITNESS.get(env.WITNESS.idFromName('main'));
    ctx.waitUntil(stub.fetch('https://witness/cron'));
  },
};
