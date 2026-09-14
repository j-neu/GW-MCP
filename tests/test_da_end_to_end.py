"""End-to-end, MCP-only validation of a sequential ``pestpp-da`` run (Task 5).

Drives the whole DA chain through the server's tool callables exactly as a
closed-book agent would — ``create_model`` → ``set_simulation`` →
``add_dis_package`` → ``add_npf_package`` → ``add_ic_package`` →
``add_sto_package`` → ``add_boundary_package`` → ``add_oc_package`` →
``import_obs_from_csv`` → ``setup_da_control`` → ``run_pestpp_da`` →
``summarise_da``.

The tiny transient model runs one MODFLOW 6 stress period with one time step
(``NPER=1``, ``NSTP=1``) per DA cycle, and two DA cycles are assimilated with
CHD-gradient heads and 2 gauge observations. ``run_pestpp_da`` is called
**without** ``num_reals`` on purpose: an omitted ensemble size must preserve
the PST's ``da_num_reals`` written by ``setup_da_control(num_reals=5)`` rather
than clobber it with a default (Task 5 Step 0).
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import time
from pathlib import Path

import pytest

from groundwater_mcp.server import mcp
from groundwater_mcp.tools.calibration import _find_pestpp_binary
from groundwater_mcp.tools.runner import _find_mf6_binary

_MODEL = "da_e2e"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously (avoids adding pytest-asyncio)."""
    return asyncio.run(coro)


def _call(tool: str, args: dict) -> dict:
    """Call an MCP tool in-process and parse its JSON payload, asserting success."""
    result = _run(mcp.call_tool(tool, args))
    assert result, f"{tool} returned nothing"
    data = json.loads(result[0].text)
    assert isinstance(data, dict), f"{tool} returned {type(data)}"
    assert "error" not in data, f"{tool} failed: {data}"
    return data


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


def _pestpp_da_available() -> bool:
    try:
        _find_pestpp_binary("pestpp-da")
        return True
    except RuntimeError:
        return False


requires_da_stack = pytest.mark.skipif(
    not (_mf6_available() and _pestpp_da_available()),
    reason="MODFLOW 6 and/or pestpp-da binary not installed",
)


def _build_model(tmp_path: Path) -> None:
    """Build the tiny 1×4×4 transient model plus 2 registered gauge observations."""
    ws = str(tmp_path / _MODEL)
    _call(
        "create_model",
        {"name": _MODEL, "workspace": ws, "units": "METERS", "time_units": "DAYS"},
    )
    # One stress period / one time step — the sequential-DA requirement: the
    # cycle's only OBS-CSV row is its end-of-cycle value.
    _call(
        "set_simulation",
        {"model": _MODEL, "nper": 1, "perlen": [50.0], "nstp": [1], "ims_complexity": "simple"},
    )
    _call(
        "add_dis_package",
        {
            "model": _MODEL,
            "nlay": 1,
            "nrow": 4,
            "ncol": 4,
            "delr": 100.0,
            "delc": 100.0,
            "top": 50.0,
            "botm": [30.0],
        },
    )
    _call("add_npf_package", {"model": _MODEL, "icelltype": 0, "k": 5.0, "k33": None, "save_flows": True})
    _call("add_ic_package", {"model": _MODEL, "strt": 25.0})
    _call(
        "add_sto_package",
        {"model": _MODEL, "iconvert": 0, "ss": 1e-4, "sy": None, "steady_state": [], "save_flows": True},
    )
    # CHD gradient: high head in the (0,0) corner, low head in the (3,3) corner.
    _call(
        "add_boundary_package",
        {
            "model": _MODEL,
            "package": "CHD",
            "stress_period_data": {"0": [[[0, 0, 0], 40.0], [[0, 3, 3], 10.0]]},
            "kwargs": None,
        },
    )
    _call(
        "add_oc_package",
        {"model": _MODEL, "head_filerecord": None, "budget_filerecord": None, "saverecord": None, "printrecord": None},
    )

    obs_csv = tmp_path / "gauges.csv"
    with obs_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cell"])
        writer.writerow(["G1", "2020-01-01", 30.0, "0 1 1"])
        writer.writerow(["G2", "2020-01-01", 24.0, "0 2 2"])
    _call(
        "import_obs_from_csv",
        {
            "model": _MODEL,
            "csv_file": str(obs_csv),
            "obs_type": "HEAD",
            "site_col": "site",
            "date_col": "date",
            "value_col": "value",
            "cellid_col": "cell",
        },
    )


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


@requires_da_stack
def test_mcp_only_sequential_da_run(tmp_path):
    """The full chain runs over >=2 cycles with finite phi, MCP-tool only."""
    _build_model(tmp_path)

    setup = _call(
        "setup_da_control",
        {
            "model": _MODEL,
            "parameterisation": {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            "cycles": [0, 1],
            "obs_cycles": {"G1": {0: 31.0, 1: 32.0}, "G2": {0: 23.0, 1: 24.0}},
            "num_reals": 5,
        },
    )
    assert setup["n_cycles"] == 2
    assert setup["n_observations"] == 2
    assert setup["n_state_parameters"] == 2
    pst_file = setup["pst_file"]
    assert Path(pst_file).exists()

    # setup_da_control wrote the requested ensemble size into the PST.
    import pyemu

    assert str(pyemu.Pst(pst_file).pestpp_options["da_num_reals"]) == "5"

    # Deliberately omit num_reals: the PST's 5 must be preserved (Task 5 Step 0).
    t0 = time.perf_counter()
    run = _call("run_pestpp_da", {"model": _MODEL, "pst_file": pst_file})
    elapsed = time.perf_counter() - t0
    print(f"pestpp-da e2e wall time: {elapsed:.1f}s")

    assert run["converged"], run
    assert run["cycles"] >= 2, run
    assert run["num_reals"] == 5, run
    assert run["final_phi_mean"] is not None
    assert math.isfinite(run["final_phi_mean"])

    # The binary really ran the PST's 5-member ensemble: the phi header holds
    # 5 member columns (0..3 + base), not the 50-member set a clobbering
    # default would have produced.
    case = Path(pst_file).stem
    phi_csv = Path(pst_file).parent / f"{case}.phi.actual.csv"
    header = phi_csv.read_text().splitlines()[0].split(",")
    member_cols = [c.strip() for c in header[6:] if c.strip()]
    assert len(member_cols) == 5, header
    assert member_cols[-1] == "base", header

    summary = _call("summarise_da", {"model": _MODEL, "pst_file": pst_file})
    assert summary["engine"] == "da"
    assert [c["cycle"] for c in summary["cycles"]] == [0, 1]
    assert summary["final_phi_mean"] is not None
    assert math.isfinite(summary["final_phi_mean"])
