#!/bin/zsh

set -u

PROJECT_DIR="${0:A:h}"
PYTHON="$PROJECT_DIR/.venv/bin/python"
URL="http://127.0.0.1:8000"

cd "$PROJECT_DIR" || exit 1

pause_before_exit() {
  printf "\nPress Enter to close this window..."
  read -r
}

if [[ ! -x "$PYTHON" ]]; then
  echo "The virtual environment was not found."
  echo
  echo "Run these commands once:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  pause_before_exit
  exit 1
fi

if curl --silent --fail --max-time 1 "$URL/health" >/dev/null 2>&1; then
  echo "Telegram Channel Parser is already running."
  open "$URL"
  exit 0
fi

echo "Starting Telegram Channel Parser..."
"$PYTHON" -m app.web &
SERVER_PID=$!

stop_server() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1
  fi
}

trap stop_server EXIT INT TERM

for _ in {1..60}; do
  if curl --silent --fail --max-time 1 "$URL/health" >/dev/null 2>&1; then
    echo "Ready: $URL"
    open "$URL"
    wait "$SERVER_PID"
    exit $?
  fi

  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    wait "$SERVER_PID"
    STATUS=$?
    echo
    echo "The app could not start. Exit code: $STATUS"
    pause_before_exit
    exit "$STATUS"
  fi

  sleep 0.25
done

echo
echo "The app did not become ready in time."
pause_before_exit
exit 1
