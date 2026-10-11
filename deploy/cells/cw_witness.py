"""The cell's side of the witness (deploy/witness): a Worker outside both cells that holds each cell's lease.

  beat()       every heartbeat: this cell says it is alive and in what state; the answer says how the other cell looks from there
  takeover()   before taking the other cell over: is its lease lapsed? True (granted), False (denied), None (the witness cannot be reached)
  release()    the customers are back with their cell

The witness only ever adds a veto or a faster verdict; it is never required. If it cannot be reached the cell behaves as it did before
there was one (takeover() answers None and the caller goes ahead).
Standard library only. WITNESS_URL unset means no witness.
"""
import json
import urllib.error
import urllib.request

from cw_env import CELL, ENV, S, log, now, partitioned
from cw_logic import WitView

URL = ENV.get('WITNESS_URL', '').rstrip('/')
KEY = ENV.get('CELL_KEY', '')
WIT = {'at': 0.0, 'peer': None, 'taken_by': None, 'epoch': 0}     # the last beat's answer
STALE = 40                                                       # an answer older than this says nothing


def _post(path, body, timeout=4):
    if not URL or partitioned(URL):
        return None
    req = urllib.request.Request(f'{URL}/v1/{path}', data=json.dumps(dict(body, cell=CELL)).encode(),
                                 headers={'content-type': 'application/json', 'x-cell-key': KEY, 'User-Agent': 'sprout-cellwatch'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b'null')
    except (urllib.error.URLError, OSError, ValueError):
        return None


def beat(status):
    """status is this cell's published status (cellwatch.build_status)."""
    r = _post('beat', {k: status.get(k) for k in ('state', 'healthy', 'holding', 'declared_down')})
    if r and r.get('ok'):
        WIT.update(at=now(), peer=r.get('peer'), taken_by=r.get('taken_by'), epoch=r.get('epoch', 0))
        return True
    return False


def view():
    """What the witness says of the other cell, as the rules want it."""
    p, at = WIT.get('peer'), WIT.get('at', 0)
    if not URL or not p or now() - at > STALE:
        return WitView()
    if not p.get('seen'):
        return WitView(reachable=True)
    return WitView(reachable=True, seen=True, age=p['age'] + (now() - at), state=p.get('state', ''), healthy=bool(p.get('healthy')),
                   declared_down=bool(p.get('declared_down')))


def takeover():
    """True: granted. False: the other cell's lease is live. None: no answer (go ahead, as before)."""
    r = _post('takeover', {})
    if r is None:
        return None, 'the witness cannot be reached'
    if r.get('granted'):
        S['witness_granted'] = True
    return bool(r.get('granted')), r.get('reason', '')


def release():
    r = _post('release', {})
    if r and r.get('ok'):
        S.pop('witness_granted', None)
        log('witness: customers handed back')
        return True
    return False
