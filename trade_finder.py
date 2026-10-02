"""Finds trades for your league: target trades that turn one to three of your spare players into another team's
RB, WR or TE outside its top three, and bench candidates on other teams with the cheapest offer for each.

A trade is scored by how much it changes each team's optimal starting lineup, week by week, not by adding up
player values. A player on a bye, or out for a week, is not in that week's lineup, and playoff weeks count
more. Every lineup may also use the best free agents, so a player no better than the waiver wire adds nothing,
and a 3-for-1 frees roster spots for pickups.

Run: python trade_finder.py [--top 15] [--protect-top 3] [--keep "Name,Name"] [--min-best-ratio 0.75]
     [--max-their-loss 10] [--adjustments FILE]   (reads LEAGUE_ID, ESPN_S2 and SWID like server.py)
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, replace
from functools import cache
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
SKILL = {"RB", "WR", "TE"}  # the positions ranked for protection and targets
TRADED = {"QB", *SKILL}
MY_PROTECTED = 2  # your top RB/WR/TE you never give
PROTECT_TOP = 3  # each other team's top RB/WR/TE it never gives
MAX_GIVE = 3
PER_TARGET = 2  # rows shown per target
MIN_BEST_RATIO = 0.75
MAX_THEIR_LOSS = 10.0
BENCH_SHOWN = 12  # bench candidates listed: Alan researches each, so this bounds his cost


@dataclass(frozen=True)
class Player:
    name: str
    position: str
    points: float  # projected fantasy points per game (or for one week, or the season, when weeks don't matter)
    bye_week: int | None = None
    out_through_week: int = 0
    slot: str = ""  # the lineup slot ESPN has him in

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
    best_ratio: float  # see best_ratio
    my_cost: float  # your lineup value lost to the players you give, before adding the ones you get


@dataclass(frozen=True)
class Candidate:
    partner: str
    roster: tuple[Player, ...]
    player: Player
    recent: tuple[float, ...]  # his points in his last games played


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


def raw_points(player: Player, weeks) -> float:
    """Unweighted projected points over the weeks left: what a manager adds up from the season projection."""
    return sum(player.points for week, _ in weeks if player.plays(week))


def best_ratio(give, get, weeks) -> float:
    """The best player given's raw points (see raw_points) over the best player gotten's."""
    best = lambda players: max((raw_points(p, weeks) for p in players), default=0.0)  # noqa: E731
    return best(give) / best(get) if best(get) else 0.0


def ranked(roster, weeks) -> list[Player]:
    """The roster's RB, WR and TE, most raw points first."""
    return sorted((p for p in roster if p.position in SKILL), key=lambda p: -raw_points(p, weeks))


def give_pool(my_roster, free_agents, weeks=ONE_WEEK, keep=()) -> list[Player]:
    """Your QB, RB, WR and TE better than a free agent, except your MY_PROTECTED best RB/WR/TE and the names in
    keep."""
    top = ranked(my_roster, weeks)[:MY_PROTECTED]
    pool = tradeable(my_roster, replacement(free_agents))
    return [p for p in pool if p.position in TRADED and p not in top and p.name not in keep]


def packages(pool, most: int) -> list[tuple[Player, ...]]:
    """Every group of 1 to most players from pool."""
    return [give for n in range(1, most + 1) for give in combinations(pool, n)]


def scorer(my_roster, free_agents, slots, weeks=ONE_WEEK):
    """score(partner, roster, give, get) -> Trade. Every lineup streams the best free agents, so a roster spot a
    trade opens is filled from the waiver wire."""
    slots, waiver = starting(slots), replacement(free_agents)
    mine = tuple(my_roster)

    @cache
    def value(roster: tuple[Player, ...]) -> tuple[float, float]:
        return season_points([*roster, *waiver], slots, weeks)

    def score(partner: str, roster, give: tuple[Player, ...], get: tuple[Player, ...]) -> Trade:
        kept = tuple(p for p in mine if p not in give)
        my_after, my_worst_after = value(kept + get)
        their_after = value(tuple(p for p in roster if p not in get) + give)[0]
        my_before, my_worst = value(mine)
        their_gain = their_after - value(tuple(roster))[0]
        return Trade(partner, give, get, my_after - my_before, their_gain, my_worst_after - my_worst,
                     best_ratio(give, get, weeks), my_before - value(kept)[0])

    return score


def acceptance(min_best_ratio=MIN_BEST_RATIO, max_their_loss=MAX_THEIR_LOSS):
    """Whether the other manager may take a trade: the best player he gets has at least min_best_ratio of the raw
    points of the best he gives, and the trade costs his lineup at most max_their_loss."""
    return lambda t: t.best_ratio >= min_best_ratio and t.their_gain >= -max_their_loss


def offers(score, partner, roster, get, gives, accept) -> dict[tuple[Player, ...], Trade]:
    """The trades for get, by package given, that accept passes and that don't lower your lineup."""
    trades = (score(partner, roster, give, get) for give in gives)
    return {t.give: t for t in trades if t.my_gain >= 0 and accept(t)}


def padded(trade: Trade, found: dict) -> bool:
    """A smaller package inside the trade is in found and at least as good for both teams."""
    smaller = (found.get(g) for n in range(1, len(trade.give)) for g in combinations(trade.give, n))
    return any(s and s.my_gain >= trade.my_gain and s.their_gain >= trade.their_gain for s in smaller)


def find_targets(score, pool, others, accept, weeks=ONE_WEEK, protect=PROTECT_TOP) -> list[Trade]:
    """For each other team's RB/WR/TE outside its protect best (see ranked), the packages of 1 to MAX_GIVE players
    from pool that accept passes and that raise your lineup, best for you first, at most PER_TARGET per target.
    A package is left out when a smaller one inside it is as good for both teams, so a throw-in must help."""
    # ponytail: every package is scored, about 1 ms each: a 10-player pool makes 175 per target, 20 players
    # 1350. Rank packages by best_ratio first if pools grow past that.
    gives = packages(pool, MAX_GIVE)
    trades = []
    for partner, roster in others:
        for target in ranked(roster, weeks)[protect:]:
            if score(partner, roster, (), (target,)).my_gain <= 0:  # giving players never raises your lineup
                continue
            found = offers(score, partner, roster, (target,), gives, accept)
            kept = [t for t in found.values() if t.my_gain > 0 and not padded(t, found)]
            trades += sorted(kept, key=lambda t: -t.my_gain)[:PER_TARGET]
    return sorted(trades, key=lambda t: (-t.my_gain, -t.their_gain))


def bench_candidates(others, free_agents, recent: dict[str, tuple[float, ...]], weeks=ONE_WEEK,
                     protect=PROTECT_TOP) -> list[Candidate]:
    """Bench QB, RB, WR and TE on other teams who beat the best free agent at their position and are outside their
    team's protect best RB/WR/TE: the BENCH_SHOWN with the most points per game over the best free agent at their
    position, by team then points per game. recent maps names to recent points."""
    waiver = replacement(free_agents)
    wire = {p.position: max(q.points for q in waiver if q.position == p.position) for p in waiver}
    found = []
    for partner, roster in others:
        top = ranked(roster, weeks)[:protect]
        found += [
            Candidate(partner, tuple(roster), p, recent.get(p.name, ())) for p in tradeable(roster, waiver)
            if p.slot == "BE" and p.position in TRADED and p not in top and raw_points(p, weeks) > 0
        ]
    shown = sorted(found, key=lambda c: wire.get(c.player.position, 0.0) - c.player.points)[:BENCH_SHOWN]
    return sorted(shown, key=lambda c: (c.partner, -c.player.points))


def cheapest_offer(score, pool, candidate: Candidate, accept) -> Trade | None:
    """The 1-for-1 or 2-for-1 for the candidate (see offers) that gives up the least of your lineup's value, then
    gains you the most, then whose best player given is worth least."""
    found = offers(score, candidate.partner, candidate.roster, (candidate.player,), packages(pool, 2), accept)
    return min(found.values(), key=lambda t: (t.my_cost, -t.my_gain, t.best_ratio), default=None)


def per_game(season_total: float, bye_week: int | None, week: int, out_through_week: int = 0) -> float:
    """Rest-of-season points spread over the NFL games the player plays from week on. ESPN's projection already
    leaves out games he is expected to miss."""
    first = max(week, out_through_week + 1)
    games = LAST_NFL_WEEK - first + 1 - (first <= (bye_week or 0) <= LAST_NFL_WEEK)
    return season_total / max(games, 1)


def adjusted(player: Player, adjustment: dict) -> Player:
    """Applies a research adjustment: a multiplier (kept within MULTIPLIER_RANGE) and an out_through_week."""
    raw = adjustment.get("multiplier")
    multiplier = float(1.0 if raw is None else raw)
    if not math.isfinite(multiplier):
        raise ValueError(f"multiplier must be a finite number, not {multiplier}")
    multiplier = min(max(multiplier, MULTIPLIER_RANGE[0]), MULTIPLIER_RANGE[1])
    out_through_week = int(adjustment.get("out_through_week") or 0)
    return replace(player, points=player.points * multiplier, out_through_week=out_through_week)


def load_adjustments(path: str | None) -> dict[str, dict]:
    """Adjustments by player name from a JSON file, if given."""
    if not path:
        return {}
    with open(path) as f:
        return json.load(f)


def adjustment_lines(adjustments: dict, ignored=()) -> list[str]:
    """Each adjustment as applied (multiplier kept in range), with its reason and source, then the ignored names,
    to print above a table."""
    if not adjustments and not ignored:
        return []
    lines = ["Research adjustments to the projections:"]
    for name, adjustment in adjustments.items():
        applied = adjusted(Player(name, "", 1.0), adjustment)
        out = f", out through week {applied.out_through_week}" if applied.out_through_week else ""
        reason, source = adjustment.get("reason", "no reason given"), adjustment.get("source", "no source")
        lines.append(f"  {name}: x{applied.points:g}{out}. {reason} ({source})")
    lines += [f"  {name}: not found, ignored" for name in ignored]
    return [*lines, ""]


def projected_players(espn_players, byes: dict[str, int], week: int, adjustments: dict) -> list[Player]:
    """Players with per-game rates from ESPN's rest-of-season projections, from week on."""
    players = []
    for p in espn_players:
        bye = byes.get(p.proTeam)
        player = Player(p.name, p.position, p.projected_total_points or 0.0, bye, slot=p.lineupSlot)
        player = adjusted(player, adjustments.get(p.name, {}))
        players.append(replace(player, points=per_game(player.points, bye, week, player.out_through_week)))
    return players


def setup(lg, free_agents, adjustments: dict):
    """(project, weeks, notes) for a script's report: project turns ESPN players into Players, weeks is
    season_weeks, notes is adjustment_lines, where names not among free_agents or any roster are ignored.
    Exits when no fantasy weeks are left."""
    import server

    weeks = season_weeks(lg.current_week, lg.settings.matchup_periods, lg.settings.reg_season_count)
    if not weeks:
        sys.exit("No fantasy weeks left this season.")
    everyone = {p.name for p in [*free_agents, *(p for t in lg.teams for p in t.roster)]}
    known = {name: adjustment for name, adjustment in adjustments.items() if name in everyone}
    notes = adjustment_lines(known, sorted(adjustments.keys() - everyone))
    byes = server._bye_weeks(lg)
    return (lambda players: projected_players(players, byes, lg.current_week, known)), weeks, notes


def add_adjustments_argument(parser):
    parser.add_argument("--adjustments", help='JSON file: {"Player": {"multiplier": 1.1, "out_through_week": 6}}')


def weekly_line(weekly: dict[int, float], marked=3) -> str:
    """Week-by-week totals, the lowest few marked with *."""
    weakest = sorted(weekly, key=weekly.get)[:marked]
    return "  ".join(f"{w}: {pts:.0f}{'*' if w in weakest else ''}" for w, pts in weekly.items())


def recent_points(espn_player, week: int, games=2) -> tuple[float, ...]:
    """His points in the last few games he played (ESPN's stat 210) before week, whose games may be in progress."""
    played = [s.get("points", 0.0) for w, s in sorted(espn_player.stats.items()) if 0 < w < week
              and "210" in s.get("breakdown", {})]
    return tuple(played[-games:])


def names(players) -> str:
    return " + ".join(p.name for p in players)


def tenths(x: float) -> str:
    """x to one decimal, never -0.0."""
    return f"{round(x, 1) + 0.0:.1f}"


def target_lines(trades: list[Trade]) -> list[str]:
    lines = [
        "Target trades. You and Them are the changes to each starting lineup in rest-of-season points, playoff",
        f"weeks counting {PLAYOFF_WEIGHT}x, and Worst the change to your lowest week. Best is the season points of",
        "the best player you give over the target's.\n",
        f"{'Partner':<20} {'You give':<52} {'You get':<22} {'You':>6} {'Them':>6} {'Best':>5} {'Worst':>6}",
    ]
    for t in trades:
        lines.append(
            f"{t.partner[:20]:<20} {names(t.give)[:52]:<52} {names(t.get)[:22]:<22} {tenths(t.my_gain):>6} "
            f"{tenths(t.their_gain):>6} {t.best_ratio:>5.2f} {tenths(t.my_worst_week_change):>6}"
        )
    return lines


def bench_lines(candidates: list[Candidate], deals: list[Trade | None], started: dict[str, float]) -> list[str]:
    lines = [
        f"Bench candidates: the {BENCH_SHOWN} other teams' bench players with the most points per game (Pts/g)",
        "over the best free agent at their position, among those who beat him; the list is capped because each",
        "one gets researched.",
        "Last 2 is his last two games played, Start% the share of ESPN teams starting him. Under each, the cheapest",
        "offer that passes the target trades' tests and keeps your lineup whole.\n",
        f"{'Team':<20} {'Player':<24} {'Pos':<4} {'Pts/g':>5}  {'Last 2':<11} {'Start%':>6}",
    ]
    for c, deal in zip(candidates, deals):
        p, last = c.player, ", ".join(f"{x:g}" for x in c.recent)
        lines.append(
            f"{c.partner[:20]:<20} {p.name[:24]:<24} {p.position:<4} {p.points:>5.1f}  {last:<11} "
            f"{started.get(p.name, 0):>6.0f}"
        )
        offer = (f"give {names(deal.give)}: You {tenths(deal.my_gain)}, Them {tenths(deal.their_gain)}, "
                 f"Best {deal.best_ratio:.2f}") if deal else "no offer passes"
        lines.append(f"{'':<20} {offer}")
    return lines


def report(lg, adjustments: dict | None = None, top=15, protect=PROTECT_TOP, keep=(),
           min_best_ratio=MIN_BEST_RATIO, max_their_loss=MAX_THEIR_LOSS) -> tuple[str, list[str]]:
    """Target trades and bench candidates as printed text, and the names of every player in the rows shown."""
    import server

    adjustments = adjustments or {}
    me = server._team(lg, None)
    rivals = [t for t in lg.teams if t is not me]
    espn_free_agents = lg.free_agents(size=200)
    project, weeks, notes = setup(lg, espn_free_agents, adjustments)
    free_agents, mine = project(espn_free_agents), project(me.roster)
    others = [(t.team_name, project(t.roster)) for t in rivals]
    slots = lg.settings.position_slot_counts
    score, accept = scorer(mine, free_agents, slots, weeks), acceptance(min_best_ratio, max_their_loss)
    pool = give_pool(mine, free_agents, weeks, keep)
    targets = find_targets(score, pool, others, accept, weeks, protect)[:top]

    bench = [p.playerId for t in rivals for p in t.roster if p.lineupSlot == "BE" and p.position in TRADED]
    cards = lg.player_info(playerId=bench) if bench else None
    cards = cards if isinstance(cards, list) else [cards] if cards else []
    recent = {card.name: recent_points(card, lg.current_week) for card in cards}
    candidates = bench_candidates(others, free_agents, recent, weeks, protect)
    deals = [cheapest_offer(score, pool, c, accept) for c in candidates]
    started = {p.name: p.percent_started for t in rivals for p in t.roster}

    my_weekly = weekly_points([*mine, *replacement(free_agents)], starting(slots), weeks)
    unknown = sorted(set(keep) - {p.name for p in mine})
    lines = [
        *notes,
        *(f"--keep: {name} is not on your roster, ignored" for name in unknown),
        f"Your lineup by week (* weakest): {weekly_line(my_weekly)}\n",
        *target_lines(targets),
        "",
        *bench_lines(candidates, deals, started),
    ]
    traded = [p.name for t in [*targets, *filter(None, deals)] for p in (*t.give, *t.get)]
    return "\n".join(lines), list(dict.fromkeys([*traded, *(c.player.name for c in candidates)]))


def main():
    import server  # reads LEAGUE_ID, ESPN_S2 and SWID from the environment

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=15, help="how many target trades to show")
    parser.add_argument("--protect-top", type=int, default=PROTECT_TOP,
                        help="how many of each other team's best RB/WR/TE are off limits")
    parser.add_argument("--keep", type=lambda s: {n.strip() for n in s.split(",")}, default=set(),
                        help='players you won\'t trade, like "Name,Name"')
    parser.add_argument("--min-best-ratio", type=float, default=MIN_BEST_RATIO,
                        help="least season points of your best player given, as a share of the target's")
    parser.add_argument("--max-their-loss", type=float, default=MAX_THEIR_LOSS,
                        help="most a trade may lower their lineup, in rest-of-season points")
    add_adjustments_argument(parser)
    args = parser.parse_args()
    text, _ = report(server.league(), load_adjustments(args.adjustments), args.top, args.protect_top,
                     keep=args.keep, min_best_ratio=args.min_best_ratio, max_their_loss=args.max_their_loss)
    print(text)


if __name__ == "__main__":
    main()
