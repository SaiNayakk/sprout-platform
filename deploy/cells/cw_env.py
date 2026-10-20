"""cellwatch's surroundings: configuration from the environment, the log, alerts, the persisted state, probes, and the shell and
database helpers. Python standard library only; it runs in Termux on the phone and in a container on the laptop.

Configuration (the environment):
  CELL, PEER                    this cell's and the other cell's ids
  SELF_URL, PEER_URL            the cells' public addresses
  LOCAL_CHECK                   a URL that answers 200 when this cell's own services work
  HOST_CHECKS                   "edge=URL,URL;trading=URL,URL;..." : every service of each host (health endpoints)
  STATUS_FILE, ROUTES_FILE, CELLS_FILE, FENCE_FILE, STATE_FILE, JOURNAL_DIR, LOG_FILE
  WEIGHTS                       normal weights for new customers, e.g. "a=35,b=65"
  PSQL_BASE, PGDUMP_BASE        psql / pg_dump commands for this cell's Postgres, without -d
  PEER_PG                       a connection string to the other cell's Postgres, with the replicator role, without dbname
  ADMIN_DB                      the database to connect to for CREATE/DROP DATABASE (postgres)
  STANDBY_START, STANDBY_STOP, STANDBY_GATEWAY, STANDBY_CHECK, STANDBY_FENCE_FILE
  RELOAD_ROUTES                 makes the web server read ROUTES_FILE and CELLS_FILE again
  CELL_KEY                      the cells' shared key
  PREFERRED_SURVIVOR            the cell that keeps its takeover if both took each other over (default b)
  NTFY_TOPIC                    alerts go to https://ntfy.sh/<topic> when set
  LAN_ADDR, LAN_PEER, LAN_PORT  this cell's address on the home network, the other's, and the port cellwatch serves it on
  OWN_DB, SEED_DB               the database that serves this cell (sprout)
"""
import datetime
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

ENV = os.environ
CELL, PEER = ENV['CELL'], ENV['PEER']
CHECK_SECONDS = int(ENV.get('CHECK_SECONDS', '10'))
PEER_SERVES = '/api/marketdata/v1/market'   # answers through the other cell's own web server and gateway, no sign-in
STATE_FILE = ENV['STATE_FILE']
OWN_DB = ENV.get('OWN_DB', 'sprout')
DB_OWNER = ENV.get('DB_OWNER', 'sprout')    # the role the services connect as: it must own what cellwatch creates for them
OWNER_PSQL = ENV.get('OWNER_PSQL') or ENV['PSQL_BASE']   # psql as that role (it is no superuser on the phone)
COPY_DB = f'sprout_{PEER}'                  # this cell's copy of the other cell's database
ADMIN_DB = ENV.get('ADMIN_DB', 'postgres')
LAN_PORT = int(ENV.get('LAN_PORT', '8195'))
PARTITION_FILE = ENV.get('PARTITION_FILE', os.path.join(os.path.dirname(STATE_FILE) or '.', 'partition'))
ARCHIVE_DIR = ENV.get('JOURNAL_ARCHIVE_DIR', os.path.join(ENV.get('JOURNAL_DIR', '.'), 'archive'))
ARCHIVE_KEEP_HOURS = int(ENV.get('JOURNAL_ARCHIVE_HOURS', '72'))

LOCK = threading.RLock()
S = {}                                      # the persisted state; guarded by LOCK


def now():
    return time.time()


def iso(t=None):
    return datetime.datetime.fromtimestamp(t if t is not None else now(), datetime.timezone.utc).isoformat(timespec='seconds')


def log(msg):
    line = f'{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} [{CELL}] {msg}'
    print(line, flush=True)
    if ENV.get('LOG_FILE'):
        try:
            with open(ENV['LOG_FILE'], 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError:
            pass


# ── alerts ───────────────────────────────────────────────────────────────────

_last_alert = {}


def notify(title, body='', priority=3, tags='', key=None, cooldown=60):
    """Logs, and (when NTFY_TOPIC is set) pushes to the owner's phone. At most one push per key a minute, or per `cooldown` seconds:
    a longer cooldown also keeps the repeat out of the log (a condition checked every 30 s was logged 17,000 times in eight days)."""
    k = key or title
    t = now()
    if cooldown > 60 and t - _last_alert.get(k, 0) < cooldown:
        return
    log(f'ALERT {title}' + (f': {body}' if body else ''))
    topic = ENV.get('NTFY_TOPIC')
    if not topic:
        _last_alert[k] = t
        return
    if t - _last_alert.get(k, 0) < 60:
        return
    _last_alert[k] = t

    def post():
        try:
            req = urllib.request.Request(f'https://ntfy.sh/{topic}', data=(body or title).encode('utf-8'), method='POST',
                                         headers={'Title': f'Sprout cell {CELL.upper()}: {title}'.encode('ascii', 'ignore').decode(),
                                                  'Priority': str(priority), 'Tags': tags or 'warning',
                                                  'User-Agent': 'sprout-cellwatch'})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
    threading.Thread(target=post, daemon=True).start()


# ── state ────────────────────────────────────────────────────────────────────

def write_atomic(path, text):
    # one temporary file per thread: the heartbeat and a worker both publish the status, and a shared name lost the rename
    # race (the first automatic failback rolled back because of it)
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            S.update(json.load(f))
    except (OSError, ValueError):
        pass
    S.setdefault('state', 'NORMAL')


def save_state():
    with LOCK:
        write_atomic(STATE_FILE, json.dumps(S, indent=1))


def set_state(state, **extra):
    with LOCK:
        old = S.get('state')
        S['state'] = state
        S.update(extra)
        if state == 'NORMAL':
            S['normal_at'] = now()
        save_state()
    if old != state:
        log(f'state {old} -> {state}')


# ── probes ───────────────────────────────────────────────────────────────────

def lan_peer_url():
    addr = S.get('lan_peer') or ENV.get('LAN_PEER')
    return f'http://{addr}' if addr else None


def partitioned(url):
    """Fault injection for chaos tests: while PARTITION_FILE exists this cell cannot see the other (every request to its
    addresses fails), though nothing on the network is touched. The file's content says which paths: `cf` blocks only the
    Cloudflare address, `lan` only the home-network one, `witness` only the witness, `everything` the other cell and the witness,
    anything else (or nothing) both of the other cell's addresses."""
    try:
        with open(PARTITION_FILE, encoding='utf-8') as f:
            mode = f.read().strip()
    except OSError:
        return False
    lan = lan_peer_url()
    on_cf = url.startswith(ENV['PEER_URL'])
    on_lan = bool(lan and url.startswith(lan))
    on_wit = bool(ENV.get('WITNESS_URL') and url.startswith(ENV['WITNESS_URL']))
    if mode == 'witness':
        return on_wit
    if mode == 'everything':
        return on_cf or on_lan or on_wit
    if mode == 'cf':
        return on_cf
    if mode == 'lan':
        return on_lan
    return on_cf or on_lan


def probe(url, timeout=3, headers=None):
    """'up' | 'bad' (answered, not 2xx) | 'refused' (nothing listening) | 'slow' (no answer in time)."""
    if partitioned(url):
        return 'refused'
    try:
        req = urllib.request.Request(url, headers=dict({'User-Agent': 'sprout-cellwatch'}, **(headers or {})))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 'up' if 200 <= r.status < 300 else 'bad'
    except urllib.error.HTTPError:
        return 'bad'
    except urllib.error.URLError as e:
        reason = getattr(e, 'reason', None)
        if isinstance(reason, (ConnectionRefusedError, ConnectionResetError)) or 'refused' in str(reason).lower():
            return 'refused'
        if 'timed out' in str(reason).lower():
            return 'slow'
        return 'refused'
    except (TimeoutError, OSError):
        return 'slow'
    except Exception:
        return 'bad'


def answers(url, timeout=5):
    return probe(url, timeout) == 'up'


def get_json(url, timeout=5, headers=None):
    if partitioned(url):
        return 0, None
    try:
        req = urllib.request.Request(url, headers=dict({'Cache-Control': 'no-cache', 'User-Agent': 'sprout-cellwatch'}, **(headers or {})))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def host_checks():
    """{'edge': [url, ...], ...} from HOST_CHECKS."""
    out = {}
    for part in ENV.get('HOST_CHECKS', '').split(';'):
        if '=' in part:
            name, urls = part.split('=', 1)
            out[name.strip()] = [u.strip() for u in urls.split(',') if u.strip()]
    return out


# ── shell and database ───────────────────────────────────────────────────────

def sh(cmd, stdin=None, check=True, timeout=None):
    r = subprocess.run(cmd, shell=True, input=stdin, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f'{cmd[:70]}... failed ({r.returncode}): {(r.stderr or r.stdout)[-500:]}')
    return r.stdout


def psql(sql, db=None, check=True, timeout=None):
    """Runs SQL (on stdin) and returns the tuples-only output."""
    return sh(f'{ENV["PSQL_BASE"]} -d {db or OWN_DB} -At', stdin=sql if sql.rstrip().endswith(';') else sql + ';', check=check, timeout=timeout)


def db_exists(db):
    return psql(f"SELECT 1 FROM pg_database WHERE datname = '{db}'", ADMIN_DB).strip() == '1'
