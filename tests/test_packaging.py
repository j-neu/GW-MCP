"""Packaging guards: things that only break on a clean install."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_mcp_dependency_is_capped_below_2():
    """mcp 2.x removed ``mcp.server.fastmcp``; an uncapped ``mcp>=1.0`` makes a
    fresh install resolve to 2.x and fail on import (found by a clean-venv
    install, R5.6)."""
    spec = next(d for d in _project()["dependencies"] if re.match(r"mcp\b", d))
    assert "<2" in spec.replace(" ", "")


def test_console_script_and_pypi_metadata_present():
    project = _project()
    assert project["scripts"]["groundwater-mcp"] == "groundwater_mcp.server:main"
    assert project["keywords"] and project["classifiers"]
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert {"Homepage", "Issues"} <= set(project["urls"])
