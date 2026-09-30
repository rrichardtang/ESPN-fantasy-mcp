"""A panel of fantasy football experts that answers from your league's live data through the ESPN MCP tools.

Fantasy Fred (fantasy strategy) and Analytic Alan (football analysis, with web search) answer on their own,
rebut each other once, and a judge gives the verdict. Their instructions live in experts/.

    python agent.py                # chat
    python agent.py lineup         # one of the ready-made jobs in JOBS
    python agent.py "Should I trade Bijan for two WRs?"
    python agent.py --quick lineup # ask Fred alone: cheaper and faster
    python agent.py --brief        # show the league brief and each expert's tools, without calling Claude

It talks to your deployed server when ESPN_MCP_URL is set (the connector URL), and otherwise runs
server.py in-process with the same LEAGUE_ID, ESPN_S2 and SWID settings. Claude needs ANTHROPIC_API_KEY.
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import anthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import Client

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

RULES = """You sit on a panel that advises the manager of one ESPN fantasy football league. You read the \
league through read-only tools.

Shared rules:
- The first message has a league brief: today's date, the current week, roster slots, scoring and \
standings. Trust it and don't fetch it again.
- Call independent tools in parallel. Don't stop at one tool when a second would change the answer: \
check injuries, byes and matchups before any start, sit, add or trade call.
- Every claim about a player comes from a tool result or a cited source in this chat. Quote the numbers \
(projection, points, owned %, bye week). If you didn't look something up, say so rather than guess. Your \
memory of NFL depth charts and trades may be out of date; the tools are not.
- Never start a player, or add one for a week, during their bye week, or when they are OUT, DOUBTFUL, \
on IR or suspended. For a QUESTIONABLE starter, name the bench backup who plays later.
- Fit the league's rules: fill every roster slot legally (RB/WR/TE is a flex slot).
- You can't make moves. Say exactly what to change in the ESPN app.

"""

EXPERTS = Path(__file__).parent / "experts"
TITLES = {"fred": "Fantasy Fred", "alan": "Analytic Alan"}
ALAN_TOOLS = {"get_player", "get_matchup", "get_defense_injuries", "get_team"}
WEB_SEARCH = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 8,
    "allowed_domains": [
        "espn.com", "nfl.com", "pro-football-reference.com", "pff.com",
        "nytimes.com", "rotowire.com", "cbssports.com", "actionnetwork.com",
    ],
}
PANEL_NOTES = {
    "fred": """
For the panel:
- Write concise notes for the other panelists, not a polished answer for the manager: your recommendation \
first, then the numbers behind it, then what would change your mind.
- Analytic Alan covers football detail (role, scheme, injuries, game script). When you rebut Alan, translate \
those points into fantasy value and say which ones actually move the decision.
""",
    "alan": """
For the panel:
- Write concise notes for the other panelists, not a polished answer for the manager: your read first, then \
the evidence with sources, then what would change your mind.
- When you rebut Fred, check the football behind the fantasy math: a projection that ignores a role change, \
an injury or the likely game script is the thing to flag.
""",
}
QUICK_NOTE = """
You are answering the manager directly: decision first, a table for lineups, brief, and cover injuries, \
byes and matchups yourself.
"""
CUT_OFF = """{what} was cut off or declined, so it is left out. Rule on the evidence you do have plus your own \
tool checks."""
REBUTTAL = """Here is {title}'s take on the same question.

<{name}_take>
{take}
</{name}_take>

Give one rebuttal: where you agree, where you disagree and why, and what, if anything, you'd change in \
your recommendation."""

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


def tool_name(tool) -> str:
    return tool["name"] if isinstance(tool, dict) else tool.name


class Expert:
    def __init__(self, name: str, system: str, tools: list, client: anthropic.AsyncAnthropic, league_brief: str,
                 log=sys.stderr):
        self.name, self.system, self.tools, self.client, self.log = name, system, tools, client, log
        self.messages = []
        self.complete = True
        self.container = None
        self.league_brief = league_brief

    async def ask(self, question: str) -> str:
        if not self.messages:
            question = f"{self.league_brief}\n\n{question}"
        self.messages.append({"role": "user", "content": question})
        runner = self.client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=16000,
            max_iterations=25,
            system=self.system,
            messages=self.messages,
            tools=self.tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            cache_control={"type": "ephemeral"},
            # If a safety check declines the request, the API retries it on another model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            container=self._live_container_id() or anthropic.omit,
        )
        message = None
        async for message in runner:
            # Keep the whole reply, thinking included, so the next question continues this conversation.
            self.messages.append(message.to_param())
            if message.container:
                self.container = message.container
            for block in message.content:
                if block.type in ("tool_use", "server_tool_use"):
                    args = json.dumps(block.input) if block.input else ""
                    print(f"  {self.name} → {block.name}({args})", file=self.log)
            results = await runner.generate_tool_call_response()
            if results:
                self.messages.append(results)
                for result in results["content"]:
                    if result.get("is_error"):
                        print(f"  {self.name} ✗ {result['content']}", file=self.log)
        self.complete = message.stop_reason == "end_turn"
        if message.stop_reason == "refusal":
            return "Claude declined to answer that."
        text = "\n".join(block.text for block in message.content if block.type == "text")
        if not self.complete:
            text += "\n\n(Cut off before finishing. Ask again to let it continue.)"
        return text

    def _live_container_id(self):
        if self.container and self.container.expires_at > datetime.now(timezone.utc):
            return self.container.id


class Panel:
    """Fred and Alan answer independently, rebut each other once, and the judge gives the verdict."""

    def __init__(self, client: anthropic.AsyncAnthropic, espn_tools: list, league_brief: str, log=sys.stderr,
                 quick=False):
        def expert(name, tools):
            notes = QUICK_NOTE if quick and name == "fred" else PANEL_NOTES.get(name, "")
            system = RULES + (EXPERTS / f"{name}.md").read_text() + notes
            return Expert(name, system, tools, client, league_brief, log)

        self.fred = expert("fred", espn_tools)
        self.alan = expert("alan", [WEB_SEARCH, *(t for t in espn_tools if t.name in ALAN_TOOLS)])
        self.judge = expert("judge", espn_tools)
        self.log = log

    async def _speak(self, expert: Expert, prompt: str, heading: str = "") -> str:
        text = await expert.ask(prompt)
        print(f"\n## {TITLES[expert.name]}{heading}\n\n{text}", file=self.log)
        return text

    async def _rebut(self, expert: Expert, other: str, take: str) -> str:
        return await self._speak(expert, REBUTTAL.format(title=TITLES[other], name=other, take=take), " — rebuttal")

    async def ask(self, question: str) -> str:
        fred_take, alan_take = await asyncio.gather(self._speak(self.fred, question), self._speak(self.alan, question))
        takes = {"fred": fred_take, "alan": alan_take}
        cut = [name for name in takes if not getattr(self, name).complete]
        texts = {f"{name}_take": take for name, take in takes.items() if name not in cut}
        lost = [f"{TITLES[name]}'s answer" for name in cut]
        if not cut:
            rebuttals = await asyncio.gather(
                self._rebut(self.fred, "alan", alan_take), self._rebut(self.alan, "fred", fred_take)
            )
            for name, text in zip(takes, rebuttals):
                if getattr(self, name).complete:
                    texts[f"{name}_rebuttal"] = text
                else:
                    lost.append(f"{TITLES[name]}'s rebuttal")
        debate = "\n\n".join(f"<{tag}>\n{text}\n</{tag}>" for tag, text in texts.items())
        notes = "".join(CUT_OFF.format(what=what) + "\n\n" for what in lost)
        return await self.judge.ask(f"<question>\n{question}\n</question>\n\n{debate}\n\n{notes}Give the final answer.")


async def main(args: list[str]) -> None:
    quick = "--quick" in args
    args = [a for a in args if a != "--quick"]
    async with connect() as mcp:
        tools = [async_mcp_tool(t, mcp) for t in (await mcp.list_tools()).tools]
        league_brief = await brief(mcp)
        panel = Panel(anthropic.AsyncAnthropic(), tools, league_brief, quick=quick)
        if args == ["--brief"]:
            print(league_brief)
            for expert in (panel.fred, panel.alan, panel.judge):
                print(f"{expert.name}: " + ", ".join(map(tool_name, expert.tools)))
            return

        async def answer(question: str) -> str:
            if quick:
                return await panel.fred.ask(question)
            return "## Verdict\n\n" + await panel.ask(question)

        if args:
            print(await answer(JOBS.get(args[0], " ".join(args))))
            return
        print(f"Ask about your league, or type one of: {', '.join(JOBS)}. Ctrl-D quits.")
        while True:
            try:
                question = input("\n> ").strip()
            except EOFError:
                return
            if question:
                print("\n" + await answer(JOBS.get(question, question)))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
