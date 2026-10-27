#!/usr/bin/env bash
# Restore only with the service stopped; preserve the current ledger first.
set -euo pipefail
umask 077
[[ $# -ge 1 && $# -le 2 && -f "$1" ]] || { echo "Uso: $0 <backup.sqlite3> [--check]" >&2; exit 2; }
[[ $# == 1 || "$2" == --check ]] || { echo 'Opción no válida.' >&2; exit 2; }
BACKUP="$1"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
python3 "$SCRIPT_DIR/sqlite_volume.py" check "$BACKUP"
if [[ "${2:-}" == --check ]]; then exit 0; fi
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/../docker-compose.yml}"
SERVICE="${RESTORE_SERVICE:-app}"
# Any Docker/Compose error aborts; an error never means "stopped".
CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps --all --quiet "$SERVICE")"
[[ -n "$CONTAINER" && "$CONTAINER" != *$'\n'* ]] || { echo 'Se necesita un contenedor existente y parado (usa compose stop, no down).' >&2; exit 3; }
[[ "$(docker inspect --format '{{.State.Status}}' "$CONTAINER")" == exited ]] || { echo "Detén primero el servicio $SERVICE con docker compose stop." >&2; exit 3; }
VOLUME="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{if eq .Type "volume"}}{{.Name}}{{end}}{{end}}{{end}}' "$CONTAINER")"
[[ -n "$VOLUME" ]] || { echo 'No se encontró un volumen nombrado en /data.' >&2; exit 4; }
docker volume inspect "$VOLUME" > /dev/null
IMAGE="$(docker inspect --format '{{.Image}}' "$CONTAINER")"
DB_IN_CONTAINER="${HISTORY_DB_PATH:-/data/history.sqlite3}"
HELPER="$(cat "$SCRIPT_DIR/sqlite_volume.py")"
ledger() {
  docker run --rm -i --network none --mount "type=volume,src=$VOLUME,dst=/data" \
    --entrypoint python "$IMAGE" -c "$HELPER" "$1" "$DB_IN_CONTAINER"
}
SAFETY="$(mktemp "${BACKUP}.pre-restore-XXXXXX.sqlite3")"
if ! ledger dump > "$SAFETY"; then
  rm -f -- "$SAFETY"
  echo 'No se pudo conservar la base vigente. No se ha restaurado nada.' >&2
  exit 5
fi
python3 "$SCRIPT_DIR/sqlite_volume.py" check "$SAFETY"
ledger restore < "$BACKUP"
echo "Restauración correcta. Base anterior conservada en: $SAFETY"
echo "Arranca explícitamente el servicio $SERVICE cuando hayas revisado el resultado."
