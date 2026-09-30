"""Runs the experts' loop and the panel against a scripted Claude and a small in-process MCP server. Run: pytest"""

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


@league.tool()
def get_free_agents() -> str:
    return json.dumps([])


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


def fake_claude(respond):
    return anthropic.AsyncAnthropic(
        api_key="test", http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(respond))
    )


def test_expert_runs_tools_and_keeps_the_conversation():
    requests = []

    def claude(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=SCRIPT[len(requests) - 1])

    client = fake_claude(claude)

    async def run():
        async with Client(league) as mcp:
            tools = [async_mcp_tool(t, mcp) for t in (await mcp.list_tools()).tools]
            log = io.StringIO()
            expert = agent.Expert("fred", "Be Fred.", tools, client, await agent.brief(mcp), log=log)
            return await expert.ask(agent.JOBS["lineup"]), await expert.ask("Sure?"), log.getvalue()

    first, second, log = anyio.run(run)
    assert (first, second) == ("Start Bijan. Bijan's bye is week 11.", "Yes, still Bijan.")
    assert "fred → get_player" in log and "No player found matching 'Bjian'" in log

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


SEARCH = [
    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "Bijan snap share"}},
    {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
        {"type": "web_search_result", "url": "https://espn.com/bijan", "title": "Bijan", "encrypted_content": "x"}
    ]},
]
# Each speaker's replies in turn, found by the first line of its expert file.
PANEL = {
    "You are Fantasy Fred": ["FRED TAKE: start Bijan.", "FRED REBUTTAL: agree with Alan."],
    "You are Analytic Alan": ["ALAN TAKE: Bijan plays 80% of snaps.", "ALAN REBUTTAL: Fred's math holds."],
    "You are the judge": ["VERDICT: start Bijan."],
}


def run_panel(alan_stop="end_turn", alan_rebuttal_stop="end_turn"):
    requests = {speaker: [] for speaker in PANEL}

    def claude(request):
        body = json.loads(request.content)
        speaker = next(s for s in PANEL if s in json.dumps(body["system"]))
        requests[speaker].append(body)
        turn = len(requests[speaker]) - 1
        content = [{"type": "text", "text": PANEL[speaker][turn]}]
        stop = "end_turn"
        if speaker == "You are Analytic Alan":
            stop = alan_stop if turn == 0 else alan_rebuttal_stop
            content = SEARCH + content if turn == 0 else content
        return httpx2.Response(200, json=reply(content, stop))

    async def run():
        async with Client(league) as mcp:
            tools = [async_mcp_tool(t, mcp) for t in (await mcp.list_tools()).tools]
            log = io.StringIO()
            panel = agent.Panel(fake_claude(claude), tools, await agent.brief(mcp), log=log)
            return await panel.ask("Start Bijan?"), log.getvalue()

    verdict, log = anyio.run(run)
    return verdict, log, *requests.values()


def test_panel_debates_then_the_judge_decides():
    verdict, log, fred, alan, judge = run_panel()
    assert verdict == "VERDICT: start Bijan."
    assert 'alan → web_search({"query": "Bijan snap share"})' in log and "## Analytic Alan — rebuttal" in log

    alan_tools = {t["name"]: t for t in alan[0]["tools"]}
    assert alan_tools["web_search"]["allowed_domains"] and "get_free_agents" not in alan_tools
    assert "web_search" not in {t["name"] for t in judge[0]["tools"]}
    assert "ALAN TAKE" in json.dumps(fred[1]["messages"][-1]) and "FRED TAKE" in json.dumps(alan[1]["messages"][-1])
    kept = [block["type"] for block in alan[1]["messages"][1]["content"]]
    assert "server_tool_use" in kept and "web_search_tool_result" in kept

    ruling = judge[0]["messages"][0]["content"]
    assert "GTO Wizards" in ruling and "Start Bijan?" in ruling and "cut off" not in ruling
    assert all(text in ruling for text in ["FRED TAKE", "ALAN TAKE", "FRED REBUTTAL", "ALAN REBUTTAL"])


def test_a_refused_expert_is_not_rebutted_and_the_judge_is_told():
    verdict, log, fred, alan, judge = run_panel(alan_stop="refusal")
    assert verdict == "VERDICT: start Bijan." and len(fred) == len(alan) == 1
    ruling = judge[0]["messages"][0]["content"]
    assert "Analytic Alan's answer was cut off or declined" in ruling and "FRED TAKE" in ruling
    assert "ALAN TAKE" not in ruling and "_rebuttal>" not in ruling


def test_a_take_stopped_at_max_tokens_counts_as_cut_off():
    verdict, log, fred, alan, judge = run_panel(alan_stop="max_tokens")
    ruling = judge[0]["messages"][0]["content"]
    assert len(fred) == len(alan) == 1 and "Analytic Alan's answer was cut off" in ruling
    assert "ALAN TAKE" not in ruling and "_rebuttal>" not in ruling


def test_a_refused_rebuttal_is_left_out_and_the_judge_is_told():
    verdict, log, fred, alan, judge = run_panel(alan_rebuttal_stop="refusal")
    ruling = judge[0]["messages"][0]["content"]
    assert "Analytic Alan's rebuttal was cut off or declined" in ruling
    assert "ALAN TAKE" in ruling and "FRED REBUTTAL" in ruling and "ALAN REBUTTAL" not in ruling


def test_prompts_differ_by_mode():
    def system(quick):
        return agent.Panel(None, [], "", quick=quick).fred.system

    assert "answering the manager directly" in system(True) and "For the panel:" not in system(True)
    assert "answering the manager directly" not in system(False) and "For the panel:" in system(False)


def sent_containers(expires_at):
    requests = []
    container = {"id": "container_1", "expires_at": expires_at}

    def claude(request):
        requests.append(json.loads(request.content))
        content = [{"type": "text", "text": "ok"}]
        return httpx2.Response(200, json={**reply(content, "end_turn"), "container": container})

    async def run():
        expert = agent.Expert("alan", "Be Alan.", [], fake_claude(claude), "", log=io.StringIO())
        await expert.ask("One?")
        await expert.ask("Two?")

    anyio.run(run)
    return requests


def test_the_code_execution_container_carries_over_between_asks():
    first, second = sent_containers("2999-01-01T00:00:00Z")
    assert "container" not in first and second["container"] == "container_1"


def test_an_expired_container_is_not_sent():
    assert all("container" not in request for request in sent_containers("2000-01-01T00:00:00Z"))
