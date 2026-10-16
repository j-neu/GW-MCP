"""workspace.py — model directory management.

A simple registry mapping model names to workspace paths. The registry is
**scoped per workspace root** (7e-B4.2): models created with an explicit
``workspace`` register in a ``.gwmcp_registry.json`` next to that workspace
(parent directory), and models created without one register in the default
root's registry. A small "known roots" index (``known_roots.json`` next to the
default root) lets ``resolve_workspace`` / ``list_workspaces`` find models
registered in external roots.

Re-registering the *same* name+path is idempotent (returns the existing
workspace); the same name under a different root is legal; the same name
twice in the same root with different paths is a collision error. When the same
name exists under several roots, ``resolve_workspace`` prefers the root that
was registered most recently (known roots are stored most-recent-first).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------------------
# Registry — persisted as a JSON file in each workspace root
# ---------------------------------------------------------------------------

_REGISTRY_FILENAME = ".gwmcp_registry.json"
_KNOWN_ROOTS_FILENAME = "known_roots.json"


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
    _atomic_write(_registry_path(workspace_root), json.dumps(registry, indent=2))


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a reader never sees a torn file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


_LOCK_FILENAME = ".gwmcp_registry.lock"
_LOCK_TIMEOUT_S = 30.0
_STALE_LOCK_S = 60.0


@contextmanager
def _registry_lock(directory: Path, filename: str = _LOCK_FILENAME) -> Iterator[None]:
    """Exclusive cross-process lock for a read-modify-write of a registry file.

    The critical sections are milliseconds long, so a lock file created with
    ``O_EXCL`` that a crashed holder left behind for more than
    ``_STALE_LOCK_S`` is taken over rather than waited on forever.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / filename
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except FileNotFoundError:
                continue  # released between the open and the stat
            if age > _STALE_LOCK_S:
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Could not lock {lock} within {_LOCK_TIMEOUT_S:.0f}s; "
                    "another groundwater-mcp session holds it."
                ) from None
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Known-roots index — which external roots hold registries (7e-B4.2)
# ---------------------------------------------------------------------------


def _known_roots_path() -> Path:
    """The known-roots index lives next to the default workspace root.

    Deriving it from ``default_workspace_root()`` keeps it inside the same
    base directory, so tests that monkeypatch the default root stay isolated.
    """
    return default_workspace_root().parent / _KNOWN_ROOTS_FILENAME


def _load_known_roots() -> list[Path]:
    p = _known_roots_path()
    if p.exists():
        try:
            return [Path(x) for x in json.loads(p.read_text())]
        except (OSError, ValueError):
            return []
    return []


def _remember_root(root: Path) -> None:
    """Record *root* as the most recently used external registry root.

    Roots are stored most-recent-first so ``resolve_workspace`` prefers the
    workspace that was registered last when the same model name exists in
    several roots (e.g. one Agent Manager worktree per run).
    """
    with _registry_lock(_known_roots_path().parent, ".gwmcp_known_roots.lock"):
        known = [r for r in _load_known_roots() if r != root]
        known.insert(0, root)
        _save_known_roots(known)


def _forget_root_if_empty(root: Path) -> None:
    """Drop *root* from the known-roots index when its registry is empty."""
    if _load_registry(root):
        return
    with _registry_lock(_known_roots_path().parent, ".gwmcp_known_roots.lock"):
        known = [r for r in _load_known_roots() if r != root]
        _save_known_roots(known)


def _save_known_roots(roots: list[Path]) -> None:
    """Persist the known-roots index, preserving order (most recent first)."""
    seen: list[str] = []
    for r in roots:
        s = str(r)
        if s not in seen:
            seen.append(s)
    p = _known_roots_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(seen, indent=2))


# ---------------------------------------------------------------------------
# Default workspace root: ~/.groundwater-mcp/workspaces/
# ---------------------------------------------------------------------------

def default_workspace_root() -> Path:
    return Path.home() / ".groundwater-mcp" / "workspaces"


def _registry_root_for(model_dir: Path, explicit: bool) -> Path:
    """Return the registry root that owns a model directory.

    Explicit workspaces register in their parent directory (the workspace
    root); default workspaces register in the default root itself.
    """
    return model_dir.parent if explicit else default_workspace_root()


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
        If a model with the same name is already registered in the same
        workspace root at a different path.
    """
    explicit = workspace is not None
    if explicit:
        assert workspace is not None
        model_dir = Path(workspace)
    else:
        model_dir = default_workspace_root() / name
    root = _registry_root_for(model_dir, explicit)
    with _registry_lock(root):
        registry = _load_registry(root)

        if name in registry:
            if Path(registry[name]).resolve() == model_dir.resolve():
                return model_dir  # idempotent re-register of the same name+path
            raise ValueError(
                f"A model named '{name}' already exists in this workspace root "
                f"at {registry[name]}. Use a different name, a different "
                "workspace root, or delete the existing model workspace."
            )

        model_dir.mkdir(parents=True, exist_ok=True)
        registry[name] = str(model_dir)
        _save_registry(root, registry)
    if explicit:
        _remember_root(root)
    return model_dir


def resolve_workspace(name: str) -> Path:
    """Return the workspace path for a registered model.

    The default root's registry is checked first; models registered in
    external workspace roots are located via the known-roots index.

    Raises
    ------
    KeyError
        If the model name is not registered.
    """
    # A registration whose directory no longer exists (an old session, a deleted
    # worktree) must not shadow a live workspace of the same name in another
    # root. Prefer the first live entry; fall back to the first stale one so a
    # tool can still report "files not found" instead of "no such model".
    stale: Path | None = None
    registry = _load_registry(default_workspace_root())
    if name in registry:
        path = Path(registry[name])
        if path.exists():
            return path
        stale = path

    for root in _load_known_roots():
        reg = _load_registry(root)
        if name in reg:
            path = Path(reg[name])
            if path.exists():
                return path
            stale = stale or path

    if stale is not None:
        return stale

    raise KeyError(
        f"No model named '{name}' found. "
        "Run create_model first, or check the model name."
    )


def list_workspaces() -> dict[str, str]:
    """Return a mapping of all registered model names to their workspace paths."""
    merged: dict[str, str] = dict(_load_registry(default_workspace_root()))
    for root in _load_known_roots():
        for key, value in _load_registry(root).items():
            # a live workspace replaces a stale registration of the same name
            if key not in merged or (
                not Path(merged[key]).exists() and Path(value).exists()
            ):
                merged[key] = value
    return merged


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

    model_dir: Path | None = None
    removed_from: Path | None = None

    root = default_workspace_root()
    with _registry_lock(root):
        registry = _load_registry(root)
        if name in registry:
            model_dir = Path(registry.pop(name))
            _save_registry(root, registry)
            removed_from = root

    if removed_from is None:
        for ext_root in _load_known_roots():
            with _registry_lock(ext_root):
                reg = _load_registry(ext_root)
                found = name in reg
                if found:
                    model_dir = Path(reg.pop(name))
                    _save_registry(ext_root, reg)
            if found:
                removed_from = ext_root
                _forget_root_if_empty(ext_root)
                break

    if removed_from is None:
        raise KeyError(f"No model named '{name}' is registered.")

    if remove_files and model_dir is not None and model_dir.exists():
        shutil.rmtree(model_dir)
