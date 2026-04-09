"""builder module — create and configure MODFLOW 6 GWF models via FloPy."""

from __future__ import annotations

import json
from pathlib import Path

import flopy.mf6 as mf6

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


def _impl_add_boundary_package(
    model: str,
    package: str,
    stress_period_data: dict,
    kwargs: dict | None,
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
    if existing is not None:
        gwf.remove_package(existing)

    pkg_kwargs = kwargs or {}
    pkg_cls(gwf, stress_period_data=spd, **pkg_kwargs)
    save_sim(model, gwf.simulation)

    cell_counts = {sp: len(rows) for sp, rows in spd.items()}
    return {
        "model": model,
        "package": pkg_name,
        "stress_periods": cell_counts,
    }


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

    return {
        "model": model,
        "workspace": str(ws),
        "packages": package_list,
        "grid": grid_info,
        "stress_periods": stress_periods,
        "boundary_types": boundary_types,
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
        """Create a new MODFLOW 6 GWF model workspace."""
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
    def add_boundary_package(
        model: str,
        package: str,
        stress_period_data: dict,
        kwargs: dict | None = None,
    ) -> dict:
        """Add a boundary condition package (CHD, WEL, RIV, DRN, RCH, EVT, GHB, SFR)."""
        try:
            return _impl_add_boundary_package(model, package, stress_period_data, kwargs)
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
