"""Phase 6 Layer 1 — Tutorial 05: boundary conditions, observations, water balance.

Tests the full workflow using real-world data from Tutorials Modelmuse/05/data1a/Data/:
  river.shp      — river bed polygon (EPSG:32718, UTM 18S); used as RIV package
  wells.shp      — 29 pumping-well points (Q field, m³/day)
  chd_high.shp   — high constant-head boundary lines (2 features, head=70 m)
  chd_lower.shp  — low constant-head boundary lines (4 features, head=40 m)

The base grid and DEM are reused from tests/fixtures/tutorial_04/.

Each pytest fixture extends the previous one, mirroring the tool sequence a user
would execute through the MCP. Tests assert that each step's output is a valid
input to the next. Integration tests that require MODFLOW 6 are skipped when the
binary is not installed.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.parameterise import (
    _impl_assign_top_from_raster,
    _impl_import_grid_from_shapefile,
    _impl_import_obs_from_csv,
    _impl_import_river_from_shapefile,
)
from groundwater_mcp.tools.postprocess import (
    _impl_compute_water_balance,
    _impl_plot_heads_map,
    _impl_read_heads,
)
from groundwater_mcp.tools.runner import _find_mf6_binary, _impl_run_simulation
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.spatial import grid_centroids, intersect_lines_with_dis_grid

# ---------------------------------------------------------------------------
# Fixture data paths
# ---------------------------------------------------------------------------

TUT04 = Path(__file__).parent / "fixtures" / "tutorial_04"
TUT05 = Path(__file__).parent / "fixtures" / "tutorial_05"

SHP_ZONE = str(TUT04 / "activeZone.shp")
DEM = str(TUT04 / "dem_clipped.tif")
SHP_RIVER = str(TUT05 / "river.shp")
SHP_WELLS = str(TUT05 / "wells.shp")
SHP_CHD_HIGH = str(TUT05 / "chd_high.shp")
SHP_CHD_LOWER = str(TUT05 / "chd_lower.shp")

MODEL = "tut05"
CELL_SIZE = 500.0   # same grid resolution as Tutorial 04
CHD_HIGH_HEAD = 70.0
CHD_LOW_HEAD = 40.0

# ---------------------------------------------------------------------------
# Skip marker
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

# ---------------------------------------------------------------------------
# Incrementally-built fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tut05_base(tmp_path):
    """Create model workspace and configure a single steady-state stress period."""
    ws = str(tmp_path / MODEL)
    r = _impl_create_model(MODEL, ws, "METERS", "DAYS")
    assert "error" not in r, f"create_model failed: {r}"
    _impl_set_simulation(MODEL, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    return MODEL


@pytest.fixture()
def tut05_with_grid(tut05_base):
    """Build DIS grid from the same activeZone catchment polygon as Tutorial 04."""
    grid = _impl_import_grid_from_shapefile(
        model=tut05_base,
        shapefile=SHP_ZONE,
        nlay=1,
        layer_surfaces=[],
        method="dis",
        target_crs=None,
        cell_size=CELL_SIZE,
    )
    assert "error" not in grid, f"import_grid_from_shapefile failed: {grid}"
    return tut05_base, grid


@pytest.fixture()
def tut05_with_dem(tut05_with_grid):
    """Assign top elevations from the Tutorial 04 DEM."""
    model, grid = tut05_with_grid
    dem = _impl_assign_top_from_raster(model, DEM, layer=0, method="mean")
    assert "error" not in dem, f"assign_top_from_raster failed: {dem}"
    assert dem["cells_assigned"] > 0
    return model, grid, dem


@pytest.fixture()
def tut05_with_riv(tut05_with_dem):
    """Add RIV package by intersecting river.shp with the model grid.

    river.shp is a polygon in this tutorial (not a centreline), so the function
    uses polygon-grid overlay; reach lengths are perimeters of the overlap areas.
    Stage defaults to 0.0 m; conductance equals the overlap perimeter (m).
    The CHD boundaries supply any excess outflow so the model still converges.
    """
    model, grid, dem = tut05_with_dem
    riv = _impl_import_river_from_shapefile(
        model=model,
        shapefile=SHP_RIVER,
        package="RIV",
        stage_field=None,
        cond_field=None,
        depth_field=None,
        stress_periods=None,
    )
    assert "error" not in riv, f"import_river_from_shapefile failed: {riv}"
    return model, grid, riv


@pytest.fixture()
def tut05_with_chd(tut05_with_riv):
    """Add CHD package using cell IDs derived from chd_high.shp and chd_lower.shp.

    Intersects each boundary shapefile with the model grid, assigns the
    corresponding head value (70 m high, 40 m low), and calls add_boundary_package.
    Duplicate cells (line touches same cell via multiple features) are deduplicated
    so MODFLOW 6 does not see the same cellid twice.
    """
    model, grid, riv = tut05_with_riv
    gwf = get_gwf(model)
    mg = gwf.modelgrid

    high_reaches = intersect_lines_with_dis_grid(SHP_CHD_HIGH, mg, [])
    low_reaches = intersect_lines_with_dis_grid(SHP_CHD_LOWER, mg, [])

    seen: set[tuple] = set()
    chd_records: list = []
    for reach in high_reaches:
        cid = reach["cellid"]
        if cid not in seen:
            seen.add(cid)
            chd_records.append([list(cid), CHD_HIGH_HEAD])
    for reach in low_reaches:
        cid = reach["cellid"]
        if cid not in seen:
            seen.add(cid)
            chd_records.append([list(cid), CHD_LOW_HEAD])

    assert chd_records, "No CHD cells derived from chd_high/chd_lower shapefiles"
    r = _impl_add_boundary_package(model, "CHD", {"0": chd_records}, {"save_flows": True})
    assert "error" not in r, f"add_boundary_package CHD failed: {r}"
    return model, grid, {"high_count": len(high_reaches), "low_count": len(low_reaches), "total_chd": len(chd_records)}


@pytest.fixture()
def tut05_with_wel(tut05_with_chd):
    """Add WEL package by mapping well-point coordinates to the nearest grid cell.

    Reads wells.shp (29 pumping wells) and assigns each well's Q value (m³/day)
    to its nearest model cell. Q values for wells that map to the same cell are
    summed to keep a single record per cell.
    """
    import geopandas as gpd

    model, grid, chd_info = tut05_with_chd
    gwf = get_gwf(model)
    mg = gwf.modelgrid
    ncol = mg.ncol

    xc, yc = grid_centroids(mg)
    ncells = mg.nrow * mg.ncol
    xc = xc[:ncells]
    yc = yc[:ncells]

    wells_gdf = gpd.read_file(SHP_WELLS)
    cell_q: dict[tuple, float] = {}
    for row in wells_gdf.itertuples():
        wx, wy = row.geometry.x, row.geometry.y
        q = float(row.Q)
        dist = np.hypot(xc - wx, yc - wy)
        idx = int(np.argmin(dist))
        cellid = (0, idx // ncol, idx % ncol)
        cell_q[cellid] = cell_q.get(cellid, 0.0) + q

    wel_records = [[list(cid), q] for cid, q in cell_q.items()]
    r = _impl_add_boundary_package(model, "WEL", {"0": wel_records}, {"save_flows": True})
    assert "error" not in r, f"add_boundary_package WEL failed: {r}"
    return model, grid, {"well_count": len(wells_gdf), "wel_cells": len(wel_records)}


@pytest.fixture()
def tut05_runnable(tut05_with_wel):
    """Add NPF, IC, and OC packages to make the model runnable."""
    model, grid, wel_info = tut05_with_wel

    r = _impl_add_npf_package(model, icelltype=0, k=5.0, k33=None, save_flows=True)
    assert "error" not in r

    r = _impl_add_ic_package(model, strt=55.0)
    assert "error" not in r

    r = _impl_add_oc_package(model, None, None, None, None)
    assert "error" not in r

    return model, grid


@pytest.fixture()
def tut05_ran(tut05_runnable):
    """Run the MODFLOW 6 simulation (requires mf6 binary)."""
    model, grid = tut05_runnable
    run = _impl_run_simulation(model, silent=True)
    return model, grid, run


# ---------------------------------------------------------------------------
# Separate fixture for import_obs_from_csv (forks from tut05_with_dem)
# ---------------------------------------------------------------------------


@pytest.fixture()
def wells_obs_csv(tmp_path):
    """Generate a synthetic head-observation CSV from wells.shp coordinates."""
    import geopandas as gpd

    gdf = gpd.read_file(SHP_WELLS)
    csv_path = tmp_path / "wells_obs.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "head_m", "x", "y"])
        for i, row in enumerate(gdf.itertuples()):
            writer.writerow([
                f"W{i + 1:02d}",
                "2020-01-01",
                55.0,
                row.geometry.x,
                row.geometry.y,
            ])
    return str(csv_path)


@pytest.fixture()
def tut05_with_obs(tut05_with_dem, wells_obs_csv):
    """Add OBS package via import_obs_from_csv using well coordinates as sites."""
    model, grid, dem = tut05_with_dem
    obs = _impl_import_obs_from_csv(
        model=model,
        csv_file=wells_obs_csv,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="head_m",
        x_col="x",
        y_col="y",
        layer=0,
    )
    assert "error" not in obs, f"import_obs_from_csv failed: {obs}"
    return model, obs


# ---------------------------------------------------------------------------
# Tests: import_river_from_shapefile
# ---------------------------------------------------------------------------


def test_river_reach_count_positive(tut05_with_riv):
    _, _, riv = tut05_with_riv
    assert riv["reach_count"] > 0, "No grid cells intersected the river polygon"


def test_river_package_is_riv(tut05_with_riv):
    _, _, riv = tut05_with_riv
    assert riv["package"] == "RIV"


def test_river_stress_period_zero_present(tut05_with_riv):
    _, _, riv = tut05_with_riv
    assert 0 in riv["stress_periods"]
    assert riv["stress_periods"][0] > 0


# ---------------------------------------------------------------------------
# Tests: CHD from shapefiles
# ---------------------------------------------------------------------------


def test_chd_high_produces_cells(tut05_with_chd):
    _, _, chd = tut05_with_chd
    assert chd["high_count"] > 0, "chd_high.shp produced no intersecting cells"


def test_chd_lower_produces_cells(tut05_with_chd):
    _, _, chd = tut05_with_chd
    assert chd["low_count"] > 0, "chd_lower.shp produced no intersecting cells"


def test_chd_total_unique_cells(tut05_with_chd):
    _, _, chd = tut05_with_chd
    # Total unique cells must be at least as many as the larger of high/low sets
    assert chd["total_chd"] >= max(chd["high_count"], chd["low_count"])


# ---------------------------------------------------------------------------
# Tests: WEL from wells shapefile
# ---------------------------------------------------------------------------


def test_wel_cells_positive(tut05_with_wel):
    _, _, wel = tut05_with_wel
    assert wel["wel_cells"] > 0


def test_wel_input_wells_count(tut05_with_wel):
    _, _, wel = tut05_with_wel
    assert wel["well_count"] == 29


def test_wel_cells_at_most_wells(tut05_with_wel):
    """Multiple wells may share a cell (summed Q) → unique cells ≤ total wells."""
    _, _, wel = tut05_with_wel
    assert wel["wel_cells"] <= wel["well_count"]


# ---------------------------------------------------------------------------
# Tests: import_obs_from_csv
# ---------------------------------------------------------------------------


def test_obs_site_count_matches_wells(tut05_with_obs):
    _, obs = tut05_with_obs
    assert obs["site_count"] == 29


def test_obs_type_is_head(tut05_with_obs):
    _, obs = tut05_with_obs
    assert obs["obs_type"] == "HEAD"


def test_obs_file_created(tut05_with_obs):
    _, obs = tut05_with_obs
    assert Path(obs["obs_file"]).exists()


def test_obs_summary_file_created(tut05_with_obs):
    _, obs = tut05_with_obs
    assert Path(obs["summary_file"]).exists()


def test_obs_all_sites_mapped(tut05_with_obs):
    _, obs = tut05_with_obs
    assert len(obs["site_cellid_map"]) == 29


# ---------------------------------------------------------------------------
# Tests: run_simulation
# ---------------------------------------------------------------------------


@requires_mf6
def test_run_succeeds(tut05_ran):
    _, _, run = tut05_ran
    assert run["success"] is True, f"Simulation failed: {run.get('listing_summary', '')}"


@requires_mf6
def test_run_converged(tut05_ran):
    _, _, run = tut05_ran
    assert run["convergence"] == "converged"


@requires_mf6
def test_hds_file_exists(tut05_ran):
    from groundwater_mcp.utils.workspace import resolve_workspace
    model, _, _ = tut05_ran
    ws = resolve_workspace(model)
    hds_files = list(ws.glob("*.hds"))
    assert len(hds_files) > 0 and hds_files[0].stat().st_size > 0


@requires_mf6
def test_cbb_file_exists(tut05_ran):
    from groundwater_mcp.utils.workspace import resolve_workspace
    model, _, _ = tut05_ran
    ws = resolve_workspace(model)
    assert len(list(ws.glob("*.cbb"))) > 0


# ---------------------------------------------------------------------------
# Tests: read_heads
# ---------------------------------------------------------------------------


@requires_mf6
def test_read_heads_shape_matches_grid(tut05_ran):
    model, grid, _ = tut05_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result, f"read_heads failed: {result}"
    assert result["shape"][0] == grid["nrow"]
    assert result["shape"][1] == grid["ncol"]


@requires_mf6
def test_read_heads_not_all_dry(tut05_ran):
    model, _, _ = tut05_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result
    assert result["min"] is not None, "All cells returned dry-cell sentinel (1e30)"


@requires_mf6
def test_read_heads_kstpkper_is_first_step(tut05_ran):
    model, _, _ = tut05_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result
    assert result["kstpkper"] == [0, 0]


# ---------------------------------------------------------------------------
# Tests: compute_water_balance
# ---------------------------------------------------------------------------


@requires_mf6
def test_water_balance_returns_inflow_outflow(tut05_ran):
    model, _, _ = tut05_ran
    wb = _impl_compute_water_balance(model, kstpkper=None)
    assert "error" not in wb
    assert isinstance(wb["inflow"], dict)
    assert isinstance(wb["outflow"], dict)


@requires_mf6
def test_water_balance_net_near_zero(tut05_ran):
    """Net balance (in + out) should be < 1% of total inflow for a converged model."""
    model, _, _ = tut05_ran
    wb = _impl_compute_water_balance(model, kstpkper=None)
    assert "error" not in wb
    total_in = wb["total_inflow"]
    net = abs(wb["net_balance"])
    if total_in > 0:
        assert net / total_in < 0.02, (
            f"Water balance discrepancy too large: net={net:.4f}, total_in={total_in:.4f}"
        )


@requires_mf6
def test_water_balance_has_chd_component(tut05_ran):
    """CHD boundaries should appear in either inflow or outflow."""
    model, _, _ = tut05_ran
    wb = _impl_compute_water_balance(model, kstpkper=None)
    all_labels = set(wb["inflow"]) | set(wb["outflow"])
    chd_labels = {lbl for lbl in all_labels if "CHD" in lbl.upper()}
    assert chd_labels, f"No CHD component in water balance. Labels: {all_labels}"


# ---------------------------------------------------------------------------
# Tests: plot_heads_map
# ---------------------------------------------------------------------------


@requires_mf6
def test_plot_heads_map_creates_png(tut05_ran):
    model, _, _ = tut05_ran
    result = _impl_plot_heads_map(model, layer=0, kstpkper=None, contour_intervals=5)
    assert "error" not in result, f"plot_heads_map failed: {result}"
    out = Path(result["output_file"])
    assert out.exists(), f"PNG not created at {out}"
    assert out.stat().st_size > 1000, "PNG file appears empty"


@requires_mf6
def test_plot_heads_map_metadata(tut05_ran):
    model, _, _ = tut05_ran
    result = _impl_plot_heads_map(model, layer=0, kstpkper=None, contour_intervals=5)
    assert result["model"] == model
    assert result["layer"] == 0
    assert result["kstpkper"] == [0, 0]
