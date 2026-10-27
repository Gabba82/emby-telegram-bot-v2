# Notas de seguridad (EMBY-005)

## Secretos

- `.env` esta excluido por `.gitignore` **y** `.dockerignore`: las credenciales no
  entran en el contexto de build ni en la imagen.
- La imagen no contiene ningun token ni clave. Solo codigo y assets estaticos.
- Las credenciales se inyectan en tiempo de ejecucion por entorno.
- Rota `TELEGRAM_TOKEN` y `EMBY_API_KEY` si alguna vez se expusieron.
- El backup de la base **no** copia `.env` ni credenciales: solo el ledger SQLite.

## Ejecucion

- El contenedor corre como **usuario no privilegiado** `10001:10001` (`USER` en el
  `Dockerfile`). No hay shell interactiva (`/usr/sbin/nologin`).
- El unico puerto expuesto es el de la aplicacion. `/health` no requiere autenticacion
  (no revela secretos: solo `{"status":"ok"}`).
- `curl` esta en la imagen unicamente para el `HEALTHCHECK`; no se expone al servicio.

## Panel de publicacion

- Desactivado por defecto (`PANEL_ENABLED=false`). Si no se activa, no existe ninguna
  ruta `/manager/` ni `/api/*` del panel.
- Requisitos que el servidor aplica y no admite saltarse:
  - `PANEL_ADMIN_PASSWORD`: minimo 16 caracteres, sin valores de demo ni placeholder.
  - `PANEL_SECRET_KEY`: minimo 32 caracteres, sin placeholder y distinto de la
    contrasena.
  - `PANEL_ALLOW_SENDS=false` por defecto. Solo limita los envios manuales del panel;
    los webhooks del bot siguen activos.
- Cookie de sesion: `HttpOnly`, `SameSite=Strict` y **`Secure=True`**. El panel exige
  HTTPS. Si se sirve por HTTP, el login nunca funcionara (la cookie no se envia).
- Todas las mutaciones exigen el token CSRF (`X-CSRF-Token`); sin el o con uno ajeno
  responden `403` y no ejecutan nada. El token rota en cada login y logout.
- Los endpoints de conciliacion son de **solo lectura**: ninguna accion de conciliacion
  envia publicaciones. El unico endpoint que envia es
  `POST /api/batches/<batch_id>/confirm`.

## Red

- Publica el puerto solo en la red de confianza o detras de proxy inverso con TLS.
- El perfil `demo` corre con `network_mode: none`: no puede abrir ninguna conexion
  saliente. Usalo para verificar la instalacion sin riesgo.
- `TELEGRAM_WEBHOOK_SECRET` protege **solo** `/telegramhook`: si se define, el servidor
  exige la cabecera `X-Telegram-Bot-Api-Secret-Token`. El webhook de **Emby**
  (`/embyhook`) **no** usa esa variable; su proteccion depende de la red y del proxy
  (allow-list por IP, red interna, o una cabecera/token propio exigido en el proxy).

## Datos

- El ledger SQLite vive en el volumen del proyecto (`<proyecto>_history-data`), propiedad del UID 10001.
- El backup es una copia transaccional (`sqlite3.backup`): consistente aunque el servicio
  este escribiendo, y no requiere detenerlo.
- La restauracion **exige el servicio parado** (`docker compose stop`, no `down`: el contenedor
  debe seguir existiendo para localizar su volumen) y verifica `PRAGMA integrity_check`
  antes de sobrescribir. Conserva siempre una copia de la base vigente con sufijo
  `.pre-restore-<fecha>`.
- **El historial no se reconstruye ni se infiere.** Sin entrega registrada, el estado es
  `history_unknown` con un motivo explicito. El sistema nunca sentencia "perdido" ni
  reenvia por su cuenta.

## Registro

- Los logs no incluyen tokens ni claves. Los errores se registran por codigo
  (`error_type`), nunca con la excepcion completa ni con URLs que contengan claves.
- Errores de API: `{"error": "<codigo>", "message": "<texto legible>"}` con 400/401/403/
  409/429/503. Sin trazas.

### Publicación de red por defecto

El puerto publicado escucha por defecto en `127.0.0.1:8081` (`APP_BIND=127.0.0.1`). Un proxy ejecutado **en el host** puede reenviar a `http://127.0.0.1:8081`. Si Emby accede directamente desde otra máquina, configura explícitamente `APP_BIND=<IP-de-confianza-del-host>` y restringe el acceso con firewall/VPN. No uses `0.0.0.0` sin una protección equivalente.

Un proxy en **otro contenedor** no alcanza el loopback del host: conéctalo mediante una red Docker compartida al servicio `app:8081`, o configura una IP de confianza explícita y reglas de firewall. El puerto interior del contenedor sigue siendo 8081. Mantén HTTPS y la cabecera de secreto para `/telegramhook`; **`/embyhook` carece de autenticación propia** y necesita protección de red o controles específicos del proxy, incluso si se sirve por HTTPS.
