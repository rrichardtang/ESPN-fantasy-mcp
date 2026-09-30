"""Ranks free-agent pickups by how much they raise your best starting lineup, for the rest of the season and this week.

A move adds one free agent and drops one of your players (none if you have an open roster spot). Each free
agent is shown with its best drop. A bench player you drop costs nothing, a starter you drop is charged.

Run: python waiver_finder.py [--top 10]   (reads LEAGUE_ID, ESPN_S2 and SWID like server.py)
"""

import argparse

from trade_finder import Player, projected_players, lineup_points, starting


def move_gains(roster, free_agents, slots, limit, ir=()) -> dict[tuple[int, int | None], float]:
    """Change in lineup points for every move, keyed by (free agent index, dropped roster index or None).
    Dropping nobody is only allowed while the roster has fewer than limit players. ir players count in the
    lineup but are never dropped and take no roster spot."""
    slots = starting(slots)
    before = lineup_points([*roster, *ir], slots)
    drops = [None] if len(roster) < limit else range(len(roster))
    return {
        (a, d): round(lineup_points([*(p for i, p in enumerate(roster) if i != d), *ir, fa], slots) - before, 1)
        for a, fa in enumerate(free_agents)
        for d in drops
    }


def best_moves(primary, secondary) -> list[tuple[int, int | None, float, float]]:
    """(free agent, drop, primary gain, secondary gain) for each free agent's best drop: the most primary gain,
    then the most secondary gain. Only primary gains above 0, biggest first."""
    best = {}
    for (a, d), gain in primary.items():
        if a not in best or (gain, secondary[a, d]) > best[a][2:]:
            best[a] = (a, d, gain, secondary[a, d])
    return sorted((m for m in best.values() if m[2] > 0), key=lambda m: -m[2])


def _weekly(espn_players, week) -> list[Player]:
    return [Player(p.name, p.position, p.stats.get(week, {}).get("projected_points") or 0.0) for p in espn_players]


def main():
    import server  # reads LEAGUE_ID, ESPN_S2 and SWID from the environment

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=10, help="how many pickups to show in each table")
    args = parser.parse_args()

    lg = server.league()
    me = server._team(lg, None)
    slots = lg.settings.position_slot_counts
    limit = sum(n for s, n in slots.items() if s != "IR")
    mine = [p for p in me.roster if p.lineupSlot != "IR"]
    on_ir = [p for p in me.roster if p.lineupSlot == "IR"]
    free_agents = lg.free_agents(week=lg.current_week, size=200)

    ros = move_gains(projected_players(mine), projected_players(free_agents), slots, limit, projected_players(on_ir))
    week = move_gains(_weekly(mine, lg.current_week), _weekly(free_agents, lg.current_week), slots, limit)
    drop = lambda d: "nobody" if d is None else mine[d].name  # noqa: E731

    print("Rest of season\n")
    print(f"{'Add':<28} {'Drop':<28} {'Gain':>6}")
    for a, d, gain, _ in best_moves(ros, ros)[: args.top]:
        print(f"{free_agents[a].name[:28]:<28} {drop(d)[:28]:<28} {gain:>6}")
    print(f"\nThis week (week {lg.current_week})\n")
    print(f"{'Add':<28} {'Drop':<28} {'This week':>9} {'Rest of season':>15}")
    for a, d, gain, cost in best_moves(week, ros)[: args.top]:
        print(f"{free_agents[a].name[:28]:<28} {drop(d)[:28]:<28} {gain:>9} {cost:>15}")


if __name__ == "__main__":
    main()
