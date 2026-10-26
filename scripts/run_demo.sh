#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then
  demo_python=.venv/bin/python
elif [ -x ../.emby-dev-tools/venv/bin/python ]; then
  demo_python=../.emby-dev-tools/venv/bin/python
else
  echo 'Crea .venv e instala requirements.txt según docs/INSTALLATION.md' >&2
  exit 1
fi
exec "$demo_python" scripts/run_manager.py --host "${HOST:-127.0.0.1}" --port "${PASEO_PORT:-8093}"
