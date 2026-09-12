"""spec.py — declarative model-spec schema, apply/diff, and export (7f-G1).

A model spec is a single JSON-serialisable dict describing the grid, layer
surfaces, properties, time discretisation, storage, boundaries, output control
and units of a model. ``apply_spec`` reconciles a spec onto a model in any
prior state and returns a structured diff; ``export_spec`` emits the spec for
an existing or adopted model.
"""

from __future__ import annotations

import hashlib

import numpy as np

from groundwater_mcp.utils.grid import get_dis, get_disv
from groundwater_mcp.utils.model_store import flush_model, get_gwf, get_sim, read_meta

_TOP_KEYS = {
    "name",
    "units",
    "time_units",
    "grid",
    "time",
    "properties",
    "initial_conditions",
    "storage",
    "boundaries",
    "output_control",
}
_GRID_KEYS = {"type", "nlay", "nrow", "ncol", "delr", "delc", "top", "botm",
              "idomain", "crs", "xorigin", "yorigin", "vertices", "cell2d"}
_TIME_KEYS = {"nper", "perlen", "nstp", "tsmult", "ims_complexity"}
_NPF_KEYS = {"icelltype", "k", "k33", "save_flows"}
_IC_KEYS = {"strt"}
_STO_KEYS = {"iconvert", "ss", "sy", "steady_state", "save_flows"}
_OC_KEYS = {"head_file", "budget_file", "saverecord", "printrecord"}

_SUPPORTED_BOUNDARY_PKGS = {"CHD", "WEL", "RIV", "DRN", "RCH", "EVT", "GHB", "SFR"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _unknown_keys(spec: dict, allowed: set[str], context: str) -> list[str]:
    return [k for k in spec if k not in allowed]


def validate_spec(spec: dict) -> None:
    """Validate a model spec, raising ValueError with a distinct message for
    unknown keys, missing required keys, and dimensional mismatches."""
    if not isinstance(spec, dict):
        raise ValueError("Spec must be a dict mapping section → configuration.")

    unknown = _unknown_keys(spec, _TOP_KEYS, "spec")
    if unknown:
        raise ValueError(
            f"Unknown spec key(s): {sorted(unknown)}. Valid keys: {sorted(_TOP_KEYS)}."
        )

    missing = [k for k in ("grid", "time") if k not in spec]
    if missing:
        raise ValueError(
            f"Missing required spec key(s): {missing}. 'grid' and 'time' are required."
        )

    grid = spec["grid"]
    if not isinstance(grid, dict) or "type" not in grid:
        raise ValueError("spec['grid'] must be a dict with a 'type' key ('DIS' or 'DISV').")
    grid_type = str(grid["type"]).upper()
    if grid_type not in ("DIS", "DISV"):
        raise ValueError(f"spec['grid']['type'] must be 'DIS' or 'DISV', got '{grid_type}'.")

    for key in ("nlay",):
        if key not in grid:
            raise ValueError(f"spec['grid'] missing required key '{key}'.")

    if grid_type == "DIS":
        for key in ("nrow", "ncol", "delr", "delc", "top", "botm"):
            if key not in grid:
                raise ValueError(f"spec['grid'] missing required key '{key}' for type='DIS'.")
        if len(grid["botm"]) != int(grid["nlay"]):
            raise ValueError(
                f"Dimensional mismatch: len(botm)={len(grid['botm'])} but nlay={grid['nlay']}."
            )
        for key in ("nrow", "ncol"):
            if int(grid[key]) <= 0:
                raise ValueError(f"spec['grid']['{key}'] must be positive, got {grid[key]}.")
    else:
        for key in ("vertices", "cell2d", "top", "botm"):
            if key not in grid:
                raise ValueError(f"spec['grid'] missing required key '{key}' for type='DISV'.")
        if len(grid["botm"]) != int(grid["nlay"]):
            raise ValueError(
                f"Dimensional mismatch: len(botm)={len(grid['botm'])} but nlay={grid['nlay']}."
            )

    time = spec["time"]
    if not isinstance(time, dict):
        raise ValueError("spec['time'] must be a dict.")
    for key in ("nper", "perlen", "nstp"):
        if key not in time:
            raise ValueError(f"spec['time'] missing required key '{key}'.")
    nper = int(time["nper"])
    if len(time["perlen"]) != nper:
        raise ValueError(
            f"Dimensional mismatch: len(perlen)={len(time['perlen'])} but nper={nper}."
        )
    if len(time["nstp"]) != nper:
        raise ValueError(
            f"Dimensional mismatch: len(nstp)={len(time['nstp'])} but nper={nper}."
        )

    for section, allowed, label in (
        ("properties", {"npf"}, "spec['properties']"),
    ):
        if section in spec and not isinstance(spec[section], dict):
            raise ValueError(f"{label} must be a dict.")
        if section in spec:
            unknown = _unknown_keys(spec[section], allowed, label)
            if unknown:
                raise ValueError(f"Unknown key(s) in {label}: {sorted(unknown)}.")

    if "npf" in spec.get("properties", {}):
        npf = spec["properties"]["npf"]
        unknown = _unknown_keys(npf, _NPF_KEYS, "spec['properties']['npf']")
        if unknown:
            raise ValueError(
                f"Unknown key(s) in spec['properties']['npf']: {sorted(unknown)}."
            )
        for key in ("icelltype", "k"):
            if key not in npf:
                raise ValueError(f"spec['properties']['npf'] missing required key '{key}'.")

    if "initial_conditions" in spec:
        unknown = _unknown_keys(spec["initial_conditions"], _IC_KEYS, "spec['initial_conditions']")
        if unknown:
            raise ValueError(f"Unknown key(s) in spec['initial_conditions']: {sorted(unknown)}.")

    if "storage" in spec:
        unknown = _unknown_keys(spec["storage"], _STO_KEYS, "spec['storage']")
        if unknown:
            raise ValueError(f"Unknown key(s) in spec['storage']: {sorted(unknown)}.")
        for key in ("iconvert", "ss"):
            if key not in spec["storage"]:
                raise ValueError(f"spec['storage'] missing required key '{key}'.")

    if "boundaries" in spec:
        if not isinstance(spec["boundaries"], dict):
            raise ValueError("spec['boundaries'] must be a dict of package → stress_period_data.")
        unknown = _unknown_keys(spec["boundaries"], _SUPPORTED_BOUNDARY_PKGS, "spec['boundaries']")
        if unknown:
            raise ValueError(
                f"Unknown boundary package(s) in spec['boundaries']: {sorted(unknown)}. "
                f"Supported: {sorted(_SUPPORTED_BOUNDARY_PKGS)}."
            )

    if "output_control" in spec:
        unknown = _unknown_keys(spec["output_control"], _OC_KEYS, "spec['output_control']")
        if unknown:
            raise ValueError(f"Unknown key(s) in spec['output_control']: {sorted(unknown)}.")


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def _normalised_hash(path) -> str:
    """Hash a package file, ignoring flopy's generation-timestamp header line."""
    text = path.read_bytes()
    if text.startswith(b"# File generated by"):
        parts = text.split(b"\n", 1)
        if len(parts) == 2:
            text = parts[1]
    return hashlib.sha1(text).hexdigest()


def _snapshot_hashes(model: str) -> dict[str, str]:
    """Flush the model and return {package_filename: content_hash}."""
    from groundwater_mcp.utils.workspace import resolve_workspace

    flush_model(model)
    ws = resolve_workspace(model)
    out: dict[str, str] = {}
    for p in sorted(ws.iterdir()):
        if p.is_file() and not p.name.startswith(".") and p.suffix != ".nam":
            if p.suffix in (".dis", ".disv", ".npf", ".ic", ".sto",
                            ".tdis", ".ims", ".oc", ".obs", ".wel", ".chd",
                            ".riv", ".drn", ".ghb", ".rch", ".evt", ".sfr"):
                out[p.name] = _normalised_hash(p)
    return out


def _diff_snapshots(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    """Return a structured diff of package files between two snapshots."""
    diff: list[dict] = []
    for name in sorted(set(before) | set(after)):
        if name not in after:
            diff.append({"package": name, "status": "removed"})
        elif name not in before:
            diff.append({"package": name, "status": "added"})
        elif before[name] != after[name]:
            diff.append({"package": name, "status": "replaced"})
        else:
            diff.append({"package": name, "status": "unchanged"})
    return diff


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_spec(model: str, spec: dict) -> dict:
    """Validate a spec and reconcile it onto a model in any prior state.

    Returns a structured diff of what changed (packages added/replaced/
    unchanged/removed) rather than a bare confirmation.
    """
    validate_spec(spec)
    before = _snapshot_hashes(model)

    from groundwater_mcp.tools.builder import (
        _impl_add_boundary_package,
        _impl_add_dis_package,
        _impl_add_disv_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_add_oc_package,
        _impl_add_sto_package,
        _impl_set_simulation,
    )

    time = spec["time"]
    _impl_set_simulation(
        model,
        nper=int(time["nper"]),
        perlen=[float(v) for v in time["perlen"]],
        nstp=[int(v) for v in time["nstp"]],
        ims_complexity=str(time.get("ims_complexity", "moderate")),
    )

    grid = spec["grid"]
    grid_type = str(grid["type"]).upper()
    if grid_type == "DIS":
        _impl_add_dis_package(
            model,
            nlay=int(grid["nlay"]),
            nrow=int(grid["nrow"]),
            ncol=int(grid["ncol"]),
            delr=grid["delr"],
            delc=grid["delc"],
            top=grid["top"],
            botm=grid["botm"],
        )
    else:
        _impl_add_disv_package(
            model,
            nlay=int(grid["nlay"]),
            vertices=grid["vertices"],
            cell2d=grid["cell2d"],
            top=grid["top"],
            botm=grid["botm"],
        )

    props = spec.get("properties", {}).get("npf")
    if props is not None:
        _impl_add_npf_package(
            model,
            icelltype=props["icelltype"],
            k=props["k"],
            k33=props.get("k33"),
            save_flows=bool(props.get("save_flows", True)),
        )

    if "initial_conditions" in spec:
        _impl_add_ic_package(model, strt=spec["initial_conditions"]["strt"])

    if "storage" in spec:
        sto = spec["storage"]
        _impl_add_sto_package(
            model,
            iconvert=sto["iconvert"],
            ss=sto["ss"],
            sy=sto.get("sy"),
            steady_state=sto.get("steady_state"),
            save_flows=bool(sto.get("save_flows", True)),
        )

    for pkg_name, spd in spec.get("boundaries", {}).items():
        _impl_add_boundary_package(model, pkg_name, spd, None)

    oc = spec.get("output_control")
    if oc is not None:
        _impl_add_oc_package(
            model,
            head_filerecord=oc.get("head_file"),
            budget_filerecord=oc.get("budget_file"),
            saverecord=oc.get("saverecord"),
            printrecord=oc.get("printrecord"),
        )

    after = _snapshot_hashes(model)
    diff = _diff_snapshots(before, after)
    return {
        "model": model,
        "changed": [d for d in diff if d["status"] != "unchanged"],
        "unchanged": [d["package"] for d in diff if d["status"] == "unchanged"],
        "packages": [d["package"] for d in diff],
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _arr(v) -> float | list:
    """Convert a flopy array value into a JSON-serialisable structure."""
    a = np.asarray(v)
    if a.ndim == 0:
        return float(a)
    return a.tolist()


def _export_boundaries(model: str) -> dict[str, dict]:
    gwf = get_gwf(model)
    from groundwater_mcp.tools.builder import _BOUNDARY_PKG_CLASSES

    out: dict[str, dict] = {}
    for pkg_name in _BOUNDARY_PKG_CLASSES:
        pkg = gwf.get_package(pkg_name.lower())
        if pkg is None:
            continue
        spd: dict[str, list] = {}
        try:
            data = pkg.stress_period_data.get_data()
        except Exception:
            continue
        for sp_key, rec in data.items():
            if rec is None:
                continue
            records = []
            for row in rec:
                row_dict = {name: row[name] for name in rec.dtype.names}
                cellid = row_dict.pop("cellid", None)
                entry: list[object] = [list(cellid)] if cellid is not None else []
                for name, v in row_dict.items():
                    kind = rec.dtype.fields[name][0].kind
                    if kind in "iuf":
                        entry.append(float(v))
                    elif kind == "b":
                        entry.append(bool(v))
                    else:
                        # Text columns (e.g. WEL boundname, string aux) are
                        # preserved as strings rather than float()-cast.
                        if isinstance(v, (bytes, bytearray)):
                            v = v.decode("utf-8", "replace")
                        if v is None:
                            s = ""
                        else:
                            s = str(v)
                        entry.append("" if s.strip() == "" else s)
                records.append(entry)
            spd[str(sp_key)] = records
        if spd:
            out[pkg_name] = spd
    return out


def export_spec(model: str) -> dict:
    """Emit the declarative spec for an existing or adopted model."""
    sim = get_sim(model)
    gwf = get_gwf(model)
    meta = read_meta(model)

    spec: dict = {
        "name": model,
        "units": meta.get("units", "METERS"),
        "time_units": meta.get("time_units", "DAYS"),
    }

    dis = get_dis(gwf)
    disv = get_disv(gwf)
    if dis is not None:
        spec["grid"] = {
            "type": "DIS",
            "nlay": int(dis.nlay.data),
            "nrow": int(dis.nrow.data),
            "ncol": int(dis.ncol.data),
            "delr": _arr(dis.delr.array),
            "delc": _arr(dis.delc.array),
            "top": _arr(dis.top.array),
            "botm": _arr(dis.botm.array),
        }
        crs = getattr(gwf.modelgrid, "crs", None)
        if crs is not None:
            spec["grid"]["crs"] = str(crs)
    elif disv is not None:
        spec["grid"] = {
            "type": "DISV",
            "nlay": int(disv.nlay.data),
            "vertices": _arr(disv.vertices.array),
            "cell2d": _arr(disv.cell2d.array),
            "top": _arr(disv.top.array),
            "botm": _arr(disv.botm.array),
        }

    tdis = sim.get_package("tdis")
    if tdis is not None:
        perioddata = [list(r) for r in tdis.perioddata.array]
        spec["time"] = {
            "nper": len(perioddata),
            "perlen": [float(r[0]) for r in perioddata],
            "nstp": [int(r[1]) for r in perioddata],
            "tsmult": float(perioddata[0][2]) if perioddata else 1.0,
        }
    ims = sim.get_package("ims")
    if ims is not None:
        spec["time"]["ims_complexity"] = str(ims.complexity.array).lower()

    npf = gwf.get_package("npf")
    if npf is not None:
        props: dict = {"icelltype": _arr(npf.icelltype.array), "k": _arr(npf.k.array)}
        if npf.k33.array is not None:
            props["k33"] = _arr(npf.k33.array)
        if getattr(npf, "save_flows", None) is not None:
            props["save_flows"] = bool(npf.save_flows.array)
        spec["properties"] = {"npf": props}

    ic = gwf.get_package("ic")
    if ic is not None:
        spec["initial_conditions"] = {"strt": _arr(ic.strt.array)}

    sto = gwf.get_package("sto")
    if sto is not None:
        st = {"iconvert": _arr(sto.iconvert.array), "ss": _arr(sto.ss.array)}
        if sto.sy.array is not None:
            st["sy"] = _arr(sto.sy.array)
        if "sto_steady_state" in meta:
            st["steady_state"] = list(meta.get("sto_steady_state", []))
        spec["storage"] = st

    boundaries = _export_boundaries(model)
    if boundaries:
        spec["boundaries"] = boundaries

    oc = gwf.get_package("oc")
    if oc is not None:
        spec["output_control"] = {}
        for attr in ("head_file", "budget_file"):
            val = getattr(oc, attr, None)
            if val is not None:
                try:
                    spec["output_control"][attr] = str(val.array)
                except Exception:
                    pass

    return spec
