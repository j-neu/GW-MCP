"""docs module — search_docs, search_tutorials, get_doc_file.

Searches a locally built index of MODFLOW 6, FloPy, PEST++, and pyEMU documentation.
Build the index first with:  groundwater-mcp build-index
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from groundwater_mcp.index_builder import (
    EMBEDDINGS_PATH,
    METADATA_PATH,
    PAGE_SIZE_BYTES,
    WHOOSH_DIR,
    build_index,
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

# Auto-build control — the first search_docs/search_tutorials call when no
# index exists kicks off a background build (best-effort) and returns the
# INDEX_NOT_BUILT error with build instructions.  Tests set this to False so
# a missing index returns the error without hitting the network.
_AUTOBUILD_INDEX = True
_autobuild_started = False
_autobuild_lock = threading.Lock()


def _maybe_start_autobuild() -> bool:
    """Start a background index build on first call if the index is missing.

    Returns True if the index is (now) available, False otherwise.
    """
    global _autobuild_started
    if _index_available():
        return True
    if not _AUTOBUILD_INDEX:
        return False
    with _autobuild_lock:
        if _autobuild_started:
            return False
        _autobuild_started = True
    import traceback

    def _run_build() -> None:
        try:
            build_index(verbose=False)
        except Exception:
            # best-effort: leave the error path to surface build instructions
            traceback.print_exc()

    threading.Thread(target=_run_build, daemon=True).start()
    return False


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


def _semantic_available() -> bool:
    """Whether the optional sentence-transformers extra is installed (7f-I2)."""
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Index-not-built error
# ---------------------------------------------------------------------------

_NO_INDEX_ERROR = {
    "error": True,
    "code": "INDEX_NOT_BUILT",
    "message": "The documentation index has not been built yet.",
    "suggestion": (
        "Run `groundwater-mcp build-index` to download and index the "
        "documentation (requires network on first run). A build has been "
        "started in the background; retry search_docs in a minute."
    ),
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
    if not _maybe_start_autobuild():
        return _NO_INDEX_ERROR

    expanded = expand_acronyms(query)
    effective_method = method if method != "auto" else _auto_method(expanded)

    if effective_method == "semantic" and not _semantic_available():
        if method == "semantic":
            return {
                "error": True,
                "code": "SEMANTIC_SEARCH_UNAVAILABLE",
                "message": "Semantic search requires the 'semantic' extra "
                "(sentence-transformers). Install with: pip install "
                "groundwater-mcp[semantic], or use method='text'.",
                "suggestion": "Use method='text' (full-text Whoosh search) "
                "which works without the extra.",
            }
        effective_method = "text"

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
    if not _maybe_start_autobuild():
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
    if not _maybe_start_autobuild():
        return _NO_INDEX_ERROR

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
# describe_package — machine-readable package spec (7f-I3)
# ---------------------------------------------------------------------------

# The DFN files the plan expected are not vendored in flopy 3.10, so the
# authoritative spec is derived from flopy's own package classes: a throwaway
# simulation is built to introspect the package's blocks and the
# stress_period_data record fields (which mirror the DFN).
_PACKAGE_CLASSES = {
    "DIS": "ModflowGwfdis",
    "DISV": "ModflowGwfdisv",
    "NPF": "ModflowGwfnpf",
    "IC": "ModflowGwfic",
    "STO": "ModflowGwfsto",
    "OC": "ModflowGwfoc",
    "CHD": "ModflowGwfchd",
    "WEL": "ModflowGwfwel",
    "RIV": "ModflowGwfriv",
    "DRN": "ModflowGwfdrn",
    "RCH": "ModflowGwfrch",
    "EVT": "ModflowGwfevt",
    "GHB": "ModflowGwfghb",
    "SFR": "ModflowGwfsfr",
    "CSUB": "ModflowGwfcsub",
}


_DUMMY_RECORDS = {
    "WEL": [[[0, 0, 0], -1.0]],
    "CHD": [[[0, 0, 0], 1.0, 1.0]],
    "DRN": [[[0, 0, 0], 1.0, 1.0]],
    "GHB": [[[0, 0, 0], 1.0, 1.0]],
    "RIV": [[[0, 0, 0], 1.0, 1.0, 0.0]],
    "RCH": [[[0, 0, 0], 0.001]],
    "EVT": [[[0, 0, 0], 0.001, 0.0, 0.0]],
}

# Packages that need constructor arguments to materialise their blocks. CSUB
# has no stress-period records to infer dimensions from, so a dummy interbed
# declares ``NINTERBEDS`` and lets the packagedata block be introspected.
_PACKAGE_KWARGS: dict[str, dict] = {"CSUB": {"ninterbeds": 1}}

_DUMMY_CSUB_PACKAGEDATA = [
    [0, (0, 0, 0), "nodelay", 0.0, 0.35, 1.0, 0.001, 0.001, 0.35, 0.01, 0.0]
]



def _impl_describe_package(name: str) -> dict:
    import tempfile

    import flopy.mf6 as mf6

    pkg_name = name.upper()
    if pkg_name not in _PACKAGE_CLASSES:
        raise ValueError(
            f"Unknown package '{pkg_name}'. Known packages: {sorted(_PACKAGE_CLASSES)}."
        )
    cls = getattr(mf6, _PACKAGE_CLASSES[pkg_name])

    # Build a throwaway simulation to introspect blocks and record fields.
    ws = tempfile.mkdtemp(prefix="gw-mcp-spec-")
    sim = mf6.MFSimulation(sim_name="mfsim", version="mf6", sim_ws=ws)
    gwf = mf6.ModflowGwf(sim, modelname="spec", model_nam_file="spec.nam")
    mf6.ModflowTdis(sim, pname="tdis", time_units="DAYS", nper=1, perioddata=[(1.0, 1, 1.0)])
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=2, ncol=2, delr=100.0, delc=100.0, top=10.0, botm=[0.0])

    doc_first = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else ""

    is_boundary = pkg_name in _DUMMY_RECORDS
    try:
        if is_boundary:
            pkg = cls(gwf, stress_period_data={"0": _DUMMY_RECORDS[pkg_name]})
        elif pkg_name in _PACKAGE_KWARGS:
            pkg = cls(gwf, **_PACKAGE_KWARGS[pkg_name])
        else:
            pkg = cls(gwf)
    except Exception:
        pkg = None

    blocks: list[dict] = []
    stress_fields: list[str] = []
    packagedata_fields: list[str] = []
    if pkg is not None:
        blocks = _describe_blocks(pkg)
        if is_boundary:
            try:
                stress_fields = list(pkg.stress_period_data.dtype.names)
            except Exception:
                pass
        if pkg_name == "CSUB":
            # The packagedata block's dataset list is just ``packagedata``; the
            # per-interbed record fields only materialise once data is set.
            try:
                pkg.packagedata.set_data(_DUMMY_CSUB_PACKAGEDATA)
                packagedata_fields = list(pkg.packagedata.dtype.names)
            except Exception:
                pass

    result: dict = {
        "package": pkg_name,
        "description": doc_first,
        "blocks": blocks,
    }
    if stress_fields:
        result["stress_period_data"] = stress_fields
    if packagedata_fields:
        result["packagedata"] = packagedata_fields
    return result


def _describe_blocks(pkg) -> list[dict]:
    """Block names and their dataset (keyword) names.

    ``pkg.blocks`` is a list of ``MFBlock`` objects for most packages but a
    ``{block_name: MFBlock}`` mapping for the advanced CSUB package, so both
    shapes are handled. The dataset names are what let a caller discover a
    package's options — e.g. CSUB's ``beta``/``gammaw`` (the Target 9 rerun-1
    miss), rather than only the block names.
    """
    blocks = getattr(pkg, "blocks", None) or {}
    if isinstance(blocks, dict):
        items = list(blocks.items())
    else:
        items = [(getattr(block, "name", None), block) for block in blocks]

    described: list[dict] = []
    for key, block in items:
        name = key if key is not None else getattr(block, "name", None)
        entry: dict = {"name": name, "required": getattr(block, "required", None)}
        datasets = getattr(block, "datasets", None)
        if isinstance(datasets, dict) and datasets:
            entry["fields"] = list(datasets)
        described.append(entry)
    return described


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register docs tools with the MCP server."""

    @mcp.tool()
    def describe_package(name: str) -> dict:
        """Return the authoritative package specification for a MODFLOW 6
        package (7f-I3): each block with its dataset (keyword) names and, for
        boundary packages, the ``stress_period_data`` record fields (cellid +
        value columns). Advanced packages expose their own record fields —
        CSUB returns the interbed ``packagedata`` fields."""
        try:
            return _impl_describe_package(name)
        except ValueError as exc:
            return {
                "error": True,
                "code": "INVALID_INPUT",
                "message": str(exc),
                "suggestion": f"Choose from: {sorted(_PACKAGE_CLASSES)}.",
            }
        except Exception as exc:
            return {"error": True, "code": "DESCRIBE_FAILED", "message": str(exc)}

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
