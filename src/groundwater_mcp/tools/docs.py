"""docs module — search_docs, search_tutorials, get_doc_file.

Searches a locally built index of MODFLOW 6, FloPy, PEST++, and pyEMU documentation.
Build the index first with:  groundwater-mcp build-index
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from groundwater_mcp.index_builder import (
    EMBEDDINGS_PATH,
    METADATA_PATH,
    PAGE_SIZE_BYTES,
    WHOOSH_DIR,
    expand_acronyms,
    extract_text,
)

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_whoosh_index = None
_embeddings = None  # numpy array, shape (n_docs, dim)
_metadata: list[dict] | None = None
_st_model = None  # SentenceTransformer


def _get_whoosh_index():
    global _whoosh_index
    if _whoosh_index is None:
        if not WHOOSH_DIR.exists():
            return None
        try:
            from whoosh import index as whoosh_index_mod

            _whoosh_index = whoosh_index_mod.open_dir(str(WHOOSH_DIR))
        except Exception:
            return None
    return _whoosh_index


def _get_embeddings_and_metadata():
    global _embeddings, _metadata
    if _embeddings is None:
        if not EMBEDDINGS_PATH.exists() or not METADATA_PATH.exists():
            return None, None
        import numpy as np

        _embeddings = np.load(str(EMBEDDINGS_PATH))
        _metadata = json.loads(METADATA_PATH.read_text())
    return _embeddings, _metadata


def _get_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer

        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model


# ---------------------------------------------------------------------------
# Index-not-built error
# ---------------------------------------------------------------------------

_NO_INDEX_ERROR = {
    "error": True,
    "code": "INDEX_NOT_BUILT",
    "message": "The documentation index has not been built yet.",
    "suggestion": "Run `groundwater-mcp build-index` to download and index the documentation.",
}


def _index_available() -> bool:
    return _get_whoosh_index() is not None or _get_embeddings_and_metadata()[0] is not None


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------


def _text_search(
    query: str,
    repos: list[str] | None,
    is_tutorial: bool | None,
    complexity: str | None,
    limit: int,
) -> list[dict]:
    """Full-text search via Whoosh."""
    ix = _get_whoosh_index()
    if ix is None:
        return []

    from whoosh import query as wq
    from whoosh.qparser import MultifieldParser

    with ix.searcher() as searcher:
        parser = MultifieldParser(
            ["title", "content"],
            schema=ix.schema,
            fieldboosts={"title": 2.0},
        )
        try:
            q = parser.parse(query)
        except Exception:
            q = wq.Every()

        filters: list[wq.Query] = []
        if repos:
            filters.append(wq.Or([wq.Term("repo", r) for r in repos]))
        if is_tutorial is not None:
            filters.append(wq.Term("is_tutorial", is_tutorial))
        if complexity:
            filters.append(wq.Term("complexity", complexity))

        if filters:
            q = wq.And([q, *filters])

        results = searcher.search(q, limit=limit)
        return [
            {
                "path": r["path"],
                "repo": r["repo"],
                "title": r["title"],
                "snippet": r.get("snippet", ""),
                "is_tutorial": r.get("is_tutorial", False),
                "complexity": r.get("complexity") or None,
                "score": r.score,
                "method": "text",
            }
            for r in results
        ]


def _semantic_search(
    query: str,
    repos: list[str] | None,
    is_tutorial: bool | None,
    complexity: str | None,
    limit: int,
) -> list[dict]:
    """Semantic search via sentence-transformers embeddings."""
    embeddings, metadata = _get_embeddings_and_metadata()
    if embeddings is None or not metadata:
        return []

    model = _get_model()
    q_vec = model.encode(query, normalize_embeddings=True)
    scores = embeddings @ q_vec  # cosine similarity (embeddings are L2-normalised)

    results = []
    for idx in range(len(metadata)):
        m = metadata[idx]
        if repos and m["repo"] not in repos:
            continue
        if is_tutorial is not None and m["is_tutorial"] != is_tutorial:
            continue
        if complexity and m.get("complexity") != complexity:
            continue
        results.append((float(scores[idx]), m))

    results.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "path": m["path"],
            "repo": m["repo"],
            "title": m["title"],
            "snippet": m.get("snippet", ""),
            "is_tutorial": m.get("is_tutorial", False),
            "complexity": m.get("complexity"),
            "score": score,
            "method": "semantic",
        }
        for score, m in results[:limit]
    ]


def _hybrid_search(
    query: str,
    repos: list[str] | None,
    is_tutorial: bool | None,
    complexity: str | None,
    limit: int,
) -> list[dict]:
    """Merge text and semantic results, deduplicate by path, average normalised scores."""
    text_hits = _text_search(query, repos, is_tutorial, complexity, limit)
    sem_hits = _semantic_search(query, repos, is_tutorial, complexity, limit)

    max_text = max((h["score"] for h in text_hits), default=1.0) or 1.0
    by_path: dict[str, dict] = {}

    for h in text_hits:
        h = dict(h)
        h["score"] = h["score"] / max_text
        by_path[h["path"]] = h

    for h in sem_hits:
        if h["path"] in by_path:
            by_path[h["path"]]["score"] = (by_path[h["path"]]["score"] + h["score"]) / 2
            by_path[h["path"]]["method"] = "hybrid"
        else:
            by_path[h["path"]] = dict(h)

    merged = sorted(by_path.values(), key=lambda x: x["score"], reverse=True)
    return merged[:limit]


def _auto_method(query: str) -> str:
    """Choose search method based on query characteristics."""
    return "text" if len(query.split()) <= 3 else "semantic"


# ---------------------------------------------------------------------------
# Tool implementations (_impl_* — importable for testing)
# ---------------------------------------------------------------------------


def _impl_search_docs(
    query: str,
    repos: list[str] | None = None,
    method: str = "auto",
    limit: int = 10,
) -> dict:
    if not _index_available():
        return _NO_INDEX_ERROR

    expanded = expand_acronyms(query)
    effective_method = method if method != "auto" else _auto_method(expanded)

    if effective_method == "text":
        hits = _text_search(expanded, repos, None, None, limit)
    elif effective_method == "semantic":
        hits = _semantic_search(expanded, repos, None, None, limit)
    else:
        hits = _hybrid_search(expanded, repos, None, None, limit)

    return {
        "query": query,
        "expanded_query": expanded if expanded != query else None,
        "method": effective_method,
        "results": hits,
        "count": len(hits),
    }


def _impl_search_tutorials(
    query: str,
    complexity: str | None = None,
    limit: int = 5,
) -> dict:
    if not _index_available():
        return _NO_INDEX_ERROR

    if complexity and complexity not in ("beginner", "intermediate", "advanced"):
        return {
            "error": True,
            "code": "INVALID_COMPLEXITY",
            "message": f"Invalid complexity '{complexity}'.",
            "suggestion": "Use 'beginner', 'intermediate', or 'advanced'.",
        }

    expanded = expand_acronyms(query)
    hits = _semantic_search(expanded, None, True, complexity, limit)
    if not hits:
        hits = _text_search(expanded, None, True, complexity, limit)

    return {
        "query": query,
        "complexity_filter": complexity,
        "results": hits,
        "count": len(hits),
    }


def _impl_get_doc_file(path: str, page: int = 1) -> dict:
    _, metadata = _get_embeddings_and_metadata()
    if metadata is None:
        return _NO_INDEX_ERROR

    doc = next((m for m in metadata if m["path"] == path), None)
    if doc is None:
        return {
            "error": True,
            "code": "DOC_NOT_FOUND",
            "message": f"No document found with path '{path}'.",
            "suggestion": "Use search_docs to find valid document paths.",
        }

    local_path = Path(doc.get("source_local", ""))
    if not local_path.exists():
        return {
            "error": True,
            "code": "SOURCE_FILE_MISSING",
            "message": f"Cached source file not found at '{local_path}'.",
            "suggestion": "Re-run `groundwater-mcp build-index` to refresh the cache.",
        }

    suffix = local_path.suffix.lower()
    raw = local_path.read_bytes()
    text = extract_text(raw, suffix)
    text_bytes = text.encode("utf-8")

    total_pages = max(1, -(-len(text_bytes) // PAGE_SIZE_BYTES))  # ceiling division

    if page < 1 or page > total_pages:
        return {
            "error": True,
            "code": "PAGE_OUT_OF_RANGE",
            "message": f"Page {page} is out of range. Document has {total_pages} page(s).",
            "suggestion": f"Request a page between 1 and {total_pages}.",
        }

    start = (page - 1) * PAGE_SIZE_BYTES
    end = start + PAGE_SIZE_BYTES
    chunk = text_bytes[start:end].decode("utf-8", errors="replace")

    return {
        "path": path,
        "title": doc["title"],
        "repo": doc["repo"],
        "page": page,
        "total_pages": total_pages,
        "content": chunk,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register docs tools with the MCP server."""

    @mcp.tool()
    def search_docs(
        query: str,
        repos: list[str] | None = None,
        method: str = "auto",
        limit: int = 10,
    ) -> dict:
        """Search MODFLOW 6, FloPy, PEST++, and pyEMU documentation.

        Args:
            query: Search query. MODFLOW package acronyms (WEL, RIV, CHD, etc.)
                   are automatically expanded.
            repos: Filter to specific repos. Options: "modflow6", "flopy",
                   "pestpp", "pyemu". Default: search all.
            method: Search method — "text" (BM25 full-text), "semantic"
                    (sentence-transformers), or "auto" (choose based on query).
            limit: Maximum number of results to return.
        """
        return _impl_search_docs(query, repos, method, limit)

    @mcp.tool()
    def search_tutorials(
        query: str,
        complexity: str | None = None,
        limit: int = 5,
    ) -> dict:
        """Search tutorial notebooks and example scripts.

        Args:
            query: Search query describing what you want to learn.
            complexity: Filter by complexity level — "beginner", "intermediate",
                        or "advanced". Default: all levels.
            limit: Maximum number of results to return.
        """
        return _impl_search_tutorials(query, complexity, limit)

    @mcp.tool()
    def get_doc_file(path: str, page: int = 1) -> dict:
        """Retrieve a documentation file by its index path (paginated at 30 KB).

        Args:
            path: The document path as returned by search_docs or search_tutorials
                  (e.g. "flopy/docs/introduction.md").
            page: Page number (1-indexed). Each page is up to 30 KB of plain text.
        """
        return _impl_get_doc_file(path, page)
