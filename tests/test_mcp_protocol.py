"""Phase 6 Layer 2 — MCP protocol tests.

Verifies that the groundwater-mcp server behaves correctly at the MCP layer:
  - tool listing (all 36 tools registered, metadata complete)
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

_EXPECTED_TOOL_COUNT = 36

_EXPECTED_TOOLS: dict[str, list[str]] = {
    "docs": ["search_docs", "search_tutorials", "get_doc_file"],
    "parameterise": [
        "import_grid_from_shapefile",
        "assign_top_from_raster",
        "assign_k_from_zones",
        "import_river_from_shapefile",
        "import_obs_from_csv",
    ],
    "builder": [
        "create_model",
        "set_simulation",
        "add_dis_package",
        "add_npf_package",
        "add_ic_package",
        "add_oc_package",
        "add_boundary_package",
        "summarise_model",
        "list_model_files",
    ],
    "runner": ["check_model", "run_simulation", "get_run_log"],
    "postprocess": [
        "read_heads",
        "read_budget",
        "compute_drawdown",
        "compute_water_balance",
        "plot_heads_map",
        "plot_cross_section",
    ],
    "calibration": [
        "setup_pest_control",
        "run_pestpp_glm",
        "run_pestpp_ies",
        "summarise_calibration",
        "run_ies_uncertainty",
        "setup_ucode_control",
        "run_ucode",
        "summarise_ucode_calibration",
        "run_ucode_uncertainty",
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
    })))
    assert "error" not in r, f"import_river_from_shapefile failed: {r}"
    assert r["reach_count"] > 0
