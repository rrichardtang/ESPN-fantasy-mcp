"""Tests the trade finder's lineup math and search on small made-up rosters. Run: pytest"""

from trade_finder import Player, find_trades, lineup_points, tradeable

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
