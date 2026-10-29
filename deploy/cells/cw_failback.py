"""Giving a cell its customers back, automatically, with no downtime until a short cutover.

The cell that was taken over (the returning cell, X) and the cell that holds its customers (the holder, H) do it together,
talking through the `fb` field of their published status:

  X  builds a new database from H's copy by logical replication while H keeps serving; the old database is not touched
  X  asks for the cutover                        fb {role returning, phase cutover}
  H  stops the standby taking writes, replays the journal once more, reads its WAL position
                                                 fb {role holder, phase fenced, lsn}
  X  waits until it has everything up to that position, drops the subscription, moves the sequences on, and swaps the new
     database in for the old (which is archived, never merged), becomes NORMAL and serves
                                                 fb {role returning, phase done}
  H  stops the standby, becomes NORMAL, rebuilds its copy of X from X's new database

Customers of X see refused writes only between H's fence and X's swap (seconds). Anything that goes wrong before the swap rolls
back: X drops what it built and stays TAKEN_OVER, H unfences its standby and keeps holding, and it is tried again later.
"""
import time
import uuid

from cw_env import (ADMIN_DB, DB_OWNER, OWNER_PSQL, CELL, ENV, LOCK, OWN_DB, PEER, S, db_exists, iso, log, notify, now, psql, save_state, set_state, sh)
from cw_ops import (ABORT, SEQUENCES, archive_journal, copy_untouched, drop_probe, drop_remote_slot, rebuild_copy, replay_pass, resume_copy,
                    start_probe, terminate_connections)

NEW_DB = 'sprout_new'
SUB = f'back_{CELL}'
BUILD_TIMEOUT = 20 * 60
FENCED_WAIT = 90
LSN_WAIT = 90


def _set_fb(**kw):
    with LOCK:
        S['fb'] = dict(kw, at=iso())
        save_state()


def _clear_fb():
    with LOCK:
        S['fb'] = None
        save_state()


def _peer_fb(ctx):
    p = ctx.fetch_peer()
    return (p or {}).get('fb') or {}


# ── the returning cell ───────────────────────────────────────────────────────

def _cleanup_new():
    if db_exists(NEW_DB):
        psql(f"SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE database = '{NEW_DB}'", ADMIN_DB, check=False)
        psql(f'ALTER SUBSCRIPTION {SUB} DISABLE', NEW_DB, check=False)
        psql(f'ALTER SUBSCRIPTION {SUB} SET (slot_name = NONE)', NEW_DB, check=False)
        psql(f'DROP SUBSCRIPTION IF EXISTS {SUB}', NEW_DB, check=False)
        terminate_connections(NEW_DB)
        psql(f'DROP DATABASE IF EXISTS {NEW_DB}', ADMIN_DB)
    drop_remote_slot(SUB)


def _build(ctx, fid):
    log(f'failback {fid[:8]}: building a new database from cell {PEER.upper()}\'s copy')
    _cleanup_new()
    psql(f'CREATE DATABASE {NEW_DB} OWNER {DB_OWNER}', ADMIN_DB)
    sh(f'{ENV["PGDUMP_BASE"]} -d {OWN_DB} --schema-only --no-owner --no-privileges --no-publications --no-subscriptions '
       f'| {OWNER_PSQL} -d {NEW_DB} -q', timeout=300)
    psql(f"CREATE SUBSCRIPTION {SUB} CONNECTION '{ENV['PEER_PG']} dbname=sprout_{CELL}' PUBLICATION handback "
         f"WITH (copy_data = true, slot_name = '{SUB}')", NEW_DB)
    deadline = time.time() + BUILD_TIMEOUT
    while True:
        out = psql(f"SELECT count(*) FILTER (WHERE r.srsubstate = 'r') || '/' || count(*) FROM pg_subscription s "
                   f"JOIN pg_subscription_rel r ON r.srsubid = s.oid WHERE s.subname = '{SUB}'", NEW_DB).strip()
        ready, total = (int(x) for x in out.split('/'))
        if total > 0 and ready == total:
            break
        if time.time() > deadline:
            raise RuntimeError('the new database was not copied in time')
        if ABORT.is_set():
            raise RuntimeError('asked to stop')
        ctx.publish_status()
        time.sleep(3)
    log(f'failback {fid[:8]}: the new database is in sync')


def _wait_lsn(lsn):
    deadline = time.time() + LSN_WAIT
    while time.time() < deadline:
        ok = psql(f"SELECT coalesce(bool_or(latest_end_lsn >= '{lsn}'::pg_lsn), false) FROM pg_stat_subscription "
                  f"WHERE subname = '{SUB}' AND relid IS NULL", NEW_DB).strip()
        if ok == 't':
            return
        time.sleep(0.5)
    raise RuntimeError(f'the new database did not reach {lsn} in {LSN_WAIT} s')


def _swap(fid):
    ts = time.strftime('%Y%m%d%H%M', time.gmtime())
    archive = f'sprout_before_failback_{ts}'
    log(f'failback {fid[:8]}: swapping the new database in (the old one is kept as {archive})')
    psql(f'DROP SUBSCRIPTION {SUB}', NEW_DB)                 # also drops its slot on the holder
    psql(SEQUENCES, NEW_DB)
    psql(f"SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'from_{CELL}' AND NOT active", ADMIN_DB, check=False)
    # the new database is ready to publish, as the old one was
    psql(f"""
DO $$ DECLARE s text; BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO replicator', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO replicator', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO replicator', s);
  END LOOP;
END $$;
CREATE PUBLICATION cell_{CELL} FOR ALL TABLES;
""", NEW_DB)
    # the holder's copy of this cell is this database as it is now: a slot made now, before anything is written to it, lets the holder
    # resume its copy from here instead of copying everything again
    try:
        psql(f"SET statement_timeout = '15s'; SELECT pg_create_logical_replication_slot('from_{CELL}', 'pgoutput')", NEW_DB)
        slot = True
    except RuntimeError as e:
        log(f'failback {fid[:8]}: no slot for the holder to resume its copy from (it will rebuild it): {e}')
        slot = False
    psql(f'ALTER DATABASE {OWN_DB} ALLOW_CONNECTIONS false', ADMIN_DB)
    last = None
    for _ in range(20):
        terminate_connections(OWN_DB)
        terminate_connections(NEW_DB)
        try:
            psql(f'ALTER DATABASE {OWN_DB} RENAME TO {archive}', ADMIN_DB)
            break
        except RuntimeError as e:
            last = e
            time.sleep(0.5)
    else:
        psql(f'ALTER DATABASE {OWN_DB} ALLOW_CONNECTIONS true', ADMIN_DB, check=False)
        raise RuntimeError(f'could not rename the old database: {last}')
    psql(f'ALTER DATABASE {NEW_DB} RENAME TO {OWN_DB}', ADMIN_DB)
    return archive, slot


def failback_returning(ctx):
    """Runs in a worker thread, on the cell that was taken over."""
    fid = uuid.uuid4().hex
    ABORT.clear()
    swapped = False
    set_state('FAILING_BACK', failback_id=fid, fb_swapped=False)
    notify(f'taking cell {CELL.upper()} back from cell {PEER.upper()}', 'building a new database; no interruption yet', 3, 'arrows_counterclockwise', key='failback')
    t0 = now()
    try:
        _set_fb(role='returning', id=fid, phase='build')
        _build(ctx, fid)
        _set_fb(role='returning', id=fid, phase='cutover')
        ctx.publish_status()
        deadline = time.time() + FENCED_WAIT
        lsn = None
        while time.time() < deadline:
            fb = _peer_fb(ctx)
            if fb.get('id') == fid and fb.get('phase') == 'fenced':
                lsn = fb['lsn']
                break
            time.sleep(1)
        if not lsn:
            raise RuntimeError('the holder did not stop its standby in time')
        _wait_lsn(lsn)
        t_swap = now()
        archive, slot = _swap(fid)
        swapped = True
        with LOCK:
            S['fb_swapped'] = True          # the point of no return: a restart after this finishes forwards
            S['fb_done_at'] = now()
            save_state()
        ctx.fence(False)
        set_state('NORMAL', failback_id=None, retry_after=0, takeover_failures=0, replay=None, hb_prepared=False)
        ctx.publish_routes('NORMAL')
        _set_fb(role='returning', id=fid, phase='done', slot=slot)
        ctx.publish_status()
        log(f'failback {fid[:8]}: serving again; refused writes lasted {now() - t_swap:.0f} s (the old database is {archive})')
        notify(f'cell {CELL.upper()} has its customers back', f'cutover took {now() - t_swap:.0f} s; the whole failback {now() - t0:.0f} s', 3, 'white_check_mark', key='failback-done')
        deadline = time.time() + 180
        while time.time() < deadline:                      # the holder gives way
            p = ctx.fetch_peer() or {}
            if p.get('state') == 'NORMAL' and not p.get('holding'):
                break
            time.sleep(2)
        _clear_fb()
    except Exception as e:
        log(f'failback {fid[:8]} failed: {e}')
        if swapped:
            set_state('NORMAL')
            ctx.publish_routes('NORMAL')
            _set_fb(role='returning', id=fid, phase='done')
            notify('failback finished with an error', str(e)[:200], 5, 'rotating_light')
        else:
            _set_fb(role='returning', id=fid, phase='abort')
            ctx.publish_status()
            try:
                _cleanup_new()
            except Exception as e2:
                log(f'could not clean up the new database: {e2}')
            set_state('TAKEN_OVER', failback_id=None, retry_after=now() + 600)
            notify('failback failed and was rolled back', f'{str(e)[:150]}; trying again in 10 minutes', 4, 'warning', key='failback-failed')
            time.sleep(5)
            _clear_fb()
    finally:
        ABORT.clear()


# ── the holder ───────────────────────────────────────────────────────────────

def handback_holder(ctx, fid):
    """Runs in a worker thread, on the cell that holds the other's customers, when the other asks for them back."""
    with LOCK:
        S['hb'] = {'id': fid, 'phase': 'fencing', 'at': iso()}
        save_state()
    log(f'handback {fid[:8]}: the other cell asks for its customers back')
    try:
        ctx.fence_standby(True)
        time.sleep(3)
        archive_journal()
        r = replay_pass()
        probe = start_probe()      # before the position is read: what the other cell builds from includes everything up to the probe
        lsn = psql('SELECT pg_current_wal_lsn()', ADMIN_DB).strip()
        with LOCK:
            S['hb'] = {'id': fid, 'phase': 'fenced', 'lsn': lsn, 'at': iso()}
            save_state()
        ctx.publish_status()
        log(f'handback {fid[:8]}: standby fenced at {lsn} (journal pass: {r["total"]} writes, {r["failed"]} failed)')
        deadline = time.time() + 120
        outcome, slot = None, False
        while time.time() < deadline:
            fb = _peer_fb(ctx)
            if fb.get('id') == fid and fb.get('phase') in ('done', 'abort'):
                outcome, slot = fb['phase'], bool(fb.get('slot'))
                break
            time.sleep(1)
        if outcome != 'done':
            raise RuntimeError('the other cell did not finish' if outcome is None else 'the other cell gave up')
        sh(ENV['STANDBY_STOP'], check=False)
        ctx.fence_standby(False)
        set_state('NORMAL', since=iso(), replay=None, hb_prepared=False)
        ctx.publish_routes('NORMAL')
        with LOCK:
            S['hb'] = None
            save_state()
        log(f'handback {fid[:8]}: cell {PEER.upper()} has its customers back')
        notify(f'gave cell {PEER.upper()} its customers back', '', 3, 'white_check_mark', key='handback-done')
        # the standby has stopped: if nothing reached the copy after the cutover point, it is what the other cell serves from
        if not (slot and probe and copy_untouched() and resume_copy()):
            log(f'handback {fid[:8]}: rebuilding this cell\'s copy of cell {PEER.upper()}')
            rebuild_copy()
    except Exception as e:
        log(f'handback {fid[:8]} did not complete: {e}; the standby serves again')
        ctx.fence_standby(False)
        with LOCK:
            S['hb'] = None
            save_state()
        notify('handback did not complete', str(e)[:200], 4, 'warning', key='handback-failed')
    finally:
        drop_probe()          # a slot left behind would keep this cell's WAL forever
