"""Tests for tools/docs.py — documentation search and retrieval.

Uses a minimal 10-document index built in-process (no GitHub download needed).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import groundwater_mcp.tools.docs as docs_module
from groundwater_mcp.index_builder import (
    ACRONYMS,
    detect_complexity,
    detect_is_tutorial,
    expand_acronyms,
    extract_text,
    extract_title,
)


# ---------------------------------------------------------------------------
# Minimal index fixture
# ---------------------------------------------------------------------------

_FAKE_DOCS = [
    {
        "path": "modflow6/README.md",
        "repo": "modflow6",
        "title": "MODFLOW 6 Overview",
        "text": "MODFLOW 6 is the latest release of MODFLOW a groundwater flow model.",
        "is_tutorial": False,
        "complexity": None,
    },
    {
        "path": "flopy/docs/introduction.md",
        "repo": "flopy",
        "title": "Introduction to FloPy",
        "text": "FloPy is a Python package for creating running and post-processing MODFLOW models.",
        "is_tutorial": False,
        "complexity": None,
    },
    {
        "path": "flopy/examples/basic_model.ipynb",
        "repo": "flopy",
        "title": "Basic Model Tutorial",
        "text": "This tutorial shows how to build a simple groundwater flow model using FloPy.",
        "is_tutorial": True,
        "complexity": "beginner",
    },
    {
        "path": "flopy/examples/calibration_pest.ipynb",
        "repo": "flopy",
        "title": "Calibration with PEST++",
        "text": "Advanced calibration of groundwater models using PEST++ ensemble smoother.",
        "is_tutorial": True,
        "complexity": "advanced",
    },
    {
        "path": "pestpp/documentation/pestpp_ies.md",
        "repo": "pestpp",
        "title": "PESTPP-IES Documentation",
        "text": "PESTPP-IES implements iterative ensemble smoother for parameter estimation.",
        "is_tutorial": False,
        "complexity": None,
    },
    {
        "path": "pyemu/docs/getting_started.md",
        "repo": "pyemu",
        "title": "Getting Started with pyEMU",
        "text": "pyEMU provides Python tools for working with PEST and PEST++ control files.",
        "is_tutorial": False,
        "complexity": None,
    },
    {
        "path": "pyemu/examples/linear_uncertainty.ipynb",
        "repo": "pyemu",
        "title": "Linear Uncertainty Analysis",
        "text": "Demonstrates linear uncertainty analysis for groundwater model predictions.",
        "is_tutorial": True,
        "complexity": "intermediate",
    },
    {
        "path": "flopy/docs/dis_package.md",
        "repo": "flopy",
        "title": "Structured Discretization (DIS)",
        "text": "The DIS package defines the structured grid for MODFLOW 6 models.",
        "is_tutorial": False,
        "complexity": None,
    },
    {
        "path": "modflow6/doc/wel_package.md",
        "repo": "modflow6",
        "title": "Well Package (WEL)",
        "text": "The well package adds pumping or injection to specified model cells.",
        "is_tutorial": False,
        "complexity": None,
    },
    {
        "path": "flopy/examples/intermediate_transient.ipynb",
        "repo": "flopy",
        "title": "Transient Simulation Tutorial",
        "text": "Step-by-step guide to building a transient groundwater model.",
        "is_tutorial": True,
        "complexity": "intermediate",
    },
]


@pytest.fixture()
def minimal_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal 10-document index in tmp_path for testing."""
    from whoosh import index as whoosh_index_mod
    from whoosh.fields import BOOLEAN, ID, STORED, TEXT, Schema

    index_dir = tmp_path / "index"
    whoosh_dir = index_dir / "whoosh"
    sources_dir = index_dir / "sources"
    whoosh_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)

    embeddings_path = index_dir / "embeddings.npy"
    metadata_path = index_dir / "metadata.json"

    # Patch module-level paths in docs and index_builder
    monkeypatch.setattr(docs_module, "WHOOSH_DIR", whoosh_dir)
    monkeypatch.setattr(docs_module, "EMBEDDINGS_PATH", embeddings_path)
    monkeypatch.setattr(docs_module, "METADATA_PATH", metadata_path)

    # Reset lazy singletons so they reload from the patched paths
    monkeypatch.setattr(docs_module, "_whoosh_index", None)
    monkeypatch.setattr(docs_module, "_embeddings", None)
    monkeypatch.setattr(docs_module, "_metadata", None)

    schema = Schema(
        path=ID(stored=True, unique=True),
        repo=ID(stored=True),
        title=TEXT(stored=True),
        content=TEXT(stored=False),
        snippet=STORED(),
        is_tutorial=BOOLEAN(stored=True),
        complexity=ID(stored=True),
    )
    ix = whoosh_index_mod.create_in(str(whoosh_dir), schema)
    writer = ix.writer()

    rng = np.random.default_rng(42)
    embeddings = []
    metadata = []

    for doc in _FAKE_DOCS:
        # Write source file to sources_dir
        local_name = doc["path"].replace("/", "_")
        repo = doc["path"].split("/")[0]
        repo_dir = sources_dir / repo
        repo_dir.mkdir(exist_ok=True)
        local_path = repo_dir / local_name
        local_path.write_text(doc["text"], encoding="utf-8")

        writer.update_document(
            path=doc["path"],
            repo=doc["repo"],
            title=doc["title"],
            content=doc["text"],
            snippet=doc["text"][:300],
            is_tutorial=doc["is_tutorial"],
            complexity=doc["complexity"] or "",
        )

        # Random unit-vector embedding
        vec = rng.standard_normal(384).astype("float32")
        vec /= np.linalg.norm(vec)
        embeddings.append(vec)

        metadata.append(
            {
                "path": doc["path"],
                "repo": doc["repo"],
                "title": doc["title"],
                "is_tutorial": doc["is_tutorial"],
                "complexity": doc["complexity"],
                "snippet": doc["text"][:300],
                "source_local": str(local_path),
            }
        )

    writer.commit()

    np.save(str(embeddings_path), np.stack(embeddings))
    metadata_path.write_text(json.dumps(metadata, indent=2))

    return index_dir


# ---------------------------------------------------------------------------
# expand_acronyms
# ---------------------------------------------------------------------------


def test_expand_acronyms_known():
    result = expand_acronyms("WEL package setup")
    assert "well package" in result.lower()


def test_expand_acronyms_unknown():
    result = expand_acronyms("run my model")
    assert result == "run my model"


def test_expand_acronyms_case_insensitive():
    # Only exact uppercase matches; mixed case words should expand
    result = expand_acronyms("WEL RIV CHD")
    for acronym in ("WEL", "RIV", "CHD"):
        assert ACRONYMS[acronym] in result


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


def test_extract_text_markdown():
    md = b"# Heading\n\nSome **bold** text and a [link](http://example.com)."
    text = extract_text(md, ".md")
    assert "Heading" in text
    assert "bold" in text
    assert "link" in text
    assert "http://example.com" not in text
    assert "**" not in text


def test_extract_text_notebook():
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n", "Some description."]},
            {"cell_type": "code", "source": ["import flopy"]},
        ]
    }
    raw = json.dumps(nb).encode()
    text = extract_text(raw, ".ipynb")
    assert "Title" in text
    assert "description" in text
    assert "import flopy" in text


def test_extract_text_invalid_notebook():
    text = extract_text(b"not json", ".ipynb")
    assert text == ""


# ---------------------------------------------------------------------------
# extract_title
# ---------------------------------------------------------------------------


def test_extract_title_markdown_heading():
    md = b"# My Model Title\n\nSome text."
    title = extract_title(md, "docs/my_model.md", ".md")
    assert title == "My Model Title"


def test_extract_title_fallback_filename():
    md = b"No heading here."
    title = extract_title(md, "some_doc_file.md", ".md")
    assert "Some Doc File" in title


# ---------------------------------------------------------------------------
# detect_is_tutorial
# ---------------------------------------------------------------------------


def test_detect_is_tutorial_notebook():
    assert detect_is_tutorial("examples/basic_model.ipynb") is True


def test_detect_is_tutorial_docs():
    assert detect_is_tutorial("docs/introduction.md") is False


def test_detect_is_tutorial_example_path():
    assert detect_is_tutorial("examples/head_observation.py") is True


# ---------------------------------------------------------------------------
# detect_complexity
# ---------------------------------------------------------------------------


def test_detect_complexity_not_tutorial():
    result = detect_complexity("docs/introduction.md", "some content")
    assert result is None


def test_detect_complexity_beginner():
    result = detect_complexity("tutorials/getting_started.ipynb", "beginner content")
    assert result == "beginner"


def test_detect_complexity_advanced():
    result = detect_complexity("examples/calibration_pest.ipynb", "calibration uncertainty")
    assert result == "advanced"


def test_detect_complexity_intermediate():
    result = detect_complexity("examples/transient_model.ipynb", "build a transient model")
    assert result == "intermediate"


# ---------------------------------------------------------------------------
# search_docs (text)
# ---------------------------------------------------------------------------


def test_search_docs_text_returns_results(minimal_index):
    from groundwater_mcp.tools.docs import _text_search

    hits = _text_search("groundwater flow model", None, None, None, 5)
    assert isinstance(hits, list)
    assert len(hits) > 0
    for h in hits:
        assert "path" in h
        assert "title" in h
        assert "score" in h


def test_search_docs_text_repo_filter(minimal_index):
    from groundwater_mcp.tools.docs import _text_search

    hits = _text_search("model", ["modflow6"], None, None, 10)
    assert all(h["repo"] == "modflow6" for h in hits)


def test_search_docs_text_no_results(minimal_index):
    from groundwater_mcp.tools.docs import _text_search

    hits = _text_search("xyzzy_nonexistent_term_12345", None, None, None, 5)
    assert hits == []


# ---------------------------------------------------------------------------
# search_docs (semantic)
# ---------------------------------------------------------------------------


def test_search_docs_semantic_returns_results(minimal_index, monkeypatch):
    from groundwater_mcp.tools.docs import _semantic_search

    # Patch the model to return a fixed random embedding (avoid loading torch in CI)
    rng = np.random.default_rng(0)
    fake_vec = rng.standard_normal(384).astype("float32")
    fake_vec /= np.linalg.norm(fake_vec)

    monkeypatch.setattr(
        docs_module, "_get_model", lambda: type("M", (), {"encode": lambda self, q, **kw: fake_vec})()
    )

    hits = _semantic_search("how to build a model", None, None, None, 5)
    assert isinstance(hits, list)
    assert len(hits) == 5
    for h in hits:
        assert "path" in h
        assert "score" in h


def test_search_docs_semantic_tutorial_filter(minimal_index, monkeypatch):
    from groundwater_mcp.tools.docs import _semantic_search

    rng = np.random.default_rng(1)
    fake_vec = rng.standard_normal(384).astype("float32")
    fake_vec /= np.linalg.norm(fake_vec)
    monkeypatch.setattr(
        docs_module, "_get_model", lambda: type("M", (), {"encode": lambda self, q, **kw: fake_vec})()
    )

    hits = _semantic_search("tutorial", None, True, None, 10)
    assert all(h["is_tutorial"] for h in hits)


# ---------------------------------------------------------------------------
# search_tutorials
# ---------------------------------------------------------------------------


def test_search_tutorials_complexity_filter(minimal_index, monkeypatch):
    from groundwater_mcp.tools.docs import _impl_search_tutorials

    # Monkeypatch _semantic_search to return all tutorials
    def fake_semantic(query, repos, is_tutorial, complexity, limit):
        return [
            {
                "path": d["path"],
                "repo": d["repo"],
                "title": d["title"],
                "snippet": d["text"][:200],
                "is_tutorial": d["is_tutorial"],
                "complexity": d["complexity"],
                "score": 0.5,
                "method": "semantic",
            }
            for d in _FAKE_DOCS
            if d["is_tutorial"] and (complexity is None or d["complexity"] == complexity)
        ][:limit]

    monkeypatch.setattr(docs_module, "_semantic_search", fake_semantic)

    result = _impl_search_tutorials("beginner tutorial", complexity="beginner")
    assert "error" not in result
    assert all(h["complexity"] == "beginner" for h in result["results"])


def test_search_tutorials_invalid_complexity(minimal_index):
    from groundwater_mcp.tools.docs import _impl_search_tutorials

    result = _impl_search_tutorials("model", complexity="expert")
    assert result["error"] is True
    assert result["code"] == "INVALID_COMPLEXITY"


# ---------------------------------------------------------------------------
# get_doc_file
# ---------------------------------------------------------------------------


def test_get_doc_file_first_page(minimal_index):
    from groundwater_mcp.tools.docs import _impl_get_doc_file

    result = _impl_get_doc_file("modflow6/README.md", page=1)
    assert "error" not in result
    assert result["page"] == 1
    assert result["total_pages"] >= 1
    assert len(result["content"]) > 0
    assert "MODFLOW" in result["content"]


def test_get_doc_file_not_found(minimal_index):
    from groundwater_mcp.tools.docs import _impl_get_doc_file

    result = _impl_get_doc_file("nonexistent/path.md", page=1)
    assert result["error"] is True
    assert result["code"] == "DOC_NOT_FOUND"


def test_get_doc_file_page_out_of_range(minimal_index):
    from groundwater_mcp.tools.docs import _impl_get_doc_file

    result = _impl_get_doc_file("modflow6/README.md", page=999)
    assert result["error"] is True
    assert result["code"] == "PAGE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# No index built
# ---------------------------------------------------------------------------


def test_no_index_returns_error(tmp_path, monkeypatch):
    from groundwater_mcp.tools.docs import _impl_search_docs

    # Point to empty dir (no index)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(docs_module, "WHOOSH_DIR", empty / "whoosh")
    monkeypatch.setattr(docs_module, "EMBEDDINGS_PATH", empty / "embeddings.npy")
    monkeypatch.setattr(docs_module, "METADATA_PATH", empty / "metadata.json")
    monkeypatch.setattr(docs_module, "_whoosh_index", None)
    monkeypatch.setattr(docs_module, "_embeddings", None)
    monkeypatch.setattr(docs_module, "_metadata", None)

    result = _impl_search_docs("anything")
    assert result["error"] is True
    assert result["code"] == "INDEX_NOT_BUILT"
