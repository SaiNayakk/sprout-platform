"""What cellwatch does to the databases, the journal and the standby: take the other cell over, keep replaying its journal,
watch the replication, rebuild the copy, and clean up. Every step is safe to run again (a restart can land anywhere)."""
import base64
import glob
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from cw_logic import should_rebuild_copy
from cw_env import (ADMIN_DB, ARCHIVE_DIR, DB_OWNER, OWNER_PSQL, ARCHIVE_KEEP_HOURS, COPY_DB, ENV, LOCK, OWN_DB, PEER, S, CELL, answers, db_exists, iso,
                    log, notify, now, psql, save_state, set_state, sh)

REPLAY_WORKERS = int(ENV.get('REPLAY_WORKERS', '8'))
REPLAY_GIVE_UP_AFTER = 40          # attempts for one journalled write before it is reported and let go
ABORT = threading.Event()          # asks a takeover in progress to stop and roll back
REPLAY_LOCK = threading.Lock()     # one replay pass at a time (the loop and a handback both run one)
RT = {}                            # runtime facts the status and the monitor share (not persisted)

# logical replication doesn't carry sequences: move each past any id the lost cell can have handed out
SEQUENCES = """
DO $$
DECLARE r record; top bigint;
BEGIN
  FOR r IN SELECT s.oid::regclass AS seq, d.refobjid::regclass AS tbl, a.attname AS col
           FROM pg_class s
           LEFT JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a', 'i')
           LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
           WHERE s.relkind = 'S' LOOP
    top := 0;
    IF r.tbl IS NOT NULL THEN
      EXECUTE format('SELECT coalesce(max(%I), 0) FROM %s', r.col, r.tbl) INTO top;
    -- two sequences number something that isn't their own column (2026-10-09: demat accounts couldn't be opened)
    ELSIF r.seq::text = 'depository.client_numbers' THEN
      SELECT coalesce(max(right(bo_id, 8)::bigint), 0) INTO top FROM depository.accounts;
    ELSIF r.seq::text = 'sandbox.demo_account_numbers' THEN
      SELECT coalesce(max(number), 0) INTO top FROM sandbox.demo_accounts;
    ELSE
      RAISE WARNING 'sequence % numbers no column cellwatch knows: moved to 1000000, which may already be used', r.seq;
    END IF;
    PERFORM setval(r.seq, greatest(top, 0) + 1000000, false);
  END LOOP;
END $$;
"""


# ── the copy of the other cell ───────────────────────────────────────────────

def copy_info():
    """The state of this cell's copy of the other cell's database, or None if it has no subscription."""
    try:
        out = psql(
            "SELECT s.subenabled::int || '|' || "
            " (SELECT count(*) FILTER (WHERE r.srsubstate = 'r') FROM pg_subscription_rel r WHERE r.srsubid = s.oid) || '|' || "
            " (SELECT count(*) FROM pg_subscription_rel r WHERE r.srsubid = s.oid) || '|' || "
            " coalesce((SELECT extract(epoch FROM max(last_msg_receipt_time)) FROM pg_stat_subscription ss "
            "           WHERE ss.subid = s.oid AND ss.relid IS NULL), 0) || '|' || "
            " (SELECT count(*) FROM pg_stat_subscription ss WHERE ss.subid = s.oid AND ss.relid IS NULL AND ss.pid IS NOT NULL) "
            f"FROM pg_subscription s WHERE s.subname = 'from_{PEER}'", COPY_DB, timeout=30).strip()
    except Exception:
        return None
    if not out:
        return None
    enabled, ready, total, last, worker = out.split('|')
    return {'enabled': enabled == '1', 'ready': int(ready), 'total': int(total), 'last_receipt': float(last), 'worker': int(worker)}


def copy_missing():
    """True only when it is certain: the copy's database is not there, or it has no subscription to the other cell. A failing query
    (Postgres starting, a timeout) says nothing, and rebuilding on it would throw away a good copy."""
    try:
        if not db_exists(COPY_DB):
            return True
        return psql(f"SELECT count(*) FROM pg_subscription WHERE subname = 'from_{PEER}'", COPY_DB, timeout=30).strip() == '0'
    except Exception:
        return False


def copy_whole():
    i = copy_info()
    return bool(i and i['total'] > 0 and i['ready'] == i['total'])


# ── the journal ──────────────────────────────────────────────────────────────

def _hour_of(name):
    # a-2026101018.jsonl -> 2026101018
    return name.rsplit('-', 1)[-1].split('.')[0]


def archive_journal():
    """The gateway keeps two hours of the journal; this keeps ARCHIVE_KEEP_HOURS, so a replication that has been broken for a day
    can still be covered. Two journals: the other cell's writes (`a-*` here on the laptop), and the writes whoever holds THIS
    cell's customers has accepted for it (`b-*`), which this cell replays if that holder is lost."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    oldest = time.strftime('%Y%m%d%H', time.gmtime(now() - ARCHIVE_KEEP_HOURS * 3600))
    for prefix in (PEER, CELL):
        for path in glob.glob(os.path.join(ENV['JOURNAL_DIR'], f'{prefix}-*.jsonl')):
            dst = os.path.join(ARCHIVE_DIR, os.path.basename(path))
            try:
                if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(path):
                    shutil.copyfile(path, dst)
            except OSError:
                pass
        for path in glob.glob(os.path.join(ARCHIVE_DIR, f'{prefix}-*.jsonl')):
            if _hour_of(os.path.basename(path)) < oldest:
                try:
                    os.remove(path)
                except OSError:
                    pass


def read_journal(since, prefix=None):
    """(entries newer than `since`, ids of writes the customer was told were refused), from the archive."""
    prefix = prefix or PEER
    start_hour = time.strftime('%Y%m%d%H', time.gmtime(max(0, _parse_iso(since) - 3600)))
    entries, refused = [], set()
    for path in sorted(glob.glob(os.path.join(ARCHIVE_DIR, f'{prefix}-*.jsonl'))):
        if _hour_of(os.path.basename(path)) < start_hour:
            continue
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue            # a line still being written: seen whole next time
                if e.get('outcomeOf'):
                    if 400 <= int(e.get('status', 0)) < 500:
                        refused.add(e['outcomeOf'])
                elif e.get('receivedAt', '') > since:
                    entries.append(e)
    return entries, refused


def _parse_iso(s):
    import datetime
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0


def replay_one(e, target=None):
    url = (target or ENV['STANDBY_GATEWAY']) + e['uri'] + (('?' + e['query']) if e.get('query') else '')
    headers = {'X-Cell-Replay-Key': ENV['CELL_KEY'], 'X-Cell-Replay-User': e['userId'], 'Idempotency-Key': e['idempotencyKey'],
               'Content-Type': e.get('contentType') or 'application/json', 'User-Agent': 'sprout-cellwatch'}
    body = base64.b64decode(e.get('body') or '')
    status = 0
    for _ in range(3):
        try:
            req = urllib.request.Request(url, data=body if body else None, method=e['method'], headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                status = r.status
        except urllib.error.HTTPError as err:
            status = err.code
        except Exception:
            status = 0
        if status and status < 500:
            return status
        time.sleep(1)
    return status


def replay_pass(prefix=None, target=None, key='replay'):
    """Sends the journalled writes not yet handled to the standby's gateway (or `target`): different customers in parallel, one customer's
    writes in order. A write that fails is kept and tried again every pass (and so are the writes after it, for that customer),
    so nothing the customer was told succeeded is dropped. Safe to repeat: every write carries its key."""
    with REPLAY_LOCK:
        return _replay_pass(prefix, target, key)


def _replay_pass(prefix, target, key):
    with LOCK:
        r = S.setdefault(key, {'watermark': iso(now() - 3600), 'failed': {}})
        watermark, failed = r['watermark'], dict(r['failed'])
    since_read = min([watermark] + [f['at'] for f in failed.values()])
    entries, refused = read_journal(since_read, prefix)
    todo = [e for e in entries if (e.get('receivedAt', '') > watermark or e.get('id') in failed) and e.get('id') not in refused]
    if not todo:
        return {'total': 0, 'applied': 0, 'repeated': 0, 'refused': 0, 'failed': len(failed)}
    todo.sort(key=lambda e: e.get('receivedAt', ''))
    by_user = {}
    for e in todo:
        by_user.setdefault(e['userId'], []).append(e)
    counts = {'applied': 0, 'repeated': 0, 'refused': 0}
    new_failed, done_max = {}, watermark
    lock = threading.Lock()

    def run_user(items):
        nonlocal done_max
        blocked = False
        for e in items:
            if blocked:
                with lock:
                    new_failed[e['id']] = {'at': e.get('receivedAt', ''), 'n': failed.get(e['id'], {}).get('n', 0)}
                continue
            status = replay_one(e, target)
            with lock:
                if status in (201, 204):
                    counts['applied'] += 1
                elif status == 200:
                    counts['repeated'] += 1
                elif status and status < 500:
                    counts['refused'] += 1
                else:
                    blocked = True
                    n = failed.get(e['id'], {}).get('n', 0) + 1
                    new_failed[e['id']] = {'at': e.get('receivedAt', ''), 'n': n}
                    log(f'replay failed ({status}): {e["method"]} {e["uri"]} key {e["idempotencyKey"]} attempt {n}')
                    continue
                if e.get('receivedAt', '') > done_max:
                    done_max = e['receivedAt']

    with ThreadPoolExecutor(max_workers=REPLAY_WORKERS) as pool:
        list(pool.map(run_user, by_user.values()))
    gave_up = [i for i, f in new_failed.items() if f['n'] >= REPLAY_GIVE_UP_AFTER]
    for i in gave_up:
        new_failed.pop(i)
    if gave_up:
        notify(f'{len(gave_up)} journalled writes could not be replayed', 'gave up after repeated failures: see the log', 5, 'rotating_light')
    with LOCK:
        S[key] = {'watermark': max(done_max, watermark), 'failed': new_failed}
        save_state()
    return dict(counts, total=len(todo), failed=len(new_failed))


def initial_watermark():
    """Where the journal must be replayed from: a little before the copy last heard from the other cell. The copy has
    everything up to then; the journal has the rest, if it reaches back that far."""
    i = copy_info()
    if i and i['last_receipt'] > 0:
        since = i['last_receipt'] - 120
    else:
        since = now() - (ARCHIVE_KEEP_HOURS - 1) * 3600
    if since < now() - (ARCHIVE_KEEP_HOURS - 1) * 3600:
        notify('the journal may not reach back to the copy',
               f'the copy last heard from cell {PEER.upper()} {int((now() - since) / 3600)} h ago; writes before the journal began are not covered',
               5, 'rotating_light')
        since = now() - (ARCHIVE_KEEP_HOURS - 1) * 3600
    return iso(since)


# ── taking the other cell over ───────────────────────────────────────────────

def _stop_standby():
    sh(ENV['STANDBY_STOP'], check=False)


def prepare_handback():
    """What giving the customers back needs, ready on the holder: the replicator may read this copy, and the copy publishes."""
    psql("""
DO $$ DECLARE s text; BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO replicator', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO replicator', s);
  END LOOP;
END $$;
SELECT 'CREATE PUBLICATION handback FOR ALL TABLES' WHERE NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'handback') \\gexec
SELECT 1;
""", COPY_DB)
    with LOCK:
        S['hb_prepared'] = True
        save_state()


def take_over(reason, publish_routes):
    """Runs in a worker thread, so the watcher keeps watching. Rolls itself back if anything fails or is asked to stop."""
    ABORT.clear()
    set_state('TAKING_OVER', since=iso(), takeover_reason=reason, takeover_started=now())
    notify(f'taking cell {PEER.upper()} over', reason, 4, 'warning', key='takeover')
    try:
        info = copy_info()
        if not info or not (info['total'] > 0 and info['ready'] == info['total']):
            raise RuntimeError('this cell holds no whole copy of the other cell')
        archive_journal()
        watermark = initial_watermark()
        psql(f'ALTER SUBSCRIPTION from_{PEER} DISABLE', COPY_DB)
        psql(SEQUENCES, COPY_DB)
        log(f'stopped replicating from {PEER} and moved its sequences on')
        sh(ENV['STANDBY_START'])
        deadline = time.time() + 600
        while not answers(ENV['STANDBY_CHECK']):
            if ABORT.is_set():
                raise RuntimeError('asked to stop')
            if time.time() > deadline:
                raise RuntimeError("the standby didn't come up in 10 minutes")
            time.sleep(3)
        log('standby is up')
        RT['standby_up'] = True
        if ABORT.is_set():
            raise RuntimeError('asked to stop')
        with LOCK:
            S['replay'] = {'watermark': watermark, 'failed': {}}
        archive_journal()
        r = replay_pass()
        log(f'replayed {r["total"]} journalled writes: {r["applied"]} applied, {r["repeated"]} already done, {r["refused"]} refused, '
            f'{r["failed"]} failed (retried every few seconds until they succeed)')
        try:
            prepare_handback()
        except Exception as e:
            log(f'handback preparation failed (retried later): {e}')
        set_state('HOLDING', since=iso(), holding_since=now(), retry_after=0, takeover_failures=0)
        publish_routes('HOLDING')
        notify(f'holding cell {PEER.upper()}', f"its customers are served here ({int(now() - S['takeover_started'])} s)", 3, 'white_check_mark', key='held')
    except Exception as e:
        log(f'taking cell {PEER} over failed: {e}')
        _stop_standby()
        try:
            psql(f'ALTER SUBSCRIPTION from_{PEER} ENABLE', COPY_DB)
        except Exception as e2:
            log(f'could not re-enable the replication: {e2}')
        with LOCK:
            n = S.get('takeover_failures', 0) + 1
        set_state('NORMAL', takeover_failures=n, retry_after=now() + (120 if n < 3 else 600))
        notify(f'taking cell {PEER.upper()} over failed', str(e)[:200], 5, 'rotating_light', key='takeover-failed')
    finally:
        ABORT.clear()


def resume_stale(publish_routes, fence):
    """The cell holding this one's customers is gone: serve them from this cell's own database (as it was when it was taken over),
    and replay the writes the holder journalled here, which is everything it accepted that it had told them succeeded."""
    log('the cell holding this one has been gone: resuming from this cell\'s own database')
    start = S.get('taken_over_at', now() - 3600) - 120
    with LOCK:
        S['selfreplay'] = {'watermark': iso(start), 'failed': {}}
        S['selfreplay_until'] = now() + 1800
    fence(False)
    set_state('NORMAL', resumed_at=now(), declared_down=None)
    publish_routes('NORMAL')
    notify(f'cell {CELL.upper()} resumed without cell {PEER.upper()}',
           f'cell {PEER.upper()}, which held its customers, is gone; serving from the database as it was at the takeover, plus what was journalled here since',
           5, 'rotating_light', key='resume-stale')


def selfreplay_while_active():
    if S.get('selfreplay_until', 0) > now() and ENV.get('OWN_GATEWAY'):
        archive_journal()
        r = replay_pass(prefix=CELL, target=ENV['OWN_GATEWAY'], key='selfreplay')
        if r['applied'] or r['failed']:
            log(f'replayed {r["total"]} writes the holder journalled here: {r["applied"]} applied, {r["repeated"]} already done, '
                f'{r["refused"]} refused, {r["failed"]} failed')


def yield_to_peer(publish_routes, fence):
    """Both cells took each other over, and the other one keeps its takeover: stop serving its customers and step aside."""
    log('both cells took each other over: giving way')
    ABORT.set()
    fence(True)
    _stop_standby()
    set_state('TAKEN_OVER', retry_after=0, taken_over_at=now())
    publish_routes('TAKEN_OVER')
    notify('gave way in a double takeover', f'cell {PEER.upper()} keeps cell {CELL.upper()}\'s customers; this copy is rebuilt', 4, 'warning')
    threading.Thread(target=rebuild_copy, daemon=True).start()


# ── the copy ─────────────────────────────────────────────────────────────────

def drop_remote_slot(name):
    """Drops a replication slot on the OTHER cell's Postgres with the replicator role (it has REPLICATION)."""
    sh(f'psql "{ENV["PEER_PG"]} dbname={OWN_DB} replication=database" -c "DROP_REPLICATION_SLOT {name} WAIT"', check=False, timeout=30)


def terminate_connections(db):
    psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db}' AND pid <> pg_backend_pid()", ADMIN_DB, check=False)


def rebuild_copy():
    """Makes this cell's copy of the other cell's database again, from scratch: drops the old one and subscribes anew (the
    initial copy runs in the background and is whole when every table is ready)."""
    try:
        log(f'rebuilding the copy of cell {PEER.upper()}')
        if db_exists(COPY_DB):
            psql(f'ALTER SUBSCRIPTION from_{PEER} DISABLE', COPY_DB, check=False)
            psql(f'ALTER SUBSCRIPTION from_{PEER} SET (slot_name = NONE)', COPY_DB, check=False)
            psql(f'DROP SUBSCRIPTION IF EXISTS from_{PEER}', COPY_DB, check=False)
            terminate_connections(COPY_DB)
            psql(f'DROP DATABASE IF EXISTS {COPY_DB}', ADMIN_DB)
        drop_remote_slot(f'from_{PEER}')
        psql(f'CREATE DATABASE {COPY_DB} OWNER {DB_OWNER}', ADMIN_DB)
        sh(f'pg_dump "{ENV["PEER_PG"]} dbname={OWN_DB}" --schema-only --no-owner --no-privileges --no-publications --no-subscriptions '
           f'| {OWNER_PSQL} -d {COPY_DB} -q', timeout=300)
        psql(f"CREATE SUBSCRIPTION from_{PEER} CONNECTION '{ENV['PEER_PG']} dbname={OWN_DB}' PUBLICATION cell_{PEER} "
             'WITH (copy_data = true)', COPY_DB)
        log(f'subscribed to cell {PEER.upper()}; the initial copy is running')
        return True
    except Exception as e:
        log(f'rebuilding the copy failed: {e}')
        notify('could not rebuild the copy', str(e)[:200], 5, 'rotating_light', key='rebuild')
        return False


# ── watching the replication ─────────────────────────────────────────────────

def monitor_once():
    state = S.get('state')
    info = copy_info()
    RT['copy'] = info
    if state not in ('NORMAL', 'FENCED'):
        return
    if info is None:
        if S.get('peer_seen') and copy_missing():
            since = RT.setdefault('copy_missing_since', now())
            notify('no copy of the other cell', 'this cell has no subscription to it', 5, 'rotating_light', key='nocopy', cooldown=3600)
            if should_rebuild_copy(state, now() - since, True, bool(RT.get('peer_ok')), now() < S.get('rebuild_after', 0)):
                S['rebuild_after'] = now() + 600        # a failed attempt is not repeated for ten minutes
                notify('making the missing copy again', 'the other cell is well: copying it', 3, 'wrench', key='rebuilding', cooldown=3600)
                rebuild_copy()
        else:
            RT.pop('copy_missing_since', None)
        return
    RT.pop('copy_missing_since', None)
    if not info['enabled']:
        log('the replication was disabled while nothing is being taken over: enabling it')
        try:
            psql(f'ALTER SUBSCRIPTION from_{PEER} ENABLE', COPY_DB)
            notify('replication was off', 're-enabled', 4, 'warning', key='repl-off')
        except Exception as e:
            notify('replication is off and cannot be enabled', str(e)[:200], 5, 'rotating_light', key='repl-off')
        return
    if info['total'] > 0 and info['ready'] == info['total']:
        if info['worker'] == 0:
            RT['worker_missing'] = RT.get('worker_missing', 0) + 1
            if RT['worker_missing'] >= 3:
                notify('replication is not running', 'the apply worker is gone', 5, 'rotating_light', key='repl-worker')
        else:
            RT['worker_missing'] = 0
        lag = now() - info['last_receipt'] if info['last_receipt'] else None
        RT['lag'] = lag
        if lag is not None and lag > 180 and RT.get('peer_ok'):
            notify('replication is behind', f'nothing received from the other cell for {int(lag)} s', 4, 'warning', key='repl-lag')
    lost = psql("SELECT slot_name || ' ' || wal_status FROM pg_replication_slots WHERE wal_status IN ('lost', 'unreserved')",
                ADMIN_DB, check=False).strip()
    if lost:
        notify('a replication slot is lost', f'{lost}: the other cell\'s copy of this cell must be rebuilt', 5, 'rotating_light', key='slot-lost')


def setup_wal_cap():
    """A stalled peer must not fill the disk: its slot is let go past this much WAL (the copy is then rebuilt)."""
    try:
        psql("ALTER SYSTEM SET max_slot_wal_keep_size = '8GB'", ADMIN_DB)
        psql('SELECT pg_reload_conf()', ADMIN_DB)
    except Exception as e:
        log(f'could not cap the WAL kept for replication: {e}')


def maintenance():
    """Archived databases from failbacks: keep the newest three, and any younger than three days."""
    try:
        names = [n for n in psql("SELECT datname FROM pg_database WHERE datname LIKE 'sprout\\_before\\_failback\\_%' ORDER BY datname",
                                 ADMIN_DB).split() if n]
        cutoff = time.strftime('%Y%m%d%H%M', time.gmtime(now() - 3 * 86400))
        for n in names[:-3]:
            if n.rsplit('_', 1)[-1] < cutoff:
                terminate_connections(n)
                psql(f'DROP DATABASE IF EXISTS {n}', ADMIN_DB)
                log(f'dropped the archived database {n}')
    except Exception as e:
        log(f'maintenance failed: {e}')
