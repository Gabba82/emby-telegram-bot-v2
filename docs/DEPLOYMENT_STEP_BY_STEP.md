# Despliegue paso a paso (EMBY-005)

Guía para empezar desde cero. La referencia completa es [`INSTALLATION.md`](INSTALLATION.md); ante cualquier diferencia, manda esa. Para migrar una instalación existente: [`MIGRATION.md`](MIGRATION.md).

## 1. Prepara Telegram

1. En Telegram abre `@BotFather`, escribe `/newbot` y guarda el token (`123456789:AA...`).
2. Añade el bot al grupo o canal de avisos (si es canal, con permiso para publicar).
3. Obtén el `chat_id`: escribe un mensaje en el grupo y abre `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`; busca `chat` → `id` (en supergrupos empieza por `-100`).
4. Para tu ID privado (`ADMIN_CHAT_IDS`), escribe al bot en privado y repite `getUpdates`.

Varios destinos van separados por comas: `CHAT_IDS=-1001234567890,-1009876543210`.

## 2. Prepara Emby

Como administrador: **Claves de API** → crear una clave. Anota la URL base, con formato `http://IP_O_HOST:8096/emby`.

## 3. Configura el proyecto

```bash
git clone <URL_DEL_REPO> && cd <directorio>
cp .env.example .env
```

Rellena al menos `TELEGRAM_TOKEN`, `EMBY_API_KEY` y `CHAT_IDS` (y `EMBY_API_URL` si Emby no está en `http://emby:8096/emby`). El resto tiene valores por defecto razonables. Sin esos tres valores el contenedor no arranca.

## 4. Despliega

```bash
docker compose --profile production up --build -d
docker compose ps
curl -fsS http://127.0.0.1:8081/health      # {"status":"ok"}
docker compose exec app id                  # uid=10001
```

Sin `--profile production` Compose **no** arranca el servicio `app`. Para una segunda instalación en el mismo equipo usa otro `COMPOSE_PROJECT_NAME` y otro `APP_PORT`.

## 5. Webhooks

- **Emby** → URL `http://TU_HOST:8081/embyhook`, método `POST`. Esta ruta no usa secreto: protégela por red (red interna, VPN o lista de IP) o con una cabecera propia en tu proxy.
- **Telegram** → `/telegramhook` con HTTPS y, opcionalmente, `TELEGRAM_WEBHOOK_SECRET`. Los comandos `curl` de `setWebhook` están en [`USAGE.md`](USAGE.md#8-webhook-de-telegram-y-https).

## 6. Prueba

1. Añade una película o un episodio en Emby y comprueba el grupo de Telegram.
2. Abre el bot en privado, pulsa **Iniciar** y escribe `/buscar`.
3. Si no llega nada: `docker compose logs -f app`.

## 7. Panel (opcional)

Desactivado por defecto. Para activarlo (`PANEL_ENABLED=true`, contraseña de 16 caracteres o más, clave de sesión de 32 o más, y HTTPS) sigue la sección 4 de [`INSTALLATION.md`](INSTALLATION.md). Para probarlo sin credenciales reales usa la demostración ([`USAGE.md`](USAGE.md#4-demostración-local-linux-y-windows)).

## 8. Copias de seguridad y actualización

```bash
scripts/backup.sh /ruta/segura          # en caliente; el contenedor debe estar en marcha
git pull
docker compose --profile production up --build -d
```

Restaurar exige parar antes el servicio (`docker compose stop app`, no `down`) y usar `scripts/restore.sh <copia>`; ver [`MIGRATION.md`](MIGRATION.md) e [`INSTALLATION.md`](INSTALLATION.md).

## 9. Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `docker compose up` no arranca nada | falta `--profile production` |
| El contenedor se detiene al arrancar | falta `TELEGRAM_TOKEN`, `EMBY_API_KEY` o `CHAT_IDS`, o el panel está activado con credenciales no válidas |
| No llega nada a Telegram | bot fuera del grupo o `CHAT_IDS` incorrecto |
| Emby no alcanza el bot | IP, puerto o cortafuegos; prueba `/health` desde la red de Emby |
| El panel no acepta el login | falta HTTPS (cookie `Secure`) |
| El panel no existe | `PANEL_ENABLED` sigue en `false` |
| No se escribe en `/data` | el volumen no es del UID 10001; recrea el volumen |

## 10. Buenas prácticas

- No subas `.env` al repositorio y rota las claves si se filtran.
- Haz una copia del historial antes de cada actualización.
- Limita el puerto 8081 a la red de confianza o publícalo tras un proxy inverso con TLS.
