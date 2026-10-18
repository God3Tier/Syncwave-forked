# syntax=docker/dockerfile:1
#
# One image, two processes (compose.yaml, and two ECS services in production):
#   lyrics          the HTTP API; the default command applies the database
#                   migrations first, then serves on port 8080
#   lyrics-worker   python -m lyrics_service.worker (AMQP consumer, no port)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY src ./src

USER app
EXPOSE 8080
# The slim image has no wget/curl, so the check uses Python.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn lyrics_service.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
