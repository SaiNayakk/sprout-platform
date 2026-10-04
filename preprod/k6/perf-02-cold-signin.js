// PERF-02: sign-in straight after a restart.
//
// Hypothesis: with the edge host warming itself up before it reports ready, 10 sign-ins a second
// from the moment it is ready meet the same bar as a warm host: p95 under 500 ms, p99 under 1 s.
// (Without warm-up, PERF-01's first version measured p99 1.9 s here.)
//
// Run twice: once with PREPARE=1 before the restart, to create the accounts (creating them on the
// fresh host would warm it up and spoil the measurement), then without it, right after the restart.
import http from 'k6/http';
import { check } from 'k6';

const BASE = `${__ENV.BASE_URL || 'http://localhost:8100'}/api/identity`;
const PREPARE = __ENV.PREPARE === '1';
const USERS = 50;
const PASSWORD = 'monsoon-mango-42';

export const options = PREPARE
  ? { vus: 1, iterations: 1 }
  : {
      scenarios: {
        cold: { executor: 'constant-arrival-rate', rate: 10, timeUnit: '1s', duration: '30s', preAllocatedVUs: 20, maxVUs: 60 },
      },
      thresholds: {
        'http_req_duration{scenario:cold}': ['p(95)<500', 'p(99)<1000'],
        'http_req_failed{scenario:cold}': ['rate<0.01'],
        'checks{scenario:cold}': ['rate>0.99'],
      },
      summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
    };

function ip() {
  return `198.18.${Math.floor(Math.random() * 256)}.${1 + Math.floor(Math.random() * 254)}`;
}

function email(i) {
  return `perf02-${i}@example.com`;
}

function post(path, body) {
  return http.post(`${BASE}${path}`, JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': ip() },
  });
}

export default function () {
  if (PREPARE) {
    for (let i = 0; i < USERS; i++) {
      post('/v1/users', { email: email(i), password: PASSWORD, displayName: `Perf ${i}` });
    }
    return;
  }
  const res = post('/v1/sessions', { email: email(Math.floor(Math.random() * USERS)), password: PASSWORD });
  check(res, { 'signed in': (r) => r.status === 200 && r.json('status') === 'AUTHENTICATED' });
}

export function handleSummary(data) {
  if (PREPARE) {
    return { stdout: 'PERF-02 accounts ready\n' };
  }
  return {
    '/out/perf-02-k6-summary.json': JSON.stringify(data, null, 2),
    stdout: 'PERF-02 finished: results in perf-02-k6-summary.json\n',
  };
}
