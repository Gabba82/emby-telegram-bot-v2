#!/usr/bin/env bash
# Consistent online backup. Host requires Docker Compose and Python 3.
set -euo pipefail
umask 077
[[ $# == 1 && -d "$1" ]] || { echo "Uso: $0 <directorio_destino>" >&2; exit 2; }
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/../docker-compose.yml}"
SERVICE="${BACKUP_SERVICE:-app}"
CONTAINER="${BACKUP_CONTAINER:-}"
if [[ -z "$CONTAINER" ]]; then
  CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps --quiet "$SERVICE")"
fi
[[ -n "$CONTAINER" && "$CONTAINER" != *$'\n'* ]] || { echo 'Selecciona exactamente un contenedor en marcha.' >&2; exit 3; }
[[ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER")" == true ]] || { echo 'El contenedor no está en marcha.' >&2; exit 3; }
DB_IN_CONTAINER="${HISTORY_DB_PATH:-/data/history.sqlite3}"
HELPER="$(cat "$SCRIPT_DIR/sqlite_volume.py")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp "$1/history-${STAMP}-XXXXXX.sqlite3.partial")"
trap 'rm -f -- "$TMP"' EXIT
docker exec "$CONTAINER" python -c "$HELPER" dump "$DB_IN_CONTAINER" > "$TMP"
[[ -s "$TMP" ]] || { echo 'Backup vacío; abortando.' >&2; exit 4; }
python3 "$SCRIPT_DIR/sqlite_volume.py" check "$TMP"
OUT="${TMP%.partial}"
mv -- "$TMP" "$OUT"
trap - EXIT
echo "Backup correcto: $OUT"
