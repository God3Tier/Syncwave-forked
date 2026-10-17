# syntax=docker/dockerfile:1
#
# The Recommendation API. No database, so no migrations: it reads songs from
# the Catalogue and the weather from the Weather API on every request.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY src ./src

USER app
EXPOSE 8080
# The slim image has no wget/curl, so the check uses Python.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
CMD ["sh", "-c", "exec uvicorn recommendation_service.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
