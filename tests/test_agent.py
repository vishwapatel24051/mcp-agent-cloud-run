"""Offline tests: a scripted fake LLM drives the real graph against the real MCP servers.

Run with: pytest -q   (needs `npm install` done; no API keys required)
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent import build_agent
from mcp_client import load_mcp_tools


class ScriptedLLM(GenericFakeChatModel):
    """Returns pre-written AI messages in order; bind_tools is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*messages: AIMessage) -> ScriptedLLM:
    return ScriptedLLM(messages=iter(messages))


def call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


def config(session: str) -> dict:
    return {"configurable": {"thread_id": session}}


@pytest.fixture(scope="module")
async def mcp_tools(tmp_path_factory):
    import os

    os.environ["WORKSPACE_DIR"] = str(tmp_path_factory.mktemp("workspace"))
    os.environ.setdefault("TAVILY_API_KEY", "test-key")
    tools, status = await load_mcp_tools("mcp_config.json")
    return tools, status


async def test_all_servers_discovered(mcp_tools):
    tools, status = mcp_tools
    names = {t.name for t in tools}
    assert all(s.startswith("ok") for s in status.values()), status
    assert {"write_file", "read_text_file", "tavily_search", "fetch", "calculate", "current_time"} <= names


async def test_chains_two_tool_calls_then_answers(mcp_tools):
    tools, _ = mcp_tools
    llm = scripted(
        call("write_file", {"path": "notes.txt", "content": "MCP rocks"}, "1"),
        call("read_text_file", {"path": "notes.txt"}, "2"),
        AIMessage("The file says: MCP rocks"),
    )
    agent = build_agent(llm, tools)
    result = await agent.ainvoke({"messages": [HumanMessage("save and read back")]}, config("chain"))
    tool_results = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_results) == 2
    assert "MCP rocks" in str(tool_results[1].content)
    assert result["messages"][-1].content == "The file says: MCP rocks"


async def test_utilities_server_calculates_and_rejects_unsafe_input(mcp_tools):
    tools, _ = mcp_tools
    llm = scripted(
        call("calculate", {"expression": "(17 * 23) / 4 + 2 ** 10"}, "1"),
        call("calculate", {"expression": "__import__('os').system('ls')"}, "2"),
        call("current_time", {"timezone": "Asia/Kolkata"}, "3"),
        AIMessage("done"),
    )
    result = await build_agent(llm, tools).ainvoke({"messages": [HumanMessage("math")]}, config("utils"))
    replies = [str(m.content) for m in result["messages"] if isinstance(m, ToolMessage)]
    assert "1121.75" in replies[0]
    assert "only numbers" in replies[1]  # rejected, and the error reached the model
    assert "Asia/Kolkata" in replies[2]


async def test_answers_without_tools(mcp_tools):
    tools, _ = mcp_tools
    agent = build_agent(scripted(AIMessage("4")), tools)
    result = await agent.ainvoke({"messages": [HumanMessage("2+2?")]}, config("no-tools"))
    assert not any(isinstance(m, ToolMessage) for m in result["messages"])


async def test_memory_is_per_session(mcp_tools):
    tools, _ = mcp_tools
    agent = build_agent(scripted(AIMessage("hi"), AIMessage("again"), AIMessage("new")), tools)
    await agent.ainvoke({"messages": [HumanMessage("my name is V")]}, config("a"))
    second = await agent.ainvoke({"messages": [HumanMessage("what is my name?")]}, config("a"))
    other = await agent.ainvoke({"messages": [HumanMessage("what is my name?")]}, config("b"))
    assert "my name is V" in [m.content for m in second["messages"]]
    assert "my name is V" not in [m.content for m in other["messages"]]


async def test_tool_execution_error_returned_to_llm(mcp_tools):
    tools, _ = mcp_tools
    llm = scripted(call("read_text_file", {"path": "missing.txt"}, "1"), AIMessage("That file does not exist."))
    result = await build_agent(llm, tools).ainvoke({"messages": [HumanMessage("read it")]}, config("err"))
    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "ENOENT" in str(tool_message.content)


async def test_transport_and_malformed_errors_do_not_crash():
    @tool
    def flaky(kind: str) -> str:
        """Simulates a broken MCP transport or an unparsable server reply."""
        if kind == "transport":
            raise ConnectionError("server process exited")
        return json.loads("{not json")

    llm = scripted(
        call("flaky", {"kind": "transport"}, "1"),
        call("flaky", {"kind": "malformed"}, "2"),
        AIMessage("Both tools failed, sorry."),
    )
    result = await build_agent(llm, [flaky]).ainvoke({"messages": [HumanMessage("go")]}, config("x"))
    errors = [m.content for m in result["messages"] if isinstance(m, ToolMessage)]
    assert "could not be reached" in errors[0]
    assert "malformed" in errors[1]


async def test_unavailable_server_is_skipped(tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text(json.dumps({
        "broken": {"transport": "stdio", "command": "does-not-exist", "args": []},
        "fetch": {"transport": "stdio", "command": "${PYTHON}", "args": ["-m", "mcp_server_fetch"]},
    }))
    tools, status = await load_mcp_tools(str(bad))
    assert status["broken"].startswith("unavailable")
    assert [t.name for t in tools] == ["fetch"]


async def test_misbehaving_mcp_server_over_real_stdio(tmp_path):
    """A real stdio MCP server that crashes, emits garbage, breaks the schema and reports isError."""
    server = Path(__file__).parent / "bad_mcp_server.py"
    manifest = tmp_path / "config.json"
    manifest.write_text(json.dumps({"bad": {"transport": "stdio", "command": "${PYTHON}", "args": [str(server)]}}))
    tools, status = await load_mcp_tools(str(manifest))
    assert status["bad"].startswith("ok")

    names = ["crash_mid_call", "garbage_output", "bad_schema", "exec_error", "works"]
    llm = scripted(*[call(name, {}, str(i)) for i, name in enumerate(names)], AIMessage("still alive"))
    result = await build_agent(llm, tools).ainvoke({"messages": [HumanMessage("go")]}, config("bad"))
    replies = [str(m.content) for m in result["messages"] if isinstance(m, ToolMessage)]

    assert "could not be reached" in replies[0]  # transport closed mid-call
    assert "could not be reached" in replies[1]  # garbage on the stream, then the connection drops
    assert "malformed or invalid response" in replies[2]  # result violates the MCP schema
    assert "simulated tool failure" in replies[3]  # isError=true reaches the model unchanged
    assert "ok" in replies[4]  # the server keeps working after earlier failures
    assert result["messages"][-1].content == "still alive"


def test_chat_rejects_invalid_request(monkeypatch):
    import main

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("MODEL_NAME", "test")
    with TestClient(main.app) as client:
        response = client.post("/chat", json={"query": ""})
    assert response.status_code == 422
    assert "Invalid request" in response.json()["response"]


def test_root_describes_the_service(monkeypatch):
    import main

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("MODEL_NAME", "test")
    with TestClient(main.app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "POST /chat" in response.json()["endpoints"]
