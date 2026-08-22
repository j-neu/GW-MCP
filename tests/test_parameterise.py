"""Tests for tools/parameterise.py — spatial data import tools."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Synthetic geodata fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def catchment_shapefile(tmp_path: Path) -> Path:
    """A 1 km × 1 km square catchment polygon (EPSG:32755 / UTM zone 55S)."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    poly = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:32755")
    path = tmp_path / "catchment.gpkg"
    gdf.to_file(path, driver="GPKG")
    return path


@pytest.fixture()
def zone_shapefile(tmp_path: Path) -> Path:
    """Two K zones side by side (K=1.0 on left, K=5.0 on right)."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    zones = [
        Polygon([(0, 0), (500, 0), (500, 1000), (0, 1000)]),
        Polygon([(500, 0), (1000, 0), (1000, 1000), (500, 1000)]),
    ]
    gdf = gpd.GeoDataFrame(
        {"k_hk": [1.0, 5.0], "k_vk": [0.1, 0.5], "geometry": zones},
        crs="EPSG:32755",
    )
    path = tmp_path / "zones.gpkg"
    gdf.to_file(path, driver="GPKG")
    return path


@pytest.fixture()
def dem_raster(tmp_path: Path) -> Path:
    """A 10×10 DEM GeoTIFF with values ranging from 50 to 100 m."""
    import rasterio
    from rasterio.transform import from_bounds

    data = np.linspace(50.0, 100.0, 100).reshape(10, 10).astype(np.float32)
    transform = from_bounds(0, 0, 1000, 1000, 10, 10)
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:32755",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture()
def river_shapefile(tmp_path: Path) -> Path:
    """A single river reach running diagonally across the catchment."""
    import geopandas as gpd
    from shapely.geometry import LineString

    line = LineString([(0, 500), (500, 500), (1000, 500)])
    gdf = gpd.GeoDataFrame(
        {"stage": [45.0], "conductance": [500.0], "geometry": [line]},
        crs="EPSG:32755",
    )
    path = tmp_path / "river.gpkg"
    gdf.to_file(path, driver="GPKG")
    return path


@pytest.fixture()
def obs_csv(tmp_path: Path) -> Path:
    """Three observation sites with two head readings each."""
    import pandas as pd

    data = pd.DataFrame({
        "site": ["BH01", "BH01", "BH02", "BH02", "BH03", "BH03"],
        "date": ["2020-01-01", "2020-04-01"] * 3,
        "value": [48.5, 48.2, 65.3, 65.1, 52.7, 52.4],
        "x": [250.0, 250.0, 750.0, 750.0, 500.0, 500.0],
        "y": [250.0, 250.0, 750.0, 750.0, 500.0, 500.0],
    })
    path = tmp_path / "obs.csv"
    data.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Model fixture with DIS grid (reused by most tests)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dis_model(tmp_path, model_name):
    """A model with TDIS, IMS, a 10×10 DIS grid over a 1 km catchment, and NPF/IC.

    The grid carries an explicit CRS (EPSG:32755, matching every spatial fixture
    in this module) so the CRS-safety checks in the spatial tools (7f-D2) are
    not tripped by the "grid without CRS + data with CRS" guard.
    """
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils.model_store import get_gwf

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [365.0], [12], "moderate")
    _impl_add_dis_package(
        model_name,
        nlay=2,
        nrow=10,
        ncol=10,
        delr=100.0,
        delc=100.0,
        top=50.0,
        botm=[40.0, 30.0],
    )
    _impl_add_npf_package(model_name, icelltype=1, k=1.0, k33=0.1, save_flows=True)
    _impl_add_ic_package(model_name, strt=45.0)
    get_gwf(model_name).modelgrid.set_coord_info(xoff=0.0, yoff=0.0, crs="EPSG:32755")
    return model_name


def _ramp_raster_x(tmp_path, name, ncol, nrow, width, height, crs="EPSG:32755", nodata=None):
    """A GeoTIFF whose value at each pixel equals the pixel-centre x coordinate."""
    import rasterio
    from rasterio.transform import from_bounds

    xc = (np.arange(ncol) + 0.5) * (width / ncol)
    data = np.tile(xc, (nrow, 1)).astype(np.float64)
    kwargs = {}
    if nodata is not None:
        kwargs["nodata"] = nodata
    path = tmp_path / name
    with rasterio.open(
        path, "w", driver="GTiff", height=nrow, width=ncol, count=1,
        dtype="float64", crs=crs, transform=from_bounds(0, 0, width, height, ncol, nrow),
        **kwargs,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture()
def dis_model_crs(tmp_path, model_name):
    """Non-square DIS grid (5 rows × 10 cols, delr=100, delc=200) with CRS EPSG:32755.

    Non-square so a transposed (y, x) raster query is not accidentally equal to
    the true (x, y) centroid query (7f-D1.1 regression guard).
    """
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils.model_store import get_gwf

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [365.0], [12], "moderate")
    _impl_add_dis_package(
        model_name,
        nlay=1,
        nrow=5,
        ncol=10,
        delr=100.0,
        delc=200.0,
        top=50.0,
        botm=[30.0],
    )
    get_gwf(model_name).modelgrid.set_coord_info(xoff=0.0, yoff=0.0, crs="EPSG:32755")
    return model_name


@pytest.fixture()
def river_mid_shapefile(tmp_path):
    """A horizontal river crossing the middle of the 5×10 grid at y=500."""
    import geopandas as gpd
    from shapely.geometry import LineString

    line = LineString([(0, 500), (1000, 500)])
    gdf = gpd.GeoDataFrame(geometry=[line], crs="EPSG:32755")
    path = tmp_path / "river_mid.gpkg"
    gdf.to_file(path, driver="GPKG")
    return path


@pytest.fixture()
def river_utm18_pair(tmp_path):
    """The same river in native EPSG:32718 and reprojected to EPSG:4326."""
    import geopandas as gpd
    from shapely.geometry import LineString

    line = LineString([(250, 500), (1750, 500)])
    gdf = gpd.GeoDataFrame(geometry=[line], crs="EPSG:32718")
    native = tmp_path / "river_utm18.gpkg"
    gdf.to_file(native, driver="GPKG")
    ll = tmp_path / "river_4326.gpkg"
    gdf.to_crs("EPSG:4326").to_file(ll, driver="GPKG")
    return native, ll


# ---------------------------------------------------------------------------
# import_grid_from_shapefile — DIS method
# ---------------------------------------------------------------------------


def test_import_grid_dis_creates_package(tmp_path, model_name, catchment_shapefile):
    from groundwater_mcp.tools.builder import _impl_create_model, _impl_set_simulation
    from groundwater_mcp.tools.parameterise import _impl_import_grid_from_shapefile

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")

    result = _impl_import_grid_from_shapefile(
        model_name,
        str(catchment_shapefile),
        nlay=2,
        layer_surfaces=[],
        method="dis",
        target_crs=None,
        cell_size=200.0,
    )
    assert "error" not in result
    assert result["grid_type"] == "DIS"
    assert result["nrow"] == 5
    assert result["ncol"] == 5
    assert result["nlay"] == 2


def test_import_grid_dis_writes_dis_file(tmp_path, model_name, catchment_shapefile):
    from groundwater_mcp.tools.builder import _impl_create_model, _impl_set_simulation
    from groundwater_mcp.tools.parameterise import _impl_import_grid_from_shapefile
    from groundwater_mcp.utils.model_store import flush_model
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    _impl_import_grid_from_shapefile(
        model_name, str(catchment_shapefile), 1, [], "dis", None, 200.0
    )
    flush_model(model_name)
    model_ws = resolve_workspace(model_name)
    assert (model_ws / f"{model_name}.dis").exists()


def test_import_grid_persists_crs_to_meta_and_survives_reload(
    tmp_path, model_name, catchment_shapefile
):
    """A CRS set in-call by import_grid_from_shapefile must be persisted to
    .gwmcp_meta.json and re-applied after a disk reload.

    Regression for modeB rerun-6: the grid CRS was set in-call but never
    persisted, so after the calibration rewrites reloaded the model the
    exporters failed CRS_UNKNOWN.
    """
    from groundwater_mcp.tools.builder import _impl_create_model, _impl_set_simulation
    from groundwater_mcp.tools.parameterise import _impl_import_grid_from_shapefile
    from groundwater_mcp.utils.model_store import flush_model, get_gwf, invalidate, read_meta

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    result = _impl_import_grid_from_shapefile(
        model_name, str(catchment_shapefile), 1, [], "dis", "EPSG:32755", 200.0
    )
    assert "error" not in result
    flush_model(model_name)

    meta = read_meta(model_name)
    assert "crs" in meta, "import_grid_from_shapefile must persist the CRS to meta"

    invalidate(model_name)  # drop the cached sim — next access reloads from disk
    gwf = get_gwf(model_name)
    assert gwf.modelgrid.crs is not None, "CRS lost after reload from disk"
    assert gwf.modelgrid.crs.to_epsg() == 32755


# ---------------------------------------------------------------------------
# assign_top_from_raster
# ---------------------------------------------------------------------------


def test_assign_top_from_raster(dis_model, dem_raster):
    from groundwater_mcp.tools.parameterise import _impl_assign_top_from_raster
    from groundwater_mcp.utils.model_store import get_gwf

    result = _impl_assign_top_from_raster(dis_model, str(dem_raster), layer=0, method="mean")
    assert "error" not in result
    assert result["cells_assigned"] == 100  # 10x10 grid
    assert result["min"] >= 50.0
    assert result["max"] <= 100.0

    # Verify the DIS package was updated in memory
    gwf = get_gwf(dis_model)
    top_array = gwf.dis.top.array
    assert top_array.shape == (10, 10)
    assert float(top_array.min()) >= 49.9  # allow small float tolerance


def test_assign_layer_bottom_from_raster(dis_model, dem_raster):
    from groundwater_mcp.tools.parameterise import _impl_assign_top_from_raster

    result = _impl_assign_top_from_raster(dis_model, str(dem_raster), layer=1, method="mean")
    assert "error" not in result
    assert result["layer"] == 1


# ---------------------------------------------------------------------------
# assign_k_from_zones
# ---------------------------------------------------------------------------


def test_assign_k_from_zones(dis_model, zone_shapefile):
    from groundwater_mcp.tools.parameterise import _impl_assign_k_from_zones
    from groundwater_mcp.utils.model_store import get_gwf

    result = _impl_assign_k_from_zones(
        dis_model, str(zone_shapefile), k_field="k_hk", layer=0,
        k33_field="k_vk", icelltype_field=None,
    )
    assert "error" not in result
    assert result["zone_count"] == 2
    assert result["cells_matched"] == 100  # all 100 cells should be inside the two zones

    # Left 5 columns → K=1.0, right 5 → K=5.0
    gwf = get_gwf(dis_model)
    k_array = gwf.npf.k.array[0]  # layer 0
    assert float(k_array[0, 0]) == pytest.approx(1.0)
    assert float(k_array[0, 9]) == pytest.approx(5.0)


def test_assign_k_invalid_field_raises(dis_model, zone_shapefile):
    from groundwater_mcp.tools.parameterise import _impl_assign_k_from_zones

    with pytest.raises(ValueError, match="not found"):
        _impl_assign_k_from_zones(
            dis_model, str(zone_shapefile), k_field="nonexistent_field", layer=0,
            k33_field=None, icelltype_field=None,
        )


# ---------------------------------------------------------------------------
# import_river_from_shapefile
# ---------------------------------------------------------------------------


def test_import_river_riv_package(dis_model, river_shapefile):
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile
    from groundwater_mcp.utils.model_store import get_gwf

    result = _impl_import_river_from_shapefile(
        dis_model,
        str(river_shapefile),
        package="RIV",
        stage_field="stage",
        cond_field="conductance",
        depth_field=None,
        stress_periods=[0],
    )
    assert "error" not in result
    assert result["package"] == "RIV"
    assert result["reach_count"] >= 1

    gwf = get_gwf(dis_model)
    assert gwf.get_package("riv") is not None


def test_import_river_unsupported_package_raises(dis_model, river_shapefile):
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    with pytest.raises(ValueError, match="supports RIV, DRN, GHB"):
        _impl_import_river_from_shapefile(
            dis_model, str(river_shapefile), "SFR", None, None, None, None
        )


# ---------------------------------------------------------------------------
# 7f-D1 — stage_raster sampling uses true cell centroids (no x/y swap)
# ---------------------------------------------------------------------------


def test_stage_raster_uses_true_centroids(dis_model_crs, river_mid_shapefile, tmp_path):
    """Per-reach stage must equal the raster value at the reach cell's TRUE
    centroid minus stage_offset. Regression guard for the transposed (y, x)
    sampler that silently queried the wrong coordinate (7f-D1.1)."""
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile
    from groundwater_mcp.utils.model_store import get_gwf

    raster = _ramp_raster_x(tmp_path, "ramp_x.tif", ncol=10, nrow=5, width=1000.0, height=1000.0)

    result = _impl_import_river_from_shapefile(
        dis_model_crs,
        str(river_mid_shapefile),
        package="RIV",
        stage_field=None,
        cond_field=None,
        depth_field=None,
        stress_periods=[0],
        stage_raster=str(raster),
        stage_offset=1.0,
        bed_k=1e-4,
        bed_thickness=1.0,
        channel_width=10.0,
    )
    assert "error" not in result, result
    assert result["stage_source"] == "raster"
    assert result["reaches_no_raster_coverage"] == 0

    gwf = get_gwf(dis_model_crs)
    mg = gwf.modelgrid
    spd = gwf.get_package("riv").stress_period_data.array[0]
    assert len(spd) == 10
    for rec in spd:
        r, c = int(rec["cellid"][1]), int(rec["cellid"][2])
        xc = float(mg.xcellcenters[r, c])
        assert rec["stage"] == pytest.approx(xc - 1.0, abs=1e-6, rel=1e-6)


def test_stage_raster_partial_coverage_errors(dis_model_crs, river_mid_shapefile, tmp_path):
    """More than the default 10% of reaches outside the stage_raster extent must
    fail loudly with the uncovered count, not silently fall back (7f-D1.2)."""
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    raster = _ramp_raster_x(tmp_path, "ramp_half.tif", ncol=4, nrow=5, width=400.0, height=1000.0)

    result = _impl_import_river_from_shapefile(
        dis_model_crs,
        str(river_mid_shapefile),
        package="RIV",
        stage_field=None,
        cond_field=None,
        depth_field=None,
        stress_periods=[0],
        stage_raster=str(raster),
        stage_offset=1.0,
    )
    assert result.get("error") is True
    assert result.get("code") == "STAGE_RASTER_NO_COVERAGE"
    assert "6" in result.get("message", "")  # 6 of 10 reaches uncovered


def test_stage_raster_single_uncovered_reach_succeeds(
    dis_model_crs, river_mid_shapefile, tmp_path
):
    """A single uncovered reach (≤ 10% of reaches) succeeds and reports the count."""
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    raster = _ramp_raster_x(tmp_path, "ramp_880.tif", ncol=9, nrow=5, width=880.0, height=1000.0)

    result = _impl_import_river_from_shapefile(
        dis_model_crs,
        str(river_mid_shapefile),
        package="RIV",
        stage_field=None,
        cond_field=None,
        depth_field=None,
        stress_periods=[0],
        stage_raster=str(raster),
        stage_offset=1.0,
        bed_k=1e-4,
        bed_thickness=1.0,
        channel_width=10.0,
    )
    assert "error" not in result, result
    assert result["reaches_no_raster_coverage"] == 1


def test_stage_raster_custom_tolerance_overrides_default(
    dis_model_crs, river_mid_shapefile, tmp_path
):
    """coverage_tolerance=0.5 turns the 6-uncovered case (60%) into an error."""
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    raster = _ramp_raster_x(tmp_path, "ramp_half.tif", ncol=4, nrow=5, width=400.0, height=1000.0)

    result = _impl_import_river_from_shapefile(
        dis_model_crs,
        str(river_mid_shapefile),
        package="RIV",
        stage_field=None,
        cond_field=None,
        depth_field=None,
        stress_periods=[0],
        stage_raster=str(raster),
        stage_offset=1.0,
        coverage_tolerance=0.9,
        bed_k=1e-4,
        bed_thickness=1.0,
        channel_width=10.0,
    )
    assert "error" not in result, result
    assert result["reaches_no_raster_coverage"] == 6


# ---------------------------------------------------------------------------
# 7f-D2 — river importer CRS reprojection (tag grid with the model's CRS)
# ---------------------------------------------------------------------------


def test_river_reprojected_matches_native(tmp_path, river_utm18_pair):
    """A river in EPSG:4326 against a grid in EPSG:32718 must be reprojected and
    produce the same reach set as the pre-projected shapefile (7f-D2.1)."""
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile
    from groundwater_mcp.utils.model_store import get_gwf

    def _build_utm18(name: str):
        ws = str(tmp_path / name)
        _impl_create_model(name, ws, "METERS", "DAYS")
        _impl_set_simulation(name, 1, [365.0], [12], "moderate")
        _impl_add_dis_package(
            name, nlay=1, nrow=5, ncol=10, delr=200.0, delc=200.0, top=50.0, botm=[30.0]
        )
        get_gwf(name).modelgrid.set_coord_info(xoff=0.0, yoff=0.0, crs="EPSG:32718")
        return name

    native, ll = river_utm18_pair

    m_native = _build_utm18("m_native")
    r1 = _impl_import_river_from_shapefile(
        m_native, str(native), "RIV", None, None, None, [0],
        bed_k=1e-4, bed_thickness=1.0, channel_width=10.0,
    )
    assert "error" not in r1, r1
    native_cells = {
        tuple(r["cellid"]) for r in get_gwf(m_native).get_package("riv").stress_period_data.array[0]
    }

    m_ll = _build_utm18("m_ll")
    r2 = _impl_import_river_from_shapefile(
        m_ll, str(ll), "RIV", None, None, None, [0],
        bed_k=1e-4, bed_thickness=1.0, channel_width=10.0,
    )
    assert "error" not in r2, r2  # must reproject, not silently miss
    ll_cells = {
        tuple(r["cellid"]) for r in get_gwf(m_ll).get_package("riv").stress_period_data.array[0]
    }

    assert len(native_cells) == 8
    assert ll_cells == native_cells


def test_river_import_unknown_model_crs_errors(tmp_path, model_name, river_shapefile):
    """Grid without CRS + shapefile with CRS → CRS_UNKNOWN (7f-D2.2), instead of
    silently sampling in the wrong coordinate space."""
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [365.0], [12], "moderate")
    _impl_add_dis_package(
        model_name, nlay=1, nrow=5, ncol=10, delr=100.0, delc=200.0, top=50.0, botm=[30.0]
    )

    result = _impl_import_river_from_shapefile(
        model_name, str(river_shapefile), "RIV", None, None, None, [0]
    )
    assert result.get("error") is True
    assert result.get("code") == "CRS_UNKNOWN"


def test_river_import_no_intersection_reports_bboxes(dis_model_crs, tmp_path):
    """A disjoint but same-CRS shapefile → NO_INTERSECTION whose message names
    both the grid and shapefile bounding boxes (7f-D2.2)."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    line = LineString([(100000, 100000), (101000, 100000)])
    far = tmp_path / "far.gpkg"
    gpd.GeoDataFrame(geometry=[line], crs="EPSG:32755").to_file(far, driver="GPKG")

    result = _impl_import_river_from_shapefile(
        dis_model_crs, str(far), "RIV", None, None, None, [0]
    )
    assert result.get("error") is True
    assert result.get("code") == "NO_INTERSECTION"
    assert "grid bbox" in result.get("message", "")
    assert "shapefile bbox" in result.get("message", "")


# ---------------------------------------------------------------------------
# import_obs_from_csv
# ---------------------------------------------------------------------------


def test_import_obs_from_csv_with_coords(dis_model, obs_csv):
    from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
    from groundwater_mcp.utils.workspace import resolve_workspace

    result = _impl_import_obs_from_csv(
        dis_model,
        str(obs_csv),
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    assert "error" not in result
    assert result["site_count"] == 3
    assert result["total_records"] == 6

    ws = resolve_workspace(dis_model)
    assert Path(result["summary_file"]).exists()


def test_import_obs_site_cellid_map_has_all_sites(dis_model, obs_csv):
    from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv

    result = _impl_import_obs_from_csv(
        dis_model, str(obs_csv),
        obs_type="HEAD", site_col="site", date_col="date", value_col="value",
        x_col="x", y_col="y", layer=0,
    )
    assert set(result["site_cellid_map"].keys()) == {"BH01", "BH02", "BH03"}


def test_import_obs_missing_column_raises(dis_model, obs_csv):
    from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv

    with pytest.raises(ValueError, match="not found"):
        _impl_import_obs_from_csv(
            dis_model, str(obs_csv),
            obs_type="HEAD", site_col="site", date_col="date", value_col="nonexistent",
            x_col=None, y_col=None, layer=0,
        )
