#!/usr/bin/env bash
# Why does the forwarded wallboard URL fail? Compares the server itself with GitHub's link to it.
#   bash .devcontainer/check-port.sh
PORT=${1:-8000}
URL="https://${CODESPACE_NAME}-${PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/"

echo "== Listening on port $PORT"
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep ":$PORT " || echo "   nothing is listening on $PORT"

echo "== 1. Inside the codespace"
curl -s -o /dev/null -m 10 -w "   http://127.0.0.1:$PORT/ -> %{http_code}\n" "http://127.0.0.1:$PORT/"
curl -s -o /dev/null -m 10 -w "   http://[::1]:$PORT/ -> %{http_code}\n" "http://[::1]:$PORT/"

echo "== 2. Through GitHub's link ($URL)"
curl -s -m 20 -D - -o /tmp/forwarded-body.txt -H "X-Github-Token: $GITHUB_TOKEN" "$URL" | head -12 | sed 's/^/   /'
echo "   body: $(head -c 200 /tmp/forwarded-body.txt | tr '\n' ' ')"

echo "== Last wallboard log lines"
tail -n 8 /tmp/wallboard.log 2>/dev/null | sed 's/^/   /' || echo "   (no /tmp/wallboard.log: started from a terminal?)"
