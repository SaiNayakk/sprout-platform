// PERF-01: sign-in throughput and latency through the gateway.
//
// Hypothesis: at a steady 20 sign-ins per second (far above what the phone will see), p95
// latency stays under 500 ms and fewer than 1% of requests fail, within the edge host's
// memory budget. Each request comes from a different client address, as real users would,
// so the per-client sign-in rate limit doesn't interfere.
//
// A freshly started JVM is measurably slower until the JIT has compiled the hot paths (bcrypt
// above all), and a deploy puts a fresh JVM straight into traffic. So the first 30 s ramp up
// and are held to a looser bar of their own (never near the gateway's 5 s timeout) instead of
// being hidden or averaged into the steady state.
import http from 'k6/http';
import { check } from 'k6';

const BASE = `${__ENV.BASE_URL || 'http://localhost:8100'}/api/identity`;
const USERS = 50;
const PASSWORD = 'monsoon-mango-42';

export const options = {
  scenarios: {
    warmup: {
      executor: 'ramping-arrival-rate',
      startRate: 2,
      timeUnit: '1s',
      stages: [{ target: 20, duration: '30s' }],
      preAllocatedVUs: 20,
      maxVUs: 60,
    },
    steady: {
      executor: 'constant-arrival-rate',
      startTime: '30s',
      rate: 20,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 20,
      maxVUs: 60,
    },
  },
  thresholds: {
    'http_req_duration{scenario:steady}': ['p(95)<500', 'p(99)<1000'],
    'http_req_failed{scenario:steady}': ['rate<0.01'],
    'checks{scenario:steady}': ['rate>0.99'],
    'http_req_duration{scenario:warmup}': ['p(99)<3000'],
    'http_req_failed{scenario:warmup}': ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function ip() {
  return `198.18.${Math.floor(Math.random() * 256)}.${1 + Math.floor(Math.random() * 254)}`;
}

function json(body) {
  return { headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': ip() }, body: JSON.stringify(body) };
}

export function setup() {
  const run = Date.now();
  const emails = [];
  for (let i = 0; i < USERS; i++) {
    const email = `perf-${run}-${i}@example.com`;
    const p = json({ email, password: PASSWORD, displayName: `Perf ${i}` });
    const res = http.post(`${BASE}/v1/users`, p.body, { headers: p.headers, tags: { name: 'setup' } });
    if (res.status === 201) emails.push(email);
  }
  if (emails.length < USERS * 0.9) throw new Error(`setup created only ${emails.length} users`);
  return { emails };
}

export default function (data) {
  const email = data.emails[Math.floor(Math.random() * data.emails.length)];
  const p = json({ email, password: PASSWORD });
  const res = http.post(`${BASE}/v1/sessions`, p.body, { headers: p.headers, tags: { name: 'signin' } });
  check(res, {
    'signed in': (r) => r.status === 200 && r.json('status') === 'AUTHENTICATED',
  });
}

export function handleSummary(data) {
  return {
    '/out/perf-01-k6-summary.json': JSON.stringify(data, null, 2),
    stdout: 'PERF-01 finished: results in perf-01-k6-summary.json\n',
  };
}
