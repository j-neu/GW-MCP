"""legacy_transport.py — adopt and cache legacy MODFLOW-2005 + MT3D-USGS models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import flopy

from groundwater_mcp.utils.model_store import read_meta
from groundwater_mcp.utils.workspace import resolve_workspace

_FLOW_PACKAGES = {
    "DIS", "BAS6", "LPF", "BCF6", "OC", "WEL", "RCH", "CHD", "RIV", "DRN",
    "GHB", "EVT", "PCG", "SIP", "SOR", "MULT", "ZONE", "SUB", "SWI", "HFB",
}
_TRANSPORT_PACKAGES = {
    "BTN", "ADV", "DSP", "SSM", "GCG", "RCT", "SFT", "UZT", "LKT", "TOB", "PHC",
}


@dataclass
class LegacyTransportModel:
    name: str
    workspace: Path
    flow_model: object
    transport_model: object
    flow_nam: str
    transport_nam: str
    version: str = "mt3d-usgs"


_LEGACY_CACHE: dict[str, LegacyTransportModel] = {}


def clear() -> None:
    _LEGACY_CACHE.clear()


def read_nam_packages(nam: Path) -> set[str]:
    """Return the package tokens listed in a MODFLOW/MT3D name file."""
    pkgs: set[str] = set()
    for line in nam.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            pkgs.add(parts[0].upper())
    pkgs.discard("LIST")
    pkgs.discard("FTL")
    return pkgs


def _discover_nam_files(workspace: Path) -> tuple[Path, Path]:
    nams = sorted(
        p for p in workspace.iterdir()
        if p.is_file() and p.suffix.lower() == ".nam"
    )
    if not nams:
        raise FileNotFoundError(
            f"No .nam file found in {workspace}. adopt_mt3d_usgs_model "
            "registers an existing MODFLOW-2005 + MT3D-USGS directory."
        )
    flow: list[Path] = []
    transport: list[Path] = []
    for nam in nams:
        pkgs = read_nam_packages(nam)
        if pkgs & _TRANSPORT_PACKAGES:
            transport.append(nam)
        elif pkgs & _FLOW_PACKAGES:
            flow.append(nam)
    if len(flow) == 1 and len(transport) == 1:
        return flow[0], transport[0]
    raise ValueError(
        f"Could not identify exactly one MODFLOW-2005 name file and one MT3D "
        f"name file in {workspace}. Found flow={[p.name for p in flow]}, "
        f"transport={[p.name for p in transport]}. Pass flow_nam/transport_nam."
    )


def _resolve(workspace: Path, nam: str | Path | None) -> Path | None:
    if nam is None:
        return None
    p = Path(nam)
    return p if p.is_absolute() else workspace / p


def adopt_legacy_mt3d_usgs(
    name: str,
    workspace,
    flow_nam: str | None = None,
    transport_nam: str | None = None,
    allow_modify: bool = False,
) -> LegacyTransportModel:
    ws = Path(workspace)
    if flow_nam is None or transport_nam is None:
        d_flow, d_transport = _discover_nam_files(ws)
        if flow_nam is None:
            flow_nam = d_flow.name
        if transport_nam is None:
            transport_nam = d_transport.name

    flow_path = _resolve(ws, flow_nam)
    assert flow_path is not None
    if not flow_path.exists():
        raise FileNotFoundError(f"MODFLOW-2005 name file not found: {flow_path}")

    flow_model = flopy.modflow.Modflow.load(
        flow_path.name, version="mf2005", exe_name="mf2005",
        model_ws=str(ws), verbose=False, check=False,
    )
    if getattr(flow_model, "dis", None) is None:
        raise ValueError(
            "Legacy MT3D-USGS post-processing requires a structured DIS flow "
            "model; DISU/DISV flow grids are not supported."
        )

    trans_path = _resolve(ws, transport_nam)
    assert trans_path is not None
    if not trans_path.exists():
        raise FileNotFoundError(f"MT3D name file not found: {trans_path}")
    transport_model = flopy.mt3d.Mt3dms.load(
        trans_path.name, version="mt3d-usgs", model_ws=str(ws),
        modflowmodel=flow_model, verbose=False,
    )

    legacy = LegacyTransportModel(
        name=name, workspace=ws, flow_model=flow_model,
        transport_model=transport_model,
        flow_nam=flow_path.name, transport_nam=trans_path.name,
    )
    _LEGACY_CACHE[name] = legacy
    return legacy


def get_legacy_model(name: str) -> LegacyTransportModel:
    legacy = _LEGACY_CACHE.get(name)
    if legacy is not None:
        return legacy
    block = (read_meta(name) or {}).get("legacy")
    if not block:
        raise KeyError(f"'{name}' is not a registered MT3D-USGS model.")
    ws = resolve_workspace(name)
    return adopt_legacy_mt3d_usgs(
        name, ws, flow_nam=block.get("flow_nam"),
        transport_nam=block.get("transport_nam"),
    )


def is_legacy(name: str) -> bool:
    if name in _LEGACY_CACHE:
        return True
    try:
        return bool((read_meta(name) or {}).get("legacy"))
    except Exception:
        return False
