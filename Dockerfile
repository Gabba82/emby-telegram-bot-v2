# syntax=docker/dockerfile:1
# EMBY-005 — runtime image for the Emby -> Telegram webhook service + optional panel.
#
# Postura de seguridad:
#   * corre como usuario no privilegiado (UID/GID 10001) creado en build
#   * los secretos llegan por entorno en tiempo de ejecucion, nunca en la imagen
#   * no se copia ningun .env: solo codigo y assets estaticos
#   * healthcheck en el puerto de la app, independiente de Telegram/Emby
#   * el panel esta OFF salvo PANEL_ENABLED=true en tiempo de ejecucion

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_VERSION=0.5.0 \
    APP_UID=10001 \
    APP_GID=10001 \
    HISTORY_DB_PATH=/data/history.sqlite3

# curl solo se usa para el HEALTHCHECK; no se expone al servicio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$APP_GID" app \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencias primero para que los cambios de codigo no invaliden la capa.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && python -c "import emby_telegram_bot, pathlib; \
p = pathlib.Path(emby_telegram_bot.__file__).parent / 'panel_static'; \
assert (p / 'index.html').is_file(), 'panel_static/index.html missing from wheel'; \
assert (p / 'css' / 'panel.css').is_file(), 'panel_static css missing'; \
assert (p / 'js' / 'api.js').is_file(), 'panel_static js missing'"

# El ledger SQLite vive aqui; el volumen se monta encima.
RUN mkdir -p /data \
    && chown -R "$APP_UID":"$APP_GID" /data /app

USER "$APP_UID"
EXPOSE 8081

# El panel no existe salvo que PANEL_ENABLED=true. La app de demo NUNCA arranca
# desde esta imagen (scripts/run_manager.py es la entrada de demo).
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "120", \
     "--bind", "0.0.0.0:8081", "--log-level", "info", "--access-logfile", "-", \
     "--error-logfile", "-", "emby_telegram_bot.wsgi:app"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:8081/health" || exit 1
