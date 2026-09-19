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
    restore_oc_period_records(sim, ws)
    return sim


def _parse_oc_record_lines(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Parse bare SAVE/PRINT lines (an OC period file) into record tuples."""
    saves: list[tuple[str, str]] = []
    prints: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 3:
            continue
        kind, atype, freq = parts[0].upper(), parts[1].upper(), parts[2].upper()
        if kind == "SAVE":
            saves.append((atype, freq))
        elif kind == "PRINT":
            prints.append((atype, freq))
    return saves, prints


def restore_oc_period_records(sim: mf6.MFSimulation, ws: Path) -> None:
    """Re-populate OC ``saverecord``/``printrecord`` from the on-disk OC file.

    FloPy loads a GWF OC package but does not populate the transient
    ``saverecord``/``printrecord`` lists when the period block is an external
    ``OPEN/CLOSE`` file — GMS writes
    ``BEGIN PERIOD 1 / OPEN/CLOSE GWF_Model_input/GWF_Model.oc_1.txt / END PERIOD``
    holding ``SAVE HEAD FIRST`` / ``SAVE BUDGET FIRST``. Without this restore the
    first write of an adopted model drops the period block entirely, so the run
    produces no heads/budget at all. Only restores when the in-memory lists are
    empty, so an explicitly-set saverecord is never overridden.

    If a period block exists, a referenced period file is missing, and the OC
    declares HEAD/BUDGET filerecords, this falls back to saving HEAD and BUDGET
    at FIRST so an adopted GMS model still writes outputs.
    """
    for mname in list(sim.model_names):
        try:
            gwf = sim.get_model(mname)
        except Exception:
            continue
        oc = gwf.get_package("oc")
        if oc is None:
            continue
        try:
            if oc.saverecord.data:
                continue
        except Exception:
            pass
        oc_path = Path(str(getattr(oc, "filename", "") or ""))
        if not oc_path.is_absolute():
            oc_path = ws / oc_path
        if not oc_path.exists():
            continue

        text = oc_path.read_text(errors="replace")
        saverecord: dict[int, list[tuple[str, str]]] = {}
        printrecord: dict[int, list[tuple[str, str]]] = {}
        period: int | None = None
        referenced_missing = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("BEGIN PERIOD"):
                try:
                    period = int(line.split()[2]) - 1
                except (IndexError, ValueError):
                    period = 0
                continue
            if upper.startswith("END PERIOD"):
                period = None
                continue
            if period is None:
                continue
            if upper.startswith("OPEN/CLOSE"):
                toks = line.split(None, 1)
                if len(toks) != 2:
                    continue
                ref = Path(toks[1].strip().strip("'\""))
                if not ref.is_absolute():
                    ref = ws / ref
                if ref.exists():
                    saves, prints = _parse_oc_record_lines(ref.read_text(errors="replace"))
                    saverecord.setdefault(period, []).extend(saves)
                    printrecord.setdefault(period, []).extend(prints)
                else:
                    referenced_missing = True
                continue
            saves, prints = _parse_oc_record_lines(line)
            saverecord.setdefault(period, []).extend(saves)
            printrecord.setdefault(period, []).extend(prints)

        if not saverecord and referenced_missing:
            # Fall back to the declared filerecords when the external period
            # file is unavailable (e.g. a clone that did not carry subdirs).
            if getattr(oc, "head_filerecord", None) is not None or getattr(
                oc, "budget_filerecord", None
            ) is not None:
                saverecord = {0: [("HEAD", "FIRST"), ("BUDGET", "FIRST")]}
        try:
            if saverecord:
                oc.saverecord.set_data(saverecord)
            if printrecord:
                oc.printrecord.set_data(printrecord)
        except Exception:
            pass


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


def clear_k_base_snapshot(model: str, gwf_name: str) -> bool:
    """Delete ``setup_calibration``'s pristine NPF snapshot(s), if present.

    Any tool that deliberately changes NPF ``k`` or ``k33``
    (``assign_k_from_raster``, ``assign_k_from_zones``, ``add_npf_package``)
    calls this so a later ``setup_calibration`` re-snapshots the new field
    instead of restoring the previous base. Both ``<gwf>_k_pristine.npy`` and
    ``<gwf>_k33_pristine.npy`` are removed. Returns ``True`` when at least one
    snapshot was removed.
    """
    ws = resolve_workspace(model)
    removed = False
    for keyword in ("k", "k33"):
        path = ws / f"{gwf_name}_{keyword}_pristine.npy"
        if path.exists():
            path.unlink()
            removed = True
    return removed


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
