"""Tests for prompts.py / resources.py — MCP prompts and resource templates
(7e-C6/C7)."""

from __future__ import annotations

import asyncio
import json

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
from groundwater_mcp.tools.runner import _find_mf6_binary, _impl_get_run_log, _impl_run_simulation

# ---------------------------------------------------------------------------
# Skip marker — some resource tests require a real run
# ---------------------------------------------------------------------------


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
    return asyncio.run(coro)


@pytest.fixture()
def ran_model(tmp_path, model_name):
    """1-layer 5x5 steady-state CHD model that has already been run."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)
    _impl_run_simulation(model_name, silent=True)
    return model_name


# ---------------------------------------------------------------------------
# C6 — prompts
# ---------------------------------------------------------------------------


def test_list_prompts_includes_both():
    names = {p.name for p in _run(mcp.list_prompts())}
    assert {"build_model_from_data", "calibrate_model"} <= names


def test_build_model_from_data_renders_without_error():
    result = _run(mcp.get_prompt("build_model_from_data", {"model": "demo"}))
    text = result.messages[0].content.text
    assert "demo" in text
    assert "create_model" in text


def test_build_model_from_data_encodes_set_simulation_before_grid():
    """The documented (but unenforced) prerequisite: set_simulation before
    import_grid_from_shapefile."""
    text = _run(
        mcp.get_prompt("build_model_from_data", {"model": "demo", "has_grid_shapefile": True})
    ).messages[0].content.text
    assert text.index("set_simulation") < text.index("import_grid_from_shapefile")


def test_build_model_from_data_encodes_npf_before_assign_k():
    text = _run(
        mcp.get_prompt("build_model_from_data", {"model": "demo", "has_zone_shapefile": True})
    ).messages[0].content.text
    assert text.index("add_npf_package") < text.index("assign_k_from_zones")


def test_build_model_from_data_omits_sto_step_when_not_transient():
    """add_sto_package is mentioned in passing (as a set_simulation prerequisite)
    even for a steady-state build, but the dedicated build step must not appear."""
    text = _run(
        mcp.get_prompt("build_model_from_data", {"model": "demo", "transient": False})
    ).messages[0].content.text
    assert "REQUIRED for any model with more than one stress" not in text


def test_build_model_from_data_includes_sto_step_when_transient():
    text = _run(
        mcp.get_prompt("build_model_from_data", {"model": "demo", "transient": True})
    ).messages[0].content.text
    assert "REQUIRED for any model with more than one stress" in text
    assert "add_sto_package" in text


def test_calibrate_model_renders_without_error():
    result = _run(mcp.get_prompt("calibrate_model", {"model": "demo"}))
    text = result.messages[0].content.text
    assert "setup_calibration" in text
    assert "summarise_calibration" in text
    assert text.index("setup_calibration") < text.index("summarise_calibration")


def test_calibrate_model_ensemble_mentions_ies():
    text = _run(
        mcp.get_prompt("calibrate_model", {"model": "demo", "use_ensemble": True})
    ).messages[0].content.text
    assert "run_pestpp_ies" in text or "method=\"ies\"" in text
    assert "run_ies_uncertainty" in text


# ---------------------------------------------------------------------------
# C7 — resources
# ---------------------------------------------------------------------------


def test_list_resource_templates_includes_all_three():
    uris = {t.uriTemplate for t in _run(mcp.list_resource_templates())}
    assert {
        "gwmcp://models/{model}/lst",
        "gwmcp://models/{model}/pst",
        "gwmcp://models/{model}/files",
    } <= uris


@requires_mf6
def test_lst_resource_matches_get_run_log(ran_model):
    contents = _run(mcp.read_resource(f"gwmcp://models/{ran_model}/lst"))
    resource_text = contents[0].content

    # get_run_log(tail=<very large>) returns every line — the resource's full
    # file text, modulo the trailing newline splitlines() strips.
    full_log = _impl_get_run_log(ran_model, tail=10**6)
    assert resource_text.splitlines() == full_log["tail_lines"]


def test_lst_resource_unrun_model_raises(tmp_path, model_name):
    """FastMCP wraps a resource-template function's exception in a ValueError
    naming the original message — the model has no .lst before it has run."""
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    with pytest.raises(ValueError, match=r"No listing file"):
        _run(mcp.read_resource(f"gwmcp://models/{model_name}/lst"))


def test_lst_resource_unknown_model_raises():
    with pytest.raises(ValueError, match=r"No model named"):
        _run(mcp.read_resource("gwmcp://models/no_such_model_xyz/lst"))


def test_pst_resource_no_pst_raises(ran_model):
    with pytest.raises(ValueError, match=r"No PEST control file"):
        _run(mcp.read_resource(f"gwmcp://models/{ran_model}/pst"))


def test_files_resource_matches_list_model_files(ran_model):
    from groundwater_mcp.tools.builder import _impl_list_model_files

    contents = _run(mcp.read_resource(f"gwmcp://models/{ran_model}/files"))
    payload = json.loads(contents[0].content)
    expected = _impl_list_model_files(ran_model)

    assert payload["model"] == expected["model"]
    assert {f["name"] for f in payload["files"]} == {f["name"] for f in expected["files"]}
