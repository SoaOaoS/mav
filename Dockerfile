# Mav — one image, three roles (engine, worker, web): see docker-compose.yml.
#   docker build -t mav .            (or: docker compose build)
#
# Built in stages so the final image carries only what runs: Node and the
# opencode engine from the official Node image (not Debian's nodejs/npm and
# their hundreds of packages), Python dependencies in a ready-made virtualenv,
# no compilers, no package caches.
ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=22

# ---------------------------------------------------------------- engine
FROM node:${NODE_VERSION}-bookworm-slim AS node
# The opencode agent engine, from npm (an exact version, or "latest").
ARG OPENCODE_VERSION=latest
RUN npm install -g --omit=dev "opencode-ai@${OPENCODE_VERSION}" \
 && npm cache clean --force \
 && rm -rf /usr/local/lib/node_modules/npm/docs /usr/local/lib/node_modules/npm/man \
           /usr/local/include /usr/local/share/doc /usr/local/share/man /root/.npm

# ---------------------------------------------------------------- python deps
FROM python:${PYTHON_VERSION}-slim-bookworm AS python
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY bot/requirements.txt /tmp/requirements.txt
# py-vapid/cryptography: push keys (web). uv: uvx, for Python MCP connections.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r /tmp/requirements.txt py-vapid cryptography uv \
 && /opt/venv/bin/pip uninstall -y pip \
 && find /opt/venv -type d \( -name tests -o -name test \) -path '*/site-packages/*' -prune -exec rm -rf {} +

# ---------------------------------------------------------------- image
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG MAV_VERSION=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    MAV_DATA=/data \
    MAV_VERSION_FILE=/app/VERSION

# tini: a proper PID 1. git/curl: tools the helpers may use. ca-certificates:
# HTTPS for the engine and the MCP connections.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git tini \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man /usr/share/info \
 && groupadd --gid 1000 mav \
 && useradd --uid 1000 --gid 1000 --home-dir /data/home --no-create-home --shell /bin/bash mav

# Node (node, npm, npx: the MCP connections that run with npx) and opencode.
COPY --from=node /usr/local/bin/ /usr/local/bin/
COPY --from=node /usr/local/lib/node_modules/ /usr/local/lib/node_modules/
COPY --from=python /opt/venv /opt/venv
RUN node --version && opencode --version

WORKDIR /app
COPY . /app
# Bytecode compiled once here, so each start does not (and cannot: /app is
# read-only for the mav user) recompile it.
RUN echo "$MAV_VERSION" >/app/VERSION \
 && chmod +x /app/docker/entrypoint.sh /app/run-opencode.sh \
 && python -m compileall -q -j 0 /app/bot /app/dashboard/server

VOLUME ["/data"]
EXPOSE 8787
ENTRYPOINT ["tini", "--", "/app/docker/entrypoint.sh"]
CMD ["web"]

LABEL org.opencontainers.image.title="Mav" \
      org.opencontainers.image.description="Your everyday AI assistant — proactive, private, on your own machine, with your own model." \
      org.opencontainers.image.source="https://github.com/SoaOaoS/mav" \
      org.opencontainers.image.licenses="MIT"
