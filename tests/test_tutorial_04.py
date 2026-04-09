"""Phase 6 Option 1 — Tutorial 04: spatial parameterisation pipeline.

Tests the full workflow using real-world data from Tutorials Modelmuse/04/:
  activeZone.shp  — catchment boundary polygon (EPSG:32718, UTM 18S)
  dem_clipped.tif — DEM clipped to the active zone area (18–129 m elevation)

Fixture copies live in tests/fixtures/tutorial_04/ so CI does not depend on the
original tutorial directory.

Each fixture builds incrementally on the previous, mirroring the pipeline a user
would execute. Individual tests assert that the output of each step is a valid
input to the next (no silent failures at boundaries).

Integration tests that require the MODFLOW 6 binary are skipped when it is not
installed.
"""

from __future__ import annotations

from pathlib import Path

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
)
from groundwater_mcp.tools.postprocess import _impl_read_heads
from groundwater_mcp.tools.runner import _find_mf6_binary, _impl_run_simulation

# ---------------------------------------------------------------------------
# Fixture data paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "tutorial_04"
SHP = str(FIXTURES / "activeZone.shp")
DEM = str(FIXTURES / "dem_clipped.tif")

MODEL = "tut04"
CELL_SIZE = 500.0  # metres — yields a ~7×7 cell grid over the ~3.2×3.3 km zone

# ---------------------------------------------------------------------------
# Skip marker — integration tests require the mf6 binary
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
def tut04_base(tmp_path):
    """Create model workspace and configure steady-state simulation."""
    ws = str(tmp_path / MODEL)
    r = _impl_create_model(MODEL, ws, "METERS", "DAYS")
    assert "error" not in r, f"create_model failed: {r}"
    _impl_set_simulation(MODEL, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    return MODEL


@pytest.fixture()
def tut04_with_grid(tut04_base):
    """Build DIS grid from the activeZone catchment polygon."""
    grid_result = _impl_import_grid_from_shapefile(
        model=tut04_base,
        shapefile=SHP,
        nlay=1,
        layer_surfaces=[],
        method="dis",
        target_crs=None,
        cell_size=CELL_SIZE,
    )
    assert "error" not in grid_result, f"import_grid_from_shapefile failed: {grid_result}"
    return tut04_base, grid_result


@pytest.fixture()
def tut04_with_dem(tut04_with_grid):
    """Assign top elevations from the clipped DEM raster."""
    model, grid_result = tut04_with_grid
    dem_result = _impl_assign_top_from_raster(model, DEM, layer=0, method="mean")
    assert "error" not in dem_result, f"assign_top_from_raster failed: {dem_result}"
    # Validate output is usable by the next step: at least one cell assigned
    assert dem_result["cells_assigned"] > 0
    return model, grid_result, dem_result


@pytest.fixture()
def tut04_runnable(tut04_with_dem):
    """Add NPF, IC, OC, and CHD boundary packages to produce a runnable model.

    CHD boundaries are added along the leftmost and rightmost column for all
    rows (MODFLOW 6 silently skips cells with IDOMAIN < 0).  A simple linear
    head gradient (60 m → 40 m) drives groundwater flow across the aquifer.
    Bottom of the single layer is left at −1 m (the import_grid default);
    the DEM-assigned top ranges ~18–129 m, giving a thick confined aquifer.
    """
    model, grid_result, dem_result = tut04_with_dem
    nrow = grid_result["nrow"]
    ncol = grid_result["ncol"]

    r = _impl_add_npf_package(model, icelltype=0, k=1.0, k33=None, save_flows=True)
    assert "error" not in r

    r = _impl_add_ic_package(model, strt=50.0)
    assert "error" not in r

    r = _impl_add_oc_package(model, None, None, None, None)
    assert "error" not in r

    # CHD along left and right column — simple 60/40 m head gradient
    chd = []
    for row in range(nrow):
        chd.append([[0, row, 0], 60.0])
        chd.append([[0, row, ncol - 1], 40.0])
    r = _impl_add_boundary_package(model, "CHD", {"0": chd}, None)
    assert "error" not in r

    return model, grid_result


@pytest.fixture()
def tut04_ran(tut04_runnable):
    """Run the MODFLOW 6 simulation (requires mf6 binary)."""
    model, grid_result = tut04_runnable
    run_result = _impl_run_simulation(model, silent=True)
    return model, grid_result, run_result


# ---------------------------------------------------------------------------
# Test: import_grid_from_shapefile
# ---------------------------------------------------------------------------


def test_grid_cell_count_positive(tut04_with_grid):
    _, grid = tut04_with_grid
    assert grid["ncells"] > 0, "Grid must contain at least one cell"
    assert grid["nrow"] > 0
    assert grid["ncol"] > 0


def test_grid_type_is_dis(tut04_with_grid):
    _, grid = tut04_with_grid
    assert grid["grid_type"] == "DIS"


def test_grid_crs_is_epsg32718(tut04_with_grid):
    _, grid = tut04_with_grid
    # CRS string should reference the UTM 18S zone from the shapefile
    assert "32718" in (grid["crs"] or ""), f"Expected EPSG:32718, got: {grid['crs']}"


def test_grid_dimensions_match_cell_size(tut04_with_grid):
    _, grid = tut04_with_grid
    # activeZone spans ~3 200 m × 3 300 m → expect 6–8 cols and rows at 500 m
    assert 5 <= grid["ncol"] <= 10, f"Unexpected ncol: {grid['ncol']}"
    assert 5 <= grid["nrow"] <= 10, f"Unexpected nrow: {grid['nrow']}"


# ---------------------------------------------------------------------------
# Test: assign_top_from_raster
# ---------------------------------------------------------------------------


def test_raster_elevation_range_plausible(tut04_with_dem):
    _, _, dem = tut04_with_dem
    # DEM elevations in the active zone are 18–129 m
    assert dem["min"] >= 1.0, f"Min elevation implausibly low: {dem['min']}"
    assert dem["max"] <= 300.0, f"Max elevation implausibly high: {dem['max']}"


def test_raster_cells_assigned_matches_grid(tut04_with_dem):
    _, grid, dem = tut04_with_dem
    # Every cell in the grid (including inactive) is assigned a DEM value
    assert dem["cells_assigned"] == grid["nrow"] * grid["ncol"]


def test_raster_mean_elevation_in_range(tut04_with_dem):
    _, _, dem = tut04_with_dem
    # Mean elevation for this sub-catchment (~60 m) must be between min and max
    assert dem["min"] <= dem["mean"] <= dem["max"]


# ---------------------------------------------------------------------------
# Test: run_simulation
# ---------------------------------------------------------------------------


@requires_mf6
def test_run_simulation_succeeds(tut04_ran):
    _, _, run = tut04_ran
    assert run["success"] is True, f"Simulation failed: {run.get('listing_summary', '')}"


@requires_mf6
def test_run_simulation_converged(tut04_ran):
    _, _, run = tut04_ran
    assert run["convergence"] == "converged"


@requires_mf6
def test_hds_file_exists(tut04_ran):
    model, _, _ = tut04_ran
    from groundwater_mcp.utils.workspace import resolve_workspace
    ws = resolve_workspace(model)
    hds_files = list(ws.glob("*.hds"))
    assert len(hds_files) > 0, f"No .hds file in {ws}"
    assert hds_files[0].stat().st_size > 0, ".hds file is empty"


@requires_mf6
def test_budget_file_exists(tut04_ran):
    model, _, _ = tut04_ran
    from groundwater_mcp.utils.workspace import resolve_workspace
    ws = resolve_workspace(model)
    assert len(list(ws.glob("*.cbb"))) > 0, "No .cbb budget file produced"


# ---------------------------------------------------------------------------
# Test: read_heads
# ---------------------------------------------------------------------------


@requires_mf6
def test_read_heads_shape_matches_grid(tut04_ran):
    model, grid, _ = tut04_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result, f"read_heads failed: {result}"
    shape = result["shape"]  # [nrow, ncol]
    assert shape[0] == grid["nrow"], f"nrow mismatch: {shape[0]} vs {grid['nrow']}"
    assert shape[1] == grid["ncol"], f"ncol mismatch: {shape[1]} vs {grid['ncol']}"


@requires_mf6
def test_read_heads_no_dry_active_cells(tut04_ran):
    """All active cells should have a finite head value (no dry cells in confined mode)."""
    model, _, _ = tut04_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result
    # _array_stats returns None only if every cell is the 1e30 sentinel (all dry)
    assert result["min"] is not None, "All cells are dry — simulation did not produce valid heads"


@requires_mf6
def test_read_heads_values_within_chd_range(tut04_ran):
    """Interior heads must lie between the two CHD boundary values (40–60 m)."""
    model, _, _ = tut04_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result
    # Allow a small tolerance around the CHD heads (40 / 60 m)
    assert result["min"] >= 35.0, f"Head below lower CHD boundary: {result['min']}"
    assert result["max"] <= 65.0, f"Head above upper CHD boundary: {result['max']}"


@requires_mf6
def test_read_heads_kstpkper_matches_simulation(tut04_ran):
    """kstpkper returned by read_heads must correspond to the single stress period run."""
    model, _, _ = tut04_ran
    result = _impl_read_heads(model, kstpkper=None, layer=0)
    assert "error" not in result
    # 1 period, 1 time step → kstpkper = [0, 0] (0-indexed in FloPy)
    assert result["kstpkper"] == [0, 0], f"Unexpected kstpkper: {result['kstpkper']}"
