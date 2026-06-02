# emby-telegram-bot-v2

Version limpia y documentada del bot Emby -> Telegram.

Licencia: MIT (ver `LICENSE`).

## Que hace este proyecto

Este servicio recibe eventos de Emby por webhook y envia notificaciones a uno o varios chats de Telegram:

- Nuevas peliculas.
- Nuevos episodios.
- Agrupacion de episodios por temporada en una sola notificacion (buffer temporal).
- Eventos de reproduccion (inicio, pausa, reanudar, stop) si los activas en Emby.
- Consultas desde Telegram con boton o comando `/buscar`.
- Reenvio manual desde Telegram con selector grafico (`/reenviar`, `/reenviaultimo` y `/reenvia ID`).
- Deduccion de calidad/formato usando metadata de Emby (`MediaSources/MediaStreams`) con fallback por nombre/ruta.
- Campos desconocidos ocultos en specs (evita ruido de `N/D`).

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

## Despliegue en produccion con dominio HTTPS

Esta es la configuracion recomendada para usar el bot de forma estable sin ngrok.

### 1. Preparar `.env`

Crea el archivo:

```bash
cp .env.example .env
```

Edita `.env`:

```bash
nano .env
```

Ejemplo:

```env
TELEGRAM_TOKEN=token_real_de_botfather
CHAT_IDS=-1001234567890
ADMIN_CHAT_IDS=123456789
LIBRARY_CHAT_IDS=-1001234567890
PLAYBACK_CHAT_IDS=-1001234567890
CHAT_LABELS=chat:Canal novedades,playback:Grupo reproduccion,private:Mi privado
EMBY_API_URL=https://emby.tudominio.duckdns.org/emby
EMBY_API_KEY=api_key_real_de_emby
REQUEST_TIMEOUT_SECONDS=15
EPISODE_BUFFER_SECONDS=60
LIBRARY_DEBOUNCE_SECONDS=120
PLAYBACK_DEBOUNCE_SECONDS=10
ENABLE_LIBRARY_NOTIFICATIONS=true
ENABLE_PLAYBACK_NOTIFICATIONS=true
PLAYBACK_NOTIFY_PAUSE=false
PLAYBACK_WITH_IMAGE=false
PLAYBACK_STYLE=compact
APP_TIMEZONE=Europe/Madrid
TELEGRAM_WEBHOOK_SECRET=un_secreto_simple_igual_en_telegram
```

Notas:

- `CHAT_IDS` debe ser el ID del grupo/chat autorizado. En grupos suele empezar por `-100`.
- `ADMIN_CHAT_IDS` debe incluir tu ID privado de Telegram para usar comandos administrativos por privado.
- `TELEGRAM_WEBHOOK_SECRET` puede ser cualquier texto, pero debe coincidir exactamente con el `secret_token` configurado en Telegram.
- Si no quieres usar secreto durante pruebas, deja `TELEGRAM_WEBHOOK_SECRET=` vacio y configura Telegram sin `secret_token`.

### 2. Levantar Docker

```bash
docker compose up -d --build
```

Comprueba que esta vivo:

```bash
docker compose ps
curl http://localhost:8081/health
```

Respuesta correcta:

```json
{"status":"ok"}
```

### 3. Configurar proxy inverso HTTPS

Telegram necesita una URL publica con HTTPS. Si usas Nginx Proxy Manager, Caddy, Nginx o similar, crea un proxy:

```text
https://embybot.tudominio.duckdns.org  ->  http://IP_DEL_SERVIDOR:8081
```

Ejemplo:

```text
https://embybot.tudominio.duckdns.org  ->  http://192.168.1.112:8081
```

No hace falta crear rutas especiales para `/telegramhook` o `/embyhook` si todo el dominio ya apunta al bot.

Activa SSL/HTTPS en el proxy y comprueba desde fuera:

```bash
curl https://embybot.tudominio.duckdns.org/health
```

Debe responder:

```json
{"status":"ok"}
```

Si usas DuckDNS y Telegram no resuelve el host, prueba con un dominio directo tipo:

```text
embybottudominio.duckdns.org
```

en vez de un sub-subdominio tipo:

```text
embybot.tudominio.duckdns.org
```

### 4. Configurar webhook de Telegram

Primero comprueba que el token funciona:

```bash
curl "https://api.telegram.org/botTU_TOKEN/getMe"
```

Debe devolver `"ok": true`.

Configura el webhook con secreto:

```bash
curl -X POST "https://api.telegram.org/botTU_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://embybot.tudominio.duckdns.org/telegramhook","secret_token":"EL_MISMO_SECRETO_DEL_ENV"}'
```

Si dejaste `TELEGRAM_WEBHOOK_SECRET=` vacio, usa:

```bash
curl "https://api.telegram.org/botTU_TOKEN/setWebhook?url=https://embybot.tudominio.duckdns.org/telegramhook"
```

Comprueba:

```bash
curl "https://api.telegram.org/botTU_TOKEN/getWebhookInfo"
```

Debe aparecer:

```json
"url":"https://embybot.tudominio.duckdns.org/telegramhook"
```

### 5. Configurar webhook en Emby

En Emby, configura el webhook hacia:

```text
https://embybot.tudominio.duckdns.org/embyhook
```

Eventos recomendados:

- Nuevo contenido de biblioteca.
- Playback start/stop/unpause si quieres eventos de reproduccion. El bot acepta nombres tipo `PlaybackStart`, `PlaybackStop`, `SessionStart` y tambien `playback.start`.
- Pause solo si no te molesta recibir mas mensajes.

### 6. Probar el bot

En Telegram:

1. Abre el bot en privado.
2. Pulsa `Iniciar`.
3. Escribe `/start` o `/menu`.
4. Debe quedar disponible el menu de comandos junto al campo de escritura. Si no aparece, cierra y abre el chat o reinicia Telegram.
5. Usa `/buscar` desde ese menu para buscar una pelicula o serie.

En el grupo:

1. Anade el bot al grupo.
2. Asegurate de que el `chat_id` del grupo esta en `.env`.
3. Como admin, escribe `/menu`.
4. Fija el mensaje con el boton `Buscar por privado`.

Cada usuario debe iniciar antes el bot en privado. Telegram no permite que un bot escriba primero a un usuario si ese usuario nunca pulso `Iniciar`.

### 7. Comandos utiles de mantenimiento

Ver estado:

```bash
docker compose ps
```

Ver logs:

```bash
docker compose logs -f
```

Reiniciar sin reconstruir:

```bash
docker compose restart
```

Reconstruir despues de actualizar codigo o `.env`:

```bash
docker compose down
docker compose up -d --build
```

Actualizar desde GitHub:

```bash
git pull
docker compose down
docker compose up -d --build
```

## Diagnostico rapido

El comando `/diagnostico` muestra comprobaciones con estado `[OK]`, `[WARNING]` o `[ERROR]` para configuracion local, acceso a Emby, token de Telegram, chats configurados, timezone, secreto de webhook y destinos efectivos. `/estado` sigue funcionando como alias, pero no se muestra como comando separado para evitar duplicados.

### No llegan notificaciones de reproduccion

Comprueba en este orden:

1. En Emby, el webhook/plugin debe apuntar a `https://TU_DOMINIO/embyhook`.
2. Activa eventos de reproduccion en Emby: `PlaybackStart`, `PlaybackStop`, `PlaybackPause`, `PlaybackUnpause` y, si lo usas, `SessionStart`/`SessionEnd`.
3. En `.env`, confirma `ENABLE_PLAYBACK_NOTIFICATIONS=true`.
4. Si usas destino separado, confirma `PLAYBACK_CHAT_IDS`; si esta vacio se usa `CHAT_IDS`.
5. Comprueba que el bot puede escribir en ese chat: no debe estar bloqueado y debe seguir dentro del grupo/canal.
6. Mira logs: `docker compose logs -f emby-telegram-bot`.
7. Desde un chat autorizado puedes enviar `/diagnostico` para validar configuracion, Emby API y Telegram API.

Los logs del bot muestran `raw_event` y `normalized_event`; si Emby envia `PlaybackStart`, debe aparecer `normalized_event=playback.start`.

### Las altas de biblioteca llegan duplicadas

Si ves dos entradas muy juntas para el mismo `item_id`, normalmente hay dos webhooks de Emby apuntando al bot o dos rutas distintas llegando a `/embyhook` (por ejemplo una interna y otra por proxy). Revisa en Emby que solo haya un webhook activo hacia el bot.

Como proteccion adicional, `LIBRARY_DEBOUNCE_SECONDS` evita reenviar el mismo item de biblioteca dentro de esa ventana. Por defecto son `120` segundos.

### `/health` funciona local, pero no por dominio

El problema esta en el proxy, DNS o SSL.

Comprueba:

```bash
curl http://localhost:8081/health
curl https://embybot.tudominio.duckdns.org/health
```

### Telegram sigue apuntando a ngrok o a una URL antigua

Comprueba:

```bash
curl "https://api.telegram.org/botTU_TOKEN/getWebhookInfo"
```

Si la URL no es la correcta, vuelve a ejecutar `setWebhook`.

### Error `401 Unauthorized`

El token de Telegram esta mal. Compruebalo con:

```bash
curl "https://api.telegram.org/botTU_TOKEN/getMe"
```

### Error `403 FORBIDDEN` o log `secret token did not match`

El secreto de Telegram no coincide con `.env`.

Comprueba:

```bash
grep TELEGRAM_WEBHOOK_SECRET .env
```

El valor debe ser exactamente el mismo que `secret_token` en `setWebhook`.

### Error `Failed to resolve host`

Telegram no puede resolver el dominio. Comprueba DNS:

```bash
nslookup embybot.tudominio.duckdns.org 1.1.1.1
```

Si usas DuckDNS, puede ser mejor crear un dominio directo `nombre.duckdns.org`.

### Error `bot can't initiate conversation with a user`

El usuario pulso el boton desde el grupo, pero nunca inicio el bot en privado.

Solucion:

1. El usuario abre el bot.
2. Pulsa `Iniciar`.
3. Vuelve al grupo.
4. Pulsa `Buscar por privado`.

### Logs con muchos `404` en `/`, `/.env`, `/graphql`, etc.

Son escaneos normales de internet. La app solo usa:

```text
/health
/telegramhook
/embyhook
```

Mientras `/health` devuelva `200` y los webhooks devuelvan `200`, esta bien.

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
- `ADMIN_CHAT_IDS`: IDs privados autorizados para comandos administrativos (`/reenviar`, `/reenviaultimo`, `/lastadded`, `/reenvia ID`, `/diagnostico`, `/diagnostico_playback`, `/version`, `/reload_menu`). Si se deja vacio, se usan los `CHAT_IDS`.
- `LIBRARY_CHAT_IDS`: opcional, destinos solo para altas de biblioteca (si vacio usa `CHAT_IDS`).
- `PLAYBACK_CHAT_IDS`: opcional, destinos solo para eventos de reproduccion (si vacio usa `CHAT_IDS`).
- `CHAT_LABELS`: opcional, nombres amigables para destinos. Acepta claves de destino (`private`, `chat`, `library`, `playback`, `admin`) o IDs concretos, por ejemplo `chat:Canal novedades,-100123:Grupo familia`.
- `EMBY_API_URL`: URL base de Emby, por ejemplo `http://192.168.1.112:8096/emby`.
- `EMBY_API_KEY`: API key de Emby.
- `REQUEST_TIMEOUT_SECONDS`: timeout de llamadas HTTP a Emby.
- `EPISODE_BUFFER_SECONDS`: segundos para agrupar episodios.
- `LIBRARY_DEBOUNCE_SECONDS`: ventana anti-duplicado para altas de biblioteca con el mismo item de Emby. Util si Emby o el proxy mandan el mismo webhook por dos caminos.
- `PLAYBACK_DEBOUNCE_SECONDS`: ventana anti-duplicado para eventos `playback.*` (excepto `playback.stop`).
- `ENABLE_LIBRARY_NOTIFICATIONS`: activa/desactiva notificaciones de biblioteca.
- `ENABLE_PLAYBACK_NOTIFICATIONS`: activa/desactiva notificaciones de reproduccion/sesion.
- `PLAYBACK_NOTIFY_PAUSE`: `true/false`, incluye eventos `playback.pause` (por defecto `false` para reducir spam).
- `PLAYBACK_WITH_IMAGE`: `true/false`, adjunta caratula en notificaciones de reproduccion.
- `PLAYBACK_STYLE`: `compact` o `detailed` para mensajes de reproduccion.
- `APP_TIMEZONE`: zona horaria IANA para la hora mostrada en reproduccion (ej. `Europe/Madrid`).
- `APP_VERSION`: opcional, etiqueta de build que muestra `/version` (en Docker usa `local` si no se indica otra).
- `TELEGRAM_WEBHOOK_SECRET`: opcional, secreto para validar el webhook de Telegram.

## Consultas desde Telegram

El bot puede buscar peliculas y series en Emby desde Telegram.

- Envia `/menu` al bot y pulsa `Buscar por privado`.
- O envia directamente `/buscar nombre de la peli o serie`.
- El menu de comandos de Telegram se configura al arrancar el bot. Los usuarios normales ven `/buscar`, `/help` y `/menu`.
- En el chat privado con el bot, `/start` o `/menu` recuerda usar el menu de comandos junto al campo de escritura.
- Los admins definidos en `ADMIN_CHAT_IDS` ven comandos extra en su chat privado: `/reenviar`, `/reenviaultimo`, `/reenvia`, `/diagnostico`, `/version` y `/reload_menu`.
- Si actualizas `ADMIN_CHAT_IDS` o cambias los comandos, reinicia el contenedor para que Telegram reciba el menu nuevo.
- Si pulsas el boton desde un grupo autorizado, el bot intentara abrir la busqueda por privado con ese usuario para no ensuciar el chat.
- El usuario debe haber iniciado antes una conversacion privada con el bot; si no, Telegram no permite que el bot le escriba.
- Al iniciar una busqueda sin texto, el bot deja filtrar por `Todo`, `Peliculas` o `Series`.
- Despues de una ficha aparece `Buscar otra vez` para lanzar otra consulta sin volver al menu.
- En privado, si hay varios resultados se muestran como botones para elegir uno; al seleccionarlo se envia la ficha con caratula y sinopsis cuando Emby tiene esos datos.
- En series, la ficha intenta mostrar temporadas y episodios disponibles en rangos compactos. Si Emby devuelve detalles de episodios, tambien resume audio y subtitulos comunes a todos ellos.
- En peliculas, la ficha intenta mostrar resolucion, contenedor, tamano, video, audios y subtitulos; si hay varias versiones, lista cada una.
- En peliculas y series, si Emby tiene ID de IMDb en `ProviderIds`, la ficha anade enlace directo a IMDb.
- Cuando Telegram lo soporta, la sinopsis se envia como bloque desplegable para no ocupar toda la tarjeta.

## Reenvio manual tras reidentificar en Emby

Configura primero tu ID privado en `ADMIN_CHAT_IDS` y abre una conversacion privada con el bot.

- `/reenviar`: muestra un menu con los ultimos contenidos anadidos. Elige uno y luego elige destino.
- `/reenviaultimo` o `/lastadded`: consulta en Emby el ultimo elemento anadido (`Movie`, `Series` o `Episode`) y muestra el selector de destino.
- `/reenvia 12345`: carga el item con ID de Emby `12345` y muestra el selector de destino.
- `/diagnostico_playback`: valida credenciales y muestra destinos activos para reproduccion y biblioteca.
- `/estado`: alias oculto de `/diagnostico` para ver configuracion y salud.
- `/help`: muestra los comandos disponibles segun seas usuario normal o admin.
- `/version`: muestra la version del paquete y el build configurado con `APP_VERSION`.
- `/reload_menu`: vuelve a registrar el menu de comandos de Telegram sin reiniciar el contenedor.

El menu de recientes muestra peliculas y series. Si Emby devuelve episodios recientes, el bot intenta agruparlos por serie para evitar reenviar capitulos uno a uno. El selector de destino usa los chats definidos en `.env`: `CHAT_IDS`, `LIBRARY_CHAT_IDS`, `PLAYBACK_CHAT_IDS`, `ADMIN_CHAT_IDS` y tu chat privado actual. Al confirmar, el bot vuelve a consultar Emby y regenera la notificacion con metadata actual.

Al reenviar una serie, el bot consulta temporadas y episodios para reconstruir una ficha mas completa: temporadas disponibles, rangos de capitulos y, cuando Emby lo facilita, audio/subtitulos comunes en los episodios. Esto evita que el reenvio de una serie quede reducido a solo caratula y titulo.

Esto esta pensado para el caso en que Emby identifico mal una pelicula/serie al entrar en biblioteca. Reidentifica manualmente en Emby, espera a que Emby guarde la metadata y ejecuta `/reenviar`, `/reenviaultimo` o `/reenvia ID` por privado.

Si haces una busqueda desde tu chat privado admin, la ficha del resultado incluye acciones para `Reenviar al canal` o elegir otro destino sin copiar el ID a mano.

Para recibir esos mensajes, configura el webhook de Telegram apuntando a:

```text
https://<HOST>/telegramhook
```

Telegram necesita una URL publica con HTTPS. Si el contenedor escucha en `:8081`, ponlo detras de un proxy inverso con TLS que redirija a `http://localhost:8081/telegramhook`.

Si defines `TELEGRAM_WEBHOOK_SECRET`, configura el webhook de Telegram usando ese mismo secret token para que el endpoint rechace llamadas no autorizadas.

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
