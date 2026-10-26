# Instalacion (EMBY-005)

Guia de instalacion de produccion con Docker Compose. Detalle paso a paso:
`docs/DEPLOYMENT_STEP_BY_STEP.md`. Migracion desde una version anterior:
`docs/MIGRATION.md`. Endurecimiento: `docs/SECURITY.md`.

## Requisitos

| Componente | Minimo | Notas |
|---|---|---|
| Docker Engine | 24 | en el host |
| Docker Compose | v2.20 | `docker compose`, no `docker-compose` |
| Python (solo desarrollo) | 3.11 | la imagen ya lo incluye |
| Disco | ~1 GB | imagen + volumen SQLite |

La imagen corre como **usuario no privilegiado (UID/GID 10001)**. El volumen
pertenece a ese usuario: no hace falta `chown` manual.

## 1. Credenciales

```bash
cp .env.example .env
```

Rellena al menos `TELEGRAM_TOKEN`, `EMBY_API_KEY` y `CHAT_IDS`. Sin esos tres valores
la aplicacion **no arranca**: falla al construir `Settings` y el contenedor se detiene
con un error explicito.

> `.env` esta excluido por `.gitignore` y `.dockerignore`. Las credenciales nunca
> entran en la imagen ni en el repositorio.

## 2. Arranque

```bash
docker compose --profile production up --build -d
docker compose ps
curl -fsS http://127.0.0.1:${APP_PORT:-8081}/health
```

`/health` responde `{"status":"ok"}` y no depende de que Telegram o Emby esten
alcanzables: es valido para el `HEALTHCHECK` del contenedor.

Comprobar que no corre como root:

```bash
docker compose exec app id      # -> uid=10001(app gid=10001(app
```

## 3. Instalaciones paralelas

El `docker-compose.yml` publico **no** fija `container_name` ni `name:` de volumen:
Compose deriva ambos del proyecto. Para levantar una segunda copia sin pisar nada:

```bash
docker compose -p emby-otra-instalacion -f docker-compose.yml --profile production up -d
APP_PORT=9081 docker compose -p emby-otra-instalacion -f docker-compose.yml --profile production up -d
```

## 4. Panel de publicacion y conciliacion (opcional)

El panel esta **desactivado por defecto**. Para activarlo anade a `.env`:

```env
PANEL_ENABLED=true
PANEL_ADMIN_PASSWORD=<minimo 16 caracteres, no placeholder>
PANEL_SECRET_KEY=<minimo 32 caracteres, distinto de la contrasena>
PANEL_ALLOW_SENDS=false
```

```bash
python3 -c "import secrets;print(secrets.token_urlsafe(24))"   # PANEL_ADMIN_PASSWORD
python3 -c "import secrets;print(secrets.token_hex(32))"      # PANEL_SECRET_KEY
```

Reglas que el servidor aplica y no admite saltarse:

- `PANEL_ADMIN_PASSWORD`: minimo **16** caracteres y no un valor de demo ni placeholder
  (`replace`, `change`, `changeme`, `example`, `emby-demo`, `<`, `>`).
- `PANEL_SECRET_KEY`: minimo **32** caracteres, no placeholder y **distinto** de la
  contrasena.
- `PANEL_ALLOW_SENDS=false` por defecto. Solo afecta a los envios manuales del panel;
  **los webhooks del bot siguen activos**.
- La cookie de sesion lleva `Secure=True`: el panel exige **HTTPS**. Ponlo detras de
  un proxy inverso con TLS; no lo expongas directamente a internet.

Si un requisito no se cumple, el contenedor no arranca.

## 5. Webhooks

### 5.1 Webhook de Telegram (`/telegramhook`)

Telegram llama a esta ruta. Si defines `TELEGRAM_WEBHOOK_SECRET`, el servidor exige la
cabecera `X-Telegram-Bot-Api-Secret-Token` con ese valor; si lo dejas vacio, no la exige.

### 5.2 Webhook de Emby (`/embyhook`)

Esta ruta **no usa `TELEGRAM_WEBHOOK_SECRET`**: ese valor solo aplica a `/telegramhook`.
La proteccion de `/embyhook` depende de la red y del proxy:

- Restringe quien puede alcanzar el puerto 8081 (o el proxy): red interna, VPN o
  allow-list por IP.
- Si tu proxy inverso lo permite, exige una cabecera/token propio configurado ahi.
- Como capa adicional, el panel y la conciliacion son de solo lectura: ninguna accion
  de conciliacion envia publicaciones.

## 6. Persistencia

| Ruta | Contenido | Persistencia |
|---|---|---|
| `/data/history.sqlite3` | ledger de entregas e historial | volumen del proyecto |
| `/data/` | WAL/SHM junto a la base | mismo volumen |

SQLite con `journal_mode=WAL`. El volumen es propiedad del UID 10001, asi que el
servicio crea y rota el fichero sin privilegios.

## 7. Backup y restauracion

```bash
scripts/backup.sh /ruta/segura                    # online, sin parar el servicio
scripts/restore.sh /ruta/segura/history-AAAAMMDDTHHMMSSZ-XXXXXX.sqlite3 # con el servicio PARADO
scripts/restore.sh /ruta/segura/history-AAAAMMDDTHHMMSSZ-XXXXXX.sqlite3 --check   # solo valida
```

Ambos guiones derivan el contenedor y el volumen del propio Compose (`COMPOSE_FILE` y
`COMPOSE_PROJECT_NAME`), y el backup/restore mueve los datos por **stdin**: no dependen
de rutas internas de Docker (`/var/lib/docker`) ni de montar el volumen a mano.

- **Backup**: copia transaccional (`sqlite3.backup`) sobre conexion de solo lectura.
  Seguro con el servicio escribiendo. Verifica `PRAGMA integrity_check == ok` y no
  deja el fichero vacio. `umask 077`: solo tu usuario lo lee.
- **Restauracion**: el script **se niega** a continuar si el servicio sigue en marcha
  (el estado del contenedor debe ser `exited`). Es deliberado: sobrescribir el fichero bajo
  gunicorn con WAL deja la base inconsistente. Deten el servicio, restaura y arranca:
  ```bash
  docker compose -f docker-compose.yml stop app
  scripts/restore.sh /ruta/segura/history-AAAAMMDDTHHMMSSZ-XXXXXX.sqlite3
  docker compose -f docker-compose.yml --profile production up -d app
  ```
- La restauracion conserva siempre la base vigente como
  `<backup>.pre-restore-<fecha>.sqlite3` antes de sobrescribir.
- El backup **no** copia `.env` ni credenciales: solo el ledger.

## 8. Rollback

La restauracion de la base y el rollback de la aplicacion son **pasos separados y
manuales**; no hay automatismo que cambie la imagen a mitad de un comando.

1. Base de datos: seccion 7.
2. Aplicacion: conserva previamente la imagen anterior y su Compose. Para una imagen ya construida compatible con el servicio `app`:

   ```bash
   APP_IMAGE=<imagen-anterior-conservada> docker compose --profile production up -d --no-build app
   ```

   Si regresas al bot original, utiliza el Compose y las instrucciones de esa versión: los servicios y perfiles no se llaman igual. Conserva siempre el historial y los secretos por separado.

El esquema SQLite es compatible entre versiones: se crea con `CREATE TABLE IF NOT EXISTS`
y se versiona con `PRAGMA user_version`. Un esquema incompatible se rechaza con error
explicito en lugar de corromper el historial. **No se inventa historial**: sin entrega
registrada, el estado es `history_unknown`.

## 9. Demo local y smoke aislado

El `docker-compose.yml` base **no** publica puertos del servicio `demo`: se anaden en
`docker-compose.demo.yml`, para no exponer nada por defecto. No se usan etiquetas
`!override` / `!reset` (exigirian Compose 2.24.4): basta con el minimo de la tabla de
requisitos.

### 9.1 Demo usable en local

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile demo up -d
curl -fsS http://127.0.0.1:8093/health
```

Publica **solo en 127.0.0.1** (`DEMO_PORT` controla el puerto). Usa datos
sinteticos, no lee `.env` (`env_file: []`) y no registra comandos de Telegram.

La app de demo usa su contrasena publica de siempre (`emby-demo-003`). No existe
ninguna variable para cambiarla: el panel de demo no lee `PANEL_*`. Es un entorno
sintetico sin credenciales reales.

### 9.2 Smoke totalmente aislado (sin red, sin puertos)

```bash
docker compose -p emby005smoke -f docker-compose.yml -f docker-compose.smoke.yml --profile demo up -d
docker exec emby005smoke-demo-1 curl -fsS http://127.0.0.1:8093/health
docker exec emby005smoke-demo-1 id
docker inspect -f '{{.HostConfig.NetworkMode}}' emby005smoke-demo-1   # -> none
docker compose -p emby005smoke -f docker-compose.yml -f docker-compose.smoke.yml down -v
```

Con `network_mode: none` el contenedor no tiene red: no puede abrir conexiones
salientes y no publica puertos. Por eso la comprobacion es con `docker exec` **dentro**
del contenedor, no desde el host. El proyecto se llama `emby005smoke` para no chocar
con ninguna instalacion existente.

## 10. Actualizacion

```bash
git pull
scripts/backup.sh /ruta/segura
docker compose --profile production up --build -d
```

## 11. Solucion de problemas

| Sintoma | Causa probable |
|---|---|
| El contenedor se detiene al arrancar | falta `TELEGRAM_TOKEN`, `EMBY_API_KEY` o `CHAT_IDS` |
| `PANEL_ENABLED=true` y no arranca | contrasena o clave de session no cumplen los requisitos |
| `/health` responde pero no llegan mensajes | bot fuera del grupo, `CHAT_IDS` incorrecto, o Emby no alcanza el webhook |
| El panel no acepta el login | la cookie es `Secure`: falta HTTPS |
| El panel no existe | `PANEL_ENABLED` sigue en `false` |
| El contenedor no escribe en `/data` | el volumen no es del UID 10001; recrear el volumen |
| `restore.sh` se niega a continuar | el servicio sigue en marcha: paralo antes |
| Dos instalaciones se pisan | falta `-p <proyecto>` distinto (seccion 3) |

Logs:

```bash
docker compose logs -f app
```
