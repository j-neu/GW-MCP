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

import numpy as np
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


def test_add_boundary_package_rejects_multi_element_cellid_on_disu(tmp_path):
    """A DISV/DIS-style cellid must not be silently truncated on a DISU grid."""
    name = _build_disu_model(tmp_path, "disu_chdbad")
    with pytest.raises(ValueError, match="single node index"):
        _impl_add_boundary_package(name, "CHD", {"0": [[[0, 0], 1.0]]}, None)


def test_add_boundary_package_accepts_one_element_node_on_disu(tmp_path):
    name = _build_disu_model(tmp_path, "disu_chdok")
    result = _impl_add_boundary_package(
        name, "CHD", {"0": [[[0], 1.0], [[2], 0.0]]}, None
    )
    assert result.get("error") is not True
    assert result["package"] == "CHD"


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
    # DISU OBS node numbers are 1-based (FloPy does not add 1 for a scalar id).
    assert result["site_cellid_map"]["S1"] == 1
    assert result["site_cellid_map"]["S2"] == 2
    entry = read_meta(name)["observations"]["sites"][0]
    assert entry["cellid"] == 1


@requires_mf6
def test_disu_obs_file_is_one_based_and_model_runs(tmp_path):
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_disu_model(tmp_path, "disu_obsrun")
    _impl_import_obs_from_csv(
        name, _write_seq_obs_csv(tmp_path, name), "HEAD", "site", "date", "value",
        None, None, 0,
    )
    flush_model(name)
    obs_text = (resolve_workspace(name) / f"{name}.obs").read_text()
    data_lines = [
        ln.split()
        for ln in obs_text.splitlines()
        if not ln.lstrip().startswith("#")
        and len(ln.split()) >= 3
        and ln.split()[1].upper() == "HEAD"
    ]
    assert data_lines
    node_ids = [parts[2] for parts in data_lines]
    assert node_ids == ["1", "2"]  # 1-based, MF6-valid

    from groundwater_mcp.tools.runner import _impl_run_simulation

    run = _impl_run_simulation(name)
    assert run.get("success") is True, run


def test_import_obs_from_csv_disu_coords_without_geometry_raises(tmp_path):
    name = _build_disu_model(tmp_path, "disu_obsxy")
    csv_path = _write_coord_obs_csv(tmp_path, name)
    with pytest.raises(ValueError, match="no cell-centroid x/y"):
        _impl_import_obs_from_csv(
            name, csv_path, "HEAD", "site", "date", "value", "x", "y", 0
        )


def test_import_obs_from_csv_disu_coords_maps_to_nodes(tmp_path):
    """Coordinate mode on a vertex-carrying DISU grid maps to 1-based nodes."""
    name = _build_vertex_disu_model(tmp_path, "disu_obsxy_ok")
    path = tmp_path / f"{name}_xy.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        writer.writerow(["W1", "2020-01-01", 1.0, 0.5, 0.5])
        writer.writerow(["W2", "2020-01-01", 0.5, 1.5, 0.5])
        writer.writerow(["W3", "2020-01-01", 0.0, 0.5, 1.5])
    result = _impl_import_obs_from_csv(
        name, str(path), "HEAD", "site", "date", "value", "x", "y", 0
    )
    assert result["site_cellid_map"] == {"W1": 1, "W2": 2, "W3": 3}


def test_import_obs_from_csv_disu_cellid_column(tmp_path):
    """An explicit 0-based node column maps to 1-based DISU OBS nodes."""
    name = _build_disu_model(tmp_path, "disu_obsid")
    path = tmp_path / f"{name}_id.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cellid"])
        writer.writerow(["N1", "2020-01-01", 1.0, 0])
        writer.writerow(["N2", "2020-01-01", 0.5, 1])
        writer.writerow(["N3", "2020-01-01", 0.0, 2])
    result = _impl_import_obs_from_csv(
        name, str(path), "HEAD", "site", "date", "value", None, None, 0, "cellid"
    )
    assert result["site_cellid_map"] == {"N1": 1, "N2": 2, "N3": 3}


def test_import_obs_from_csv_disu_cellid_out_of_range_raises(tmp_path):
    name = _build_disu_model(tmp_path, "disu_obsidbad")
    path = tmp_path / f"{name}_idbad.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cellid"])
        writer.writerow(["N1", "2020-01-01", 1.0, 99])
    with pytest.raises(ValueError, match="out of range"):
        _impl_import_obs_from_csv(
            name, str(path), "HEAD", "site", "date", "value", None, None, 0, "cellid"
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


@requires_mf6
def test_setup_calibration_disu_base_run_succeeds(tmp_path):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_disu_model(tmp_path, "disu_calrun")
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
    flush_model(name)
    run = _impl_run_simulation(name)
    assert run.get("success") is True, run


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


# ---------------------------------------------------------------------------
# DISU with explicit vertices/cell2d geometry (coordinate ops + plots)
# ---------------------------------------------------------------------------

_VERTICES = [
    [0, 0.0, 0.0], [1, 1.0, 0.0], [2, 2.0, 0.0],
    [3, 0.0, 1.0], [4, 1.0, 1.0], [5, 2.0, 1.0],
    [6, 0.0, 2.0], [7, 1.0, 2.0],
]
_CELL2D = [
    [0, 0.5, 0.5, 4, 0, 1, 4, 3],
    [1, 1.5, 0.5, 4, 1, 2, 5, 4],
    [2, 0.5, 1.5, 4, 3, 4, 7, 6],
]


def _build_vertex_disu_model(tmp_path, name: str = "disu_vtx") -> str:
    """3-cell L-shaped DISU model carrying vertices/cell2d (has cell x/y).

    Centroids are (0.5, 0.5), (1.5, 0.5), (0.5, 1.5) — deliberately
    non-collinear so the plan-view triangulation is valid.
    """
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    _impl_add_disu_package(
        name, 3, 9, [0.0] * 3, [-1.0] * 3, area=[1.0] * 3,
        iac=[3, 3, 3], ja=[0, 1, 2, 1, 0, 2, 2, 0, 1],
        ihc=[1] * 9, cl12=[1.0] * 9, hwva=[1.0] * 9,
        vertices=_VERTICES, cell2d=_CELL2D,
    )
    _impl_add_npf_package(name, icelltype=0, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=0.5)
    _impl_add_boundary_package(name, "CHD", {"0": [[0, 1.0], [2, 0.0]]}, None)
    _impl_add_oc_package(name, None, None, None, None)
    flush_model(name)
    return name


def test_add_disu_package_with_vertices_gives_cell_centroids(tmp_path):
    from groundwater_mcp.utils.spatial import grid_centroids

    name = _build_vertex_disu_model(tmp_path, "disu_vtxc")
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    assert xc.size == 3
    assert list(np.round(xc, 3)) == [0.5, 1.5, 0.5]
    assert list(np.round(yc, 3)) == [0.5, 0.5, 1.5]


@requires_mf6
def test_plot_heads_map_disu_with_vertices_produces_png(tmp_path):
    from pathlib import Path

    from groundwater_mcp.tools.postprocess import _impl_plot_heads_map
    from groundwater_mcp.tools.runner import _impl_run_simulation
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_vertex_disu_model(tmp_path, "disu_vtxplot")
    run = _impl_run_simulation(name)
    assert run.get("success") is True, run
    result = _impl_plot_heads_map(name)
    assert result.get("error") is not True, result
    p = Path(result["output_file"])
    if not p.is_absolute():
        p = resolve_workspace(name) / p
    assert p.exists() and p.stat().st_size > 0
