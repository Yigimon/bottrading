#!/usr/bin/env bash
# Kompletter Test: Unit-Tests, Integrationstests (Daten, Live = Backtest, Neustarts, Master), API und Sicherheit.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== Unit-Tests"
docker run --rm -v "$PWD":/app -w /app python:3.12-slim sh -c 'pip install -q pytest >/dev/null 2>&1; PYTHONPATH=libs/core pytest -q'
echo "== Integrationstests"
docker compose run --rm --no-deps -v ./tests/integration:/itest:ro bots python /itest/check_system.py
echo "== API"
fail=0
for p in health prices wallets equity benchmark meta master system strategies analytics/backtests; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "localhost:8080/api/$p"); [ "$code" = 200 ] && echo "[OK ] /api/$p" || { echo "[FEHLER] /api/$p -> $code"; fail=1; }
done
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8080/api/control/kill); [ "$code" = 403 ] && echo "[OK ] Steuerung ohne Header abgelehnt" || { echo "[FEHLER] Steuerung ungeschützt ($code)"; fail=1; }
exit $fail
