"""Tests the waiver finder's move scoring on small made-up rosters. Run: pytest"""

from types import SimpleNamespace

from trade_finder import Player, replacement
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
    assert [(m[0], m[2]) for m in best_moves(gains, gains, [0] * 4)] == [(0, 50)]


def test_this_week_ties_pick_the_drop_with_the_smaller_rest_of_season_cost():
    week = {(0, 1): 5.0, (0, 2): 5.0, (1, 1): -1.0}
    ros = {(0, 1): -40.0, (0, 2): -10.0, (1, 1): 3.0}
    assert best_moves(week, ros, [0] * 3) == [(0, 2, 5.0, -10.0)]


def test_an_ir_player_lowers_a_pickups_gain_and_is_never_dropped():
    injured = Player("Hurt", "RB", 240)
    gains = move_gains(ROSTER, [STAR], SLOTS, limit=4, ir=[injured])
    assert gains == {(0, d): g for d, g in zip(range(4), [40 + 250 - 540, 10, 10, 10])}


def test_a_missing_weekly_projection_counts_as_zero():
    bye = SimpleNamespace(name="Q", position="QB", stats={})
    assert _weekly([bye], 5)[0].points == 0.0


def test_a_kicker_bye_is_covered_by_streaming_so_only_a_better_kicker_gains():
    butker = Player("Butker", "K", 9, bye_week=5)
    better, similar, other = Player("Better", "K", 12), Player("Similar", "K", 8.5), Player("Other", "K", 8.3)
    free_agents = [better, similar, other]
    weeks = ((5, 1.0), (6, 1.0))
    gains = move_gains([butker], free_agents, {"K": 1}, limit=2, weeks=weeks, waiver=replacement(free_agents))
    assert gains == {(0, None): 24 - (8.5 + 9), (1, None): 0, (2, None): 0}
    assert move_gains([butker], [similar], {"K": 1}, limit=2, weeks=weeks, waiver=[similar, other]) == {(0, None): 0.2}


def test_free_drops_pick_the_lowest_projected_player():
    gains = {(0, 0): 5.0, (0, 1): 5.0}
    assert best_moves(gains, gains, [125.0, 0.0]) == [(0, 1, 5.0, 5.0)]
    assert best_moves(gains, gains, [0.0, 125.0]) == [(0, 0, 5.0, 5.0)]
