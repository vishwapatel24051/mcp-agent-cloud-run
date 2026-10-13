#!/usr/bin/env bash
# Sends the rubric scenarios to a running agent. Usage: scripts/smoke_test.sh [base_url]
set -euo pipefail
URL="${1:-http://localhost:8080}"
SESSION="smoke-$(date +%s)"

ask() {
  echo; echo ">>> [$2] $1"
  curl -s -X POST "${URL}/chat" -H "Content-Type: application/json" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1], "session_id": sys.argv[2]}))' "$1" "$2")"
  echo
}

curl -s "${URL}/health"; echo
ask "What is the capital of France? Answer from your own knowledge." "$SESSION"
ask "Search the web for the latest stable Python release and give me the version number." "$SESSION"
ask "Fetch https://modelcontextprotocol.io and summarize it in two sentences." "$SESSION"
ask "Search the web for what LangGraph is, then save a 3-sentence summary to langgraph.txt." "$SESSION"
ask "Read langgraph.txt and tell me what it says." "$SESSION"
ask "Read the file does_not_exist.txt." "$SESSION"
ask "What did I ask you two questions ago?" "$SESSION"
ask "What did I ask you last?" "other-${SESSION}"
