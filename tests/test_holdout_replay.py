"""Phase C Mode A — holdout replay tests (pre-registered protocol).

Replays the build -> run -> postprocess sequence from sealed holdout projects
against the frozen v0.1.0 tool set, through the in-process FastMCP layer
(mcp.list_tools / mcp.call_tool), exactly like test_mcp_protocol.py.

The holdout lives OUTSIDE the repo (sibling ``GW-MCP-holdout/`` folder, or
wherever ``GW_MCP_HOLDOUT`` points). All tests skip when the holdout is not
configured, so no holdout data ever enters the repo — the validation seal is
preserved by construction.

Pre-registered success criteria (research/holdout-registry.md):
  - Build:  create_model -> packages -> check_model, no fatal errors
  - Run:    run_simulation succeeds and converges
  - Outputs plausible: heads in expected range; water-balance closure
  - Post-process: read_heads, read_budget, plot_heads_map valid
  - Known-limitation gate: GAP-capability projects fail cleanly with
    actionable structured errors — the expected v0.1.0 outcome (validates the
    error envelope, not the feature).

Mode A v1 scope (documented deviations):
  - Grid + time discretisation replayed faithfully from the holdout .dis/.tdis
    (via FloPy's loader, which handles all MF6 array formats).
  - Boundaries: WEL/GHB stress data parsed from the holdout files when
    present; projects whose only stress packages are GAP capabilities (MAW)
    get a synthetic CHD gradient instead (deviation noted per project).
  - NPF/IC use constant values; STO/UZF/MAW/OBS packages are NOT replayed —
    they are GAP/partial matrix rows covered by the known-limitation gate.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from groundwater_mcp.server import mcp
from groundwater_mcp.tools.runner import _find_mf6_binary

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_mcp_protocol.py)
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously (avoids adding pytest-asyncio dependency)."""
    return asyncio.run(coro)


def _parse(result) -> dict | list:
    """Extract and parse the JSON payload from a call_tool result list."""
    assert result, "call_tool returned an empty result list"
    return json.loads(result[0].text)


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)


# ---------------------------------------------------------------------------
# Holdout discovery — env var GW_MCP_HOLDOUT, else sibling folder
# ---------------------------------------------------------------------------

_DEFAULT_HOLDOUT = (
    Path(__file__).resolve().parent.parent.parent / "GW-MCP-holdout"
)


def _holdout_root() -> Path | None:
    env = os.environ.get("GW_MCP_HOLDOUT")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    return _DEFAULT_HOLDOUT if _DEFAULT_HOLDOUT.is_dir() else None


@pytest.fixture(scope="session")
def holdout_root() -> Path:
    """The sealed holdout folder; skips the whole module when absent."""
    root = _holdout_root()
    if root is None:
        pytest.skip(
            "Holdout not configured: set GW_MCP_HOLDOUT or create the sibling "
            "GW-MCP-holdout/ folder next to the repo."
        )
    return root


def _selected_dir(root: Path, name: str) -> Path:
    return root / "selected" / name


# ---------------------------------------------------------------------------
# Holdout project loading (read-only; never copies into the repo)
# ---------------------------------------------------------------------------


def _load_project(project_dir: Path) -> dict:
    """Load grid, time discretisation and simple boundary stress from a holdout
    project via FloPy (read-only; never copies into the repo).

    FloPy's loader handles CONSTANT / INTERNAL / open-close array formats and
    normalises 1-based file cellids to 0-based, so the boundary records match
    the MCP stress_period_data schema exactly.
    """
    import flopy.mf6 as mf6
    import numpy as np

    sim = mf6.MFSimulation.load(sim_ws=str(project_dir), verbosity_level=0)
    gwf = sim.get_model(sim.model_names[0])
    dis = gwf.get_package("dis")
    assert dis is not None, f"no DIS package in {project_dir.name}"

    nlay = int(dis.nlay.array)
    nrow = int(dis.nrow.array)
    ncol = int(dis.ncol.array)

    perlen: list[float] = []
    nstp: list[int] = []
    tsmult: list[float] = []
    for row in sim.tdis.perioddata.array:
        perlen.append(float(row[0]))
        nstp.append(int(row[1]))
        tsmult.append(float(row[2]))

    # CONSTANT blocks load as flat arrays — reshape to canonical dims.
    delr = np.asarray(dis.delr.array, dtype=float).reshape(ncol).tolist()
    delc = np.asarray(dis.delc.array, dtype=float).reshape(nrow).tolist()
    top_arr = np.asarray(dis.top.array, dtype=float).reshape(nrow, ncol)
    botm_flat = np.asarray(dis.botm.array, dtype=float)
    n_botm = botm_flat.size // (nrow * ncol)
    if n_botm == nlay + 1:
        # BOTM includes the top-of-layer-1 duplicate (canonical MF6 form)
        botm_full = botm_flat.reshape(nlay + 1, nrow, ncol)
        botm_arrs = list(botm_full[1:])
    else:
        # BOTM holds only the layer bottoms (as written by MF5to6)
        botm_full = botm_flat.reshape(nlay, nrow, ncol)
        botm_arrs = list(botm_full)

    # add_dis_package does not expose idomain (v0.2.0 item), so cells that the
    # original marks inactive (top == botm == 0) would be zero-thickness and
    # fatal. Deviation: give them a minimum 1-unit thickness.
    for b in botm_arrs:
        thin = (top_arr - b) <= 0
        if thin.any():
            b[thin] = top_arr[thin] - 1.0

    top = top_arr.tolist()
    botm = [b.tolist() for b in botm_arrs]

    # Simple boundary packages (WEL/GHB) — only fully-replayed packages.
    boundaries: dict[str, dict] = {}
    for pkg in ("WEL", "GHB"):
        p = gwf.get_package(pkg.lower())
        if p is None:
            continue
        spd: dict[str, list] = {}
        for per, frame in p.stress_period_data.get_data().items():
            records = []
            names = frame.dtype.names
            for row in frame:
                cellid = row["cellid"]
                cellid = [int(v) for v in cellid] if hasattr(cellid, "__iter__") else [int(cellid)]
                records.append([cellid, *[float(row[n]) for n in names if n != "cellid"]])
            if records:
                spd[str(per)] = records
        if spd:
            boundaries[pkg] = spd

    return {
        "name": project_dir.name,
        "nlay": nlay,
        "nrow": nrow,
        "ncol": ncol,
        "delr": delr,
        "delc": delc,
        "top": top,
        "botm": botm,
        "perlen": perlen,
        "nstp": nstp,
        "tsmult": tsmult,
        "top_max": float(np.asarray(top).max()),
        "botm_min": float(botm_flat.min()),
        "boundaries": boundaries,
    }


# Per-project replay notes:
#   - boundaries: WEL/GHB replayed from the holdout files (flopy-normalised);
#     GAP stress packages (SFR/UZF/STO/MAW) are not replayed at v0.1.0.
#   - balance_expected: water-balance closure is only asserted when ALL stress
#     is replayed (test020: CHD only). test051's SFR/UZF/STO stresses are GAP
#     capabilities, so its replayed WEL+GHB budget cannot close — the closure
#     criterion applies to fully-replayed projects only (v1 limitation).
_BOUNDARY_FILES: dict[str, list[str]] = {
    "test051_uzfp2": ["WEL", "GHB"],
    "test020_NevilleTonkinTransient": [],  # only MAW stress — GAP; synthetic CHD instead
}
_BALANCE_EXPECTED: dict[str, bool] = {
    "test051_uzfp2": False,  # partial stress replay (SFR/UZF/STO are GAP)
    "test020_NevilleTonkinTransient": True,  # CHD-only, fully replayed
}


# ---------------------------------------------------------------------------
# Flow-project replay (build -> run -> postprocess)
# ---------------------------------------------------------------------------

_FLOW_PROJECTS = ["test051_uzfp2", "test020_NevilleTonkinTransient"]


@pytest.fixture(params=_FLOW_PROJECTS)
def flow_project(request, holdout_root):
    """Parametrized sealed flow project: (name, project_dir)."""
    name = request.param
    project_dir = _selected_dir(holdout_root, name)
    if not project_dir.is_dir():
        pytest.skip(f"holdout project {name} not present under {project_dir}")
    return name, project_dir


def _call(name: str, args: dict) -> dict:
    """Call an MCP tool and assert it did not return an error envelope."""
    data = _parse(_run(mcp.call_tool(name, args)))
    assert "error" not in data, f"{name} returned an error: {data}"
    return data


def _build_flow_model(project_dir: Path, model_name: str, ws_str: str) -> dict:
    """Replay the build phase via MCP tools, geometry from the holdout project."""
    proj = _load_project(project_dir)

    _call("create_model", {
        "name": model_name,
        "workspace": ws_str,
        "units": "METERS",
        "time_units": "DAYS",
    })
    _call("set_simulation", {
        "model": model_name,
        "nper": len(proj["perlen"]),
        "perlen": proj["perlen"],
        "nstp": proj["nstp"],
        "ims_complexity": "simple",
    })
    _call("add_dis_package", {
        "model": model_name,
        "nlay": proj["nlay"],
        "nrow": proj["nrow"],
        "ncol": proj["ncol"],
        "delr": proj["delr"],
        "delc": proj["delc"],
        "top": proj["top"],
        "botm": proj["botm"],
    })
    _call("add_npf_package", {
        "model": model_name,
        "icelltype": 0,
        "k": 10.0,
        "save_flows": True,
    })
    _call("add_ic_package", {"model": model_name, "strt": proj["top_max"]})
    _call("add_oc_package", {"model": model_name})

    # Boundaries: WEL/GHB from holdout files (flopy-normalised cellids) when
    # present; otherwise a synthetic CHD gradient (deviation noted above).
    if _BOUNDARY_FILES.get(project_dir.name):
        for pkg in _BOUNDARY_FILES[project_dir.name]:
            spd = proj["boundaries"].get(pkg)
            assert spd, f"no stress-period data loaded for {pkg} in {project_dir.name}"
            _call("add_boundary_package", {
                "model": model_name,
                "package": pkg,
                "stress_period_data": spd,
            })
    else:
        nrow, ncol = proj["nrow"], proj["ncol"]
        chd = []
        for row in range(nrow):
            chd.append([[0, row, 0], proj["top_max"]])
            chd.append([[0, row, ncol - 1], proj["botm_min"]])
        _call("add_boundary_package", {
            "model": model_name,
            "package": "CHD",
            "stress_period_data": {"0": chd},
        })

    return proj


@requires_mf6
def test_replay_flow_build_check_run_postprocess(flow_project, tmp_path):
    """Pre-registered criteria: build, check, run, plausible heads, postprocess."""
    name, project_dir = flow_project
    # MODFLOW 6 caps MODELNAME at 16 characters — use a short replay name.
    model_name = f"ho_{_FLOW_PROJECTS.index(name) + 1}"
    proj = _build_flow_model(project_dir, model_name, str(tmp_path / model_name))

    # Build gate: check_model without fatal errors
    r = _call("check_model", {"model": model_name})
    assert r["check_passed"] is True, f"check_model not clean: {r}"
    assert r["errors"] == [], f"check_model reported errors: {r['errors']}"

    # Run gate: converges
    r = _call("run_simulation", {"model": model_name, "silent": True})
    assert r["success"] is True, f"run_simulation did not converge: {r}"
    assert r["convergence"] == "converged"

    # Outputs plausible: heads within [botm_min, top_max]
    r = _call("read_heads", {"model": model_name, "layer": 0})
    assert r["shape"] == [proj["nrow"], proj["ncol"]], f"head shape wrong: {r}"
    assert r["min"] is not None and r["max"] is not None
    assert r["min"] >= proj["botm_min"] - 1.0, f"heads below bottom: {r['min']}"
    assert r["max"] <= proj["top_max"] + 1.0, f"heads above top: {r['max']}"

    # Post-processing: budget read + water-balance closure. Closure is only
    # asserted for fully-replayed stress (see _BALANCE_EXPECTED); partially
    # replayed projects (GAP stress packages) assert valid structure only.
    r = _call("read_budget", {"model": model_name})
    assert isinstance(r["records"], list) and len(r["records"]) > 0

    r = _call("compute_water_balance", {"model": model_name})
    if _BALANCE_EXPECTED.get(project_dir.name, False):
        scale = max(abs(r["total_inflow"]), abs(r["total_outflow"]), 1.0)
        assert abs(r["net_balance"]) <= 1e-3 * scale, (
            f"water balance not closed: net={r['net_balance']} "
            f"in={r['total_inflow']} out={r['total_outflow']}"
        )

    # Post-processing: head map PNG
    r = _call("plot_heads_map", {"model": model_name, "layer": 0})
    png = Path(r["output_file"])
    assert png.exists() and png.stat().st_size > 0, f"PNG not produced: {r}"


# ---------------------------------------------------------------------------
# Known-limitation gate — GAP capabilities must fail cleanly at v0.1.0
# ---------------------------------------------------------------------------

_GAP_TOOLS = [
    "add_disu_package",
    "add_maw_package",
    "add_uzf_package",
    "add_lak_package",
    "add_gnc_package",
    "add_mvr_package",
    "add_sto_package",
    "add_gwt_package",
    "add_swt_package",
    "add_obs_package",
]


def test_gap_tools_not_exposed(holdout_root):
    """GAP capabilities must not be exposed at v0.1.0 (frozen 36 tools)."""
    tools = {t.name for t in _run(mcp.list_tools())}
    leaked = [t for t in _GAP_TOOLS if t in tools]
    assert not leaked, f"GAP capability tools must not exist at v0.1.0: {leaked}"


def test_gap_unsupported_boundary_fails_cleanly(holdout_root):
    """Requesting a GAP boundary package returns the structured error envelope."""
    for pkg in ("MAW", "UZF", "LAK", "GNC", "MVR"):
        data = _parse(_run(mcp.call_tool("add_boundary_package", {
            "model": "ghost_model",
            "package": pkg,
            "stress_period_data": {"0": []},
        })))
        assert data.get("error") is True, f"{pkg} did not fail cleanly: {data}"
        assert data.get("code"), f"error envelope missing code for {pkg}: {data}"
        assert data.get("message"), f"error envelope missing message for {pkg}: {data}"
        assert "suggestion" in data, f"error envelope missing suggestion for {pkg}: {data}"


def test_gap_disu_project_has_no_tool_path(holdout_root):
    """The sealed DISU project cannot be built at v0.1.0 — that is the point.

    The holdout keeps it for v0.2.0 validation; at v0.1.0 the limitation must
    be explicit (no tool claims DISU support).
    """
    project_dir = _selected_dir(holdout_root, "test009_3lay-disu")
    if not project_dir.is_dir():
        pytest.skip("holdout project test009_3lay-disu not present")
    tools = {t.name for t in _run(mcp.list_tools())}
    assert "add_disu_package" not in tools
    assert "add_disv_package" in tools  # DISV exists; DISU must not be confused with it


def test_gap_transport_projects_present_and_ungated(holdout_root):
    """GWT projects are sealed for v0.2.0; no transport tools at v0.1.0."""
    tools = {t.name for t in _run(mcp.list_tools())}
    assert not any(t.startswith("add_gwt") for t in tools)
    for name in ("test201_gwtbuy-henryCHD", "ex-gwt-keating"):
        project_dir = _selected_dir(holdout_root, name)
        assert project_dir.is_dir(), f"seal broken: {name} missing from holdout"


# ---------------------------------------------------------------------------
# Seal integrity — the holdout must remain complete on disk
# ---------------------------------------------------------------------------


def test_holdout_sealed_projects_present(holdout_root):
    """All registry projects must be present under the holdout root."""
    for name in (
        "test009_3lay-disu",
        "test051_uzfp2",
        "test020_NevilleTonkinTransient",
        "test201_gwtbuy-henryCHD",
        "ex-gwt-keating",
    ):
        assert _selected_dir(holdout_root, name).is_dir(), (
            f"seal broken: {name} missing under {holdout_root}"
        )
    assert (holdout_root / "pools" / "modflow6-examples").is_dir(), (
        "seal broken: pools/modflow6-examples archive missing"
    )
