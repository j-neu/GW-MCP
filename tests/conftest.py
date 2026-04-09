"""pytest configuration and shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Return a temporary directory to use as a model workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def model_name() -> str:
    """A default model name for use in tests."""
    return "test_model"


@pytest.fixture(autouse=True)
def patch_workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the workspace registry to tmp_path so tests don't touch ~/.groundwater-mcp."""
    import groundwater_mcp.utils.workspace as ws_module

    monkeypatch.setattr(ws_module, "default_workspace_root", lambda: tmp_path / "registry")


@pytest.fixture(autouse=True)
def clear_model_cache() -> None:
    """Clear the in-process simulation cache before and after each test."""
    from groundwater_mcp.utils import model_store

    model_store._cache.clear()
    yield
    model_store._cache.clear()
