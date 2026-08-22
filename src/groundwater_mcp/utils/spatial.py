"""spatial.py — shared helpers for raster sampling and vector/grid intersection.

Used by tools/parameterise.py. Requires geopandas and rasterio.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class CRSError(ValueError):
    """Raised when the model CRS is unknown but the spatial data declares one.

    The caller must not guess the coordinate space: sampling in the wrong CRS
    returns plausible-looking numbers that are silently wrong.
    """


# ---------------------------------------------------------------------------
# Raster sampling
# ---------------------------------------------------------------------------


def _bilinear_sample(
    band: np.ndarray, transform, x: np.ndarray, y: np.ndarray, nodata
) -> np.ndarray:
    """Bilinear interpolation of *band* at (x, y) (rasterio 1.5 lacks a
    resampling argument on ``sample_gen``, so this is computed directly).

    Continuous pixel indices use the rasterio convention: pixel *i*'s centre
    is at integer ``i + 0.5``, so the interpolation anchors are the pixel
    centres. Points outside the band or on nodata pixels return NaN.
    """
    rows, cols = band.shape
    col_f = (np.asarray(x, dtype=float) - transform.c) / transform.a - 0.5
    row_f = (np.asarray(y, dtype=float) - transform.f) / transform.e - 0.5
    col0 = np.floor(col_f).astype(int)
    row0 = np.floor(row_f).astype(int)
    fx = col_f - col0
    fy = row_f - row0

    out = np.full(len(x), np.nan, dtype=float)
    valid = (col0 >= 0) & (col0 + 1 < cols) & (row0 >= 0) & (row0 + 1 < rows)
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return out
    c0, r0 = col0[idx], row0[idx]
    band_f = band.astype(float)
    v00 = band_f[r0, c0]
    v10 = band_f[r0, c0 + 1]
    v01 = band_f[r0 + 1, c0]
    v11 = band_f[r0 + 1, c0 + 1]
    top = v00 * (1 - fx[idx]) + v10 * fx[idx]
    bot = v01 * (1 - fx[idx]) + v11 * fx[idx]
    out[idx] = top * (1 - fy[idx]) + bot * fy[idx]
    if nodata is not None:
        out[out == nodata] = np.nan
    return out


def sample_raster_at_points(
    raster_path: str | Path,
    x: np.ndarray,
    y: np.ndarray,
    src_crs: str | None = None,
    resampling: str = "nearest",
) -> np.ndarray:
    """Sample a GeoTIFF raster at (x, y) coordinates.

    Parameters
    ----------
    raster_path:
        Path to a GeoTIFF file.
    x, y:
        1-D arrays of coordinate pairs (same CRS as ``src_crs``).
    src_crs:
        CRS of the input coordinates as a proj string, EPSG code, or WKT.
        If None, assumed to match the raster CRS.
    resampling:
        ``"nearest"`` (default) or ``"bilinear"`` (7e-B5).

    Returns
    -------
    np.ndarray
        1-D array of sampled values (float32). Points outside the raster
        extent are returned as NaN.
    """
    import rasterio
    from rasterio.crs import CRS

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    with rasterio.open(raster_path) as src:
        raster_crs = src.crs

        # Reproject coordinates if CRS mismatch
        if src_crs is not None:
            from pyproj import Transformer

            in_crs = CRS.from_user_input(src_crs)
            if not in_crs.equals(raster_crs):
                transformer = Transformer.from_crs(in_crs, raster_crs, always_xy=True)
                x, y = transformer.transform(x, y)

        if resampling == "bilinear":
            sampled = _bilinear_sample(src.read(1), src.transform, x, y, src.nodata)
        else:
            coords = list(zip(x.tolist(), y.tolist()))
            sampled = np.array(
                list(src.sample(coords, indexes=1)), dtype=float
            ).ravel()
            # Replace nodata with NaN
            if src.nodata is not None:
                sampled[sampled == src.nodata] = np.nan

        # Explicitly mask out-of-bounds points. rasterio returns the nodata
        # value when one is set, but 0.0 when it is not — a plausible-looking
        # wrong value that would silently corrupt stage/elevation sampling
        # (7f-D1.2). Anything outside the raster bounds is NaN.
        b = src.bounds
        tol = 1e-9
        inside = (
            (x >= b.left - tol)
            & (x <= b.right + tol)
            & (y >= b.bottom - tol)
            & (y <= b.top + tol)
        )
        sampled[~inside] = np.nan

    return sampled


# ---------------------------------------------------------------------------
# Polygon–point intersection
# ---------------------------------------------------------------------------


def intersect_points_with_polygons(
    x: np.ndarray,
    y: np.ndarray,
    gdf,  # geopandas.GeoDataFrame
    value_columns: list[str],
    points_crs: str | None = None,
) -> dict[str, np.ndarray]:
    """Return per-point values from a polygon GeoDataFrame via spatial join.

    Parameters
    ----------
    x, y:
        1-D coordinate arrays.
    gdf:
        GeoDataFrame of polygons. Must have the requested ``value_columns``.
    value_columns:
        Columns in ``gdf`` to extract for each point.
    points_crs:
        CRS of the input points. If None, assumed to match ``gdf.crs``.

    Returns
    -------
    dict[str, np.ndarray]
        One array per value column. Points outside all polygons have NaN.
    """
    import geopandas as gpd

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    pts_gdf = gpd.GeoDataFrame(
        {"_idx": np.arange(len(x))},
        geometry=gpd.GeoSeries.from_xy(x, y),
        crs=points_crs or gdf.crs,
    )

    if pts_gdf.crs != gdf.crs:
        pts_gdf = pts_gdf.to_crs(gdf.crs)

    joined = gpd.sjoin(pts_gdf, gdf[["geometry"] + value_columns], how="left", predicate="within")

    # If a point falls in multiple polygons, keep the first match only
    joined = joined[~joined["_idx"].duplicated(keep="first")]
    # Re-index to original order
    joined = joined.set_index("_idx").reindex(np.arange(len(x)))

    return {col: joined[col].to_numpy(dtype=float, na_value=np.nan) for col in value_columns}


# ---------------------------------------------------------------------------
# Grid centroid extraction
# ---------------------------------------------------------------------------


def grid_centroids(modelgrid) -> tuple[np.ndarray, np.ndarray]:
    """Return flattened (x, y) cell-centroid arrays from a FloPy modelgrid.

    Works for both DIS (structured) and DISV (unstructured) grids.
    """
    xc = np.asarray(modelgrid.xcellcenters).ravel()
    yc = np.asarray(modelgrid.ycellcenters).ravel()
    return xc, yc


# ---------------------------------------------------------------------------
# DIS grid geometry from shapefile
# ---------------------------------------------------------------------------


def dis_grid_props_from_shapefile(
    shapefile: str | Path,
    cell_size: float,
    target_crs: str | None = None,
) -> dict:
    """Compute DIS grid parameters from a catchment boundary shapefile.

    Returns a dict with keys: nrow, ncol, delr, delc, xoff, yoff, crs,
    idomain (numpy array shape nrow x ncol, 1 inside / -1 outside polygon).
    """
    import geopandas as gpd

    gdf = gpd.read_file(shapefile)
    if target_crs:
        gdf = gdf.to_crs(target_crs)

    polygon = gdf.geometry.unary_union
    xmin, ymin, xmax, ymax = polygon.bounds

    ncol = max(1, int(np.ceil((xmax - xmin) / cell_size)))
    nrow = max(1, int(np.ceil((ymax - ymin) / cell_size)))
    delr = (xmax - xmin) / ncol
    delc = (ymax - ymin) / nrow

    # Cell centroids: row 0 is at the top (highest y)
    xc = xmin + (np.arange(ncol) + 0.5) * delr
    yc = ymax - (np.arange(nrow) + 0.5) * delc

    # Containment check
    pts_x = np.tile(xc, nrow)
    pts_y = np.repeat(yc, ncol)
    pts_gdf = gpd.GeoSeries.from_xy(pts_x, pts_y, crs=gdf.crs)
    within = pts_gdf.within(polygon).to_numpy()
    idomain = np.where(within.reshape(nrow, ncol), 1, -1)

    return {
        "nrow": nrow,
        "ncol": ncol,
        "delr": delr,
        "delc": delc,
        "xoff": xmin,
        "yoff": ymin,
        "crs": str(gdf.crs) if gdf.crs else None,
        "idomain": idomain,
        "polygon": polygon,
    }


# ---------------------------------------------------------------------------
# DISV Voronoi grid from shapefile
# ---------------------------------------------------------------------------


def disv_grid_props_from_shapefile(
    shapefile: str | Path,
    cell_size: float,
    target_crs: str | None = None,
) -> dict:
    """Build a Voronoi DISV grid from a catchment polygon shapefile.

    Generates seed points on a regular grid inside the polygon, then creates
    a Voronoi tessellation. Returns a dict compatible with ``add_disv_package``.

    Keys: ncpl, nvert, vertices (list), cell2d (list), crs.
    """
    import geopandas as gpd
    from flopy.utils.voronoi import VoronoiGrid

    gdf = gpd.read_file(shapefile)
    if target_crs:
        gdf = gdf.to_crs(target_crs)

    polygon = gdf.geometry.unary_union
    xmin, ymin, xmax, ymax = polygon.bounds

    # Seed points on regular grid, filtered to polygon interior
    xs = np.arange(xmin + cell_size / 2, xmax, cell_size)
    ys = np.arange(ymin + cell_size / 2, ymax, cell_size)
    xx, yy = np.meshgrid(xs, ys)
    pts_all = np.column_stack([xx.ravel(), yy.ravel()])

    # Vectorised containment using geopandas
    pts_gs = gpd.GeoSeries.from_xy(pts_all[:, 0], pts_all[:, 1], crs=gdf.crs)
    mask = pts_gs.within(polygon).to_numpy()
    pts_inside = pts_all[mask]

    if len(pts_inside) < 3:
        raise ValueError(
            f"Only {len(pts_inside)} seed points inside polygon with cell_size={cell_size}. "
            "Reduce cell_size or check the shapefile."
        )

    vor = VoronoiGrid(pts_inside)
    gridprops = vor.get_disv_gridprops()

    return {
        "ncpl": gridprops["ncpl"],
        "nvert": gridprops["nvert"],
        "vertices": gridprops["vertices"],
        "cell2d": gridprops["cell2d"],
        "crs": str(gdf.crs) if gdf.crs else None,
        "xoff": xmin,
        "yoff": ymin,
    }


# ---------------------------------------------------------------------------
# River/line intersection with DIS grid
# ---------------------------------------------------------------------------


def intersect_lines_with_dis_grid(
    shapefile: str | Path,
    modelgrid,
    attribute_columns: list[str],
) -> list[dict]:
    """Intersect a river/drain polyline shapefile with a structured DIS grid.

    For each intersecting cell, returns the cell ID (layer 0), intersection
    length, and any requested attribute values from the shapefile.

    The grid's own CRS (``modelgrid.crs``) is authoritative: the line is
    reprojected into it when the two differ. When the grid has no CRS but the
    shapefile declares one, :class:`CRSError` is raised — the caller must not
    guess the coordinate space (7f-D2).

    Returns a list of dicts with keys: cellid, length_m, and one key per
    attribute column.
    """
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.read_file(shapefile)

    # Build a GeoDataFrame of model grid cells
    nrow = modelgrid.nrow
    ncol = modelgrid.ncol
    xv, yv = modelgrid.xvertices, modelgrid.yvertices  # shape (nrow+1, ncol+1)

    model_crs = modelgrid.crs
    if model_crs is None and gdf.crs is not None:
        raise CRSError(
            "The model grid has no CRS but the river shapefile declares "
            f"'{gdf.crs}'. Set a CRS on the model grid first "
            "(e.g. import_grid_from_shapefile with target_crs) so coordinates "
            "are compared in a known space — silently assuming a match can "
            "corrupt the river boundary."
        )

    cells = []
    for r in range(nrow):
        for c in range(ncol):
            cell_box = box(
                float(xv[r, c]),
                float(yv[r + 1, c + 1]),
                float(xv[r + 1, c + 1]),
                float(yv[r, c]),
            )
            cells.append({"row": r, "col": c, "geometry": cell_box})

    grid_gdf = gpd.GeoDataFrame(cells, crs=model_crs if model_crs else None)

    # Reproject lines into the grid's CRS if needed
    if gdf.crs and grid_gdf.crs and not gdf.crs.equals(grid_gdf.crs):
        gdf = gdf.to_crs(grid_gdf.crs)

    # Intersection
    intersected = gpd.overlay(gdf, grid_gdf, how="intersection", keep_geom_type=False)

    results = []
    for _, row_ in intersected.iterrows():
        geom = row_.geometry
        length = geom.length if geom else 0.0
        if length == 0.0:
            continue
        result = {
            "cellid": (0, int(row_["row"]), int(row_["col"])),
            "length_m": float(length),
        }
        for col in attribute_columns:
            result[col] = row_.get(col, np.nan)
        results.append(result)

    return results
