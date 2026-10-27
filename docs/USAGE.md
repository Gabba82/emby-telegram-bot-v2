# Guía de uso

Esta guía describe cómo se usa el bot desde Telegram, el panel web y la demostración local. Para instalar, consulta [`INSTALLATION.md`](INSTALLATION.md); para migrar desde una versión anterior, [`MIGRATION.md`](MIGRATION.md).

Índice:

1. [Notificaciones automáticas](#1-notificaciones-automáticas)
2. [Comandos de Telegram](#2-comandos-de-telegram)
3. [Historial de entregas y estados](#3-historial-de-entregas-y-estados)
4. [Demostración local (Linux y Windows)](#4-demostración-local-linux-y-windows)
5. [Panel web](#5-panel-web)
6. [Conciliación](#6-conciliación)
7. [Autenticación y confirmaciones del panel](#7-autenticación-y-confirmaciones-del-panel)
8. [Webhook de Telegram y HTTPS](#8-webhook-de-telegram-y-https)
9. [Diagnóstico y problemas frecuentes](#9-diagnóstico-y-problemas-frecuentes)

## 1. Notificaciones automáticas

El bot recibe eventos de Emby en `POST /embyhook`:

- **Biblioteca**: películas y episodios nuevos. Los episodios se agrupan por temporada durante `EPISODE_BUFFER_SECONDS` (60 s por defecto) para enviar una sola ficha. Antes de publicar se vuelven a consultar los datos del contenido en Emby. `LIBRARY_DEBOUNCE_SECONDS` (120 s) evita reenviar el mismo elemento si Emby o un proxy entregan el webhook dos veces.
- **Reproducción** (si `ENABLE_PLAYBACK_NOTIFICATIONS=true`): inicio y parada; pausa solo con `PLAYBACK_NOTIFY_PAUSE=true`. Se aceptan nombres como `PlaybackStart`, `PlaybackStop`, `SessionStart` y `playback.start`. `PLAYBACK_STYLE` elige `compact` o `detailed`.

Los destinos son `LIBRARY_CHAT_IDS` y `PLAYBACK_CHAT_IDS`; si están vacíos se usa `CHAT_IDS`. Cada publicación automática de biblioteca queda registrada en el historial de entregas (origen `automatic`).

Eventos recomendados en el webhook de Emby: nuevo contenido de biblioteca y, si los quieres, inicio, parada y reanudación de reproducción.

## 2. Comandos de Telegram

El menú de comandos se registra al arrancar. Cada usuario debe haber pulsado **Iniciar** en el chat privado con el bot; Telegram no permite que un bot escriba primero.

### Todos los usuarios

| Comando | Descripción |
|---|---|
| `/start`, `/menu` | En privado, recuerda cómo usar el menú de comandos; en un grupo, muestra el botón **Buscar por privado** (fíjalo como administrador). |
| `/buscar [título]` | Busca películas y series. Sin texto ofrece filtrar por **Todo**, **Películas** o **Series**. Con varios resultados se muestran botones; al elegir uno llega la ficha con carátula y sinopsis. |
| `/help` | Ayuda según seas usuario o administrador. |

En una conversación privada, escribir un texto sin comando también lanza una búsqueda. Las fichas de serie resumen temporadas, rangos de capítulos y audio/subtítulos comunes; las de película, resolución, contenedor, tamaño, video, audios y subtítulos, con enlace a IMDb cuando Emby lo conoce. Tras una ficha aparece **Buscar otra vez**.

### Chats autorizados

| Comando | Descripción |
|---|---|
| `/diagnostico` | Comprobaciones `[OK]`, `[WARNING]` o `[ERROR]` de configuración, acceso a Emby, token de Telegram, chats, zona horaria, secreto del webhook y destinos efectivos. `/estado` y `/diagnostico_playback` son alias. |

### Administradores (chat privado y en `ADMIN_CHAT_IDS`)

Si `ADMIN_CHAT_IDS` está vacío, los comandos de reenvío usan `CHAT_IDS` como administradores. **`/historial` y `/reintentar` nunca recurren a `CHAT_IDS`**: exigen estar listado en `ADMIN_CHAT_IDS` y escribir en privado.

| Comando | Descripción |
|---|---|
| `/reenviar` | Menú de contenido reciente (películas y series; los episodios recientes se agrupan por serie). Elige contenido y luego destino. |
| `/reenviaultimo` (`/lastadded`) | Muestra el último elemento añadido y el selector de destino. |
| `/reenvia ID_DE_EMBY` | Carga el elemento con ese ID y muestra el selector de destino. |
| `/historial [página] [estado]` | Lista entregas, 5 por página. Estados: `enviado`, `fallido`, `pendiente`, `incierto`. |
| `/historial item ID_DE_EMBY` | Estado de un contenido en cada destino configurado, incluido «historial desconocido». |
| `/reintentar NÚMERO` | Reintenta una entrega **pendiente o fallida**. |
| `/reintentar NÚMERO confirmar-incierto` | Reintenta una entrega **incierta**, aceptando que pueda duplicarse. |
| `/version` | Versión del paquete y build (`APP_VERSION`). |
| `/reload_menu` | Vuelve a registrar el menú de comandos sin reiniciar. |

El selector de destino usa los chats definidos en `.env` (`CHAT_IDS`, `LIBRARY_CHAT_IDS`, `PLAYBACK_CHAT_IDS`, `ADMIN_CHAT_IDS`) y tu chat privado. Al confirmar, el bot vuelve a consultar Emby y regenera la ficha con la metadata actual, pensado para cuando Emby identificó mal un contenido: reidentifícalo en Emby, espera a que guarde la metadata y reenvíalo. Si buscas desde tu chat privado de administrador, la ficha incluye **Reenviar al canal** o elegir otro destino.

Ejemplos:

```text
/historial                  # primera página
/historial 2 fallido        # página 2, solo fallidas
/historial item 12345       # estado del contenido 12345 por destino
/reintentar 87              # entrega pendiente o fallida #87
/reintentar 87 confirmar-incierto
```

## 3. Historial de entregas y estados

Cada publicación se guarda en SQLite (`HISTORY_DB_PATH`) como una **entrega** (contenido × destino) con uno o más **intentos**. Debes conservar ese fichero en un volumen persistente.

| Estado | Significado |
|---|---|
| `enviado` | Telegram confirmó el envío (se guarda el número de mensaje). |
| `fallido` | El último intento falló con un error conocido; se puede reintentar. |
| `pendiente` | Intención registrada, sin intento realizado aún. |
| `incierto` | Hubo un intento sin confirmación fiable (p. ej. tiempo de espera); puede haber llegado o no. **Nunca se reenvía solo.** |
| historial desconocido | No hay ningún registro para ese contenido y destino. No demuestra que nunca se enviara. |

Un contenido con algún envío confirmado en un destino se considera `enviado` aunque tenga intentos fallidos anteriores.

## 4. Demostración local (Linux y Windows)

La demostración arranca el panel con **datos ficticios**: sin `.env`, sin credenciales reales y con las conexiones salientes bloqueadas. Los «envíos» son simulados (el destino «Laboratorio privado» devuelve estado incierto y «Series · pruebas» falla en el primer intento, para poder probar la recuperación).

**Linux/macOS** (Python 3.11+):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sh scripts/run_demo.sh
```

**Windows**: doble clic en `INICIAR-WINDOWS.bat`. Requiere Python 3.11+ (lanzador `py`); la primera vez crea `.venv` e instala `requirements.txt`.

Después abre <http://127.0.0.1:8093/manager/> e inicia sesión con la contraseña de demostración `emby-demo-003`. `HOST` y `PASEO_PORT` ajustan la dirección y el puerto de `run_demo.sh`; `scripts/run_manager.py` acepta `--host`, `--port` y `--db` (por defecto `data/emby004-demo.sqlite3`). La siembra es idempotente: reiniciar no añade publicaciones. También existe el perfil `demo` de Docker Compose ([`INSTALLATION.md`](INSTALLATION.md), sección 9).

> La contraseña de demostración es pública y solo vale para el modo demo. El panel operativo la rechaza.

## 5. Panel web

El panel «Emby Telegram Manager» se sirve en `/manager/` y tiene cinco secciones: **Biblioteca**, **Historial**, **Conciliación**, **Recuperación individual** y **Envío**.

**Panel operativo (opcional).** Está desactivado por defecto. Para activarlo define en `.env` `PANEL_ENABLED=true`, `PANEL_ADMIN_PASSWORD` (≥ 16 caracteres), `PANEL_SECRET_KEY` (≥ 32 caracteres, distinta de la contraseña) y, si quieres permitir envíos manuales desde el panel, `PANEL_ALLOW_SENDS=true`. Detalle y requisitos de HTTPS en [`INSTALLATION.md`](INSTALLATION.md) y [`SECURITY.md`](SECURITY.md). Con `PANEL_ALLOW_SENDS=false` el panel funciona en solo consulta/preparación: se puede explorar y preparar lotes, pero el servidor rechaza la confirmación.

### Nombres y alias de destinos

Al arrancar, el bot reutiliza `getChat` para guardar el nombre real de cada destino del panel. Los selectores muestran ese nombre y el ID de Telegram como referencia; internamente filtros, historial, conciliación y envíos siguen usando exclusivamente el ID. Las respuestas correctas se memorizan durante el proceso y se conservan en el mismo volumen SQLite. Si Telegram no responde, se usa el último nombre guardado y, si aún no existe, el ID.

En **Envío → Destinos** se puede guardar un alias opcional, usado solo para presentar el chat. Vaciarlo recupera el nombre de Telegram. `CHAT_LABELS` sigue siendo compatible y actúa como alias inicial la primera vez; los cambios del panel persisten tras reiniciar el contenedor. Las tablas añadidas para esta presentación no modifican las entregas ni la versión del esquema del historial.

### Biblioteca

Muestra películas y series de Emby (los 60 elementos más recientes, o los resultados de la búsqueda; este límite es solo de esta pestaña: la Conciliación recorre toda la biblioteca) en páginas de 12, con filtros por título, tipo, chat y estado. Cada carátula lleva un punto por destino con su estado (`enviado`, `fallido`, `incierto`, etc.). Marca hasta **20 títulos** y pulsa **Preparar envío**.

### Historial

Lista las entregas (10 por página) filtrables por chat y estado; cada una se puede abrir para ver todos sus intentos con fecha, resultado, error y texto enviado. Al elegir un chat, **Preparar recuperación del chat** reúne los títulos de ese chat con envíos fallidos, pendientes, inciertos o sin historial (máximo 20); lo ya enviado nunca se incluye.

### Envío

Reúne el lote (hasta 20 títulos), los **destinos** (hasta 8, cada uno con nombre legible, ID y recuento de estados actual) y una **vista previa** del texto exacto (máximo 1024 caracteres). Hay dos modos:

- **Recuperar** (por defecto): lo ya enviado se omite; lo pendiente o fallido se reintenta con el texto original; lo incierto o sin historial exige decisión.
- **Reenvío voluntario**: permite duplicar a propósito un contenido ya enviado, solo si se decide explícitamente. No está disponible en lotes de conciliación.

El plan por destino indica, para cada par, si se **envía**, se **omite** o requiere **decisión** (`Enviar igualmente` / `Omitir`, con atajos para todos los dudosos). **Revisar y confirmar** no está disponible mientras queden decisiones pendientes o algún texto supere el límite.

### Recuperación individual

Este flujo es independiente del envío masivo y limita cada operación a **una película o episodio y un único destino**. La búsqueda de esta pestaña no agrupa episodios por serie. Antes de confirmar muestra el estado actual, el último intento y su fecha, el resultado conocido y el texto exacto que se publicaría.

- Una entrega ya `enviada` se omite y no puede confirmarse de nuevo.
- Una entrega `pendiente` o `fallida` conserva el texto registrado y puede reintentarse.
- Una entrega `incierta` o sin historial exige decidir expresamente si se asume el riesgo de duplicación.
- La confirmación final se desactiva durante la petición. Si se pierde la respuesta, **no se debe repetir**: el botón **Consultar resultado** lee la operación guardada.
- El plan caduca a los 15 minutos. Tras un reinicio, una operación que estuviera en curso queda `interrumpida`, conserva su traza y nunca continúa automáticamente.

Con `PANEL_ALLOW_SENDS=false` se puede consultar y preparar la vista previa, pero la confirmación continúa bloqueada por el servidor.

## 6. Conciliación

La pestaña **Conciliación** responde a la pregunta «¿qué hay en la biblioteca de Emby que no consta como publicado?». **Es de solo lectura**: consultar no envía nada ni cambia el historial.

1. **Consulta.** Elige destinos, bibliotecas, tipos (películas y/o episodios) y el rango «Añadidos desde/hasta» (fechas en UTC). Solo aparecen bibliotecas compatibles de películas y series, seleccionadas por defecto; listas de reproducción, colecciones, vídeos musicales y vistas sin tipo reconocido quedan fuera. Cada biblioteca se consulta únicamente con su tipo compatible. El panel lee Emby por páginas y guarda una **instantánea** de la consulta; no se actualiza sola.
2. **Inicio del historial.** Fecha desde la que el historial de entregas está completo. Debe ser una **fecha conocida de registro, no una estimación** (hay una casilla de confirmación). Es independiente del rango de la consulta. Las consultas anteriores conservan la fecha con la que se calcularon.
3. **Resultado.** Cada par contenido × destino recibe un estado:

| Estado | Significado |
|---|---|
| Enviado | Hay una entrega confirmada en el historial de biblioteca. No se puede preparar desde aquí. |
| Fallido | El último intento consta como fallido. |
| Pendiente | Hay una intención registrada, aún sin intento. |
| Incierto | Hay un intento sin confirmación fiable. |
| Historial desconocido | No hay evidencia suficiente para concluir: contenido fuera del ámbito, sin fecha de alta fiable, anterior al inicio conocido del historial, sin inicio establecido o con lectura incompleta. |
| Posible omisión | Dentro del período registrado, con lectura completa y sin evidencia de publicación. **Requiere revisión manual**: es un aviso, no una conclusión. |

Cada fila tiene **Ver detalle**. La lectura se marca **incompleta** si Emby falla, cambia el total durante la consulta, repite elementos, devuelve un tipo inesperado o se alcanza el límite de la consulta; en ese caso nunca se concluye una «posible omisión». El diagnóstico de tipos inesperados incluye su nombre y cantidad. Las consultas anteriores se listan y se pueden reabrir sin volver a leer la biblioteca.

4. **Preparar recuperación.** Marca hasta **20 pares** y pulsa **Preparar recuperación**. Se abre **Envío** con un **lote exacto**: solo se enviará esa lista, sin añadir otros destinos ni títulos, y solo en modo recuperación. Si el inicio del historial cambió desde la consulta, el panel exige repetirla.

## 7. Autenticación y confirmaciones del panel

- **Sesión.** Contraseña administrativa única; la sesión caduca a los 30 minutos y la cookie es `HttpOnly`, `SameSite=Strict` y, en modo operativo, `Secure` (requiere HTTPS).
- **Intentos.** Tras 5 contraseñas incorrectas desde una misma IP, el acceso se bloquea 5 minutos.
- **CSRF y cabeceras.** Las peticiones `POST` exigen JSON y token CSRF; las respuestas llevan `Content-Security-Policy` restrictiva y `Cache-Control: no-store`.
- **Lotes.** Un plan caduca a los **15 minutos**, pertenece a la sesión que lo preparó y solo se ejecuta una vez (un lote en curso no se puede lanzar de nuevo). Se identifica con un identificador visible en pantalla.
- **Confirmación.** Para ejecutar hay que confirmar expresamente; si el lote contiene riesgo de duplicado, además hay que aceptarlo. Antes de enviar cada par, el servidor vuelve a comprobar el historial: lo que se haya enviado entretanto se omite en modo recuperación, y un estado que pasó a incierto desde la preparación obliga a preparar de nuevo.
- **Estados del lote.** `preparado`, `en curso`, `completado` o `interrumpido`, con resumen de enviados, fallidos, pendientes, inciertos y omitidos.
- **Errores.** Los mensajes del panel no incluyen datos internos; si el historial no está disponible, el panel lo indica y **no se confirma ninguna operación**. Tras un error de red, consulta el historial antes de repetir una acción.
- **Envíos desactivados.** Con `PANEL_ALLOW_SENDS=false` la confirmación devuelve «Las acciones de envío están desactivadas». Esto no afecta a las notificaciones automáticas ni a los comandos de Telegram.

## 8. Webhook de Telegram y HTTPS

Telegram necesita una URL pública con HTTPS. Pon el servicio (puerto `8081`) detrás de un proxy inverso con TLS (Nginx Proxy Manager, Caddy, Nginx…), por ejemplo `https://embybot.tudominio.org` → `http://127.0.0.1:8081` si el proxy corre en el host. El bind predeterminado es `APP_BIND=127.0.0.1`. Para un proxy en otro contenedor usa una red Docker compartida hacia `app:8081` o una IP de confianza explícita con firewall (ver `INSTALLATION.md`). Mantén la cabecera de secreto de Telegram; restringe específicamente `/embyhook`, que **no tiene autenticación propia**: HTTPS por sí solo no autoriza al emisor. Comprueba desde fuera:

```bash
curl https://embybot.tudominio.org/health     # {"status":"ok"}
```

Comprueba el token y configura el webhook (con secreto, si definiste `TELEGRAM_WEBHOOK_SECRET`):

```bash
curl "https://api.telegram.org/botTU_TOKEN/getMe"
curl -X POST "https://api.telegram.org/botTU_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://embybot.tudominio.org/telegramhook","secret_token":"EL_MISMO_SECRETO_DEL_ENV"}'
curl "https://api.telegram.org/botTU_TOKEN/getWebhookInfo"
```

Sin secreto (`TELEGRAM_WEBHOOK_SECRET=` vacío), usa `setWebhook?url=https://embybot.tudominio.org/telegramhook`. En Emby, apunta el webhook a `https://embybot.tudominio.org/embyhook`.

Si usas DuckDNS y Telegram no resuelve el host, prueba con un dominio directo (`nombre.duckdns.org`) en lugar de un sub-subdominio.

## 9. Diagnóstico y problemas frecuentes

Empieza por `/diagnostico` y por los registros: `docker compose logs -f`.

| Síntoma | Qué revisar |
|---|---|
| No llegan notificaciones de reproducción | Webhook de Emby a `/embyhook` con eventos de reproducción; `ENABLE_PLAYBACK_NOTIFICATIONS=true`; `PLAYBACK_CHAT_IDS` (si está vacío se usa `CHAT_IDS`); que el bot pueda escribir en el chat. Los registros muestran `raw_event` y `normalized_event`; un `PlaybackStart` debe aparecer como `playback.start`. |
| Altas de biblioteca duplicadas | Debe haber un solo webhook de Emby hacia el bot (no uno interno y otro por proxy). `LIBRARY_DEBOUNCE_SECONDS` actúa como protección adicional. |
| `/health` funciona en local pero no por dominio | Problema de proxy, DNS o SSL. |
| Telegram apunta a una URL antigua (ngrok) | `getWebhookInfo` y repetir `setWebhook`. |
| `401 Unauthorized` | Token de Telegram incorrecto (`getMe`). |
| `403 FORBIDDEN` o `secret token did not match` | `TELEGRAM_WEBHOOK_SECRET` distinto del `secret_token` de `setWebhook`. |
| `Failed to resolve host` | Telegram no resuelve el dominio; revisa DNS. |
| `bot can't initiate conversation with a user` | El usuario no pulsó **Iniciar** en privado con el bot. |
| `404` en `/`, `/.env`, `/graphql`… | Escaneos normales de internet. La aplicación solo usa `/health`, `/telegramhook` y `/embyhook` (y `/manager/` y `/api/` si activas el panel). |
| `/historial` responde «Solo administradores configurados en privado» | Añade tu ID privado a `ADMIN_CHAT_IDS`. |
| Cambié `ADMIN_CHAT_IDS` y no veo los comandos | Ejecuta `/reload_menu` o reinicia el contenedor. |
| El panel no arranca con `PANEL_ENABLED=true` | Contraseña (< 16) o clave de sesión (< 32) no válidas, o valores de demostración/marcador. |
