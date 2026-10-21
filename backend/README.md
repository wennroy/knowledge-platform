# knowledge-platform-backend

FastAPI 后端：文档解析 → 切片 → 向量化 → 检索 → 带引用的聊天问答。

完整文档见仓库根目录的 [README](../README.md)。

## 快速上手

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 填写 GATEWAY_BASE_URL / GATEWAY_API_KEY / EMBEDDING_MODEL
uvicorn app.main:app --reload --port 8000
```

## 测试

```bash
pytest -q          # 88 tests
ruff check app/ tests/
```

## 目录

```
app/
  main.py              FastAPI 装配、lifespan、路由注册
  config.py            Pydantic Settings（读 .env）
  metrics.py           Prometheus 指标定义
  models.py            数据模型
  routes/
    chat.py            POST /v1/chat/completions（OpenAI 兼容 + SSE + 引用）
    files.py           POST/GET/DELETE /v1/files
    graph.py           GET /graph（nodes + edges）
    admin_index.py     /admin/index/{status,scan,reindex}
  services/
    parser_router.py   MarkItDown 默认 + Docling 扫描件 fallback
    chunker.py         markdown-it + tiktoken 切片（512/64）
    embedder.py        httpx → 网关 /embeddings（批处理 + 退避重试）
    indexer.py         LanceDB 读写与状态表
    retriever.py       检索 + context 组装
    vault.py           vault 读写、frontmatter、staging
    sync.py            watchdog + 启动对账
    prompts.py         系统提示词模板
```
