"""Read-only MCP server for one ESPN fantasy football league, served over HTTP."""

import copy
import difflib
import functools
import inspect
import json
import os
import re
import time
from datetime import date, datetime
from typing import Annotated, Literal

import requests
import uvicorn
from espn_api.football import League
from espn_api.football.player import Player
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

LEAGUE_ID = int(os.environ["LEAGUE_ID"])
ESPN_S2 = os.environ.get("ESPN_S2")
SWID = os.environ.get("SWID")
_today = date.today()
# ESPN names a season after the year it starts, and drafts happen in August.
YEAR = int(os.environ.get("ESPN_YEAR") or (_today.year if _today.month >= 8 else _today.year - 1))

ESPN_ERRORS = (ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError, requests.RequestException)

mcp = MCPServer(
    "espn-fantasy",
    instructions=(
        "Read-only tools for one ESPN fantasy football league. Tools that take team_id default to "
        "the user's own team; get_standings lists every team's id. An empty week means the current week."
    ),
)


@functools.lru_cache(maxsize=1)
def _league_for_minute(minute: int) -> League:
    return League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)


def league() -> League:
    # ponytail: reloads the whole league at most once a minute, plenty for one person's chats.
    return _league_for_minute(int(time.time() // 60))


def tool(fn):
    """Registers fn as a read-only tool that returns JSON and shows ESPN errors to Claude."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return json.dumps(fn(*args, **kwargs), default=str)
        except ESPN_ERRORS as e:
            raise ToolError(f"ESPN request failed: {e}") from e

    mcp.tool(
        description=inspect.cleandoc(fn.__doc__),
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=False,
    )(wrapper)
    return fn


def _my_team_id(lg: League) -> int | None:
    for team in lg.teams:
        if SWID and any(owner.get("id", "").upper() == SWID.upper() for owner in team.owners):
            return team.team_id
    return None


def _team(lg: League, team_id: int | None):
    team = lg.get_team_data(_my_team_id(lg) if team_id is None else team_id)
    if team is None:
        raise ToolError("Couldn't find that team. Pass a team_id from get_standings.")
    return team


def _owners(team) -> str:
    return ", ".join(
        f"{o.get('firstName', '')} {o.get('lastName', '')}".strip() or o.get("displayName", "") for o in team.owners
    )


def _date(epoch_ms: int) -> str | None:
    return datetime.fromtimestamp(epoch_ms / 1000).date().isoformat() if epoch_ms else None


def _box_scores(week: int | None):
    lg = league()
    week = week or lg.current_week
    if not 1 <= week <= lg.current_week:
        raise ToolError(f"Week must be 1 to {lg.current_week}, the current week. get_team shows later weeks.")
    return lg, week, lg.box_scores(week)


def _side(team, score, projected):
    if team is None:  # bye
        return None
    return {"team_id": team.team_id, "name": team.team_name, "score": score, "projected": round(projected, 2)}


def _lineup(team, score, projected, players):
    side = _side(team, score, projected)
    if side:
        side["players"] = [
            {
                "name": p.name,
                "slot": p.slot_position,
                "position": p.position,
                "nfl_team": p.proTeam,
                "opponent": p.pro_opponent,
                "points": p.points,
                "projected": p.projected_points,
                "injury": p.injuryStatus,
                "game_over": p.game_played == 100,
                "bye": p.on_bye_week,
            }
            for p in players
        ]
    return side


@tool
def get_league_info() -> dict:
    """League settings: season, current week, roster slots, scoring rules, playoffs, trade deadline, FAAB."""
    lg = league()
    s = lg.settings
    return {
        "name": s.name,
        "season": lg.year,
        "current_week": lg.current_week,
        "your_team_id": _my_team_id(lg),
        "teams": s.team_count,
        "regular_season_weeks": s.reg_season_count,
        "playoff_teams": s.playoff_team_count,
        "trade_deadline": _date(s.trade_deadline),
        "faab_budget": s.acquisition_budget if s.faab else None,
        "keepers": s.keeper_count,
        "divisions": list(s.division_map.values()),
        "roster_slots": {slot: count for slot, count in s.position_slot_counts.items() if count},
        "scoring": [
            {"stat": item["label"], "abbr": item["abbr"], "points": item["points"]}
            for item in s.scoring_format
            if item["label"] != "Unknown"
        ],
    }


@tool
def get_standings() -> dict:
    """Standings: every team's id, name, owner, record, points for and against, and current streak."""
    lg = league()
    return {
        "your_team_id": _my_team_id(lg),
        "teams": [
            {
                "rank": t.final_standing or t.standing,
                "team_id": t.team_id,
                "name": t.team_name,
                "owner": _owners(t),
                "record": f"{t.wins}-{t.losses}-{t.ties}",
                "points_for": round(t.points_for, 2),
                "points_against": t.points_against,
                "streak": f"{t.streak_type[:1]}{t.streak_length}" if t.streak_length else None,
            }
            for t in lg.standings()
        ],
    }


@tool
def get_team(team_id: int | None = None) -> dict:
    """One team's roster with season points per player, plus its schedule. Defaults to your team.

    Each schedule entry lists the NFL weeks it covers. Result is W, L, T, or U (not decided yet).
    """
    lg = league()
    t = _team(lg, team_id)
    return {
        "team_id": t.team_id,
        "name": t.team_name,
        "owner": _owners(t),
        "record": f"{t.wins}-{t.losses}-{t.ties}",
        "waiver_rank": t.waiver_rank,
        "faab_left": lg.settings.acquisition_budget - t.acquisition_budget_spent if lg.settings.faab else None,
        "roster": [
            {
                "name": p.name,
                "position": p.position,
                "slot": p.lineupSlot,
                "nfl_team": p.proTeam,
                "injury": p.injuryStatus,
                "season_points": p.total_points,
                "avg_points": p.avg_points,
                "projected_season_points": p.projected_total_points,
            }
            for p in t.roster
        ],
        # ESPN lists the team once per matchup period, and a playoff matchup can span two NFL weeks.
        "schedule": [
            {
                "weeks": lg.settings.matchup_periods.get(str(period), [period]),
                "opponent": "BYE" if opp is t else opp.team_name,
                "score": score,
                "result": result,
            }
            for period, (opp, score, result) in enumerate(zip(t.schedule, t.scores, t.outcomes), start=1)
        ],
    }


@tool
def get_scoreboard(week: int | None = None) -> dict:
    """Every matchup in a week with live scores and projected final scores. Current or past weeks only."""
    _, week, boxes = _box_scores(week)
    return {
        "week": week,
        "matchups": [
            {
                "home": _side(b.home_team, b.home_score, b.home_projected),
                "away": _side(b.away_team, b.away_score, b.away_projected),
            }
            for b in boxes
        ],
    }


@tool
def get_matchup(team_id: int | None = None, week: int | None = None) -> dict:
    """One team's matchup in a week: both lineups with each player's points, projection and NFL opponent.

    Defaults to your team this week. Slot BE is the bench and IR is injured reserve.
    """
    lg, week, boxes = _box_scores(week)
    team = _team(lg, team_id)
    box = next((b for b in boxes if team in (b.home_team, b.away_team)), None)
    if box is None:
        raise ToolError(f"{team.team_name} has no matchup in week {week}.")
    home = (box.home_team, box.home_score, box.home_projected, box.home_lineup)
    away = (box.away_team, box.away_score, box.away_projected, box.away_lineup)
    mine, theirs = (away, home) if box.away_team is team else (home, away)
    return {"week": week, "team": _lineup(*mine), "opponent": _lineup(*theirs)}


@tool
def get_free_agents(
    position: Literal["QB", "RB", "WR", "TE", "FLEX", "D/ST", "K"] | None = None,
    week: int | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    """Best available free agents and waiver players, most rostered first, with points and projections for a week."""
    lg = league()
    week = week or lg.current_week
    return {
        "week": week,
        "players": [
            {
                "name": p.name,
                "position": p.position,
                "nfl_team": p.proTeam,
                "injury": p.injuryStatus or None,  # ESPN leaves it out for D/ST, and espn-api fills in []
                "owned_pct": p.percent_owned,
                "projected": p.projected_points,
                "points": p.points,
                "season_points": p.total_points,
                "avg_points": p.avg_points,
                "opponent": p.pro_opponent,
                "bye": p.on_bye_week,
            }
            for p in lg.free_agents(week=week, size=limit, position=position)
        ],
    }


@tool
def get_player(name: str) -> dict:
    """Look up any NFL player by name (close spellings work): fantasy team, injury, season totals,
    week-by-week points and NFL opponents, and this week's projection. get_matchup has past projections."""
    lg = league()
    names = {key.lower(): key for key in lg.player_map if isinstance(key, str)}
    match = difflib.get_close_matches(name.lower(), names, n=1, cutoff=0.6)
    if not match:
        raise ToolError(f"No player found matching {name!r}.")
    # espn-api's player_info leaves out weekly projections. "11<year><week>" asks ESPN for this week's,
    # the only week it still has on the player card.
    card = lg.espn_request.get_player_card(
        [lg.player_map[names[match[0]]]], lg.finalScoringPeriod, [f"11{lg.year}{lg.current_week}"]
    )
    if not card["players"]:
        raise ToolError(f"No player found matching {name!r}.")
    player = Player(card["players"][0], lg.year, lg._get_all_pro_schedule())
    owner = lg.get_team_data(player.onTeamId)
    weeks = sorted({int(week) for week in player.schedule} | {week for week in player.stats if week})
    return {
        "name": player.name,
        "position": player.position,
        "nfl_team": player.proTeam,
        "injury": player.injuryStatus or None,
        "fantasy_team": owner.team_name if owner else "free agent",
        "owned_pct": player.percent_owned,
        "started_pct": player.percent_started,
        "season_points": player.total_points,
        "avg_points": player.avg_points,
        "projected_season_points": player.projected_total_points,
        "weeks": [
            {
                "week": week,
                "opponent": player.schedule.get(str(week), {}).get("team"),
                "points": player.stats.get(week, {}).get("points"),
                "projected": player.stats.get(week, {}).get("projected_points"),
            }
            for week in weeks
        ],
    }


@tool
def get_recent_activity(limit: Annotated[int, Field(ge=1, le=50)] = 15) -> list:
    """Recent league moves, newest first: free agent adds, waiver claims with FAAB bids, drops and trades."""
    # espn-api asks ESPN for two more pages per dropped player; try the league's player list first.
    lg = copy.copy(league())
    lg.player_info = lambda playerId: lg.player_map.get(playerId) or League.player_info(lg, playerId=playerId)
    return [
        {
            "date": _date(activity.date),
            "actions": [
                {
                    "team": getattr(team, "team_name", team),
                    "action": action,
                    "player": getattr(player, "name", player),
                    "bid": bid,
                }
                for team, action, player, bid in activity.actions
            ],
        }
        for activity in lg.recent_activity(size=limit)
    ]


def http_app():
    """The MCP endpoint lives at /<MCP_SECRET>/mcp, so only someone with the full URL can use it."""
    secret = os.environ.get("MCP_SECRET", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", secret):
        raise SystemExit("Set MCP_SECRET to at least 20 letters, digits, dashes or underscores.")
    return mcp.streamable_http_app(
        streamable_http_path=f"/{secret}/mcp", stateless_http=True, json_response=True, host="0.0.0.0"
    )


if __name__ == "__main__":
    uvicorn.run(http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
