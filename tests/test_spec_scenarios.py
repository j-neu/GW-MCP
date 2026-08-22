"""7f-G tests — declarative spec, provenance ledger, scenarios.

G1: apply_model_spec / export_model_spec + schema validation + idempotence.
G2: provenance ledger, describe_model, export_model_report.
G3: clone_model + compare_scenarios.

See tasks.md § 7f Tier G.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from groundwater_mcp.server import mcp
from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.runner import _find_mf6_binary
from groundwater_mcp.tools.spec import (
    _impl_apply_model_spec,
    _impl_clone_model,
    _impl_compare_scenarios,
    _impl_describe_model,
    _impl_export_model_report,
    _impl_export_model_spec,
)
from groundwater_mcp.utils import ledger
from groundwater_mcp.utils.model_store import flush_model
from groundwater_mcp.utils.spec import validate_spec
from groundwater_mcp.utils.workspace import resolve_workspace


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _parse(result):
    assert result, "call_tool returned an empty result list"
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _spec_dict(name: str, nlay: int = 2, nrow: int = 10, ncol: int = 10) -> dict:
    """A representative spec (the tutorial_05-shaped example from tools.md)."""
    return {
        "name": name,
        "units": "METERS",
        "time_units": "DAYS",
        "grid": {
            "type": "DIS",
            "nlay": nlay,
            "nrow": nrow,
            "ncol": ncol,
            "delr": 500.0,
            "delc": 500.0,
            "top": 50.0,
            "botm": [40.0, 30.0],
        },
        "time": {"nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "moderate"},
        "properties": {"npf": {"icelltype": 1, "k": 10.0, "k33": 1.0, "save_flows": True}},
        "initial_conditions": {"strt": 45.0},
        "boundaries": {
            "WEL": {"0": [[[0, 5, 5], -500.0]]},
            "CHD": {"0": [[[0, r, 0], 70.0] for r in range(10)]},
        },
        "output_control": {
            "head_file": f"{name}.hds",
            "budget_file": f"{name}.cbb",
            "saverecord": [["HEAD", "ALL"], ["BUDGET", "ALL"]],
        },
    }


def _build_small_model(tmp_path, name: str = "g_model") -> str:
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 2, 10, 10, 500.0, 500.0, 50.0, [40.0, 30.0])
    _impl_add_npf_package(name, icelltype=1, k=10.0, k33=1.0, save_flows=True)
    _impl_add_ic_package(name, strt=45.0)
    _impl_add_boundary_package(
        name, "WEL", {"0": [[[0, 5, 5], -500.0]]}, None
    )
    chd = [[[0, r, 0], 70.0] for r in range(10)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


# ---------------------------------------------------------------------------
# G1.1 — schema validation
# ---------------------------------------------------------------------------


def test_validate_spec_accepts_valid_spec():
    validate_spec(_spec_dict("valid"))
    validate_spec(_spec_dict("valid"))


def test_validate_spec_rejects_unknown_key():
    spec = _spec_dict("unknown")
    spec["bogus_section"] = {}
    with pytest.raises(ValueError, match="Unknown spec key"):
        validate_spec(spec)


def test_validate_spec_rejects_missing_required_key():
    spec = _spec_dict("missing")
    del spec["time"]
    with pytest.raises(ValueError, match="Missing required"):
        validate_spec(spec)


def test_validate_spec_rejects_dimensional_mismatch():
    spec = _spec_dict("dims")
    spec["grid"]["botm"] = [40.0]  # only one bottom for nlay=2
    with pytest.raises(ValueError, match="len\\(botm\\)"):
        validate_spec(spec)

    spec = _spec_dict("dims2")
    spec["time"]["perlen"] = [1.0, 2.0]  # two periods but nper=1
    with pytest.raises(ValueError, match="len\\(perlen\\)"):
        validate_spec(spec)


# ---------------------------------------------------------------------------
# G1.2 — apply_model_spec diff
# ---------------------------------------------------------------------------


def test_apply_spec_to_empty_model_reports_added(tmp_path):
    name = "spec_empty"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")

    result = _impl_apply_model_spec(name, _spec_dict(name))
    assert "error" not in result
    changed = {d["package"] for d in result["changed"]}
    for pkg in (f"{name}.dis", f"{name}.npf", f"{name}.ic", f"{name}.oc",
                f"{name}.wel", f"{name}.chd", "mfsim.tdis", "mfsim.ims"):
        assert pkg in changed, f"{pkg} not reported added: {result['changed']}"
    assert all(d["status"] == "added" for d in result["changed"])


def test_apply_spec_to_granular_built_model_reports_unchanged(tmp_path):
    name = _build_small_model(tmp_path)

    result = _impl_apply_model_spec(name, _spec_dict(name))
    assert "error" not in result
    assert result["changed"] == [], f"expected nothing to change: {result['changed']}"
    assert f"{name}.dis" in result["unchanged"]
    assert f"{name}.npf" in result["unchanged"]


def test_apply_spec_twice_is_idempotent(tmp_path):
    from groundwater_mcp.utils.spec import _snapshot_hashes

    name = _build_small_model(tmp_path)
    spec = _spec_dict(name)

    first = _impl_apply_model_spec(name, spec)
    assert first["changed"] == []
    snap1 = _snapshot_hashes(name)
    second = _impl_apply_model_spec(name, spec)
    assert second["changed"] == []
    snap2 = _snapshot_hashes(name)
    assert snap1 == snap2  # byte-identical (header-normalised) file set


def test_spec_build_matches_granular_build(tmp_path):
    from groundwater_mcp.utils.spec import _snapshot_hashes

    a = _build_small_model(tmp_path, name="granular")
    b = "specbuilt"
    _impl_create_model(b, str(tmp_path / b), "METERS", "DAYS")
    _impl_apply_model_spec(b, _spec_dict(b, nlay=2, nrow=10, ncol=10))

    ha, hb = _snapshot_hashes(a), _snapshot_hashes(b)
    for key in (f"{a}.dis", f"{a}.npf", f"{a}.wel", f"{a}.chd"):
        counterpart = key.replace(a, b)
        assert ha.get(key) == hb.get(counterpart), f"content mismatch for {key}"


# ---------------------------------------------------------------------------
# G1.4 — export_model_spec round-trip
# ---------------------------------------------------------------------------


@requires_mf6
def test_export_apply_roundtrip_reproduces_heads(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_heads
    from groundwater_mcp.tools.runner import _impl_run_simulation

    src = _build_small_model(tmp_path, name="orig")
    run_a = _impl_run_simulation(src, silent=True)
    assert run_a["success"] is True

    spec = _impl_export_model_spec(src)["spec"]
    assert spec["grid"]["type"] == "DIS"
    assert "WEL" in spec["boundaries"] and "CHD" in spec["boundaries"]

    dst = "rebuilt"
    _impl_create_model(dst, str(tmp_path / dst), "METERS", "DAYS")
    _impl_apply_model_spec(dst, spec)
    run_b = _impl_run_simulation(dst, silent=True)
    assert run_b["success"] is True

    heads_a = _impl_read_heads(src, kstpkper=[0, 0], layer=0, include_values=True)["values"]
    heads_b = _impl_read_heads(dst, kstpkper=[0, 0], layer=0, include_values=True)["values"]
    assert np.allclose(heads_a, heads_b, atol=1e-6)


# ---------------------------------------------------------------------------
# G2.1 — provenance ledger (through the MCP layer)
# ---------------------------------------------------------------------------


def test_ledger_records_every_tool_call_in_order(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    calls = [
        ("create_model", {"name": model_name, "workspace": ws}),
        ("set_simulation", {"model": model_name, "nper": 1, "perlen": [1.0], "nstp": [1]}),
        ("add_dis_package", {"model": model_name, "nlay": 1, "nrow": 5, "ncol": 5,
                             "delr": 100.0, "delc": 100.0, "top": 10.0, "botm": [0.0]}),
        ("add_npf_package", {"model": model_name, "icelltype": 0, "k": 10.0}),
        ("add_ic_package", {"model": model_name, "strt": 5.0}),
        ("add_oc_package", {"model": model_name}),
    ]
    for tool, args in calls:
        result = _parse(_run(mcp.call_tool(tool, args)))
        assert "error" not in result, f"{tool} failed: {result}"

    records = ledger.read_records(model_name)
    assert len(records) == 6
    for rec, (tool, _) in zip(records, calls):
        assert rec["tool"] == tool
        assert rec["change"], f"empty change description for {tool}"

    # A failing call on a real model is recorded with its error code
    _parse(_run(mcp.call_tool("add_boundary_package", {
        "model": model_name,
        "package": "XYZ",
        "stress_period_data": {},
    })))
    records = ledger.read_records(model_name)
    assert records[-1]["tool"] == "add_boundary_package"
    assert records[-1]["change"].startswith("failed: INVALID_INPUT")


def test_describe_model_reports_sources_defaults_and_staleness(tmp_path):
    name = _build_small_model(tmp_path)
    # scalar k via add_npf_package → flagged as unverified default
    desc = _impl_describe_model(name)
    assert any("npf.k" in entry for entry in desc["unverified_defaults"])
    assert desc["data_sources"] == {}
    assert desc["has_run"] is False

    # Set a raster-derived top → provenance recorded. The model grid must
    # carry the DEM's CRS and origin first (7e-B11.2 — sampling without a CRS
    # fails loudly instead of assuming a coordinate space).
    tut04 = Path(__file__).parent / "fixtures" / "tutorial_04"
    dem = tut04 / "dem_clipped.tif"
    if dem.exists():
        import rasterio

        from groundwater_mcp.tools.builder import _impl_set_model_crs
        from groundwater_mcp.tools.parameterise import _impl_assign_top_from_raster

        with rasterio.open(dem) as src:
            dem_bounds = src.bounds
        _impl_set_model_crs(
            name, "EPSG:32718", xorigin=dem_bounds.left, yorigin=dem_bounds.bottom
        )
        # The clipped DEM covers the catchment, not all 100 grid cells — the
        # new default fill='error' would fail loudly on the uncovered 34%;
        # fill='median' (B11.3) fills them and reports the count.
        _impl_assign_top_from_raster(name, str(dem), layer=0, method="mean", fill="median")
        desc = _impl_describe_model(name)
        assert desc["data_sources"]["top"]["source"].endswith("dem_clipped.tif")
        assert desc["data_sources"]["top"]["tool"] == "assign_top_from_raster"


@requires_mf6
def test_describe_model_reports_stale_after_external_edit(tmp_path):
    import os
    import time as time_mod

    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_small_model(tmp_path)
    _impl_run_simulation(name, silent=True)
    desc = _impl_describe_model(name)
    assert desc["has_run"] is True
    assert desc["results_stale"] is False

    # Editing a package file (newer mtime) makes results stale
    flush_model(name)
    ic_file = resolve_workspace(name) / f"{name}.ic"
    ic_file.write_text(ic_file.read_text() + "\n")
    future = time_mod.time() + 10
    os.utime(ic_file, (future, future))
    desc = _impl_describe_model(name)
    assert desc["results_stale"] is True


@requires_mf6
def test_export_model_report_contains_sources(tmp_path):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_small_model(tmp_path)
    _impl_run_simulation(name, silent=True)

    result = _impl_export_model_report(name)
    assert "error" not in result
    report_path = Path(result["report_file"])
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "# Model report" in text
    # References only files that exist
    import re

    for fname in re.findall(r"`([^`]+\.(?:png|hds|cbb|md))`", text):
        assert (resolve_workspace(name) / fname).exists(), f"report references missing {fname}"


# ---------------------------------------------------------------------------
# G3 — clone + compare scenarios
# ---------------------------------------------------------------------------


def test_clone_model_copies_and_isolates(tmp_path):
    name = _build_small_model(tmp_path, name="base")
    clone = _impl_clone_model(name, "clone", str(tmp_path / "clone"))
    assert "error" not in clone
    assert clone["cloned_from"] == name

    base_files = {
        p.name: p.read_bytes() for p in resolve_workspace(name).iterdir() if p.is_file()
    }
    # Modify the clone
    _impl_add_boundary_package("clone", "WEL", {"0": [[[0, 5, 5], -900.0]]}, None)
    flush_model("clone")
    new_base_files = {
        p.name: p.read_bytes() for p in resolve_workspace(name).iterdir() if p.is_file()
    }
    assert new_base_files == base_files, "modifying the clone changed the source"


@requires_mf6
def test_compare_scenarios_well_rate_difference(tmp_path):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    a = _build_small_model(tmp_path, name="scen_a")
    run_a = _impl_run_simulation(a, silent=True)
    assert run_a["success"] is True

    b = _impl_clone_model(a, "scen_b", str(tmp_path / "scen_b"))["model"]
    _impl_add_boundary_package(b, "WEL", {"0": [[[0, 5, 5], -900.0]]}, None)
    run_b = _impl_run_simulation(b, silent=True)
    assert run_b["success"] is True

    result = _impl_compare_scenarios(a, b)
    assert "error" not in result

    # Max head difference is at the well cell (row 5, col 5)
    at = result["difference"]["max_abs_at"]
    assert (at["row"], at["col"]) == (5, 5)

    # Budget delta for WEL equals the rate change (500 → 900)
    wel_delta = result["budget_deltas"]["WEL"]
    delta = wel_delta["outflow_delta"] if wel_delta["outflow_delta"] else wel_delta["inflow_delta"]
    assert abs(delta) == pytest.approx(400.0, abs=1.0)

    # Response stays small (no arrays)
    assert len(json.dumps(result)) < 8_000
