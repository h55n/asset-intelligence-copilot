#!/bin/sh
# Render (or any host) start: fetch the dataset if absent, then serve.
set -e
if [ ! -d /tmp/ds/sample-data ]; then
  git clone --depth 1 https://github.com/FlytBaseAILabs/flytbase-ahc-swe-asset-intelligence-dataset /tmp/ds
fi
export DATA_DIR=${DATA_DIR:-/tmp/ds/sample-data}
export DB_PATH=${DB_PATH:-/tmp/copilot.db}
exec python app/server.py
