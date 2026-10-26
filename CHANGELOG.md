# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). El estado de verificación de cada versión está en [`docs/RELEASE-NOTES.md`](docs/RELEASE-NOTES.md).

## [0.5.0] — EMBY-005 (propuesta, sin etiqueta ni publicación)

Consolida en una sola rama (`release/emby-005`) las fases EMBY-002, 003 y 004 sobre la base original e incorpora instalación Docker y guía de migración. La versión `0.5.0` es una propuesta pendiente de revisión: no hay etiqueta ni release creados.

### Añadido

- **Historial persistente de entregas (EMBY-002).** Registro SQLite de cada publicación por contenido, destino e intento, con estados `enviado`, `fallido`, `pendiente`, `incierto` e «historial desconocido» (`deliveries.py`, `publications.py`). Nueva variable `HISTORY_DB_PATH` (por defecto `data/history.sqlite3`; no admite `:memory:`).
- **Comandos de administración.** `/historial [página] [estado]`, `/historial item ID` y `/reintentar NÚMERO [confirmar-incierto]`, solo para `ADMIN_CHAT_IDS` en privado (sin recurrir a `CHAT_IDS`).
- **Panel web «Emby Telegram Manager» (EMBY-003).** Biblioteca, Historial y Envío con selección por lotes (hasta 20 títulos y 8 destinos), vista previa, plan por destino, decisiones explícitas para estados dudosos, planes con caducidad de 15 minutos y confirmación expresa. Autenticación por contraseña, sesión de 30 minutos, protección CSRF, límite de intentos y cabeceras de seguridad.
- **Modo demostración.** Aplicación con datos ficticios y conexiones salientes bloqueadas: `scripts/run_demo.sh`, `scripts/run_manager.py` e `INICIAR-WINDOWS.bat`.
- **Conciliación de biblioteca (EMBY-004).** Consulta de solo lectura que compara Emby con el historial y clasifica cada par contenido × destino (Enviado, Fallido, Pendiente, Incierto, Historial desconocido, Posible omisión); fecha de inicio conocido del historial; lectura paginada con detección de resultados incompletos; consultas anteriores reabribles; preparación de **lotes exactos** de recuperación.
- **Panel operativo opcional.** `PANEL_ENABLED`, `PANEL_ADMIN_PASSWORD`, `PANEL_SECRET_KEY` y `PANEL_ALLOW_SENDS` (`runtime.py`). Desactivado por defecto; exige contraseña de al menos 16 caracteres, clave de sesión de al menos 32 y distinta, sin valores de demostración o marcador; cookie `Secure`.
- **Documentación.** `docs/USAGE.md`, `docs/RELEASE-NOTES.md`, `docs/INSTALLATION.md`, `docs/MIGRATION.md`, `docs/SECURITY.md`, capturas reales de la demostración y `docs/GEMINI-STATUS.md`.
- **Pruebas.** Suite Python aislada de la red y de disco compartido (`tests/conftest.py`) y pruebas de navegador del panel y de la conciliación (`tests/panel-browser.cjs`, `tests/reconciliation-browser.cjs`).

### Cambiado

- Las notificaciones automáticas de biblioteca y los envíos manuales pasan por el mismo servicio de publicación y quedan registrados en el historial.
- `README.md` reorganizado: la instalación y la migración pasan a `docs/INSTALLATION.md` y `docs/MIGRATION.md`; el webhook de Telegram con HTTPS y el diagnóstico pasan a `docs/USAGE.md`.
- Docker Compose con servicios `app` (perfil `production`) y `demo` (perfil `demo`), sin nombres fijos de contenedor ni volumen; la imagen incluye los ficheros estáticos del panel (`package_data`).
- Scripts `scripts/backup.sh` (en caliente) y `scripts/restore.sh` (con el servicio parado) para el historial SQLite.
- Cambios en `config.py`, `emby_client.py`, `episode_aggregator.py`, `telegram_client.py` y `webhook.py` para integrar el historial, los comandos y el panel.

### Notas

- La delegación opcional a Gemini está **bloqueada** por limitaciones del entorno y no forma parte de esta versión (`docs/GEMINI-STATUS.md`).
- No se ha validado esta versión contra un Emby y un Telegram reales ni se ha desplegado en producción.

## [0.1.0] — Base original (v2)

Funcionalidades previas a las fases 002–004, tal como estaban en `main`:

- Notificaciones de películas y episodios nuevos con fichas ricas (carátula, sinopsis desplegable, valoraciones, enlace a IMDb, calidad y formato deducidos de la metadata de Emby).
- Agrupación de episodios por temporada con buffer temporal y control de concurrencia.
- Eventos de reproducción configurables (compacto/detallado, pausa opcional, carátula opcional) con anti-duplicado.
- Destinos separados para biblioteca y reproducción, `CHAT_LABELS` y anti-duplicado de biblioteca.
- Búsqueda en Telegram (`/buscar`) con filtros, menú de comandos por rol y botones privados.
- Reenvío manual para administradores (`/reenviar`, `/reenviaultimo`, `/reenvia`) y diagnóstico (`/diagnostico`, `/version`, `/reload_menu`).
- Secretos en `.env`, escape seguro de MarkdownV2, validación opcional del webhook de Telegram, despliegue con Docker y gunicorn, licencia MIT.
