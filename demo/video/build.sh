#!/usr/bin/env bash
# Rebuilds the demo video from scratch: a clean database, three real model runs, then the recording.
#
#   NODE_PATH=/path/to/node_modules ./demo/video/build.sh      (needs puppeteer-core, ffmpeg, Google Chrome, a running warden-db)
#
# It uses its own database (guardrail_v2_video) and port 8091, so your development data is untouched.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
set -a; . ./.env; set +a
export LLM_PROVIDER=nebius LLM_JUDGE=auto
PORT_DB="${WARDEN_DB_PORT:-5440}"
export MIGRATION_DATABASE_URL="postgresql://guardrail_owner:ownerpass@localhost:${PORT_DB}/guardrail_v2_video"
export DATABASE_URL="postgresql://guardrail_app:apppass@localhost:${PORT_DB}/guardrail_v2_video"

docker exec warden-db psql -U guardrail_owner -d postgres -q -c "DROP DATABASE IF EXISTS guardrail_v2_video WITH (FORCE)" -c "CREATE DATABASE guardrail_v2_video"
python scripts/db/migrate.py && python scripts/db/seed.py

uvicorn src.main:app --port 8091 > /tmp/veilgate-video-server.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf localhost:8091/healthz >/dev/null && break; sleep 1; done

rm -rf demo/video/out && mkdir -p demo/video/out
URL=http://localhost:8091
python -m demo.clinic_demo --url $URL --story clean  --user nurse.rao > demo/video/out/run_clean.txt
python -m demo.clinic_demo --url $URL --story attack --user nurse.rao > demo/video/out/run_attack2.txt
python -m demo.clinic_demo --url $URL --story attack --user dr.iyer   > demo/video/out/real_run.txt
grep -h "FINAL ANSWER" demo/video/out/run_*.txt demo/video/out/real_run.txt | cut -c1-100

export BASE=$URL RUN_LOG="$PWD/demo/video/out/real_run.txt"
node demo/video/record.js
CAPTIONS=0 node demo/video/record.js
echo "done: demo/video/out/veilgate-demo.mp4 (+ -clean.mp4, .srt, voiceover-script.txt)"
