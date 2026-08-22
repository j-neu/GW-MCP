"""7e-B — implementation-audit Tier B: correctness bugs (v0.1.0 gate).

Each test maps to an atomic task in tasks.md § 7e Tier B:
B2 (.rei missing → loud error), B3 (narrow excepts), B4.1 (list/delete
models), B4.2 (registry scoping), B5 (assign_top_from_raster method),
B6 (DISV layer_surfaces), B8 (RCHA/EVTA array packages), B9 (idomain),
B10 (pname), B11.1 (set_model_crs), B11.2/B11.3 (CRS + fill),
B12 (NaN sanitizer), B13 (OC filerecord selection), B14 (sentinels),
B16 (no stale UCODE references). B1.1/B1.2 are covered in
test_calibration.py; B7 was superseded by 7f-H1.2; B17/B18 by
test_mcp_protocol.py.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from groundwater_mcp.server import _sanitise, mcp
from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_delete_model,
    _impl_list_models,
    _impl_set_model_crs,
    _impl_set_simulation,
    _impl_summarise_model,
)
from groundwater_mcp.tools.calibration import (
    _impl_setup_pest_control,
    _impl_summarise_calibration,
)
from groundwater_mcp.tools.parameterise import (
    _impl_assign_top_from_raster,
    _impl_import_grid_from_shapefile,
)
from groundwater_mcp.tools.postprocess import (
    _array_stats,
    _find_budget_file,
    _find_output_file,
    _impl_compute_water_balance,
    _impl_read_heads,
)
from groundwater_mcp.tools.runner import _find_mf6_binary, _impl_run_simulation
from groundwater_mcp.utils.model_store import flush_model, get_gwf
from groundwater_mcp.utils.spatial import CRSError
from groundwater_mcp.utils.workspace import resolve_workspace


def _run(coro):
    return asyncio.run(coro)


def _parse(result) -> dict | list:
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


def _write_raster(
    tmp_path: Path,
    name: str,
    data: np.ndarray,
    width: float,
    height: float,
    crs: str = "EPSG:32755",
    nodata: float | None = None,
    xoff: float = 0.0,
    yoff: float = 0.0,
) -> Path:
    """Write *data* (nrow, ncol) as a GeoTIFF covering
    (xoff, yoff, xoff + width, yoff + height)."""
    import rasterio
    from rasterio.transform import from_bounds

    nrow, ncol = data.shape
    kwargs = {"nodata": nodata} if nodata is not None else {}
    path = tmp_path / name
    with rasterio.open(
        path, "w", driver="GTiff", height=nrow, width=ncol, count=1,
        dtype="float64", crs=crs,
        transform=from_bounds(xoff, yoff, xoff + width, yoff + height, ncol, nrow),
        **kwargs,
    ) as dst:
        dst.write(data, 1)
    return path


def _ramp_raster(tmp_path: Path, name: str = "ramp.tif", ncol: int = 40, nrow: int = 40) -> Path:
    """A raster whose value at each pixel equals the pixel-centre x coordinate."""
    xc = (np.arange(ncol) + 0.5) * (1000.0 / ncol)
    return _write_raster(tmp_path, name, np.tile(xc, (nrow, 1)), 1000.0, 1000.0)


def _synthetic_hds(ws: Path, name: str, nlay: int = 1, nrow: int = 5, ncol: int = 5) -> None:
    """Write a minimal valid MODFLOW 6 head file (single precision, unframed).

    MODFLOW 6 binary files carry no Fortran record markers, unlike the
    MODFLOW-2005 format flopy still reads.
    """
    import struct

    heads = np.linspace(8.0, 3.0, ncol * nrow).reshape(nrow, ncol)
    path = ws / name
    header = struct.pack(
        "=2i2f16s3i", 1, 1, 1.0, 1.0, b"            HEAD", ncol, nrow, nlay,
    )
    with open(path, "wb") as f:
        f.write(header)
        f.write(heads.astype(np.float32).tobytes())


def _build_dis_model(tmp_path: Path, name: str, crs: str | None = None) -> str:
    """A model with a 5×5 DIS grid (delr=delc=100, extent 0..500)."""
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 50.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=5.0)
    if crs is not None:
        get_gwf(name).modelgrid.set_coord_info(xoff=0.0, yoff=0.0, crs=crs)
    return name


def _write_pst_artifacts(model: str, pst_file: str) -> None:
    """Write a .par and .rei so summarise_calibration's happy path works."""
    ws = resolve_workspace(model)
    base = Path(pst_file).stem
    (ws / f"{base}.par").write_text("single point\nk        42.0  1.0  0\n")
    (ws / f"{base}.rei").write_text(
        "PEST++ - GLM\n"
        "   name     group     measured   modelled    residual    weight\n"
        "h1  heads  5.0  4.9  0.1  1.0\n"
        "h2  heads  4.8  4.7  0.1  1.0\n"
        "h3  heads  4.6  4.5  0.1  1.0\n"
        "h4  heads  4.4  4.3  0.1  1.0\n"
        "h5  heads  4.2  4.1  0.1  1.0\n"
    )


# ---------------------------------------------------------------------------
# B2 — summarise_calibration fails loudly when the run died before residuals
# ---------------------------------------------------------------------------


def test_summarise_calibration_missing_rei_mcp_envelope(tmp_path, model_name):
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    ws = resolve_workspace(model_name)
    (ws / "params.tpl").write_text("ptf ~\n~  k  ~\n")
    (ws / "heads.ins").write_text("pif @\nl1 !h1!\n")
    setup = _impl_setup_pest_control(
        model=model_name,
        obs_data={"h1": {"obsval": 5.0, "weight": 1.0}},
        par_data={"k": {"parval1": 10.0}},
        template_files=["params.tpl"],
        instruction_files=["heads.ins"],
    )
    # .par exists but no .rei — the run died before residuals
    base = Path(setup["pst_file"]).stem
    (ws / f"{base}.par").write_text("single point\nk  42.0  1.0  0\n")
    result = _run(mcp.call_tool("summarise_calibration", {
        "model": model_name,
        "pst_file": setup["pst_file"],
    }))
    data = _parse(result)
    assert data.get("error") is True
    assert data["code"] == "OUTPUT_FILE_MISSING"
    assert "rei" in data["message"].lower() or "residual" in data["message"].lower()


def test_summarise_calibration_happy_path_with_rei(tmp_path, model_name):
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    ws = resolve_workspace(model_name)
    (ws / "params.tpl").write_text("ptf ~\n~  k  ~\n")
    (ws / "heads.ins").write_text("pif @\nl1 !h1!\n")
    setup = _impl_setup_pest_control(
        model=model_name,
        obs_data={"h1": {"obsval": 5.0, "weight": 1.0}},
        par_data={"k": {"parval1": 10.0}},
        template_files=["params.tpl"],
        instruction_files=["heads.ins"],
    )
    _write_pst_artifacts(model_name, setup["pst_file"])
    result = _impl_summarise_calibration(model_name, setup["pst_file"])
    assert "error" not in result
    assert result["residual_statistics"]["n_observations"] == 5
    assert result["residual_statistics"]["rmse"] is not None


# ---------------------------------------------------------------------------
# B3 — narrow the broad excepts on the calibration hot path
# ---------------------------------------------------------------------------


def test_read_phi_csv_corrupt_raises(tmp_path):
    """A genuinely corrupt phi CSV must surface an error, not empty progress
    (7e-B3 — the old bare except returned ([], None) as a success)."""
    from groundwater_mcp.tools.calibration import _read_phi_csv

    corrupt = tmp_path / "m.phi.actual.csv"
    corrupt.write_bytes(b"\x00\x01\xff\xfe garbage without newlines")
    with pytest.raises(Exception):
        _read_phi_csv(corrupt)


def test_read_iobj_phi_corrupt_raises(tmp_path):
    from groundwater_mcp.tools.calibration import _read_iobj_phi

    corrupt = tmp_path / "m.iobj"
    corrupt.write_bytes(b"iteration,total_phi\n\x00\xff broken")
    with pytest.raises(Exception):
        _read_iobj_phi(corrupt)


def test_parse_par_file_corrupt_raises(tmp_path):
    """A malformed .par (a directory where a file is expected) must surface an
    error, not silently return {} (7e-B3)."""
    from groundwater_mcp.tools.calibration import _parse_par_file

    bad = tmp_path / "m.par"
    bad.mkdir()
    with pytest.raises(OSError):
        _parse_par_file(bad)


def test_summarise_calibration_corrupt_par_mcp_envelope(tmp_path, model_name):
    """A malformed .par surfaces PEST_ERROR with a message, not a success dict
    with null fields (7e-B3)."""
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    ws = resolve_workspace(model_name)
    (ws / "params.tpl").write_text("ptf ~\n~  k  ~\n")
    (ws / "heads.ins").write_text("pif @\nl1 !h1!\n")
    setup = _impl_setup_pest_control(
        model=model_name,
        obs_data={"h1": {"obsval": 5.0, "weight": 1.0}},
        par_data={"k": {"parval1": 10.0}},
        template_files=["params.tpl"],
        instruction_files=["heads.ins"],
    )
    base = Path(setup["pst_file"]).stem
    (ws / f"{base}.par").mkdir()  # a directory where a .par file is expected
    (ws / f"{base}.rei").write_text(
        "PEST++ - GLM\n   name  group  measured  modelled  residual  weight\n"
        "h1  heads  5.0  4.9  0.1  1.0\n"
    )
    result = _run(mcp.call_tool("summarise_calibration", {
        "model": model_name,
        "pst_file": setup["pst_file"],
    }))
    data = _parse(result)
    assert data.get("error") is True
    assert data["code"] == "PEST_ERROR"
    assert data["message"]


# ---------------------------------------------------------------------------
# B4.1 — list_models / delete_model exposed as MCP tools
# ---------------------------------------------------------------------------


def test_list_models_and_delete_model_mcp(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")

    listed = _impl_list_models()
    assert "models" in listed and model_name in listed["models"]

    result = _run(mcp.call_tool("list_models", {}))
    data = _parse(result)
    assert model_name in data["models"]

    deleted = _impl_delete_model(model_name)
    assert deleted["removed"] is True
    assert model_name not in _impl_list_models()["models"]

    # a fresh create with the same name succeeds
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    assert "error" not in result


def test_delete_model_mcp_envelope_unknown(tmp_path):
    result = _run(mcp.call_tool("delete_model", {"model": "no_such_model_xyz"}))
    data = _parse(result)
    assert data.get("error") is True
    assert data["code"] == "MODEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# B5 — assign_top_from_raster method is honoured, not ignored
# ---------------------------------------------------------------------------


def test_assign_top_zonal_methods_min_mean_max(tmp_path, model_name):
    """On a ramp raster (value = pixel x), per-cell zonal min < mean < max
    (7e-B5 — the methods used to be silently ignored point-sampling)."""
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    raster = _ramp_raster(tmp_path)

    r_min = _impl_assign_top_from_raster(name, str(raster), 0, method="min")
    r_mean = _impl_assign_top_from_raster(name, str(raster), 0, method="mean")
    r_max = _impl_assign_top_from_raster(name, str(raster), 0, method="max")

    assert "error" not in r_min and "error" not in r_mean and "error" not in r_max
    # Cells cover x 0..500; pixel width 25 → per-cell min/mean/max across the
    # 5 columns average to 212.5 / 250 / 287.5, and min < mean < max.
    assert r_min["mean"] == pytest.approx(212.5, abs=1e-6)
    assert r_mean["mean"] == pytest.approx(250.0, abs=1e-6)
    assert r_max["mean"] == pytest.approx(287.5, abs=1e-6)
    assert r_min["mean"] < r_mean["mean"] < r_max["mean"]


def test_assign_top_bilinear_differs_from_nearest(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    # 38×38 pixels (~26.3 m) so the 100 m cell centroids fall mid-pixel —
    # bilinear then interpolates (≈ centroid value) while nearest picks a side.
    raster = _ramp_raster(tmp_path, "ramp38.tif", ncol=38, nrow=38)

    _impl_assign_top_from_raster(name, str(raster), 0, method="nearest")
    near_top = get_gwf(name).get_package("dis").top.array.copy()
    _impl_assign_top_from_raster(name, str(raster), 0, method="bilinear")
    bil_top = get_gwf(name).get_package("dis").top.array

    # The mean agrees (symmetric ramp) but the per-cell values differ at the
    # non-centre points — bilinear tracks the centroid value, nearest a side.
    assert not np.allclose(near_top, bil_top)
    assert bil_top.mean() == pytest.approx(250.0, abs=2.0)
    assert np.allclose(bil_top, near_top) is False


def test_assign_top_invalid_method_rejected(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    raster = _ramp_raster(tmp_path)
    with pytest.raises(ValueError, match="method"):
        _impl_assign_top_from_raster(name, str(raster), 0, method="bogus")


# ---------------------------------------------------------------------------
# B6 — DISV layer_surfaces is rejected, not silently ignored
# ---------------------------------------------------------------------------


def test_import_grid_disv_layer_surfaces_rejected(tmp_path, model_name):
    import geopandas as gpd
    from shapely.geometry import Polygon

    poly = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:32755")
    shp = tmp_path / "catchment.gpkg"
    gdf.to_file(shp, driver="GPKG")

    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    with pytest.raises(ValueError, match="layer_surfaces"):
        _impl_import_grid_from_shapefile(
            model_name, str(shp), 1, ["top.tif", "botm.tif"], "disv", None, 200.0
        )
    result = _run(mcp.call_tool("import_grid_from_shapefile", {
        "model": model_name,
        "shapefile": str(shp),
        "nlay": 1,
        "layer_surfaces": ["top.tif", "botm.tif"],
        "method": "disv",
        "cell_size": 200.0,
    }))
    data = _parse(result)
    assert data.get("error") is True
    assert data["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# B8 — array-based RCHA/EVTA packages
# ---------------------------------------------------------------------------


@requires_mf6
def test_rcha_full_grid_array_runs_and_budgets(tmp_path, model_name):
    """An RCHA full-grid array writes an array-based package; the model runs
    and the budget RCH term equals rate × cell_area × n_cells (7e-B8).

    Steady state with a drain providing the outflow — recharge is applied to
    every active cell (unlike constant-head cells, which MF6 excludes from
    the RCH budget term).
    """
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "moderate")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 50.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.0)
    rate = 0.001  # m/d
    rcha = np.full((5, 5), rate)
    result = _impl_add_boundary_package(model_name, "RCHA", {0: rcha}, None, save_flows=True)
    assert "error" not in result
    assert result["package"] == "RCHA"
    assert result["stress_periods"] == {0: 25}
    drn = [[[0, 0, c], 0.0, 1000.0] for c in range(5)]
    _impl_add_boundary_package(model_name, "DRN", {0: drn}, None)
    _impl_add_oc_package(model_name, None, None, None, None)

    run = _impl_run_simulation(model_name, silent=True)
    assert run["success"] is True, run.get("listing_summary", run)

    wb = _impl_compute_water_balance(model_name)
    rch_key = next((k for k in wb["inflow"] if "RCH" in k), None)
    assert rch_key is not None, f"no RCH budget term in {wb['inflow']}"
    assert wb["inflow"][rch_key] == pytest.approx(rate * 100.0 * 100.0 * 25, rel=1e-2)


@requires_mf6
def test_evta_rate_units_converted(tmp_path, model_name):
    """EVTA accepts a full-grid rate array and converts rate_units on entry."""
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "moderate")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 50.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.0)
    result = _impl_add_boundary_package(
        model_name, "EVTA", {0: np.full((5, 5), 365.0)}, None, save_flows=True, rate_units="mm/yr"
    )
    assert "error" not in result
    ws = resolve_workspace(model_name)
    flush_model(model_name)
    evta_text = (ws / f"{model_name}.evta").read_text()
    # 365 mm/yr = 0.001 m/d
    assert "1.0e-03" in evta_text.replace("0.001", "1.0e-03") or "0.001" in evta_text


# ---------------------------------------------------------------------------
# B9 — add_dis_package idomain
# ---------------------------------------------------------------------------


def test_add_dis_idomain_writes_and_counts(tmp_path, model_name):
    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    idomain = np.ones((5, 5), dtype=int)
    idomain[0, 0] = -1  # one inactive cell
    result = _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0], idomain=idomain)
    assert "error" not in result
    flush_model(model_name)
    ws = resolve_workspace(model_name)
    assert "IDOMAIN" in (ws / f"{model_name}.dis").read_text().upper()
    summary = _impl_summarise_model(model_name)
    assert summary["grid"]["n_active"] == 24


# ---------------------------------------------------------------------------
# B10 — multiple packages per type via pname
# ---------------------------------------------------------------------------


def test_boundary_package_pname_coexists(tmp_path, model_name):
    _build_dis_model(tmp_path, model_name)
    r1 = _impl_add_boundary_package(
        model_name, "CHD", {0: [[[0, 0, 0], 10.0]]}, None, pname="chd_high"
    )
    r2 = _impl_add_boundary_package(
        model_name, "CHD", {0: [[[0, 4, 4], 2.0]]}, None, pname="chd_low"
    )
    assert "error" not in r1 and "error" not in r2

    gwf = get_gwf(model_name)
    nam_list = gwf.get_package_list()
    assert "CHD_HIGH" in nam_list and "CHD_LOW" in nam_list

    # Re-adding with the same pname replaces only that package
    r3 = _impl_add_boundary_package(
        model_name, "CHD", {0: [[[0, 1, 1], 5.0]]}, None, pname="chd_high"
    )
    assert "warning" in r3 and "chd_high" in r3["warning"]
    nam_list = gwf.get_package_list()
    assert "CHD_HIGH" in nam_list and "CHD_LOW" in nam_list

    summary = _impl_summarise_model(model_name)
    assert "CHD" in summary["boundary_types"]


def test_boundary_package_no_pname_replaces_all(tmp_path, model_name):
    _build_dis_model(tmp_path, model_name)
    _impl_add_boundary_package(model_name, "CHD", {0: [[[0, 0, 0], 10.0]]}, None, pname="chd_a")
    _impl_add_boundary_package(model_name, "CHD", {0: [[[0, 4, 4], 2.0]]}, None, pname="chd_b")
    result = _impl_add_boundary_package(model_name, "CHD", {0: [[[0, 2, 2], 7.0]]}, None)
    assert "warning" in result
    gwf = get_gwf(model_name)
    nam_list = [p for p in gwf.get_package_list() if p.startswith("CHD")]
    assert len(nam_list) == 1


# ---------------------------------------------------------------------------
# B11.1 — set_model_crs
# ---------------------------------------------------------------------------


def test_set_model_crs_enables_spatial_sampling(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name)  # no CRS
    raster = _ramp_raster(tmp_path)

    # Without a CRS on the grid, sampling must fail loudly (B11.2).
    with pytest.raises(CRSError):
        _impl_assign_top_from_raster(name, str(raster), 0, method="nearest")

    result = _impl_set_model_crs(name, "EPSG:32755", xorigin=0.0, yorigin=0.0)
    assert "error" not in result
    gwf = get_gwf(name)
    assert gwf.modelgrid.crs is not None
    assert "32755" in str(gwf.modelgrid.crs)

    assigned = _impl_assign_top_from_raster(name, str(raster), 0, method="nearest")
    assert "error" not in assigned
    assert assigned["mean"] == pytest.approx(262.5, abs=1.0)


# ---------------------------------------------------------------------------
# B11.2 / B11.3 — CRS safety and explicit no-data fill
# ---------------------------------------------------------------------------


def test_assign_top_crs_unknown_mcp_envelope(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name)  # no CRS
    raster = _ramp_raster(tmp_path)  # declares EPSG:32755
    result = _run(mcp.call_tool("assign_top_from_raster", {
        "model": name,
        "raster": str(raster),
        "layer": 0,
        "method": "nearest",
    }))
    data = _parse(result)
    assert data.get("error") is True
    assert data["code"] == "CRS_UNKNOWN"


def test_assign_top_zero_coverage_errors(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    # raster covering 5000..5100 — disjoint from the grid's 0..500 extent
    far = _write_raster(tmp_path, "far.tif", np.full((10, 10), 100.0), 100.0, 100.0,
                        xoff=5000.0, yoff=5000.0)
    with pytest.raises(ValueError, match="does not cover"):
        _impl_assign_top_from_raster(name, str(far), 0, method="nearest")


def _hole_raster(tmp_path: Path, name: str = "hole.tif") -> Path:
    """A 38×38 raster (pixel ~26.3 m) with a nodata hole over the grid cells
    whose centroids fall at x 250/350 and y 250/350 (a 4-of-25 = 16% gap).

    Raster rows run top-down (row 0 = y 1000), so the low-y grid centroids
    land in high row indices: y 250 → row 28, y 350 → row 24, y 450 → row 20.
    """
    data = np.full((38, 38), 10.0)
    data[20:29, 9:14] = -9999.0
    return _write_raster(tmp_path, name, data, 1000.0, 1000.0, nodata=-9999.0)


def test_assign_top_fill_error_above_tolerance(tmp_path, model_name):
    """A hole covering >10% of cells errors under fill='error' (7e-B11.3)."""
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    raster = _hole_raster(tmp_path)
    with pytest.raises(ValueError, match="coverage"):
        _impl_assign_top_from_raster(name, str(raster), 0, method="nearest", fill="error")


def test_assign_top_fill_median_warns_and_fills(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    raster = _hole_raster(tmp_path)
    result = _impl_assign_top_from_raster(
        name, str(raster), 0, method="nearest", fill="median"
    )
    assert "error" not in result
    assert result["cells_no_coverage"] > 0
    assert "warning" in result
    assert result["min"] == result["max"]  # all filled — no uncovered remainder


def test_assign_top_fill_nearest_no_nan(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name, crs="EPSG:32755")
    raster = _hole_raster(tmp_path)
    result = _impl_assign_top_from_raster(
        name, str(raster), 0, method="nearest", fill="nearest"
    )
    assert "error" not in result
    assert result["cells_no_coverage"] > 0
    assert result["min"] == pytest.approx(10.0)
    assert result["max"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# B12 — NaN/Inf never reach the JSON response
# ---------------------------------------------------------------------------


def test_sanitise_non_finite_to_none():
    data = {
        "min": float("nan"),
        "max": float("inf"),
        "ok": 1.5,
        "nested": [float("-inf"), 2.0, {"a": float("nan")}],
    }
    out = _sanitise(data)
    json.dumps(out, allow_nan=False)  # must not raise
    assert out["min"] is None
    assert out["max"] is None
    assert out["nested"][0] is None
    assert out["nested"][1] == 2.0
    assert out["nested"][2]["a"] is None
    assert out["ok"] == 1.5


def test_sanitise_leaves_other_objects_untouched():
    class _Marker:
        pass

    marker = _Marker()
    assert _sanitise({"image": marker})["image"] is marker


# ---------------------------------------------------------------------------
# B13 — output-file selection prefers the OC filerecord
# ---------------------------------------------------------------------------


def test_find_output_file_prefers_oc_declared(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name)
    _impl_add_oc_package(name, head_filerecord="special.hds", budget_filerecord="special.cbb",
                         saverecord=None, printrecord=None)
    flush_model(name)
    ws = resolve_workspace(name)
    _synthetic_hds(ws, "special.hds")
    _synthetic_hds(ws, "other.hds")

    path, warning = _find_output_file(name, ws, ".hds")
    assert path.name == "special.hds"
    assert warning is None


def test_find_output_file_warns_on_multiple_undeclared(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name)  # no OC package
    ws = resolve_workspace(name)
    _synthetic_hds(ws, "a.hds")
    _synthetic_hds(ws, "b.hds")

    path, warning = _find_output_file(name, ws, ".hds")
    assert path.name in ("a.hds", "b.hds")
    assert warning is not None
    assert "a.hds" in warning and "b.hds" in warning


def test_find_budget_file_prefers_oc_declared(tmp_path, model_name):
    name = _build_dis_model(tmp_path, model_name)
    _impl_add_oc_package(name, head_filerecord="h.hds", budget_filerecord="declared.cbb",
                         saverecord=None, printrecord=None)
    flush_model(name)
    ws = resolve_workspace(name)
    (ws / "declared.cbb").write_bytes(b"budget")
    (ws / "other.cbc").write_bytes(b"budget2")

    path, warning = _find_budget_file(name, ws)
    assert path.name == "declared.cbb"
    assert warning is None


# ---------------------------------------------------------------------------
# B14 — _array_stats masks both sentinels (+1e30 and −1e30)
# ---------------------------------------------------------------------------


def test_array_stats_masks_both_sentinels():
    arr = np.array([[1e30, -1e30, 5.0], [2.0, 3.0, 4.0]])
    assert _array_stats(arr) == {"min": 2.0, "max": 5.0, "mean": 3.5}


def test_read_heads_stats_ignore_dry_sentinel(tmp_path, model_name):
    """A -1e30 dry-cell sentinel must not wreck read_heads stats (7e-B14)."""

    name = _build_dis_model(tmp_path, model_name)
    ws = resolve_workspace(name)
    import struct

    heads = np.full((5, 5), 6.0)
    heads[0, 0] = -1e30
    heads[1, 1] = 1e30
    path = ws / f"{name}.hds"
    header = struct.pack(
        "=2i2f16s3i", 1, 1, 1.0, 1.0, b"            HEAD", 5, 5, 1,
    )
    with open(path, "wb") as f:
        f.write(header)
        f.write(heads.astype(np.float32).tobytes())
    result = _impl_read_heads(name, include_values=True)
    assert "error" not in result
    assert result["min"] == pytest.approx(6.0)
    assert result["mean"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# B16 — no stale UCODE references in the codebase
# ---------------------------------------------------------------------------


def test_no_stale_ucode_references():
    """UCODE was dropped from project scope (Phase 5 decision, 2026-08-17);
    grep -ri ucode src/ must return nothing."""
    import re

    from groundwater_mcp import tools

    src_root = Path(tools.__file__).parent.parent
    hits = []
    for p in src_root.rglob("*.py"):
        if "site-packages" in str(p):
            continue
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if re.search(r"ucode", line, re.IGNORECASE):
                hits.append(f"{p}:{i}")
    assert not hits, f"stale UCODE references: {hits}"
