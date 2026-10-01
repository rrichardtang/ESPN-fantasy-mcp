"""Finds trades that raise your best starting lineup, and the other team's, using ESPN's rest-of-season projections.

A trade is scored by how much it changes each team's optimal starting lineup, week by week, not by adding up
player values. A player on a bye, or out for a week, is not in that week's lineup, and playoff weeks count
more. Every lineup may also use the best free agents, so a player no better than the waiver wire adds nothing,
and a 2-for-1 frees a roster spot for a pickup.

Run: python trade_finder.py [--top 15] [--min-their-gain -10] [--adjustments FILE]
(reads LEAGUE_ID, ESPN_S2 and SWID like server.py)
"""

import argparse
import json
import sys
from dataclasses import dataclass, replace
from itertools import combinations

# Flex slots and the positions they accept. Any other slot takes only its own position.
FLEX = {
    "RB/WR": {"RB", "WR"},
    "WR/TE": {"WR", "TE"},
    "RB/WR/TE": {"RB", "WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"},
    "DL": {"DT", "DE"},
    "DB": {"CB", "S"},
    "DP": {"DT", "DE", "LB", "CB", "S"},
}
NOT_STARTING = {"BE", "IR", ""}
FREE_AGENTS_PER_POSITION = 3
LAST_NFL_WEEK = 18
PLAYOFF_WEIGHT = 1.25
MULTIPLIER_RANGE = (0.8, 1.2)
ONE_WEEK = ((1, 1.0),)  # (week, weight) pairs for points that are not split by week


@dataclass(frozen=True)
class Player:
    name: str
    position: str
    points: float  # projected fantasy points per game (or for one week, or the season, when weeks don't matter)
    bye_week: int | None = None
    out_through_week: int = 0

    def plays(self, week: int) -> bool:
        return week != self.bye_week and week > self.out_through_week


@dataclass(frozen=True)
class Trade:
    partner: str
    give: tuple[Player, ...]
    get: tuple[Player, ...]
    my_gain: float
    their_gain: float
    my_worst_week_change: float


def starting(slots: dict[str, int]) -> dict[str, int]:
    """The slots that hold a starter."""
    return {s: n for s, n in slots.items() if n and s not in NOT_STARTING}


def lineup_points(players, slots: dict[str, int]) -> float:
    """Projected points of the best starting lineup. Filling narrow slots before wide ones is optimal when any
    two slots' positions are nested or disjoint. Only RB/WR and WR/TE overlap otherwise, so with both, each
    WR/TE slot is tried as a WR slot and as a TE slot, which covers every way the optimal lineup can fill it."""
    if slots.get("RB/WR") and slots.get("WR/TE"):
        rest = {s: n for s, n in slots.items() if s != "WR/TE"}
        n = slots["WR/TE"]
        return max(
            lineup_points(players, {**rest, "TE": rest.get("TE", 0) + k, "WR": rest.get("WR", 0) + n - k})
            for k in range(n + 1)
        )
    pool = sorted(players, key=lambda p: p.points, reverse=True)
    total = 0.0
    for slot, count in sorted(slots.items(), key=lambda s: len(FLEX.get(s[0], {s[0]}))):
        allowed = FLEX.get(slot, {slot})
        picks = [p for p in pool if p.position in allowed][:count]
        for p in picks:
            pool.remove(p)
        total += sum(p.points for p in picks)
    return total


def weekly_points(players, slots: dict[str, int], weeks) -> dict[int, float]:
    """Best lineup points each week, from the players who play that week. weeks pairs each week with its weight.
    Weeks missing the same players share one lineup."""
    lineups = {}
    totals = {}
    for week, _ in weeks:
        available = tuple(p for p in players if p.plays(week))
        if available not in lineups:
            lineups[available] = lineup_points(available, slots)
        totals[week] = lineups[available]
    return totals


def season_points(players, slots: dict[str, int], weeks) -> tuple[float, float]:
    """(Weighted points over weeks, the lowest single-week points). weeks pairs each week with its weight."""
    weekly = weekly_points(players, slots, weeks)
    return sum(weekly[w] * weight for w, weight in weeks), min(weekly.values())


def season_weeks(current: int, matchup_periods: dict[str, list[int]], reg_season_count: int):
    """(week, weight) for every fantasy week left. Playoff weeks weigh PLAYOFF_WEIGHT."""
    last_regular = max(matchup_periods[str(reg_season_count)])
    last = max(w for weeks in matchup_periods.values() for w in weeks)
    return tuple((w, PLAYOFF_WEIGHT if w > last_regular else 1.0) for w in range(current, last + 1))


def replacement(free_agents) -> list[Player]:
    """The best few free agents at each position: the players any team could pick up instead."""
    by_position: dict[str, list[Player]] = {}
    for p in sorted(free_agents, key=lambda p: p.points, reverse=True):
        by_position.setdefault(p.position, []).append(p)
    return [p for top in by_position.values() for p in top[:FREE_AGENTS_PER_POSITION]]


def tradeable(roster, waiver: list[Player]) -> list[Player]:
    """Players who beat the best free agent at their position. Anyone else is worth nothing in a trade."""
    best = {}
    for p in waiver:
        best[p.position] = max(best.get(p.position, 0.0), p.points)
    return [p for p in roster if p.points > best.get(p.position, 0.0)]


def find_trades(
    my_roster,
    others: list[tuple[str, list[Player]]],
    free_agents,
    slots,
    min_their_gain=0.0,
    sizes=((1, 1), (2, 1), (1, 2)),
    weeks=ONE_WEEK,
):
    """Every 1-for-1 and 2-for-1 trade (in both directions) that improves your lineup and changes theirs by
    more than min_their_gain, best for you first. A trade is left out when a smaller one inside it is at
    least as good for both teams, so a throw-in player only shows up if it helps the other team.

    others pairs each other team's name with its roster. sizes lists (players you give, players you get).
    weeks pairs each week left with its weight, see season_weeks."""
    slots = starting(slots)
    waiver = replacement(free_agents)

    def value(roster):
        return season_points([*roster, *waiver], slots, weeks)

    mine = tradeable(my_roster, waiver)
    my_before, my_worst = value(my_roster)
    found = {}
    for partner, roster in others:
        theirs = tradeable(roster, waiver)
        their_before = value(roster)[0]
        for n_give, n_get in sizes:
            for give in combinations(mine, n_give):
                for get in combinations(theirs, n_get):
                    my_after, my_worst_after = value([p for p in my_roster if p not in give] + list(get))
                    my_gain = round(my_after - my_before, 1)
                    their_gain = round(value([p for p in roster if p not in get] + list(give))[0] - their_before, 1)
                    if my_gain > 0 and their_gain > min_their_gain:
                        worst_change = round(my_worst_after - my_worst, 1)
                        found[partner, give, get] = Trade(partner, give, get, my_gain, their_gain, worst_change)

    def padded(t):
        smaller = [(t.partner, g, t.get) for g in combinations(t.give, len(t.give) - 1)] + [
            (t.partner, t.give, g) for g in combinations(t.get, len(t.get) - 1)
        ]
        return any(
            s in found and found[s].my_gain >= t.my_gain and found[s].their_gain >= t.their_gain for s in smaller
        )

    trades = [t for t in found.values() if not padded(t)]
    return sorted(trades, key=lambda t: (-t.my_gain, -t.their_gain))


def per_game(season_total: float, bye_week: int | None, week: int, out_through_week: int = 0) -> float:
    """Rest-of-season points spread over the NFL games the player plays from week on. ESPN's projection already
    leaves out games he is expected to miss."""
    first = max(week, out_through_week + 1)
    games = LAST_NFL_WEEK - first + 1 - (first <= (bye_week or 0) <= LAST_NFL_WEEK)
    return season_total / max(games, 1)


def adjusted(player: Player, adjustment: dict) -> Player:
    """Applies a research adjustment: a multiplier (kept within MULTIPLIER_RANGE) and an out_through_week."""
    multiplier = min(max(float(adjustment.get("multiplier") or 1.0), MULTIPLIER_RANGE[0]), MULTIPLIER_RANGE[1])
    out_through_week = int(adjustment.get("out_through_week") or 0)
    return replace(player, points=player.points * multiplier, out_through_week=out_through_week)


def load_adjustments(path: str | None, names) -> dict[str, dict]:
    """Adjustments by player name from a JSON file, if given. Names not among names are reported."""
    if not path:
        return {}
    with open(path) as f:
        adjustments = json.load(f)
    for name in sorted(adjustments.keys() - set(names)):
        print(f"Adjustment for unknown player ignored: {name}", file=sys.stderr)
    return adjustments


def projected_players(espn_players, byes: dict[str, int], week: int, adjustments: dict) -> list[Player]:
    """Players with per-game rates from ESPN's rest-of-season projections, from week on."""
    players = []
    for p in espn_players:
        bye = byes.get(p.proTeam)
        player = adjusted(Player(p.name, p.position, p.projected_total_points or 0.0, bye), adjustments.get(p.name, {}))
        players.append(replace(player, points=per_game(player.points, bye, week, player.out_through_week)))
    return players


def setup(lg, free_agents, adjustments_path):
    """(project, weeks) for a script's main: project turns ESPN players into Players, weeks is season_weeks.
    Adjustment names are checked against free_agents and every roster. Exits when no fantasy weeks are left."""
    import server

    weeks = season_weeks(lg.current_week, lg.settings.matchup_periods, lg.settings.reg_season_count)
    if not weeks:
        sys.exit("No fantasy weeks left this season.")
    everyone = [*free_agents, *(p for t in lg.teams for p in t.roster)]
    adjustments = load_adjustments(adjustments_path, (p.name for p in everyone))
    byes = server._bye_weeks(lg)
    return (lambda players: projected_players(players, byes, lg.current_week, adjustments)), weeks


def add_adjustments_argument(parser):
    parser.add_argument("--adjustments", help='JSON file: {"Player": {"multiplier": 1.1, "out_through_week": 6}}')


def weekly_line(weekly: dict[int, float], marked=3) -> str:
    """Week-by-week totals, the lowest few marked with *."""
    weakest = sorted(weekly, key=weekly.get)[:marked]
    return "  ".join(f"{w}: {pts:.0f}{'*' if w in weakest else ''}" for w, pts in weekly.items())


def main():
    import server  # reads LEAGUE_ID, ESPN_S2 and SWID from the environment

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=15, help="how many trades to show")
    parser.add_argument(
        "--min-their-gain", type=float, default=0.0, help="lowest change to their lineup to allow, can be negative"
    )
    add_adjustments_argument(parser)
    args = parser.parse_args()

    lg = server.league()
    me = server._team(lg, None)
    espn_free_agents = lg.free_agents(size=200)
    project, weeks = setup(lg, espn_free_agents, args.adjustments)
    free_agents = project(espn_free_agents)
    mine = project(me.roster)
    others = [(t.team_name, project(t.roster)) for t in lg.teams if t is not me]
    slots = lg.settings.position_slot_counts
    trades = find_trades(mine, others, free_agents, slots, args.min_their_gain, weeks=weeks)

    my_weekly = weekly_points([*mine, *replacement(free_agents)], starting(slots), weeks)
    names = lambda players: " + ".join(p.name for p in players)  # noqa: E731
    print(f"Your lineup by week (* weakest): {weekly_line(my_weekly)}\n")
    print(f"{len(trades)} trades found. Gains are changes to each starting lineup in rest-of-season points,")
    print(f"playoff weeks counting {PLAYOFF_WEIGHT}x. Worst is the change to your lowest week.\n")
    print(f"{'Partner':<24} {'You give':<40} {'You get':<40} {'You':>6} {'Them':>6} {'Worst':>6}")
    for t in trades[: args.top]:
        print(
            f"{t.partner[:24]:<24} {names(t.give)[:40]:<40} {names(t.get)[:40]:<40} "
            f"{t.my_gain:>6} {t.their_gain:>6} {t.my_worst_week_change:>6}"
        )


if __name__ == "__main__":
    main()
