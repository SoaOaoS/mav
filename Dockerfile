# Mav — one image, three roles (engine, worker, web): see docker-compose.yml.
#   docker build -t mav .            (or: docker compose build)
FROM python:3.12-slim-bookworm

ARG MAV_VERSION=dev
# The opencode agent engine, from npm (an exact version, or "latest").
ARG OPENCODE_VERSION=latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MAV_DATA=/data \
    MAV_VERSION_FILE=/app/VERSION

# nodejs/npm: the opencode engine and the MCP connections that run with npx.
# tini: a proper PID 1. git/curl: tools the helpers may use.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git nodejs npm tini \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g "opencode-ai@${OPENCODE_VERSION}" \
 && npm cache clean --force \
 && opencode --version

COPY bot/requirements.txt /tmp/requirements.txt
# py-vapid/cryptography: push keys (web). uv: uvx, for Python MCP connections.
RUN pip install -r /tmp/requirements.txt py-vapid cryptography uv \
 && rm /tmp/requirements.txt

RUN groupadd --gid 1000 mav && useradd --uid 1000 --gid 1000 --home-dir /data/home --no-create-home --shell /bin/bash mav

WORKDIR /app
COPY . /app
RUN echo "$MAV_VERSION" >/app/VERSION \
 && chmod +x /app/docker/entrypoint.sh /app/run-opencode.sh

VOLUME ["/data"]
EXPOSE 8787
ENTRYPOINT ["tini", "--", "/app/docker/entrypoint.sh"]
CMD ["web"]

LABEL org.opencontainers.image.title="Mav" \
      org.opencontainers.image.description="Your everyday AI assistant — proactive, private, on your own machine, with your own model." \
      org.opencontainers.image.source="https://github.com/SoaOaoS/mav" \
      org.opencontainers.image.licenses="MIT"
