"""Tests the trade finder's lineup math and search on small made-up rosters. Run: pytest"""

import json
from dataclasses import replace
from types import SimpleNamespace

import server
from trade_finder import (
    Player,
    Trade,
    acceptance,
    adjusted,
    adjustment_lines,
    bench_candidates,
    best_ratio,
    cheapest_offer,
    find_targets,
    give_pool,
    lineup_points,
    load_adjustments,
    per_game,
    ranked,
    recent_points,
    report,
    scorer,
    season_points,
    season_weeks,
    target_lines,
    tradeable,
)

SLOTS = {"QB": 1, "RB": 1, "WR": 1, "RB/WR/TE": 1, "BE": 3, "IR": 1}


def test_lineup_fills_flex_with_the_best_leftover_player():
    roster = [Player("Q", "QB", 300), Player("R1", "RB", 200), Player("R2", "RB", 150), Player("W", "WR", 100)]
    assert lineup_points(roster, SLOTS) == 300 + 200 + 100 + 150


def test_players_no_better_than_a_free_agent_are_not_tradeable():
    waiver = [Player("FA", "WR", 120)]
    assert tradeable([Player("W1", "WR", 150), Player("W2", "WR", 110)], waiver) == [Player("W1", "WR", 150)]


def test_rb_wr_and_wr_te_flex_slots_share_wide_receivers_correctly():
    roster = [Player("W", "WR", 100), Player("R", "RB", 90), Player("T", "TE", 10)]
    assert lineup_points(roster, {"RB/WR": 1, "WR/TE": 1}) == 190
    assert lineup_points(roster, {"WR/TE": 1, "RB/WR": 1}) == 190


def test_defensive_group_slots_take_their_positions():
    roster = [Player("E", "DE", 50), Player("T", "DT", 40), Player("C", "CB", 30), Player("L", "LB", 20)]
    assert lineup_points(roster, {"DL": 1, "DP": 1}) == 50 + 40
    assert lineup_points(roster, {"DB": 1, "DP": 1}) == 30 + 50


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
    assert adjusted(star, {"multiplier": 0}).points == 8
    out = adjusted(star, {"out_through_week": 5})
    assert season_points([out], {"RB": 1}, WEEKS) == (10, 0)


def test_worst_week_change_shows_a_trade_that_creates_a_bye_hole():
    me = [Player("A", "RB", 10, bye_week=5), Player("B", "RB", 10, bye_week=6)]
    them = [Player("C", "RB", 11, bye_week=5), Player("D", "RB", 1)]
    hole = scorer(me, [], TWO_RB, WEEKS)("Them", them, (me[1],), (them[0],))
    assert (hole.my_gain, hole.my_worst_week_change, hole.my_cost) == (1, -10, 10)


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


def test_adjustments_load_from_a_file_and_print_as_applied(tmp_path):
    path = tmp_path / "adjustments.json"
    path.write_text(json.dumps({"A": {"multiplier": 1.5, "reason": "Lead back", "source": "espn.com, Oct 1"}}))
    adjustments = load_adjustments(str(path))
    assert adjustment_lines(adjustments)[1] == "  A: x1.2. Lead back (espn.com, Oct 1)"
    assert load_adjustments(None) == {} and adjustment_lines({}) == []


TARGET_SLOTS = {"QB": 1, "RB": 1, "WR": 2, "RB/WR/TE": 1, "BE": 5}
ANYTHING = acceptance(min_best_ratio=0, max_their_loss=1e9)
A, B, C = Player("A", "WR", 120), Player("B", "WR", 110), Player("C", "WR", 100)
ME = [Player("Q", "QB", 300), Player("R1", "RB", 200), Player("R2", "RB", 190), A, B, C]
T = Player("T", "WR", 240)
THEM = [Player("Q2", "QB", 290), Player("S1", "RB", 260), Player("S2", "WR", 255), T, Player("Rx", "RB", 60)]
FREE_AGENTS = [Player("FA-WR", "WR", 80), Player("FA-RB", "RB", 70)]


def targets(accept, me=ME, them=THEM, protect=2):
    score, pool = scorer(me, FREE_AGENTS, TARGET_SLOTS), give_pool(me, FREE_AGENTS)
    return find_targets(score, pool, [("Them", them)], accept, protect=protect)


def test_targets_skip_each_teams_top_three_and_show_at_most_two_per_target():
    them = [*THEM, Player("S3", "WR", 250)]
    trades = targets(ANYTHING, them=them, protect=3)
    assert ranked(them, ((1, 1.0),))[2].name == "S3" and {p for t in trades for p in t.get} == {T}
    assert len(trades) == 2


def test_my_top_two_and_kept_players_are_never_given():
    junk, kicker = Player("Junk", "WR", 79), Player("K", "K", 150)
    assert give_pool([*ME, junk, kicker], FREE_AGENTS, keep={"B"}) == [Player("Q", "QB", 300), A, C]


def test_three_for_one_fills_the_open_spot_with_a_streamer():
    best = scorer(ME, FREE_AGENTS, TARGET_SLOTS)("Them", THEM, (A, B, C), (T,))
    # Me: T and the best free-agent WR replace A and B: 1010 - 920. Them: A and B replace T and FA-WR: 1035 - 1125.
    assert (best.my_gain, best.their_gain, best.best_ratio) == (90, -90, 0.5)


def test_acceptance_needs_a_close_best_player_and_a_small_loss_for_them():
    accept = acceptance(min_best_ratio=0.75, max_their_loss=10)
    trade = Trade("Them", (A,), (T,), my_gain=5, their_gain=-10, my_worst_week_change=0, best_ratio=0.75, my_cost=0)
    assert accept(trade)
    assert not accept(replace(trade, best_ratio=0.74)) and not accept(replace(trade, their_gain=-11))
    assert targets(accept) == []  # A, worth half of T, is the best they would get


def test_a_target_no_better_for_me_than_my_bench_is_skipped():
    assert targets(ANYTHING, them=[*THEM[:3], Player("Meh", "WR", 70)]) == []


def test_a_tiny_loss_does_not_keep_my_lineup_whole_and_prints_as_zero():
    trade = Trade("Them", (A,), (T,), my_gain=-0.04, their_gain=-0.04, my_worst_week_change=0, best_ratio=1,
                  my_cost=0)
    score = lambda partner, roster, give, get: trade  # noqa: E731
    assert cheapest_offer(score, [A], SimpleNamespace(partner="Them", roster=(), player=T), ANYTHING) is None
    assert "-0.0" not in target_lines([trade])[-1]


def test_throw_ins_that_change_nothing_are_left_out():
    junk = Player("Junk", "QB", 10)
    trades = targets(ANYTHING, me=[*ME, junk])
    assert trades and not any(junk in t.give and len(t.give) > 1 for t in trades)


BENCH_TEAM = [
    Player("S1", "RB", 260, slot="RB"), Player("S2", "WR", 255, slot="WR"), Player("T", "WR", 240, slot="WR"),
    Player("Weak", "WR", 90, slot="RB/WR/TE"), Player("Bench", "WR", 120, slot="BE"),
    Player("Bench2", "RB", 100, slot="BE"), Player("Low", "WR", 60, slot="BE"),
    Player("Bye", "WR", 130, bye_week=1, slot="BE"), Player("K", "K", 150, slot="BE"),
]


def test_bench_candidates_are_every_playing_bench_player_beating_the_wire_by_team_then_points():
    others = [("Zed", BENCH_TEAM), ("Abe", [Player("Q3", "QB", 200, slot="BE")])]
    found = bench_candidates(others, FREE_AGENTS, {"Bench2": (3, 4)})
    assert [(c.partner, c.player.name, c.recent) for c in found] == [
        ("Abe", "Q3", ()), ("Zed", "Bench", ()), ("Zed", "Bench2", (3, 4))
    ]


def test_a_qb_barely_above_the_wire_does_not_push_out_a_rb_well_above_it(monkeypatch):
    monkeypatch.setattr("trade_finder.BENCH_SHOWN", 1)
    wire = [Player("FA-QB", "QB", 17), Player("FA-RB", "RB", 5)]
    team = [Player("Q", "QB", 18, slot="BE"), Player("R", "RB", 12, slot="BE")]
    assert [c.player.name for c in bench_candidates([("Them", team)], wire, {}, protect=0)] == ["R"]


def test_a_bench_player_out_for_the_season_is_no_candidate_and_zero_target_has_zero_ratio():
    out = Player("Out", "WR", 150, out_through_week=18, slot="BE")
    assert bench_candidates([("Them", [out])], FREE_AGENTS, {}, protect=0) == []
    assert best_ratio((A,), (replace(out, slot=""),), WEEKS) == 0.0


def test_recent_points_are_the_last_games_played_before_the_week():
    played = {"points": 5, "breakdown": {"210": 1}}
    stats = {0: played, 1: played, 2: {"points": 0, "breakdown": {}}, 3: {**played, "points": 12}, 4: played}
    assert recent_points(SimpleNamespace(stats=stats), week=4) == (5, 12)


def test_the_cheapest_bench_offer_gives_up_the_least_lineup_value():
    me = [Player("Q", "QB", 300), Player("R1", "RB", 200), Player("R2", "RB", 190), Player("W1", "WR", 150),
          Player("W0", "WR", 140), Player("W2", "WR", 125), Player("W3", "WR", 121)]
    bench = next(c for c in bench_candidates([("Them", BENCH_TEAM)], FREE_AGENTS, {}) if c.player.name == "Bench")
    score, pool = scorer(me, FREE_AGENTS, TARGET_SLOTS), give_pool(me, FREE_AGENTS)
    offer = cheapest_offer(score, pool, bench, acceptance())
    assert offer.give == (Player("W3", "WR", 121),) and offer.my_gain >= 0
    assert cheapest_offer(score, pool, bench, acceptance(min_best_ratio=2)) is None


def espn(name, position, points, slot, recent=()):
    stats = {16 + i: {"points": p, "breakdown": {"210": 1}} for i, p in enumerate(recent)}
    return SimpleNamespace(name=name, position=position, proTeam="ATL", projected_total_points=points,
                           lineupSlot=slot, playerId=name, percent_started=50.0, stats=stats)


def test_report_lists_every_player_in_the_rows_shown(monkeypatch):
    me = SimpleNamespace(team_name="Me", roster=[
        espn("Q", "QB", 300, "QB"), espn("R1", "RB", 260, "RB"), espn("W1", "WR", 240, "WR"),
        espn("A", "WR", 120, "WR"), espn("B", "WR", 110, "BE"), espn("C", "RB", 90, "BE"),
    ])
    them = SimpleNamespace(team_name="Them", roster=[
        espn("Q2", "QB", 290, "QB"), espn("S1", "RB", 300, "RB"), espn("S2", "WR", 280, "WR"),
        espn("S3", "WR", 250, "BE"), espn("Weak", "WR", 100, "WR"), espn("T", "WR", 140, "BE", recent=(150,)),
    ])
    settings = SimpleNamespace(matchup_periods={"1": [17], "2": [18]}, reg_season_count=1,
                               position_slot_counts={"QB": 1, "RB": 1, "WR": 2, "BE": 5})
    lg = SimpleNamespace(current_week=17, settings=settings, teams=[me, them], free_agents=lambda size: [],
                         player_info=lambda playerId: [p for p in them.roster if p.name in playerId])
    monkeypatch.setattr(server, "_team", lambda lg, team_id: me)
    monkeypatch.setattr(server, "_bye_weeks", lambda lg: {})

    text, players = report(lg, max_their_loss=1000)
    assert "give B: You 22.5, Them 0.0, Best 0.79" in text and "Them                 A  " in text
    assert players == ["A", "T", "B"]
