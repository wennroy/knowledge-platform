# Open WebUI Integration

The Knowledge Platform backend exposes an OpenAI-compatible
`POST /v1/chat/completions` endpoint with vault-grounded retrieval. This doc
shows how to point [Open WebUI](https://github.com/open-webui/open-webui) at
the backend so the chat UI in your browser can answer questions from your
local vault.

The flow is:

```
Browser  →  Open WebUI (port 3000)  →  backend (port 8000)  →  gateway /embeddings + /chat/completions
                       ↑
            OpenAI-compatible /v1/chat/completions only
```

The backend ignores the model name sent by Open WebUI; it always uses the
model configured via the `CHAT_MODEL` environment variable. The retrieval
augmentation and references event are produced entirely by the backend.

---

## 1. Run the backend

From `backend/`:

```bash
cp -n .env.example .env       # only if you don't already have a .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl -s http://localhost:8000/healthz   # → {"ok": true}
```

If the vault is empty, ask anything in Open WebUI and you will get a response
that begins with "I could not find relevant material in the vault…".

---

## 2. Run Open WebUI in Docker

The official image is published as
[`ghcr.io/open-webui/open-webui:main`](https://github.com/open-webui/open-webui).
Two environment variables are enough to make it talk to the backend:

```bash
docker run -d \
  --name open-webui \
  --restart unless-stopped \
  -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OPENAI_API_KEY=any-non-empty-value \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

Notes on the values:

- `3000:8080` — the container listens on `8080`; we expose it on the host at
  `3000` so it doesn't collide with the backend on `8000`.
- `OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1` — Docker Desktop
  on macOS/Windows rewrites `host.docker.internal` to the host's loopback.
  On Linux, add `--add-host=host.docker.internal:host-gateway` to the
  `docker run` command, or replace `host.docker.internal` with the host IP
  reachable from the container.
- `OPENAI_API_KEY=any` — the backend does **not** validate the API key, so
  any non-empty placeholder works. (Real key enforcement is the gateway's
  job.) Open WebUI requires the variable to be present and non-empty.

### Linux / older Docker engines

```bash
docker run -d \
  --name open-webui \
  --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OPENAI_API_KEY=any \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

---

## 3. Open the UI

Visit <http://localhost:3000> in your browser. The first visit walks you
through creating the local admin account.

In the model picker, Open WebUI lists the model name from the most recent
response — because the backend proxies the gateway unchanged, the label that
shows up is whatever `CHAT_MODEL` is set to on the backend. The backend
ignores the model name sent by the UI, so picking any entry routes the
request back to the same endpoint.

---

## 4. Verify the round-trip

1. Drop a file into the vault, e.g. `vault/notes/personal/quickstart.md` with
   a short paragraph of content.
2. Wait a few seconds (the backend's watchdog indexes new `.md` files within
   ~500 ms).
3. In Open WebUI, ask a question whose answer is in that file.

You should see:

- The assistant response cites the vault file (the backend injects the
  reference block under your message).
- The Open WebUI message footer shows a "References" section with the
  source file, heading path, and a relevance score.

If references don't appear, the most likely cause is an unsupported Open
WebUI version that doesn't recognise our `{"type": "references", ...}` event.
The backend still returns the references inline in the assistant message in
that case.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| "Network error" in the Open WebUI chat input | Backend not reachable from the container | Check `OPENAI_API_BASE_URL` and `--add-host=host.docker.internal:host-gateway` on Linux |
| 401 from Open WebUI when sending | `OPENAI_API_KEY` empty | Set it to any non-empty placeholder string |
| Responses contain "I could not find relevant material…" | Vault is empty or chunk hasn't been indexed yet | Drop a `.md` file into `vault/`, wait ~1 s, retry |
| Reference sidebar empty | Old Open WebUI build | Upgrade `ghcr.io/open-webui/open-webui:main` to the latest tag |