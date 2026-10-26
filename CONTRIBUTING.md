# Contribuir

Gracias por ayudar a mejorar este proyecto.

## Entorno local

1. Haz un fork y clona el repositorio.
2. Crea tu rama desde `main`.
3. Instala las dependencias (Python 3.11+):
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
4. Ejecuta las pruebas:
```bash
.venv/bin/python -m pytest -q -p no:cacheprovider
```

Las pruebas Python se ejecutan sin red: `tests/conftest.py` bloquea las conexiones externas y usa un directorio y una base SQLite nuevos en cada prueba. Una prueba que intente salir a internet falla.

## Probar el panel

Para trabajar en el panel no necesitas Emby ni Telegram: arranca la demostración con datos ficticios (`sh scripts/run_demo.sh`, o `INICIAR-WINDOWS.bat` en Windows) y abre <http://127.0.0.1:8093/manager/>. Ver [`docs/USAGE.md`](docs/USAGE.md).

Las pruebas de navegador (`tests/panel-browser.cjs` y `tests/reconciliation-browser.cjs`) requieren Node.js, `playwright-core` y un Chromium, y se ejecutan contra una demostración en marcha; las variables de entorno (`PANEL_URL`, `PANEL_PASSWORD`, `PLAYWRIGHT_CORE`, `CHROMIUM_PATH`) están descritas en la cabecera de cada fichero. Con `--shots` guardan capturas en `screenshots/` (no las subas al repositorio; elige solo las que documenten algo y colócalas en `docs/screenshots/`).

## Pull requests

- Mantén los PR pequeños y centrados.
- Explica qué cambia y por qué.
- Incluye pruebas cuando cambie el comportamiento.
- No subas secretos ni `.env`.
- No incluyas capturas, bases de datos (`*.sqlite3`) ni datos reales de tu Emby o de tus chats.
- Si cambias variables de entorno, actualiza `.env.example`, el README y `docs/INSTALLATION.md`.
- Anota los cambios visibles para el usuario en `CHANGELOG.md`.

## Principios del proyecto

- Un envío a Telegram nunca debe ocurrir sin una acción explícita (webhook de Emby o confirmación de un administrador).
- Un resultado dudoso se muestra como dudoso (`incierto`, «historial desconocido», «posible omisión»); no se resuelve solo.
- El panel debe seguir funcionando en modo demostración sin credenciales ni red.

## Estilo de código

- Python 3.11+.
- Módulos simples y legibles.
- Registra de forma explícita los errores de webhooks e integraciones, sin escribir secretos en los registros.
- Textos de usuario en español.
