# emby-telegram-bot-v2

Version limpia y documentada del bot Emby -> Telegram.

Licencia: MIT (ver `LICENSE`).

## Que hace este proyecto

Este servicio recibe eventos de Emby por webhook y envia notificaciones a uno o varios chats de Telegram:

- Nuevas peliculas.
- Nuevos episodios.
- Agrupacion de episodios por temporada en una sola notificacion (buffer temporal).
- Eventos de reproduccion (inicio, pausa, reanudar, stop) si los activas en Emby.

## Para quien es

Esta guia esta pensada para usuarios sin experiencia tecnica. Si sabes copiar/pegar comandos, lo puedes desplegar.

## Mejoras sobre la version original

- Secretos fuera del codigo (`.env`).
- Codigo modular y mantenible.
- Escape seguro de texto para Telegram MarkdownV2.
- Buffer de episodios con control de concurrencia.
- Tests unitarios base.

## Requisitos

Necesitas:

- Docker y Docker Compose instalados.
- Un bot de Telegram (token de BotFather).
- Tu `chat_id` (o varios) del grupo/canal destino.
- URL y API key de Emby.

## Despliegue rapido (Docker)

1. Clonar este repositorio.
2. Entrar en la carpeta del proyecto.
3. Crear `.env` desde el ejemplo:
```bash
cp .env.example .env
```
En Windows PowerShell:
```powershell
Copy-Item .env.example .env
```
4. Editar `.env` y rellenar valores reales.
5. Levantar el contenedor:
```bash
docker compose up --build -d
```
6. Verificar salud:
```bash
curl http://localhost:8081/health
```
Respuesta esperada:
```json
{"status":"ok"}
```

Este despliegue usa `gunicorn` en Docker (servidor WSGI de produccion).

## Configuracion paso a paso (detallada para principiantes)

Consulta la guia completa:

- `docs/DEPLOYMENT_STEP_BY_STEP.md`

Incluye:

- Como crear bot en Telegram.
- Como sacar `chat_id`.
- Como configurar webhook en Emby.
- Como validar que todo funciona.
- Como resolver errores comunes.

## Variables de entorno

Ejemplo completo en `.env.example`.

- `TELEGRAM_TOKEN`: token de BotFather.
- `CHAT_IDS`: uno o varios chat IDs separados por coma.
- `EMBY_API_URL`: URL base de Emby, por ejemplo `http://192.168.1.112:8096/emby`.
- `EMBY_API_KEY`: API key de Emby.
- `REQUEST_TIMEOUT_SECONDS`: timeout de llamadas HTTP a Emby.
- `EPISODE_BUFFER_SECONDS`: segundos para agrupar episodios.
- `PLAYBACK_WITH_IMAGE`: `true/false`, adjunta caratula en notificaciones de reproduccion.
- `PLAYBACK_STYLE`: `compact` o `detailed` para mensajes de reproduccion.

## Seguridad minima recomendada

- No publiques nunca `.env`.
- Rota tokens si alguna vez se exponen.
- Limita acceso a `:8081` solo a red confiable.

Mas detalles:

- `docs/SECURITY.md`

## Test

```bash
python -m pytest -q -p no:cacheprovider
```

## Estructura del proyecto

- `src/emby_telegram_bot/config.py`: carga/validacion de entorno.
- `src/emby_telegram_bot/emby_client.py`: cliente Emby.
- `src/emby_telegram_bot/telegram_client.py`: envio Telegram.
- `src/emby_telegram_bot/formatting.py`: captions/specs.
- `src/emby_telegram_bot/episode_aggregator.py`: agrupado de episodios.
- `src/emby_telegram_bot/webhook.py`: endpoints Flask.
- `src/emby_telegram_bot/main.py`: entrada principal.

## Migracion desde la version anterior

- `docs/MIGRATION.md`

## Contribuir

- `CONTRIBUTING.md`
