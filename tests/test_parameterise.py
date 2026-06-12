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
    """A model with TDIS, IMS, a 10×10 DIS grid over a 1 km catchment, and NPF/IC."""
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_create_model,
        _impl_set_simulation,
    )

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
    return model_name


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
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    _impl_import_grid_from_shapefile(
        model_name, str(catchment_shapefile), 1, [], "dis", None, 200.0
    )
    model_ws = resolve_workspace(model_name)
    assert (model_ws / f"{model_name}.dis").exists()


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
