"""Tests the waiver finder's move scoring on small made-up rosters. Run: pytest"""

from types import SimpleNamespace

from trade_finder import Player
from waiver_finder import _weekly, best_moves, move_gains

SLOTS = {"QB": 1, "RB": 1, "BE": 2, "IR": 1}
ROSTER = [Player("Q", "QB", 300), Player("R", "RB", 200), Player("Bench", "RB", 50), Player("Bench2", "QB", 40)]
STAR = Player("Star", "RB", 250)


def test_dropping_a_bench_player_costs_nothing():
    gains = move_gains(ROSTER, [STAR], SLOTS, limit=4)
    assert gains[0, 2] == gains[0, 3] == 50


def test_dropping_a_starter_is_charged():
    assert move_gains(ROSTER, [STAR], SLOTS, limit=4)[0, 0] == 250 + 40 - (300 + 200)


def test_an_open_roster_spot_needs_no_drop():
    assert move_gains(ROSTER, [STAR], SLOTS, limit=5) == {(0, None): 50}


def test_free_agents_that_do_not_help_are_left_out():
    gains = move_gains(ROSTER, [STAR, Player("Kicker", "K", 99)], SLOTS, limit=4)
    assert [(m[0], m[2]) for m in best_moves(gains, gains)] == [(0, 50)]


def test_this_week_ties_pick_the_drop_with_the_smaller_rest_of_season_cost():
    week = {(0, 1): 5.0, (0, 2): 5.0, (1, 1): -1.0}
    ros = {(0, 1): -40.0, (0, 2): -10.0, (1, 1): 3.0}
    assert best_moves(week, ros) == [(0, 2, 5.0, -10.0)]


def test_an_ir_player_lowers_a_pickups_gain_and_is_never_dropped():
    injured = Player("Hurt", "RB", 240)
    gains = move_gains(ROSTER, [STAR], SLOTS, limit=4, ir=[injured])
    assert gains == {(0, d): g for d, g in zip(range(4), [40 + 250 - 540, 10, 10, 10])}


def test_a_missing_weekly_projection_counts_as_zero():
    bye = SimpleNamespace(name="Q", position="QB", stats={})
    assert _weekly([bye], 5)[0].points == 0.0
