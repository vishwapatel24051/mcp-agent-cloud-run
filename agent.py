"""The LangGraph agent: an LLM node and a tool node joined in a reason -> act loop."""

import os
from datetime import UTC, datetime
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from mcp_client import tool_error_message

SYSTEM_PROMPT = """You are a helpful research assistant with access to tools.

Decide for yourself whether a tool is needed:
- Answer general-knowledge, math, coding and conversational questions directly, without tools.
- Use the web search tools for current events, recent facts, or anything you are unsure about.
  The current UTC date and time are given at the end of this prompt; never search for them.
- Use the calculate tool for arithmetic instead of computing in your head, and the current_time tool
  for the time in a specific time zone.
- Use the fetch tool to read the full content of a specific URL.
- Use the filesystem tools to list, read, write or edit files. They only work inside the
  allowed workspace directory; call list_allowed_directories if you need its path.
- Never delete, empty, move away or overwrite files the user did not ask you to change. If asked to
  delete or wipe files, say which files would be affected and ask for confirmation first; the tools
  have no delete operation, so do not simulate deletion by emptying or moving files.
- Chain several tool calls when a task needs it (for example: search, then save a summary to a file).
- If a tool returns an error, explain the problem to the user or try a different approach.
- Use the conversation history to answer questions about earlier turns.

Keep final answers clear and concise, and mention which sources or files you used."""


class AgentState(TypedDict):
    # add_messages appends new messages instead of overwriting, which is what lets the
    # checkpointer replay the whole conversation on the next turn.
    messages: Annotated[list[AnyMessage], add_messages]


def create_llm() -> ChatOpenAI:
    """NVIDIA NIM (or OpenAI) through the OpenAI-compatible API; settings come from the environment."""
    return ChatOpenAI(
        model=os.environ["MODEL_NAME"],
        base_url=os.getenv("OPENAI_BASE_URL"),
        api_key=os.environ["OPENAI_API_KEY"],
        temperature=0,
        timeout=60,
        max_retries=6,  # the free NIM tier rate-limits at ~40 req/min; the SDK backs off between retries
    )


def build_agent(llm: BaseChatModel, tools: list[BaseTool]) -> CompiledStateGraph:
    """Build the graph: START -> agent -> (tools -> agent)* -> END, with per-session memory."""
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    async def call_model(state: AgentState) -> dict:
        # The model has no clock, and web search returns stale "current time" pages, so supply it.
        now = datetime.now(UTC).strftime("%A, %B %d, %Y %H:%M:%S UTC")
        system = SystemMessage(f"{SYSTEM_PROMPT}\n\nCurrent date and time: {now}.")
        response = await llm_with_tools.ainvoke([system, *state["messages"]])
        return {"messages": [response]}

    def route_after_model(state: AgentState) -> str:
        # The LLM asked for tools -> run them and loop back; otherwise it gave its final answer.
        return "tools" if state["messages"][-1].tool_calls else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=tool_error_message))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_model, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=InMemorySaver())
