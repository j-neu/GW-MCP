"""model_store.py — in-process FloPy simulation cache with disk persistence.

All tool modules that need to read or modify a model go through this module
so we never have two separate in-memory copies of the same simulation.

Cache correctness (7f-D4):
- The mtimes of the simulation's input files (``mfsim.nam``, model name files,
  package files) are recorded at load/save time. ``get_sim`` re-reads the
  mtimes on every cache hit and reloads from disk when any tracked file is
  newer than the recorded state, so external edits are never served from a
  stale in-memory copy.
- Adopted models are read-only by default: ``save_sim`` raises
  :class:`ModelReadOnlyError` for them so a real published model cannot be
  silently rewritten by a stray builder call.

Deferred writes (7f-E1.2):
- ``save_sim`` stages a mutation into the cache and marks the model dirty; the
  disk write is deferred to ``flush_model``. Builder tools therefore do not
  re-serialise the whole simulation on every call (which is quadratic in write
  volume on a regional grid).
- ``flush_model`` performs the write and records fresh mtimes; it is a no-op
  (returns ``False``) for clean models and for adopted read-only models.
- A model with no on-disk mtime snapshot yet (created but never flushed) is
  authoritative in memory: ``_files_changed`` returns ``False`` for it so the
  cache is never reloaded from an absent/empty disk state. Once flushed,
  external edits are detected exactly as before (7f-D4.1).
"""

from __future__ import annotations

import json
from pathlib import Path

import flopy.mf6 as mf6

from groundwater_mcp.utils.workspace import resolve_workspace


class ModelReadOnlyError(RuntimeError):
    """Raised when a save_sim-backed tool tries to modify an adopted model.

    Adopted models are registered read-only by default (7f-D4.2): the on-disk
    input set is treated as authoritative. Re-register with
    ``adopt_model(allow_modify=True)`` to opt out.
    """


# ---------------------------------------------------------------------------
# Module-level cache: model_name → MFSimulation (+ file-mtime snapshot)
# ---------------------------------------------------------------------------

_cache: dict[str, mf6.MFSimulation] = {}
_mtimes: dict[str, dict[str, float]] = {}
_reload_flags: dict[str, bool] = {}
_dirty: dict[str, bool] = {}

_META_FILE = ".gwmcp_meta.json"


def _read_meta(ws: Path) -> dict:
    p = ws / _META_FILE
    return json.loads(p.read_text()) if p.exists() else {}


def read_meta(name: str) -> dict:
    """Read the workspace metadata JSON (``.gwmcp_meta.json``) for a model."""
    return _read_meta(resolve_workspace(name))


def write_meta(name: str, meta: dict) -> None:
    """Replace the workspace metadata JSON for a model."""
    (resolve_workspace(name) / _META_FILE).write_text(json.dumps(meta, indent=2))


def _is_readonly(name: str) -> bool:
    ws = resolve_workspace(name)
    meta = _read_meta(ws)
    return bool(meta.get("adopted") and not meta.get("allow_modify"))


def _collect_input_files(sim: mf6.MFSimulation, ws: Path) -> list[Path]:
    """Return the absolute paths of the simulation's input files (name files
    plus package files), used for staleness detection."""
    paths: set[Path] = set()

    def add(pkg_or_nam) -> None:
        if pkg_or_nam is None:
            return
        fn = getattr(pkg_or_nam, "filename", None)
        if not fn:
            return
        p = Path(fn)
        if not p.is_absolute():
            p = ws / p
        paths.add(p)

    add(sim.name_file)
    for mname in list(sim.model_names):
        m = sim.get_model(mname)
        add(m.name_file)
        try:
            for pname in m.get_package_list():
                try:
                    add(m.get_package(pname))
                except Exception:
                    pass
        except Exception:
            pass
    return sorted(paths)


def _record_mtimes(name: str, sim: mf6.MFSimulation, ws: Path) -> None:
    _mtimes[name] = {
        str(p): p.stat().st_mtime for p in _collect_input_files(sim, ws) if p.exists()
    }


def _files_changed(name: str) -> bool:
    """True when any tracked input file is missing or newer than recorded.

    A model with no on-disk snapshot yet (created but never flushed, or
    freshly staged) is authoritative in memory — nothing on disk exists to be
    newer than, so the cache is served (7f-E1.2).
    """
    recorded = _mtimes.get(name)
    if not recorded:
        return False
    for path_str, old_mtime in recorded.items():
        p = Path(path_str)
        if not p.exists():
            return True
        if p.stat().st_mtime > old_mtime:
            return True
    return False


def _load_sim(name: str, ws: Path) -> mf6.MFSimulation:
    try:
        return mf6.MFSimulation.load(sim_ws=str(ws), verbosity_level=0)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load simulation for model '{name}' from {ws}. "
            f"Has create_model been called? FloPy error: {exc}"
        ) from exc


def _apply_meta_crs(sim: mf6.MFSimulation, ws: Path) -> None:
    """Re-apply the persisted CRS/origin to a freshly-loaded simulation.

    flopy does not store the CRS in MF6 input files, so any load from disk
    (a 7f-D4.1 staleness reload, adopt_model, or a fresh process) would leave
    ``modelgrid.crs`` as ``None`` and the georeferenced exporters would fail
    CRS_UNKNOWN. ``set_model_crs`` / ``import_grid_from_shapefile`` persist
    the CRS (and origin) to ``.gwmcp_meta.json``; restore it here.
    """
    meta = _read_meta(ws)
    crs = meta.get("crs")
    if not crs:
        return
    kwargs: dict = {}
    if "xorigin" in meta:
        kwargs["xoff"] = meta["xorigin"]
    if "yorigin" in meta:
        kwargs["yoff"] = meta["yorigin"]
    if "angrot" in meta:
        kwargs["angrot"] = meta["angrot"]
    kwargs["crs"] = crs
    for mname in list(sim.model_names):
        try:
            sim.get_model(mname).modelgrid.set_coord_info(**kwargs)
        except Exception:
            pass


def _load_and_apply(name: str, ws: Path) -> mf6.MFSimulation:
    sim = _load_sim(name, ws)
    _apply_meta_crs(sim, ws)
    return sim


def get_sim(name: str) -> mf6.MFSimulation:
    """Return the MFSimulation for a model, loading from disk if not cached.

    A cache hit is served only when the recorded input-file mtimes are still
    current; otherwise the simulation is reloaded from disk and the reload is
    flagged for ``consume_reload_flag`` so the calling tool can report it.
    """
    ws = resolve_workspace(name)
    if name in _cache:
        if _files_changed(name):
            sim = _load_and_apply(name, ws)
            _cache[name] = sim
            _record_mtimes(name, sim, ws)
            _reload_flags[name] = True
        return _cache[name]
    sim = _load_and_apply(name, ws)
    _cache[name] = sim
    _record_mtimes(name, sim, ws)
    return sim


def save_sim(name: str, sim: mf6.MFSimulation) -> bool:
    """Stage a mutation into the cache and mark the model dirty (7f-E1.2).

    The disk write is deferred to :func:`flush_model`. Returns ``False``
    (``written: false``) so builder tools can report that their change is not
    yet on disk. The next flush point — ``check_model``, ``run_simulation``,
    ``list_model_files``, ``flush_model``, or the calibration handoff —
    performs the write.

    Adopted read-only models refuse staging (7f-D4.2): the on-disk input set
    is authoritative and a stray builder call must not rewrite it.
    """
    if _is_readonly(name):
        # Discard the in-memory (possibly mutated) copy so the next access
        # reloads the authoritative on-disk state.
        _cache.pop(name, None)
        _dirty.pop(name, None)
        raise ModelReadOnlyError(
            f"Model '{name}' was registered with adopt_model and is read-only. "
            "The on-disk MODFLOW 6 input set is authoritative — it would be "
            "overwritten by this write. Re-register with adopt_model("
            "allow_modify=True) to allow modifications, or create a copy with "
            "create_model and rebuild the model there."
        )
    _cache[name] = sim
    _dirty[name] = True
    return False


def _write_sim_to_disk(sim: mf6.MFSimulation) -> None:
    """Write a simulation to disk (with the bare-model name-file fallback)."""
    try:
        sim.write_simulation(silent=True)
    except AttributeError:
        # TDIS not yet attached — write only the simulation and model name files.
        sim.name_file.write()
        for mname in list(sim.model_names):
            sim.get_model(mname).name_file.write()


def flush_model(name: str) -> bool:
    """Write a dirty model to disk and update the cache snapshot.

    Returns ``True`` when a write actually happened, ``False`` when the model
    was already clean (nothing to write) or is an adopted read-only model
    (which can never become dirty). After a flush, external edits are again
    detected via the mtime snapshot (7f-D4.1).
    """
    if not _dirty.get(name):
        return False
    sim = _cache[name]
    _write_sim_to_disk(sim)
    _dirty[name] = False
    _record_mtimes(name, sim, resolve_workspace(name))
    return True


def is_dirty(name: str) -> bool:
    """Return whether a model has staged in-memory changes not yet flushed."""
    return bool(_dirty.get(name))


def cache_sim(name: str, sim: mf6.MFSimulation) -> None:
    """Cache an already-loaded simulation without writing anything to disk.

    Used by adopt_model to bring an existing on-disk MODFLOW 6 simulation
    into the in-process cache (the files are authoritative; no re-write).
    """
    ws = resolve_workspace(name)
    _apply_meta_crs(sim, ws)
    _cache[name] = sim
    _record_mtimes(name, sim, ws)
    _reload_flags.pop(name, None)
    _dirty.pop(name, None)


def consume_reload_flag(name: str) -> bool:
    """Return and clear whether the last get_sim reloaded from disk (7f-D4.1).

    Tools surface this as ``reloaded_from_disk`` in their result so callers
    know the in-memory model was refreshed mid-flight.
    """
    return _reload_flags.pop(name, False)


def get_gwf(name: str) -> mf6.ModflowGwf:
    """Return the GWF model object for a registered model name."""
    sim = get_sim(name)
    gwf = sim.get_model(name)
    if gwf is None:
        # Fallback: take the first model in the simulation
        model_names = list(sim.model_names)
        if not model_names:
            raise KeyError(f"No models found in simulation for '{name}'.")
        gwf = sim.get_model(model_names[0])
    return gwf


def invalidate(name: str) -> None:
    """Remove a model from the in-process cache (force reload from disk next access)."""
    _cache.pop(name, None)
    _mtimes.pop(name, None)
    _reload_flags.pop(name, None)
    _dirty.pop(name, None)
