"""Runs the coach's loop against a scripted Claude and a small in-process MCP server. Run: pytest"""

import io
import json

import anthropic
import anyio
import httpx2
from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import agent

league = MCPServer("fake-league")


@league.tool()
def get_league_info() -> str:
    return json.dumps({"current_week": 4, "scoring": [{"stat": "Each reception", "abbr": "REC", "points": 0.5}]})


@league.tool()
def get_standings() -> str:
    return json.dumps({"teams": [{"team_id": 3, "name": "GTO Wizards", "record": "1-2-0"}]})


@league.tool()
def get_player(name: str) -> str:
    if name != "Bijan Robinson":
        raise ToolError(f"No player found matching {name!r}.")
    return json.dumps({"name": name, "bye_week": 11})


def reply(content, stop_reason):
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": agent.MODEL, "content": content,
        "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def lookup(id, player):
    return {"type": "tool_use", "id": id, "name": "get_player", "input": {"name": player}}


# Claude looks up two players, one misspelled, answers, then answers a follow-up.
SCRIPT = [
    reply([{"type": "text", "text": "Checking."}, lookup("t1", "Bijan Robinson"), lookup("t2", "Bjian")], "tool_use"),
    reply([{"type": "text", "text": "Start Bijan. Bijan's bye is week 11."}], "end_turn"),
    reply([{"type": "text", "text": "Yes, still Bijan."}], "end_turn"),
]


def test_coach_runs_tools_and_keeps_the_conversation():
    requests = []

    def claude(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=SCRIPT[len(requests) - 1])

    client = anthropic.AsyncAnthropic(
        api_key="test", http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(claude))
    )

    async def run():
        async with Client(league) as mcp:
            tools = [async_mcp_tool(t, mcp) for t in (await mcp.list_tools()).tools]
            log = io.StringIO()
            coach = agent.Coach(client, mcp, tools, await agent.brief(mcp), log=log)
            return await coach.ask(agent.JOBS["lineup"]), await coach.ask("Sure?"), log.getvalue()

    first, second, log = anyio.run(run)
    assert (first, second) == ("Start Bijan. Bijan's bye is week 11.", "Yes, still Bijan.")
    assert "get_player" in log and "No player found matching 'Bjian'" in log

    opening = requests[0]["messages"][0]["content"]
    assert "Each reception" in opening and "GTO Wizards" in opening and opening.endswith(agent.JOBS["lineup"])
    assert requests[0]["fallbacks"] == "default" and requests[0]["model"] == agent.MODEL

    results = requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "bye_week" in json.dumps(results[0]["content"]) and results[1]["is_error"]

    # The follow-up carries the brief once, both tool rounds, and the first answer.
    history = requests[2]["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant", "user"]
    assert history[-1]["content"] == "Sure?"
