"""A fantasy football coach that answers from your league's live data through the ESPN MCP tools.

    python agent.py                # chat
    python agent.py lineup         # one of the ready-made jobs in JOBS
    python agent.py "Should I trade Bijan for two WRs?"
    python agent.py --brief        # show what the coach starts with, without calling Claude

It talks to your deployed server when ESPN_MCP_URL is set (the connector URL), and otherwise runs
server.py in-process with the same LEAGUE_ID, ESPN_S2 and SWID settings. Claude needs ANTHROPIC_API_KEY.
"""

import asyncio
import json
import os
import sys
from datetime import date

import anthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import Client

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM = """You are a sharp fantasy football coach for one ESPN league. You read the league through \
read-only tools and give decisions the manager can act on today.

How you work:
- The first message has a league brief: today's date, the current week, roster slots, scoring and \
standings. Trust it and don't fetch it again.
- Call independent tools in parallel. Don't stop at one tool when a second would change the answer: \
check injuries, byes and matchups before any start, sit, add or trade call.
- Every claim about a player comes from a tool result in this chat. Quote the numbers (projection, \
points, owned %, bye week). If you didn't look something up, say so rather than guess. Your memory of \
NFL depth charts and trades may be out of date; the tools are not.
- Never start a player, or add one for a week, during their bye week, or when they are OUT, DOUBTFUL, \
on IR or suspended. For a QUESTIONABLE starter, name the bench backup who plays later.
- Fit the league's rules: fill every roster slot legally (RB/WR/TE is a flex slot), weigh positions \
by how many start (two QB slots make QBs scarce), and value catches by the reception points.
- Projections are the baseline. Move off them only for a stated reason: an injured defense \
(get_defense_injuries), a teammate's injury, a trend over recent weeks (get_player), or a bye.
- You can't make moves. Tell the manager exactly what to change in the ESPN app.

How you answer: the decision first, then a short reason for each change, then risks worth watching. \
Use a table for lineups. Be brief; the manager is on a phone."""

JOBS = {
    "lineup": "Set my best lineup for this week. Compare every starter with my bench, and say which "
    "slots to change. Check injuries, byes and the defenses my borderline players face.",
    "waivers": "Who should I pick up and drop this week? Look at my weak slots and my upcoming bye weeks, "
    "then the best free agents at those positions for this week and next.",
    "matchup": "Scout my matchup this week. Where am I ahead or behind, position by position, and what "
    "could swing it? If games have started, tell me where things stand.",
    "trades": "Find trades worth offering. Compare my roster's depth with every other team's, name the "
    "teams whose needs fit my surplus, and suggest fair offers.",
    "recap": "Recap last week for the whole league: results, standouts, busts, and what it means for "
    "the standings.",
}


def connect() -> Client:
    url = os.environ.get("ESPN_MCP_URL")
    if url:
        return Client(url)
    import server  # reads LEAGUE_ID, ESPN_S2 and SWID when imported

    return Client(server.mcp)


async def brief(mcp: Client) -> str:
    """The league facts every answer needs, fetched once so Claude doesn't spend turns on them."""
    info, standings = await asyncio.gather(
        mcp.call_tool("get_league_info", {}), mcp.call_tool("get_standings", {})
    )
    for result in (info, standings):
        if result.is_error:
            raise SystemExit(f"The ESPN tools failed: {result.content[0].text}")
    info, standings = json.loads(info.content[0].text), json.loads(standings.content[0].text)
    info["scoring"] = {s["stat"]: s["points"] for s in info["scoring"]}
    return (
        f"<league_brief>\nToday is {date.today().isoformat()}.\n"
        f"League: {json.dumps(info)}\nStandings: {json.dumps(standings['teams'])}\n</league_brief>"
    )


class Coach:
    def __init__(self, client: anthropic.AsyncAnthropic, mcp: Client, tools, league_brief: str, log=sys.stderr):
        self.client, self.mcp, self.tools, self.log = client, mcp, tools, log
        self.messages = []
        self.league_brief = league_brief

    async def ask(self, question: str) -> str:
        if not self.messages:
            question = f"{self.league_brief}\n\n{question}"
        self.messages.append({"role": "user", "content": question})
        runner = self.client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=16000,
            max_iterations=25,
            system=SYSTEM,
            messages=self.messages,
            tools=self.tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            cache_control={"type": "ephemeral"},
            # If a safety check declines the request, the API retries it on another model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        message = None
        async for message in runner:
            # Keep the whole reply, thinking included, so the next question continues this conversation.
            self.messages.append(message.to_param())
            for block in message.content:
                if block.type == "tool_use":
                    print(f"  → {block.name}({json.dumps(block.input) if block.input else ''})", file=self.log)
            results = await runner.generate_tool_call_response()
            if results:
                self.messages.append(results)
                for result in results["content"]:
                    if result.get("is_error"):
                        print(f"  ✗ {result['content']}", file=self.log)
        if message.stop_reason == "refusal":
            return "Claude declined to answer that."
        text = "\n".join(block.text for block in message.content if block.type == "text")
        if message.stop_reason == "tool_use":
            text += "\n\n(Stopped after 25 steps. Ask again to let it continue.)"
        return text


async def main(args: list[str]) -> None:
    async with connect() as mcp:
        tools = [async_mcp_tool(t, mcp) for t in (await mcp.list_tools()).tools]
        league_brief = await brief(mcp)
        if args == ["--brief"]:
            print(SYSTEM, league_brief, "Tools: " + ", ".join(t.name for t in tools), sep="\n\n")
            return
        coach = Coach(anthropic.AsyncAnthropic(), mcp, tools, league_brief)
        if args:
            print(await coach.ask(JOBS.get(args[0], " ".join(args))))
            return
        print(f"Ask about your league, or type one of: {', '.join(JOBS)}. Ctrl-D quits.")
        while True:
            try:
                question = input("\n> ").strip()
            except EOFError:
                return
            if question:
                print("\n" + await coach.ask(JOBS.get(question, question)))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
