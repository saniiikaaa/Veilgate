#!/usr/bin/env bash
# Fill the dashboard with demo sessions (scripted stand-in model, no network). The API must be running on :8080.
set -e
cd "$(dirname "$0")/../.."
source .venv/bin/activate
for i in 1 2; do python -m demo.clinic_demo --offline --story attack --user dr.iyer >/dev/null; done
python -m demo.clinic_demo --offline --story clean --user dr.iyer >/dev/null
python -m demo.clinic_demo --offline --story clean --user nurse.rao >/dev/null
python -m demo.clinic_demo --offline --story attack --user nurse.rao >/dev/null
echo "demo data loaded: open http://localhost:8080/"
