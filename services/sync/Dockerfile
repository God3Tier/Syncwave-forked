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

USER app
EXPOSE 8080 50051

CMD ["sh", "-c", "uvicorn sync_service.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
