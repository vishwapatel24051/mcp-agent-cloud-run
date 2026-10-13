#!/usr/bin/env bash
# Interactive chat with a running agent. Usage: scripts/chat.sh [base_url]
URL="${1:-http://localhost:8080}"
SESSION="chat-$(date +%s)"
echo "Chatting with ${URL} (session ${SESSION}). Type a message, or 'exit' to quit."
while true; do
  read -r -p "you> " QUERY || break
  [ "$QUERY" = "exit" ] && break
  [ -z "$QUERY" ] && continue
  curl -s -X POST "${URL}/chat" -H "Content-Type: application/json" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1], "session_id": sys.argv[2]}))' "$QUERY" "$SESSION")" \
    | python3 -c 'import json,sys; print("agent>", json.load(sys.stdin)["response"]); print()'
done
