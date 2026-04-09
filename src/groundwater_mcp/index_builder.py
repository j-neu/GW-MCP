"""Build the local documentation search index for groundwater-mcp.

Downloads documentation from public GitHub repositories and builds:
  1. A Whoosh full-text search index
  2. A sentence-transformers semantic embedding index (numpy array + JSON metadata)

Both indexes are saved to ~/.groundwater-mcp/index/

Usage (via CLI):
    groundwater-mcp build-index

Usage (programmatic):
    from groundwater_mcp.index_builder import build_index
    build_index()
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

INDEX_DIR = Path.home() / ".groundwater-mcp" / "index"
WHOOSH_DIR = INDEX_DIR / "whoosh"
SOURCES_DIR = INDEX_DIR / "sources"
EMBEDDINGS_PATH = INDEX_DIR / "embeddings.npy"
METADATA_PATH = INDEX_DIR / "metadata.json"

PAGE_SIZE_BYTES = 30 * 1024  # 30 KB per page for get_doc_file

# ---------------------------------------------------------------------------
# Repos to index
# ---------------------------------------------------------------------------

REPOS: dict[str, dict] = {
    "modflow6": {
        "owner": "MODFLOW-USGS",
        "repo": "modflow6",
        "branch": "develop",
        "extensions": {".md", ".rst"},
        "path_prefixes": ("README", "CONTRIBUTING", "doc/"),
        "max_files": 60,
        "max_file_bytes": 200_000,
    },
    "flopy": {
        "owner": "modflowpy",
        "repo": "flopy",
        "branch": "main",
        "extensions": {".md", ".rst", ".ipynb"},
        "path_prefixes": ("README", "docs/", "examples/", "autotest/"),
        "max_files": 80,
        "max_file_bytes": 300_000,
    },
    "pestpp": {
        "owner": "usgs",
        "repo": "pestpp",
        "branch": "master",
        "extensions": {".md", ".rst"},
        "path_prefixes": ("README", "documentation/", "docs/"),
        "max_files": 40,
        "max_file_bytes": 200_000,
    },
    "pyemu": {
        "owner": "pypest",
        "repo": "pyemu",
        "branch": "master",
        "extensions": {".md", ".rst", ".ipynb"},
        "path_prefixes": ("README", "docs/", "examples/", "tutorials/"),
        "max_files": 60,
        "max_file_bytes": 300_000,
    },
}

# ---------------------------------------------------------------------------
# MODFLOW acronym expansion
# ---------------------------------------------------------------------------

ACRONYMS: dict[str, str] = {
    "WEL": "well package",
    "RIV": "river package",
    "CHD": "constant head boundary",
    "DRN": "drain package",
    "GHB": "general head boundary",
    "RCH": "recharge package",
    "EVT": "evapotranspiration package",
    "SFR": "streamflow routing package",
    "MAW": "multi-aquifer well",
    "LAK": "lake package",
    "UZF": "unsaturated zone flow",
    "MVR": "mover package",
    "OBS": "observation package",
    "DIS": "structured discretization",
    "DISV": "vertex discretization",
    "DISU": "unstructured discretization",
    "NPF": "node property flow",
    "IC": "initial conditions",
    "OC": "output control",
    "IMS": "iterative model solution",
    "TDIS": "time discretization",
    "GWF": "groundwater flow model",
    "GWT": "groundwater transport model",
    "PEST": "parameter estimation",
    "IES": "iterative ensemble smoother",
    "GLM": "Gauss-Levenberg-Marquardt",
}


def expand_acronyms(query: str) -> str:
    """Expand known MODFLOW package acronyms in a query string."""
    words = query.split()
    expanded = []
    for word in words:
        clean = word.upper().strip(".,;:")
        if clean in ACRONYMS:
            expanded.append(f"{word} {ACRONYMS[clean]}")
        else:
            expanded.append(word)
    return " ".join(expanded)


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"


def _api_get(url: str, token: str | None = None) -> dict | list:
    """Fetch a GitHub API endpoint and return parsed JSON."""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError(
                "GitHub API rate limit hit. Set GITHUB_TOKEN env variable to increase limits."
            ) from e
        raise


def _fetch_raw(owner: str, repo: str, branch: str, path: str, token: str | None = None) -> bytes:
    """Fetch raw file content from GitHub."""
    url = f"{_GITHUB_RAW}/{owner}/{repo}/{branch}/{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _get_repo_tree(
    owner: str, repo: str, branch: str, token: str | None = None
) -> list[dict]:
    """Return the full recursive file tree for a repo."""
    url = f"{_GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    data = _api_get(url, token)
    return [item for item in data.get("tree", []) if item["type"] == "blob"]


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

_MD_CODE_BLOCK = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_MD_INLINE_CODE = re.compile(r"`[^`]+`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD_ITALIC = re.compile(r"[*_]{1,3}([^*_]+)[*_]{1,3}")
_RST_DIRECTIVE = re.compile(r"^\.\. [\w-]+::.*$", re.MULTILINE)
_RST_ROLE = re.compile(r":[a-z]+:`[^`]+`")


def _strip_markdown(text: str) -> str:
    text = _MD_CODE_BLOCK.sub(" ", text)
    text = _MD_INLINE_CODE.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_BOLD_ITALIC.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_rst(text: str) -> str:
    text = _RST_DIRECTIVE.sub("", text)
    text = _RST_ROLE.sub(lambda m: m.group(0).split("`")[1], text)
    # Remove underline/overline headings
    text = re.sub(r"^[=\-~^]+$", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _strip_notebook(content: bytes) -> str:
    """Extract text from a Jupyter notebook (markdown + code cells)."""
    try:
        nb = json.loads(content)
    except json.JSONDecodeError:
        return ""
    parts: list[str] = []
    for cell in nb.get("cells", []):
        source = "".join(cell.get("source", []))
        if cell.get("cell_type") == "markdown":
            parts.append(_strip_markdown(source))
        elif cell.get("cell_type") == "code":
            parts.append(source)
    return " ".join(parts)


def extract_text(content: bytes, suffix: str) -> str:
    """Convert raw file bytes to searchable plain text."""
    if suffix == ".ipynb":
        return _strip_notebook(content)
    raw = content.decode("utf-8", errors="replace")
    if suffix == ".md":
        return _strip_markdown(raw)
    if suffix == ".rst":
        return _strip_rst(raw)
    return raw


def extract_title(content: bytes, path: str, suffix: str) -> str:
    """Extract a human-readable title from the file content."""
    filename = Path(path).stem.replace("_", " ").replace("-", " ").title()
    if suffix == ".ipynb":
        try:
            nb = json.loads(content)
            for cell in nb.get("cells", []):
                if cell.get("cell_type") == "markdown":
                    src = "".join(cell.get("source", []))
                    m = re.match(r"^#\s+(.+)", src.strip())
                    if m:
                        return m.group(1).strip()
        except json.JSONDecodeError:
            pass
        return filename
    raw = content.decode("utf-8", errors="replace")
    if suffix in (".md",):
        m = re.search(r"^#\s+(.+)", raw, re.MULTILINE)
        if m:
            return m.group(1).strip()
    if suffix == ".rst":
        lines = raw.splitlines()
        for i, line in enumerate(lines):
            if i + 1 < len(lines) and re.match(r"^[=\-~^]+$", lines[i + 1]):
                return line.strip()
    return filename


def detect_is_tutorial(path: str) -> bool:
    """Return True if the document is a tutorial or example."""
    lower = path.lower()
    return any(seg in lower for seg in ("example", "tutorial", "notebook", "autotest", ".ipynb"))


_ADVANCED_KEYWORDS = {"calibrat", "uncertain", "pest", "ensemble", "sensitiv", "mcmc", "invers"}
_BEGINNER_KEYWORDS = {"getting_start", "getting-start", "beginner", "basic", "intro", "quickstart"}


def detect_complexity(path: str, text: str) -> str | None:
    """Classify tutorial complexity as beginner, intermediate, or advanced."""
    if not detect_is_tutorial(path):
        return None
    lower = path.lower() + " " + text[:500].lower()
    if any(k in lower for k in _BEGINNER_KEYWORDS):
        return "beginner"
    if any(k in lower for k in _ADVANCED_KEYWORDS):
        return "advanced"
    return "intermediate"


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def _should_include(tree_item: dict, cfg: dict) -> bool:
    path: str = tree_item["path"]
    size: int = tree_item.get("size", 0)
    suffix = Path(path).suffix.lower()
    if suffix not in cfg["extensions"]:
        return False
    if size > cfg["max_file_bytes"]:
        return False
    lower = path.lower()
    return any(lower.startswith(p.lower()) or lower == p.lower() for p in cfg["path_prefixes"])


def build_index(token: str | None = None, verbose: bool = True) -> None:
    """Download docs and build the full-text + semantic search index."""
    import os

    import numpy as np
    from sentence_transformers import SentenceTransformer
    from whoosh import index as whoosh_index
    from whoosh.fields import BOOLEAN, ID, STORED, TEXT, Schema

    token = token or os.environ.get("GITHUB_TOKEN")

    # Prepare directories
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    WHOOSH_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)

    # Whoosh schema
    schema = Schema(
        path=ID(stored=True, unique=True),
        repo=ID(stored=True),
        title=TEXT(stored=True),
        content=TEXT(stored=False),
        snippet=STORED(),
        is_tutorial=BOOLEAN(stored=True),
        complexity=ID(stored=True),
    )
    ix = whoosh_index.create_in(str(WHOOSH_DIR), schema)
    writer = ix.writer()

    # Sentence-transformers model for embeddings
    if verbose:
        print("Loading sentence-transformers model (all-MiniLM-L6-v2)…")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    all_embeddings: list = []
    all_metadata: list[dict] = []

    for repo_key, cfg in REPOS.items():
        owner = cfg["owner"]
        repo = cfg["repo"]
        branch = cfg["branch"]

        if verbose:
            print(f"\nFetching tree for {owner}/{repo} ({branch})…")

        try:
            tree = _get_repo_tree(owner, repo, branch, token)
        except Exception as exc:
            print(f"  WARNING: could not fetch tree for {repo}: {exc}")
            continue

        # Filter to relevant files
        candidates = [item for item in tree if _should_include(item, cfg)]
        candidates = candidates[: cfg["max_files"]]

        if verbose:
            print(f"  Indexing {len(candidates)} files…")

        source_dir = SOURCES_DIR / repo_key
        source_dir.mkdir(parents=True, exist_ok=True)

        for item in candidates:
            file_path: str = item["path"]
            suffix = Path(file_path).suffix.lower()
            doc_id = f"{repo_key}/{file_path}"
            local_path = source_dir / file_path.replace("/", "_")

            # Use cached copy if available
            if local_path.exists():
                raw = local_path.read_bytes()
            else:
                try:
                    time.sleep(0.05)  # gentle rate limiting
                    raw = _fetch_raw(owner, repo, branch, file_path, token)
                    local_path.write_bytes(raw)
                except Exception as exc:
                    if verbose:
                        print(f"    SKIP {file_path}: {exc}")
                    continue

            text = extract_text(raw, suffix)
            title = extract_title(raw, file_path, suffix)
            is_tutorial = detect_is_tutorial(file_path)
            complexity = detect_complexity(file_path, text)
            snippet = text[:300]

            writer.update_document(
                path=doc_id,
                repo=repo_key,
                title=title,
                content=text,
                snippet=snippet,
                is_tutorial=is_tutorial,
                complexity=complexity or "",
            )

            # Embed title + first 1000 chars of text
            embed_text = f"{title}: {text[:1000]}"
            embedding = model.encode(embed_text, normalize_embeddings=True)
            all_embeddings.append(embedding)
            all_metadata.append(
                {
                    "path": doc_id,
                    "repo": repo_key,
                    "title": title,
                    "is_tutorial": is_tutorial,
                    "complexity": complexity,
                    "snippet": snippet,
                    "source_local": str(local_path),
                }
            )

    writer.commit()

    # Save embeddings
    if all_embeddings:
        embeddings_arr = np.stack(all_embeddings).astype("float32")
        np.save(str(EMBEDDINGS_PATH), embeddings_arr)
        METADATA_PATH.write_text(json.dumps(all_metadata, indent=2))
        if verbose:
            print(f"\nDone. Indexed {len(all_metadata)} documents.")
            print(f"Index saved to: {INDEX_DIR}")
    else:
        if verbose:
            print("\nWARNING: No documents were indexed.")


def main() -> None:
    """CLI entry point for `groundwater-mcp build-index`."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Build the groundwater-mcp documentation index.")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub personal access token (optional, increases rate limits). "
        "Also reads GITHUB_TOKEN environment variable.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    args = parser.parse_args()

    build_index(token=args.token, verbose=not args.quiet)
