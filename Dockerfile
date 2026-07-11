# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config.example.yaml ./
COPY config/locales ./config/locales
COPY ha ./ha

# Default image: core + Deepgram optional extra (local-stt is heavy; install separately if needed)
RUN pip install --no-cache-dir -e ".[deepgram]"

RUN mkdir -p /app/data/clips /app/data/db /app/config/locales

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Mount your real config.yaml + .env (or env vars) at runtime.
CMD ["radio-feed-watch", "-c", "config.yaml"]
