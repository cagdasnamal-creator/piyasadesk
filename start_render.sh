#!/usr/bin/env bash
set -euo pipefail

# Render Free tek bir Web Service calistiriyor. Test ortami icin collector'i
# ayni container icinde AYRI process olarak baslatip API'yi foreground'da tutuyoruz.
python -m haber.collector --loop 300 &
COLLECTOR_PID=$!

cleanup() {
  kill "$COLLECTOR_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec uvicorn haber.api:app --host 0.0.0.0 --port "${PORT:-10000}"
