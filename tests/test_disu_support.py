"""DISU (fully unstructured) grid support.

DISU is defined by explicit node connectivity (NODES/NJA, IAC/JA) rather than a
row/col (DIS) or vertex (DISV) description. FloPy exposes it as a
``ModflowGwfdisu`` package and an ``UnstructuredGrid`` whose ``nlay`` is 1 and
whose cell ids are scalar 0-based node ids (converted to 1-based on disk).

These tests pin the grid resolution, model summary/status, obs node mapping,
plan-view guard and K parameterisation needed for the DISU Tier-1 target.
"""

from __future__ import annotations

import csv

import pytest

from groundwater_mcp.tools.builder import (
    _compute_model_status,
    _impl_add_boundary_package,
    _impl_add_disu_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
    _impl_summarise_model,
)
from groundwater_mcp.tools.calibration import _impl_setup_calibration
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.grid import get_dis, get_disu, get_disv
from groundwater_mcp.utils.model_store import flush_model, get_gwf, read_meta


def _mf6_available() -> bool:
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")


def _build_disu_model(tmp_path, name: str = "disu_support") -> str:
    """3-node line DISU model (nodes 0-1-2), CHD at node 0 (1.0) and node 2 (0.0)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    _impl_add_disu_package(
        name,
        3,
        7,
        [0.0, 0.0, 0.0],
        [-10.0, -10.0, -10.0],
        area=[100.0, 100.0, 100.0],
        iac=[2, 3, 2],
        ja=[0, 1, 1, 0, 2, 2, 1],
    )
    _impl_add_npf_package(name, icelltype=0, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=0.0)
    _impl_add_boundary_package(name, "CHD", {"0": [[0, 1.0], [2, 0.0]]}, None)
    _impl_add_oc_package(name, None, None, None, None)
    flush_model(name)
    return name


def _write_seq_obs_csv(tmp_path, name: str, sites=("S1", "S2")):
    path = tmp_path / f"{name}_obs_seq.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value"])
        for s in sites:
            writer.writerow([s, "2020-01-01", 0.5])
    return str(path)


def _write_coord_obs_csv(tmp_path, name: str, sites=("S1",)):
    path = tmp_path / f"{name}_obs_xy.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for s in sites:
            writer.writerow([s, "2020-01-01", 0.5, 0.0, 0.0])
    return str(path)


# ---------------------------------------------------------------------------
# Grid resolution / reporting
# ---------------------------------------------------------------------------


def test_get_disu_resolves_package(tmp_path):
    name = _build_disu_model(tmp_path)
    gwf = get_gwf(name)
    assert get_disu(gwf) is not None
    assert get_dis(gwf) is None
    assert get_disv(gwf) is None


def test_summarise_model_disu_reports_grid(tmp_path):
    name = _build_disu_model(tmp_path)
    summary = _impl_summarise_model(name)
    assert summary["grid"]["type"] == "DISU"
    assert summary["grid"]["nnodes"] == 3
    assert summary["grid"]["ncells"] == 3


def test_model_status_disu_runnable(tmp_path):
    name = _build_disu_model(tmp_path)
    status = _compute_model_status(name)
    assert status["runnable"] is True
    assert "grid" not in status["missing_required"]


def test_add_disu_package_requires_connection_data(tmp_path):
    name = "disu_bad"
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    with pytest.raises(ValueError, match="connection data"):
        _impl_add_disu_package(
            name, 2, 2, [0.0, 0.0], [-1.0, -1.0], area=[1.0, 1.0]
        )


@requires_mf6
def test_disu_model_runs(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_heads
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_disu_model(tmp_path, "disu_run")
    run = _impl_run_simulation(name)
    assert run.get("success") is True, run
    heads = _impl_read_heads(name)
    assert heads["min"] == pytest.approx(0.0)
    assert heads["max"] == pytest.approx(1.0)


def test_plot_heads_map_disu_without_geometry_raises_clear_error(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_heads_map

    name = _build_disu_model(tmp_path, "disu_plot")
    with pytest.raises(ValueError, match="cell x/y geometry"):
        _impl_plot_heads_map(name)


# ---------------------------------------------------------------------------
# Observations + calibration on DISU
# ---------------------------------------------------------------------------


def test_import_obs_from_csv_disu_sequential_uses_node_ids(tmp_path):
    name = _build_disu_model(tmp_path, "disu_obsseq")
    csv_path = _write_seq_obs_csv(tmp_path, name)
    result = _impl_import_obs_from_csv(
        name, csv_path, "HEAD", "site", "date", "value", None, None, 0
    )
    assert "error" not in result, result
    assert result["site_cellid_map"]["S1"] == 0
    assert result["site_cellid_map"]["S2"] == 1
    entry = read_meta(name)["observations"]["sites"][0]
    assert entry["cellid"] == 0


def test_import_obs_from_csv_disu_coords_without_geometry_raises(tmp_path):
    name = _build_disu_model(tmp_path, "disu_obsxy")
    csv_path = _write_coord_obs_csv(tmp_path, name)
    with pytest.raises(ValueError, match="no cell-centroid x/y"):
        _impl_import_obs_from_csv(
            name, csv_path, "HEAD", "site", "date", "value", "x", "y", 0
        )


def test_setup_calibration_disu_all_scope(tmp_path):
    name = _build_disu_model(tmp_path, "disu_calall")
    _impl_import_obs_from_csv(
        name, _write_seq_obs_csv(tmp_path, name), "HEAD", "site", "date", "value",
        None, None, 0,
    )
    result = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 1.0}},
        obs_source="model",
        noptmax=1,
    )
    assert "error" not in result, result
    assert result["n_adjustable_parameters"] == 1


def test_setup_calibration_disu_zones_scope(tmp_path):
    name = _build_disu_model(tmp_path, "disu_calzon")
    _impl_import_obs_from_csv(
        name, _write_seq_obs_csv(tmp_path, name), "HEAD", "site", "date", "value",
        None, None, 0,
    )
    result = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "zones", "layer": 0, "max_zones": 5}},
        obs_source="model",
        noptmax=1,
    )
    assert "error" not in result, result
    assert result["n_adjustable_parameters"] >= 1
