"""Watches this cell and the other one, and takes the other cell's customers over when it is lost (ADR-027).

Runs in each cell (Termux on the phone, a container on the laptop), Python standard library only. Every CHECK_SECONDS:

  * publishes this cell's status (healthy?, state) to STATUS_FILE, which the cell's web server serves at
    /cells/status.json, so the other cell can see it from outside
  * checks this cell's own public address (through Cloudflare, as a customer would reach it) and the other's

and acts on what it sees:

  NORMAL      this cell can't reach its own public address for FENCE_AFTER (60 s)          -> FENCED
              it can, but the other cell has been unreachable or unhealthy for TAKEOVER_AFTER
              (120 s, deliberately longer than FENCE_AFTER, so the lost cell has stopped writing) -> HOLDING
  FENCED      no customer writes here (the gateway refuses them while FENCE_FILE exists). When the
              public address answers again: if the other cell is holding this cell's customers -> TAKEN_OVER,
              else -> NORMAL
  HOLDING     this cell runs the other cell's services on its copy of that cell's database. Stays until failback.
  TAKEN_OVER  this cell's customers are served by the other cell; this cell stays fenced. Stays until failback.

Taking over: stop applying replication from the lost cell, move every sequence past any id it can have used, start the
standby (the lost cell's services, with its keys, on the copy), replay the lost cell's journal through the standby's
gateway (a write that had already replicated is recognised by its idempotency key and changes nothing), then send the
lost cell's customers to the standby and every new customer to this cell.

Configuration is the environment; commands are run through the shell, so the same file works on both cells:
  CELL, PEER                    this cell's and the other cell's ids (a, b)
  SELF_URL, PEER_URL            the cells' own public addresses (https://sprout-a-..., https://sprout-b-...)
  LOCAL_CHECK                   a URL that answers 200 when this cell's own services are up
  STATUS_FILE, ROUTES_FILE, CELLS_FILE, FENCE_FILE, STATE_FILE, JOURNAL_DIR, LOG_FILE
  WEIGHTS                       normal weights for new customers, e.g. "a=30,b=70"
  REPLICA_PSQL                  a command that runs SQL (stdin) against this cell's copy of the other cell's database
  STANDBY_START, STANDBY_STOP   commands that start and stop the standby
  STANDBY_GATEWAY               the standby's gateway, e.g. http://127.0.0.1:8200
  STANDBY_CHECK                 a URL that answers 200 once the standby is up
  RELOAD_ROUTES                 a command that makes the web server read ROUTES_FILE and CELLS_FILE again
  CELL_KEY                      the cells' shared key (replays are accepted with it)
"""
import base64
import datetime
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENV = os.environ
CELL, PEER = ENV['CELL'], ENV['PEER']
CHECK_SECONDS = int(ENV.get('CHECK_SECONDS', '10'))
FENCE_AFTER = int(ENV.get('FENCE_AFTER', '60'))
TAKEOVER_AFTER = int(ENV.get('TAKEOVER_AFTER', '120'))
STATE_FILE = ENV['STATE_FILE']


def log(msg):
    line = f'{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} [{CELL}] {msg}'
    print(line, flush=True)
    if ENV.get('LOG_FILE'):
        with open(ENV['LOG_FILE'], 'a', encoding='utf-8') as f:
            f.write(line + '\n')


def get_json(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'sprout-cellwatch'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def answers(url, timeout=5):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'sprout-cellwatch'}), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def sh(cmd, stdin=None, check=True):
    r = subprocess.run(cmd, shell=True, input=stdin, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f'{cmd[:60]}... failed ({r.returncode}): {(r.stderr or r.stdout)[-500:]}')
    return r.stdout


def write_atomic(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'state': 'NORMAL'}


def save_state(s):
    write_atomic(STATE_FILE, json.dumps(s, indent=1))


# ── what the web server is told ─────────────────────────────────────────────

def routes_for(state):
    """Where a request for each cell's customers goes from this cell's web server."""
    r = {'default': 'local', CELL: 'local', PEER: 'peer'}
    if state == 'HOLDING':
        r[PEER] = 'standby'
    elif state == 'TAKEN_OVER':
        r = {'default': 'peer', CELL: 'peer', PEER: 'peer'}   # everything here is fenced: the other cell serves it all
    return r


def weights_for(state):
    w = dict(kv.split('=') for kv in ENV.get('WEIGHTS', f'{CELL}=50,{PEER}=50').split(','))
    if state == 'HOLDING':
        w = {CELL: '100', PEER: '0'}
    elif state == 'TAKEN_OVER':
        w = {CELL: '0', PEER: '100'}
    return w


def publish_routes(state):
    r = routes_for(state)
    lines = ['# Written by cellwatch.py: where each cell\'s customers are served from this cell (ADR-027).',
             'map $http_x_sprout_cell $sprout_route {', f'    default {r.pop("default")};']
    lines += [f'    {cell} {where};' for cell, where in sorted(r.items())]
    lines.append('}')
    write_atomic(ENV['ROUTES_FILE'], '\n'.join(lines) + '\n')
    w = weights_for(state)
    write_atomic(ENV['CELLS_FILE'], json.dumps({'cells': [{'id': c, 'weight': int(v)} for c, v in sorted(w.items())]}))
    sh(ENV['RELOAD_ROUTES'], check=False)


def publish_status(state, healthy):
    write_atomic(ENV['STATUS_FILE'], json.dumps({
        'cell': CELL, 'state': state, 'healthy': healthy, 'holding': PEER if state == 'HOLDING' else None,
        'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}))


def fence(on):
    path = ENV['FENCE_FILE']
    if on and not os.path.exists(path):
        open(path, 'w').close()
        log('fenced: this cell takes no customer writes')
    elif not on and os.path.exists(path):
        os.remove(path)
        log('unfenced')


# ── taking the other cell over ──────────────────────────────────────────────

SEQUENCES = """
DO $$
DECLARE r record; top bigint;
BEGIN
  -- logical replication doesn't carry sequences: move each past any id the lost cell can have handed out
  FOR r IN SELECT s.oid::regclass AS seq, d.refobjid::regclass AS tbl, a.attname AS col
           FROM pg_class s
           LEFT JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a', 'i')
           LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
           WHERE s.relkind = 'S' LOOP
    top := 0;
    IF r.tbl IS NOT NULL THEN
      EXECUTE format('SELECT coalesce(max(%I), 0) FROM %s', r.col, r.tbl) INTO top;
    END IF;
    PERFORM setval(r.seq, greatest(top, 0) + 1000000, false);
  END LOOP;
END $$;
"""


def replay(since):
    """Sends every journalled write of the lost cell since `since` to the standby's gateway, in order."""
    entries, refused_ids = [], set()
    for path in sorted(glob.glob(os.path.join(ENV['JOURNAL_DIR'], f'{PEER}-*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get('outcomeOf'):
                    # the customer was told this write was refused (4xx): replaying it could make it happen now
                    if 400 <= int(e.get('status', 0)) < 500:
                        refused_ids.add(e['outcomeOf'])
                elif e.get('receivedAt', '') >= since:
                    entries.append(e)
    skipped = sum(1 for e in entries if e.get('id') in refused_ids)
    entries = [e for e in entries if e.get('id') not in refused_ids]
    entries.sort(key=lambda e: e.get('receivedAt', ''))
    applied = repeated = refused = failed = 0
    for e in entries:
        url = ENV['STANDBY_GATEWAY'] + e['uri'] + (('?' + e['query']) if e.get('query') else '')
        headers = {'X-Cell-Replay-Key': ENV['CELL_KEY'], 'X-Cell-Replay-User': e['userId'],
                   'Idempotency-Key': e['idempotencyKey'], 'Content-Type': e.get('contentType') or 'application/json',
                   'User-Agent': 'sprout-cellwatch'}
        body = base64.b64decode(e.get('body') or '')
        req = urllib.request.Request(url, data=body if body else None, method=e['method'], headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    status = r.status
            except urllib.error.HTTPError as err:
                status = err.code
            except Exception:
                status = 0
            if status and status < 500:
                break
            time.sleep(2)
        if status == 201 or status == 204:
            applied += 1
        elif status == 200:
            repeated += 1    # already done (its key was found) or an idempotent state change: either way, once
        elif status and status < 500:
            refused += 1     # e.g. the account already exists: the effect is there
        else:
            failed += 1
            log(f'replay failed: {e["method"]} {e["uri"]} key {e["idempotencyKey"]} ({status})')
    log(f'replayed {len(entries)} journalled writes ({skipped} skipped: refused at the time): {applied} applied, '
        f'{repeated} already done, {refused} refused, {failed} failed')
    return failed


def replicating():
    """Whether this cell holds a live copy of the other cell's database: its subscription exists and has received data."""
    try:
        out = sh(ENV['REPLICA_PSQL'] + ' -At',
                 stdin=f"SELECT count(*) FROM pg_stat_subscription WHERE subname = 'from_{PEER}' AND received_lsn IS NOT NULL;\n")
        return out.strip() not in ('', '0')
    except RuntimeError:
        return False


def take_over(s):
    log(f'cell {PEER} is lost: taking its customers over')
    fence(False)
    sh(ENV['REPLICA_PSQL'], stdin=f'ALTER SUBSCRIPTION from_{PEER} DISABLE;\n' + SEQUENCES)
    log(f'stopped replicating from {PEER} and moved its sequences on')
    sh(ENV['STANDBY_START'])
    deadline = time.time() + 600
    while not answers(ENV['STANDBY_CHECK']):
        if time.time() > deadline:
            raise RuntimeError('the standby didn\'t come up in 10 minutes')
        time.sleep(5)
    log('standby is up')
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()
    replay(since)
    s.update(state='HOLDING', since=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))
    save_state(s)
    publish_routes('HOLDING')
    log(f'holding cell {PEER}: its customers are served here')


# ── the loop ────────────────────────────────────────────────────────────────

def main():
    s = load_state()
    publish_routes(s['state'])
    self_bad_since = peer_bad_since = None
    log(f'watching (state {s["state"]})')
    while True:
        now = time.time()
        local_ok = answers(ENV['LOCAL_CHECK'])
        publish_status(s['state'], local_ok)
        self_ok = answers(ENV['SELF_URL'] + '/healthz')
        code, peer = get_json(ENV['PEER_URL'] + '/cells/status.json')
        peer_fresh = False
        if code == 200 and isinstance(peer, dict):
            try:
                at = datetime.datetime.fromisoformat(peer['at'])
                peer_fresh = (datetime.datetime.now(datetime.timezone.utc) - at).total_seconds() < 90
            except (KeyError, ValueError):
                pass
        peer_ok = peer_fresh and peer.get('healthy') and peer.get('state') in ('NORMAL', 'HOLDING')
        if peer_ok and not s.get('peer_seen'):
            s['peer_seen'] = True    # a cell that was never seen working (not set up yet) is never "lost"
            log(f'cell {PEER} seen healthy')
        self_bad_since = None if self_ok else (self_bad_since or now)
        peer_bad_since = None if peer_ok else (peer_bad_since or now)
        state = s['state']
        try:
            if state == 'NORMAL':
                if self_bad_since and now - self_bad_since >= FENCE_AFTER:
                    fence(True)
                    s['state'] = 'FENCED'
                elif (self_ok and local_ok and peer_bad_since and now - peer_bad_since >= TAKEOVER_AFTER
                      and s.get('peer_seen') and now >= s.get('retry_after', 0)):
                    if not replicating():
                        log(f'cell {PEER} looks lost, but this cell holds no live copy of it: not taking over')
                        s['retry_after'] = now + 600
                    else:
                        try:
                            take_over(s)
                        except Exception as e:
                            log(f'taking cell {PEER} over failed: {e}; trying again in ten minutes')
                            s['retry_after'] = now + 600
            elif state == 'FENCED':
                if self_ok:
                    if peer_fresh and peer.get('holding') == CELL:
                        s['state'] = 'TAKEN_OVER'
                        publish_routes('TAKEN_OVER')
                        log(f'cell {PEER} holds this cell\'s customers: staying fenced until failback')
                    else:
                        fence(False)
                        s['state'] = 'NORMAL'
            save_state(s)
        except Exception as e:
            log(f'error in state {state}: {e}')
        time.sleep(CHECK_SECONDS)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'replay':
        replay(sys.argv[2] if len(sys.argv) > 2 else '')
    else:
        main()
