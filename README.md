# Knowledge Platform

自部署的轻量级 AI 知识管理平台 —— 用 Git 仓库里的纯 Markdown 做知识底座，接入任意 OpenAI 兼容网关，提供的核心是**带引用的聊天问答**和**知识关系图谱**。

面向 <20 人的企业团队：两类内容统一沉淀（团队上传的 PDF/DOCX/PPT + 个人 Markdown 笔记），**完全开源、无 SaaS 依赖、数据不出企业**。

---

## 特性

| 能力 | 说明 |
|---|---|
| **聊天问答 + 引用** | OpenAI 兼容 `/v1/chat/completions`，SSE 流式；每条回答带 vault 文件路径与章节引用 |
| **多格式入库** | MarkItDown 默认解析 Office/PDF；扫描件自动 fallback 到 Docling（含 OCR） |
| **三层增量同步** | watchdog 文件监听 + Git `post-commit` hook + 启动全量对账 |
| **知识图谱** | 自写 react-force-graph SPA：节点 = Markdown 文件，边 = `[[wikilink]]` + 共享 tags |
| **Git 即真理源** | 知识资产 = Git 仓库里的 `.md` 文件，可版本控制、可备份、可移植 |
| **嵌入式向量库** | LanceDB 单文件持久化，零额外服务进程 |
| **可观测** | Prometheus 指标（`kb_*`）+ JSON 结构化日志 + `/healthz` |
| **备份/恢复** | `git bundle` 备份 vault；LanceDB 可随时从 vault 重建 |

## 技术栈

全部 Apache-2.0 / MIT，无付费依赖：

| 层 | 选型 | 许可证 |
|---|---|---|
| 文档解析 | [MarkItDown](https://github.com/microsoft/markitdown) + [Docling](https://github.com/docling-project/docling) | MIT / MIT |
| 向量库 | [LanceDB](https://github.com/lancedb/lancedb) | Apache-2.0 |
| 后端 | [FastAPI](https://github.com/fastapi/fastapi) + httpx + pydantic | MIT |
| 聊天 UI | [Open WebUI](https://github.com/open-webui/open-webui) | MIT |
| 图谱 UI | React + [react-force-graph](https://github.com/grison/react-force-graph) | MIT |
| LLM / Embedding | 任意 OpenAI 兼容网关 | —— |

## 架构

```
浏览器
 ├── Open WebUI  ──►  POST /v1/chat/completions  (SSE + references)
 └── 图谱 SPA     ──►  GET  /graph                (nodes + edges)
                        │
                        ▼
             FastAPI 后端（单进程）
               ├─ /v1/files      上传 / 列表 / 删除
               ├─ /admin/index/* 索引状态 / 全量扫描 / 重建
               ├─ /metrics       Prometheus
               └─ /static/graph/ 图谱 SPA 静态资源
                 │
                 ├─ Indexer   MarkItDown/Docling → chunk → embed → LanceDB
                 ├─ Retriever embed(query) → topK → prompt → 网关
                 └─ Sync      watchdog + post-commit hook + 启动对账
                        │                              │
                        ▼                              ▼
                  vault/ (Git)              内部 AI gateway
                  team/*.md                 /v1/embeddings
                  notes/personal/*.md       /v1/chat/completions
```

## 快速开始

### 1. 配置

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env：
#   GATEWAY_BASE_URL=https://your-internal-gateway/v1
#   GATEWAY_API_KEY=sk-...
#   EMBEDDING_MODEL=...
#   EMBEDDING_DIM=1536   # 必须与 embedding 模型的向量维度一致
```

### 2. 本地开发

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

uvicorn app.main:app --reload --port 8000

# 图谱前端（另开一个终端）
cd graph-viewer && npm install && npm run dev
```

### 3. Docker 部署

```bash
cd deploy
docker compose up -d
```

- Open WebUI → http://localhost:3000（首次注册管理员账号）
- 后端 API → http://localhost:8000
- 图谱 viewer → http://localhost:8000/static/graph/

> 首次启动 Open WebUI 建议关闭其内置 RAG（`ENABLE_RAG=false`），因为检索已由本项目的后端负责。
> 详见 [`docs/OPENWEBUI.md`](docs/OPENWEBUI.md)。

### 4. Git hook（可选，让 teammate 的 commit 立即可搜）

```bash
bash deploy/scripts/install-git-hooks.sh
```

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/chat/completions` | OpenAI 兼容聊天（SSE 流式 + 引用） |
| POST | `/v1/files` | 上传文档（multipart） |
| GET | `/v1/files` | 列出 vault 内所有 Markdown |
| DELETE | `/v1/files/{path}` | 删除文档 |
| GET | `/graph` | 知识图谱 `{nodes, edges}` |
| GET | `/admin/index/status` | 每个文件的索引状态 |
| POST | `/admin/index/scan` | 触发全量对账 |
| POST | `/admin/index/reindex` | 重建单个文件索引 |
| GET | `/metrics` | Prometheus 指标 |
| GET | `/healthz` | 健康检查 |

## 知识组织约定

```markdown
---
tags: [api, backend]
---
# API 设计

遵循 [[tech-stack]] 的规范，鉴权见 [[auth-design]]。
```

- `tags`（frontmatter）→ 图谱中的**共享标签边**（灰色）
- `[[wikilink]]` → 图谱中的**有向边**（蓝色）
- frontmatter 会自动注入：`source_filename` / `source_hash` / `ingested_at` / `parser` / `ocr_used` / `uploader`

## 开发

```bash
cd backend
pytest -q          # 88 tests（52 单测 + 36 E2E）
ruff check app/
```

## 文档

- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — 部署、升级、备份、恢复、故障排查
- [`docs/OPENWEBUI.md`](docs/OPENWEBUI.md) — Open WebUI 接入与模型配置

## 许可证

[MIT](LICENSE)

> ⚠️ 自部署到企业网络前，请收紧 `backend/app/main.py` 的 CORS（当前为 `allow_origins=["*"]`）并在 `deploy/Caddyfile` 配置 `basicauth` 或 IP 白名单。
