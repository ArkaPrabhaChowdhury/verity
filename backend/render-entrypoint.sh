#!/bin/sh
set -eu

(
  cd /usr/local/searxng
  exec /usr/local/searxng/entrypoint.sh
) &
search_pid=$!
verity &
api_pid=$!

shutdown() {
  kill -TERM "$api_pid" "$search_pid" 2>/dev/null || true
}

trap shutdown INT TERM

set +e
wait -n "$api_pid" "$search_pid"
status=$?
set -e
shutdown
wait "$api_pid" 2>/dev/null || true
wait "$search_pid" 2>/dev/null || true
exit "$status"
