"""DISV (unstructured vertex) support for the obs/calibration/reporting layer.

FloPy's ``gwf.get_package("dis")`` prefix-matches the DISV package on a DISV
model (the container compares the first ``len(name)`` characters of the package
type — ``"disv"`` truncated to ``"dis"``), so any code that branched on
``if dis is not None`` silently took the structured path on an unstructured
grid. These tests pin the fix: the obs/calibration/reporting tools must
recognise the grid type and use ``ncol``/``nrow`` only on a true DIS grid.

Also covers OC-declared output discovery when MODFLOW writes into a
subdirectory or uses the GMS ``.hed``/``.ccf`` extensions.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_disv_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
    _impl_summarise_model,
)
from groundwater_mcp.tools.calibration import _impl_setup_calibration
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.spec import _impl_export_model_spec
from groundwater_mcp.utils.model_store import read_meta
from groundwater_mcp.utils.workspace import resolve_workspace


def _mf6_available() -> bool:
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")


_VERTICES = [
    [0, 0.0, 0.0],
    [1, 100.0, 0.0],
    [2, 200.0, 0.0],
    [3, 300.0, 0.0],
    [4, 400.0, 0.0],
    [5, 0.0, 100.0],
    [6, 100.0, 100.0],
    [7, 200.0, 100.0],
    [8, 300.0, 100.0],
    [9, 400.0, 100.0],
]
_CELL2D = [
    [0, 50.0, 50.0, 4, 0, 5, 6, 1],
    [1, 150.0, 50.0, 4, 1, 6, 7, 2],
    [2, 250.0, 50.0, 4, 2, 7, 8, 3],
    [3, 350.0, 50.0, 4, 3, 8, 9, 4],
]


def _build_disv_model(tmp_path, name: str = "disv_support", k=(1.0, 1.0, 5.0, 5.0)) -> str:
    """1-layer, 4-cell DISV model with a CHD gradient (steady state)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate")
    _impl_add_disv_package(name, 1, _VERTICES, _CELL2D, [50.0] * 4, [[40.0] * 4])
    _impl_add_npf_package(
        name, icelltype=0, k=np.array([list(k)]), k33=None, save_flows=True
    )
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, 0], 40.0], [[0, 3], 10.0]]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _write_disv_obs_csv(tmp_path, name: str, nodes=(0, 1, 2, 3)):
    from groundwater_mcp.utils.model_store import get_gwf

    gwf = get_gwf(name)
    mg = gwf.modelgrid
    xc = np.asarray(mg.xcellcenters).ravel()
    yc = np.asarray(mg.ycellcenters).ravel()
    csv_path = tmp_path / f"{name}_obs.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for i, node in enumerate(nodes):
            writer.writerow(
                [f"S{i + 1:02d}", "2020-01-01", 30.0, float(xc[node]), float(yc[node])]
            )
    return str(csv_path)


# ---------------------------------------------------------------------------
# Grid resolution / reporting
# ---------------------------------------------------------------------------


def test_get_dis_is_none_on_disv_model(tmp_path):
    from groundwater_mcp.utils.grid import get_dis, get_disv

    name = _build_disv_model(tmp_path)
    from groundwater_mcp.utils.model_store import get_gwf

    gwf = get_gwf(name)
    assert get_dis(gwf) is None
    assert get_disv(gwf) is not None


def test_summarise_model_disv_reports_unstructured_grid(tmp_path):
    name = _build_disv_model(tmp_path)
    summary = _impl_summarise_model(name)
    assert summary["grid"]["type"] == "DISV"
    assert summary["grid"]["ncpl"] == 4
    assert summary["grid"]["ncells"] == 4


def test_export_model_spec_disv_round_trips_grid_type(tmp_path):
    name = _build_disv_model(tmp_path)
    spec = _impl_export_model_spec(name)["spec"]
    assert spec["grid"]["type"] == "DISV"
    assert spec["grid"]["nlay"] == 1


def test_require_dis_and_crs_rejects_disv(tmp_path):
    from groundwater_mcp.tools.postprocess import _require_dis_and_crs
    from groundwater_mcp.utils.model_store import get_gwf

    name = _build_disv_model(tmp_path)
    with pytest.raises(ValueError, match="structured DIS"):
        _require_dis_and_crs(get_gwf(name))


def test_import_river_from_shapefile_rejects_disv(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    name = _build_disv_model(tmp_path)
    with pytest.raises(RuntimeError, match="DIS grids only"):
        _impl_import_river_from_shapefile(name, str(tmp_path / "nope.shp"), "RIV")


def test_validate_model_disv_does_not_crash(tmp_path):
    from groundwater_mcp.tools.runner import _impl_validate_model

    name = _build_disv_model(tmp_path)
    result = _impl_validate_model(name)
    assert "findings" in result


def test_describe_model_disv_does_not_crash(tmp_path):
    from groundwater_mcp.tools.spec import _impl_describe_model

    name = _build_disv_model(tmp_path)
    result = _impl_describe_model(name)
    assert "error" not in result


# ---------------------------------------------------------------------------
# Observation registration (coordinate mode) on DISV
# ---------------------------------------------------------------------------


def test_import_obs_from_csv_disv_maps_sites_to_nodes(tmp_path):
    name = _build_disv_model(tmp_path)
    csv_path = _write_disv_obs_csv(tmp_path, name)
    result = _impl_import_obs_from_csv(
        name, csv_path, "HEAD", "site", "date", "value", "x", "y", 0
    )
    assert "error" not in result, result
    # Coordinates are the node centroids → exact (layer, node) mapping.
    assert result["site_cellid_map"]["S01"] == [0, 0]
    assert result["site_cellid_map"]["S04"] == [0, 3]

    meta = read_meta(name)["observations"]
    assert [s["cellid"] for s in meta["sites"]] == [[0, 0], [0, 1], [0, 2], [0, 3]]


def test_import_obs_from_csv_disv_sequential_uses_two_tuple_cellids(tmp_path):
    """No-coordinate mode must emit (layer, node) on DISV, not (layer, i, 0)."""
    name = _build_disv_model(tmp_path)
    csv_path = tmp_path / f"{name}_obs_seq.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value"])
        for i in range(2):
            writer.writerow([f"S{i + 1:02d}", "2020-01-01", 30.0])
    result = _impl_import_obs_from_csv(
        name, str(csv_path), "HEAD", "site", "date", "value", None, None, 0
    )
    assert result["site_cellid_map"]["S01"] == [0, 0]
    assert result["site_cellid_map"]["S02"] == [0, 1]


# ---------------------------------------------------------------------------
# setup_calibration on DISV (non-zoned scopes)
# ---------------------------------------------------------------------------


def test_setup_calibration_disv_all_scope(tmp_path):
    name = _build_disv_model(tmp_path)
    csv_path = _write_disv_obs_csv(tmp_path, name, nodes=(0, 1))
    _impl_import_obs_from_csv(name, csv_path, "HEAD", "site", "date", "value", "x", "y", 0)

    result = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 2.0}},
        obs_source="model",
        noptmax=1,
    )
    assert "error" not in result, result
    assert result["n_adjustable_parameters"] == 1
    assert Path(result["pst_file"]).exists()


# ---------------------------------------------------------------------------
# OC-declared output discovery (subdirectory + GMS extensions)
# ---------------------------------------------------------------------------


def _build_dis_model_with_oc(tmp_path, name: str, head_file: str, budget_file: str) -> str:
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    _impl_add_dis_package(name, 1, 2, 2, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    _impl_add_oc_package(name, head_file, budget_file, None, None)
    return name


def test_find_output_file_honours_oc_subdirectory(tmp_path):
    from groundwater_mcp.tools.postprocess import _find_output_file

    name = _build_dis_model_with_oc(
        tmp_path, "oc_subdir", "out/model.hds", "out/model.cbc"
    )
    ws = resolve_workspace(name)
    (ws / "out").mkdir(exist_ok=True)
    target = ws / "out" / "model.hds"
    target.write_bytes(b"stub")
    found, warning = _find_output_file(name, ws, ".hds")
    assert found == target
    assert warning is None


def test_find_output_file_honours_gms_hed_extension(tmp_path):
    from groundwater_mcp.tools.postprocess import _find_output_file

    name = _build_dis_model_with_oc(
        tmp_path, "oc_hed", "out/model.hed", "out/model.ccf"
    )
    ws = resolve_workspace(name)
    (ws / "out").mkdir(exist_ok=True)
    target = ws / "out" / "model.hed"
    target.write_bytes(b"stub")
    found, warning = _find_output_file(name, ws, ".hds")
    assert found == target


def test_find_budget_file_honours_oc_subdirectory_and_ccf(tmp_path):
    from groundwater_mcp.tools.postprocess import _find_budget_file

    name = _build_dis_model_with_oc(
        tmp_path, "oc_ccf", "out/model.hed", "out/model.ccf"
    )
    ws = resolve_workspace(name)
    (ws / "out").mkdir(exist_ok=True)
    target = ws / "out" / "model.ccf"
    target.write_bytes(b"stub")
    found, warning = _find_budget_file(name, ws)
    assert found == target
