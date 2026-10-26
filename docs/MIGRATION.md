# Migración a EMBY-005

EMBY-005 empaqueta el bot con Docker Compose y añade el panel como módulo **opcional**. El esquema SQLite del historial es compatible con EMBY-002/003/004. Instalación completa: [`INSTALLATION.md`](INSTALLATION.md).

## Qué cambia

| Aspecto | Antes | Ahora |
|---|---|---|
| Servicio de Compose | un solo servicio | `app` (perfil `production`) y `demo` (perfil `demo`) |
| Arranque | `docker compose up` | `docker compose --profile production up --build -d` (sin perfil, **no arranca `app`**) |
| Contenedor y volumen | nombre fijo | sin nombre fijo: Compose los deriva del proyecto (`<proyecto>_history-data`) |
| Usuario | `root` | `10001:10001` |
| Historial | `data/` o ruta propia | `/data/history.sqlite3` en el volumen (`HISTORY_DB_PATH`) |
| Panel | solo en la demo | opcional, `PANEL_ENABLED=false` por defecto |

El nombre del proyecto es el del directorio o el de `COMPOSE_PROJECT_NAME`. Si lo cambias, expórtalo siempre antes de usar Compose y los scripts.

## 1. Copia tus valores

Del `.env` actual: `TELEGRAM_TOKEN`, `EMBY_API_KEY`, `CHAT_IDS` (y `LIBRARY_CHAT_IDS`, `PLAYBACK_CHAT_IDS`, `ADMIN_CHAT_IDS`, `CHAT_LABELS`), `EMBY_API_URL` y el resto. No hace falta regenerar credenciales.

```bash
cp .env.example .env     # pega tus valores
```

## 2. Elige tu caso

**A. Vienes de la versión original (sin historial SQLite).** No existe historial que migrar y **no se reconstruye**: todo contenido anterior figura como «historial desconocido». Salta al paso 3. Al usar la Conciliación, fija el inicio del historial en la fecha real de tu primer arranque con EMBY-005, nunca en una estimación.

**B. Vienes de EMBY-002/003/004 con historial real.** Conserva tu base, pero haz una **copia consistente**: con el servicio antiguo parado, o con la API de copia de SQLite (no copies solo el fichero con el servicio en marcha, porque puede haber datos en el WAL):

```bash
python3 -c "import sqlite3,sys;s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);s.backup(sqlite3.connect(sys.argv[2]))" \
  RUTA/history.sqlite3 /ruta/segura/history-previo.sqlite3
scripts/restore.sh /ruta/segura/history-previo.sqlite3 --check   # valida sin tocar nada
```

`RUTA/history.sqlite3` es el valor de `HISTORY_DB_PATH` de tu instalación anterior (por defecto `data/history.sqlite3`). Guarda esa copia hasta que EMBY-005 funcione.

## 3. Despliegue

En el caso B, mantén bloqueados los webhooks entrantes y no uses comandos de publicación durante el primer arranque y la restauración. Retira ese bloqueo únicamente después de comprobar el historial restaurado. Conserva también el Compose anterior y el identificador de su imagen para el rollback.

```bash
docker compose --profile production up --build -d
docker compose ps
curl -fsS http://127.0.0.1:8081/health      # {"status":"ok"}
```

## 4. Restaura tu historial (solo caso B)

`restore.sh` exige un servicio **existente y parado** (`stop`, no `down`) y que el volumen ya tenga una base: la primera puesta en marcha la crea.

```bash
docker compose stop app
scripts/restore.sh /ruta/segura/history-previo.sqlite3
docker compose start app
```

Hace antes una copia de seguridad de la base vigente (`<copia>.pre-restore-*.sqlite3`) y no toca el `.env`. Por defecto actúa sobre el servicio `app` (`RESTORE_SERVICE`, `HISTORY_DB_PATH=/data/history.sqlite3`).

## 5. Panel (opcional)

```env
PANEL_ENABLED=true
PANEL_ADMIN_PASSWORD=<mínimo 16 caracteres, no de demostración>
PANEL_SECRET_KEY=<mínimo 32 caracteres, distinta de la contraseña>
PANEL_ALLOW_SENDS=false
```

Exige HTTPS (cookie `Secure`) y, si los requisitos no se cumplen, el contenedor no arranca. `PANEL_ALLOW_SENDS=false` solo bloquea los envíos manuales del panel; los webhooks y comandos del bot siguen activos.

## 6. Verificación

| Prueba | Resultado esperado |
|---|---|
| `curl -fsS http://127.0.0.1:8081/health` | `{"status":"ok"}` |
| `docker compose exec app id` | `uid=10001` |
| `/historial` en Telegram (caso B) | entregas previas |
| `/manager/` con el panel desactivado | HTTP `404` |
| `docker volume ls` | volumen `<proyecto>_history-data` |

## 7. Rollback

No hay conversión de datos que deshacer: el esquema es compatible.

1. **Base de datos:** con `docker compose stop app`, `scripts/restore.sh <copia>` y `docker compose start app`. Para pruebas, `BACKUP_SERVICE` y `RESTORE_SERVICE` valen `demo`.
2. **Aplicación:** conserva el identificador de imagen y el Compose anterior antes de actualizar. Si ambos usan el servicio `app`, puedes fijar una imagen **ya construida**, manteniendo el Compose actual:
   ```bash
   APP_IMAGE=<imagen-anterior-conservada> docker compose --profile production up -d --no-build app
   ```
   Si vuelves a la versión original, usa su propio Compose y sus instrucciones: sus nombres de servicio y perfiles son diferentes. No apliques comandos de EMBY-005 sobre el Compose antiguo.
3. **Antes de pasar desde la versión original,** conserva el `.env` y la copia del historial anterior; sin ellos no hay forma de volver al estado previo.

Base y aplicación se revierten por separado. No existe importación desde CSV ni otro mecanismo para reconstruir un historial perdido.

## Más guías

[`INSTALLATION.md`](INSTALLATION.md) · [`DEPLOYMENT_STEP_BY_STEP.md`](DEPLOYMENT_STEP_BY_STEP.md) · [`SECURITY.md`](SECURITY.md)
