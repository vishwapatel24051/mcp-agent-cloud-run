"""Connects to the MCP servers listed in mcp_config.json and exposes their tools.

Each server is loaded on its own, so one broken server (missing binary, bad key,
crashed process) is logged and skipped instead of taking the whole agent down.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt.tool_node import ToolInvocationError
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent

_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
# stdio servers only see the env we pass them; forward what they need to find binaries
# and reach the network, but not our API keys.
_PASSTHROUGH_ENV = ("PATH", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS")


def _substitute(value, variables: dict[str, str]):
    """Replace ${NAME} placeholders in strings, lists and dicts (keeps secrets out of the JSON file)."""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: variables.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    return value


def load_server_config(path: str) -> dict:
    """Read the server manifest and fill in environment-specific values."""
    workspace = Path(os.getenv("WORKSPACE_DIR", APP_DIR / "workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    variables = {
        **os.environ,
        "APP_DIR": str(APP_DIR),
        "PYTHON": sys.executable,
        "WORKSPACE_DIR": str(workspace),
    }
    with open(path, encoding="utf-8") as config_file:
        raw = json.load(config_file)
    connections = _substitute(raw, variables)
    for connection in connections.values():
        if connection.get("transport") == "stdio":
            inherited = {key: os.environ[key] for key in _PASSTHROUGH_ENV if key in os.environ}
            connection["env"] = {**inherited, **connection.get("env", {})}
    return connections


async def load_mcp_tools(config_path: str) -> tuple[list[BaseTool], dict[str, str]]:
    """Discover tools (MCP tools/list) from every configured server.

    Returns the tools that loaded plus a status message per server.
    """
    connections = load_server_config(config_path)
    client = MultiServerMCPClient(connections)
    tools: list[BaseTool] = []
    status: dict[str, str] = {}
    for name in connections:
        try:
            server_tools = await client.get_tools(server_name=name)
        except Exception as error:  # noqa: BLE001  any failure of one server must not stop the others
            logger.error("MCP server '%s' unavailable: %s", name, describe_error(error))
            status[name] = f"unavailable: {describe_error(error)}"
            continue
        tools.extend(server_tools)
        status[name] = f"ok ({len(server_tools)} tools)"
        logger.info("MCP server '%s' loaded tools: %s", name, [t.name for t in server_tools])
    return tools, status


def describe_error(error: BaseException) -> str:
    """Flatten nested errors (ExceptionGroups from the MCP transport) into one readable line."""
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(describe_error(inner) for inner in error.exceptions)
    return f"{type(error).__name__}: {error}"


def tool_error_message(error: Exception) -> str:
    """Turn a failed tool call into a message the LLM can read and react to.

    Tool *execution* errors (isError=True) never reach here: the adapter already
    returns them to the model. This handles the other two failure modes.
    """
    if isinstance(error, (ToolInvocationError, ValidationError, json.JSONDecodeError, ValueError)):
        # ToolInvocationError wraps schema validation failures, in either direction.
        kind = "returned a malformed or invalid response"
    elif isinstance(error, McpError) and "closed" not in str(error).lower():
        kind = "returned a protocol error"
    else:
        # Includes McpError("Connection closed"): the server process died or its stream broke.
        kind = "could not be reached (connection or transport failure)"
    logger.warning("Tool call failed: %s", describe_error(error))
    return (
        f"Error: the tool {kind}: {describe_error(error)}. "
        "Tell the user this tool is currently unavailable, or try another approach."
    )
