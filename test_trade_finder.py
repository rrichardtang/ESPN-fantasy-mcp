"""Tests the trade finder's lineup math and search on small made-up rosters. Run: pytest"""

import json

from trade_finder import (
    Player,
    adjusted,
    find_trades,
    lineup_points,
    load_adjustments,
    per_game,
    season_points,
    season_weeks,
    tradeable,
)

SLOTS = {"QB": 1, "RB": 1, "WR": 1, "RB/WR/TE": 1, "BE": 3, "IR": 1}


def test_lineup_fills_flex_with_the_best_leftover_player():
    roster = [Player("Q", "QB", 300), Player("R1", "RB", 200), Player("R2", "RB", 150), Player("W", "WR", 100)]
    assert lineup_points(roster, SLOTS) == 300 + 200 + 100 + 150


def test_players_no_better_than_a_free_agent_are_not_tradeable():
    waiver = [Player("FA", "WR", 120)]
    assert tradeable([Player("W1", "WR", 150), Player("W2", "WR", 110)], waiver) == [Player("W1", "WR", 150)]


def test_two_for_one_consolidation_can_help_both_teams():
    # I have three good RBs and a weak WR. They have a star WR, WR depth and no RB better than a free agent.
    me = [Player("Q", "QB", 300), Player("R1", "RB", 200), Player("R2", "RB", 190), Player("R3", "RB", 180),
          Player("W", "WR", 90)]
    them = [Player("Q2", "QB", 290), Player("Star", "WR", 250), Player("W2", "WR", 140), Player("W3", "WR", 130),
            Player("Rx", "RB", 60)]
    free_agents = [Player("FA-RB", "RB", 80), Player("FA-WR", "WR", 80)]

    best = find_trades(me, [("Them", them)], free_agents, SLOTS)[0]

    assert (best.give, best.get) == ((Player("R2", "RB", 190), Player("R3", "RB", 180)), (Player("Star", "WR", 250),))
    # Me: Star takes the WR slot and W moves to flex in place of R2: 840 - 780.
    assert best.my_gain == (300 + 200 + 250 + 90) - (300 + 200 + 90 + 190)
    # Them: R2 and R3 replace the free-agent RB and the star: 800 - 760.
    assert best.their_gain == (290 + 190 + 140 + 180) - (290 + 80 + 250 + 140)


def test_both_teams_must_gain_unless_told_otherwise():
    me = [Player("Q", "QB", 300), Player("R", "RB", 100), Player("W", "WR", 100), Player("W2", "WR", 90)]
    them = [Player("Q2", "QB", 300), Player("R2", "RB", 200), Player("W3", "WR", 200), Player("W4", "WR", 190)]
    assert all(t.their_gain > 0 for t in find_trades(me, [("Them", them)], [], SLOTS))
    assert any(t.their_gain < 0 for t in find_trades(me, [("Them", them)], [], SLOTS, min_their_gain=-1000))


def test_throw_ins_that_change_nothing_are_left_out():
    me = [Player("Q", "QB", 300), Player("R1", "RB", 200), Player("R2", "RB", 190), Player("R3", "RB", 180),
          Player("W", "WR", 90), Player("Junk", "TE", 50)]
    them = [Player("Q2", "QB", 290), Player("Star", "WR", 250), Player("W2", "WR", 140), Player("Rx", "RB", 95)]
    trades = find_trades(me, [("Them", them)], [], SLOTS, min_their_gain=-1000)
    assert not any(Player("Junk", "TE", 50) in t.give and len(t.give) == 2 for t in trades)


def test_rb_wr_and_wr_te_flex_slots_share_wide_receivers_correctly():
    roster = [Player("W", "WR", 100), Player("R", "RB", 90), Player("T", "TE", 10)]
    assert lineup_points(roster, {"RB/WR": 1, "WR/TE": 1}) == 190
    assert lineup_points(roster, {"WR/TE": 1, "RB/WR": 1}) == 190


def test_defensive_group_slots_take_their_positions():
    roster = [Player("E", "DE", 50), Player("T", "DT", 40), Player("C", "CB", 30), Player("L", "LB", 20)]
    assert lineup_points(roster, {"DL": 1, "DP": 1}) == 50 + 40
    assert lineup_points(roster, {"DB": 1, "DP": 1}) == 30 + 50


def test_teams_with_the_same_name_are_both_searched():
    me = [Player("Q", "QB", 300), Player("R", "RB", 100), Player("W", "WR", 100), Player("W2", "WR", 90)]
    a = [Player("Q2", "QB", 300), Player("R2", "RB", 200), Player("W3", "WR", 200), Player("W4", "WR", 190)]
    b = [Player("Q3", "QB", 300), Player("R3", "RB", 210), Player("W5", "WR", 205), Player("W6", "WR", 195)]
    trades = find_trades(me, [("Same", a), ("Same", b)], [], SLOTS, min_their_gain=-1000)
    assert any(set(t.get) <= set(a) for t in trades) and any(set(t.get) <= set(b) for t in trades)


TWO_RB = {"RB": 2}
WEEKS = ((5, 1.0), (6, 1.0))


def test_two_starters_sharing_a_bye_score_lower_than_different_byes():
    shared = [Player("A", "RB", 10, bye_week=5), Player("B", "RB", 10, bye_week=5)]
    split = [Player("A", "RB", 10, bye_week=5), Player("B", "RB", 10, bye_week=6)]
    assert season_points(shared, TWO_RB, WEEKS) == (20, 0)
    assert season_points(split, TWO_RB, WEEKS) == (20, 10)


def test_playoff_weeks_count_more():
    periods = {"1": [13], "2": [14], "3": [15, 16]}
    assert season_weeks(13, periods, reg_season_count=2) == ((13, 1.0), (14, 1.0), (15, 1.25), (16, 1.25))
    assert season_points([Player("A", "RB", 10)], {"RB": 1}, ((14, 1.0), (15, 1.25))) == (22.5, 10)


def test_a_bench_player_covering_a_bye_earns_value():
    starters = [Player("A", "RB", 10, bye_week=5), Player("B", "RB", 10)]
    bench = Player("C", "RB", 4)
    assert season_points([*starters, bench], TWO_RB, WEEKS)[0] - season_points(starters, TWO_RB, WEEKS)[0] == 4


def test_adjustment_multiplier_is_clamped_and_out_through_week_removes_a_player():
    star = Player("A", "RB", 10)
    assert adjusted(star, {"multiplier": 2.0}).points == 12
    assert adjusted(star, {"multiplier": 0.1}).points == 8
    out = adjusted(star, {"out_through_week": 5})
    assert season_points([out], {"RB": 1}, WEEKS) == (10, 0)


def test_worst_week_change_shows_a_trade_that_creates_a_bye_hole():
    me = [Player("A", "RB", 10, bye_week=5), Player("B", "RB", 10, bye_week=6)]
    them = [Player("C", "RB", 11, bye_week=5), Player("D", "RB", 1)]
    trade = find_trades(me, [("Them", them)], [], TWO_RB, min_their_gain=-1000, sizes=((1, 1),), weeks=WEEKS)
    hole = next(t for t in trade if t.give == (me[1],) and t.get == (them[0],))
    assert (hole.my_gain, hole.my_worst_week_change) == (1, -10)


def test_per_game_skips_a_bye_only_when_it_is_still_ahead():
    assert per_game(130, bye_week=3, week=6) == 10  # 13 games, weeks 6-18
    assert per_game(120, bye_week=6, week=6) == 10
    assert per_game(120, bye_week=10, week=6) == 10
    assert per_game(0, bye_week=None, week=19) == 0


def test_per_game_spreads_points_over_games_after_an_injury():
    assert per_game(90, bye_week=None, week=6, out_through_week=9) == 10  # plays weeks 10-18
    assert per_game(80, bye_week=12, week=6, out_through_week=9) == 10
    assert per_game(90, bye_week=8, week=6, out_through_week=9) == 10


def test_null_adjustment_values_are_ignored():
    star = Player("A", "RB", 10)
    assert adjusted(star, {"multiplier": None, "out_through_week": None}) == star
    assert adjusted(star, {"multiplier": "1.1", "out_through_week": "6"}) == Player("A", "RB", 11, out_through_week=6)


def test_an_adjustment_for_an_unknown_player_warns(tmp_path, capsys):
    path = tmp_path / "adjustments.json"
    path.write_text(json.dumps({"A": {"multiplier": 1.1}, "Ghost": {}}))
    assert load_adjustments(str(path), ["A", "B"]).keys() == {"A", "Ghost"}
    assert capsys.readouterr().err == "Adjustment for unknown player ignored: Ghost\n"
