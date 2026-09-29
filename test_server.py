"""Runs every tool against the espn-api project's sample ESPN data, directly and over HTTP.

The sample files are downloaded from GitHub once and cached in the temp folder. Run: pytest
"""

import json
import os
import socket
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import anyio
import httpx2
import pytest
import uvicorn

SECRET = "test-secret-0123456789abcdef"
# The sample league is from 2018. Calling it 2019 unlocks the tools ESPN only serves for 2019 onwards.
os.environ.update(LEAGUE_ID="123", ESPN_YEAR="2019", SWID="{6863-6934-3455}", MCP_SECRET=SECRET)

import server  # noqa: E402  (reads the settings above when imported)
from mcp import Client  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

SAMPLES_COMMIT = "663d726c82acdcd1e1f42ecaef35b993ce9ce455"
SAMPLES = f"https://raw.githubusercontent.com/cwendt94/espn-api/{SAMPLES_COMMIT}/tests/football/unit/data/"


def box_player(player_id, name, slot, points, projected):
    stats = [
        {"seasonId": 2019, "scoringPeriodId": 16, "statSourceId": source, "appliedTotal": total, "stats": {"42": 1}}
        for source, total in ((0, points), (1, projected))
    ]
    player = {"id": player_id, "fullName": name, "defaultPositionId": 2, "eligibleSlots": [2, 20], "proTeamId": 12}
    return {"lineupSlotId": slot, "playerPoolEntry": {"player": {**player, "injuryStatus": "ACTIVE", "stats": stats}}}


# ESPN "view" -> sample file name, or inline data where the samples have none.
ROUTES = {
    "mTeam,mRoster,mMatchup,mSettings,mStandings": "league_2018_data.json",
    "mDraftDetail": "league_draft_2018.json",
    "players_wl": "league_players_2018.json",
    "proTeamSchedules_wl": "pro_schedule_2024.json",
    "kona_player_info": "league_free_agents_2018.json",
    "kona_league_communication": "league_recent_activity_2019.json",
    "kona_playercard": "league_2019_playerCard.json",
    # How running backs (2) rank against Houston (34), KC's week 16 opponent in the sample NFL schedule.
    "mPositionalRatings": {
        "positionAgainstOpponent": {"positionalRatings": {"2": {"ratingsByOpponent": {"34": {"rank": 7}}}}}
    },
    "mMatchupScore,mScoreboard": {
        "schedule": [
            {
                "home": {
                    "teamId": 1,
                    "totalPoints": 101.5,
                    "rosterForCurrentScoringPeriod": {
                        "entries": [box_player(1, "Home Starter", 2, 20.5, 18.0), box_player(2, "Home Bench", 20, 3, 9)]
                    },
                },
                "away": {
                    "teamId": 2,
                    "totalPoints": 88.25,
                    "rosterForCurrentScoringPeriod": {"entries": [box_player(3, "Away Starter", 2, 12.25, 15.0)]},
                },
            }
        ]
    },
}


def sample(name):
    path = Path(tempfile.gettempdir()) / "espn-api-samples" / name
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(SAMPLES + name, partial)
        partial.replace(path)  # so a cut-off download is never mistaken for a finished one
    return json.loads(path.read_text())


REQUESTS = []  # (ESPN view, x-fantasy-filter header) for every request the server makes


def fake_espn(url, params=None, headers=None, cookies=None):
    view = params["view"] if isinstance(params["view"], str) else ",".join(params["view"])
    REQUESTS.append((view, json.loads(headers["x-fantasy-filter"]) if headers else None))
    data = sample(ROUTES[view]) if isinstance(ROUTES[view], str) else ROUTES[view]
    return SimpleNamespace(status_code=200, json=lambda: data)


mock.patch("requests.get", fake_espn).start()


def test_tools_read_the_sample_league():
    info = server.get_league_info()
    assert (info["name"], info["current_week"], info["your_team_id"]) == ("FXBG League", 16, 1)
    assert info["roster_slots"]["QB"] == 1 and {"stat": "TD Rush", "abbr": "RTD", "points": 6.0} in info["scoring"]

    standings = server.get_standings()
    assert len(standings["teams"]) == 10 and standings["teams"][0]["rank"] == 1

    team = server.get_team()
    assert team["team_id"] == 1 and any(p["season_points"] > 0 for p in team["roster"])
    assert team["schedule"][0]["weeks"] == [1] and team["schedule"][0]["result"] in "WLT"
    lg = server.league()
    with (
        mock.patch.object(server, "league", return_value=lg),
        mock.patch.dict(lg.settings.matchup_periods, {"16": [16, 17]}),  # a two-week playoff round
    ):
        assert server.get_team()["schedule"][-1]["weeks"] == [16, 17]

    matchup = server.get_matchup()
    assert (matchup["team"]["team_id"], matchup["opponent"]["team_id"]) == (1, 2)
    assert matchup["team"]["score"] == 101.5 and matchup["team"]["projected"] == 18.0  # bench doesn't count
    assert [p["slot"] for p in matchup["team"]["players"]] == ["RB", "BE"]
    assert matchup["team"]["players"][0]["opponent"] == "HOU"
    assert server.get_matchup(team_id=2)["team"]["name"] == matchup["opponent"]["name"]

    assert server.get_scoreboard()["matchups"][0]["away"]["score"] == 88.25
    assert server.get_free_agents(position="QB", limit=3)["players"]
    sent = next(filters for view, filters in reversed(REQUESTS) if view == "kona_player_info")["players"]
    assert (sent["filterSlotIds"]["value"], sent["limit"]) == ([0], 3)  # QB is slot 0

    player = server.get_player("james conor")  # close spellings work
    assert player["name"] == "James Conner" and player["weeks"][0]["points"] == 10.5
    sent = next(filters for view, filters in reversed(REQUESTS) if view == "kona_playercard")["players"]
    assert "11201916" in sent["filterStatsForTopScoringPeriodIds"]["additionalValue"]  # this week's projection

    before = len(REQUESTS)
    activity = server.get_recent_activity()
    actions = [action for day in activity for action in day["actions"]]
    assert actions[0]["team"] == "Perscription Mixon" and all(isinstance(a["player"], str) for a in actions)
    # Only the 7 players missing from the (2018) sample player list need their own ESPN request.
    assert [view for view, _ in REQUESTS[before:]].count("kona_playercard") == 7


def test_tools_explain_bad_requests():
    for bad_call in (
        lambda: server.get_matchup(week=17),
        lambda: server.get_team(team_id=99),
        lambda: server.get_player("zzzzzzzz"),
    ):
        with pytest.raises(ToolError):
            bad_call()


def test_http_endpoint_only_answers_on_the_secret_path():
    with mock.patch.dict(os.environ, MCP_SECRET="too-short"), pytest.raises(SystemExit):
        server.http_app()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    http = uvicorn.Server(uvicorn.Config(server.http_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not http.started:
        assert time.time() < deadline, "test server didn't start"
        time.sleep(0.05)

    base = f"http://127.0.0.1:{port}"

    async def talk(mode):
        async with Client(f"{base}/{SECRET}/mcp", mode=mode) as client:
            tools = (await client.list_tools()).tools
            standings = await client.call_tool("get_standings", {})
            bad = await client.call_tool("get_team", {"team_id": 99})
            with mock.patch("requests.get", return_value=SimpleNamespace(status_code=401)):
                denied = await client.call_tool("get_free_agents", {})
            return tools, standings, bad, denied

    try:
        assert httpx2.post(f"{base}/mcp", json={}).status_code == 404
        assert httpx2.post(f"{base}/wrong-secret-0123456789/mcp", json={}).status_code == 404
        for mode in ("legacy", "auto"):  # older clients and the 2026 protocol
            tools, standings, bad, denied = anyio.run(talk, mode)
            assert len(tools) == 8 and all(t.annotations.read_only_hint for t in tools)
            assert len(json.loads(standings.content[0].text)["teams"]) == 10
            assert bad.is_error and "get_standings" in bad.content[0].text
            assert denied.is_error and "ESPN request failed" in denied.content[0].text
    finally:
        http.should_exit = True
        thread.join()
