# Notas de la versión — EMBY-005 (0.5.0, propuesta)

Rama `release/emby-005`, derivada de `main` y consolidada con el código y las pruebas finales de EMBY-004. La versión `0.5.0` es una **propuesta**: no hay etiqueta ni release publicados, y la rama no se ha desplegado en producción.

## Resumen

EMBY-005 reúne en un único paquete lo construido en tres fases sobre el bot original:

| Fase | Contenido |
|---|---|
| EMBY-002 | Historial persistente de entregas en SQLite y comandos `/historial` y `/reintentar`. |
| EMBY-003 | Panel web (Biblioteca, Historial, Envío) con modo demostración. |
| EMBY-004 | Conciliación de solo lectura y recuperación por lotes exactos. |
| EMBY-005 | Integración en una rama, instalación Docker, migración y documentación. |

Funcionalidades, comandos y reglas: [`USAGE.md`](USAGE.md). Cambios: [`../CHANGELOG.md`](../CHANGELOG.md).

## Estado de verificación

Validaciones previas de las fases 003 y 004, **reutilizadas y no repetidas** sobre la rama EMBY-005:

- **Pruebas Python:** 295 aprobadas.
- **Pruebas de navegador (Chromium):** 147 aprobadas.
- **Windows:** arranque de la demostración (`INICIAR-WINDOWS.bat`) de las fases 003 y 004 aprobado por Gabba.

Ejecutado específicamente en EMBY-005:

- **13 pruebas focalizadas aprobadas:** 10 del runtime opcional y 3 del flujo SQLite de backup/restauración.
- **Smoke real de Docker aprobado:** imagen demo construida, UID/GID 10001, red `none`, sin puertos ni credenciales; panel/health accesibles internamente. Cinco entregas persisten tras reiniciar; backup validado y restauración sintética de 2 a 5 entregas. La restauración con el servicio activo se rechaza. La demo local publica únicamente en loopback. Los contenedores y volúmenes de prueba se eliminaron.

No se ha repetido la regresión completa (Python y Chromium) sobre la rama EMBY-005, y no se han tomado capturas nuevas: las de la documentación proceden de la demostración de las fases anteriores.

Alcance — qué **no** significan estos resultados:

- **No** es una validación operativa: no se ha probado contra un servidor Emby ni un bot de Telegram reales.
- **No** se ha desplegado en producción.
- Las pruebas se ejecutan sin red (los envíos y las lecturas de Emby son simulados) y las capturas muestran la demostración con datos ficticios.

## Qué cambia para quien actualiza

- Se crea y usa una base SQLite (`HISTORY_DB_PATH`) que **debe conservarse** en un volumen persistente; sin ella se pierde el historial. Ver [`INSTALLATION.md`](INSTALLATION.md) y [`MIGRATION.md`](MIGRATION.md).
- El panel web es **opcional y está desactivado** (`PANEL_ENABLED=false`). Activarlo exige credenciales robustas y HTTPS; los envíos desde el panel requieren además `PANEL_ALLOW_SENDS=true`. Esa variable no desactiva los webhooks ni los comandos del bot original.
- `/historial` y `/reintentar` solo funcionan para IDs listados en `ADMIN_CHAT_IDS`, en privado.
- Las notificaciones automáticas siguen funcionando como antes, pero ahora quedan registradas en el historial.

## Limitaciones conocidas

- La conciliación solo cubre películas y episodios y evalúa únicamente el historial de **biblioteca** (publicaciones automáticas, manuales y del panel); no considera eventos de reproducción.
- «Posible omisión» es un aviso para revisión manual, nunca una conclusión: solo aparece con lectura completa de Emby y dentro del período con historial conocido.
- La pestaña **Biblioteca** del panel muestra solo las 60 entradas más recientes (o los resultados de la búsqueda) de películas y series; la **Conciliación** recorre toda la biblioteca de Emby en páginas.
- El estado «incierto» siempre exige decisión humana; el sistema no puede saber si Telegram llegó a entregar el mensaje.
- **Gemini (opcional):** la delegación a Gemini está bloqueada porque no se pudo verificar un entorno aislado para él. No forma parte de esta versión ([`GEMINI-STATUS.md`](GEMINI-STATUS.md)).

## Documentación de la versión

[`../README.md`](../README.md) · [`USAGE.md`](USAGE.md) · [`INSTALLATION.md`](INSTALLATION.md) · [`MIGRATION.md`](MIGRATION.md) · [`SECURITY.md`](SECURITY.md) · [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
