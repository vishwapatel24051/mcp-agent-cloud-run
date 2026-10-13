"""Minimal raw MCP stdio server that fails on purpose."""
import json
import os
import sys

TOOLS = [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": {}}}
         for n, d in [("crash_mid_call", "kills the server process during the call"),
                      ("garbage_output", "writes non-JSON to the protocol stream"),
                      ("bad_schema", "returns a result that violates the MCP schema"),
                      ("exec_error", "returns isError=true"),
                      ("works", "returns ok")]]
def send(o): sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line); i = m.get("id"); method = m.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": m["params"]["protocolVersion"],
              "capabilities": {"tools": {}}, "serverInfo": {"name": "bad", "version": "0"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": i, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = m["params"]["name"]
        if name == "crash_mid_call": os._exit(1)
        if name == "garbage_output": sys.stdout.write("<<< not json at all >>>\n"); sys.stdout.flush(); os._exit(0)
        if name == "bad_schema": send({"jsonrpc": "2.0", "id": i, "result": {"content": "should be a list"}})
        if name == "exec_error": send({"jsonrpc": "2.0", "id": i, "result": {"isError": True, "content": [{"type": "text", "text": "ENOENT: simulated tool failure"}]}})
        if name == "works": send({"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": "ok"}]}})
