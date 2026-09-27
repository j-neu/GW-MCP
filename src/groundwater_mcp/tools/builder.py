"""builder module — create and configure MODFLOW 6 GWF models via FloPy."""

from __future__ import annotations

import json
from pathlib import Path

import flopy.mf6 as mf6
import numpy as np

from groundwater_mcp.utils.components import (
    UnknownComponentError,
    grid_class_for,
    spec_for,
)
from groundwater_mcp.utils.grid import get_dis, get_disu, get_disv, grid_size
from groundwater_mcp.utils.model_store import (
    ModelReadOnlyError,
    cache_component_sim,
    cache_sim,
    clear_component_sims,
    clear_csub_base_snapshot,
    clear_k_base_snapshot,
    component_map,
    consume_reload_flag,
    detect_components,
    flush_model,
    get_gwf,
    get_model,
    get_sim,
    invalidate,
    is_readonly,
    list_components,
    restore_oc_period_records,
    save_sim,
)
from groundwater_mcp.utils.workspace import (
    create_workspace,
    delete_workspace,
    list_workspaces,
    resolve_workspace,
)

# ---------------------------------------------------------------------------
# Supported boundary packages
# ---------------------------------------------------------------------------

_BOUNDARY_PKG_CLASSES: dict[str, type] = {
    "CHD": mf6.ModflowGwfchd,
    "WEL": mf6.ModflowGwfwel,
    "RIV": mf6.ModflowGwfriv,
    "DRN": mf6.ModflowGwfdrn,
    "RCH": mf6.ModflowGwfrch,
    "RCHA": mf6.ModflowGwfrcha,
    "EVT": mf6.ModflowGwfevt,
    "EVTA": mf6.ModflowGwfevta,
    "GHB": mf6.ModflowGwfghb,
    "SFR": mf6.ModflowGwfsfr,
}

# List-based boundary packages (stress_period_data = list of cell records).
# Array-based packages (RCHA/EVTA) take a full-grid array per stress period.
_ARRAY_BOUNDARY_PKGS = {"RCHA", "EVTA"}

# Model length unit → metres.
_LENGTH_TO_METRES: dict[str, float] = {
    "METERS": 1.0,
    "FEET": 0.3048,
    "CENTIMETERS": 0.01,
}

# Conductivity unit → metres per day.
_K_UNITS_TO_PER_DAY: dict[str, float] = {
    "m/d": 1.0,
    "m/s": 86400.0,
    "m/yr": 1.0 / 365.0,
    "cm/s": 864.0,
    "ft/d": 0.3048,
    "ft/s": 0.3048 * 86400.0,
}

# Rate unit → metres per day.
_RATE_UNITS_TO_MD: dict[str, float] = {
    "m/d": 1.0,
    "m/yr": 1.0 / 365.0,
    "mm/d": 0.001,
    "mm/yr": 0.001 / 365.0,
}

_SECONDS_PER_TIME_UNIT: dict[str, float] = {
    "SECONDS": 1.0,
    "MINUTES": 60.0,
    "HOURS": 3600.0,
    "DAYS": 86400.0,
    "YEARS": 31536000.0,
}

# CSUB water specific weight (gammaw) and water compressibility (beta) defaults
# per model length unit. The SI pair is 9806.65 N/m3 and 4.6512e-10 1/Pa; the
# US-customary pair is 62.48 lb/ft3 and 2.227e-8 ft2/lb — the values the CSUB
# benchmark models use. Defaulting to SI in a FEET model silently mis-scales the
# effective-stress terms (6d Target 9 rerun-3).
_GAMMAW_BY_UNIT: dict[str, float] = {"METERS": 9806.65, "FEET": 62.48}
_BETA_BY_UNIT: dict[str, float] = {"METERS": 4.6512e-10, "FEET": 2.227e-8}


def _length_metres_per_unit(length_units: str) -> float:
    """Metres in one model length unit (unknown units fall back to metres)."""
    return _LENGTH_TO_METRES.get(str(length_units).upper(), 1.0)


def _time_factor(time_units: str) -> float:
    """Seconds per model time unit (unknown units fall back to days)."""
    return _SECONDS_PER_TIME_UNIT.get(str(time_units).upper(), 86400.0)


def _unit_factor(per_day: float, time_units: str, length_units: str) -> float:
    """Scale a metres-per-day base into the model's length unit per its time
    unit. Multiplies the per-day base (rather than round-tripping through
    metres/second) so exact inputs stay exact — e.g. 1 mm/d → 0.001."""
    return (
        per_day
        * (_time_factor(time_units) / 86400.0)
        / _length_metres_per_unit(length_units)
    )


def _convert_k_to_model(
    value, k_units: str, time_units: str, length_units: str = "METERS"
):
    """Convert a conductivity value from *k_units* into the model's convention:
    the model's length unit per its time unit.

    The length unit matters — MODFLOW expects k in the model's own length unit,
    so ``k_units="ft/d", k=10`` in a FEET model stays 10, while ``k_units="m/d",
    k=10`` becomes 32.808. Converting to metres in every model silently scaled
    FEET models by 0.3048 (6d Target 9 rerun-3).
    """
    if k_units not in _K_UNITS_TO_PER_DAY:
        raise ValueError(
            f"Unrecognised k_units '{k_units}'. Accepted: {sorted(_K_UNITS_TO_PER_DAY)}."
        )
    factor = _unit_factor(_K_UNITS_TO_PER_DAY[k_units], time_units, length_units)
    if isinstance(value, (int, float)):
        return float(value) * factor
    return np.asarray(value, dtype=float) * factor


def _rate_factor(rate_units: str, time_units: str, length_units: str) -> float:
    """Multiplier turning a rate in *rate_units* into the model's length unit
    per its time unit."""
    if rate_units not in _RATE_UNITS_TO_MD:
        raise ValueError(
            f"Unrecognised rate_units '{rate_units}'. Accepted: {sorted(_RATE_UNITS_TO_MD)}."
        )
    return _unit_factor(_RATE_UNITS_TO_MD[rate_units], time_units, length_units)


def _convert_rate(
    value, rate_units: str, time_units: str = "DAYS", length_units: str = "METERS"
) -> float:
    """Convert a recharge/ET rate from *rate_units* into the model's length unit
    per its time unit."""
    return float(value) * _rate_factor(rate_units, time_units, length_units)

# ---------------------------------------------------------------------------
# Shared error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


class PayloadTooLargeError(ValueError):
    """Raised when an inline payload exceeds a size guard (7f-I4)."""


_DISV_INLINE_CELL_LIMIT = 50_000


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

_META_FILE = ".gwmcp_meta.json"


def _read_meta(model_dir: Path) -> dict:
    p = model_dir / _META_FILE
    return json.loads(p.read_text()) if p.exists() else {}


def _write_meta(model_dir: Path, meta: dict) -> None:
    (model_dir / _META_FILE).write_text(json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _impl_create_model(
    name: str,
    workspace: str,
    units: str,
    time_units: str,
) -> dict:
    if len(name) > 16:
        raise ValueError(
            f"Model name '{name}' is {len(name)} characters; MODFLOW 6 caps "
            "MODELNAME at 16 characters. Use a shorter name."
        )
    model_dir = create_workspace(name, workspace or None)
    # Re-creating a model resets its flow input set and metadata; drop any
    # component simulation cached from a previous incarnation of this name.
    clear_component_sims(name)
    sim = mf6.MFSimulation(
        sim_name="mfsim",
        version="mf6",
        sim_ws=str(model_dir),
    )
    mf6.ModflowGwf(sim, modelname=name, model_nam_file=f"{name}.nam")
    _write_meta(model_dir, {
        "name": name,
        "units": units.upper(),
        "time_units": time_units.upper(),
        "components": {"gwf": name},
    })
    written = save_sim(name, sim)
    return {
        "model": name,
        "workspace": str(model_dir),
        "units": units.upper(),
        "time_units": time_units.upper(),
        "written": written,
    }


def _impl_adopt_model(
    name: str,
    workspace: str,
    units: str,
    time_units: str,
    allow_modify: bool = False,
) -> dict:
    """Register an existing MODFLOW 6 simulation on disk as a model.

    ``workspace`` must be a directory that already contains a runnable MF6
    input set (``mfsim.nam`` plus the package files it references). The
    simulation is loaded into the in-process cache from the on-disk files
    (no stub is created and no files are rewritten), so subsequent tools
    (check_model, run_simulation, summarise_model, calibration) operate on
    the real model.

    Model-name length is capped at 16 characters (MODFLOW 6 MODELNAME).
    The GWF model name inside the files need NOT match ``name`` — tools that
    resolve the GWF fall back to the first model in the simulation.

    Adopted models are registered read-only by default (7f-D4.2): every
    ``save_sim``-backed builder call is refused with MODEL_ADOPTED_READONLY so
    a real published model cannot be silently rewritten. Pass
    ``allow_modify=True`` to opt out. Non-mutating tools (check_model,
    run_simulation, summarise_model, read_heads) always work.
    """
    if len(name) > 16:
        raise ValueError(
            f"Model name '{name}' is {len(name)} characters; MODFLOW 6 caps "
            "MODELNAME at 16 characters. Use a shorter name."
        )
    model_dir = create_workspace(name, workspace or None)
    sim_nam = model_dir / "mfsim.nam"
    if not sim_nam.exists():
        raise FileNotFoundError(
            f"No mfsim.nam found in {model_dir}. adopt_model registers an "
            "existing MODFLOW 6 simulation — the workspace must already "
            "contain a runnable input set (mfsim.nam + package files)."
        )
    sim = mf6.MFSimulation.load(sim_ws=str(model_dir), verbosity_level=0)
    restore_oc_period_records(sim, model_dir)
    cache_sim(name, sim)
    # Preserve separate-simulation components (e.g. a saved GWE heat model):
    # detect_components only sees the flow simulation.
    components: dict = dict(detect_components(sim))
    for cname, value in (_read_meta(model_dir).get("components") or {}).items():
        if isinstance(value, dict) and value.get("workspace"):
            if (model_dir / value["workspace"] / "mfsim.nam").exists():
                components.setdefault(cname, value)
    _write_meta(model_dir, {
        "name": name,
        "units": units.upper(),
        "time_units": time_units.upper(),
        "adopted": True,
        "allow_modify": bool(allow_modify),
        "components": components,
    })
    result: dict = {
        "model": name,
        "workspace": str(model_dir),
        "units": units.upper(),
        "time_units": time_units.upper(),
        "adopted": True,
        "model_names": list(sim.model_names),
    }
    if allow_modify:
        result["allow_modify"] = True
    else:
        result["read_only"] = True
    return result


def _grid_kind_map() -> dict[type, str]:
    """Map every registered grid package class to its kind ('dis'/...)."""
    from groundwater_mcp.utils.components import all_components

    mapping: dict[type, str] = {}
    for spec in all_components().values():
        for kind, cls in spec.grid_classes.items():
            mapping[cls] = kind
    return mapping


def _grid_type_of(model) -> str | None:
    """Return the grid kind ('dis'/'disv'/'disu') of any component model."""
    mapping = _grid_kind_map()
    for pname in list(model.get_package_list()):
        pkg = model.get_package(pname)
        if pkg is None:
            continue
        kind = mapping.get(type(pkg))
        if kind is not None:
            return kind
    return None


def _remove_grid_packages(model, component: str, kinds: tuple[str, ...]) -> None:
    """Remove the named grid packages of *component* (class-based, so it works
    for GWE/PRT packages too — the GWF-only ``get_dis`` helpers do not)."""
    classes = tuple(
        c for c in (grid_class_for(component, k) for k in kinds) if c is not None
    )
    if not classes:
        return
    for pname in list(model.get_package_list()):
        pkg = model.get_package(pname)
        if isinstance(pkg, classes):
            model.remove_package(pkg)


def _component_model_name(model: str, key: str, existing: set[str]) -> str:
    """Derive a <=16-char, unique MF6 model name for a component.

    A plain ``f"{model}_{key}"[:16]`` truncates back onto the base name when
    the base is already 16 characters, producing two models that share one
    MODELNAME (an invalid simulation). This keeps room for the suffix and
    guarantees the result differs from every existing model name.
    """
    suffix = f"_{key}"
    room = 16 - len(suffix)
    candidate = f"{model[:room]}{suffix}" if room >= 1 else key[:16]
    if candidate not in existing:
        return candidate
    for i in range(1, 1000):
        tail = str(i)
        room = 16 - len(suffix) - len(tail)
        candidate = f"{model[: max(0, room)]}{suffix}{tail}"
        if candidate not in existing:
            return candidate
    raise ValueError(f"Could not derive a unique component model name for '{key}'.")


def _mirror_grid(src_model, dst_model, component: str) -> str:
    """Create the component's grid package from the source model's grid."""
    kind = _grid_type_of(src_model)
    if kind is None:
        raise ValueError("Source model has no grid package to mirror (DIS/DISV/DISU).")
    grid_cls = grid_class_for(component, kind)
    if grid_cls is None:
        raise ValueError(
            f"Component '{component}' has no {kind.upper()} grid class — "
            "cannot mirror this grid type."
        )
    kwargs: dict = {}
    if kind == "dis":
        src = get_dis(src_model)
        top = np.asarray(src.top.array)
        kwargs = {
            "nlay": int(src.nlay.data),
            "nrow": int(src.nrow.data),
            "ncol": int(src.ncol.data),
            "delr": np.asarray(src.delr.array).tolist(),
            "delc": np.asarray(src.delc.array).tolist(),
            "top": top.tolist() if top.ndim else float(top),
            "botm": np.asarray(src.botm.array).tolist(),
        }
        idom = getattr(src, "idomain", None)
        if idom is not None:
            kwargs["idomain"] = np.asarray(idom.array).tolist()
    elif kind == "disv":
        src = get_disv(src_model)
        kwargs = {
            "nlay": int(src.nlay.data),
            "ncpl": int(src.ncpl.data),
            "nvert": int(src.nvert.data),
            "vertices": np.asarray(src.vertices.array).tolist(),
            "cell2d": np.asarray(src.cell2d.array).tolist(),
            "top": np.asarray(src.top.array).tolist(),
            "botm": np.asarray(src.botm.array).tolist(),
        }
        idom = getattr(src, "idomain", None)
        if idom is not None:
            kwargs["idomain"] = np.asarray(idom.array).tolist()
    else:  # disu
        src = get_disu(src_model)
        kwargs = {
            "nodes": int(src.nodes.data),
            "nja": int(src.nja.data),
            "top": np.asarray(src.top.array).tolist(),
            "bot": np.asarray(src.bot.array).tolist(),
            "area": np.asarray(src.area.array).tolist(),
            "iac": np.asarray(src.iac.array).tolist(),
            "ja": np.asarray(src.ja.array).tolist(),
        }
        for opt in ("ihc", "cl12", "hwva", "angldegx"):
            ds = getattr(src, opt, None)
            if ds is not None:
                kwargs[opt] = np.asarray(ds.array).tolist()
        idom = getattr(src, "idomain", None)
        if idom is not None:
            kwargs["idomain"] = np.asarray(idom.array).tolist()
        vertices = getattr(src, "vertices", None)
        cell2d = getattr(src, "cell2d", None)
        if vertices is not None and cell2d is not None:
            varr = np.asarray(vertices.array)
            kwargs["vertices"] = varr.tolist()
            kwargs["cell2d"] = np.asarray(cell2d.array).tolist()
            nvert = getattr(src, "nvert", None)
            kwargs["nvert"] = (
                int(nvert.data)
                if nvert is not None and getattr(nvert, "data", None) is not None
                else len(varr)
            )
    grid_cls(dst_model, **kwargs)
    return kind.upper()


def _impl_add_component_model(model: str, component: str, grid_from: str = "gwf") -> dict:
    """Add a coupled component model with the source grid mirrored + exchange.

    Internal foundation helper: the GWE/PRT specs expose user-facing tools
    that call it. No physics packages are added here.
    """
    key = component.lower()
    spec = spec_for(key)
    if key == "gwf":
        raise ValueError(
            "component='gwf' is the flow model created by create_model — use a "
            "different component (e.g. 'gwe', 'prt')."
        )
    sim = get_sim(model)
    if key in component_map(model):
        raise ValueError(f"Simulation '{model}' already has a '{key}' component.")

    src_model = get_model(model, grid_from)
    gwf_model = get_model(model, "gwf")

    comp_name = _component_model_name(model, key, set(sim.model_names))
    dst_model = spec.model_class(
        sim, modelname=comp_name, model_nam_file=f"{comp_name}.nam"
    )
    exchange = None
    try:
        grid_type = _mirror_grid(src_model, dst_model, key)
        if spec.exchange_class is not None:
            spec.exchange_class(
                sim, exgmnamea=getattr(gwf_model, "name", model), exgmnameb=comp_name
            )
            exchange = spec.exchange_class.__name__
    except Exception:
        # Never leave a half-built (package-less) model in the simulation.
        try:
            sim.remove_model(comp_name)
        except Exception:
            pass
        raise

    written = save_sim(model, sim)
    model_dir = resolve_workspace(model)
    meta = _read_meta(model_dir)
    meta.setdefault("components", {})[key] = comp_name
    _write_meta(model_dir, meta)

    return {
        "model": model,
        "component": key,
        "component_model": comp_name,
        "grid_type": grid_type,
        "exchange": exchange,
        "written": written,
    }


def _oc_filename(oc, attr: str, default: str) -> str:
    """Best-effort read of an OC filerecord name; falls back to *default*."""
    rec = getattr(oc, attr, None)
    if rec is None:
        return default
    try:
        data = rec.get_data()
    except Exception:
        return default
    try:
        first = data[0]
        if isinstance(first, str):
            value = first
        else:
            value = first[0]
        return str(value) if value else default
    except Exception:
        return default


def _flow_output_filenames(gwf) -> tuple[str, str]:
    oc = gwf.get_package("oc")
    name = gwf.name
    if oc is None:
        return f"{name}.hds", f"{name}.cbc"
    return (
        _oc_filename(oc, "head_filerecord", f"{name}.hds"),
        _oc_filename(oc, "budget_filerecord", f"{name}.cbc"),
    )


def _mirror_flow_tdis(flow_sim) -> dict:
    """Copy the flow TDIS timing (period data, units, start date) for the heat run."""
    tdis = getattr(flow_sim, "tdis", None)
    if tdis is None:
        try:
            tdis = flow_sim.get_package("tdis")
        except Exception:
            tdis = None
    if tdis is None:
        return {"perioddata": [(1.0, 1, 1.0)]}
    out: dict = {"perioddata": [(1.0, 1, 1.0)]}
    try:
        data = tdis.perioddata.get_data()
        out["perioddata"] = [(float(r[0]), int(r[1]), float(r[2])) for r in data]
    except Exception:
        pass
    for attr in ("time_units", "start_date_time"):
        item = getattr(tdis, attr, None)
        if item is not None:
            try:
                value = item.data
                if value:
                    out[attr] = str(value)
            except Exception:
                pass
    return out


def _ensure_flow_saving_for_fmi(gwf, model: str) -> None:
    """Make the flow model save what a GWE FMI run needs.

    FMI advection reads the flow model's specific discharge and saturation, so
    NPF must have ``save_specific_discharge``/``save_saturation`` (and flows)
    enabled; every boundary package must save its flows too so the aux-based
    SSM terms reach the budget. The flags are set **in place** on the existing
    NPF (never rebuilt, so no other NPF setting is lost). A ``gwe_flow_saving``
    meta flag lets a later ``add_npf_package`` re-apply the flags.
    """
    npf = gwf.get_package("npf")
    if npf is not None:
        for attr in ("save_flows", "save_specific_discharge", "save_saturation"):
            try:
                setattr(npf, attr, True)
            except Exception:
                pass
    for pname in gwf.get_package_list():
        pkg = gwf.get_package(pname)
        if pkg is not None and hasattr(pkg, "save_flows"):
            try:
                pkg.save_flows = True
            except Exception:
                pass
    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    meta["gwe_flow_saving"] = True
    _write_meta(ws, meta)


def _impl_add_gwe_model(
    model: str,
    flow_model: str | None = None,
    perioddata: list | None = None,
    time_units: str | None = None,
) -> dict:
    """Create a derived GWE heat simulation coupled to a flow run via FMI.

    The heat model lives in ``<workspace>/gwe/`` and reads the flow run's head
    and budget files through ``ModflowGwefmi``. Run the flow model first, then
    the heat model. Packages are added with the ``add_gwe_*`` tools. Omit
    ``perioddata`` to mirror the flow TDIS (including its time units).
    """
    key = "gwe"
    if flow_model is not None and flow_model != model:
        raise ValueError(
            "flow_model must be the same registered model; the derived heat "
            "simulation is built inside this model's workspace."
        )
    flow_name = model
    if is_readonly(model):
        raise ModelReadOnlyError(
            f"Model '{model}' was registered with adopt_model and is read-only; "
            "add_gwe_model cannot modify its flow input set."
        )
    flow_sim = get_sim(flow_name)
    gwf = get_model(flow_name, "gwf")
    ws = resolve_workspace(model)
    if key in component_map(model):
        raise ValueError(f"Simulation '{model}' already has a '{key}' component.")

    mirror = _mirror_flow_tdis(flow_sim)
    pd = perioddata if perioddata is not None else mirror["perioddata"]
    tu = time_units if time_units is not None else mirror.get("time_units")

    heat_ws = ws / "gwe"
    heat_ws.mkdir(parents=True, exist_ok=True)
    comp_name = _component_model_name(model, key, set(flow_sim.model_names))

    hsim = mf6.MFSimulation(sim_name=f"{model}_gwe", version="mf6", sim_ws=str(heat_ws))
    tdis_kwargs: dict = {"nper": len(pd), "perioddata": pd}
    if tu is not None:
        tdis_kwargs["time_units"] = tu
    if mirror.get("start_date_time"):
        tdis_kwargs["start_date_time"] = mirror["start_date_time"]
    mf6.ModflowTdis(hsim, **tdis_kwargs)
    # GWE matrices are asymmetric — the solver must use BICGSTAB.
    mf6.ModflowIms(hsim, complexity="SIMPLE", linear_acceleration="BICGSTAB")
    gwe = mf6.ModflowGwe(hsim, modelname=comp_name, model_nam_file=f"{comp_name}.nam")

    hds, cbc = _flow_output_filenames(gwf)
    mf6.ModflowGwefmi(
        gwe,
        packagedata=[("GWFHEAD", f"../{hds}", None), ("GWFBUDGET", f"../{cbc}", None)],
    )

    _ensure_flow_saving_for_fmi(gwf, flow_name)
    cache_component_sim(model, key, hsim)
    meta = _read_meta(ws)
    meta.setdefault("components", {})[key] = {"model": comp_name, "workspace": "gwe"}
    _write_meta(ws, meta)
    written = save_sim(model, flow_sim)
    return {
        "model": model,
        "component": key,
        "component_model": comp_name,
        "workspace": str(heat_ws),
        "written": written,
    }


def _ensure_flow_saving_for_prt(model: str) -> None:
    """Ensure the GWF model exposes what the GWF-PRT exchange needs.

    The flags are set **in place** on the existing NPF (never rebuilt, so no
    other NPF setting is lost). A ``prt_flow_saving`` meta flag lets a later
    ``add_npf_package`` re-apply the flags after it rebuilds NPF — otherwise the
    required PRT exchange flow-saving flags would be silently dropped.
    """
    gwf = get_model(model, "gwf")
    npf = gwf.get_package("npf")
    if npf is not None:
        for attr, value in (("save_flows", True), ("save_specific_discharge", True)):
            try:
                setattr(npf, attr, value)
            except Exception:
                pass
    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    meta["prt_flow_saving"] = True
    _write_meta(ws, meta)


def _impl_add_prt_model(model: str) -> dict:
    """Add a same-simulation PRT model with the flow grid mirrored + exchange."""
    _require_writable(model, "add_prt_model")
    key = "prt"
    if key in component_map(model):
        raise ValueError(f"Simulation '{model}' already has a '{key}' component.")

    _ensure_flow_saving_for_prt(model)
    out = _impl_add_component_model(model, key)

    # PRT is an explicit model: solve it with an EMS listed after the GWF IMS.
    # An IMS makes prt_solve return early and the track file stays header-only.
    sim = get_sim(model)
    ems_name = f"{out['component_model']}.ems"
    ems = mf6.ModflowEms(sim, pname=f"{out['component_model']}_ems", filename=ems_name)
    sim.register_solution_package(ems, [out["component_model"]])
    out["solution"] = ems_name
    out["written"] = save_sim(model, sim)
    return out


def _impl_add_prt_mip_package(
    model: str, porosity, retfactor: float = 1.0, izone=None, save_flows: bool = False
) -> dict:
    """Add the PRT matrix-input (MIP) package: porosity and retardation."""
    _require_writable(model, "add_prt_mip_package")
    prt = get_model(model, "prt")
    pkg = prt.get_package("mip")
    if pkg is not None:
        prt.remove_package(pkg)
    kwargs: dict = {"porosity": porosity, "retfactor": retfactor}
    if izone is not None:
        kwargs["izone"] = izone
    mf6.ModflowPrtmip(prt, **kwargs)
    return {"model": model, "package": "MIP", "written": save_sim(model, prt.simulation)}


def _impl_add_prt_prp_package(
    model: str,
    release_points: list,
    perioddata: list | None = None,
    release_times: list | None = None,
    save_flows: bool = False,
) -> dict:
    """Add the PRT particle-release (PRP) package.

    ``release_points`` is ``[(irptno, cellid, xrpt, yrpt, zrpt[, boundname])]``
    with 0-based ``irptno`` (flopy writes the 1-based MF6 value). ``perioddata``
    is the per-period release setting, e.g. ``[["first"]]``. ``save_flows`` is
    accepted for interface parity with the other PRT builders and ignored: PRP
    has no budget, so it is not a valid MF6 option.
    """
    _require_writable(model, "add_prt_prp_package")
    prt = get_model(model, "prt")
    pkg = prt.get_package("prp")
    if pkg is not None:
        prt.remove_package(pkg)
    kwargs: dict = {
        "nreleasepts": len(release_points),
        "packagedata": release_points,
    }
    if perioddata is not None:
        kwargs["perioddata"] = perioddata
    if release_times is not None:
        kwargs["releasetimes"] = release_times
    mf6.ModflowPrtprp(prt, **kwargs)
    return {
        "model": model,
        "package": "PRP",
        "file": f"{prt.name}.prp",
        "written": save_sim(model, prt.simulation),
    }


def _impl_add_prt_oc_package(
    model: str,
    track_filerecord: str | None = None,
    trackcsv_filerecord: str | None = None,
    track_release: bool = True,
    track_timestep: bool = True,
    track_terminate: bool = True,
    track_exit: bool = False,
    budget_filerecord: str | None = None,
) -> dict:
    """Add the PRT output-control (OC) package with tracking output.

    Declare the track file here (not on the PRP) — MF6 aborts if the same file
    is declared twice.
    """
    _require_writable(model, "add_prt_oc_package")
    prt = get_model(model, "prt")
    pkg = prt.get_package("oc")
    if pkg is not None:
        prt.remove_package(pkg)
    kwargs: dict = {}
    if trackcsv_filerecord:
        kwargs["trackcsv_filerecord"] = trackcsv_filerecord
    if track_filerecord:
        kwargs["track_filerecord"] = track_filerecord
    if budget_filerecord:
        kwargs["budget_filerecord"] = budget_filerecord
    if track_release:
        kwargs["track_release"] = True
    if track_timestep:
        kwargs["track_timestep"] = True
    if track_terminate:
        kwargs["track_terminate"] = True
    if track_exit:
        kwargs["track_exit"] = True
    mf6.ModflowPrtoc(prt, **kwargs)
    return {
        "model": model,
        "package": "OC",
        "model_name": prt.name,
        "written": save_sim(model, prt.simulation),
    }


def _require_writable(model: str, tool: str) -> None:
    """Refuse a builder mutation on an adopt_model read-only model."""
    if is_readonly(model):
        raise ModelReadOnlyError(
            f"Model '{model}' was registered with adopt_model and is read-only; "
            f"{tool} cannot modify its input set."
        )


def _impl_add_gwe_adv_package(model: str, scheme: str = "TVD") -> dict:
    """Add the GWE advection package (transport scheme)."""
    _require_writable(model, "add_gwe_adv_package")
    gwe = get_model(model, "gwe")
    pkg = gwe.get_package("adv")
    if pkg is not None:
        gwe.remove_package(pkg)
    mf6.ModflowGweadv(gwe, scheme=scheme)
    return {"model": model, "package": "ADV", "scheme": scheme,
            "written": save_sim(model, gwe.simulation)}


def _impl_add_gwe_cnd_package(
    model: str,
    alh: float | list | None = None,
    ath1: float | list | None = None,
    ath2: float | list | None = None,
    alv: float | list | None = None,
    atv: float | list | None = None,
    ktw: float | list | None = None,
    kts: float | list | None = None,
) -> dict:
    """Add the GWE conduction/dispersion package."""
    _require_writable(model, "add_gwe_cnd_package")
    gwe = get_model(model, "gwe")
    pkg = gwe.get_package("cnd")
    if pkg is not None:
        gwe.remove_package(pkg)
    kwargs: dict = {}
    for name, value in (
        ("alh", alh), ("ath1", ath1), ("ath2", ath2), ("alv", alv),
        ("atv", atv), ("ktw", ktw), ("kts", kts),
    ):
        if value is not None:
            kwargs[name] = value
    mf6.ModflowGwecnd(gwe, **kwargs)
    return {"model": model, "package": "CND", "written": save_sim(model, gwe.simulation)}


def _impl_add_gwe_est_package(
    model: str,
    porosity: float | list,
    heat_capacity_water: float | None = None,
    density_water: float | None = None,
    heat_capacity_solid: float | list | None = None,
    density_solid: float | list | None = None,
    latent_heat_vaporization: float | None = None,
    save_flows: bool = False,
) -> dict:
    """Add the GWE energy storage and transfer package."""
    _require_writable(model, "add_gwe_est_package")
    gwe = get_model(model, "gwe")
    pkg = gwe.get_package("est")
    if pkg is not None:
        gwe.remove_package(pkg)
    kwargs: dict = {"porosity": porosity}
    for name, value in (
        ("heat_capacity_water", heat_capacity_water), ("density_water", density_water),
        ("heat_capacity_solid", heat_capacity_solid), ("density_solid", density_solid),
        ("latent_heat_vaporization", latent_heat_vaporization), ("save_flows", save_flows),
    ):
        if value is not None:
            kwargs[name] = value
    mf6.ModflowGweest(gwe, **kwargs)
    return {"model": model, "package": "EST", "written": save_sim(model, gwe.simulation)}


def _impl_add_gwe_ssm_package(model: str, sources: list | None = None) -> dict:
    """Add the GWE source-sink mixing package (required when the flow model has
    boundary packages). ``sources`` is [(pname, srctype, auxname)]."""
    _require_writable(model, "add_gwe_ssm_package")
    gwe = get_model(model, "gwe")
    kwargs: dict = {}
    if sources:
        flow = get_model(model, "gwf")
        available = {str(p).lower() for p in flow.get_package_list()}
        for src in sources:
            pname = str(src[0]).lower()
            if pname not in available:
                raise ValueError(
                    f"SSM source package '{src[0]}' is not a package on the flow "
                    f"model. Available: {sorted(flow.get_package_list())}."
                )
        kwargs["sources"] = sources
    # Validate before removing so a rejected call cannot silently drop a
    # previously configured SSM from the in-memory model.
    pkg = gwe.get_package("ssm")
    if pkg is not None:
        gwe.remove_package(pkg)
    mf6.ModflowGwessm(gwe, **kwargs)
    return {"model": model, "package": "SSM", "written": save_sim(model, gwe.simulation)}


def _impl_add_gwe_esl_package(
    model: str, stress_period_data: dict, save_flows: bool = False
) -> dict:
    """Add the GWE energy source loading (ESL) package."""
    _require_writable(model, "add_gwe_esl_package")
    gwe = get_model(model, "gwe")
    pkg = gwe.get_package("esl")
    if pkg is not None:
        gwe.remove_package(pkg)
    spd = {int(k): v for k, v in stress_period_data.items()}
    mf6.ModflowGweesl(gwe, stress_period_data=spd, save_flows=save_flows)
    return {"model": model, "package": "ESL", "written": save_sim(model, gwe.simulation)}


def _impl_set_simulation(
    model: str,
    nper: int,
    perlen: list[float],
    nstp: list[int],
    ims_complexity: str,
    start_date_time: str | None = None,
    newton: bool | None = None,
    linear_acceleration: str | None = None,
    outer_maximum: int | None = None,
    under_relaxation: str | None = None,
) -> dict:
    if len(perlen) != nper or len(nstp) != nper:
        raise ValueError(f"len(perlen) and len(nstp) must equal nper={nper}.")
    if start_date_time is not None:
        start_date_time = str(start_date_time).strip()
        if not start_date_time:
            raise ValueError("start_date_time must be a non-empty ISO-8601 string.")
    if outer_maximum is not None:
        outer_maximum = int(outer_maximum)
        if outer_maximum <= 0:
            raise ValueError("outer_maximum must be a positive integer.")

    sim = get_sim(model)
    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    time_units = meta.get("time_units", "DAYS")

    # Remove existing TDIS/IMS if present (allow reconfiguration)
    for pname in ("tdis", "ims"):
        pkg = sim.get_package(pname)
        if pkg is not None:
            sim.remove_package(pkg)

    perioddata = [(float(perlen[i]), int(nstp[i]), 1.0) for i in range(nper)]
    tdis_kwargs: dict = {
        "pname": "tdis",
        "time_units": time_units,
        "nper": nper,
        "perioddata": perioddata,
    }
    # A start date makes the model's elapsed times convertible to calendar
    # dates — required for the CSUB derived-observation time axis (Critical 1).
    if start_date_time is not None:
        tdis_kwargs["start_date_time"] = start_date_time
    mf6.ModflowTdis(sim, **tdis_kwargs)

    ims_kwargs: dict = {"pname": "ims", "complexity": ims_complexity.upper()}
    if linear_acceleration is not None:
        ims_kwargs["linear_acceleration"] = str(linear_acceleration)
    if outer_maximum is not None:
        ims_kwargs["outer_maximum"] = outer_maximum
    if under_relaxation is not None:
        # MF6 IMS UNDER_RELAXATION is a keyword string ("simple"/"complex"),
        # not a boolean flag.
        ims_kwargs["under_relaxation"] = str(under_relaxation)
    ims = mf6.ModflowIms(sim, **ims_kwargs)
    sim.register_ims_package(ims, list(sim.model_names))

    # Newton-Raphson option on the GWF model. The CSUB delay solve needs it
    # (Critical 2); setting it after construction matches how the property is
    # serialised and keeps ``newtonoptions`` absent when not requested.
    if newton is not None:
        gwf = get_gwf(model)
        gwf.newtonoptions.set_data(["NEWTON"] if newton else None)

    # Keep meta consistent with the TDIS actually written: a reconfiguration
    # without a start date clears the stale value.
    if start_date_time is not None:
        meta["start_date_time"] = start_date_time
    else:
        meta.pop("start_date_time", None)
    _write_meta(ws, meta)

    written = save_sim(model, sim)
    return {
        "model": model,
        "nper": nper,
        "time_units": time_units,
        "ims_complexity": ims_complexity.upper(),
        "start_date_time": start_date_time,
        "newton": newton,
        "linear_acceleration": ims_kwargs.get("linear_acceleration"),
        "outer_maximum": ims_kwargs.get("outer_maximum"),
        "under_relaxation": ims_kwargs.get("under_relaxation"),
        "total_time": sum(perlen),
        "written": written,
    }


def _impl_set_model_crs(
    model: str,
    crs: str,
    xorigin: float | None = None,
    yorigin: float | None = None,
    angrot: float | None = None,
    component: str = "gwf",
) -> dict:
    """Set the coordinate reference system and offsets on the model grid.

    A grid built with ``add_dis_package`` / ``add_disv_package`` has no CRS
    until this is called — every downstream spatial tool (assign_top_from_raster,
    assign_k_from_zones, import_river_from_shapefile) needs a CRS to compare
    coordinates, and without one those calls fail loudly (CRS_UNKNOWN) rather
    than guessing. ``crs`` accepts anything rasterio accepts (e.g. "EPSG:32718"
    or a WKT string). ``xorigin``/``yorigin`` are the lower-left corner of the
    grid; ``angrot`` the rotation in degrees (default 0).
    """
    gwf = get_model(model, component)
    angrot = angrot if angrot is not None else 0.0
    gwf.modelgrid.set_coord_info(xoff=xorigin, yoff=yorigin, angrot=angrot, crs=crs)

    dis_pkg = get_dis(gwf)
    if dis_pkg is not None:
        if xorigin is not None:
            dis_pkg.xorigin.set_data(xorigin)
        if yorigin is not None:
            dis_pkg.yorigin.set_data(yorigin)
    disv_pkg = get_disv(gwf)
    if disv_pkg is not None:
        if xorigin is not None:
            disv_pkg.xorigin.set_data(xorigin)
        if yorigin is not None:
            disv_pkg.yorigin.set_data(yorigin)

    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    meta["crs"] = str(crs)
    if xorigin is not None:
        meta["xorigin"] = float(xorigin)
    if yorigin is not None:
        meta["yorigin"] = float(yorigin)
    _write_meta(ws, meta)

    written = save_sim(model, gwf.simulation)
    return {
        "model": model,
        "crs": str(crs),
        "xorigin": xorigin,
        "yorigin": yorigin,
        "angrot": angrot,
        "written": written,
    }


def _impl_add_dis_package(
    model: str,
    nlay: int,
    nrow: int,
    ncol: int,
    delr: float | list,
    delc: float | list,
    top: float | list,
    botm: list,
    idomain: int | list | None = None,
    component: str = "gwf",
) -> dict:
    if len(botm) != nlay:
        raise ValueError(f"len(botm)={len(botm)} must equal nlay={nlay}.")

    gwf = get_model(model, component)
    _remove_grid_packages(gwf, component, ("dis", "disv"))

    dis_kwargs: dict = {
        "nlay": nlay,
        "nrow": nrow,
        "ncol": ncol,
        "delr": delr,
        "delc": delc,
        "top": top,
        "botm": botm,
    }
    if idomain is not None:
        dis_kwargs["idomain"] = idomain
    dis_cls = grid_class_for(component, "dis")
    if dis_cls is None:
        raise ValueError(f"Component '{component}' has no DIS grid class.")
    dis_cls(gwf, **dis_kwargs)
    written = save_sim(model, gwf.simulation)
    return {
        "model": model,
        "grid_type": "DIS",
        "nlay": nlay,
        "nrow": nrow,
        "ncol": ncol,
        "ncells": nlay * nrow * ncol,
        "written": written,
    }


def _impl_add_disv_package(
    model: str,
    nlay: int,
    vertices: list,
    cell2d: list,
    top: list,
    botm: list,
    gridprops_file: str | None = None,
    component: str = "gwf",
) -> dict:
    # Inline cell2d payloads are impractical beyond a size guard; accept a
    # gridprops file (JSON) instead (7f-I4).
    if gridprops_file is not None:
        import json as _json

        props = _json.loads(Path(gridprops_file).read_text())
        vertices = props["vertices"]
        cell2d = props["cell2d"]
        top = props.get("top", top)
        botm = props.get("botm", botm)
        nlay = int(props.get("nlay", nlay))

    ncpl = len(cell2d)
    if ncpl > _DISV_INLINE_CELL_LIMIT:
        raise PayloadTooLargeError(
            f"{ncpl} inline cell2d entries exceeds the {_DISV_INLINE_CELL_LIMIT} "
            "cell limit for inline payloads. Use import_grid_from_shapefile "
            "(method='disv') or pass gridprops_file (a JSON file with "
            "vertices/cell2d/top/botm) instead."
        )
    nvert = len(vertices)
    if len(botm) != nlay:
        raise ValueError(f"len(botm)={len(botm)} must equal nlay={nlay}.")

    gwf = get_model(model, component)
    _remove_grid_packages(gwf, component, ("dis", "disv"))

    disv_cls = grid_class_for(component, "disv")
    if disv_cls is None:
        raise ValueError(f"Component '{component}' has no DISV grid class.")
    disv_cls(
        gwf,
        nlay=nlay,
        ncpl=ncpl,
        nvert=nvert,
        vertices=vertices,
        cell2d=cell2d,
        top=top,
        botm=botm,
    )
    written = save_sim(model, gwf.simulation)
    return {
        "model": model,
        "grid_type": "DISV",
        "nlay": nlay,
        "ncpl": ncpl,
        "nvert": nvert,
        "ncells": nlay * ncpl,
        "written": written,
    }


def _impl_add_disu_package(
    model: str,
    nodes: int,
    nja: int,
    top,
    bot,
    area=None,
    iac=None,
    ja=None,
    ihc=None,
    cl12=None,
    hwva=None,
    angldegx=None,
    idomain=None,
    vertices=None,
    cell2d=None,
    nvert: int | None = None,
    gridprops_file: str | None = None,
    component: str = "gwf",
) -> dict:
    """Add a fully-unstructured (DISU) grid from explicit node connectivity.

    DISU is defined by NODES/NJA plus connection data (IAC/JA, optional
    IHC/CL12/HWVA/ANGLDEGX). The per-node TOP/BOT arrays are required; AREA
    defaults to 1.0. A ``gridprops_file`` (JSON) may carry any of these keys.
    Optional ``vertices``/``cell2d`` (with ``nvert``) provide cell x/y geometry
    so coordinate-based operations and plan-view plots work.
    """
    if gridprops_file is not None:
        import json as _json

        props = _json.loads(Path(gridprops_file).read_text())
        nodes = int(props.get("nodes", nodes))
        nja = int(props.get("nja", nja))
        top = props.get("top", top)
        bot = props.get("bot", bot)
        area = props.get("area", area)
        iac = props.get("iac", iac)
        ja = props.get("ja", ja)
        ihc = props.get("ihc", ihc)
        cl12 = props.get("cl12", cl12)
        hwva = props.get("hwva", hwva)
        angldegx = props.get("angldegx", angldegx)
        idomain = props.get("idomain", idomain)
        vertices = props.get("vertices", vertices)
        cell2d = props.get("cell2d", cell2d)
        nvert = props.get("nvert", nvert)

    nodes = int(nodes)
    nja = int(nja)
    if iac is None or ja is None:
        raise ValueError(
            "DISU requires connection data: pass 'iac' and 'ja' (or a "
            "gridprops_file containing them)."
        )
    if area is None:
        area = [1.0] * nodes
    # FloPy needs IHC+IAC to derive the modelgrid's layer structure; for a
    # single-layer DISU every connection is horizontal (IHC=1).
    if ihc is None:
        ihc = [1] * nja
    # MF6 requires symmetric CL12/HWVA; when the caller does not supply real
    # geometry, placeholder unit values keep the model runnable.
    if cl12 is None:
        cl12 = [1.0] * nja
    if hwva is None:
        hwva = [1.0] * nja
    if len(top) != nodes or len(bot) != nodes or len(area) != nodes:
        raise ValueError(
            f"len(top)={len(top)}, len(bot)={len(bot)}, len(area)={len(area)} "
            f"must each equal nodes={nodes}."
        )
    if len(iac) != nodes:
        raise ValueError(f"len(iac)={len(iac)} must equal nodes={nodes}.")
    if len(ja) != nja:
        raise ValueError(f"len(ja)={len(ja)} must equal nja={nja}.")
    if ihc is not None and len(ihc) != nja:
        raise ValueError(f"len(ihc)={len(ihc)} must equal nja={nja}.")
    if cl12 is not None and len(cl12) != nja:
        raise ValueError(f"len(cl12)={len(cl12)} must equal nja={nja}.")
    if hwva is not None and len(hwva) != nja:
        raise ValueError(f"len(hwva)={len(hwva)} must equal nja={nja}.")

    gwf = get_model(model, component)
    _remove_grid_packages(gwf, component, ("dis", "disv", "disu"))

    kwargs: dict = {
        "nodes": nodes,
        "nja": nja,
        "top": top,
        "bot": bot,
        "area": area,
        "iac": iac,
        "ja": ja,
    }
    if ihc is not None:
        kwargs["ihc"] = ihc
    if cl12 is not None:
        kwargs["cl12"] = cl12
    if hwva is not None:
        kwargs["hwva"] = hwva
    if angldegx is not None:
        kwargs["angldegx"] = angldegx
    if idomain is not None:
        kwargs["idomain"] = idomain
    if vertices is not None:
        kwargs["nvert"] = int(nvert) if nvert is not None else len(vertices)
        kwargs["vertices"] = vertices
    elif nvert is not None:
        kwargs["nvert"] = int(nvert)
    if cell2d is not None:
        kwargs["cell2d"] = cell2d
    disu_cls = grid_class_for(component, "disu")
    if disu_cls is None:
        raise ValueError(f"Component '{component}' has no DISU grid class.")
    disu_cls(gwf, **kwargs)
    written = save_sim(model, gwf.simulation)
    return {
        "model": model,
        "grid_type": "DISU",
        "nodes": nodes,
        "nja": nja,
        "ncells": nodes,
        "written": written,
    }


def _impl_add_npf_package(
    model: str,
    icelltype: int | list,
    k: float | list,
    k33: float | list | None,
    save_flows: bool,
    k_units: str = "m/d",
) -> dict:
    gwf = get_gwf(model)
    pkg = gwf.get_package("npf")
    if pkg is not None:
        gwf.remove_package(pkg)

    # Dimensional arguments carry units (7f-H1.1): convert k/k33 into the
    # model's length/time convention and record the declared units.
    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    time_units = meta.get("time_units", "DAYS")
    length_units = meta.get("units", "METERS")
    k_converted = _convert_k_to_model(k, k_units, time_units, length_units)
    kwargs: dict = {"icelltype": icelltype, "k": k_converted, "save_flows": save_flows}
    if k33 is not None:
        kwargs["k33"] = _convert_k_to_model(k33, k_units, time_units, length_units)
    meta.setdefault("declared_units", {})["k"] = k_units
    if meta.get("gwe_flow_saving"):
        # A GWE heat model needs specific discharge/saturation saved by NPF.
        kwargs["save_specific_discharge"] = True
        kwargs["save_saturation"] = True
        kwargs["save_flows"] = True
    if meta.get("prt_flow_saving"):
        # A same-simulation GWF-PRT exchange needs the flow budget and specific
        # discharge, and the flags must survive this NPF rebuild.
        kwargs["save_flows"] = True
        kwargs["save_specific_discharge"] = True
    _write_meta(ws, meta)

    mf6.ModflowGwfnpf(gwf, **kwargs)
    written = save_sim(model, gwf.simulation)
    clear_k_base_snapshot(model, gwf.name)
    return {
        "model": model,
        "package": "NPF",
        "save_flows": save_flows,
        "written": written,
        "k_units": k_units,
    }


def _impl_add_ic_package(model: str, strt: float | list, component: str = "gwf") -> dict:
    gwf = get_model(model, component)
    pkg = gwf.get_package("ic")
    if pkg is not None:
        gwf.remove_package(pkg)

    ic_cls = spec_for(component).ic_class
    if ic_cls is None:
        raise ValueError(f"Component '{component}' has no IC package class.")
    ic_cls(gwf, strt=strt)
    written = save_sim(model, gwf.simulation)
    return {"model": model, "package": "IC", "written": written}


def _impl_add_sto_package(
    model: str,
    iconvert: int | list,
    ss: float | list,
    sy: float | list | None,
    steady_state: list[int] | None,
    save_flows: bool,
) -> dict:
    """Add a Storage (STO) package.

    Required for transient simulations. ``steady_state`` holds the 0-based
    stress-period indices (matching set_simulation) that are steady-state;
    every other period is transient. Default ``[0]`` → first period steady,
    the rest transient (nper=1 stays fully steady). ``sy`` (specific yield)
    is required when any cell is convertible (iconvert>0).
    """
    gwf = get_gwf(model)
    sim = get_sim(model)

    tdis = sim.get_package("tdis")
    if tdis is None:
        raise ValueError(
            "set_simulation must be called before add_sto_package so the "
            "stress-period count is known."
        )
    nper = int(tdis.nper.array)

    if steady_state is None:
        steady_state = [0]
    else:
        steady_state = sorted(int(i) for i in steady_state)
        for i in steady_state:
            if not (0 <= i < nper):
                raise ValueError(
                    f"steady_state period index {i} out of range for nper={nper}. "
                    "Use 0-based indices matching set_simulation."
                )

    if sy is None:
        iconvert_arr = np.asarray(iconvert, dtype=int)
        has_convertible = (
            int(iconvert_arr) > 0
            if iconvert_arr.ndim == 0
            else bool((iconvert_arr > 0).any())
        )
        if has_convertible:
            raise ValueError(
                "sy (specific yield) is required because iconvert contains at "
                "least one convertible cell (iconvert>0)."
            )

    pkg = gwf.get_package("sto")
    replaced = pkg is not None
    if pkg is not None:
        gwf.remove_package(pkg)

    sto_kwargs: dict = {"iconvert": iconvert, "ss": ss, "save_flows": save_flows}
    if sy is not None:
        sto_kwargs["sy"] = sy
    if steady_state:
        sto_kwargs["steady_state"] = {i: True for i in steady_state}
    transient_start = (max(steady_state) + 1) if steady_state else 0
    if transient_start < nper:
        sto_kwargs["transient"] = {transient_start: True}

    mf6.ModflowGwfsto(gwf, **sto_kwargs)
    written = save_sim(model, sim)

    transient_periods = [i for i in range(nper) if i not in set(steady_state)]
    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    meta["sto_steady_state"] = steady_state
    meta["sto_transient"] = transient_periods
    _write_meta(ws, meta)

    result: dict = {
        "model": model,
        "package": "STO",
        "steady_state_periods": steady_state,
        "transient_periods": transient_periods,
        "save_flows": save_flows,
        "written": written,
    }
    if replaced:
        result["warning"] = "A previous STO package was removed and replaced by this call."
    return result


# ---------------------------------------------------------------------------
# CSUB (subsidence)
# ---------------------------------------------------------------------------

# FloPy's ``ModflowGwfcsub._package_type`` is ``"csub"`` (the MF6 name-file
# type is ``CSUB6``). ``_packages_of_type`` matches on flopy's ``package_type``,
# so ``"csub"`` is the value that actually finds an existing package.
_CSUB_PKG_TYPE = "csub"

# Canonical MF6 CSUB cell-observation type names.
_CSUB_OBS_TYPES = {
    "compaction-cell",
    "preconstress-cell",
    "elastic-compaction-cell",
    "inelastic-compaction-cell",
}
# The four cell types may also be given without the ``-cell`` suffix.
_CSUB_OBS_TYPE_ALIASES = {
    "compaction": "compaction-cell",
    "preconstress": "preconstress-cell",
    "elastic-compaction": "elastic-compaction-cell",
    "inelastic-compaction": "inelastic-compaction-cell",
}
# Interbed observations take a 0-based interbed number (and, for the delay
# types, an optional delay-cell index).
_CSUB_INTERBED_OBS_TYPES = {
    "interbed-compaction-pct",
    "delay-preconstress",
    "delay-head",
}
_CSUB_FILERECORDS = {
    "zdisplacement": "zdisplacement_filerecord",
    "package_convergence": "package_convergence_filerecord",
    "strainib": "strainib_filerecord",
    "compaction": "compaction_filerecord",
}


def _normalise_csub_packagedata(packagedata, nlay: int) -> list:
    """Validate CSUB packagedata records and return them as lists.

    A record is ``[icsubno, cellid, cdelay, pcs0, thick_frac, rnb, ssv_cc,
    sse_cr, theta, kv, h0]``. ``icsubno`` must be contiguous from 0 (the file
    is renumbered to 1-based by flopy on write). ``pcs0`` is deliberately not
    validated: the holdout sets ``pcs0=0.0`` whenever
    ``initial_preconsolidation_head=True``.
    """
    recs = []
    for i, rec in enumerate(packagedata):
        rec = list(rec)
        if len(rec) != 11:
            raise ValueError(
                f"packagedata record {i} has {len(rec)} fields, expected 11 "
                "(icsubno, cellid, cdelay, pcs0, thick_frac, rnb, ssv_cc, "
                "sse_cr, theta, kv, h0)."
            )
        icsubno, cellid, cdelay, _pcs0, thick_frac, rnb, _ssv_cc, _sse_cr, \
            theta, _kv, _h0 = rec
        if int(icsubno) != i:
            raise ValueError(
                f"packagedata icsubno must be contiguous from 0 (record {i})."
            )
        cdelay = str(cdelay).lower()
        if cdelay not in ("delay", "nodelay"):
            raise ValueError(
                f"packagedata record {i}: cdelay must be 'delay' or 'nodelay'."
            )
        if isinstance(cellid, (list, tuple)):
            if not cellid:
                raise ValueError(f"packagedata record {i}: empty cellid.")
            layer = int(cellid[0])
            if not 0 <= layer < nlay:
                raise ValueError(
                    f"packagedata record {i}: layer {layer} outside 0..{nlay - 1}."
                )
        elif int(cellid) < 0:
            # DISU cell ids are a single node number.
            raise ValueError(f"packagedata record {i}: node id must be >= 0.")
        if float(thick_frac) <= 0.0:
            raise ValueError(f"packagedata record {i}: thick_frac must be > 0.")
        if float(rnb) < 1.0:
            raise ValueError(f"packagedata record {i}: rnb must be >= 1.")
        if not 0.0 < float(theta) < 1.0:
            raise ValueError(f"packagedata record {i}: theta must be in (0, 1).")
        recs.append(rec)
    return recs


def _per_layer_values(value, nlay: int, field: str) -> list:
    """Broadcast a scalar to ``nlay`` values, or validate an explicit list."""
    vals = list(value) if isinstance(value, (list, tuple)) else [value] * nlay
    if len(vals) != nlay:
        raise ValueError(f"{field} has {len(vals)} values, expected nlay={nlay}.")
    return vals


def _resolve_external_path(ws, filename) -> Path:
    """Resolve a possibly-relative external filename against a workspace."""
    path = Path(str(filename))
    return path if path.is_absolute() else Path(ws) / path


def _normalise_csub_observations(
    observations: dict, gwf_name: str
) -> tuple[dict, str, list]:
    """Validate CSUB observations into flopy's ``continuous`` structure.

    ``observations`` maps a CSV name to ``[(name, obs_type, index), ...]``. A
    CSV name that does not end in ``.csv`` is treated as a label and the default
    ``<gwf>.csub.obs.csv`` is used. Cell types take a cellid; interbed types
    take a 0-based interbed number (converted to MF6's 1-based ``icsubno``).
    """
    continuous: dict = {}
    obs_names: list[str] = []
    default_csv = f"{gwf_name}.csub.obs.csv"
    output_csv = default_csv
    accepted = sorted(_CSUB_OBS_TYPES | _CSUB_INTERBED_OBS_TYPES)
    for csv_name, records in observations.items():
        out_csv = str(csv_name)
        if not out_csv.lower().endswith(".csv"):
            out_csv = default_csv
        entries: list = []
        for record in records:
            if len(record) != 3:
                raise ValueError(
                    "each CSUB observation record must be "
                    "(name, obs_type, index)."
                )
            obs_name, obs_type, index = record
            obs_name = str(obs_name)
            obs_type = _CSUB_OBS_TYPE_ALIASES.get(str(obs_type), str(obs_type))
            if obs_type in _CSUB_OBS_TYPES:
                if not isinstance(index, (list, tuple)):
                    raise ValueError(
                        f"observation '{obs_name}': cell observation "
                        f"'{obs_type}' requires a cellid (layer, row, col) or "
                        "(layer, node)."
                    )
                entries.append((obs_name, obs_type, tuple(int(v) for v in index)))
            elif obs_type in _CSUB_INTERBED_OBS_TYPES:
                if isinstance(index, (list, tuple)):
                    idx = [int(v) for v in index]
                    if not idx:
                        raise ValueError(
                            f"observation '{obs_name}': empty interbed index."
                        )
                    # FloPy converts every tuple id element from 0-based to
                    # 1-based when it writes the OBS6 records (exactly as it does
                    # for a cellid), so the interbed — and the delay-cell index —
                    # are passed through 0-based and must NOT be pre-incremented
                    # here. Incrementing both wrote interbed i+2: a `delay-head` /
                    # `delay-preconstress` record then referenced a non-existent
                    # interbed, which built and started but crashed MF6 6.7.0 on
                    # the first transient step (6d Target 9 rerun-2).
                    entries.append((obs_name, obs_type, tuple(idx)))
                else:
                    # A scalar id is written verbatim by FloPy, so the 0-based ->
                    # 1-based icsubno conversion happens here instead.
                    entries.append((obs_name, obs_type, int(index) + 1))
            else:
                raise ValueError(
                    f"observation '{obs_name}': unknown obs_type '{obs_type}'. "
                    f"Accepted: {', '.join(accepted)}."
                )
            obs_names.append(obs_name)
        continuous[out_csv] = entries
        output_csv = out_csv
    return continuous, output_csv, obs_names


def _impl_add_csub_package(
    model: str,
    packagedata: list | dict,
    ninterbeds: int | None = None,
    sgm: float | list | None = None,
    sgs: float | list | None = None,
    cg_theta: float | list | None = None,
    cg_ske_cr: float | list | None = None,
    head_based: bool = False,
    initial_preconsolidation_head: bool = False,
    specified_initial_interbed_state: bool = False,
    update_material_properties: bool = False,
    ndelaycells: int | None = None,
    beta: float | None = None,
    gammaw: float | None = None,
    interbeddata: list | None = None,
    stress_period_data: dict | None = None,
    observations: dict | None = None,
    filerecords: dict | None = None,
    print_input: bool = True,
    save_flows: bool = True,
    pname: str | None = None,
) -> dict:
    """Add or replace the CSUB (subsidence) package on a GWF model.

    ``packagedata`` is a list of interbed records, a ``{"filename": ...}``
    dict referencing a pre-externalised file that must already exist (then
    ``ninterbeds`` is required), or ``{"filename": ..., "data": [...]}`` to
    externalise the records to that file (written immediately; ``ninterbeds``
    defaults to ``len(data)``). ``packagedata_filename`` is recorded in the
    meta/result only when the referenced file exists on disk. Per-layer
    arrays (``sgm``/``sgs``/``cg_theta``/``cg_ske_cr``) accept a scalar or one
    value per layer. ``ndelaycells`` is required when any interbed has
    ``cdelay="delay"`` — it is never defaulted silently.
    """
    gwf = get_gwf(model)
    sim = get_sim(model)
    nlay, _ = grid_size(gwf)
    ws = resolve_workspace(model)

    pkg_filename: str | None = None
    recs: list | None = None
    try:
        if isinstance(packagedata, dict):
            pkg_filename = packagedata.get("filename")
            if not pkg_filename:
                raise ValueError(
                    "packagedata dict must contain a 'filename' key."
                )
            data = packagedata.get("data")
            if data is not None:
                recs = _normalise_csub_packagedata(data, nlay)
        else:
            recs = _normalise_csub_packagedata(packagedata, nlay)

        if recs is not None:
            if ninterbeds is None:
                ninterbeds = len(recs)
            elif int(ninterbeds) != len(recs):
                raise ValueError(
                    f"ninterbeds={ninterbeds} does not match "
                    f"len(packagedata)={len(recs)}."
                )
        elif ninterbeds is None:
            raise ValueError(
                "ninterbeds is required when packagedata is given as "
                "{'filename': ...} without 'data'."
            )
        ninterbeds = int(ninterbeds)

        if pkg_filename is not None and recs is None:
            # A filename-only dict is a pre-externalised reference. flopy
            # writes OPEN/CLOSE but never creates the file, so a missing file
            # would leave the model unrunnable and the recorded provenance
            # false.
            if not _resolve_external_path(ws, pkg_filename).exists():
                raise ValueError(
                    f"packagedata {{'filename': '{pkg_filename}'}} does not "
                    "exist. Provide 'data' so the external file can be "
                    "written, or create the pre-externalised file first."
                )

        if ndelaycells is not None:
            ndelaycells = int(ndelaycells)
            if ndelaycells <= 0:
                raise ValueError("ndelaycells must be a positive integer.")
        has_delay = recs is not None and any(
            str(r[2]).lower() == "delay" for r in recs
        )
        if has_delay and ndelaycells is None:
            raise ValueError(
                "ndelaycells is required when any interbed has cdelay='delay'."
            )

        kw: dict = {}
        if print_input:
            kw["print_input"] = True
        if save_flows:
            kw["save_flows"] = True
        if head_based:
            kw["head_based"] = True
        if initial_preconsolidation_head:
            kw["initial_preconsolidation_head"] = True
        if specified_initial_interbed_state:
            kw["specified_initial_interbed_state"] = True
        if update_material_properties:
            kw["update_material_properties"] = True
        if ndelaycells is not None:
            kw["ndelaycells"] = ndelaycells
        # gammaw/beta are unit-system dependent. FloPy's defaults are SI, which
        # silently mis-scales the effective-stress terms of a FEET model, so
        # the default follows the model's length unit (6d Target 9 rerun-3).
        length_units = str(_read_meta(ws).get("units", "METERS")).upper()
        kw["beta"] = (
            float(beta)
            if beta is not None
            else _BETA_BY_UNIT.get(length_units, _BETA_BY_UNIT["METERS"])
        )
        kw["gammaw"] = (
            float(gammaw)
            if gammaw is not None
            else _GAMMAW_BY_UNIT.get(length_units, _GAMMAW_BY_UNIT["METERS"])
        )
        for field, value in (
            ("sgm", sgm),
            ("sgs", sgs),
            ("cg_theta", cg_theta),
            ("cg_ske_cr", cg_ske_cr),
        ):
            if value is not None:
                kw[field] = _per_layer_values(value, nlay, field)
        for key, target in (filerecords or {}).items():
            if key not in _CSUB_FILERECORDS:
                raise ValueError(
                    f"Unknown filerecord '{key}'. Accepted: "
                    f"{', '.join(sorted(_CSUB_FILERECORDS))}."
                )
            kw[_CSUB_FILERECORDS[key]] = target
        if stress_period_data is not None:
            kw["stress_period_data"] = stress_period_data
        if interbeddata is not None:
            raise ValueError(
                "interbeddata is not supported by flopy 3.10's CSUB6 dfn; "
                "specify the initial interbed state via packagedata (h0) "
                "and/or stress_period_data"
            )
        if pname:
            kw["pname"] = pname

        obs_continuous: dict | None = None
        obs_output_csv: str | None = None
        obs_names: list[str] = []
        if observations:
            obs_continuous, obs_output_csv, obs_names = _normalise_csub_observations(
                observations, gwf.name
            )
    except ValueError as exc:
        return _err("INVALID_INPUT", str(exc))

    # Replacement semantics (matching add_boundary_package): with an explicit
    # ``pname`` only that package is replaced; otherwise every CSUB package.
    existing = _packages_of_type(gwf, _CSUB_PKG_TYPE)
    if pname:
        targets = [p for p in existing if _pkg_nam_name(p).lower() == pname.lower()]
    else:
        targets = existing
    for pkg in targets:
        gwf.remove_package(pkg)
    replaced = bool(targets)

    if pkg_filename is not None:
        pkg = mf6.ModflowGwfcsub(gwf, ninterbeds=ninterbeds, **kw)
        if recs is not None:
            # Externalise: flopy writes the packagedata file immediately and
            # rewrites the block to OPEN/CLOSE. Existence is verified below
            # before the filename is recorded.
            pkg.packagedata.set_data(
                {"filename": pkg_filename, "data": recs}
            )
        else:
            # Pre-externalised file (existence checked above): reference it
            # without reading or rewriting it.
            pkg.packagedata.set_data(
                {"filename": pkg_filename}, check_data=False
            )
    else:
        pkg = mf6.ModflowGwfcsub(
            gwf, ninterbeds=ninterbeds, packagedata=recs, **kw
        )

    if obs_continuous is not None:
        pkg.obs.initialize(
            filename=f"{gwf.name}.csub.obs",
            digits=10,
            print_input=True,
            continuous=obs_continuous,
        )

    written = save_sim(model, sim)

    # A deliberately re-added CSUB package invalidates every pristine snapshot
    # setup_calibration would otherwise restore (Important 3/4): the packagedata
    # external file and the per-layer cg_theta/cg_ske_cr arrays.
    clear_csub_base_snapshot(model, gwf.name)

    if recs is not None:
        layers: list = [
            int(r[1][0]) if isinstance(r[1], (list, tuple)) else None
            for r in recs
        ]
        interbeds = [
            {
                "icsubno": i,
                "layer": layers[i],
                "cdelay": str(r[2]).lower(),
            }
            for i, r in enumerate(recs)
        ]
        n_delay: int | None = sum(
            1 for r in recs if str(r[2]).lower() == "delay"
        )
    else:
        layers = []
        interbeds = []
        n_delay = None

    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    csub_meta: dict = {
        "ninterbeds": ninterbeds,
        "n_delay_interbeds": n_delay,
        "ndelaycells": ndelaycells,
        "layers": layers,
        "interbeds": interbeds,
        "filerecords": dict(filerecords or {}),
    }
    # Only record provenance once the referenced file actually exists on disk.
    ext_exists = (
        pkg_filename is not None
        and _resolve_external_path(ws, pkg_filename).exists()
    )
    if ext_exists:
        csub_meta["packagedata_filename"] = str(pkg_filename)
    if obs_output_csv is not None:
        csub_meta["obs_output_csv"] = obs_output_csv
        csub_meta["obs_names"] = obs_names
    meta["csub"] = csub_meta
    _write_meta(ws, meta)

    result: dict = {
        "model": model,
        "package": "CSUB",
        "ninterbeds": ninterbeds,
        "n_delay_interbeds": n_delay,
        "ndelaycells": ndelaycells,
        "layers": layers,
        "filerecords": dict(filerecords or {}),
        "written": written,
    }
    if ext_exists:
        result["packagedata_filename"] = str(pkg_filename)
    if obs_output_csv is not None:
        result["obs_output_csv"] = obs_output_csv
        result["obs_names"] = obs_names
    if replaced:
        if pname:
            result["warning"] = (
                f"A previous CSUB package named '{pname}' was removed and "
                "replaced by this call."
            )
        else:
            result["warning"] = (
                "A previous CSUB package was removed and replaced by this "
                "call. Pass a distinct pname to keep multiple CSUB packages "
                "side by side."
            )
    return result


def _transient_like_without_sto(sim, gwf) -> tuple[bool, str]:
    """Return (True, message) when TDIS looks transient but no STO exists.

    MODFLOW 6 runs a model without an STO package as steady state regardless
    of TDIS settings — a multi-time-step configuration is therefore silently
    stripped of storage physics. This helper lets check_model and
    run_simulation surface that loudly.
    """
    if gwf.get_package("sto") is not None:
        return False, ""
    tdis = sim.get_package("tdis")
    if tdis is None:
        return False, ""
    try:
        rows = list(tdis.perioddata.array)
    except Exception:
        return False, ""
    if len(rows) > 1 or any(int(row[1]) > 1 for row in rows):
        return True, (
            "No STO (storage) package present — the model runs as steady state "
            "even though multiple time steps are configured. If a transient "
            "simulation is intended, add storage first: "
            "add_sto_package(iconvert=1, ss=1e-5, sy=0.2)."
        )
    return False, ""


def _impl_add_boundary_package(
    model: str,
    package: str,
    stress_period_data: dict,
    kwargs: dict | None,
    save_flows: bool = True,
    rate_units: str | None = None,
    pname: str | None = None,
) -> dict:
    pkg_name = package.upper()
    if pkg_name not in _BOUNDARY_PKG_CLASSES:
        raise ValueError(
            f"Unsupported package '{pkg_name}'. "
            f"Choose from: {', '.join(_BOUNDARY_PKG_CLASSES)}."
        )

    # Convert JSON string keys to int keys
    spd = {int(k): v for k, v in stress_period_data.items()}

    # Dimensional arguments carry units (7f-H1.1): RCH/EVT rates and the
    # array-based RCHA/EVTA grids are converted from rate_units into the model's
    # length unit per its time unit, and the declared units are recorded.
    if rate_units is not None and (
        pkg_name in ("RCH", "EVT") or pkg_name in _ARRAY_BOUNDARY_PKGS
    ):
        ws = resolve_workspace(model)
        meta = _read_meta(ws)
        time_units = meta.get("time_units", "DAYS")
        length_units = meta.get("units", "METERS")
        if pkg_name in _ARRAY_BOUNDARY_PKGS:
            spd = {
                sp: _convert_rate_array(arr, rate_units, time_units, length_units)
                for sp, arr in spd.items()
            }
        else:
            spd = {
                sp: [
                    _convert_rate_record(r, rate_units, time_units, length_units)
                    for r in records
                ]
                for sp, records in spd.items()
            }
        meta.setdefault("declared_units", {})["recharge"] = rate_units
        _write_meta(ws, meta)

    gwf = get_gwf(model)
    pkg_cls = _BOUNDARY_PKG_CLASSES[pkg_name]

    # DISU boundary cell ids are a single node index. A malformed multi-element
    # id (e.g. a DISV-style (layer, node)) is silently reduced to its first
    # element by FloPy, which can collapse two records onto one node — reject it
    # up front with a clear message instead.
    if get_disu(gwf) is not None and pkg_name not in _ARRAY_BOUNDARY_PKGS:
        _validate_disu_boundary_cellids(spd)

    # Replacement semantics (7e-B10): with an explicit ``pname`` only that
    # package is replaced (so two CHD sets can coexist, e.g. chd_high +
    # chd_lower); without one, every package of the type is removed first.
    existing = _packages_of_type(gwf, pkg_name.lower())
    if pname:
        targets = [p for p in existing if _pkg_nam_name(p).lower() == pname.lower()]
    else:
        targets = existing
    for pkg in targets:
        gwf.remove_package(pkg)
    replaced = bool(targets)

    pkg_kwargs = dict(kwargs or {})
    if pname:
        pkg_kwargs["pname"] = pname
    if "save_flows" not in pkg_kwargs:
        pkg_kwargs["save_flows"] = save_flows

    if pkg_name == "RCHA":
        mf6.ModflowGwfrcha(gwf, recharge=spd, **pkg_kwargs)
    elif pkg_name == "EVTA":
        mf6.ModflowGwfevta(gwf, rate=spd, **pkg_kwargs)
    else:
        pkg_cls(gwf, stress_period_data=spd, **pkg_kwargs)
    written = save_sim(model, gwf.simulation)

    if pkg_name in _ARRAY_BOUNDARY_PKGS:
        cell_counts = {sp: int(np.asarray(arr).size) for sp, arr in spd.items()}
    else:
        cell_counts = {sp: len(rows) for sp, rows in spd.items()}
    result: dict = {
        "model": model,
        "package": pkg_name,
        "pname": pname,
        "stress_periods": cell_counts,
        "save_flows": bool(pkg_kwargs.get("save_flows", save_flows)),
        "written": written,
    }
    if rate_units is not None and pkg_name in ("RCH", "EVT", "RCHA", "EVTA"):
        result["rate_units"] = rate_units
    if replaced:
        if pname:
            result["warning"] = (
                f"A previous {pkg_name} package named '{pname}' was removed and "
                "replaced by this call."
            )
        else:
            result["warning"] = (
                f"A previous {pkg_name} package was removed and replaced by "
                "this call. If that was unintentional (e.g. two separate CHD "
                "sets were meant to be combined), pass distinct pname values "
                "and re-add each boundary in its own call."
            )
    return result


def _validate_disu_boundary_cellids(spd: dict) -> None:
    """Reject non-scalar boundary cell ids on a DISU grid.

    On DISU the cell id is a single node index (or a 1-element ``[node]``);
    ``(layer, row, col)`` and ``(layer, node)`` forms are invalid and FloPy
    silently truncates them, which can map several records onto one node.
    """
    for sp, records in spd.items():
        for rec in records:
            try:
                cellid = rec[0]
            except (TypeError, IndexError, KeyError):
                raise ValueError(
                    f"Malformed boundary record in stress period {sp}: {rec!r}."
                ) from None
            if isinstance(cellid, (list, tuple, np.ndarray)):
                if len(cellid) != 1:
                    raise ValueError(
                        "On a DISU grid a boundary cell id must be a single node "
                        f"index (got {list(cellid)!r} in stress period {sp}). Use a "
                        "scalar node or a 1-element [node] id; DIS (layer,row,col) "
                        "and DISV (layer,node) ids are not valid on DISU."
                    )
            elif not isinstance(cellid, (int, np.integer)):
                raise ValueError(
                    "On a DISU grid a boundary cell id must be a single node "
                    f"index (got {cellid!r} in stress period {sp})."
                )


def _convert_rate_record(
    record, rate_units: str, time_units: str, length_units: str
) -> list:
    """Convert the rate element of an RCH (`[cellid, rate]`) or EVT
    (`[cellid, evtrate, surf_dep, extdp]`) record into the model's units."""
    record = list(record)
    if len(record) >= 2:
        record[1] = _convert_rate(record[1], rate_units, time_units, length_units)
    return record


def _convert_rate_array(arr, rate_units: str, time_units: str, length_units: str) -> np.ndarray:
    """Convert a full-grid RCHA/EVTA rate array into the model's units (7e-B8)."""
    return np.asarray(arr, dtype=float) * _rate_factor(
        rate_units, time_units, length_units
    )


def _pkg_nam_name(pkg) -> str:
    """The model-nam-file name of a package (flopy stores it as a list)."""
    name = getattr(pkg, "name", "")
    if isinstance(name, list):
        return str(name[0]) if name else ""
    return str(name)


def _packages_of_type(gwf, pkg_type: str) -> list:
    """Return every package on *gwf* whose ``package_type`` matches.

    ``gwf.get_package(type)`` returns a list when several packages share a
    type, which the replacement logic must handle (7e-B10) — this helper
    normalises that.
    """
    pkg_type = pkg_type.lower()
    out = []
    for nam_name in gwf.get_package_list():
        p = gwf.get_package(nam_name)
        if p is not None and getattr(p, "package_type", "").lower() == pkg_type:
            out.append(p)
    return out


def _impl_add_oc_package(
    model: str,
    head_filerecord: str | None,
    budget_filerecord: str | None,
    saverecord: list | None,
    printrecord: list | None,
    component: str = "gwf",
) -> dict:
    key = component.lower()
    spec = spec_for(key)
    comp = get_model(model, key)
    name = comp.name

    if key == "gwf":
        head_file = head_filerecord or f"{name}.hds"
        budget_file = budget_filerecord or f"{name}.cbb"
        save_rec = saverecord or [("HEAD", "ALL"), ("BUDGET", "ALL")]
        oc_kwargs: dict = {"head_filerecord": head_file}
    else:
        head_file = head_filerecord or f"{name}.ucn"
        budget_file = budget_filerecord or f"{name}.cbb"
        oc_kwargs = {}
        if spec.oc_value_keyword:
            save_rec = saverecord or [("TEMPERATURE", "ALL"), ("BUDGET", "ALL")]
            oc_kwargs[spec.oc_value_keyword] = head_file
        else:
            save_rec = saverecord or [("BUDGET", "ALL")]
    oc_kwargs["budget_filerecord"] = budget_file
    oc_kwargs["saverecord"] = save_rec
    if printrecord is not None:
        oc_kwargs["printrecord"] = printrecord

    pkg = comp.get_package("oc")
    if pkg is not None:
        comp.remove_package(pkg)

    if spec.oc_class is None:
        raise ValueError(f"Component '{key}' has no OC package class.")
    spec.oc_class(comp, **oc_kwargs)
    written = save_sim(model, comp.simulation)
    return {
        "model": model,
        "component": key,
        "package": "OC",
        "head_file": head_file,
        "budget_file": budget_file,
        "written": written,
    }


def _impl_summarise_model(model: str) -> dict:
    sim = get_sim(model)
    gwf = get_gwf(model)
    ws = resolve_workspace(model)

    # Packages present on the GWF model
    package_list = gwf.get_package_list()

    # Grid info
    grid_info: dict = {}
    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
    if dis_pkg is not None:
        grid_info = {
            "type": "DIS",
            "nlay": int(dis_pkg.nlay.data),
            "nrow": int(dis_pkg.nrow.data),
            "ncol": int(dis_pkg.ncol.data),
            "ncells": int(dis_pkg.nlay.data * dis_pkg.nrow.data * dis_pkg.ncol.data),
        }
        idomain = getattr(dis_pkg, "idomain", None)
        if idomain is not None:
            try:
                id_arr = np.asarray(idomain.array)
                grid_info["n_active"] = int((id_arr > 0).sum())
            except Exception:
                pass
    elif disv_pkg is not None:
        grid_info = {
            "type": "DISV",
            "nlay": int(disv_pkg.nlay.data),
            "ncpl": int(disv_pkg.ncpl.data),
            "ncells": int(disv_pkg.nlay.data * disv_pkg.ncpl.data),
        }
    else:
        disu_pkg = get_disu(gwf)
        if disu_pkg is not None:
            nnodes = int(disu_pkg.nodes.data)
            nja = int(disu_pkg.nja.data) if getattr(disu_pkg, "nja", None) is not None else None
            grid_info = {
                "type": "DISU",
                "nlay": 1,
                "nnodes": nnodes,
                "ncells": nnodes,
            }
            if nja is not None:
                grid_info["nja"] = nja
            idomain = getattr(disu_pkg, "idomain", None)
            if idomain is not None:
                try:
                    id_arr = np.asarray(idomain.array)
                    if id_arr is not None and id_arr.dtype != object:
                        grid_info["n_active"] = int((id_arr > 0).sum())
                except Exception:
                    pass

    # Stress period info from TDIS
    stress_periods: list[dict] = []
    tdis = sim.get_package("tdis")
    if tdis is not None:
        try:
            for row in tdis.perioddata.array:
                stress_periods.append({
                    "perlen": float(row[0]),
                    "nstp": int(row[1]),
                    "tsmult": float(row[2]),
                })
        except Exception:
            pass

    boundary_types = [
        pkg for pkg in _BOUNDARY_PKG_CLASSES
        if gwf.get_package(pkg.lower()) is not None
    ]

    storage: dict | None = None
    if gwf.get_package("sto") is not None:
        meta = _read_meta(ws)
        storage = {
            "package": "STO",
            "steady_state_periods": list(meta.get("sto_steady_state", [])),
            "transient_periods": list(meta.get("sto_transient", [])),
        }

    # Registered observation targets (7f-F1.1): the site → cellid map plus
    # observed values/dates persisted by import_obs_from_csv.
    observations: dict | None = None
    meta = _read_meta(ws)
    obs_meta = meta.get("observations")
    if obs_meta:
        observations = {
            "type": obs_meta.get("type"),
            "layer": obs_meta.get("layer"),
            "output_csv": obs_meta.get("output_csv"),
            "site_count": len(obs_meta.get("sites", [])),
        }

    # Declared units per quantity (7f-H1.3): what was declared, not assumed.
    declared = meta.get("declared_units", {})
    units = {
        "length": meta.get("units", "METERS"),
        "time": meta.get("time_units", "DAYS"),
        "k": declared.get("k", "m/d"),
        "recharge": declared.get("recharge", "m/d"),
    }

    components_info: dict[str, dict] = {}
    for cname, mname in list_components(model).items():
        try:
            comp_model = get_model(model, cname)
        except KeyError:
            continue
        grid_kind = _grid_type_of(comp_model)
        components_info[cname] = {
            "model": mname,
            "packages": list(comp_model.get_package_list()),
            "grid_type": grid_kind.upper() if grid_kind else None,
        }

    return {
        "model": model,
        "workspace": str(ws),
        "packages": package_list,
        "grid": grid_info,
        "stress_periods": stress_periods,
        "boundary_types": boundary_types,
        "storage": storage,
        "observations": observations,
        "units": units,
        "components": components_info,
        "reloaded_from_disk": consume_reload_flag(model),
    }


def _compute_model_status(model: str) -> dict:
    """Ordered build-order status for a model (7e-C8): what's present, what's
    still missing, and what to call next — read-only, no flush/mutation.

    "runnable" means MF6 has everything it needs for a meaningful run: a grid
    (DIS/DISV), TDIS+IMS (set_simulation), NPF, IC, OC (technically optional
    for MF6 itself, but without it no output is written), and STO whenever
    TDIS looks transient (multiple stress periods/time steps). A boundary
    condition package is recommended, not required — MF6 will run without
    one, it just won't do anything interesting.
    """
    sim = get_sim(model)
    try:
        gwf = get_model(model, "gwf")
    except KeyError:
        return {
            "model": model,
            "runnable": False,
            "missing_required": ["gwf"],
            "missing_recommended": [],
            "next_steps": [
                "create_model(...) — this simulation has no flow (gwf) model."
            ],
            "warnings": [],
            "components": sorted(list_components(model)),
        }

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
    disu_pkg = get_disu(gwf)
    has_grid = dis_pkg is not None or disv_pkg is not None or disu_pkg is not None
    tdis = sim.get_package("tdis")
    ims = sim.get_package("ims")
    has_simulation = tdis is not None and ims is not None
    has_npf = gwf.get_package("npf") is not None
    has_ic = gwf.get_package("ic") is not None
    has_oc = gwf.get_package("oc") is not None
    has_sto = gwf.get_package("sto") is not None
    has_boundary = any(
        gwf.get_package(pkg.lower()) is not None for pkg in _BOUNDARY_PKG_CLASSES
    )

    needs_sto = False
    sto_warning = ""
    if not has_sto:
        needs_sto, sto_warning = _transient_like_without_sto(sim, gwf)

    # (name, present, required, hint) in recommended build order.
    steps = [
        ("simulation", has_simulation, True,
         "set_simulation(model, nper, perlen, nstp, ims_complexity) — defines "
         "TDIS+IMS; also a documented prerequisite for import_grid_from_shapefile."),
        ("grid", has_grid, True,
         "add_dis_package / add_disv_package / add_disu_package / "
         "import_grid_from_shapefile — defines the model grid."),
        ("npf", has_npf, True,
         "add_npf_package(model, icelltype, k) — hydraulic properties; must "
         "exist before assign_k_from_zones, which edits this package in place."),
        ("ic", has_ic, True,
         "add_ic_package(model, strt) — starting heads."),
        ("sto", has_sto, needs_sto,
         "add_sto_package(model, iconvert, ss, sy, steady_state) — storage, "
         "required because multiple time steps are configured; without it "
         "the model silently runs as steady state."),
        ("oc", has_oc, True,
         "add_oc_package(model) — declares the head/budget output files."),
        ("boundary", has_boundary, False,
         "add_boundary_package / import_river_from_shapefile — at least one "
         "boundary condition (recommended: MF6 will run without one, but "
         "nothing will change)."),
    ]

    missing_required: list[str] = []
    missing_recommended: list[str] = []
    next_steps: list[str] = []
    for name, present, required, hint in steps:
        if present:
            continue
        if name == "sto" and not required:
            continue  # steady-state model — STO genuinely isn't needed
        (missing_required if required else missing_recommended).append(name)
        next_steps.append(hint)

    warnings: list[str] = []
    if needs_sto:
        warnings.append(sto_warning)

    return {
        "model": model,
        "runnable": len(missing_required) == 0,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "next_steps": next_steps,
        "warnings": warnings,
        "components": sorted(list_components(model)),
    }


def _impl_flush_model(model: str) -> dict:
    """Flush a dirty model to disk (7f-E1.2).

    Builder calls defer their disk writes; this tool forces the pending write
    so the on-disk input set reflects the current in-memory state. It is a
    no-op (``written: false``) for clean models and for adopted read-only
    models (which can never be dirty).
    """
    written = flush_model(model)
    return {"model": model, "workspace": str(resolve_workspace(model)), "written": written}


def _impl_list_model_files(model: str) -> dict:
    ws = resolve_workspace(model)
    flushed = flush_model(model)
    files = []
    for f in sorted(ws.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            files.append({
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "extension": f.suffix,
            })
    return {
        "model": model,
        "workspace": str(ws),
        "files": files,
        "flushed": flushed,
    }


def _impl_list_models() -> dict:
    """Return every registered model name → workspace path (7e-B4.1)."""
    return {"models": dict(list_workspaces())}


def _impl_delete_model(model: str, remove_files: bool = False) -> dict:
    """Unregister a model; optionally delete its workspace (7e-B4.1)."""
    delete_workspace(model, remove_files=remove_files)
    clear_component_sims(model)
    invalidate(model)
    return {
        "model": model,
        "removed": True,
        "remove_files": bool(remove_files),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp) -> None:
    """Register model builder tools with the MCP server."""

    @mcp.tool()
    def create_model(
        name: str,
        workspace: str = "",
        units: str = "METERS",
        time_units: str = "DAYS",
    ) -> dict:
        """Create a new MODFLOW 6 GWF model workspace.

        ``workspace`` is the absolute path where the model files are written. Pass an
        explicit path — ideally a subfolder of the folder containing your data — so all
        model inputs and outputs live together. If empty, the model is created under the
        default workspace root (~/.groundwater-mcp/workspaces/<name>)."""
        try:
            return _impl_create_model(name, workspace, units, time_units)
        except ValueError as exc:
            return _err("MODEL_EXISTS", str(exc), "Use a different model name.")
        except Exception as exc:
            return _err("CREATE_FAILED", str(exc))

    @mcp.tool()
    def adopt_model(
        name: str,
        workspace: str,
        units: str = "METERS",
        time_units: str = "DAYS",
        allow_modify: bool = False,
    ) -> dict:
        """Register an existing MODFLOW 6 simulation on disk as a model.

        ``workspace`` must be a directory that already contains a runnable
        MF6 input set (``mfsim.nam`` plus the package files it references).
        The simulation is loaded into the in-process cache from the on-disk
        files (no stub is created, no files are rewritten), so check_model,
        run_simulation, summarise_model, and the calibration chain operate on
        the real model. The GWF model name inside the files need NOT match
        ``name``. Model-name length is capped at 16 characters (MODFLOW 6
        MODELNAME).

        Adopted models are read-only by default (7f-D4.2): save_sim-backed
        builder calls are refused with MODEL_ADOPTED_READONLY so a real
        published model cannot be silently rewritten. Pass ``allow_modify=True``
        to opt out; check_model / run_simulation / summarise_model /
        read_heads always work on read-only adopted models."""
        try:
            return _impl_adopt_model(name, workspace, units, time_units, allow_modify)
        except ValueError as exc:
            return _err("MODEL_EXISTS", str(exc), "Use a different model name.")
        except FileNotFoundError as exc:
            return _err(
                "MODEL_FILES_NOT_FOUND",
                str(exc),
                "Point workspace at a directory containing an existing MF6 "
                "input set (mfsim.nam + package files).",
            )
        except Exception as exc:
            return _err("ADOPT_FAILED", str(exc))

    @mcp.tool()
    def set_simulation(
        model: str,
        nper: int,
        perlen: list[float],
        nstp: list[int],
        ims_complexity: str = "moderate",
        start_date_time: str | None = None,
        newton: bool | None = None,
        linear_acceleration: str | None = None,
        outer_maximum: int | None = None,
        under_relaxation: str | None = None,
    ) -> dict:
        """Configure simulation time discretisation (TDIS) and solver (IMS).

        ``start_date_time`` is an optional ISO-8601 date/datetime (e.g.
        "1935-01-25") that anchors the elapsed model time axis to calendar
        dates, so derived CSUB observations can match calendar dates.
        ``newton`` toggles the GWF Newton-Raphson formulation (mandatory for
        CSUB delay interbeds); ``linear_acceleration``, ``outer_maximum`` and
        ``under_relaxation`` (an IMS keyword such as "simple") map onto the IMS
        package. All new arguments are optional and default to the previous
        behaviour.
        """
        try:
            return _impl_set_simulation(
                model,
                nper,
                perlen,
                nstp,
                ims_complexity,
                start_date_time,
                newton,
                linear_acceleration,
                outer_maximum,
                under_relaxation,
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("SET_SIM_FAILED", str(exc))

    @mcp.tool()
    def set_model_crs(
        model: str,
        crs: str,
        xorigin: float | None = None,
        yorigin: float | None = None,
        angrot: float | None = None,
        component: str = "gwf",
    ) -> dict:
        """Set the coordinate reference system (and optional offsets) on the
        model grid.

        Grids built with add_dis_package / add_disv_package have no CRS until
        this is called. Every spatial tool (assign_top_from_raster,
        assign_k_from_zones, import_river_from_shapefile) needs the grid to
        carry a CRS to compare coordinates — without one they fail with
        CRS_UNKNOWN rather than guessing. ``crs`` accepts anything rasterio
        accepts (e.g. "EPSG:32718"); ``xorigin``/``yorigin`` are the grid
        lower-left corner in that CRS. ``component`` (default "gwf") targets a
        coupled component model (e.g. "gwe")."""
        try:
            return _impl_set_model_crs(model, crs, xorigin, yorigin, angrot, component)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("CRS_SET_FAILED", str(exc))

    @mcp.tool()
    def add_dis_package(
        model: str,
        nlay: int,
        nrow: int,
        ncol: int,
        delr: float | list,
        delc: float | list,
        top: float | list,
        botm: list,
        idomain: int | list | None = None,
        component: str = "gwf",
    ) -> dict:
        """Add a structured (DIS) grid to the model.

        ``idomain`` marks active/inactive cells: 1 = active, 0 = inactive,
        -1 = inactive (constant head under some formulations). A 2-D array
        (nrow, ncol) is broadcast across layers; a 3-D array is (nlay, nrow,
        ncol). Without it every cell is active. ``component`` (default "gwf")
        targets a coupled component model (e.g. "gwe")."""
        try:
            return _impl_add_dis_package(
                model, nlay, nrow, ncol, delr, delc, top, botm, idomain,
                component=component,
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_disv_package(
        model: str,
        nlay: int,
        vertices: list,
        cell2d: list,
        top: list,
        botm: list,
        gridprops_file: str | None = None,
        component: str = "gwf",
    ) -> dict:
        """Add an unstructured vertex-based (DISV) grid to the model.

        Inline vertices/cell2d are rejected beyond 50,000 cells
        (PAYLOAD_TOO_LARGE) — pass gridprops_file (a JSON file with
        vertices/cell2d/top/botm) or use import_grid_from_shapefile
        (method='disv') for real Voronoi grids. ``component`` (default "gwf")
        targets a coupled component model (e.g. "gwe")."""
        try:
            return _impl_add_disv_package(
                model, nlay, vertices, cell2d, top, botm, gridprops_file,
                component=component,
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except PayloadTooLargeError as exc:
            return _err(
                "PAYLOAD_TOO_LARGE",
                str(exc),
                "Use import_grid_from_shapefile (method='disv') or pass "
                "gridprops_file naming a JSON file.",
            )
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_disu_package(
        model: str,
        nodes: int,
        nja: int,
        top: list,
        bot: list,
        area: list | None = None,
        iac: list | None = None,
        ja: list | None = None,
        ihc: list | None = None,
        cl12: list | None = None,
        hwva: list | None = None,
        angldegx: list | None = None,
        idomain: list | None = None,
        vertices: list | None = None,
        cell2d: list | None = None,
        nvert: int | None = None,
        gridprops_file: str | None = None,
        component: str = "gwf",
    ) -> dict:
        """Add a fully-unstructured (DISU) grid from explicit node connectivity.

        DISU is defined by ``nodes``/``nja`` plus per-edge connection data:
        ``iac`` (connections per node), ``ja`` (connected node ids, 0-based)
        and optionally ``ihc``/``cl12``/``hwva``/``angldegx``. Per-node ``top``
        and ``bot`` are required and ``area`` defaults to 1.0. Optional
        ``vertices``/``cell2d`` add cell x/y geometry (enabling coordinate
        observations and plan-view plots). Pass ``gridprops_file`` (JSON with
        any of these keys) for large grids. ``component`` (default "gwf")
        targets a coupled component model.
        """
        try:
            return _impl_add_disu_package(
                model, nodes, nja, top, bot, area, iac, ja, ihc, cl12, hwva,
                angldegx, idomain, vertices, cell2d, nvert, gridprops_file,
                component=component,
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_npf_package(
        model: str,
        icelltype: int | list,
        k: float | list,
        k33: float | list | None = None,
        save_flows: bool = True,
        k_units: str = "m/d",
    ) -> dict:
        """Add a Node Property Flow (NPF) package defining hydraulic conductivity.

        ``k_units`` declares the units of ``k``/``k33`` (default "m/d"); values
        are converted into the model's own length unit per its time unit (so
        ``k_units="ft/d", k=10`` stays 10 in a FEET model, while ``k_units="m/d",
        k=10`` becomes 32.808 ft/d). Accepted k_units:
        m/d, m/s, m/yr, cm/s, ft/d, ft/s."""
        try:
            return _impl_add_npf_package(model, icelltype, k, k33, save_flows, k_units)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_ic_package(model: str, strt: float | list, component: str = "gwf") -> dict:
        """Add an Initial Conditions (IC) package with starting values.

        ``component`` (default "gwf") targets a coupled component model
        (e.g. "gwe", whose IC is initial temperature)."""
        try:
            return _impl_add_ic_package(model, strt, component=component)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_sto_package(
        model: str,
        iconvert: int | list,
        ss: float | list,
        sy: float | list | None = None,
        steady_state: list[int] | None = None,
        save_flows: bool = True,
    ) -> dict:
        """Add a Storage (STO) package defining aquifer storage properties.

        Required for transient simulations (without it, a multi-time-step
        model silently runs as steady state). ``steady_state`` lists the
        0-based stress-period indices (matching set_simulation) that are
        steady-state; all other periods run transient. Default ``[0]`` marks
        the first period steady and the rest transient. ``sy`` (specific
        yield) is required when any cell is convertible (iconvert>0)."""
        try:
            return _impl_add_sto_package(
                model, iconvert, ss, sy, steady_state, save_flows
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_csub_package(
        model: str,
        packagedata: list | dict,
        ninterbeds: int | None = None,
        sgm: float | list | None = None,
        sgs: float | list | None = None,
        cg_theta: float | list | None = None,
        cg_ske_cr: float | list | None = None,
        head_based: bool = False,
        initial_preconsolidation_head: bool = False,
        specified_initial_interbed_state: bool = False,
        update_material_properties: bool = False,
        ndelaycells: int | None = None,
        beta: float | None = None,
        gammaw: float | None = None,
        interbeddata: list | None = None,
        stress_period_data: dict | None = None,
        observations: dict | None = None,
        filerecords: dict | None = None,
        print_input: bool = True,
        save_flows: bool = True,
        pname: str | None = None,
    ) -> dict:
        """Add or replace the CSUB (subsidence) package on a MODFLOW 6 GWF model.

        ``packagedata`` is a list of 11-field interbed records
        ``[icsubno, cellid, cdelay, pcs0, thick_frac, rnb, ssv_cc, sse_cr,
        theta, kv, h0]`` with 0-based ``icsubno`` (contiguous from 0) and
        0-based cellids, ``{"filename": ...}`` to reference a pre-externalised
        file that must already exist (then ``ninterbeds`` is required), or
        ``{"filename": ..., "data": [...]}`` to externalise the records to
        that file (written immediately).
        ``sgm``/``sgs``/``cg_theta``/``cg_ske_cr`` take a scalar or one value
        per layer. ``ndelaycells`` is required — never defaulted — when any
        interbed has ``cdelay="delay"``.

        ``observations`` maps a CSV name to ``[(name, obs_type, index), ...]``:
        cell types (compaction, preconstress, elastic-compaction,
        inelastic-compaction; the ``-cell`` suffix is optional) take a cellid;
        interbed types (interbed-compaction-pct, delay-preconstress, delay-head)
        take a 0-based interbed number. ``filerecords`` accepts zdisplacement,
        package_convergence, strainib and compaction. Re-adding replaces the
        existing CSUB package(s) unless distinct ``pname`` values are used."""
        try:
            return _impl_add_csub_package(
                model,
                packagedata,
                ninterbeds,
                sgm,
                sgs,
                cg_theta,
                cg_ske_cr,
                head_based,
                initial_preconsolidation_head,
                specified_initial_interbed_state,
                update_material_properties,
                ndelaycells,
                beta,
                gammaw,
                interbeddata,
                stress_period_data,
                observations,
                filerecords,
                print_input,
                save_flows,
                pname,
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_boundary_package(
        model: str,
        package: str,
        stress_period_data: dict,
        kwargs: dict | None = None,
        save_flows: bool = True,
        rate_units: str | None = None,
        pname: str | None = None,
    ) -> dict:
        """Add a boundary condition package (CHD, WEL, RIV, DRN, RCH, RCHA,
        EVT, EVTA, GHB, SFR).

        stress_period_data maps a stress-period index (0-based, matching the
        nper/perioddata set in set_simulation) to a list of records.  Each
        record uses 0-based cell indices (layer, row, col) for DIS grids and
        (layer, node) for DISV grids — indices are converted to the 1-based
        form written to the package file.  Example:
        ``{"0": [[[0, 2, 3], 55.0], [[0, 2, 4], 55.0]]}``

        RCHA/EVTA are the array-based recharge/ET packages: instead of cell
        records, stress_period_data maps each period to a full-grid array
        (nrow×ncol for DIS layer 0, or ncpl for DISV) of rates.

        save_flows writes the SAVE FLOWS option into the package file so the
        package's fluxes appear in the budget file for compute_water_balance.

        rate_units declares the units of RCH/EVT/RCHA/EVTA rates (default None
        = rates are already in the model's units); accepted: m/d, m/yr, mm/d,
        mm/yr. Rates are converted into the model's own length unit per its time
        unit on entry.

        pname names the package in the model name file. Re-adding a package
        with the same pname (or with no pname) replaces the existing one(s) of
        that type; two packages of the same type with different pnames coexist
        (e.g. pname='chd_high' and pname='chd_lower').
        """
        try:
            return _impl_add_boundary_package(
                model, package, stress_period_data, kwargs, save_flows, rate_units, pname
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_oc_package(
        model: str,
        head_filerecord: str | None = None,
        budget_filerecord: str | None = None,
        saverecord: list | None = None,
        printrecord: list | None = None,
        component: str = "gwf",
    ) -> dict:
        """Add an Output Control (OC) package.

        ``component="gwf"`` (default) writes the head/budget filerecords;
        ``component="gwe"`` writes the GWE temperature/budget filerecords."""
        try:
            return _impl_add_oc_package(
                model, head_filerecord, budget_filerecord, saverecord, printrecord,
                component=component,
            )
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_gwe_model(
        model: str,
        flow_model: str | None = None,
        perioddata: list | None = None,
        time_units: str | None = None,
    ) -> dict:
        """Create a derived GWE heat-transport simulation coupled to a flow run.

        The heat model lives in ``<workspace>/gwe/`` and reads the flow run's
        head/budget files through the Flow Model Interface. Build its packages
        with the ``add_gwe_*`` tools (and grid/IC with ``component="gwe"``), then
        ``run_simulation`` runs the flow model first and the heat model second.
        Omit ``perioddata`` to mirror the flow TDIS (including its time units);
        pass ``[ (perlen, nstp, tsmult), ... ]`` for a different heat schedule."""
        try:
            return _impl_add_gwe_model(
                model, flow_model=flow_model, perioddata=perioddata, time_units=time_units
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("GWE_BUILD_FAILED", str(exc))

    @mcp.tool()
    def add_gwe_adv_package(model: str, scheme: str = "TVD") -> dict:
        """Add the GWE advection package. ``scheme`` is the transport scheme
        (TVD, upstream, central, ...)."""
        try:
            return _impl_add_gwe_adv_package(model, scheme=scheme)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Call add_gwe_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_gwe_cnd_package(
        model: str,
        alh: float | list | None = None,
        ath1: float | list | None = None,
        ath2: float | list | None = None,
        alv: float | list | None = None,
        atv: float | list | None = None,
        ktw: float | list | None = None,
        kts: float | list | None = None,
    ) -> dict:
        """Add the GWE conduction/dispersion package: thermal conductivities
        (ktw water, kts solid) and dispersivities (alh/ath1/ath2/alv/atv)."""
        try:
            return _impl_add_gwe_cnd_package(model, alh, ath1, ath2, alv, atv, ktw, kts)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Call add_gwe_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_gwe_est_package(
        model: str,
        porosity: float | list,
        heat_capacity_water: float | None = None,
        density_water: float | None = None,
        heat_capacity_solid: float | list | None = None,
        density_solid: float | list | None = None,
        latent_heat_vaporization: float | None = None,
        save_flows: bool = False,
    ) -> dict:
        """Add the GWE energy storage and transfer (EST) package."""
        try:
            return _impl_add_gwe_est_package(
                model, porosity, heat_capacity_water, density_water,
                heat_capacity_solid, density_solid, latent_heat_vaporization, save_flows,
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Call add_gwe_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_gwe_ssm_package(model: str, sources: list | None = None) -> dict:
        """Add the GWE source-sink mixing (SSM) package. Required whenever the
        flow model has boundary packages. ``sources`` is a list of
        ``(package_name, source_type, aux_name)`` tuples, e.g.
        ``[("CHD", "AUX", "TEMPERATURE")]``."""
        try:
            return _impl_add_gwe_ssm_package(model, sources)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Call add_gwe_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_gwe_esl_package(model: str, stress_period_data: dict, save_flows: bool = False) -> dict:
        """Add the GWE energy source loading (ESL) package."""
        try:
            return _impl_add_gwe_esl_package(model, stress_period_data, save_flows)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Call add_gwe_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def summarise_model(model: str) -> dict:
        """Return a structured summary of a model's packages, grid, and stress periods."""
        try:
            return _impl_summarise_model(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("SUMMARISE_FAILED", str(exc))

    @mcp.tool()
    def model_status(model: str) -> dict:
        """Ordered build-order status (7e-C8): what's present, what's still
        missing, and what to call next.

        runnable=True once the grid (DIS/DISV), simulation (TDIS+IMS), NPF,
        IC, OC, and — when TDIS looks transient — STO all exist.
        missing_required/missing_recommended name the gaps, and next_steps
        gives the exact tool call for each, in build order. Call this after
        create_model to see the whole build order up front, instead of
        discovering it one error at a time; every builder/parameterise tool's
        result also carries a next_steps list for the same reason."""
        try:
            return _compute_model_status(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("MODEL_STATUS_FAILED", str(exc))

    @mcp.tool()
    def list_model_files(model: str) -> dict:
        """List all files in the model workspace with sizes and extensions."""
        try:
            return _impl_list_model_files(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("LIST_FILES_FAILED", str(exc))

    @mcp.tool()
    def flush_model(model: str) -> dict:
        """Flush staged model changes to disk.

        Builder and parameterisation calls (add_*, assign_*, import_*, ...)
        mutate the in-memory model and defer the disk write (their results
        report ``written: false``). This tool performs the pending write so
        the on-disk input set matches the current in-memory state. It is a
        no-op (``written: false``) for clean models and for adopted read-only
        models. check_model, run_simulation and list_model_files also flush
        automatically before they run.
        """
        try:
            return _impl_flush_model(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("FLUSH_FAILED", str(exc))

    @mcp.tool()
    def list_models() -> dict:
        """List every registered model name and its workspace path (7e-B4.1).

        Models are registered by create_model / adopt_model. Use this to
        recover the model name when a session loses track, and to discover
        what is already on disk."""
        try:
            return _impl_list_models()
        except Exception as exc:
            return _err("LIST_MODELS_FAILED", str(exc))

    @mcp.tool()
    def delete_model(model: str, remove_files: bool = False) -> dict:
        """Unregister a model (7e-B4.1).

        Removes the model from the workspace registry. With ``remove_files``
        also deletes the workspace directory and all its contents — use with
        care; a recreated model of the same name starts from scratch. Model
        files left behind by a registry-only delete can be re-adopted with
        adopt_model."""
        try:
            return _impl_delete_model(model, remove_files)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run list_models to see registered models.")
        except Exception as exc:
            return _err("DELETE_FAILED", str(exc))
