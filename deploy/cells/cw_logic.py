"""The decisions cellwatch makes (ADR-027), as pure functions: no network, no clock, no database. Each rule was written
for something that went wrong, and test_cw_logic.py replays each of those cases.

A cell is in one of these states:

  NORMAL       serving its own customers
  FENCED       takes no customer writes: it cannot be reached, or its own services are down
  TAKING_OVER  promoting its copy of the other cell and starting that cell's services (a worker is running)
  HOLDING      serving the other cell's customers from the promoted copy
  TAKEN_OVER   the other cell holds this one's customers: fenced, forwarding, waiting to be given them back
  (FAILING_BACK and HANDING_BACK are the two halves of giving them back: see cw_failback.py)
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Decision:
    action: str                   # FENCE, UNFENCE, TAKEN_OVER, TAKEOVER, YIELD, FAILBACK, RESUME, RESUME_STALE
    reason: str = ''
    declared_down: bool = False   # FENCE only: this cell says it is out because a host of its own is down


@dataclass
class Cfg:
    cell: str = 'a'
    peer: str = 'b'
    preferred: str = 'b'          # when both took each other over, this cell keeps what it took
    fence_after: int = 60         # own public address unreachable
    host_down_fence_after: int = 60   # a host of this cell refusing connections (a crash restarts in about 30 s)
    sick_fence_after: int = 300   # answering, but unhealthy
    takeover_after: int = 120     # the other cell's address silent
    sick_takeover_after: int = 600    # the other cell answers but cannot serve
    declared_takeover_after: int = 30  # the other cell has said it is out
    unfence_after: int = 210      # healthy this long, whatever the other cell says (it needs this long to decide)
    unfence_fast_after: int = 30  # ... or this long when the other cell reports it sees this one healthy
    peer_sees_me_for: int = 15
    failback_stable_after: int = 180  # healthy this long before the cell asks for its customers back
    resume_after: int = 300       # the cell holding this one's customers has been gone this long: serve them from here
    lease_after: int = 90         # the witness has not heard from the other cell this long: its lease has lapsed (30 s took a mobile blip for a death)
    flap_count: int = 3
    flap_window: int = 600


@dataclass
class PeerView:
    """What this cell knows of the other from one vantage point (through Cloudflare, or over the LAN)."""
    fresh: bool = False           # its status answered and is recent
    state: str = ''
    healthy: bool = False
    holding: Optional[str] = None
    declared_down: bool = False   # it fenced itself because one of its own hosts is down
    peer_ok_for: float = 0        # how long it has been seeing THIS cell's status (whatever state this cell is in)
    fb: Optional[dict] = None     # its failback progress
    fb_ready: bool = False        # holding, with what a handback needs prepared
    at: float = 0                 # when it published this status (its clock, as a timestamp)
    resumed_at: float = 0         # when it resumed serving its own customers because the cell holding them was gone


@dataclass
class WitView:
    """What the witness (a Worker outside both cells) says of the other cell."""
    reachable: bool = False       # it answered recently
    seen: bool = False            # it has heard from the other cell at least once
    age: float = 0                # seconds since it last did
    state: str = ''
    healthy: bool = False
    declared_down: bool = False


@dataclass
class Obs:
    addr_down_for: float = 0      # this cell's own public address
    sick_for: float = 0           # its own health check failing
    hosts_down: dict = field(default_factory=dict)   # host -> seconds, for the hosts refusing connections now
    flapping: bool = False
    declared: bool = False        # this cell, fenced, has already said it is out
    good_for: float = 0           # address, health check and every host fine, continuously
    cf: PeerView = field(default_factory=PeerView)
    lan: PeerView = field(default_factory=PeerView)
    wit: WitView = field(default_factory=WitView)
    peer_gone_for: float = 0      # the other cell's status unreachable through Cloudflare
    peer_bad_for: float = 0       # ... or answering, but neither healthy nor serving
    peer_declared_for: float = 0
    peer_seen: bool = False       # it has been seen working at least once (a cell not set up yet is never "lost")
    retry_wait: bool = False      # a recent attempt failed: wait
    takeover_can_abort: bool = False
    normal_at: float = 0          # when this cell last became NORMAL
    gave_back_recently: bool = False   # it has just taken its customers back from the other cell
    holding_since: float = 0      # when this cell started taking the other cell over


# the other cell's clock may be ahead of this one's (the phone's runs about 9 s ahead of the laptop's), and its status is published every
# 10 s: a claim has to be this much newer than this cell's becoming NORMAL to count
CLAIM_MARGIN = 20


def peer_holds_me(o: Obs, c: Cfg) -> bool:
    """The other cell says it holds this one's customers, in a status published after this cell last became NORMAL: right
    after a failback the holder's last status (up to 90 s old) still says it holds them, and means nothing now."""
    return any(v.fresh and v.holding == c.cell and v.at > o.normal_at + CLAIM_MARGIN for v in (o.cf, o.lan))


def lan_vetoes(o: Obs) -> bool:
    """The LAN shows the other cell up and well: a silent Cloudflare address then means Cloudflare, not the cell."""
    v = o.lan
    return v.fresh and v.healthy and v.state in ('NORMAL', 'HOLDING') and not v.declared_down


def peer_lost(o: Obs, c: Cfg) -> Optional[str]:
    """Why the other cell counts as lost, or None."""
    if o.peer_declared_for >= c.declared_takeover_after:
        return 'it has said it is out'          # it fenced itself: it takes no writes, whatever the LAN shows
    if lan_vetoes(o):
        return None
    w = o.wit
    if w.reachable and w.seen:
        if w.age < c.lease_after and w.healthy and w.state in ('NORMAL', 'HOLDING') and not w.declared_down:
            return None                         # neither of our paths sees it, but the witness does: it is alive
        if w.age >= c.lease_after:
            return 'its lease at the witness has lapsed'
    if o.peer_gone_for >= c.takeover_after:
        return 'its address is silent'
    if o.peer_bad_for >= c.sick_takeover_after:
        return 'it answers but cannot serve'
    return None


def flapping(flaps: dict, c: Cfg) -> bool:
    """One host came back from being down `flap_count` times in `flap_window` (host -> the times it came back, kept for the window).
    Counted per host: after Docker starts, every host comes up within a minute of the others, and on 2026-10-28 five hosts starting
    together counted as one host crashing five times; the cell fenced itself, said it was out, and was taken over again."""
    return any(len(times) >= c.flap_count for times in flaps.values())


def peer_taking_me(o: Obs) -> bool:
    """The other cell is promoting its copy of this one: it has stopped replicating from here, so a write taken here now would be
    missing from the copy that will serve this cell's customers."""
    return any(v.fresh and v.state == 'TAKING_OVER' for v in (o.cf, o.lan))


def fence_reason(o: Obs, c: Cfg) -> Optional[tuple]:
    """(why, declared_down): why this cell must stop taking writes."""
    if o.hosts_down:
        worst = max(o.hosts_down.values())
        if worst >= c.host_down_fence_after:
            return ('host down: ' + ', '.join(sorted(o.hosts_down)), True)
    if o.flapping:
        return ('a host keeps crashing', True)
    if o.addr_down_for >= c.fence_after:
        return ('its address is unreachable', False)
    if o.sick_for >= c.sick_fence_after:
        return ('its services are failing', False)
    if peer_taking_me(o):
        return ('the other cell is taking this one over', False)
    return None


def may_unfence(o: Obs, c: Cfg) -> Optional[str]:
    if peer_taking_me(o):
        return None     # 2026-10-28: unfenced while the other cell took it over, and both served its customers for 100 s
    if o.good_for >= c.unfence_after:
        return f'healthy for {c.unfence_after} s'
    if o.good_for >= c.unfence_fast_after:
        for v in (o.cf, o.lan):
            # a NORMAL or a FENCED cell sees this one (a fenced cell takes nobody over): both fenced after a shared outage would
            # otherwise each wait for the other to be NORMAL
            if v.fresh and v.state in ('NORMAL', 'FENCED') and v.peer_ok_for >= c.peer_sees_me_for and not v.holding:
                return 'the other cell sees it, and is neither holding nor taking it over'
    return None


def should_rebuild_copy(state: str, missing_for: float, peer_seen: bool, peer_ok: bool, retry_wait: bool, grace: int = 60) -> bool:
    """This cell's copy of the other cell's database is certainly missing (not merely unreadable): make it again. Only while this cell
    serves its own customers (or is fenced), only when the other cell is well enough to copy from, and only once the copy has been
    missing for a while and no attempt failed lately."""
    return state in ('NORMAL', 'FENCED') and missing_for >= grace and peer_seen and peer_ok and not retry_wait


def decide(state: str, o: Obs, c: Cfg) -> Optional[Decision]:
    """The one thing to do now, or None."""
    held = peer_holds_me(o, c)
    if state == 'NORMAL':
        if held:
            return Decision('TAKEN_OVER', 'the other cell holds this one: it was taken over while it looked lost')
        f = fence_reason(o, c)
        if f:
            return Decision('FENCE', f[0], f[1])
        why = peer_lost(o, c)
        if why and o.peer_seen and not o.retry_wait and o.good_for > 0:
            return Decision('TAKEOVER', why)
        return None
    if state == 'FENCED':
        if held:
            return Decision('TAKEN_OVER', 'the other cell holds this one')
        f = fence_reason(o, c)
        if f and f[1] and not o.declared:
            # 2026-10-29: fenced because its address went silent, then every host stayed down while cellwatch kept beating; it never
            # said it was out, so the witness (lease live) never let the other cell take its customers
            return Decision('FENCE', f[0], True)
        why = may_unfence(o, c)
        if why and not o.hosts_down and not o.flapping:
            return Decision('UNFENCE', why)
        return None
    if state in ('TAKING_OVER', 'HOLDING'):
        if held and c.cell != c.preferred:
            return Decision('YIELD', 'both cells took each other over, and the other one keeps its takeover')
        for v in (o.cf, o.lan):
            if v.fresh and v.state == 'NORMAL' and v.healthy and v.resumed_at and v.resumed_at > o.holding_since:
                return Decision('YIELD', 'the other cell has resumed serving its own customers: its database has them all')
        return None
    if state == 'TAKEN_OVER':
        v = o.cf if o.cf.fresh else o.lan
        if o.gave_back_recently and v.fresh and v.state == 'NORMAL' and not v.holding and o.good_for >= 20:
            return Decision('RESUME', 'the customers were given back, and the other cell no longer holds them')
        if o.peer_gone_for >= c.resume_after and not lan_vetoes(o) and o.good_for >= 60 and not o.retry_wait:
            return Decision('RESUME_STALE', 'the cell holding this one has been gone for a while: serving from here, and replaying what it journalled here')
        if (o.good_for >= c.failback_stable_after and not o.retry_wait and v.fresh and v.state == 'HOLDING'
                and v.holding == c.cell and v.healthy and v.fb_ready):
            return Decision('FAILBACK', 'healthy and stable: the other cell can give its customers back')
        return None
    return None
