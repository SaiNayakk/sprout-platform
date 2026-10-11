"""Every rule of cw_logic.py against the incident that taught it.   python -m unittest deploy/cells/test_cw_logic.py"""
import unittest

from cw_logic import Cfg, Obs, PeerView, decide, peer_holds_me, peer_lost

A = Cfg(cell='a', peer='b', preferred='b')
B = Cfg(cell='b', peer='a', preferred='b')


def alive(state='NORMAL', **kw):
    return PeerView(fresh=True, state=state, healthy=True, **dict({'at': 1000}, **kw))


def act(state, o, c=A):
    d = decide(state, o, c)
    return d.action if d else None


class Fencing(unittest.TestCase):
    def test_own_address_silent_fences_after_a_minute_not_before(self):
        self.assertIsNone(act('NORMAL', Obs(addr_down_for=59, peer_seen=True)))
        self.assertEqual(act('NORMAL', Obs(addr_down_for=60)), 'FENCE')

    def test_a_crashing_host_restarts_itself_in_30_s_and_is_not_a_failure(self):
        self.assertIsNone(act('NORMAL', Obs(hosts_down={'trading': 27})))

    def test_a_host_that_stays_down_fences_the_cell_and_says_why(self):
        d = decide('NORMAL', Obs(hosts_down={'trading': 61}), A)
        self.assertEqual((d.action, d.declared_down), ('FENCE', True))
        self.assertIn('trading', d.reason)

    def test_a_host_that_keeps_crashing_counts_as_down(self):
        self.assertEqual(act('NORMAL', Obs(flapping=True)), 'FENCE')

    def test_slow_but_answering_waits_five_minutes(self):
        self.assertIsNone(act('NORMAL', Obs(sick_for=299)))
        self.assertEqual(act('NORMAL', Obs(sick_for=300)), 'FENCE')


class Takeover(unittest.TestCase):
    def test_a_silent_address_is_lost_after_two_minutes(self):
        self.assertIsNone(act('NORMAL', Obs(peer_gone_for=119, peer_seen=True, good_for=500)))
        self.assertEqual(act('NORMAL', Obs(peer_gone_for=120, peer_seen=True, good_for=500)), 'TAKEOVER')

    def test_never_seen_is_never_lost(self):
        self.assertIsNone(act('NORMAL', Obs(peer_gone_for=9999, peer_seen=False, good_for=500)))

    def test_a_sick_peer_that_still_answers_gets_ten_minutes(self):
        """2026-10-09: an overloaded cell was taken over at two minutes while it served."""
        self.assertIsNone(act('NORMAL', Obs(peer_bad_for=599, peer_seen=True, good_for=500)))
        self.assertEqual(act('NORMAL', Obs(peer_bad_for=600, peer_seen=True, good_for=500)), 'TAKEOVER')

    def test_a_peer_that_announced_it_is_out_is_taken_in_thirty_seconds(self):
        """Audit: a dead host took 13.5 minutes. The cell fences itself and says so; the other cell believes it."""
        self.assertEqual(act('NORMAL', Obs(peer_declared_for=30, peer_seen=True, good_for=500)), 'TAKEOVER')

    def test_the_lan_showing_the_peer_well_stops_a_takeover_that_cloudflare_asks_for(self):
        """The cells cannot see each other through Cloudflare, but the LAN shows both up: nobody takes anybody."""
        o = Obs(peer_gone_for=999, peer_seen=True, good_for=500, lan=alive('NORMAL'))
        self.assertIsNone(act('NORMAL', o))

    def test_the_lan_cannot_override_a_peer_that_declared_itself_out(self):
        o = Obs(peer_declared_for=40, peer_seen=True, good_for=500, lan=alive('FENCED'))
        self.assertEqual(act('NORMAL', o), 'TAKEOVER')

    def test_a_cell_that_is_not_healthy_itself_takes_nobody_over(self):
        self.assertIsNone(act('NORMAL', Obs(peer_gone_for=999, peer_seen=True, good_for=0)))

    def test_a_failed_attempt_waits(self):
        self.assertIsNone(act('NORMAL', Obs(peer_gone_for=999, peer_seen=True, good_for=500, retry_wait=True)))


class ReturningCell(unittest.TestCase):
    def test_2026_10_09_a_fenced_cell_must_not_unfence_before_the_takeover_finishes(self):
        """The phone unfenced after 65 s healthy, while the laptop was 40 s from holding it."""
        o = Obs(good_for=65, cf=alive('NORMAL', peer_ok_for=0))
        self.assertIsNone(act('FENCED', o))

    def test_it_unfences_after_210_s_healthy(self):
        self.assertEqual(act('FENCED', Obs(good_for=210)), 'UNFENCE')

    def test_it_unfences_in_30_s_when_the_other_cell_reports_it_sees_it_healthy(self):
        """Audit: after both addresses were silent for 3 minutes, writes stayed refused for 3.5 minutes more."""
        o = Obs(good_for=30, cf=alive('NORMAL', peer_ok_for=20))
        self.assertEqual(act('FENCED', o), 'UNFENCE')

    def test_it_unfences_in_30_s_when_the_other_cell_is_fenced_too_and_sees_it(self):
        """Audit: both cells fenced after a shared outage waited 211 s, each for the other to be NORMAL."""
        o = Obs(good_for=30, cf=alive('FENCED', peer_ok_for=20))
        self.assertEqual(act('FENCED', o), 'UNFENCE')

    def test_but_not_while_the_other_cell_is_taking_it_over(self):
        o = Obs(good_for=30, cf=alive('TAKING_OVER', peer_ok_for=0))
        self.assertIsNone(act('FENCED', o))

    def test_a_fenced_cell_whose_host_is_still_down_never_unfences(self):
        self.assertIsNone(act('FENCED', Obs(good_for=999, hosts_down={'money': 5})))

    def test_a_cell_in_normal_that_finds_itself_held_fences_at_once(self):
        o = Obs(cf=alive('HOLDING', holding='a'))
        self.assertEqual(act('NORMAL', o), 'TAKEN_OVER')

    def test_held_is_seen_on_the_lan_too(self):
        o = Obs(lan=alive('HOLDING', holding='a'))
        self.assertEqual(act('NORMAL', o), 'TAKEN_OVER')

    def test_a_stale_status_is_not_believed(self):
        o = Obs(cf=PeerView(fresh=False, state='HOLDING', holding='a'))
        self.assertFalse(peer_holds_me(o, A))


class StaleClaims(unittest.TestCase):
    def test_after_a_failback_the_holders_last_status_means_nothing(self):
        """Found by the first automatic failback: B became NORMAL, read A's status from 14 s earlier (still 'holding b'),
        and fenced itself again."""
        o = Obs(normal_at=2000, cf=alive('HOLDING', holding='a', at=1990))
        self.assertIsNone(act('NORMAL', o))

    def test_a_claim_published_after_this_cell_became_normal_counts(self):
        """2026-10-09: the phone unfenced at 16:57:59 and the laptop said it held it at 16:58:27."""
        o = Obs(normal_at=2000, cf=alive('HOLDING', holding='a', at=2028))
        self.assertEqual(act('NORMAL', o), 'TAKEN_OVER')

    def test_a_cell_that_just_took_its_customers_back_resumes_when_the_holder_has_let_go(self):
        o = Obs(good_for=25, gave_back_recently=True, cf=alive('NORMAL'))
        self.assertEqual(act('TAKEN_OVER', o), 'RESUME')

    def test_but_not_if_the_holder_still_holds_them(self):
        o = Obs(good_for=25, gave_back_recently=True, cf=alive('HOLDING', holding='a'))
        self.assertIsNone(act('TAKEN_OVER', o))

    def test_and_not_a_cell_that_never_gave_back(self):
        o = Obs(good_for=999, gave_back_recently=False, cf=alive('NORMAL'))
        self.assertIsNone(act('TAKEN_OVER', o))


class HolderDies(unittest.TestCase):
    """Audit run 3: the phone, holding cell B's customers, went off the network; cell B stayed fenced with nobody serving them."""

    def test_a_taken_over_cell_resumes_when_its_holder_has_been_gone_five_minutes(self):
        o = Obs(peer_gone_for=301, good_for=120)
        self.assertEqual(act('TAKEN_OVER', o), 'RESUME_STALE')

    def test_not_before(self):
        self.assertIsNone(act('TAKEN_OVER', Obs(peer_gone_for=299, good_for=120)))

    def test_not_while_the_lan_still_shows_the_holder(self):
        self.assertIsNone(act('TAKEN_OVER', Obs(peer_gone_for=999, good_for=120, lan=alive('HOLDING', holding='a'))))

    def test_but_a_holder_whose_cellwatch_alone_survives_does_not_stop_it(self):
        """Audit: the phone's cellwatch outlived its services and answered over the LAN, saying it was not well."""
        sick = PeerView(fresh=True, state='HOLDING', healthy=False, holding='a', at=1000)
        self.assertEqual(act('TAKEN_OVER', Obs(peer_gone_for=999, good_for=120, lan=sick)), 'RESUME_STALE')

    def test_not_while_this_cell_is_itself_unwell(self):
        self.assertIsNone(act('TAKEN_OVER', Obs(peer_gone_for=999, good_for=30)))

    def test_a_holder_that_returns_steps_down_when_the_cell_it_holds_has_resumed(self):
        o = Obs(holding_since=1000, cf=alive('NORMAL', resumed_at=1500))
        self.assertEqual(act('HOLDING', o, B), 'YIELD')       # whichever cell it is
        self.assertEqual(act('HOLDING', o, A), 'YIELD')

    def test_but_not_for_a_resume_older_than_its_hold(self):
        o = Obs(holding_since=2000, cf=alive('NORMAL', resumed_at=1500))
        self.assertIsNone(act('HOLDING', o, A))


class BothTookEachOther(unittest.TestCase):
    """Audit: with neither able to see the other, both took over and ended HOLDING each other for good."""

    def test_the_other_cell_yields_and_the_preferred_one_keeps_what_it_took(self):
        o = Obs(cf=alive('HOLDING', holding='a'))
        self.assertEqual(act('HOLDING', o, A), 'YIELD')       # the phone gives way
        self.assertIsNone(act('HOLDING', Obs(cf=alive('HOLDING', holding='b')), B))   # the laptop keeps

    def test_also_while_a_takeover_is_in_progress(self):
        self.assertEqual(act('TAKING_OVER', Obs(cf=alive('HOLDING', holding='a')), A), 'YIELD')


class Failback(unittest.TestCase):
    def holding(self, **kw):
        return alive('HOLDING', holding='a', fb_ready=True, **kw)

    def test_a_stable_healthy_cell_asks_for_its_customers_back(self):
        self.assertEqual(act('TAKEN_OVER', Obs(good_for=180, cf=self.holding())), 'FAILBACK')

    def test_not_before_it_has_been_stable(self):
        self.assertIsNone(act('TAKEN_OVER', Obs(good_for=179, cf=self.holding())))

    def test_not_until_the_holder_is_ready(self):
        v = alive('HOLDING', holding='a', fb_ready=False)
        self.assertIsNone(act('TAKEN_OVER', Obs(good_for=999, cf=v)))

    def test_not_after_a_failed_attempt(self):
        self.assertIsNone(act('TAKEN_OVER', Obs(good_for=999, cf=self.holding(), retry_wait=True)))

    def test_it_can_use_the_lan_when_cloudflare_is_silent(self):
        self.assertEqual(act('TAKEN_OVER', Obs(good_for=999, lan=self.holding())), 'FAILBACK')


class PeerLostReasons(unittest.TestCase):
    def test_reasons_are_named(self):
        self.assertEqual(peer_lost(Obs(peer_gone_for=130), A), 'its address is silent')
        self.assertEqual(peer_lost(Obs(peer_bad_for=700), A), 'it answers but cannot serve')
        self.assertIsNone(peer_lost(Obs(), A))


if __name__ == '__main__':
    unittest.main()
