"""builder module — create and configure MODFLOW 6 GWF models via FloPy."""

from __future__ import annotations

import json
from pathlib import Path

import flopy.mf6 as mf6
import numpy as np

from groundwater_mcp.utils.model_store import get_gwf, get_sim, save_sim
from groundwater_mcp.utils.workspace import create_workspace, resolve_workspace

# ---------------------------------------------------------------------------
# Supported boundary packages
# ---------------------------------------------------------------------------

_BOUNDARY_PKG_CLASSES: dict[str, type] = {
    "CHD": mf6.ModflowGwfchd,
    "WEL": mf6.ModflowGwfwel,
    "RIV": mf6.ModflowGwfriv,
    "DRN": mf6.ModflowGwfdrn,
    "RCH": mf6.ModflowGwfrch,
    "EVT": mf6.ModflowGwfevt,
    "GHB": mf6.ModflowGwfghb,
    "SFR": mf6.ModflowGwfsfr,
}

# ---------------------------------------------------------------------------
# Shared error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


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
    save_sim(name, sim)
    return {
        "model": name,
        "workspace": str(model_dir),
        "units": units.upper(),
        "time_units": time_units.upper(),
    }


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

    save_sim(model, sim)
    return {
        "model": model,
        "nper": nper,
        "time_units": time_units,
        "ims_complexity": ims_complexity.upper(),
        "total_time": sum(perlen),
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
) -> dict:
    if len(botm) != nlay:
        raise ValueError(f"len(botm)={len(botm)} must equal nlay={nlay}.")

    gwf = get_gwf(model)
    pkg = gwf.get_package("dis")
    if pkg is not None:
        gwf.remove_package(pkg)

    mf6.ModflowGwfdis(
        gwf,
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm,
    )
    save_sim(model, gwf.simulation)
    return {
        "model": model,
        "grid_type": "DIS",
        "nlay": nlay,
        "nrow": nrow,
        "ncol": ncol,
        "ncells": nlay * nrow * ncol,
    }


def _impl_add_disv_package(
    model: str,
    nlay: int,
    vertices: list,
    cell2d: list,
    top: list,
    botm: list,
) -> dict:
    ncpl = len(cell2d)
    nvert = len(vertices)
    if len(botm) != nlay:
        raise ValueError(f"len(botm)={len(botm)} must equal nlay={nlay}.")

    gwf = get_gwf(model)
    pkg = gwf.get_package("disv")
    if pkg is not None:
        gwf.remove_package(pkg)

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
    save_sim(model, gwf.simulation)
    return {
        "model": model,
        "grid_type": "DISV",
        "nlay": nlay,
        "ncpl": ncpl,
        "nvert": nvert,
        "ncells": nlay * ncpl,
    }


def _impl_add_npf_package(
    model: str,
    icelltype: int | list,
    k: float | list,
    k33: float | list | None,
    save_flows: bool,
) -> dict:
    gwf = get_gwf(model)
    pkg = gwf.get_package("npf")
    if pkg is not None:
        gwf.remove_package(pkg)

    kwargs: dict = {"icelltype": icelltype, "k": k, "save_flows": save_flows}
    if k33 is not None:
        kwargs["k33"] = k33

    mf6.ModflowGwfnpf(gwf, **kwargs)
    save_sim(model, gwf.simulation)
    return {"model": model, "package": "NPF", "save_flows": save_flows}


def _impl_add_ic_package(model: str, strt: float | list) -> dict:
    gwf = get_gwf(model)
    pkg = gwf.get_package("ic")
    if pkg is not None:
        gwf.remove_package(pkg)

    mf6.ModflowGwfic(gwf, strt=strt)
    save_sim(model, gwf.simulation)
    return {"model": model, "package": "IC"}


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
    save_sim(model, sim)

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
    }
    if replaced:
        result["warning"] = "A previous STO package was removed and replaced by this call."
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
) -> dict:
    pkg_name = package.upper()
    if pkg_name not in _BOUNDARY_PKG_CLASSES:
        raise ValueError(
            f"Unsupported package '{pkg_name}'. "
            f"Choose from: {', '.join(_BOUNDARY_PKG_CLASSES)}."
        )

    # Convert JSON string keys to int keys
    spd = {int(k): v for k, v in stress_period_data.items()}

    gwf = get_gwf(model)
    pkg_cls = _BOUNDARY_PKG_CLASSES[pkg_name]

    # Remove existing package of same type if present (allow re-adding)
    existing = gwf.get_package(pkg_name.lower())
    replaced = existing is not None
    if existing is not None:
        gwf.remove_package(existing)

    pkg_kwargs = dict(kwargs or {})
    if "save_flows" not in pkg_kwargs:
        pkg_kwargs["save_flows"] = save_flows
    pkg_cls(gwf, stress_period_data=spd, **pkg_kwargs)
    save_sim(model, gwf.simulation)

    cell_counts = {sp: len(rows) for sp, rows in spd.items()}
    result: dict = {
        "model": model,
        "package": pkg_name,
        "stress_periods": cell_counts,
        "save_flows": bool(pkg_kwargs.get("save_flows", save_flows)),
    }
    if replaced:
        result["warning"] = (
            f"A previous {pkg_name} package was removed and replaced by this "
            "call. If that was unintentional (e.g. two separate CHD sets were "
            "meant to be combined), re-add the boundary in a single call."
        )
    return result


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
    save_sim(model, gwf.simulation)
    return {
        "model": model,
        "package": "OC",
        "head_file": head_file,
        "budget_file": budget_file,
    }


def _impl_summarise_model(model: str) -> dict:
    sim = get_sim(model)
    gwf = get_gwf(model)
    ws = resolve_workspace(model)

    # Packages present on the GWF model
    package_list = gwf.get_package_list()

    # Grid info
    grid_info: dict = {}
    dis_pkg = gwf.get_package("dis")
    disv_pkg = gwf.get_package("disv")
    if dis_pkg is not None:
        grid_info = {
            "type": "DIS",
            "nlay": int(dis_pkg.nlay.data),
            "nrow": int(dis_pkg.nrow.data),
            "ncol": int(dis_pkg.ncol.data),
            "ncells": int(dis_pkg.nlay.data * dis_pkg.nrow.data * dis_pkg.ncol.data),
        }
    elif disv_pkg is not None:
        grid_info = {
            "type": "DISV",
            "nlay": int(disv_pkg.nlay.data),
            "ncpl": int(disv_pkg.ncpl.data),
            "ncells": int(disv_pkg.nlay.data * disv_pkg.ncpl.data),
        }

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

    return {
        "model": model,
        "workspace": str(ws),
        "packages": package_list,
        "grid": grid_info,
        "stress_periods": stress_periods,
        "boundary_types": boundary_types,
        "storage": storage,
    }


def _impl_list_model_files(model: str) -> dict:
    ws = resolve_workspace(model)
    files = []
    for f in sorted(ws.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            files.append({
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "extension": f.suffix,
            })
    return {"model": model, "workspace": str(ws), "files": files}


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
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("SET_SIM_FAILED", str(exc))

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
    ) -> dict:
        """Add a structured (DIS) grid to the model."""
        try:
            return _impl_add_dis_package(model, nlay, nrow, ncol, delr, delc, top, botm)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
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
    ) -> dict:
        """Add an unstructured vertex-based (DISV) grid to the model."""
        try:
            return _impl_add_disv_package(model, nlay, vertices, cell2d, top, botm)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
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
    ) -> dict:
        """Add a Node Property Flow (NPF) package defining hydraulic conductivity."""
        try:
            return _impl_add_npf_package(model, icelltype, k, k33, save_flows)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))

    @mcp.tool()
    def add_ic_package(model: str, strt: float | list) -> dict:
        """Add an Initial Conditions (IC) package with starting heads."""
        try:
            return _impl_add_ic_package(model, strt)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
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
    ) -> dict:
        """Add a boundary condition package (CHD, WEL, RIV, DRN, RCH, EVT, GHB, SFR).

        stress_period_data maps a stress-period index (0-based, matching the
        nper/perioddata set in set_simulation) to a list of records.  Each
        record uses 0-based cell indices (layer, row, col) for DIS grids and
        (layer, node) for DISV grids — indices are converted to the 1-based
        form written to the package file.  Example:
        ``{"0": [[[0, 2, 3], 55.0], [[0, 2, 4], 55.0]]}``

        save_flows writes the SAVE FLOWS option into the package file so the
        package's fluxes appear in the budget file for compute_water_balance.
        """
        try:
            return _impl_add_boundary_package(
                model, package, stress_period_data, kwargs, save_flows
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
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
    def list_model_files(model: str) -> dict:
        """List all files in the model workspace with sizes and extensions."""
        try:
            return _impl_list_model_files(model)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("LIST_FILES_FAILED", str(exc))
