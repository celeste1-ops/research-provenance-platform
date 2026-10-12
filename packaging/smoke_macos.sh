#!/usr/bin/env bash
# Start the built app without browser or menu bar icon on a throw-away data folder and check
# it end to end over HTTP: set-up, a step, an evidence bundle that the bundled verify.py
# accepts. Uses an in-memory key store so it never touches your Keychain or ~/.rprov.
#   bash packaging/smoke_macos.sh "dist/Research History.app"
set -euo pipefail
APP="${1:-dist/Research History.app}"
BIN="$APP/Contents/MacOS/Research History"
DATA="$(mktemp -d)/rprov-smoke"
PORT=8799
BASE="http://127.0.0.1:${PORT}"

RPROV_HOME="$DATA" RPROV_KEYSTORE=memory RPROV_TSA=off RPROV_BTC=off \
  "$BIN" --no-browser --no-tray --port "$PORT" &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT

for _ in $(seq 1 90); do
  curl -fsS "$BASE/api/status" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "$BASE/api/status" | grep -q '"device":"Mac"' || { cat "$DATA/logs/app.log" || true; echo "app did not start"; exit 1; }

TOKEN="$(curl -fsS "$BASE/" | sed -n 's/.*name="rprov-session-token" content="\([^"]*\)".*/\1/p')"
[ -n "$TOKEN" ] || { echo "no session token in page"; exit 1; }
H=(-H "X-RPROV-Token: $TOKEN")
curl -fsS "${H[@]}" -H 'Content-Type: application/json' -d '{"author_label":"Smoke test"}' "$BASE/api/identity" >/dev/null
PROJECT="$(curl -fsS "${H[@]}" -H 'Content-Type: application/json' -d '{"title":"Smoke"}' "$BASE/api/projects" \
  | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
curl -fsS "${H[@]}" -F "project_id=$PROJECT" -F node_type=idea -F "title=Smoke step — ünïcode" -F body=hello \
  "$BASE/api/entries" >/dev/null
curl -fsS "$BASE/api/status" | grep -q '"entry_count":1' || { echo "step not saved"; exit 1; }

curl -fsS "${H[@]}" -H 'Content-Type: application/json' -d '{"title":"Smoke","default":"full"}' \
  -o "$DATA/bundle.zip" "$BASE/api/export"
mkdir -p "$DATA/bundle" && (cd "$DATA/bundle" && unzip -q ../bundle.zip)
uv run python "$DATA/bundle/verify.py" "$DATA/bundle" --offline   # needs cryptography + rfc3161-client
kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# The app's own window (D-058), as you would use it: the page is drawn in the window, closing the
# window hides it while the app keeps running, a second start shows it again, Quit ends the app.
WDATA="$(mktemp -d)/rprov-window"
RPROV_HOME="$WDATA" RPROV_KEYSTORE=memory RPROV_TSA=off RPROV_BTC=off \
  "$BIN" --check-window --port 8798 &
WPID=$!
trap 'kill $PID $WPID 2>/dev/null || true' EXIT
for _ in $(seq 1 180); do
  kill -0 "$WPID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$WPID" 2>/dev/null; then
  cat "$WDATA/logs/app.log" || true; echo "window check did not finish"; exit 1
fi
wait "$WPID" || { cat "$WDATA/logs/app.log" || true; echo "window check failed"; exit 1; }
grep -q "window check passed" "$WDATA/logs/app.log" || { cat "$WDATA/logs/app.log"; echo "window check incomplete"; exit 1; }
grep "window check" "$WDATA/logs/app.log"
echo "Smoke test passed: started, saved a step, exported, verified; the window works."
