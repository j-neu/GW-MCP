"""spatial.py — shared helpers for raster sampling and vector/grid intersection.

Used by tools/parameterise.py. Requires geopandas and rasterio.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Raster sampling
# ---------------------------------------------------------------------------


def sample_raster_at_points(
    raster_path: str | Path,
    x: np.ndarray,
    y: np.ndarray,
    src_crs: str | None = None,
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

        coords = list(zip(x.tolist(), y.tolist()))
        sampled = np.array(list(src.sample(coords, indexes=1)), dtype=float).ravel()

        # Replace nodata with NaN
        nodata = src.nodata
        if nodata is not None:
            sampled[sampled == nodata] = np.nan

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
    from shapely.geometry import Point

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
    from shapely.geometry import Point

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

    Returns a list of dicts with keys: cellid, length_m, and one key per
    attribute column.
    """
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.read_file(shapefile)

    # Build a GeoDataFrame of model grid cells
    nrow = modelgrid.nrow
    ncol = modelgrid.ncol
    xyzv = modelgrid.xyzvertices  # ((nrow+1, ncol+1) arrays for x and y)
    xv, yv = modelgrid.xvertices, modelgrid.yvertices  # shape (nrow+1, ncol+1)

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

    grid_gdf = gpd.GeoDataFrame(cells, crs=gdf.crs if gdf.crs else None)

    # Reproject lines if needed
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
