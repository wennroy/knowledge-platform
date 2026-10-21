# Knowledge Platform — Runbook

Operational guide for deploying, verifying, upgrading, backing up, restoring,
and troubleshooting the Knowledge Platform stack.

The stack has two long-running services:

| Service    | Image / build                  | Loopback port |
|------------|--------------------------------|---------------|
| `backend`  | built from `deploy/backend.Dockerfile` | `127.0.0.1:8000` |
| `open-webui` | `ghcr.io/open-webui/open-webui:main` | `127.0.0.1:3000` |

Data volumes:

- `lancedb` — named volume, holds the vector index (rebuilt on startup if missing)
- `open-webui` — named volume, holds chat history / users
- `../vault` — bind-mounted read-write, the git-tracked notes source of truth

---

## 1. Deploy

First-time (or after editing `backend.Dockerfile` / Python sources):

```bash
cd /Users/wennroy/proj/knowledge-platform/deploy
docker compose up -d --build
```

Subsequent starts (image is already built):

```bash
cd /Users/wennroy/proj/knowledge-platform/deploy
docker compose up -d
```

The backend reads its config (gateway URL, model names, paths, etc.) from
`backend/.env`. To change anything, edit that file and restart:

```bash
docker compose restart backend
```

The gateway endpoint is the only LLM/embedding-facing address — the backend
treats it as an OpenAI-compatible service. `OPENAI_API_BASE_URL` inside the
`open-webui` container points at `http://backend:8000/v1`.

---

## 2. Verify

After `docker compose up -d`:

```bash
# 1. backend health
curl -sf http://127.0.0.1:8000/healthz   # -> {"ok": true}

# 2. metrics endpoint (Prometheus text format)
curl -sf http://127.0.0.1:8000/metrics | head

# 3. Open WebUI
# Open http://127.0.0.1:3000 in a browser.
# Log in, then pick any model from the dropdown — chat completions
# are routed via the OpenAI-compat layer to the backend.
```

If the chat UI shows "no models available", check the backend logs and the
`GATEWAY_BASE_URL` env var — see §6.

---

## 3. Upgrade

Pulls new images and restarts the stack in place:

```bash
cd /Users/wennroy/proj/knowledge-platform/deploy
docker compose pull            # pull new open-webui image
docker compose up -d --build   # rebuild backend if sources changed,
                               # otherwise plain `up -d` is enough
```

Vault data on the host (`/Users/wennroy/proj/knowledge-platform/vault`) and
the named volumes are preserved across upgrades — they are never deleted by
`compose up`.

---

## 4. Backup

```bash
bash /Users/wennroy/proj/knowledge-platform/deploy/scripts/backup.sh /tmp/kb-backup
```

The script writes to `/tmp/kb-backup/` by default; pass any writable
directory. Outputs:

- `vault-<timestamp>.bundle` — git bundle of the vault repo (`--all` refs)
- `lancedb-<timestamp>.tgz` — raw `lancedb/` data directory

The bundle is small and self-contained. The lancedb tarball is optional —
see §5. Schedule via cron / launchd if you want periodic snapshots.

---

## 5. Restore

Restoration rebuilds the vault and lets the backend re-derive the LanceDB
index on its next start.

```bash
# 1. Stop the stack and wipe the persistent lancedb volume so the
#    backend rebuilds it from scratch on next start.
cd /Users/wennroy/proj/knowledge-platform/deploy
docker compose down
docker volume rm deploy_lancedb      # or `docker volume rm <project>_lancedb`

# 2. Restore vault from a bundle (script refuses to overwrite a non-empty vault).
bash /Users/wennroy/proj/knowledge-platform/deploy/scripts/restore.sh \
    /tmp/kb-backup/vault-20260119-143022.bundle

# 3. Bring the stack back up; backend's startup reconcile will rebuild
#    the LanceDB vector index from the restored vault.
docker compose up -d
```

LanceDB is intentionally **not** restored from the lancedb tgz — the
bundle/restart path produces a self-consistent index, eliminates the
possibility of restoring a stale on-disk index whose file references
disagree with vault contents, and is the only path that needs to be
documented end-to-end. If you ever need to restore from a lancedb tgz
instead, stop the stack and untar into the named volume.

---

## 6. AI gateway switch

The backend has no hard-coded provider — it speaks OpenAI-compatible HTTP
to whatever `GATEWAY_BASE_URL` points at. To switch providers:

```bash
# 1. edit backend/.env
#    GATEWAY_BASE_URL=https://your-other-gateway/v1
#    GATEWAY_API_KEY=...
#    EMBEDDING_MODEL=...
#    EMBEDDING_DIM=...
#
# 2. restart the backend only (open-webui follows via depends_on)
cd /Users/wennroy/proj/knowledge-platform/deploy
docker compose restart backend
```

Confirm the new gateway is reachable:

```bash
curl -sf $GATEWAY_BASE_URL/models -H "Authorization: Bearer $GATEWAY_API_KEY"
```

If the backend can't reach the gateway, chat completions will surface as
gateway errors in `/var/log/...` and you'll see
`kb_chat_completions_total{outcome="error"}` increment on
`http://127.0.0.1:8000/metrics`.

---

## 7. Troubleshooting

### Vault permission errors (`fatal: Unable to create '.git/...'`)
The vault on the host must be writable by the UID that runs inside the
container. On Linux, fix ownership:

```bash
sudo chown -R $USER:$USER /Users/wennroy/proj/knowledge-platform/vault
```

(`/data/vault` inside the container is bind-mounted read-write from the
host vault; if the host directory is read-only to the in-container UID,
the post-commit hooks that the indexer installs will fail.)

### `401` / `403` from the gateway
- Confirm `GATEWAY_BASE_URL` is reachable from the **container** network
  (use `docker compose exec backend curl -sf $GATEWAY_BASE_URL/models`).
- Check that `GATEWAY_API_KEY` matches what the gateway expects.
- Open WebUI's "any" key is fine because the backend authenticates upstream,
  not the chat UI.

### Port conflicts (`:3000` or `:8000` already in use)
- See what owns the port: `lsof -iTCP:3000 -sTCP:LISTEN`.
- Either stop the conflicting process or change the published port in
  `deploy/docker-compose.yml` (left side of the `ports:` mapping). Remember
  to update the Caddyfile / your browser accordingly.

### Backend keeps restarting
- `docker compose logs --tail=200 backend` to see the traceback.
- Common cause: stale bind-mount. Try
  `docker compose down && docker compose up -d`.

### Open WebUI shows "no models"
- The OpenAI-compat route only works if the backend is `service_healthy`.
  `docker compose ps` should show `backend` as `healthy`. If it's
  `unhealthy`, see the backend logs.

### `kb_lancedb_rows` gauge stays at 0
- Normal only on a fresh startup; reconcile runs on boot. If it stays 0
  after a few minutes, your vault may be empty (no notes) — drop a file
  in `/Users/wennroy/proj/knowledge-platform/vault/` and watch logs.
