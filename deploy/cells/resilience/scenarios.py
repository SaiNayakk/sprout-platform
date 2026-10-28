"""The scenarios of the resilience suite. Each one starts from both cells NORMAL and replicating, breaks something while customers
keep ordering, waits for the system to put itself right (no hands), and checks:

  * the time to recover (orders working again) against the target
  * every order a customer was told succeeded exists in the end, exactly once
  * both cells end NORMAL and replicating again

Each returns a dict with `pass`, the numbers, and what each cell did, and writes it to deploy/cells/results/.
"""
import time

import lib
from lib import Load, Timeline, docker, ensure_clean, heal, now, partition, record, say, states, wait_states

RECOVERY_TARGET = {'dead_host': 330, 'cf_blind': 0}


def first_order_after(load, t0, timeout=120):
    """Seconds after t0 until a customer was acknowledged for an order again: waits for it (customers retry every few seconds)."""
    end = now() + timeout
    while now() < end:
        after = [x for x in load.acked if x['at'] > t0 + 5]
        if after:
            return round(after[0]['at'] - t0)
        time.sleep(2)
    return None


def _finish(name, tl, load, extra, checks, home):
    load.stop()
    tl.stop()
    v = load.verify(home)
    clean = ensure_clean(300, whole=False)     # a copy rebuilt after a handback takes minutes more; the next scenario waits for it
    result = dict(extra, scenario=name, orders=v, both_normal_and_replicating=clean, timeline=tl.changes())
    result['pass'] = bool(v['missing'] == 0 and v['applied_twice'] == 0 and clean and all(checks.values()))
    result['checks'] = checks
    return record(name, result)


def cf_blind():
    """Neither cell can see the other through Cloudflare for 4 minutes, but both are fine and the LAN shows it: nobody takes
    anybody over, nobody fences, orders never stop."""
    name = 'cf-blind'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('a', 6, 'cfb')
    load.start()
    time.sleep(45)
    t_fault = now() - tl.t0
    partition(laptop='cf', phone_side='cf')
    say('both cells blind to each other through Cloudflare (the LAN is intact) for 240 s')
    time.sleep(240)
    heal()
    time.sleep(60)
    ok_states = all(a == 'NORMAL' and b == 'NORMAL' for t, a, b in tl.rows if t >= t_fault)
    gaps = sorted(y['at'] - x['at'] for x, y in zip(load.acked, load.acked[1:]))
    checks = {'both cells stayed NORMAL throughout': ok_states, 'no gap in the orders longer than 30 s': (gaps[-1] if gaps else 0) < 30}
    return _finish(name, tl, load, {'longest_gap_between_acknowledged_orders_s': round(gaps[-1], 1) if gaps else None}, checks, 'a')


def dead_host(service='trading', cell='b'):
    """A host of a cell stays down. The cell fences itself and says why, the other cell takes its customers over, and when the host
    is back the customers are given back, by the cells themselves."""
    name = f'dead-host-{service}'
    other = 'a' if cell == 'b' else 'b'
    container = f'sprout-laptop-{service}-1'
    assert cell == 'b', 'this scenario stops a laptop container'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load(cell, 6, 'dh')
    load.start()
    time.sleep(60)
    t_fault = now()
    docker('stop', container)
    say(f'{container} stopped')
    t_fenced = wait_states(lambda a, b: b.startswith('FENCED'), 180)
    t_hold = wait_states(lambda a, b: a.startswith('HOLDING') or b.startswith('TAKEN_OVER'), 600)
    orders_back = first_order_after(load, t_fault)
    say(f'fenced after {t_fenced}s; held after {t_hold}s (from the wait); orders back after {orders_back}s')
    time.sleep(20)
    t_restart = now()
    docker('start', container)
    say(f'{container} started again: the cells should give the customers back by themselves')
    t_back = wait_states(lambda a, b: (a, b) == ('NORMAL', 'NORMAL'), 900)
    say(f'both NORMAL {t_back}s after the host was back')
    time.sleep(45)
    gaps = [(y['at'] - x['at'], x['at']) for x, y in zip(load.acked, load.acked[1:]) if x['at'] > t_restart]
    worst = max(gaps)[0] if gaps else None
    checks = {
        'orders worked again within the target': orders_back is not None and orders_back <= RECOVERY_TARGET['dead_host'],
        'the customers were given back without hands': t_back is not None,
        'the longest pause in orders during the failback is under 60 s': worst is not None and worst < 60,
    }
    extra = {'fenced_after_s': (round(t_fenced) if t_fenced is not None else None), 'orders_back_after_s': orders_back,
             'both_normal_after_host_back_s': t_back, 'longest_pause_during_failback_s': round(worst, 1) if worst else None,
             'laptop_cellwatch': lib.laptop_cellwatch_log(14), 'phone_cellwatch': lib.phone_cellwatch_log(14)}
    return _finish(name, tl, load, extra, checks, cell)


def both_offline():
    """The home internet drops: both cells' addresses are silent for 3 minutes, then back. Both fence, neither takes the other over,
    and they unfence by themselves soon after (not minutes later)."""
    name = 'both-offline'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('a', 6, 'bo')
    load.start()
    time.sleep(45)
    lib.freeze_phone_web(True)
    docker('pause', 'sprout-laptop-web-1')
    t_off = now()
    say('both addresses silent for 180 s')
    time.sleep(180)
    lib.freeze_phone_web(False)
    docker('unpause', 'sprout-laptop-web-1')
    t_on = now()
    t_normal = wait_states(lambda a, b: (a, b) == ('NORMAL', 'NORMAL'), 600)
    time.sleep(30)
    took_over = any(a in ('HOLDING', 'TAKEN_OVER', 'TAKING_OVER') or b in ('HOLDING', 'TAKEN_OVER', 'TAKING_OVER') for t, a, b in tl.rows)
    checks = {'nobody took anybody over': not took_over,
              'both unfenced within 90 s of the addresses coming back': t_normal is not None and t_normal <= 90}
    return _finish(name, tl, load, {'both_normal_after_addresses_back_s': t_normal}, checks, 'a')


def mutual_blind():
    """Neither cell can see the other at all (both paths), but both reach the witness, which sees both alive: nobody takes
    anybody over, nobody fences, orders never stop."""
    name = 'mutual-blind'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('a', 6, 'mb')
    load.start()
    time.sleep(45)
    t_fault = now() - tl.t0
    partition(laptop='all', phone_side='all')
    say('both cells completely blind to each other, the witness intact, for 330 s')
    time.sleep(330)
    heal()
    time.sleep(60)
    ok_states = all(a == 'NORMAL' and b == 'NORMAL' for t, a, b in tl.rows if t >= t_fault)
    gaps = sorted(y['at'] - x['at'] for x, y in zip(load.acked, load.acked[1:]))
    checks = {'both cells stayed NORMAL throughout': ok_states, 'no gap in the orders longer than 30 s': (gaps[-1] if gaps else 0) < 30}
    return _finish(name, tl, load, {'longest_gap_between_acknowledged_orders_s': round(gaps[-1], 1) if gaps else None}, checks, 'a')


def blind_no_witness():
    """Neither cell can see the other, and neither can reach the witness (the case before there was one): each may think the other is
    lost; whatever happens, exactly one ends up serving each cell's customers, nothing is lost, and the cells sort themselves out."""
    name = 'blind-no-witness'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('a', 6, 'bnw')
    load.start()
    time.sleep(45)
    partition(laptop='everything', phone_side='everything')
    say('both cells blind to each other and to the witness for 330 s')
    time.sleep(330)
    heal()
    t_normal = wait_states(lambda a, b: (a, b) == ('NORMAL', 'NORMAL'), 1200)
    time.sleep(30)
    checks = {'both cells are NORMAL again without hands': t_normal is not None}
    return _finish(name, tl, load, {'both_normal_after_heal_s': t_normal}, checks, 'a')


def failed_takeover():
    """The takeover cannot start its standby: it rolls back, and the replication it paused is on again."""
    name = 'failed-takeover'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('a', 4, 'ft')
    load.start()
    docker('rm', '-f', 'sprout-laptop-standby-1')
    time.sleep(30)
    partition(laptop='everything')
    say('the laptop cannot see the phone or the witness and has no standby to take it over with')
    time.sleep(200)
    log = chr(10).join(lib.laptop_cellwatch_log(40))
    heal()
    sub = lib.laptop_psql('sprout_a', "select subenabled from pg_subscription where subname='from_a'")
    # put the standby back for the next scenario
    docker('compose', '--env-file', str(lib.LAPTOP_DATA / '.env'), '-f', str(lib.ROOT / 'deploy/laptop/docker-compose.yml'), '--profile', 'standby',
           'up', '--no-start', 'standby')
    time.sleep(20)
    checks = {'the failed takeover was rolled back': 'taking cell a over failed' in log,
              'the replication it paused is enabled again': sub.strip() == 't',
              'neither cell left NORMAL for good': states() == ('NORMAL', 'NORMAL')}
    return _finish(name, tl, load, {'subscription_enabled': sub}, checks, 'a')


def kill_cell(cell='a'):
    """A whole cell is lost (its services stopped). The other takes over; when it is back, the customers are given back."""
    name = f'kill-cell-{cell}'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load(cell, 6, 'kc')
    load.start()
    time.sleep(60)
    t_fault = now()
    if cell == 'a':
        lib.phone('sh ~/sprout/ctl.sh stop sprout')
    else:
        docker('stop', *[f'sprout-laptop-{s}-1' for s in ('edge', 'trading', 'money', 'street', 'web', 'front', 'cellwatch', 'cloudflared')])
    say(f'cell {cell.upper()} stopped')
    t_hold = wait_states(lambda a, b: (a.startswith('HOLDING') if cell == 'b' else b.startswith('HOLDING')), 900)
    orders_back = first_order_after(load, t_fault)
    time.sleep(20)
    if cell == 'a':
        lib.phone('sh ~/sprout/ctl.sh start sprout')
    else:
        docker('start', *[f'sprout-laptop-{s}-1' for s in ('edge', 'trading', 'money', 'street', 'web', 'front', 'cellwatch', 'cloudflared')])
    t_back = wait_states(lambda a, b: (a, b) == ('NORMAL', 'NORMAL'), 1500)
    time.sleep(30)
    checks = {'orders worked again within 6 minutes': orders_back is not None and orders_back <= 360,
              'the customers were given back without hands': t_back is not None}
    return _finish(name, tl, load, {'orders_back_after_s': orders_back, 'both_normal_after_restart_s': t_back}, checks, cell)


def holder_dies():
    """The cell holding another cell's customers dies too. The cell it held, once healthy again, resumes after a few minutes from its
    own database, replays the writes the holder journalled with it (so nothing the customers were told succeeded is lost), takes the
    dead holder over, and when the holder returns it gives way and the customers are handed back."""
    name = 'holder-dies'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('b', 6, 'hd')
    load.start()
    time.sleep(45)
    docker('stop', 'sprout-laptop-trading-1')
    t_hold = wait_states(lambda a, b: a.startswith('HOLDING'), 400)
    say(f'the phone holds cell B after {t_hold}s; its customers keep ordering there for 60 s')
    time.sleep(60)
    docker('start', 'sprout-laptop-trading-1')      # cell B is healthy again, but fenced and waiting to be given its customers back
    lib.phone('sh ~/sprout/ctl.sh stop sprout')     # ... and the holder dies
    t_dead = now()
    say('the phone (holding cell B) is stopped')
    t_resume = wait_states(lambda a, b: b == 'NORMAL' or b.startswith('HOLDING'), 900)
    orders_back = first_order_after(load, t_dead)
    say(f'cell B resumed after {t_resume}s; orders back after {orders_back}s')
    time.sleep(60)
    lib.phone('sh ~/sprout/ctl.sh start sprout')
    t_back = wait_states(lambda a, b: (a, b) == ('NORMAL', 'NORMAL'), 1800)
    time.sleep(45)
    checks = {'cell B resumed by itself within 10 minutes': t_resume is not None and t_resume <= 600,
              'the cells sorted themselves out when the phone returned': t_back is not None}
    return _finish(name, tl, load, {'orders_back_after_holder_died_s': orders_back, 'both_normal_after_phone_restart_s': t_back,
                                     'laptop_cellwatch': lib.laptop_cellwatch_log(16)}, checks, 'b')


def replication_off():
    """Replication of a cell into its copy is switched off silently (as a stalled subscription would be). The watcher turns it back
    on, says so, and the copy catches up with every order placed in the meantime."""
    name = 'replication-off'
    assert ensure_clean(), 'the cells are not clean'
    tl, load = Timeline(name).start(), Load('a', 4, 'ro')
    load.start()
    time.sleep(30)
    lib.laptop_psql('sprout_a', 'ALTER SUBSCRIPTION from_a DISABLE')
    t0 = now()
    say('the laptop replication of cell A switched off')
    t_on = None
    while now() - t0 < 180:
        if lib.laptop_psql('sprout_a', "select subenabled from pg_subscription where subname='from_a'").strip() == 't':
            t_on = round(now() - t0)
            break
        time.sleep(3)
    time.sleep(45)
    load.stop()
    time.sleep(30)
    keys = [x['key'] for x in load.acked]
    q = "('" + "','".join(keys) + "')"
    in_copy = int(lib.laptop_psql('sprout_a', f"select count(*) from oms.orders where idempotency_key in {q}") or 0)
    said = any('replication was disabled' in l or 'replication was off' in l for l in lib.laptop_cellwatch_log(200))
    checks = {'the watcher switched it back on within 90 s': t_on is not None and t_on <= 90,
              'it said so': said,
              'the copy has every order placed meanwhile': in_copy == len(keys)}
    extra = {'switched_back_on_after_s': t_on, 'orders_in_the_copy': in_copy, 'orders_acknowledged': len(keys)}
    result = dict(extra, scenario=name, timeline=tl.changes(), checks=checks)
    result['pass'] = all(checks.values())
    tl.stop()
    return record(name, result)


SCENARIOS = {'replication_off': replication_off, 'holder_dies': holder_dies, 'cf_blind': cf_blind, 'dead_host': dead_host, 'both_offline': both_offline, 'mutual_blind': mutual_blind, 'blind_no_witness': blind_no_witness,
             'failed_takeover': failed_takeover, 'kill_cell_a': lambda: kill_cell('a'), 'kill_cell_b': lambda: kill_cell('b')}
