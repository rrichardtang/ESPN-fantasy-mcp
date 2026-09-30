# ESPN Fantasy MCP

An [MCP](https://modelcontextprotocol.io) server that gives Claude live, read-only access to one ESPN
fantasy football league: rosters, matchups, free agents, NFL injuries and bye weeks. Ask Claude who to
start, who to pick up or how your matchup is going, and it answers from your league's real data instead
of guessing.

It runs on Google Cloud Run, and you add it to Claude once as a custom connector. After that it works
in claude.ai, the Claude apps and Claude Code.

> [!IMPORTANT]
> Your connector URL and ESPN cookies work like a password. Anyone with the URL can read your league.
> Keep both out of chats, screenshots and git.

## What you can ask

- "Who should I start at flex this week? Check injuries and byes."
- "Which free agent running back should I pick up for week 6?"
- "My D/ST plays Carolina. How banged up is their secondary?"
- "How am I doing against Gibble right now, player by player?"
- "Who in my league is thin at QB and might trade for one of mine?"

## Tools

Every tool is read-only and returns JSON. `team_id` defaults to your own team, and an empty `week`
means the current week.

| Tool | What it answers | Parameters |
|---|---|---|
| `get_league_info` | Scoring rules, roster slots, playoff format, trade deadline, FAAB budget | none |
| `get_standings` | Every team's id, record, points for and against, and streak | none |
| `get_team` | A roster with season points and bye weeks, plus the full schedule | `team_id` |
| `get_scoreboard` | Every matchup in a week, with live and projected scores | `week` |
| `get_matchup` | Both lineups in one matchup, player by player: points, projection, opponent, bye | `team_id`, `week` |
| `get_free_agents` | The best available players, most rostered first, with projections and bye weeks | `position`, `week`, `limit` (1-100, default 25) |
| `get_player` | Any NFL player, week by week: points, opponents, injury, bye week, owner | `name` (close spellings work) |
| `get_defense_injuries` | Injured defensive players on up to 8 NFL teams, with their season stats | `nfl_teams`, such as `["CAR", "NYG"]` |
| `get_recent_activity` | Adds, drops, waiver claims with bids, and trades, newest first | `limit` (1-50, default 15) |

### Why they help

- **Bye weeks are built in.** Every player comes with a `bye_week`, and a bye shows as `BYE` in place
  of an opponent. The server tells Claude never to suggest starting or adding a player for their bye
  week.
- **Defense injuries show matchups.** Your league rosters whole team defenses, so the other tools never
  mention individual defenders. `get_defense_injuries` adds the injured cornerbacks, linemen and
  linebackers behind a D/ST. That helps
  you judge your own defense and the defense your receivers face. Season tackles, sacks and weeks
  played show whether the injured player is a starter or a backup.
- **Your league's rules, not generic rankings.** Projections, points and roster slots come from your
  league's own scoring settings. A 2-QB or half-PPR league gets advice that fits it.
- **Live during games.** `get_scoreboard` and `get_matchup` show scores as they happen. League data is
  cached for at most one minute.

## Setup

You need a Google Cloud project with billing turned on (the free trial counts). Setup takes about 10
minutes.

**1. Get your league ID and cookies.** Open your league at https://fantasy.espn.com in Chrome. The
league ID is the number after `leagueId=` in the address bar. Then press F12, open **Application** >
**Cookies** > `https://fantasy.espn.com`, and copy `espn_s2` and `SWID` (keep SWID's braces). Public
leagues can skip `espn_s2`, but `SWID` tells the tools which team is yours.

**2. Deploy.** Open https://console.cloud.google.com, click **Activate Cloud Shell** (the `>_` button,
top right), and run:

```bash
git clone https://github.com/rrichardtang/ESPN-fantasy-mcp
cd ESPN-fantasy-mcp
./deploy.sh
```

Enter the league ID and cookies when asked, and answer `y` to any yes/no questions. The script prints
your connector URL at the end. If it stops with an error, run `./deploy.sh` again. Nothing is lost.

**3. Connect Claude.** At https://claude.ai/customize/connectors, add a custom connector named
`ESPN Fantasy` with the connector URL. Start a new chat or session so the tools load.

## Coach agent

`agent.py` is a command-line coach built on the same tools. It starts every chat with your league's
rules and standings, then follows a playbook: check injuries, byes and opposing defenses before any
call, quote the numbers, and fill every roster slot legally. It needs a Claude API key.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-agent.txt
export ANTHROPIC_API_KEY=...  ESPN_MCP_URL=...   # your connector URL
.venv/bin/python agent.py lineup     # or waivers, matchup, trades, recap
.venv/bin/python agent.py "Should I trade Bijan for two receivers?"
.venv/bin/python agent.py            # chat
```

Without `ESPN_MCP_URL` it runs the server in-process instead, using `LEAGUE_ID`, `ESPN_S2` and `SWID`.
`agent.py --brief` prints what the coach starts with, without calling Claude.

<details>
<summary><b>Configuration</b></summary>

`deploy.sh` sets these environment variables on the first run.

| Variable | Meaning |
|---|---|
| `LEAGUE_ID` | Your ESPN league ID (required) |
| `ESPN_S2`, `SWID` | Your ESPN login cookies (needed for private leagues) |
| `MCP_SECRET` | Random text in the connector URL: at least 20 letters, digits, dashes or underscores (required) |
| `ESPN_YEAR` | Season to read, 2019 or later. Defaults to the current season, which starts each August |

</details>

<details>
<summary><b>Updating and troubleshooting</b></summary>

- **Get new code:** in Cloud Shell, run `cd ESPN-fantasy-mcp && git pull && ./deploy.sh`. Your
  settings and connector URL stay the same.
- **"Cannot be accessed with the provided credentials":** your cookies expired. Get fresh ones (step
  1), then in the Cloud Console open **Cloud Run** > `espn-fantasy-mcp` > **Edit & deploy new
  revision** > **Variables & Secrets**, and replace `ESPN_S2` and `SWID`.
- **New tools don't show up:** start a new chat. Claude loads connectors when a chat starts.

</details>

<details>
<summary><b>Development</b></summary>

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-agent.txt pytest && .venv/bin/pytest
```

The tests run every tool against sample ESPN data from the
[espn-api](https://github.com/cwendt94/espn-api) project, which the first run downloads.

</details>
