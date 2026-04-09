"""Tests for tools/builder.py — model creation and package configuration."""

from __future__ import annotations

import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_disv_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_list_model_files,
    _impl_set_simulation,
    _impl_summarise_model,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bare_model(tmp_path, model_name):
    """Create a bare model (no packages) and return its name."""
    ws = str(tmp_path / model_name)
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    assert "error" not in result
    return model_name


@pytest.fixture()
def model_with_dis(bare_model):
    """Extend bare_model with TDIS, IMS, and a 3-layer 10x10 DIS grid."""
    name = bare_model
    _impl_set_simulation(name, nper=2, perlen=[1.0, 9.0], nstp=[1, 3], ims_complexity="moderate")
    _impl_add_dis_package(
        name,
        nlay=3,
        nrow=10,
        ncol=10,
        delr=100.0,
        delc=100.0,
        top=50.0,
        botm=[40.0, 30.0, 20.0],
    )
    return name


@pytest.fixture()
def full_model(model_with_dis):
    """Extend model_with_dis with NPF, IC, WEL, and OC packages."""
    name = model_with_dis
    _impl_add_npf_package(name, icelltype=1, k=10.0, k33=1.0, save_flows=True)
    _impl_add_ic_package(name, strt=45.0)
    _impl_add_boundary_package(
        name,
        "WEL",
        {"0": [[[0, 5, 5], -500.0]], "1": [[[0, 5, 5], -600.0]]},
        None,
    )
    _impl_add_oc_package(name, None, None, None, None)
    return name


# ---------------------------------------------------------------------------
# create_model
# ---------------------------------------------------------------------------


def test_create_model_returns_workspace(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    assert "error" not in result
    assert result["model"] == model_name
    assert result["units"] == "METERS"
    assert result["time_units"] == "DAYS"


def test_create_model_writes_nam_file(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    ws_path = __import__("pathlib").Path(result["workspace"])
    assert (ws_path / "mfsim.nam").exists()
    assert (ws_path / f"{model_name}.nam").exists()


def test_create_model_duplicate_raises(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    with pytest.raises(ValueError, match="already exists"):
        _impl_create_model(model_name, ws, "METERS", "DAYS")


# ---------------------------------------------------------------------------
# set_simulation
# ---------------------------------------------------------------------------


def test_set_simulation_basic(bare_model):
    result = _impl_set_simulation(bare_model, nper=1, perlen=[365.0], nstp=[12], ims_complexity="simple")
    assert "error" not in result
    assert result["nper"] == 1
    assert result["total_time"] == pytest.approx(365.0)


def test_set_simulation_multiperiod(bare_model):
    result = _impl_set_simulation(bare_model, nper=3, perlen=[1.0, 10.0, 100.0], nstp=[1, 2, 5], ims_complexity="moderate")
    assert result["nper"] == 3
    assert result["total_time"] == pytest.approx(111.0)


def test_set_simulation_mismatched_arrays_raises(bare_model):
    with pytest.raises(ValueError):
        _impl_set_simulation(bare_model, nper=2, perlen=[1.0], nstp=[1, 2], ims_complexity="simple")


# ---------------------------------------------------------------------------
# add_dis_package
# ---------------------------------------------------------------------------


def test_add_dis_package_returns_grid_summary(bare_model):
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    result = _impl_add_dis_package(bare_model, 3, 10, 10, 100.0, 100.0, 50.0, [40.0, 30.0, 20.0])
    assert "error" not in result
    assert result["grid_type"] == "DIS"
    assert result["nlay"] == 3
    assert result["nrow"] == 10
    assert result["ncol"] == 10
    assert result["ncells"] == 300


def test_add_dis_package_writes_dis_file(model_with_dis):
    from groundwater_mcp.utils.workspace import resolve_workspace
    ws = resolve_workspace(model_with_dis)
    assert (ws / f"{model_with_dis}.dis").exists()


def test_add_dis_package_botm_mismatch_raises(bare_model):
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    with pytest.raises(ValueError, match="nlay"):
        _impl_add_dis_package(bare_model, 3, 10, 10, 100.0, 100.0, 50.0, [40.0, 30.0])  # only 2 botm entries


# ---------------------------------------------------------------------------
# add_disv_package
# ---------------------------------------------------------------------------


def test_add_disv_package(bare_model):
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    # Minimal 2-cell DISV grid (2 triangles, 4 vertices)
    vertices = [[0, 0.0, 0.0], [1, 100.0, 0.0], [2, 100.0, 100.0], [3, 0.0, 100.0]]
    cell2d = [
        [0, 33.3, 33.3, 3, 0, 1, 2],
        [1, 66.6, 66.6, 3, 0, 2, 3],
    ]
    top = [50.0, 50.0]
    botm = [[40.0, 40.0], [30.0, 30.0]]
    result = _impl_add_disv_package(bare_model, 2, vertices, cell2d, top, botm)
    assert "error" not in result
    assert result["grid_type"] == "DISV"
    assert result["ncpl"] == 2
    assert result["nvert"] == 4
    assert result["ncells"] == 4  # 2 layers x 2 cells


# ---------------------------------------------------------------------------
# add_npf_package
# ---------------------------------------------------------------------------


def test_add_npf_package(model_with_dis):
    result = _impl_add_npf_package(model_with_dis, icelltype=1, k=10.0, k33=1.0, save_flows=True)
    assert "error" not in result
    assert result["package"] == "NPF"


def test_add_npf_package_no_k33(model_with_dis):
    result = _impl_add_npf_package(model_with_dis, icelltype=0, k=5.0, k33=None, save_flows=False)
    assert "error" not in result


# ---------------------------------------------------------------------------
# add_ic_package
# ---------------------------------------------------------------------------


def test_add_ic_package(model_with_dis):
    result = _impl_add_ic_package(model_with_dis, strt=45.0)
    assert "error" not in result
    assert result["package"] == "IC"


# ---------------------------------------------------------------------------
# add_boundary_package
# ---------------------------------------------------------------------------


def test_add_well_package(model_with_dis):
    spd = {"0": [[[0, 5, 5], -500.0]]}
    result = _impl_add_boundary_package(model_with_dis, "WEL", spd, None)
    assert "error" not in result
    assert result["package"] == "WEL"
    assert result["stress_periods"][0] == 1


def test_add_chd_package(model_with_dis):
    # Constant head along first column
    cells = [[[lay, row, 0], 45.0] for lay in range(3) for row in range(10)]
    spd = {"0": cells}
    result = _impl_add_boundary_package(model_with_dis, "CHD", spd, None)
    assert "error" not in result
    assert result["stress_periods"][0] == 30


def test_add_invalid_package_raises(model_with_dis):
    with pytest.raises(ValueError, match="Unsupported package"):
        _impl_add_boundary_package(model_with_dis, "XYZ", {}, None)


# ---------------------------------------------------------------------------
# add_oc_package
# ---------------------------------------------------------------------------


def test_add_oc_package_defaults(model_with_dis):
    result = _impl_add_oc_package(model_with_dis, None, None, None, None)
    assert "error" not in result
    assert result["head_file"].endswith(".hds")
    assert result["budget_file"].endswith(".cbb")


def test_add_oc_package_custom_filenames(model_with_dis):
    result = _impl_add_oc_package(
        model_with_dis,
        head_filerecord="my_heads.hds",
        budget_filerecord="my_budget.cbb",
        saverecord=[["HEAD", "LAST"]],
        printrecord=None,
    )
    assert result["head_file"] == "my_heads.hds"
    assert result["budget_file"] == "my_budget.cbb"


# ---------------------------------------------------------------------------
# summarise_model
# ---------------------------------------------------------------------------


def test_summarise_model_full(full_model):
    result = _impl_summarise_model(full_model)
    assert "error" not in result
    assert result["model"] == full_model
    assert result["grid"]["type"] == "DIS"
    assert result["grid"]["nlay"] == 3
    assert result["grid"]["nrow"] == 10
    assert result["grid"]["ncol"] == 10
    assert len(result["stress_periods"]) == 2
    assert "WEL" in result["boundary_types"]
    assert "NPF" in result["packages"]
    assert "IC" in result["packages"]


def test_summarise_bare_model(bare_model):
    result = _impl_summarise_model(bare_model)
    assert "error" not in result
    assert result["grid"] == {}
    assert result["stress_periods"] == []


# ---------------------------------------------------------------------------
# list_model_files
# ---------------------------------------------------------------------------


def test_list_model_files(full_model):
    result = _impl_list_model_files(full_model)
    assert "error" not in result
    file_names = [f["name"] for f in result["files"]]
    assert "mfsim.nam" in file_names
    assert f"{full_model}.nam" in file_names


def test_list_model_files_has_size(full_model):
    result = _impl_list_model_files(full_model)
    for f in result["files"]:
        assert f["size_bytes"] >= 0


# ---------------------------------------------------------------------------
# Round-trip: create → write → reload from disk
# ---------------------------------------------------------------------------


def test_round_trip_reload_from_disk(tmp_path, model_name):
    """Verify model survives a cache invalidation (simulating server restart)."""
    from groundwater_mcp.utils.model_store import invalidate

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    _impl_add_dis_package(model_name, 2, 5, 5, 100.0, 100.0, 10.0, [5.0, 0.0])

    # Evict from cache — next call must reload from disk
    invalidate(model_name)

    result = _impl_summarise_model(model_name)
    assert result["grid"]["type"] == "DIS"
    assert result["grid"]["nlay"] == 2
