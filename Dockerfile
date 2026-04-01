FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
COPY src ./src
COPY bot.py .

RUN pip install --no-cache-dir .

EXPOSE 8081

CMD ["gunicorn", "--workers", "2", "--threads", "4", "--bind", "0.0.0.0:8081", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-", "emby_telegram_bot.wsgi:app"]
