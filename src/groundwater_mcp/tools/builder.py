"""builder module — create and configure MODFLOW 6 GWF models via FloPy."""

from __future__ import annotations

import json
from pathlib import Path

import flopy.mf6 as mf6
import numpy as np

from groundwater_mcp.utils.grid import get_dis, get_disu, get_disv, grid_size
from groundwater_mcp.utils.model_store import (
    ModelReadOnlyError,
    cache_sim,
    clear_k_base_snapshot,
    consume_reload_flag,
    flush_model,
    get_gwf,
    get_sim,
    invalidate,
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

# Conductivity unit → metres per model-time-unit (default time unit = DAYS).
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


def _convert_k_to_model(value, k_units: str, time_units: str):
    """Convert a conductivity value from *k_units* into the model's length/time
    convention (length is metres; time comes from the model's time_units)."""
    if k_units not in _K_UNITS_TO_PER_DAY:
        raise ValueError(
            f"Unrecognised k_units '{k_units}'. Accepted: {sorted(_K_UNITS_TO_PER_DAY)}."
        )
    per_second = _K_UNITS_TO_PER_DAY[k_units] / 86400.0
    target_per_second = _SECONDS_PER_TIME_UNIT.get(time_units, 86400.0)
    factor = per_second * target_per_second
    if isinstance(value, (int, float)):
        return float(value) * factor
    return np.asarray(value, dtype=float) * factor


def _convert_rate_to_md(value, rate_units: str) -> float:
    """Convert a recharge/ET rate from *rate_units* into m/d."""
    if rate_units not in _RATE_UNITS_TO_MD:
        raise ValueError(
            f"Unrecognised rate_units '{rate_units}'. Accepted: {sorted(_RATE_UNITS_TO_MD)}."
        )
    return float(value) * _RATE_UNITS_TO_MD[rate_units]

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
    sim = mf6.MFSimulation(
        sim_name="mfsim",
        version="mf6",
        sim_ws=str(model_dir),
    )
    mf6.ModflowGwf(sim, modelname=name, model_nam_file=f"{name}.nam")
    _write_meta(model_dir, {"name": name, "units": units.upper(), "time_units": time_units.upper()})
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
    _write_meta(model_dir, {
        "name": name,
        "units": units.upper(),
        "time_units": time_units.upper(),
        "adopted": True,
        "allow_modify": bool(allow_modify),
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


def _impl_set_simulation(
    model: str,
    nper: int,
    perlen: list[float],
    nstp: list[int],
    ims_complexity: str,
) -> dict:
    if len(perlen) != nper or len(nstp) != nper:
        raise ValueError(f"len(perlen) and len(nstp) must equal nper={nper}.")

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
    mf6.ModflowTdis(
        sim,
        pname="tdis",
        time_units=time_units,
        nper=nper,
        perioddata=perioddata,
    )
    ims = mf6.ModflowIms(sim, pname="ims", complexity=ims_complexity.upper())
    sim.register_ims_package(ims, list(sim.model_names))

    written = save_sim(model, sim)
    return {
        "model": model,
        "nper": nper,
        "time_units": time_units,
        "ims_complexity": ims_complexity.upper(),
        "total_time": sum(perlen),
        "written": written,
    }


def _impl_set_model_crs(
    model: str,
    crs: str,
    xorigin: float | None = None,
    yorigin: float | None = None,
    angrot: float | None = None,
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
    gwf = get_gwf(model)
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
) -> dict:
    if len(botm) != nlay:
        raise ValueError(f"len(botm)={len(botm)} must equal nlay={nlay}.")

    gwf = get_gwf(model)
    for existing in (get_dis(gwf), get_disv(gwf)):
        if existing is not None:
            gwf.remove_package(existing)

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
    mf6.ModflowGwfdis(gwf, **dis_kwargs)
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

    gwf = get_gwf(model)
    for existing in (get_dis(gwf), get_disv(gwf)):
        if existing is not None:
            gwf.remove_package(existing)

    mf6.ModflowGwfdisv(
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

    gwf = get_gwf(model)
    for existing in (get_dis(gwf), get_disv(gwf), get_disu(gwf)):
        if existing is not None:
            gwf.remove_package(existing)

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
    mf6.ModflowGwfdisu(gwf, **kwargs)
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
    k_converted = _convert_k_to_model(k, k_units, time_units)
    kwargs: dict = {"icelltype": icelltype, "k": k_converted, "save_flows": save_flows}
    if k33 is not None:
        kwargs["k33"] = _convert_k_to_model(k33, k_units, time_units)
    meta.setdefault("declared_units", {})["k"] = k_units
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


def _impl_add_ic_package(model: str, strt: float | list) -> dict:
    gwf = get_gwf(model)
    pkg = gwf.get_package("ic")
    if pkg is not None:
        gwf.remove_package(pkg)

    mf6.ModflowGwfic(gwf, strt=strt)
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
                    idx[0] += 1  # 0-based interbed number -> MF6 icsubno
                    entries.append((obs_name, obs_type, tuple(idx)))
                else:
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

    ``packagedata`` is a list of interbed records or ``{"filename": ...}`` (a
    pre-externalised file, in which case ``ninterbeds`` is required); a dict
    may also carry ``"data"`` to write the external file on flush. Per-layer
    arrays (``sgm``/``sgs``/``cg_theta``/``cg_ske_cr``) accept a scalar or one
    value per layer. ``ndelaycells`` is required when any interbed has
    ``cdelay="delay"`` — it is never defaulted silently.
    """
    gwf = get_gwf(model)
    sim = get_sim(model)
    nlay, _ = grid_size(gwf)

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
        if beta is not None:
            kw["beta"] = float(beta)
        if gammaw is not None:
            kw["gammaw"] = float(gammaw)
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

    if recs is not None:
        pkg = mf6.ModflowGwfcsub(
            gwf, ninterbeds=ninterbeds, packagedata=recs, **kw
        )
    else:
        pkg = mf6.ModflowGwfcsub(gwf, ninterbeds=ninterbeds, **kw)
        # Pre-externalised packagedata: reference the caller's file without
        # reading or rewriting it.
        pkg.packagedata.set_data({"filename": pkg_filename}, check_data=False)

    if obs_continuous is not None:
        pkg.obs.initialize(
            filename=f"{gwf.name}.csub.obs",
            digits=10,
            print_input=True,
            continuous=obs_continuous,
        )

    written = save_sim(model, sim)

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
    if pkg_filename is not None:
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
    if pkg_filename is not None:
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

    # Dimensional arguments carry units (7f-H1.1): RCH/EVT rates are converted
    # from rate_units into m/d, and the declared units are recorded. RCHA/EVTA
    # (array-based, 7e-B8) apply the same conversion to their full-grid arrays.
    if rate_units is not None and pkg_name in ("RCH", "EVT"):
        spd = {
            sp: [_convert_rate_record(r, rate_units, pkg_name) for r in records]
            for sp, records in spd.items()
        }
        ws = resolve_workspace(model)
        meta = _read_meta(ws)
        meta.setdefault("declared_units", {})["recharge"] = rate_units
        _write_meta(ws, meta)
    elif rate_units is not None and pkg_name in _ARRAY_BOUNDARY_PKGS:
        spd = {
            sp: _convert_rate_array(arr, rate_units) for sp, arr in spd.items()
        }
        ws = resolve_workspace(model)
        meta = _read_meta(ws)
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


def _convert_rate_record(record, rate_units: str, pkg_name: str) -> list:
    """Convert the rate element of an RCH (`[cellid, rate]`) or EVT
    (`[cellid, evtrate, surf_dep, extdp]`) record into m/d."""
    record = list(record)
    if len(record) >= 2:
        record[1] = _convert_rate_to_md(record[1], rate_units)
    return record


def _convert_rate_array(arr, rate_units: str) -> np.ndarray:
    """Convert a full-grid RCHA/EVTA rate array into m/d (7e-B8)."""
    if rate_units not in _RATE_UNITS_TO_MD:
        raise ValueError(
            f"Unrecognised rate_units '{rate_units}'. Accepted: {sorted(_RATE_UNITS_TO_MD)}."
        )
    return np.asarray(arr, dtype=float) * _RATE_UNITS_TO_MD[rate_units]


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
) -> dict:
    gwf = get_gwf(model)
    gwf_name = gwf.name

    head_file = head_filerecord or f"{gwf_name}.hds"
    budget_file = budget_filerecord or f"{gwf_name}.cbb"
    save_rec = saverecord or [("HEAD", "ALL"), ("BUDGET", "ALL")]

    pkg = gwf.get_package("oc")
    if pkg is not None:
        gwf.remove_package(pkg)

    oc_kwargs: dict = {
        "head_filerecord": head_file,
        "budget_filerecord": budget_file,
        "saverecord": save_rec,
    }
    if printrecord is not None:
        oc_kwargs["printrecord"] = printrecord

    mf6.ModflowGwfoc(gwf, **oc_kwargs)
    written = save_sim(model, gwf.simulation)
    return {
        "model": model,
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
    gwf = get_gwf(model)

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
    ) -> dict:
        """Configure simulation time discretisation (TDIS) and solver (IMS)."""
        try:
            return _impl_set_simulation(model, nper, perlen, nstp, ims_complexity)
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
    ) -> dict:
        """Set the coordinate reference system (and optional offsets) on the
        model grid.

        Grids built with add_dis_package / add_disv_package have no CRS until
        this is called. Every spatial tool (assign_top_from_raster,
        assign_k_from_zones, import_river_from_shapefile) needs the grid to
        carry a CRS to compare coordinates — without one they fail with
        CRS_UNKNOWN rather than guessing. ``crs`` accepts anything rasterio
        accepts (e.g. "EPSG:32718"); ``xorigin``/``yorigin`` are the grid
        lower-left corner in that CRS."""
        try:
            return _impl_set_model_crs(model, crs, xorigin, yorigin, angrot)
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
    ) -> dict:
        """Add a structured (DIS) grid to the model.

        ``idomain`` marks active/inactive cells: 1 = active, 0 = inactive,
        -1 = inactive (constant head under some formulations). A 2-D array
        (nrow, ncol) is broadcast across layers; a 3-D array is (nlay, nrow,
        ncol). Without it every cell is active."""
        try:
            return _impl_add_dis_package(
                model, nlay, nrow, ncol, delr, delc, top, botm, idomain
            )
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
    ) -> dict:
        """Add an unstructured vertex-based (DISV) grid to the model.

        Inline vertices/cell2d are rejected beyond 50,000 cells
        (PAYLOAD_TOO_LARGE) — pass gridprops_file (a JSON file with
        vertices/cell2d/top/botm) or use import_grid_from_shapefile
        (method='disv') for real Voronoi grids."""
        try:
            return _impl_add_disv_package(model, nlay, vertices, cell2d, top, botm, gridprops_file)
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
    ) -> dict:
        """Add a fully-unstructured (DISU) grid from explicit node connectivity.

        DISU is defined by ``nodes``/``nja`` plus per-edge connection data:
        ``iac`` (connections per node), ``ja`` (connected node ids, 0-based)
        and optionally ``ihc``/``cl12``/``hwva``/``angldegx``. Per-node ``top``
        and ``bot`` are required and ``area`` defaults to 1.0. Optional
        ``vertices``/``cell2d`` add cell x/y geometry (enabling coordinate
        observations and plan-view plots). Pass ``gridprops_file`` (JSON with
        any of these keys) for large grids.
        """
        try:
            return _impl_add_disu_package(
                model, nodes, nja, top, bot, area, iac, ja, ihc, cl12, hwva,
                angldegx, idomain, vertices, cell2d, nvert, gridprops_file,
            )
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
        are converted into the model's length/time convention (length metres,
        time from the model's time_units) on entry. Accepted k_units:
        m/d, m/s, m/yr, cm/s, ft/d, ft/s."""
        try:
            return _impl_add_npf_package(model, icelltype, k, k33, save_flows, k_units)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_ic_package(model: str, strt: float | list) -> dict:
        """Add an Initial Conditions (IC) package with starting heads."""
        try:
            return _impl_add_ic_package(model, strt)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
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
        0-based cellids, or ``{"filename": ...}`` to reference a
        pre-externalised file (then ``ninterbeds`` is required).
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
        = rates are already m/d); accepted: m/d, m/yr, mm/d, mm/yr. Rates are
        converted into m/d on entry.

        pname names the package in the model name file. Re-adding a package
        with the same pname (or with no pname) replaces the existing one(s) of
        that type; two packages of the same type with different pnames coexist
        (e.g. pname='chd_high' and pname='chd_lower').
        """
        try:
            return _impl_add_boundary_package(
                model, package, stress_period_data, kwargs, save_flows, rate_units, pname
            )
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
    ) -> dict:
        """Add an Output Control (OC) package."""
        try:
            return _impl_add_oc_package(
                model, head_filerecord, budget_filerecord, saverecord, printrecord
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def summarise_model(model: str) -> dict:
        """Return a structured summary of a model's packages, grid, and stress periods."""
        try:
            return _impl_summarise_model(model)
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
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("MODEL_STATUS_FAILED", str(exc))

    @mcp.tool()
    def list_model_files(model: str) -> dict:
        """List all files in the model workspace with sizes and extensions."""
        try:
            return _impl_list_model_files(model)
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
