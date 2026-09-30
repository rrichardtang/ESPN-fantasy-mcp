"""Finds trades that raise your best starting lineup, and the other team's, using ESPN's rest-of-season projections.

A trade is scored by how much it changes each team's optimal starting lineup, not by adding up player
values. Every lineup may also use the best free agents, so a player no better than the waiver wire adds
nothing, and a 2-for-1 frees a roster spot for a pickup.

Run: python trade_finder.py [--top 15] [--min-their-gain -10]   (reads LEAGUE_ID, ESPN_S2 and SWID like server.py)
"""

import argparse
from dataclasses import dataclass
from itertools import combinations

# Flex slots and the positions they accept. Any other slot takes only its own position.
FLEX = {"RB/WR": {"RB", "WR"}, "WR/TE": {"WR", "TE"}, "RB/WR/TE": {"RB", "WR", "TE"}, "OP": {"QB", "RB", "WR", "TE"}}
NOT_STARTING = {"BE", "IR", ""}
FREE_AGENTS_PER_POSITION = 3


@dataclass(frozen=True)
class Player:
    name: str
    position: str
    points: float  # projected rest-of-season fantasy points


@dataclass(frozen=True)
class Trade:
    partner: str
    give: tuple[Player, ...]
    get: tuple[Player, ...]
    my_gain: float
    their_gain: float


def lineup_points(players, slots: dict[str, int]) -> float:
    """Projected points of the best starting lineup. Filling narrow slots before flex slots is optimal
    because each flex slot accepts every position of the slots filled before it."""
    pool = sorted(players, key=lambda p: p.points, reverse=True)
    total = 0.0
    for slot, count in sorted(slots.items(), key=lambda s: len(FLEX.get(s[0], {s[0]}))):
        allowed = FLEX.get(slot, {slot})
        picks = [p for p in pool if p.position in allowed][:count]
        for p in picks:
            pool.remove(p)
        total += sum(p.points for p in picks)
    return total


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
    my_roster, others: dict[str, list[Player]], free_agents, slots, min_their_gain=0.0, sizes=((1, 1), (2, 1), (1, 2))
):
    """Every 1-for-1 and 2-for-1 trade (in both directions) that improves your lineup and changes theirs by
    more than min_their_gain, best for you first. A trade is left out when a smaller one inside it is at
    least as good for both teams, so a throw-in player only shows up if it helps the other team.

    others maps each other team's name to its roster. sizes lists (players you give, players you get)."""
    slots = {s: n for s, n in slots.items() if n and s not in NOT_STARTING}
    waiver = replacement(free_agents)

    def value(roster):
        return lineup_points([*roster, *waiver], slots)

    mine = tradeable(my_roster, waiver)
    my_before = value(my_roster)
    found = {}
    for partner, roster in others.items():
        theirs = tradeable(roster, waiver)
        their_before = value(roster)
        for n_give, n_get in sizes:
            for give in combinations(mine, n_give):
                for get in combinations(theirs, n_get):
                    my_gain = round(value([p for p in my_roster if p not in give] + list(get)) - my_before, 1)
                    their_gain = round(value([p for p in roster if p not in get] + list(give)) - their_before, 1)
                    if my_gain > 0 and their_gain > min_their_gain:
                        found[partner, give, get] = Trade(partner, give, get, my_gain, their_gain)

    def padded(t):
        smaller = [(t.partner, g, t.get) for g in combinations(t.give, len(t.give) - 1)] + [
            (t.partner, t.give, g) for g in combinations(t.get, len(t.get) - 1)
        ]
        return any(
            s in found and found[s].my_gain >= t.my_gain and found[s].their_gain >= t.their_gain for s in smaller
        )

    trades = [t for t in found.values() if not padded(t)]
    return sorted(trades, key=lambda t: (-t.my_gain, -t.their_gain))


def _players(espn_players) -> list[Player]:
    return [Player(p.name, p.position, p.projected_total_points or 0.0) for p in espn_players]


def main():
    import server  # reads LEAGUE_ID, ESPN_S2 and SWID from the environment

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=15, help="how many trades to show")
    parser.add_argument(
        "--min-their-gain", type=float, default=0.0, help="lowest change to their lineup to allow, can be negative"
    )
    args = parser.parse_args()

    lg = server.league()
    me = server._team(lg, None)
    free_agents = _players(lg.free_agents(size=200))
    others = {t.team_name: _players(t.roster) for t in lg.teams if t is not me}
    trades = find_trades(
        _players(me.roster), others, free_agents, lg.settings.position_slot_counts, args.min_their_gain
    )

    names = lambda players: " + ".join(p.name for p in players)  # noqa: E731
    print(f"{len(trades)} trades found. Gains are changes to each starting lineup, in rest-of-season points.\n")
    print(f"{'Partner':<24} {'You give':<40} {'You get':<40} {'You':>6} {'Them':>6}")
    for t in trades[: args.top]:
        print(f"{t.partner[:24]:<24} {names(t.give)[:40]:<40} {names(t.get)[:40]:<40} {t.my_gain:>6} {t.their_gain:>6}")


if __name__ == "__main__":
    main()
