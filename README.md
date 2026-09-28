# ESPN-fantasy-mcp

Lets Claude read your ESPN fantasy football league. It runs on Google Cloud Run, and you add it to
Claude once as a custom connector. After that it works in Claude Code cloud sessions, claude.ai and
the Claude app. It can only read. It can't set lineups or make moves.

| Tool | What it answers |
|---|---|
| `get_league_info` | Scoring rules, roster slots, playoff format, trade deadline, FAAB budget |
| `get_standings` | Every team's record, points and streak |
| `get_team` | A roster with season points, plus the weekly schedule |
| `get_scoreboard` | All matchups in a week, with live and projected scores |
| `get_matchup` | Both lineups in one matchup, player by player |
| `get_free_agents` | The best available players, by position |
| `get_player` | Any NFL player, week by week |
| `get_recent_activity` | Adds, drops, waiver claims and trades |

## Set it up (once)

You need a computer for step 1. Everything else works in a browser.

### 1. Get your league ID and ESPN cookies

1. In Chrome, log in at https://fantasy.espn.com and open your league.
2. Copy the number after `leagueId=` in the address bar. That's your league ID.
3. Press F12 (Mac: Cmd+Option+I), open the **Application** tab, then **Cookies** > `https://fantasy.espn.com`.
4. Copy the values of `espn_s2` and `SWID`. SWID looks like `{1A2B3C4D-...}`. Keep the braces.

The two cookies work like your ESPN password. Don't paste them into chats or commit them to GitHub.
Public leagues don't need them, but `SWID` lets the tools know which team is yours.

### 2. Deploy to Google Cloud

Your project needs billing turned on. The free trial counts.

1. Open https://console.cloud.google.com with your project selected, then click the **>_** button
   (Activate Cloud Shell) at the top right.
2. Paste:
   ```
   git clone https://github.com/rrichardtang/ESPN-fantasy-mcp
   cd ESPN-fantasy-mcp
   ./deploy.sh
   ```
3. Enter the league ID and cookies when asked. If Google asks a yes/no question, answer `y`.
   The first deploy takes a few minutes. If it stops with an error, wait a minute and run
   `./deploy.sh` again. Nothing is lost.
4. Copy the connector URL it prints at the end. Keep it private: anyone with it can read your league.

### 3. Connect Claude

1. Go to https://claude.ai/customize/connectors and add a custom connector named `ESPN Fantasy`,
   using the connector URL.
2. Start a new Claude Code session. Connectors load when a session starts.

## Later

- **New code:** in Cloud Shell, run `cd ESPN-fantasy-mcp && git pull && ./deploy.sh`. It keeps your
  settings and the connector URL stays the same.
- **Claude says your league "cannot be accessed with the provided credentials":** your cookies
  expired. Get fresh ones (step 1), then in the Cloud Console open Cloud Run > `espn-fantasy-mcp` >
  **Edit & deploy new revision** > **Variables & Secrets**, and replace `ESPN_S2` and `SWID`.
- **Run the tests:** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest && .venv/bin/pytest`.
  The first run downloads sample ESPN data from the [espn-api](https://github.com/cwendt94/espn-api) project.

## Settings

The server reads these environment variables. `deploy.sh` sets them for you.

| Variable | Meaning |
|---|---|
| `LEAGUE_ID` | Your ESPN league ID (required) |
| `ESPN_S2`, `SWID` | Your ESPN login cookies (needed for private leagues) |
| `MCP_SECRET` | Random text in the connector URL: at least 20 letters, digits, dashes or underscores (required) |
| `ESPN_YEAR` | Season to read, 2019 or later. Defaults to the current season, which starts each August. Set it to last season if your league hasn't renewed yet |
