#!/usr/bin/env bash
set -euo pipefail

# Render Free: collector + API ayni container'da. Ikisinden biri
# beklenmedik sekilde durursa servisi de sonlandir; Render temiz bir
# yeniden baslatma yapsin. SIGTERM'de iki child process de kapatilir.
python -m haber.collector --loop 300 &
COLLECTOR_PID=$!
uvicorn haber.api:app --host 0.0.0.0 --port "${PORT:-10000}" &
API_PID=$!

cleanup() {
  kill "$COLLECTOR_PID" "$API_PID" 2>/dev/null || true
  wait "$COLLECTOR_PID" "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait -n "$COLLECTOR_PID" "$API_PID"
STATUS=$?
cleanup
exit "$STATUS"
