"""Graph viewer API: expose vault as nodes + edges for force-graph rendering.

Wiring notes:
- Reads from ``app.config.settings.vault_path()`` via ``app.services.vault``.
- Frontmatter dataclass exposes ``.meta`` (dict) and ``.body`` (str); we adapt
  to the inline contract here rather than introducing a parallel reader.
- Pure stdlib; no extra deps for this module.

Endpoint:
  GET /graph            -> {nodes: [...], edges: [...]}
  GET /graph (>=500)    -> {degraded: true, note, nodes: top-N, edges: filtered}
"""
from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.services.vault import list_vault, read_md

router = APIRouter(tags=["graph"])

# Match [[target]] or [[target|alias]]; ignore code fences for PoC simplicity.
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+?)\]\]")
NODE_LIMIT = 500
SUMMARY_CHARS = 200


def _rel_id(path: Path, base: Path) -> str:
    """Stable node id = path relative to vault root."""
    try:
        return str(path.relative_to(base)).replace("\\", "/")
    except ValueError:
        return path.name


def _resolve_target(raw: str) -> str:
    """Strip optional ``.md`` suffix; keep the rest verbatim."""
    raw = raw.strip()
    if raw.endswith(".md"):
        return raw[:-3]
    return raw


def _coerce_tags(value: Any) -> list[str]:
    """Best-effort coerce a frontmatter ``tags`` field to list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t) for t in value if isinstance(t, (str, int, float))]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []


def _build_graph() -> dict[str, Any]:
    """Walk the vault and produce the {nodes, edges} payload."""
    base: Path = settings.vault_path()
    paths = list_vault(base)

    nodes: dict[str, dict[str, Any]] = {}
    wikilink_edges: list[tuple[str, str]] = []
    by_tag: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        if path.is_dir() or not path.name.endswith(".md"):
            continue
        rel = _rel_id(path, base)
        fm = read_md(rel, vault_path=base)
        meta = fm.meta or {}
        body = fm.body or ""

        tags = _coerce_tags(meta.get("tags"))
        title = meta.get("title") if isinstance(meta.get("title"), str) else None
        summary = body.strip().replace("\n", " ")[:SUMMARY_CHARS]

        nodes[rel] = {
            "id": rel,
            "label": Path(rel).stem,
            "title": title,
            "tags": tags,
            "size": len(body),
            "summary": summary,
        }
        for t in tags:
            by_tag[t].append(rel)
        for m in _WIKILINK_RE.finditer(body):
            target = _resolve_target(m.group(1))
            if target:
                wikilink_edges.append((rel, target))

    # Resolve wikilink targets against the real-file id set. Wikilinks are
    # written as bare basenames (Obsidian style), e.g. ``[[tech-stack]]``,
    # while node ids are vault-relative paths (``team/tech-stack.md``).
    # So we match on: exact relative path -> path with/without .md ->
    # unique basename match. Only then do we spawn a dangling placeholder.
    real_ids = set(nodes.keys())
    by_stem: dict[str, list[str]] = defaultdict(list)
    for rid in real_ids:
        by_stem[Path(rid).stem].append(rid)

    def _resolve(target: str) -> str:
        # 1. exact relative path
        if target in real_ids:
            return target
        # 2. relative path with/without .md
        with_md = target if target.endswith(".md") else f"{target}.md"
        if with_md in real_ids:
            return with_md
        # 3. basename match (the common case for [[tech-stack]])
        stem = target[:-3] if target.endswith(".md") else target
        candidates = by_stem.get(stem, [])
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # Ambiguous: prefer the shortest path (closest to vault root),
            # then lexicographic — deterministic and usually the intended one.
            return sorted(candidates, key=lambda p: (p.count("/"), p))[0]
        return target

    for _, target in wikilink_edges:
        anchor = _resolve(target)
        if anchor in nodes:
            continue
        nodes[anchor] = {
            "id": anchor,
            "label": Path(anchor).stem,
            "title": None,
            "tags": [],
            "size": 0,
            "summary": "",
            "dangling": True,
        }

    edges: list[dict[str, Any]] = []
    for source, target in wikilink_edges:
        anchor = _resolve(target)
        edges.append(
            {"source": source, "target": anchor, "type": "wikilink", "weight": 1}
        )

    # share-tag edges (undirected). For each pair (A, B) sharing k tags,
    # record a single edge with weight = count of their shared tags.
    weight_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for _tag, ids in by_tag.items():
        unique = sorted(set(ids))
        for a, b in combinations(unique, 2):
            weight_by_pair[(a, b)] += 1
    for (a, b), w in weight_by_pair.items():
        edges.append(
            {"source": a, "target": b, "type": "share-tag", "weight": w}
        )

    node_list = list(nodes.values())
    if len(node_list) >= NODE_LIMIT:
        top = sorted(node_list, key=lambda n: -n["size"])[:NODE_LIMIT]
        kept = {n["id"] for n in top}
        kept_edges = [
            e
            for e in edges
            if e["source"] in kept and e["target"] in kept
        ]
        return {
            "degraded": True,
            "note": (
                f"vault has {len(node_list)} nodes; rendering top "
                f"{NODE_LIMIT} by size"
            ),
            "nodes": top,
            "edges": kept_edges,
        }

    return {"nodes": node_list, "edges": edges}


@router.get("/graph")
async def get_graph() -> dict[str, Any]:
    """Return the vault graph as nodes + edges (d3 / force-graph friendly)."""
    return _build_graph()
