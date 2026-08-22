"""environment module — preflight checks for a hands-free session.

Provides a single ``check_environment`` tool that reports everything an agent
needs before building a model: the server's own Python environment (packages
with versions), the locations of the MODFLOW 6 / PEST++ executables, the docs
index state, and the default workspace root.  The agent should call this once
at the start of a session instead of probing ``sys.executable`` with shell
commands (which commonly checks the wrong interpreter).
"""

from __future__ import annotations

import importlib
import platform
import sys

from mcp.server.fastmcp import FastMCP

from groundwater_mcp.index_builder import INDEX_DIR, METADATA_PATH, WHOOSH_DIR
from groundwater_mcp.tools.calibration import _find_pestpp_binary
from groundwater_mcp.tools.runner import _find_mf6_binary
from groundwater_mcp.utils.workspace import default_workspace_root

# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

_PACKAGES = (
    "flopy",
    "pyemu",
    "geopandas",
    "rasterio",
    "numpy",
    "scipy",
    "matplotlib",
    "whoosh",
)

_PESTPP_BINARIES = (
    "pestpp-glm",
    "pestpp-ies",
    "pestpp-sen",
    "pestpp-opt",
    "pestpp-da",
)


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in _PACKAGES:
        try:
            mod = importlib.import_module(name)
            versions[name] = getattr(mod, "__version__", "installed")
        except ImportError:
            versions[name] = None
    return versions


def _impl_check_environment() -> dict:
    """Assemble the full environment report for the running server."""
    packages = _package_versions()

    binaries: dict[str, str | None] = {"mf6": None}
    for exe in _PESTPP_BINARIES:
        binaries[exe] = None

    for exe in _PESTPP_BINARIES:
        try:
            binaries[exe] = _find_pestpp_binary(exe)
        except RuntimeError:
            pass
    try:
        binaries["mf6"] = _find_mf6_binary()
    except RuntimeError:
        pass

    index_built = (METADATA_PATH.exists() and WHOOSH_DIR.exists()) or (
        INDEX_DIR.exists() and any(INDEX_DIR.iterdir())
    )

    missing_packages = sorted(name for name, ver in packages.items() if ver is None)
    missing_binaries = sorted(name for name, path in binaries.items() if path is None)

    return {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "packages": packages,
        "binaries": binaries,
        "docs_index_built": index_built,
        "docs_index_dir": str(INDEX_DIR),
        "workspace_root": str(default_workspace_root()),
        "missing": {
            "packages": missing_packages,
            "binaries": missing_binaries,
        },
        "ready": not missing_packages and not missing_binaries and index_built,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register environment tools with the MCP server."""

    @mcp.tool()
    def check_environment() -> dict:
        """Report the server's runtime environment: Python, installed packages with
        versions (flopy, pyemu, geopandas, rasterio, ...), the paths to the MODFLOW 6
        and PEST++ executables, the local docs index state, and the default model
        workspace root. Call this once at the start of a session to confirm the
        stack is ready before building a model — do not probe with shell commands.
        """
        try:
            return _impl_check_environment()
        except Exception as exc:
            return _err("ENVIRONMENT_CHECK_FAILED", str(exc))
