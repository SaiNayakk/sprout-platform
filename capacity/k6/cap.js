// Capacity: how much load a deployment takes before it bends, and where it breaks.
//
// Unlike the pre-prod gates (PERF-01..04), which hold a fixed load to a bar, this climbs in steps and records
// every step, so the knee (where latency starts climbing) and the breaking point (errors, or the host falling
// over) are both visible. Nothing aborts the run: a failed step is a result.
//
//   TEST=signin  sign-ins (bcrypt-bound: the costliest request there is)
//   TEST=browse  what a signed-in customer's screens ask for: market, funds, holdings, orders, pots, a quote
//   TEST=demo    visitors starting a demo account (the sandbox's pool is small: this finds that limit)
//   TEST=users   whole customers: each pauses 2-6 s between actions (THINK), as people do, and does what customers
//                do, in proportion: opens home, checks quotes, looks at orders, pots and plans, buys a share, pays
//                at a shop by UPI (which round-ups follow), now and then signs in again. STEPS are concurrent users.
//
//   STEPS=1,2,4,8   requests (or sign-ins, or demo starts) a second, one step after another
//   STEP_SECONDS=60
//   BASE_URL       where the web app is (it forwards /api to the gateway)
//   OUT            where the summary goes
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

// every response counted by status, so a step's errors say what they were (429 limited, 502/503/504 overloaded, 0 refused)
const responses = new Counter('responses');
const CODES = ['0', '200', '201', '400', '401', '404', '409', '422', '429', '500', '502', '503', '504'];

const TEST = __ENV.TEST || 'browse';
const BASE = (__ENV.BASE_URL || 'http://localhost:18180') + '/api';
const STEPS = (__ENV.STEPS || '5,10,20,40').split(',').map(Number);
const STEP_SECONDS = Number(__ENV.STEP_SECONDS || 60);
const USERS = Number(__ENV.USERS || 30);
const PASSWORD = 'capacity-mango-42';
const RUN = __ENV.RUN || String(Date.now());

// one scenario per step, back to back, so each step's numbers are its own
const scenarios = {};
const thresholds = {};
STEPS.forEach((rate, i) => {
  const name = `step_${String(i).padStart(2, '0')}_${rate}`;
  scenarios[name] = TEST === 'users' ? {
    executor: 'constant-vus',
    vus: rate,
    duration: `${STEP_SECONDS}s`,
    startTime: `${i * STEP_SECONDS}s`,
    gracefulStop: '10s',
  } : {
    executor: 'constant-arrival-rate',
    rate,
    timeUnit: '1s',
    duration: `${STEP_SECONDS}s`,
    startTime: `${i * STEP_SECONDS}s`,
    preAllocatedVUs: Math.min(400, Math.max(10, rate * 2)),
    maxVUs: Math.min(1500, Math.max(50, rate * 10)),
    gracefulStop: '5s',
  };
  // thresholds only so k6 reports each step's numbers (submetrics); they don't stop anything
  thresholds[`http_req_duration{scenario:${name}}`] = [{ threshold: 'p(95)<100000', abortOnFail: false }];
  thresholds[`http_req_failed{scenario:${name}}`] = [{ threshold: 'rate<=1', abortOnFail: false }];
  thresholds[`dropped_iterations{scenario:${name}}`] = [{ threshold: 'count>=0', abortOnFail: false }];
  thresholds[`checks{scenario:${name}}`] = [{ threshold: 'rate>=0', abortOnFail: false }];
  for (const code of CODES) thresholds[`responses{scenario:${name},code:${code}}`] = [{ threshold: 'count>=0', abortOnFail: false }];
  if (TEST === 'users') {
    for (const n of ['home', 'quotes', 'orders', 'pots', 'plans', 'buy', 'upi', 'signin']) {
      thresholds[`http_req_duration{scenario:${name},name:${n}}`] = [{ threshold: 'p(95)<100000', abortOnFail: false }];
    }
  }
});

export const options = {
  scenarios,
  thresholds,
  setupTimeout: '10m',
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false,
};

// a different client address per request, as real visitors would be, so per-client rate limits don't apply;
// the gateway trusts it only because nothing but the tunnel (here: the capacity run) reaches the web server
function ip() {
  return `198.18.${Math.floor(Math.random() * 256)}.${1 + Math.floor(Math.random() * 254)}`;
}

function headers(token) {
  const h = { 'Content-Type': 'application/json', 'CF-Connecting-IP': ip() };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

function counted(r) {
  responses.add(1, { code: String(r.status) });
  return r;
}

function post(path, body, token, name) {
  return counted(http.post(`${BASE}${path}`, JSON.stringify(body), { headers: headers(token), tags: { name } }));
}

function get(path, token, name) {
  return counted(http.get(`${BASE}${path}`, { headers: headers(token), tags: { name } }));
}

export function setup() {
  if (TEST === 'demo') return {};
  const emails = [];
  for (let i = 0; i < USERS; i++) {
    const email = `capacity-${RUN}-${i}@example.invalid`;
    const r = post('/identity/v1/users', { email, password: PASSWORD, displayName: `Capacity ${i}` }, null, 'setup');
    if (r.status === 201) emails.push(email);
  }
  if (emails.length < USERS * 0.9) throw new Error(`setup created only ${emails.length} of ${USERS} users`);
  if (TEST === 'signin') return { emails };
  // each becomes a customer the way anyone does: a bank account, a Sprout account (KYC), money added and approved
  // in the bank with the PIN, so every screen does the work it does for a real customer
  const tokens = [];
  emails.forEach((email, i) => {
    const r = post('/identity/v1/sessions', { email, password: PASSWORD }, null, 'setup');
    if (r.status !== 200) return;
    const t = r.json('tokens.accessToken');
    post('/bank/v1/accounts', { holderName: `Capacity ${i}`, upiPin: '2580' }, t, 'setup');
    const vpa = get('/bank/v1/accounts/me', t, 'setup').json('vpa');
    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const pan = `CAPP${letters[Math.floor(Math.random() * 26)]}${String(Math.floor(Math.random() * 10000)).padStart(4, '0')}Z`;
    post('/accounts/v1/accounts', { legalName: `Capacity ${i}`, dateOfBirth: '1995-06-15', pan, bankVpa: vpa }, t, 'setup');
    post('/payments/v1/deposits', { amount: '50000' }, t, 'setup');
    for (const req of get('/bank/v1/requests?status=PENDING', t, 'setup').json('requests') || []) {
      post(`/bank/v1/requests/${req.id}/approve`, { upiPin: '2580' }, t, 'setup');
    }
    if (get('/oms/v1/funds', t, 'setup').status === 200) tokens.push(t);
  });
  if (tokens.length < emails.length * 0.9) throw new Error(`only ${tokens.length} of ${emails.length} became customers`);
  const symbols = get('/marketdata/v1/instruments', tokens[0], 'setup').json('instruments').map((i) => i.symbol).filter((s) => s !== 'SPROUT20');
  return { tokens, emails: emails.slice(0, tokens.length), symbols };
}

const SCREENS = [
  (t) => get('/marketdata/v1/market', t, 'market'),
  (t) => get('/oms/v1/funds', t, 'funds'),
  (t) => get('/oms/v1/holdings', t, 'holdings'),
  (t) => get('/oms/v1/orders', t, 'orders'),
  (t) => get('/goals/v1/pots', t, 'pots'),
  (t, d) => get(`/marketdata/v1/quotes?symbols=${d.symbols.slice(0, 5).join(',')}`, t, 'quotes'),
];

const THINK_MIN = Number(__ENV.THINK_MIN || 2);
const THINK_MAX = Number(__ENV.THINK_MAX || 6);
const CHEAP = ['SUNROOT', 'BREWBERRY', 'THREADS', 'IRONLEAF', 'NIGHTOWL'];
const SHOPS = ['monsoonchai@sproutbank', 'tiffinbox@sproutbank', 'kiranacorner@sproutbank', 'citymetro@sproutbank', 'bookworm@sproutbank'];
let mine = null;   // this virtual user's customer: { email, token }

function key() {
  return `cap-${RUN}-${__VU}-${__ITER}-${Math.random().toString(36).slice(2, 10)}`;
}

// What a customer does, and how often (weights out of 100), from a model of one visit of about 5 minutes: sign in
// once, look at about 60 screens (home most, then prices, orders, the pot, plans), buy once or twice, pay at a
// shop once. Sign-in is the costliest request by far (bcrypt), so getting its share right matters most.
const ACTIONS = [
  [33, 'home', (t) => http.batch([
    ['GET', `${BASE}/marketdata/v1/market`, null, { headers: headers(t), tags: { name: 'home' } }],
    ['GET', `${BASE}/oms/v1/funds`, null, { headers: headers(t), tags: { name: 'home' } }],
    ['GET', `${BASE}/oms/v1/holdings`, null, { headers: headers(t), tags: { name: 'home' } }],
  ]).map(counted)],
  [25, 'quotes', (t, d) => [get(`/marketdata/v1/quotes?symbols=${d.symbols.slice(0, 6).join(',')}`, t, 'quotes')]],
  [13, 'orders', (t) => [get('/oms/v1/orders', t, 'orders')]],
  [11, 'pots', (t) => [get('/goals/v1/pots', t, 'pots')]],
  [11, 'plans', (t) => [get('/plans/v1/plans', t, 'plans')]],
  [3, 'buy', (t) => [counted(http.post(`${BASE}/oms/v1/orders`, JSON.stringify({ symbol: CHEAP[Math.floor(Math.random() * CHEAP.length)],
    side: 'BUY', quantity: 1, orderType: 'MARKET', product: 'CNC' }), { headers: Object.assign(headers(t), { 'Idempotency-Key': key() }), tags: { name: 'buy' } }))]],
  [2, 'upi', (t) => [post('/bank/v1/payments', { payeeVpa: SHOPS[Math.floor(Math.random() * SHOPS.length)],
    amount: `${35 + Math.floor(Math.random() * 300)}.00`, upiPin: '2580' }, t, 'upi')]],
  [2, 'signin', null],
];

function customer(data) {
  const r = post('/identity/v1/sessions', { email: mine.email, password: PASSWORD }, null, 'signin');
  if (r.status === 200) mine.token = r.json('tokens.accessToken');
  return [r];
}

function users(data) {
  if (mine === null) {
    const i = (__VU - 1) % data.tokens.length;
    mine = { email: data.emails[i], token: data.tokens[i] };
  }
  let roll = Math.random() * 100;
  let action = ACTIONS[ACTIONS.length - 1];
  for (const a of ACTIONS) {
    if (roll < a[0]) { action = a; break; }
    roll -= a[0];
  }
  let rs = action[1] === 'signin' ? customer(data) : action[2](mine.token, data);
  if (rs.some((x) => x.status === 401)) {   // an access token lasts 15 minutes; a customer just signs in again
    customer(data);
    rs = action[1] === 'signin' ? rs : action[2](mine.token, data);
  }
  // a 4xx a customer can cause (an order the market turns away, a shop payment over balance) is an answer, not a failure
  check(rs, { answered: (all) => all.every((x) => x.status > 0 && x.status < 500) });
  sleep(THINK_MIN + Math.random() * (THINK_MAX - THINK_MIN));
}

export default function (data) {
  if (TEST === 'users') return users(data);
  if (TEST === 'signin') {
    const email = data.emails[Math.floor(Math.random() * data.emails.length)];
    const r = post('/identity/v1/sessions', { email, password: PASSWORD }, null, 'signin');
    check(r, { ok: (x) => x.status === 200 && x.json('status') === 'AUTHENTICATED' });
  } else if (TEST === 'demo') {
    const r = post('/sandbox/v3/demo-sessions', { name: 'Capacity' }, null, 'demo');
    // 503 is the honest "no account warm right now", not a failure of the service
    check(r, { ok: (x) => x.status === 201, answered: (x) => x.status === 201 || x.status === 503 });
  } else {
    const token = data.tokens[Math.floor(Math.random() * data.tokens.length)];
    const screen = SCREENS[Math.floor(Math.random() * SCREENS.length)];
    const r = screen(token, data);
    check(r, { ok: (x) => x.status === 200 });
  }
}

export function handleSummary(data) {
  return {
    [__ENV.OUT || '/out/summary.json']: JSON.stringify(data, null, 1),
    stdout: `${TEST}: ${STEPS.length} steps done\n`,
  };
}
