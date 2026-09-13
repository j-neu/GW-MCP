"""Phase 6 Layer 2 — MCP protocol tests.

Verifies that the groundwater-mcp server behaves correctly at the MCP layer:
  - tool listing (all 40 tools registered, metadata complete)
  - JSON response format (TextContent, parseable JSON, no extra keys)
  - error paths (MODEL_NOT_FOUND, etc.)
  - multi-step in-process workflow (create → grid → run → read_heads)

Uses FastMCP's in-process API (mcp.list_tools / mcp.call_tool) instead of a
subprocess, so it runs in the same Python process as the rest of the test suite
and benefits from conftest.py monkeypatching (workspace registry, cache clearing).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from groundwater_mcp.server import mcp
from groundwater_mcp.tools.runner import _find_mf6_binary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TUT04 = Path(__file__).parent / "fixtures" / "tutorial_04"
_SHP_ZONE = str(_TUT04 / "activeZone.shp")
_DEM = str(_TUT04 / "dem_clipped.tif")


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
# Tool listing
# ---------------------------------------------------------------------------

_EXPECTED_TOOL_COUNT = 67

# Keep in sync with the tool tables in README.md / tools.md / architecture.md
# (7e-B18).

_EXPECTED_TOOLS: dict[str, list[str]] = {
    "docs": ["search_docs", "search_tutorials", "get_doc_file", "describe_package"],
    "parameterise": [
        "import_grid_from_shapefile",
        "assign_top_from_raster",
        "assign_k_from_zones",
        "assign_k_from_raster",
        "assign_ic_from_raster",
        "assign_array_from_raster",
        "import_river_from_shapefile",
        "import_obs_from_csv",
    ],
    "builder": [
        "create_model",
        "adopt_model",
        "set_simulation",
        "set_model_crs",
        "add_dis_package",
        "add_disv_package",
        "add_disu_package",
        "add_npf_package",
        "add_ic_package",
        "add_sto_package",
        "add_oc_package",
        "add_boundary_package",
        "summarise_model",
        "model_status",
        "list_model_files",
        "flush_model",
        "list_models",
        "delete_model",
    ],
    "runner": [
        "check_model",
        "run_simulation",
        "get_run_log",
        "diagnose_convergence",
        "validate_model",
        "start_run",
        "get_job_status",
        "cancel_job",
    ],
    "environment": ["check_environment"],
    "postprocess": [
        "read_heads",
        "read_budget",
        "compute_drawdown",
        "compute_water_balance",
        "diagnose_water_balance",
        "export_heads_to_raster",
        "export_boundaries_to_shapefile",
        "export_water_balance_csv",
        "plot_heads_map",
        "plot_cross_section",
        "read_simulated_observations",
        "compare_to_observed",
    ],
    "calibration": [
        "setup_calibration",
        "setup_pest_control",
        "start_calibration",
        "run_pestpp_glm",
        "run_pestpp_ies",
        "summarise_calibration",
        "run_ies_uncertainty",
        "check_parameter_sensitivity",
        "calibrate",
    ],
    "spec": [
        "apply_model_spec",
        "export_model_spec",
        "export_reproducible_script",
        "describe_model",
        "export_model_report",
        "clone_model",
        "compare_scenarios",
    ],
}


def test_tool_count():
    tools = _run(mcp.list_tools())
    assert len(tools) == _EXPECTED_TOOL_COUNT, (
        f"Expected {_EXPECTED_TOOL_COUNT} tools, got {len(tools)}: "
        f"{[t.name for t in tools]}"
    )


def test_all_expected_tools_present():
    tools = _run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    missing = []
    for module, names in _EXPECTED_TOOLS.items():
        for name in names:
            if name not in tool_names:
                missing.append(f"{module}.{name}")
    assert not missing, f"Missing tools: {missing}"


def test_all_tools_have_descriptions():
    tools = _run(mcp.list_tools())
    missing_desc = [t.name for t in tools if not (t.description or "").strip()]
    assert not missing_desc, f"Tools without descriptions: {missing_desc}"


def test_all_tools_have_input_schema():
    tools = _run(mcp.list_tools())
    missing_schema = [t.name for t in tools if not t.inputSchema]
    assert not missing_schema, f"Tools without inputSchema: {missing_schema}"


def test_tool_names_are_snake_case():
    tools = _run(mcp.list_tools())
    non_snake = [t.name for t in tools if t.name != t.name.lower().replace("-", "_")]
    assert not non_snake, f"Non-snake-case tool names: {non_snake}"


# ---------------------------------------------------------------------------
# Environment preflight
# ---------------------------------------------------------------------------


def test_check_environment_reports_server_stack():
    result = _run(mcp.call_tool("check_environment", {}))
    data = _parse(result)
    assert isinstance(data, dict)
    assert "python" in data and "executable" in data["python"]
    assert "packages" in data
    for pkg in ("flopy", "pyemu", "geopandas", "rasterio"):
        assert pkg in data["packages"], f"missing {pkg} in package report"
    assert "binaries" in data and "mf6" in data["binaries"]
    assert "ready" in data
    assert "workspace_root" in data


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------


def test_create_model_returns_text_content(tmp_path):
    result = _run(mcp.call_tool("create_model", {
        "name": "proto_fmt",
        "workspace": str(tmp_path / "proto_fmt"),
        "units": "METERS",
        "time_units": "DAYS",
    }))
    assert result, "call_tool returned nothing"
    assert result[0].type == "text"


def test_create_model_response_is_valid_json(tmp_path):
    result = _run(mcp.call_tool("create_model", {
        "name": "proto_json",
        "workspace": str(tmp_path / "proto_json"),
        "units": "METERS",
        "time_units": "DAYS",
    }))
    data = _parse(result)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"


def test_successful_response_has_no_error_key(tmp_path):
    result = _run(mcp.call_tool("create_model", {
        "name": "proto_noerr",
        "workspace": str(tmp_path / "proto_noerr"),
        "units": "METERS",
        "time_units": "DAYS",
    }))
    data = _parse(result)
    assert "error" not in data, f"Unexpected error in success response: {data}"


def test_create_model_response_contains_expected_keys(tmp_path):
    result = _run(mcp.call_tool("create_model", {
        "name": "proto_keys",
        "workspace": str(tmp_path / "proto_keys"),
    }))
    data = _parse(result)
    for key in ("model", "workspace"):
        assert key in data, f"Missing key '{key}' in create_model response: {data}"


# ---------------------------------------------------------------------------
# Error paths — MODEL_NOT_FOUND
# ---------------------------------------------------------------------------


def test_run_before_create_returns_model_not_found():
    result = _run(mcp.call_tool("run_simulation", {
        "model": "ghost_model",
        "silent": True,
    }))
    data = _parse(result)
    assert data.get("error") is True
    assert data.get("code") == "MODEL_NOT_FOUND"


def test_add_boundary_before_create_returns_model_not_found():
    result = _run(mcp.call_tool("add_boundary_package", {
        "model": "ghost_model",
        "package": "CHD",
        "stress_period_data": {"0": []},
    }))
    data = _parse(result)
    assert data.get("error") is True
    assert data.get("code") == "MODEL_NOT_FOUND"


def test_read_heads_before_run_returns_error():
    result = _run(mcp.call_tool("read_heads", {
        "model": "ghost_model",
        "layer": 0,
    }))
    data = _parse(result)
    assert data.get("error") is True


def test_error_response_has_message_field():
    result = _run(mcp.call_tool("run_simulation", {
        "model": "ghost_model",
        "silent": True,
    }))
    data = _parse(result)
    assert "message" in data, f"Error response missing 'message': {data}"


def test_error_response_has_suggestion_field():
    result = _run(mcp.call_tool("run_simulation", {
        "model": "ghost_model",
        "silent": True,
    }))
    data = _parse(result)
    assert "suggestion" in data, f"Error response missing 'suggestion': {data}"


# ---------------------------------------------------------------------------
# Multi-step workflow — create → grid → import_river (no mf6 needed)
# ---------------------------------------------------------------------------

_WORKFLOW_MODEL = "proto_workflow"


@pytest.fixture()
def workflow_model(tmp_path):
    """Create a model and set up a simulation ready for further tool calls."""
    ws = str(tmp_path / _WORKFLOW_MODEL)

    r = _parse(_run(mcp.call_tool("create_model", {
        "name": _WORKFLOW_MODEL,
        "workspace": ws,
        "units": "METERS",
        "time_units": "DAYS",
    })))
    assert "error" not in r, f"create_model failed: {r}"

    r = _parse(_run(mcp.call_tool("set_simulation", {
        "model": _WORKFLOW_MODEL,
        "nper": 1,
        "perlen": [1.0],
        "nstp": [1],
        "ims_complexity": "simple",
    })))
    assert "error" not in r, f"set_simulation failed: {r}"

    return _WORKFLOW_MODEL


@pytest.fixture()
def workflow_with_grid(workflow_model):
    """Extend the workflow model with a DIS grid from activeZone.shp."""
    r = _parse(_run(mcp.call_tool("import_grid_from_shapefile", {
        "model": workflow_model,
        "shapefile": _SHP_ZONE,
        "nlay": 1,
        "method": "dis",
        "cell_size": 500.0,
    })))
    assert "error" not in r, f"import_grid_from_shapefile failed: {r}"
    return workflow_model, r


@pytest.fixture()
def workflow_with_dem(workflow_with_grid):
    """Assign top elevations from the Tutorial 04 DEM."""
    model, grid = workflow_with_grid
    r = _parse(_run(mcp.call_tool("assign_top_from_raster", {
        "model": model,
        "raster": _DEM,
        "layer": 0,
        "method": "mean",
    })))
    assert "error" not in r, f"assign_top_from_raster failed: {r}"
    return model, grid, r


@pytest.fixture()
def workflow_runnable(workflow_with_dem):
    """Add NPF, IC, OC, and CHD to make the model runnable."""
    model, grid, dem = workflow_with_dem
    nrow = grid["nrow"]
    ncol = grid["ncol"]

    for tool, args in [
        ("add_npf_package", {"model": model, "icelltype": 0, "k": 1.0, "save_flows": True}),
        ("add_ic_package", {"model": model, "strt": 50.0}),
        ("add_oc_package", {"model": model}),
    ]:
        r = _parse(_run(mcp.call_tool(tool, args)))
        assert "error" not in r, f"{tool} failed: {r}"

    chd = []
    for row in range(nrow):
        chd.append([[0, row, 0], 60.0])
        chd.append([[0, row, ncol - 1], 40.0])
    r = _parse(_run(mcp.call_tool("add_boundary_package", {
        "model": model,
        "package": "CHD",
        "stress_period_data": {"0": chd},
    })))
    assert "error" not in r, f"add_boundary_package CHD failed: {r}"
    return model, grid


@pytest.fixture()
def workflow_ran(workflow_runnable):
    """Run the simulation."""
    model, grid = workflow_runnable
    r = _parse(_run(mcp.call_tool("run_simulation", {
        "model": model,
        "silent": True,
    })))
    return model, grid, r


# --- workflow assertions ---


def test_workflow_create_model_response(workflow_model):
    assert workflow_model == _WORKFLOW_MODEL


def test_workflow_grid_has_cells(workflow_with_grid):
    _, grid = workflow_with_grid
    assert grid["ncells"] > 0


def test_workflow_grid_type_is_dis(workflow_with_grid):
    _, grid = workflow_with_grid
    assert grid["grid_type"] == "DIS"


def test_workflow_dem_assigns_cells(workflow_with_dem):
    _, grid, dem = workflow_with_dem
    assert dem["cells_assigned"] == grid["nrow"] * grid["ncol"]


def test_workflow_dem_elevation_plausible(workflow_with_dem):
    _, _, dem = workflow_with_dem
    assert 1.0 <= dem["min"] <= dem["max"] <= 300.0


@requires_mf6
def test_workflow_run_succeeds(workflow_ran):
    _, _, run = workflow_ran
    assert run["success"] is True, f"Simulation failed: {run}"


@requires_mf6
def test_workflow_run_converged(workflow_ran):
    _, _, run = workflow_ran
    assert run["convergence"] == "converged"


@requires_mf6
def test_workflow_read_heads_via_mcp(workflow_ran):
    model, grid, _ = workflow_ran
    r = _parse(_run(mcp.call_tool("read_heads", {
        "model": model,
        "layer": 0,
    })))
    assert "error" not in r, f"read_heads failed: {r}"
    assert r["shape"] == [grid["nrow"], grid["ncol"]]


@requires_mf6
def test_workflow_summarise_model_via_mcp(workflow_ran):
    model, _, _ = workflow_ran
    r = _parse(_run(mcp.call_tool("summarise_model", {"model": model})))
    assert "error" not in r
    assert r["model"] == model


# ---------------------------------------------------------------------------
# Import river through MCP layer
# ---------------------------------------------------------------------------


def test_import_river_via_mcp_returns_reach_count(workflow_with_dem):
    model, _, _ = workflow_with_dem
    _TUT05 = Path(__file__).parent / "fixtures" / "tutorial_05"
    r = _parse(_run(mcp.call_tool("import_river_from_shapefile", {
        "model": model,
        "shapefile": str(_TUT05 / "river.shp"),
        "package": "RIV",
        "bed_k": 1e-4,
        "bed_thickness": 1.0,
        "channel_width": 20.0,
    })))
    assert "error" not in r, f"import_river_from_shapefile failed: {r}"
    assert r["reach_count"] > 0


# ---------------------------------------------------------------------------
# 7f-D3 — layer bounds validation returns the INVALID_INPUT envelope
# ---------------------------------------------------------------------------


@pytest.fixture()
def three_layer_model(tmp_path):
    """3-layer DIS model built entirely through the MCP layer."""
    name = "proto_3layer"
    ws = str(tmp_path / name)

    r = _parse(_run(mcp.call_tool("create_model", {
        "name": name, "workspace": ws, "units": "METERS", "time_units": "DAYS",
    })))
    assert "error" not in r, r

    r = _parse(_run(mcp.call_tool("set_simulation", {
        "model": name, "nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "simple",
    })))
    assert "error" not in r, r

    r = _parse(_run(mcp.call_tool("add_dis_package", {
        "model": name, "nlay": 3, "nrow": 5, "ncol": 5,
        "delr": 100.0, "delc": 100.0, "top": 50.0, "botm": [40.0, 30.0, 20.0],
    })))
    assert "error" not in r, r
    return name


def test_read_heads_layer_out_of_range_invalid_input(three_layer_model):
    for bad in (-1, 3):
        r = _parse(_run(mcp.call_tool("read_heads", {
            "model": three_layer_model, "layer": bad,
        })))
        assert r.get("error") is True
        assert r.get("code") == "INVALID_INPUT"
        assert "3" in r.get("message", "")  # nlay named in the message
    # A valid layer passes validation (fails later on the missing .hds output)
    r = _parse(_run(mcp.call_tool("read_heads", {
        "model": three_layer_model, "layer": 2,
    })))
    assert r.get("code") == "OUTPUT_FILE_MISSING"


def test_plot_heads_map_layer_out_of_range_invalid_input(three_layer_model):
    r = _parse(_run(mcp.call_tool("plot_heads_map", {
        "model": three_layer_model, "layer": 3,
    })))
    assert r.get("error") is True
    assert r.get("code") == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 7f-D4 — adopted-model read-only guard at the MCP layer
# ---------------------------------------------------------------------------


def test_adopt_model_readonly_add_npf_returns_envelope(tmp_path):
    """add_npf_package on an adopted (read-only) model returns the
    MODEL_ADOPTED_READONLY envelope instead of a generic error."""
    import flopy.mf6 as mf6

    src = tmp_path / "adopt_src"
    src.mkdir()
    sim = mf6.MFSimulation(sim_name="mfsim", version="mf6", sim_ws=str(src))
    gwf = mf6.ModflowGwf(sim, modelname="g1", model_nam_file="g1.nam")
    mf6.ModflowTdis(sim, pname="tdis", time_units="DAYS", nper=1, perioddata=[(1.0, 1, 1.0)])
    mf6.ModflowIms(sim, pname="ims", complexity="SIMPLE")
    sim.register_ims_package(sim.get_package("ims"), [gwf.name])
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=2, ncol=2, delr=100.0, delc=100.0, top=10.0, botm=[0.0])
    mf6.ModflowGwfnpf(gwf, icelltype=0, k=5.0)
    sim.write_simulation(silent=True)

    name = "proto_adopt"
    r = _parse(_run(mcp.call_tool("adopt_model", {
        "name": name, "workspace": str(src), "units": "METERS", "time_units": "DAYS",
    })))
    assert "error" not in r, r

    r = _parse(_run(mcp.call_tool("add_npf_package", {
        "model": name, "icelltype": 0, "k": 5.0, "save_flows": True,
    })))
    assert r.get("error") is True
    assert r.get("code") == "MODEL_ADOPTED_READONLY"

    r = _parse(_run(mcp.call_tool("summarise_model", {"model": name})))
    assert "error" not in r
    assert r["grid"]["ncol"] == 2


# ---------------------------------------------------------------------------
# 7e-A2 — setup_calibration at the MCP layer
# ---------------------------------------------------------------------------


def test_setup_calibration_invalid_parameterisation_returns_envelope(
    three_layer_model,
):
    """A malformed parameterisation spec surfaces as INVALID_INPUT, not a
    generic error."""
    r = _parse(_run(mcp.call_tool("setup_calibration", {
        "model": three_layer_model,
        "parameterisation": {"k": {"target": "npf:k22", "initial": 5.0}},
    })))
    assert r.get("error") is True
    assert r.get("code") == "INVALID_INPUT"
    assert "target" in r.get("message", "")


def test_setup_calibration_unknown_model_returns_envelope():
    r = _parse(_run(mcp.call_tool("setup_calibration", {
        "model": "no_such_model_xyz",
        "parameterisation": {"k": {"target": "npf:k", "initial": 5.0}},
    })))
    assert r.get("error") is True
    assert r.get("code") == "MODEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# 7e-A3 — job control at the MCP layer
# ---------------------------------------------------------------------------


def test_get_job_status_unknown_job_returns_envelope():
    r = _parse(_run(mcp.call_tool("get_job_status", {"job_id": "no_such_job"})))
    assert r.get("error") is True
    assert r.get("code") == "JOB_NOT_FOUND"


def test_cancel_job_unknown_job_returns_envelope():
    r = _parse(_run(mcp.call_tool("cancel_job", {"job_id": "no_such_job"})))
    assert r.get("error") is True
    assert r.get("code") == "JOB_NOT_FOUND"


def test_start_calibration_unknown_model_returns_envelope():
    r = _parse(_run(mcp.call_tool("start_calibration", {
        "model": "no_such_model_xyz",
        "pst_file": "test.pst",
    })))
    assert r.get("error") is True


# ---------------------------------------------------------------------------
# 7e-C8 — next_steps auto-attached to builder/parameterise tool results
# ---------------------------------------------------------------------------


def test_model_status_is_registered_and_reports_missing_packages(tmp_path):
    r = _parse(_run(mcp.call_tool("create_model", {
        "name": "proto_c8_status",
        "workspace": str(tmp_path / "proto_c8_status"),
        "units": "METERS",
        "time_units": "DAYS",
    })))
    assert "error" not in r

    status = _parse(_run(mcp.call_tool("model_status", {"model": "proto_c8_status"})))
    assert status["runnable"] is False
    assert status["missing_required"] == ["simulation", "grid", "npf", "ic", "oc"]


def test_create_model_result_carries_next_steps(tmp_path):
    r = _parse(_run(mcp.call_tool("create_model", {
        "name": "proto_c8_create",
        "workspace": str(tmp_path / "proto_c8_create"),
        "units": "METERS",
        "time_units": "DAYS",
    })))
    assert "next_steps" in r
    assert r["next_steps"][0].startswith("set_simulation")


def test_next_steps_narrows_as_builder_tools_are_called(tmp_path):
    name = "proto_c8_narrow"
    ws = str(tmp_path / name)

    r = _parse(_run(mcp.call_tool(
        "create_model", {"name": name, "workspace": ws, "units": "METERS", "time_units": "DAYS"}
    )))
    assert any(s.startswith("set_simulation") for s in r["next_steps"])

    r = _parse(_run(mcp.call_tool("set_simulation", {
        "model": name, "nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "simple",
    })))
    assert not any(s.startswith("set_simulation") for s in r["next_steps"])
    assert any(s.startswith("add_dis_package") for s in r["next_steps"])

    r = _parse(_run(mcp.call_tool("add_dis_package", {
        "model": name, "nlay": 1, "nrow": 5, "ncol": 5,
        "delr": 100.0, "delc": 100.0, "top": 10.0, "botm": [0.0],
    })))
    assert not any(s.startswith("add_dis_package") for s in r["next_steps"])
    assert any(s.startswith("add_npf_package") for s in r["next_steps"])


def test_next_steps_empty_once_model_is_runnable(tmp_path):
    name = "proto_c8_run"
    ws = str(tmp_path / name)
    _run(mcp.call_tool(
        "create_model", {"name": name, "workspace": ws, "units": "METERS", "time_units": "DAYS"}
    ))
    _run(mcp.call_tool("set_simulation", {
        "model": name, "nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "simple",
    }))
    _run(mcp.call_tool("add_dis_package", {
        "model": name, "nlay": 1, "nrow": 5, "ncol": 5,
        "delr": 100.0, "delc": 100.0, "top": 10.0, "botm": [0.0],
    }))
    _run(mcp.call_tool("add_npf_package", {
        "model": name, "icelltype": 0, "k": 10.0, "save_flows": True,
    }))
    _run(mcp.call_tool("add_ic_package", {"model": name, "strt": 5.0}))
    r = _parse(_run(mcp.call_tool("add_oc_package", {"model": name})))

    # Only the "boundary" recommendation is left — required gaps are gone —
    # and the model is runnable despite next_steps not being empty.
    assert r["next_steps"] == [
        s for s in r["next_steps"] if "add_boundary_package" in s or "import_river" in s
    ]
    status = _parse(_run(mcp.call_tool("model_status", {"model": name})))
    assert status["runnable"] is True
    assert status["missing_required"] == []


def test_next_steps_absent_on_error_response(tmp_path):
    r = _parse(_run(mcp.call_tool("set_simulation", {
        "model": "no_such_model_for_next_steps",
        "nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "simple",
    })))
    assert r.get("error") is True
    assert "next_steps" not in r


def test_assign_k_from_zones_next_steps_names_npf_when_missing(tmp_path):
    """The documented-but-unenforced assign_k_from_zones -> NPF prerequisite
    (7e-C8) shows up proactively in next_steps before the tool is even called."""
    name = "proto_c8_zones"
    ws = str(tmp_path / name)
    _run(mcp.call_tool(
        "create_model", {"name": name, "workspace": ws, "units": "METERS", "time_units": "DAYS"}
    ))
    r = _parse(_run(mcp.call_tool("set_simulation", {
        "model": name, "nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "simple",
    })))
    assert any("add_npf_package" in s and "assign_k_from_zones" in s for s in r["next_steps"])
