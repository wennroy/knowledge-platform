# syntax=docker/dockerfile:1.7
# Knowledge Platform backend image.
#
# Multi-stage build:
#   frontend — builds the Vite SPA (node), writes to backend/app/static/app
#   builder  — installs the Python dependencies into an isolated prefix
#   final    — copies the prefix + the app source and runs uvicorn
#
# The frontend is built *inside* the image, so `docker compose up` yields a
# complete application without building the SPA on the host first.

# ---------- frontend ----------
FROM node:22-slim AS frontend

WORKDIR /build/frontend

# The lockfile is copied on its own so the dependency layer stays cached.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# `vite.config.ts` writes the bundle to `../backend/app/static/app`, i.e.
# /build/backend/app/static/app — the path the final stage copies from.
RUN npm run build

# ---------- builder ----------
FROM python:3.12-slim AS builder

# Tools needed at build/runtime:
# - git  : used by the vault git bundle helpers at runtime
# - curl : used by the container healthcheck
# `Acquire::Retries` absorbs the transient 502s the Debian mirror throws
# under load — without it the build fails on a random package.
RUN apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /Users/b/

# The full backend source — the app package, the tests and the (small)
# static assets. The SPA bundle is *not* copied from here; the frontend
# stage produces it.
COPY backend/ ./backend/

# Install the dependencies into an isolated prefix so the final stage can
# copy them without carrying the build toolchain along.
RUN pip install --no-cache-dir --prefix=/install ./backend

# ---------- final ----------
FROM python:3.12-slim AS final

RUN apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /Users/b/

# The installed Python packages (fastapi, lancedb, docling, ...).
COPY --from=builder /install /usr/local

# The application source.
COPY --from=builder /Users/b/backend /Users/b/backend

# Drop the SPA that happens to be committed under backend/app/static/app —
# the copy below is the authoritative build.
RUN rm -rf /Users/b/backend/app/static/app

# The freshly built SPA — served by FastAPI under /app/.
COPY --from=frontend /build/backend/app/static/app /Users/b/backend/app/static/app

WORKDIR /Users/b/backend

EXPOSE 8000

# Note: env vars (GATEWAY_*, EMBEDDING_MODEL, LANCEDB_PATH, VAULT_PATH, ...)
# are injected by docker-compose via env_file = ../backend/.env.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
