"""Runs in each cell (Termux on the phone, a container on the laptop): keeps the cell safe and the customers served (ADR-027).

Every CHECK_SECONDS it looks at this cell (its address, its health check, every host of its own) and at the other cell (its
published status through Cloudflare and over the home network), hands what it saw to the rules in cw_logic.py, and acts:

  fence / unfence       take no customer writes, or take them again
  take the other over   promote the copy, start its services, replay its journal (cw_ops.py, in a worker thread)
  give way              both took each other over: the other cell keeps what it took
  get the customers back, or hand them back (cw_failback.py, in worker threads)

Beside the loop run: a heartbeat that publishes this cell's status, a server for that status on the home network, the replay of
the journal while this cell holds the other's customers, a watch on the replication, and housekeeping. Alerts go out through
cw_env.notify. Details of every rule and every number: cw_logic.py and docs/reliability/audit.md.
"""
import hashlib
import hmac
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cw_failback
import cw_ops
from cw_env import (CELL, CHECK_SECONDS, ENV, LAN_PORT, LOCK, PEER, PEER_SERVES, S, answers, get_json, host_checks, iso, lan_peer_url,
                    load_state, log, notify, now, probe, save_state, set_state, sh, write_atomic)
from cw_logic import Cfg, Obs, PeerView, decide

CFG = Cfg(cell=CELL, peer=PEER, preferred=ENV.get('PREFERRED_SURVIVOR', 'b'),
          fence_after=int(ENV.get('FENCE_AFTER', '60')), takeover_after=int(ENV.get('TAKEOVER_AFTER', '120')),
          sick_fence_after=int(ENV.get('SICK_FENCE_AFTER', '300')), sick_takeover_after=int(ENV.get('SICK_TAKEOVER_AFTER', '600')),
          unfence_after=int(ENV.get('UNFENCE_AFTER', '210')), host_down_fence_after=int(ENV.get('HOST_DOWN_FENCE_AFTER', '60')),
          declared_takeover_after=int(ENV.get('DECLARED_TAKEOVER_AFTER', '30')),
          failback_stable_after=int(ENV.get('FAILBACK_STABLE_AFTER', '180')))
STALE = 90                          # a status older than this is not believed
HEALTH = {'local': True, 'hosts': {}}      # written by the heartbeat
T = {}                              # trackers: since when something has been true
WORKER = {'thread': None, 'name': None}


# ── what the web server and the gateway are told ────────────────────────────

def routes_for(state):
    """Where a request for each cell's customers goes from this cell's web server."""
    r = {'default': 'local', CELL: 'local', PEER: 'peer'}
    if state == 'HOLDING':
        r[PEER] = 'standby'
    elif state in ('TAKEN_OVER', 'FAILING_BACK'):
        r = {'default': 'peer', CELL: 'peer', PEER: 'peer'}        # everything here is fenced: the other cell serves it all
    return r


def weights_for(state):
    w = dict(kv.split('=') for kv in ENV.get('WEIGHTS', f'{CELL}=50,{PEER}=50').split(','))
    if state == 'HOLDING':
        w = {CELL: '100', PEER: '0'}
    elif state in ('TAKEN_OVER', 'FAILING_BACK'):
        w = {CELL: '0', PEER: '100'}
    return w


def publish_routes(state):
    r = routes_for(state)
    lines = ["# Written by cellwatch.py: where each cell's customers are served from this cell (ADR-027).",
             'map $http_x_sprout_cell $sprout_route {', f'    default {r.pop("default")};']
    lines += [f'    {cell} {where};' for cell, where in sorted(r.items())]
    lines.append('}')
    write_atomic(ENV['ROUTES_FILE'], '\n'.join(lines) + '\n')
    w = weights_for(state)
    write_atomic(ENV['CELLS_FILE'], json.dumps({'cells': [{'id': c, 'weight': int(v)} for c, v in sorted(w.items())]}))
    sh(ENV['RELOAD_ROUTES'], check=False)


def fence(on):
    path = ENV['FENCE_FILE']
    if on and not os.path.exists(path):
        open(path, 'w').close()
        log('fenced: this cell takes no customer writes')
    elif not on and os.path.exists(path):
        os.remove(path)
        log('unfenced')


def fence_standby(on):
    """The standby (the other cell's services, here) takes no writes while its fence file exists."""
    path = ENV.get('STANDBY_FENCE_FILE')
    if not path:
        return
    if on:
        open(path, 'w').close()
    elif os.path.exists(path):
        os.remove(path)


# ── what this cell says about itself ────────────────────────────────────────

def own_lan_addr():
    if ENV.get('LAN_ADDR'):
        return ENV['LAN_ADDR']
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.0.2.1', 9))
        ip = s.getsockname()[0]
        s.close()
        return f'{ip}:{LAN_PORT}'
    except OSError:
        return None


def build_status():
    with LOCK:
        state = S.get('state', 'NORMAL')
        fb = None
        if S.get('hb'):
            fb = dict(S['hb'], role='holder')
        elif S.get('fb'):
            fb = dict(S['fb'])
        down = sorted(h for h, v in HEALTH['hosts'].items() if v == 'down')
        peer_ok_since = T.get('peer_reach_since')
        return {
            'cell': CELL, 'state': state, 'healthy': bool(HEALTH['local']) and not down,
            'holding': PEER if state == 'HOLDING' else None, 'at': iso(),
            'declared_down': S.get('declared_down'), 'hosts_down': down or None,
            'peer_ok_for': round(now() - peer_ok_since) if peer_ok_since else 0,
            'resumed_at': S.get('resumed_at') if now() - S.get('resumed_at', 0) < 3600 else None,
            'lan': own_lan_addr(), 'fb': fb,
            'fb_ready': bool(state == 'HOLDING' and S.get('hb_prepared') and not S.get('hb')),
            'repl': {'lag': cw_ops.RT.get('lag'), 'copy': bool(cw_ops.RT.get('copy'))},
        }


LAST_STATUS = {'json': '{}'}


def publish_status():
    text = json.dumps(build_status())
    LAST_STATUS['json'] = text
    write_atomic(ENV['STATUS_FILE'], text)


def probe_hosts():
    """'up' | 'down' (refusing, or answering an error) | 'slow' for every host of this cell."""
    out = {}
    for name, urls in host_checks().items():
        worst = 'up'
        for u in urls:
            p = probe(u, timeout=3)
            if p in ('refused', 'bad'):
                worst = 'down'
                break
            if p == 'slow':
                worst = 'slow'
        out[name] = worst
    return out


def heartbeat():
    """On its own clock, whatever else cellwatch is doing: a takeover takes minutes, and a cell whose status goes stale looks
    dead to the other cell and to the phone's starter."""
    while True:
        try:
            HEALTH['local'] = answers(ENV['LOCAL_CHECK'])
            HEALTH['hosts'] = probe_hosts()
            publish_status()
        except Exception as e:
            log(f'heartbeat failed: {e}')
        time.sleep(CHECK_SECONDS)


class LanHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        key = ENV.get('CELL_KEY', '')
        given = self.headers.get('X-Cell-Key', '')
        ok = bool(key) and hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(key.encode()).digest())
        if self.path != '/status' or not ok:
            self.send_response(403)
            self.end_headers()
            return
        body = LAST_STATUS['json'].encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve_lan():
    try:
        ThreadingHTTPServer(('0.0.0.0', LAN_PORT), LanHandler).serve_forever()
    except OSError as e:
        log(f'the status server could not listen on port {LAN_PORT}: {e}')


# ── the other cell, seen two ways ───────────────────────────────────────────

def _fresh(raw):
    if not isinstance(raw, dict):
        return False
    try:
        import datetime
        at = datetime.datetime.fromisoformat(raw['at'])
        return (datetime.datetime.now(datetime.timezone.utc) - at).total_seconds() < STALE
    except (KeyError, ValueError):
        return False


def to_view(raw):
    if not _fresh(raw):
        return PeerView()
    import datetime
    return PeerView(fresh=True, state=raw.get('state', ''), healthy=bool(raw.get('healthy')), holding=raw.get('holding'),
                    declared_down=bool(raw.get('declared_down')), peer_ok_for=float(raw.get('peer_ok_for') or 0),
                    fb=raw.get('fb'), fb_ready=bool(raw.get('fb_ready')),
                    at=datetime.datetime.fromisoformat(raw['at']).timestamp(),
                    resumed_at=float(raw.get('resumed_at') or 0))


def fetch_cf():
    code, raw = get_json(ENV['PEER_URL'] + '/cells/status.json')
    return code, (raw if code == 200 else None)


def fetch_lan():
    url = lan_peer_url()
    if not url:
        return None
    code, raw = get_json(url + '/status', timeout=3, headers={'X-Cell-Key': ENV.get('CELL_KEY', '')})
    return raw if code == 200 else None


def fetch_peer_raw():
    """The freshest status of the other cell from either path, or None."""
    for raw in (fetch_lan(), fetch_cf()[1]):
        if _fresh(raw):
            return raw
    return None


class Ctx:
    fetch_peer = staticmethod(fetch_peer_raw)
    publish_status = staticmethod(publish_status)
    publish_routes = staticmethod(publish_routes)
    fence = staticmethod(fence)
    fence_standby = staticmethod(fence_standby)


# ── workers ─────────────────────────────────────────────────────────────────

def start_worker(name, fn, *args):
    t = WORKER['thread']
    if t and t.is_alive():
        return False
    th = threading.Thread(target=fn, args=args, daemon=True, name=name)
    WORKER.update(thread=th, name=name)
    th.start()
    return True


def busy():
    t = WORKER['thread']
    return bool(t and t.is_alive())


# ── the loop ────────────────────────────────────────────────────────────────

def since_of(key, cond, t):
    """Seconds `cond` has been continuously true, tracked under `key`."""
    if cond:
        T.setdefault(key, t)
        return t - T[key]
    T.pop(key, None)
    return 0


def observe(t):
    self_ok = answers(ENV['SELF_URL'] + '/healthz')
    local_ok = HEALTH['local']
    hosts = HEALTH['hosts']
    code, cf_raw = fetch_cf()
    lan_raw = fetch_lan()
    if _fresh(cf_raw) and cf_raw.get('lan'):
        S['lan_peer'] = cf_raw['lan']            # the other cell says where it is on the home network
    cf, lan = to_view(cf_raw), to_view(lan_raw)

    peer_ok_cf = cf.fresh and cf.healthy and cf.state in ('NORMAL', 'HOLDING')
    if peer_ok_cf and not S.get('peer_seen'):
        with LOCK:
            S['peer_seen'] = True                # a cell never seen working (not set up yet) is never "lost"
        log(f'cell {PEER} seen healthy')
    peer_front_door = (not peer_ok_cf) and answers(ENV['PEER_URL'] + PEER_SERVES)
    peer_ok_any = peer_ok_cf or (lan.fresh and lan.healthy and lan.state in ('NORMAL', 'HOLDING'))

    # the hosts of this cell: down for how long, and has one been crashing again and again?
    hosts_down = {}
    flaps = S.setdefault('flaps', [])
    for h, st in hosts.items():
        d = since_of(f'host_{h}', st == 'down', t)
        if st == 'down':
            hosts_down[h] = d
        was = T.get(f'prev_{h}')
        if was == 'down' and st == 'up' and t - T.get(f'down_at_{h}', t) < CFG.host_down_fence_after:
            flaps.append(t)
        if st == 'down' and was != 'down':
            T[f'down_at_{h}'] = t
        T[f'prev_{h}'] = st
    S['flaps'] = [x for x in flaps if t - x < CFG.flap_window]

    all_green = self_ok and local_ok and not hosts_down
    o = Obs(
        addr_down_for=since_of('addr_bad', not self_ok, t),
        sick_for=since_of('sick', not local_ok, t),
        hosts_down=hosts_down, flapping=len(S['flaps']) >= CFG.flap_count,
        good_for=since_of('good', all_green, t),
        cf=cf, lan=lan,
        peer_gone_for=since_of('peer_gone', code != 200, t),
        peer_bad_for=since_of('peer_bad', not (peer_ok_cf or peer_front_door), t),
        peer_declared_for=since_of('peer_declared', (cf.fresh and cf.declared_down) or (lan.fresh and lan.declared_down), t),
        peer_seen=bool(S.get('peer_seen')),
        retry_wait=t < S.get('retry_after', 0),
        normal_at=S.get('normal_at', 0), gave_back_recently=t - S.get('fb_done_at', 0) < 180,
        holding_since=S.get('holding_since', 0) if S.get('state') == 'HOLDING' else S.get('takeover_started', 0),
    )
    since_of('peer_ok', peer_ok_any, t)
    since_of('peer_reach', cf.fresh or lan.fresh, t)    # for the other cell's decision to unfence: it sees this cell
    T['peer_reach_since'] = T.get('peer_reach')
    return o


def act(d, o):
    if d.action == 'FENCE':
        fence(True)
        set_state('FENCED', declared_down=(sorted(o.hosts_down) or ['a host']) if d.declared_down else None, fenced_since=now())
        notify(f'fenced: {d.reason}', 'this cell takes no customer writes', 5 if d.declared_down else 4, 'no_entry', key='fenced')
    elif d.action == 'UNFENCE':
        fence(False)
        set_state('NORMAL', declared_down=None)
        notify('unfenced', d.reason, 3, 'white_check_mark', key='unfenced')
    elif d.action == 'TAKEN_OVER':
        fence(True)
        set_state('TAKEN_OVER', declared_down=None, taken_over_at=now())
        publish_routes('TAKEN_OVER')
        notify(f'cell {PEER.upper()} holds this cell', 'fenced; it will be given back automatically', 4, 'warning', key='taken-over')
    elif d.action == 'RESUME':
        fence(False)
        set_state('NORMAL', declared_down=None)
        publish_routes('NORMAL')
        notify(f'cell {CELL.upper()} is serving again', d.reason, 3, 'white_check_mark', key='resumed')
    elif d.action == 'RESUME_STALE':
        cw_ops.resume_stale(publish_routes, fence)
    elif d.action == 'TAKEOVER':
        if not cw_ops.copy_whole():
            log(f'cell {PEER} looks lost ({d.reason}), but this cell holds no whole copy of it: not taking over')
            S['retry_after'] = now() + 120
            notify(f'cell {PEER.upper()} is lost and there is no copy to take over', d.reason, 5, 'rotating_light', key='nocopy-takeover')
            return
        cw_ops.RT['standby_up'] = False
        start_worker('takeover', cw_ops.take_over, d.reason, publish_routes)
    elif d.action == 'YIELD':
        cw_ops.yield_to_peer(publish_routes, fence)
    elif d.action == 'FAILBACK':
        start_worker('failback', cw_failback.failback_returning, Ctx)


def recover_after_restart():
    """cellwatch can be restarted anywhere: finish or undo what was in progress."""
    st = S.get('state')
    if st == 'TAKING_OVER':
        log('restarted in the middle of a takeover: starting it again')
        start_worker('takeover', cw_ops.take_over, 'resumed after a restart', publish_routes)
    elif st == 'FAILING_BACK':
        if S.get('fb_swapped'):
            set_state('NORMAL')
            publish_routes('NORMAL')
            fence(False)
        else:
            log('restarted in the middle of a failback before the swap: rolling it back')
            try:
                cw_failback._cleanup_new()
            except Exception as e:
                log(f'cleanup failed: {e}')
            set_state('TAKEN_OVER', retry_after=now() + 120)
        cw_failback._clear_fb()
    if S.get('hb'):
        fence_standby(False)
        with LOCK:
            S['hb'] = None
            save_state()


def background(fn, every):
    def loop():
        time.sleep(5)
        while True:
            try:
                fn()
            except Exception as e:
                log(f'{fn.__name__} failed: {e}')
            time.sleep(every)
    threading.Thread(target=loop, daemon=True, name=fn.__name__).start()


def replay_while_holding():
    if S.get('state') == 'HOLDING':
        r = cw_ops.replay_pass()
        if r['applied'] or r['failed']:
            log(f'replayed {r["total"]} journalled writes: {r["applied"]} applied, {r["repeated"]} already done, '
                f'{r["refused"]} refused, {r["failed"]} failed')


def unprotected_writes():
    """The gateway writes down every write that went ahead without the other cell having it (its journal was slow or away). Those
    are the only writes a failure of this cell right now could lose: say so, once a minute at most."""
    import glob
    # every line of a file touched in the last five minutes (an hour's file holds that hour's, so this over-counts a little)
    recent = 0
    for path in glob.glob(os.path.join(ENV['JOURNAL_DIR'], f'unprotected-{CELL}-*.jsonl')):
        try:
            if now() - os.path.getmtime(path) < 300:
                with open(path, encoding='utf-8') as f:
                    recent += sum(1 for _ in f)
        except OSError:
            pass
    if recent:
        notify(f'{recent} writes have no copy in the other cell',
               'its journal has been slow or away: a failure of this cell right now could lose them', 4, 'warning', key='unprotected')


def resources():
    """Disk, clock and (on the phone) battery: the quiet ways a cell stops."""
    try:
        st = os.statvfs(ENV['JOURNAL_DIR'])
        free_gb = st.f_bavail * st.f_frsize / 1e9
        if free_gb < 2:
            notify('disk is almost full', f'{free_gb:.1f} GB free', 5, 'floppy_disk', key='disk')
    except OSError:
        pass
    raw = fetch_peer_raw()
    if raw:
        try:
            import datetime
            skew = (datetime.datetime.fromisoformat(raw['at']) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            if abs(skew) > 45:
                notify('clocks disagree', f"the other cell's clock differs by {skew:.0f} s", 4, 'clock', key='skew')
        except (KeyError, ValueError):
            pass
    out = sh('termux-battery-status 2>/dev/null', check=False)
    if out.strip():
        try:
            b = json.loads(out)
            if b.get('percentage', 100) <= 25 and b.get('plugged') == 'UNPLUGGED':
                notify(f'battery at {b["percentage"]}%', 'plug the phone in', 5, 'battery', key='battery')
        except ValueError:
            pass


def main():
    load_state()
    publish_routes(S['state'])
    HEALTH['local'] = answers(ENV['LOCAL_CHECK'])
    cw_ops.setup_wal_cap()
    threading.Thread(target=heartbeat, daemon=True, name='heartbeat').start()
    threading.Thread(target=serve_lan, daemon=True, name='lan').start()
    background(cw_ops.archive_journal, 30)
    background(cw_ops.monitor_once, 30)
    background(replay_while_holding, 5)
    background(cw_ops.selfreplay_while_active, 5)
    background(cw_ops.maintenance, 3600)
    background(resources, 300)
    background(unprotected_writes, 60)
    recover_after_restart()
    log(f'watching (state {S["state"]})')
    while True:
        t = now()
        try:
            o = observe(t)
            cw_ops.RT['peer_ok'] = bool(o.cf.fresh and o.cf.healthy)
            state = S['state']
            if state == 'TAKING_OVER' and not cw_ops.RT.get('standby_up') and T.get('peer_ok') and t - T['peer_ok'] >= 60:
                log('the other cell has been healthy for a minute: stopping the takeover')
                cw_ops.ABORT.set()
            d = decide(state, o, CFG)
            if not d and state == 'TAKEN_OVER' and t - T.get('dbg', 0) > 60:
                T['dbg'] = t          # what a taken-over cell is waiting for, once a minute
                log(f'taken over; waiting: other cell gone {o.peer_gone_for:.0f}s (lan seen: {o.lan.fresh}), this cell healthy for '
                    f'{o.good_for:.0f}s, retry wait: {o.retry_wait}, other cell says: {o.cf.state or "-"}/{o.cf.holding or "-"}')
            if d and not (busy() and d.action in ('TAKEOVER', 'FAILBACK')):
                log(f'{d.action}: {d.reason}')
                act(d, o)
            # the other cell asks for its customers back
            if state == 'HOLDING' and not busy() and not S.get('hb'):
                fb = (fetch_peer_raw() or {}).get('fb') or {}
                if fb.get('role') == 'returning' and fb.get('phase') == 'cutover' and fb.get('id') != S.get('hb_last'):
                    with LOCK:
                        S['hb_last'] = fb['id']
                    start_worker('handback', cw_failback.handback_holder, Ctx, fb['id'])
            save_state()
        except Exception as e:
            log(f'error: {e}')
        time.sleep(CHECK_SECONDS)


if __name__ == '__main__':
    main()
