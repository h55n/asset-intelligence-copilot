#!/usr/bin/env bash
# One-command QA: deterministic core checks, the full 18-scenario suite
# against a clean database with expected-answer checks, and the ID-shifted
# generalization probe. Needs LLM_BASE_URL / LLM_MODEL / LLM_API_KEY set for
# the suite; the core checks and generalization probe are model-free.
set -e
cd "$(dirname "$0")/.."
DATA="${DATA_DIR:-sample-data}"
DB="${DB_PATH:-/tmp/copilot.db}"
PORT="${PORT:-8000}"

echo '== 1/4 deterministic core checks =='
rm -f "$DB"
python3 app/ingest.py "$DATA" "$DB"
python3 verify.py

echo '== 2/4 start server =='
DB_PATH="$DB" PORT="$PORT" python3 app/server.py &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for i in $(seq 1 30); do curl -sf "http://localhost:$PORT/api/users" >/dev/null && break; sleep 1; done

echo '== 3/4 18-scenario suite + expected-answer checks =='
rm -f "$DB"
python3 app/ingest.py "$DATA" "$DB" >/dev/null
python3 scenario_suite.py
python3 qa/check_answers.py /tmp/suite_results.json

echo '== 4/4 unseen-data generalization =='
python3 qa/generalization.py "$DATA"

echo 'QA COMPLETE'
