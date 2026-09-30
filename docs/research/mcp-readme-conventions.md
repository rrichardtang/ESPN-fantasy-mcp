# MCP server README conventions

Researched 2026-09-30 from primary sources only. Raw files were fetched from `raw.githubusercontent.com`.
`modelcontextprotocol.io` and `docs.github.com` were blocked by the network proxy (403). For those pages
I read the source files they are built from, in the owners' own repos:
[`modelcontextprotocol/modelcontextprotocol`](https://github.com/modelcontextprotocol/modelcontextprotocol) and
[`github/docs`](https://github.com/github/docs). No Stripe README was fetched.

## Summary

- GitHub says a README should cover what the project does, why it's useful, how to get started, where to
  get help, and who maintains it. Anything longer belongs somewhere else.
  ([about-readmes source](https://github.com/github/docs/blob/main/content/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes.md))
- The official reference servers all follow one pattern: a title, a one-paragraph pitch, any warnings,
  a **Tools** list, then **Installation / Configuration** per client, then Debugging, Build and License.
  So setup comes after the tools. ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md),
  [git](https://github.com/modelcontextprotocol/servers/blob/main/src/git/README.md),
  [filesystem](https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/README.md),
  [memory](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md))
- Company READMEs (GitHub, Playwright) put install buttons first because they target many clients, then
  list tools in full further down, often generated from the code. Cloudflare starts with a table of server
  URLs. ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md),
  [playwright-mcp](https://github.com/microsoft/playwright-mcp/blob/main/README.md),
  [mcp-server-cloudflare](https://github.com/cloudflare/mcp-server-cloudflare/blob/main/README.md))
- Each tool is documented by its `name`, a one-line description, and its parameters with type,
  required/optional and default. The better READMEs also say what the tool returns and whether it is read-only.
  This mirrors the fields in the MCP spec (`name`, `title`, `description`, `inputSchema`, `outputSchema`, `annotations`).
  ([spec: tools](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx))

## Conventions

### Section order
1. `# Name` plus 1-3 sentences on what it connects the model to and what that enables. Examples: fetch
   ("enables LLMs to retrieve and process content from web pages"), memory ("lets Claude remember information about the user across chats").
   ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md), [memory](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md))
2. Warnings go straight after the pitch, as GitHub alert blocks. Fetch uses `> [!CAUTION]` for local/internal
   IP access. The monorepo root uses `> [!WARNING]` to say the servers are reference code, not production-ready.
   ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md), [servers root](https://github.com/modelcontextprotocol/servers/blob/main/README.md))
3. Optional "Use cases" or "Key features" bullets to explain *why* someone would want it. GitHub has a
   "Use Cases" list. Playwright has "Key Features" ("Fast and lightweight", "LLM-friendly", "Deterministic").
   ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md), [playwright-mcp](https://github.com/microsoft/playwright-mcp/blob/main/README.md))
4. **Tools**, under `## Tools`, `### Available Tools` or `## API > ### Tools`.
5. **Installation**, then **Configuration**, with one subsection per client (Claude Desktop, VS Code, Zed...).
   ([git](https://github.com/modelcontextprotocol/servers/blob/main/src/git/README.md))
6. Customization or environment variables, then Debugging/Troubleshooting, Build/Development, License.
   ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md), [cloudflare](https://github.com/cloudflare/mcp-server-cloudflare/blob/main/README.md) has a "Troubleshooting" section)

### Tool documentation formats
- **Nested bullet list.** This is the dominant format. Fetch:
  `` - `fetch` - Fetches a URL ... `` followed by `` - `url` (string, required): URL to fetch `` and
  `` - `max_length` (integer, optional): ... (default: 5000) ``.
  ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md))
- **Explicit return line.** Git adds `Returns:` to every tool (e.g. "Returns: Diff output of unstaged changes").
  ([git](https://github.com/modelcontextprotocol/servers/blob/main/src/git/README.md))
- **Behavior notes and best practice.** Filesystem adds constraints ("Cannot specify both `head` and `tail`"),
  failure behavior ("Failed reads won't stop the entire operation") and advice ("Always use dryRun first").
  ([filesystem](https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/README.md))
- **Why a parameter exists.** Fetch explains that responses are truncated and `start_index` lets the model
  "read a webpage in chunks". ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md))
- **Read-only flag per tool.** Playwright lists `Title`, `Description`, `Parameters` and `Read-only: **true/false**`.
  Filesystem has a table of `readOnlyHint` / `idempotentHint` / `destructiveHint` for every tool.
  ([playwright-mcp](https://github.com/microsoft/playwright-mcp/blob/main/README.md), [filesystem](https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/README.md))
- **Grouping and generation.** When there are many tools, they are collapsed into `<details>` groups (GitHub,
  Playwright) and generated from code between marker comments (`<!-- START AUTOMATED TOOLS -->`,
  `update-readme.js`), so the README can't drift from the code. For 9 tools, a single flat table or list is enough.
  ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md), [playwright-mcp](https://github.com/microsoft/playwright-mcp/blob/main/README.md))
- **Tables** are used for summaries: Cloudflare's server/description/URL table and filesystem's annotations table.
  A `Tool | What it answers` table works as an overview, with details below it if parameters matter.
- **Spec alignment.** Tool names should be 1-128 characters, case-sensitive, using `[A-Za-z0-9_.-]` only, and
  unique within the server. The README should use the exact registered names.
  ([spec: tools](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx))
- **Example prompts.** Memory includes a ready-to-paste "System Prompt" section showing how to get the model
  to use the tools. ([memory](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md))

### Badges
- The reference servers' READMEs have **no badges**. ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md), [git](https://github.com/modelcontextprotocol/servers/blob/main/src/git/README.md))
- Company READMEs use badges almost only as one-click **install buttons** (shields.io "Install in VS Code" deep links).
  GitHub also has one quality badge (Go Report Card). ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md), [playwright-mcp](https://github.com/microsoft/playwright-mcp/blob/main/README.md))
- Takeaway: badges are there to do a job, not for decoration. A single-user Cloud Run connector has no
  install deep link, so leaving badges out matches the reference style. A CI badge is the only one worth considering.

### Setup guide patterns
- Setup comes after the tools in every reference server (e.g. git: Tools at line 15, Installation at line 103).
  ([git](https://github.com/modelcontextprotocol/servers/blob/main/src/git/README.md))
- Mark one recommended path ("Using uv (recommended)") and put alternatives in collapsed `<details>` blocks
  ("Using uvx", "Using docker"). ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md))
- Remote servers keep it short: list the prerequisites, then "connect any MCP client ... directly to a URL".
  ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md) "Prerequisites"; [cloudflare](https://github.com/cloudflare/mcp-server-cloudflare/blob/main/README.md) "Connect to an MCP server")
- Configuration options (flags or env vars) go in their own section after install
  ([fetch](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md) "Customization - ...").
- Keep the README to what's needed to get started and move long material elsewhere (GitHub suggests a wiki).
  Content over 500 KiB is truncated. ([about-readmes source](https://github.com/github/docs/blob/main/content/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes.md))
- GitHub builds an "Outline" table of contents from headings automatically, so a hand-written TOC is optional.
  (same source)

### Security notes
- Say plainly what the server can reach and what it is *not*. Playwright: "Playwright MCP is **not** a
  security boundary", linking the MCP Security Best Practices. ([playwright-mcp](https://github.com/microsoft/playwright-mcp/blob/main/README.md))
- Credential hygiene as a short list: minimum scopes, separate tokens, rotation, "Never commit", restrict
  file permissions. ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md) "Token Security Best Practices")
- Document read-only mode as a feature. GitHub has a whole "Read-Only Mode" section (`--read-only`,
  `GITHUB_READ_ONLY=1`). ([github-mcp-server](https://github.com/github/github-mcp-server/blob/main/README.md))
- The spec says there SHOULD always be a human in the loop who can deny tool calls, and clients MUST treat
  annotations (like `readOnlyHint`) as untrusted unless the server is trusted. So a README claiming "read-only"
  should back it up with the code, e.g. no write calls. ([spec: tools](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx))

## Recommended outline for this repo's README

This repo's server already sets `ToolAnnotations(read_only_hint=True)` on every tool (`server.py`, `tool()`
decorator) and returns JSON. The endpoint is secret-path-protected (`/<MCP_SECRET>/mcp`).

1. `# ESPN-fantasy-mcp`, 2-3 sentences: what it reads, where it runs (Cloud Run custom connector), and that it
   is read-only. No badges (optionally one CI badge).
2. `> [!IMPORTANT]` or `> [!WARNING]`: the connector URL and `espn_s2`/`SWID` act like a password. Anyone with
   the URL can read the league.
3. `## What you can ask`: 3-5 example questions that show *why* it's useful (e.g. "Who should I pick up at RB?",
   "How did my matchup go last week?"). This follows GitHub's "Use Cases" and memory's example prompt.
4. `## Tools`: keep the current `Tool | What it answers` table. Add a short parameters column or bullets where
   parameters exist: `get_team(team_id?)`, `get_scoreboard(week?)`, `get_matchup(team_id?, week?)`,
   `get_free_agents(position?, week?, limit=25, 1-100)`, `get_player(name)`, `get_defense_injuries(nfl_teams, 1-8)`,
   `get_recent_activity(limit=15, 1-50)`. Also note that `team_id` defaults to your team, an empty week means the
   current week, every tool is read-only (`readOnlyHint`), and results are JSON.
5. `## Setup`: the current three steps, kept short. Move the "why" text into one sentence per step. Put the
   cookie screenshot/details in `<details>` if the section grows.
6. `## Configuration`: the env var table (already present).
7. `## Troubleshooting / Updating`: the current "Later" bullets, renamed.
8. `## Development`: the test command. Add `## License` if one is added to the repo.
