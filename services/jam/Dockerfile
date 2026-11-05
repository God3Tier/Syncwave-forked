# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app
COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt
COPY src ./src
COPY alembic.ini .
COPY migrations ./migrations
USER app
EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && uvicorn jam_service.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
