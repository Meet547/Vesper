#!/usr/bin/env bash
set -euo pipefail

# This process is pinned to the named local test graph. Never source Cloud
# endpoint overrides or bind the demonstration outside loopback.
export APP_MODE=cloud
export APP_HOST=127.0.0.1
export APP_PORT=8012
export AUTH_MODE=none
export TRACK2_ISOLATED_DEMO=true
export ISOLATED_DEMO_IDENTITY=track2-isolated-demo
export ISOLATED_DEMO_GRAPH_NAME=vesper_track2_synthetic_test
export FALKORDB_URL=redis://127.0.0.1:6389
export FALKORDB_HOST=
export FALKORDB_PORT=6389
export FALKORDB_USERNAME=
export FALKORDB_PASSWORD=
export FALKORDB_GRAPH_NAME=vesper_track2_synthetic_test
export FALKORDB_SSL=false
export PYTHONPATH=.

exec ./.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8012 --no-access-log
