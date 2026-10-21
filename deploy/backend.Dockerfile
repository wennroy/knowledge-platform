# syntax=docker/dockerfile:1.7
# Knowledge Platform backend image.
# Multi-stage build: builder installs deps into an isolated prefix,
# final stage copies the prefix + the app source and runs uvicorn.

# ---------- builder ----------
FROM python:3.12-slim AS builder

# Tools needed at build/runtime:
# - git  : used by the vault git bundle helpers at runtime
# - curl : used by the container healthcheck
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /Users/b/

# Install Python deps first for better layer caching.
COPY backend/pyproject.toml backend/README.md ./backend/
# setuptools needs at least an empty package to install -e .
RUN mkdir -p backend/app && touch backend/app/__init__.py

WORKDIR /Users/b/backend
RUN pip install --no-cache-dir -e .

# ---------- final ----------
FROM python:3.12-slim AS final

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /Users/b/

# Bring in the full backend source + installed package from the builder.
COPY --from=builder /Users/b/backend /Users/b/backend

WORKDIR /Users/b/backend

EXPOSE 8000

# Note: env vars (GATEWAY_*, EMBEDDING_MODEL, LANCEDB_PATH, VAULT_PATH, ...)
# are injected by docker-compose via env_file = ../backend/.env.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
