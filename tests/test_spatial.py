"""Tests for utils/spatial.py — raster sampling and vector/grid intersection."""

from __future__ import annotations

import numpy as np
import pytest

from groundwater_mcp.utils.spatial import sample_raster_at_points


@pytest.fixture()
def ramp_raster(tmp_path):
    """10×5 GeoTIFF over [0, 1000]×[0, 1000]; value = pixel-centre x."""
    import rasterio
    from rasterio.transform import from_bounds

    ncol, nrow = 10, 5
    xc = (np.arange(ncol) + 0.5) * (1000.0 / ncol)
    data = np.tile(xc, (nrow, 1)).astype(np.float64)
    path = tmp_path / "ramp.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=nrow, width=ncol, count=1,
        dtype="float64", crs="EPSG:32755",
        transform=from_bounds(0, 0, 1000, 1000, ncol, nrow),
    ) as dst:
        dst.write(data, 1)
    return path


def test_sample_inside_extent(ramp_raster):
    vals = sample_raster_at_points(ramp_raster, np.array([250.0]), np.array([500.0]))
    assert vals[0] == pytest.approx(250.0)


def test_sample_out_of_bounds_returns_nan(ramp_raster):
    """Points outside the raster extent must be NaN even when the raster has NO
    nodata set — rasterio otherwise returns 0.0, a plausible-looking wrong value
    that the stage_raster coverage check depends on (7f-D1.2)."""
    vals = sample_raster_at_points(
        ramp_raster, np.array([1500.0, 250.0]), np.array([500.0, 500.0])
    )
    assert np.isnan(vals[0])
    assert vals[1] == pytest.approx(250.0)


def test_sample_transposed_coordinates_differ(ramp_raster):
    """The (y, x) swap must not be accidentally equal on a non-square raster —
    guards the stage_raster regression test's discriminative power."""
    a = sample_raster_at_points(ramp_raster, np.array([250.0]), np.array([500.0]))
    b = sample_raster_at_points(ramp_raster, np.array([500.0]), np.array([250.0]))
    assert a[0] != pytest.approx(b[0])
