"""model_store.py — in-process FloPy simulation cache with disk persistence.

All tool modules that need to read or modify a model go through this module
so we never have two separate in-memory copies of the same simulation.
"""

from __future__ import annotations

import flopy.mf6 as mf6

from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Module-level cache: model_name → MFSimulation
# ---------------------------------------------------------------------------

_cache: dict[str, mf6.MFSimulation] = {}


def get_sim(name: str) -> mf6.MFSimulation:
    """Return the MFSimulation for a model, loading from disk if not cached."""
    if name in _cache:
        return _cache[name]
    ws = resolve_workspace(name)
    try:
        sim = mf6.MFSimulation.load(sim_ws=str(ws), verbosity_level=0)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load simulation for model '{name}' from {ws}. "
            f"Has create_model been called? FloPy error: {exc}"
        ) from exc
    _cache[name] = sim
    return sim


def save_sim(name: str, sim: mf6.MFSimulation) -> None:
    """Write the simulation to disk and update the cache.

    If the simulation is not yet fully configured (e.g. TDIS not added),
    only the name files are written so that the workspace directory is
    populated; the full write happens on the next save_sim call once all
    required packages are in place.
    """
    try:
        sim.write_simulation(silent=True)
    except AttributeError:
        # TDIS not yet attached — write only the simulation and model name files.
        sim.name_file.write()
        for mname in list(sim.model_names):
            sim.get_model(mname).name_file.write()
    _cache[name] = sim


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
