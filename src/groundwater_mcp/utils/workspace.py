"""workspace.py — model directory management.

A simple in-process registry mapping model names to workspace paths.
All tool modules resolve models through this module.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Registry — persisted as a JSON file in each workspace root
# ---------------------------------------------------------------------------

_REGISTRY_FILENAME = ".gwmcp_registry.json"


def _registry_path(workspace_root: Path) -> Path:
    return workspace_root / _REGISTRY_FILENAME


def _load_registry(workspace_root: Path) -> dict[str, str]:
    """Load the registry from disk. Returns an empty dict if not found."""
    p = _registry_path(workspace_root)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save_registry(workspace_root: Path, registry: dict[str, str]) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    _registry_path(workspace_root).write_text(json.dumps(registry, indent=2))


# ---------------------------------------------------------------------------
# Default workspace root: ~/.groundwater-mcp/workspaces/
# ---------------------------------------------------------------------------

def default_workspace_root() -> Path:
    return Path.home() / ".groundwater-mcp" / "workspaces"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_workspace(name: str, workspace: str | None = None) -> Path:
    """Create and register a model workspace directory.

    Parameters
    ----------
    name:
        Model name. Must be unique within the workspace root.
    workspace:
        Absolute path for the model directory. Defaults to
        ``~/.groundwater-mcp/workspaces/<name>/``.

    Returns
    -------
    Path
        Absolute path to the created model workspace.

    Raises
    ------
    ValueError
        If a model with the same name is already registered.
    """
    root = default_workspace_root()
    registry = _load_registry(root)

    if name in registry:
        raise ValueError(
            f"A model named '{name}' already exists at {registry[name]}. "
            "Use a different name or delete the existing model workspace."
        )

    model_dir = Path(workspace) if workspace else root / name
    model_dir.mkdir(parents=True, exist_ok=True)

    registry[name] = str(model_dir)
    _save_registry(root, registry)

    return model_dir


def resolve_workspace(name: str) -> Path:
    """Return the workspace path for a registered model.

    Raises
    ------
    KeyError
        If the model name is not registered.
    """
    root = default_workspace_root()
    registry = _load_registry(root)

    if name not in registry:
        raise KeyError(
            f"No model named '{name}' found. "
            "Run create_model first, or check the model name."
        )

    return Path(registry[name])


def list_workspaces() -> dict[str, str]:
    """Return a mapping of all registered model names to their workspace paths."""
    root = default_workspace_root()
    return _load_registry(root)


def delete_workspace(name: str, *, remove_files: bool = False) -> None:
    """Unregister a model. Optionally delete the workspace directory.

    Parameters
    ----------
    name:
        Model name to remove.
    remove_files:
        If True, delete the workspace directory and all its contents.
    """
    import shutil

    root = default_workspace_root()
    registry = _load_registry(root)

    if name not in registry:
        raise KeyError(f"No model named '{name}' is registered.")

    model_dir = Path(registry.pop(name))
    _save_registry(root, registry)

    if remove_files and model_dir.exists():
        shutil.rmtree(model_dir)
