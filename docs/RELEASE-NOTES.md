# Notas de la versión — EMBY-005 (0.5.3, propuesta)

Revisión derivada de `main` (`977fcfd`) para añadir recuperación individual segura. La versión `0.5.3` es una **propuesta**: no hay etiqueta ni release publicados, la PR no se fusiona automáticamente y no se despliega en Monster.

## Cambios 0.5.3

- Nueva pestaña **Recuperación individual**, separada de los lotes: el servidor valida exactamente un contenido y un destino.
- Catálogo específico de películas y episodios, con búsqueda y nombres/alias de destino sin sustituir nunca el ID interno.
- Estado actual, último intento, fecha, resultado y vista previa congelada antes de confirmar.
- Los estados enviados quedan bloqueados. Pendientes y fallidos pueden reintentarse; inciertos y desconocidos exigen aceptar explícitamente el riesgo de duplicación.
- El motor existente conserva la caducidad de 15 minutos, propiedad de sesión, confirmación, exclusión mutua y claves idempotentes.
- Tras reiniciar, un lote que estuviera `executing` se registra como `interrupted`, conserva sus resultados parciales y no se reanuda solo.
- Paquete, Compose e imágenes pasan a `0.5.3`; `PANEL_ALLOW_SENDS=false` permanece como valor predeterminado.

Validación local de esta revisión:

- **329 pruebas Python aprobadas** y 6 omitidas. Las omitidas son pruebas preexistentes del cliente Telegram (cuatro casos de error individual, cierre del SDK y respuesta vacía) cuyo bucle `asyncio` es interceptado por el bloqueo de sockets en Windows/Python 3.13; ninguna prueba nueva fue omitida.
- Las pruebas nuevas cubren enviado, pendiente, fallido, incierto, desconocido, asociación contenido/destino, CSRF/autenticación, envíos desactivados, caducidad, repetición, confirmación concurrente y reinicio durante una operación.
- Compilación Python, sintaxis de todos los módulos JavaScript y comprobación de espacios del diff aprobadas.
- Los tres YAML de Compose se analizaron correctamente y se verificó `PANEL_ALLOW_SENDS=false`.
- Docker no está instalado en este equipo: no se ejecutaron `docker compose config`, builds ni contenedores.
- `playwright-core` y Chromium no están disponibles: se añadió el recorrido de navegador de recuperación individual, pero no se ejecutó localmente.

Toda la suite usa dobles locales y bloqueo de red; no se publicaron mensajes reales ni se usaron credenciales reales.

## Cambios 0.5.2

- Los destinos del panel se enriquecen con su nombre real de Telegram mediante el mismo `getChat` usado por el diagnóstico.
- Los nombres correctos se cachean en memoria y en SQLite; ante un fallo se usa el último nombre conocido o el ID.
- Cada chat admite un alias opcional de presentación. `CHAT_LABELS` lo inicializa sin sobrescribir cambios ya persistidos.
- Selectores, filtros, conciliación e historial conservan el ID real como clave y muestran nombres legibles con el ID como contexto.
- `docker-compose.yml`, `Dockerfile`, `Dockerfile.demo` y el paquete pasan a `0.5.2`.
- No cambian credenciales, webhooks, puertos, destinatarios, lógica de envío, entregas SQLite ni `PANEL_ALLOW_SENDS=false`.

Validación local de la revisión:

- **316 pruebas Python aprobadas**; 6 pruebas preexistentes del cliente Telegram se excluyeron porque el bloqueo de red intercepta sockets internos de `asyncio` en Windows/Python 3.13.
- Sintaxis de todos los módulos JavaScript y compilación Python aprobadas.
- Los tres YAML de Compose se analizaron correctamente y se comprobaron las etiquetas, argumentos de build y `PANEL_ALLOW_SENDS=false`. Docker no está instalado en este equipo, por lo que no se pudo ejecutar `docker compose config` ni construir imágenes.
- Las pruebas de navegador no se ejecutaron porque este equipo no dispone de `playwright-core` ni Chromium.

## Corrección 0.5.1

- La conciliación expone únicamente bibliotecas Emby con `CollectionType=movies` o `CollectionType=tvshows`; Pelis y Series quedan seleccionadas por defecto.
- Cada biblioteca se consulta con el único tipo compatible: `Movie` para películas y `Episode` para series.
- `Playlist`, `BoxSet` y cualquier otro tipo inesperado se excluyen del resultado y dejan la consulta en estado parcial, con recuento por tipo y sin clasificar «posibles omisiones».
- Una petición sin `library_ids` usa las bibliotecas compatibles; una lista vacía o con identificadores no ofrecidos se rechaza.
- No cambian el entorno, los webhooks, el esquema SQLite ni `PANEL_ALLOW_SENDS=false`. Esta revisión no despliega nada en Monster.

Validación local de la revisión:

- **73 pruebas focalizadas aprobadas**: núcleo, API, persistencia y recuperación de conciliación.
- **307 pruebas Python aprobadas** de la suite general. Se excluyeron 6 pruebas preexistentes del cliente Telegram porque el bloqueo de red de la suite intercepta los sockets internos del bucle asíncrono en Windows con Python 3.13; ninguna pertenece a la conciliación.
- Sintaxis JavaScript del panel, compilación Python y comprobación de espacios del diff aprobadas.

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

## Cierre técnico — 2026-10-27

Revisión basada en `dec0dbfac7127ed99a4b70da6b1afd3defa5ac80`, sin cambios concurrentes en la rama al iniciar.

- Cambio mínimo: bind operativo `127.0.0.1` por defecto, sobrescribible con `APP_BIND`; actualización de plantilla y guías de webhooks/proxy. Autenticación y código de la aplicación sin cambios.
- Docker Compose **v2.39.4**, ejecutado hoy sin daemon: seis configuraciones válidas (producción predeterminada, bind vacío, IP explícita con puerto alternativo, `0.0.0.0` explícito, demo local y smoke sin red ni puertos).
- Suite completa ejecutada hoy: **310 passed en 62,21 s**. Incluye arranque de la factoría operativa con panel apagado/encendido y clientes Emby/Telegram simulados, webhooks, secreto Telegram, denegación de confirmación manual por defecto, persistencia tras recrear la aplicación y backup/restauración SQLite.
- Las pruebas bloquean conexiones salientes y DNS; las llamadas de publicación solo alcanzan dobles en memoria. No se han publicado mensajes reales ni usado credenciales reales.
- No se repitió Chromium: no hay cambios de interfaz. Los 147 checks previos siguen siendo antecedentes.
- **No ejecutado hoy:** build de imagen ni arranque/restauración dentro de Docker, por ausencia de cliente/motor/socket Docker en este runtime. El binario independiente de Compose permite validar la configuración, pero no construir ni ejecutar contenedores. Los smokes Docker anteriores son antecedentes, no una verificación nueva de este cierre.
- Antes de desplegar: reconstruir en un host aislado con Docker, verificar proxy/firewall y el acceso previsto de Emby, hacer backup y conservar imagen/Compose anteriores según `MIGRATION.md`. No se ha fusionado ni desplegado.
