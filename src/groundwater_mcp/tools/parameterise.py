"""parameterise module — translate processed spatial data into MODFLOW 6 model inputs.

Accepts standard file formats (GeoTIFF, GeoPackage/Shapefile, CSV) that have already
been reprojected and resampled. Raw spatial preprocessing belongs in a companion
geodata-mcp server.
"""

from __future__ import annotations

import numpy as np

from groundwater_mcp.utils.model_store import (
    ModelReadOnlyError,
    get_gwf,
    read_meta,
    save_sim,
    write_meta,
)
from groundwater_mcp.utils.spatial import CRSError
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


def _record_provenance(model: str, key: str, source: str, tool: str, **extra) -> None:
    """Record the data source of a model array/component in .gwmcp_meta.json
    (7f-G2.2 provenance)."""
    meta = read_meta(model)
    provenance = meta.setdefault("provenance", {})
    entry = {"source": source, "tool": tool}
    entry.update({k: v for k, v in extra.items() if v is not None})
    provenance[key] = entry
    write_meta(model, meta)


def _persist_grid_crs(model: str, crs: str | None, xoff: float, yoff: float) -> None:
    """Persist the grid CRS/origin to .gwmcp_meta.json.

    flopy does not store the CRS in MF6 input files, so a later disk reload
    would drop ``modelgrid.crs`` and the exporters would fail CRS_UNKNOWN.
    ``model_store._apply_meta_crs`` restores it from here (7e-C5 regression:
    modeB rerun-6).
    """
    if not crs:
        return
    meta = read_meta(model)
    meta["crs"] = str(crs)
    meta["xorigin"] = float(xoff)
    meta["yorigin"] = float(yoff)
    write_meta(model, meta)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _impl_import_grid_from_shapefile(
    model: str,
    shapefile: str,
    nlay: int,
    layer_surfaces: list[str],
    method: str,
    target_crs: str | None,
    cell_size: float,
) -> dict:
    """Build a DIS or DISV grid from a catchment polygon shapefile."""
    import flopy.mf6 as mf6

    from groundwater_mcp.utils.spatial import (
        dis_grid_props_from_shapefile,
        disv_grid_props_from_shapefile,
    )

    gwf = get_gwf(model)
    method = method.lower()

    if method == "dis":
        props = dis_grid_props_from_shapefile(shapefile, cell_size, target_crs)
        nrow, ncol = props["nrow"], props["ncol"]

        # Build flat layer tops/bottoms unless layer_surfaces provided
        if layer_surfaces and len(layer_surfaces) == nlay + 1:
            # Sample each surface raster at cell centroids (flat pass for now —
            # full surface assignment happens via assign_top_from_raster)
            top = _sample_surface(layer_surfaces[0], props, nrow, ncol)
            botm = [_sample_surface(layer_surfaces[i + 1], props, nrow, ncol) for i in range(nlay)]
        else:
            # Default: flat layers 1 m thick each
            top = np.zeros((nrow, ncol), dtype=float)
            botm = [np.full((nrow, ncol), float(-(i + 1))) for i in range(nlay)]

        idomain = np.broadcast_to(props["idomain"][np.newaxis, :, :], (nlay, nrow, ncol)).copy()

        pkg = gwf.get_package("dis")
        if pkg is not None:
            gwf.remove_package(pkg)

        mf6.ModflowGwfdis(
            gwf,
            nlay=nlay,
            nrow=nrow,
            ncol=ncol,
            delr=props["delr"],
            delc=props["delc"],
            top=top,
            botm=botm,
            idomain=idomain,
            xorigin=props["xoff"],
            yorigin=props["yoff"],
        )
        if props["crs"]:
            try:
                gwf.modelgrid.set_coord_info(
                    xoff=props["xoff"], yoff=props["yoff"], crs=props["crs"]
                )
            except Exception:
                pass
            _persist_grid_crs(model, props["crs"], props["xoff"], props["yoff"])

        written = save_sim(model, gwf.simulation)
        _record_provenance(model, "grid", shapefile, "import_grid_from_shapefile", method="dis")
        return {
            "model": model,
            "grid_type": "DIS",
            "nlay": nlay,
            "nrow": nrow,
            "ncol": ncol,
            "ncells": nlay * nrow * ncol,
            "cell_size": cell_size,
            "crs": props["crs"],
            "xoff": props["xoff"],
            "yoff": props["yoff"],
            "written": written,
        }

    elif method == "disv":
        if layer_surfaces:
            raise ValueError(
                "layer_surfaces is not supported with method='disv'. The DISV "
                "branch builds flat layers; assign surface elevations "
                "afterwards with assign_top_from_raster (7e-B6)."
            )
        props = disv_grid_props_from_shapefile(shapefile, cell_size, target_crs)
        ncpl = props["ncpl"]

        top = np.zeros(ncpl, dtype=float)
        botm = [np.full(ncpl, float(-(i + 1))) for i in range(nlay)]

        pkg = gwf.get_package("disv")
        if pkg is not None:
            gwf.remove_package(pkg)

        mf6.ModflowGwfdisv(
            gwf,
            nlay=nlay,
            ncpl=ncpl,
            nvert=props["nvert"],
            vertices=props["vertices"],
            cell2d=props["cell2d"],
            top=top,
            botm=botm,
            xorigin=props["xoff"],
            yorigin=props["yoff"],
        )
        if props["crs"]:
            try:
                gwf.modelgrid.set_coord_info(
                    xoff=props["xoff"], yoff=props["yoff"], crs=props["crs"]
                )
            except Exception:
                pass
            _persist_grid_crs(model, props["crs"], props["xoff"], props["yoff"])

        written = save_sim(model, gwf.simulation)
        _record_provenance(model, "grid", shapefile, "import_grid_from_shapefile", method="disv")
        return {
            "model": model,
            "grid_type": "DISV",
            "nlay": nlay,
            "ncpl": ncpl,
            "nvert": props["nvert"],
            "ncells": nlay * ncpl,
            "cell_size": cell_size,
            "crs": props["crs"],
            "written": written,
        }

    else:
        raise ValueError(f"method must be 'dis' or 'disv', got '{method}'.")


def _sample_surface(raster_path: str, props: dict, nrow: int, ncol: int) -> np.ndarray:
    """Helper: sample a raster at DIS cell centroids and reshape to (nrow, ncol)."""
    from groundwater_mcp.utils.spatial import sample_raster_at_points

    xmin, ymax = props["xoff"], props["yoff"] + props["nrow"] * props["delc"]
    xc = xmin + (np.arange(ncol) + 0.5) * props["delr"]
    yc = ymax - (np.arange(nrow) + 0.5) * props["delc"]
    pts_x = np.tile(xc, nrow)
    pts_y = np.repeat(yc, ncol)
    values = sample_raster_at_points(raster_path, pts_x, pts_y, src_crs=props.get("crs"))
    return values.reshape(nrow, ncol)


def _nearest_valid_fill(arr: np.ndarray) -> np.ndarray:
    """Fill non-finite cells with the nearest finite value (7e-B11.3)."""
    arr = np.asarray(arr, dtype=float)
    finite = np.isfinite(arr)
    if finite.all():
        return arr
    from scipy import ndimage

    idx = ndimage.distance_transform_edt(
        ~finite, return_distances=False, return_indices=True
    )
    return arr[tuple(idx)]


def _zonal_stats_from_grid(
    raster: str, mg, nrow: int, ncol: int, method: str
) -> np.ndarray:
    """Aggregate a raster per DIS cell via resampled reprojection (7e-B5).

    ``method`` is ``"mean"`` / ``"min"`` / ``"max"`` (rasterio resampling
    constants). Requires a uniform cell size; a non-uniform grid falls back
    to the caller's point-sampling path.
    """
    import rasterio
    from affine import Affine
    from rasterio.crs import CRS
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    delr = np.asarray(mg.delr, dtype=float).ravel()
    delc = np.asarray(mg.delc, dtype=float).ravel()
    if delr.size and not np.allclose(delr, delr[0]):
        raise ValueError(
            "method='mean'/'min'/'max' requires uniform delr (regular grid); "
            "use method='nearest' or 'bilinear' for variable-spacing grids."
        )
    if delc.size and not np.allclose(delc, delc[0]):
        raise ValueError(
            "method='mean'/'min'/'max' requires uniform delc (regular grid); "
            "use method='nearest' or 'bilinear' for variable-spacing grids."
        )
    resampling = {
        "mean": Resampling.average,
        "min": Resampling.min,
        "max": Resampling.max,
    }[method]

    dr = float(delr[0]) if delr.size else 1.0
    dc = float(delc[0]) if delc.size else 1.0
    xoff = float(mg.xoffset)
    yoff = float(mg.yoffset)
    dst_transform = Affine(dr, 0.0, xoff, 0.0, -dc, yoff + nrow * dc)

    with rasterio.open(raster) as src:
        dst_crs = CRS.from_user_input(str(mg.crs)) if mg.crs else src.crs
        dst = np.zeros((nrow, ncol), dtype=np.float64)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=resampling,
        )
    # Cells whose footprint never intersects the raster land on the nodata
    # fill of reproject (0.0) — mark them NaN so the coverage logic treats
    # them consistently.
    with rasterio.open(raster) as src:
        nodata = src.nodata
    if nodata is not None:
        dst[dst == nodata] = np.nan
    return dst


def _impl_assign_top_from_raster(
    model: str,
    raster: str,
    layer: int,
    method: str = "nearest",
    fill: str = "error",
    coverage_tolerance: float = 0.1,
) -> dict:
    """Sample a GeoTIFF and assign to model top or a layer bottom.

    ``method`` selects the sampling: ``"mean"`` / ``"min"`` / ``"max"`` are
    per-cell zonal aggregations (regular DIS grids only — 7e-B5, previously
    accepted and silently ignored); ``"nearest"`` and ``"bilinear"`` sample at
    the cell centroids. ``fill`` controls what happens to cells without
    raster coverage (7e-B11.3): ``"error"`` (default) fails when more than
    ``coverage_tolerance`` of cells are uncovered and otherwise fills with the
    global median plus a warning; ``"median"`` always median-fills; ``"nearest"``
    fills from the nearest covered cell. ``cells_no_coverage`` is always
    reported.
    """
    from groundwater_mcp.utils.spatial import CRSError, grid_centroids, sample_raster_at_points

    gwf = get_gwf(model)
    mg = gwf.modelgrid

    method = (method or "nearest").lower()
    if method not in ("mean", "min", "max", "nearest", "bilinear"):
        raise ValueError(
            f"method must be one of mean, min, max, nearest, bilinear — got '{method}'."
        )
    fill = (fill or "error").lower()
    if fill not in ("error", "median", "nearest"):
        raise ValueError(
            f"fill must be one of error, median, nearest — got '{fill}'."
        )
    if not (0.0 < coverage_tolerance <= 1.0):
        raise ValueError("coverage_tolerance must be in (0, 1].")

    model_crs = str(mg.crs) if mg.crs else None

    # Fail loudly on unknown/mismatched CRS (7e-B11.2): a model without a CRS
    # cannot be compared against a raster that declares one.
    import rasterio

    with rasterio.open(raster) as src:
        raster_crs = src.crs
    if model_crs is None and raster_crs is not None:
        raise CRSError(
            "The model grid has no CRS but the raster declares "
            f"'{raster_crs}'. Set a CRS on the model grid first "
            "(set_model_crs, or import_grid_from_shapefile with target_crs) so "
            "elevations are sampled in a known coordinate space."
        )

    dis_pkg = gwf.get_package("dis")
    disv_pkg = gwf.get_package("disv")

    if dis_pkg is not None:
        nrow = int(dis_pkg.nrow.data)
        ncol = int(dis_pkg.ncol.data)
        if method in ("mean", "min", "max"):
            sampled = _zonal_stats_from_grid(raster, mg, nrow, ncol, method)
        else:
            xc, yc = grid_centroids(mg)
            resampling = "bilinear" if method == "bilinear" else "nearest"
            sampled = sample_raster_at_points(
                raster, xc, yc, src_crs=model_crs, resampling=resampling
            ).reshape(nrow, ncol)
    elif disv_pkg is not None:
        xc, yc = grid_centroids(mg)
        resampling = "bilinear" if method == "bilinear" else "nearest"
        sampled = sample_raster_at_points(
            raster, xc, yc, src_crs=model_crs, resampling=resampling
        )
    else:
        raise RuntimeError("No DIS or DISV package found. Add a grid first.")

    n_nan = int((~np.isfinite(sampled)).sum())
    n_total = int(sampled.size)
    if n_nan == n_total:
        raise ValueError(
            f"The raster does not cover any of the {n_total} model cells — "
            "check that the raster extent overlaps the model grid and that "
            "both share a CRS."
        )
    if n_nan / n_total > coverage_tolerance and fill == "error":
        raise ValueError(
            f"{n_nan} of {n_total} cells ({n_nan / n_total:.1%}) have no "
            f"raster coverage (coverage_tolerance={coverage_tolerance}). Use "
            "fill='median' or fill='nearest', raise coverage_tolerance, or "
            "check the raster extent."
        )

    warning = None
    if n_nan > 0:
        if fill == "nearest":
            sampled = _nearest_valid_fill(sampled)
        else:  # "error" (within tolerance) and "median" both median-fill
            sampled = np.where(
                np.isfinite(sampled), sampled, float(np.nanmedian(sampled))
            )
        warning = (
            f"{n_nan} cells had no raster coverage and were filled with "
            f"'{'nearest' if fill == 'nearest' else 'median'}'."
        )

    if dis_pkg is not None:
        if layer == 0:
            dis_pkg.top.set_data(sampled)
        else:
            botm = dis_pkg.botm.array.copy()
            botm[layer - 1] = sampled
            dis_pkg.botm.set_data(botm)
    elif disv_pkg is not None:
        if layer == 0:
            disv_pkg.top.set_data(sampled)
        else:
            botm = disv_pkg.botm.array.copy()
            botm[layer - 1] = sampled
            disv_pkg.botm.set_data(botm)

    written = save_sim(model, gwf.simulation)
    _record_provenance(
        model,
        "top" if layer == 0 else f"botm_{layer}",
        raster,
        "assign_top_from_raster",
        method=method,
    )
    result: dict = {
        "model": model,
        "raster": raster,
        "layer": layer,
        "method": method,
        "cells_assigned": int(n_total - n_nan),
        "cells_no_coverage": n_nan,
        "min": float(np.nanmin(sampled)),
        "max": float(np.nanmax(sampled)),
        "mean": float(np.nanmean(sampled)),
        "written": written,
    }
    if warning:
        result["warning"] = warning
    return result


def _impl_assign_k_from_zones(
    model: str,
    shapefile: str,
    k_field: str,
    layer: int | list[int],
    k33_field: str | None,
    icelltype_field: str | None,
) -> dict:
    """Assign K arrays to model layers from geological zone polygons."""
    import geopandas as gpd

    from groundwater_mcp.utils.spatial import grid_centroids, intersect_points_with_polygons

    gwf = get_gwf(model)
    mg = gwf.modelgrid

    gdf = gpd.read_file(shapefile)
    for col in [k_field, k33_field, icelltype_field]:
        if col and col not in gdf.columns:
            raise ValueError(
                f"Column '{col}' not found in shapefile. Available: {list(gdf.columns)}"
            )

    ncells_per_layer = mg.ncpl if hasattr(mg, "ncpl") else (mg.nrow * mg.ncol)
    xc_all, yc_all = grid_centroids(mg)
    xc = xc_all[:ncells_per_layer]
    yc = yc_all[:ncells_per_layer]

    model_crs = str(mg.crs) if mg.crs else None
    value_cols = [c for c in [k_field, k33_field, icelltype_field] if c]
    values = intersect_points_with_polygons(xc, yc, gdf, value_cols, points_crs=model_crs)

    k_vals = values[k_field]
    n_unmatched = int(np.isnan(k_vals).sum())

    # Determine which layers to update
    layers = layer if isinstance(layer, list) else [layer]

    dis_pkg = gwf.get_package("dis")
    disv_pkg = gwf.get_package("disv")
    npf_pkg = gwf.get_package("npf")

    if npf_pkg is None:
        raise RuntimeError("NPF package not found. Run add_npf_package first.")

    if dis_pkg is not None:
        nrow = int(dis_pkg.nrow.data)
        ncol = int(dis_pkg.ncol.data)
        nlay = int(dis_pkg.nlay.data)
        k_array = npf_pkg.k.array.copy()
        if k33_field:
            k33_array = (
                npf_pkg.k33.array.copy() if npf_pkg.k33.array is not None else k_array.copy()
            )
        if icelltype_field:
            ict_array = npf_pkg.icelltype.array.copy()

        for lyr in layers:
            if lyr >= nlay:
                raise ValueError(
                    f"Layer {lyr} out of range for model with {nlay} layers."
                )
            k_array[lyr] = k_vals.reshape(nrow, ncol)
            if k33_field:
                k33_array[lyr] = values[k33_field].reshape(nrow, ncol)
            if icelltype_field:
                ict_array[lyr] = values[icelltype_field].reshape(nrow, ncol).astype(int)

        npf_pkg.k.set_data(k_array)
        if k33_field:
            npf_pkg.k33.set_data(k33_array)
        if icelltype_field:
            npf_pkg.icelltype.set_data(ict_array)

    elif disv_pkg is not None:
        nlay = int(disv_pkg.nlay.data)
        k_array = npf_pkg.k.array.copy()

        for lyr in layers:
            if lyr >= nlay:
                raise ValueError(
                    f"Layer {lyr} out of range for model with {nlay} layers."
                )
            k_array[lyr] = k_vals
            if k33_field:
                k33_array = (
                    npf_pkg.k33.array.copy()
                    if npf_pkg.k33.array is not None
                    else k_array.copy()
                )
                k33_array[lyr] = values[k33_field]
                npf_pkg.k33.set_data(k33_array)

        npf_pkg.k.set_data(k_array)
    else:
        raise RuntimeError("No DIS or DISV package found.")

    written = save_sim(model, gwf.simulation)
    _record_provenance(model, "k", shapefile, "assign_k_from_zones", k_field=k_field)

    return {
        "model": model,
        "layers_updated": layers,
        "zone_count": len(gdf),
        "cells_matched": int(ncells_per_layer - n_unmatched),
        "cells_unmatched": n_unmatched,
        "k_range": {"min": float(np.nanmin(k_vals)), "max": float(np.nanmax(k_vals))},
        "written": written,
    }


def _impl_import_river_from_shapefile(
    model: str,
    shapefile: str,
    package: str,
    stage_field: str | None = None,
    cond_field: str | None = None,
    depth_field: str | None = None,
    stress_periods: list[int] | None = None,
    stage_raster: str | None = None,
    stage_offset: float = 1.0,
    coverage_tolerance: float = 0.1,
    bed_k: float | None = None,
    bed_thickness: float | None = None,
    channel_width: float | None = None,
) -> dict:
    """Intersect river/drain polylines with the model grid and add boundary package."""
    from groundwater_mcp.tools.builder import _BOUNDARY_PKG_CLASSES
    from groundwater_mcp.utils.spatial import CRSError, intersect_lines_with_dis_grid

    pkg_name = package.upper()
    if pkg_name not in ("RIV", "DRN", "GHB"):
        raise ValueError(
            f"import_river_from_shapefile supports RIV, DRN, GHB (not SFR). Got '{pkg_name}'."
        )

    gwf = get_gwf(model)
    mg = gwf.modelgrid
    dis_pkg = gwf.get_package("dis")
    if dis_pkg is None:
        raise RuntimeError("import_river_from_shapefile currently supports DIS grids only.")

    attr_cols = [c for c in [stage_field, cond_field, depth_field] if c]
    try:
        reaches = intersect_lines_with_dis_grid(shapefile, mg, attr_cols)
    except CRSError as exc:
        return _err(
            "CRS_UNKNOWN",
            str(exc),
            "Set a CRS on the model grid (e.g. import_grid_from_shapefile with "
            "target_crs) or reproject the shapefile to the model coordinates.",
        )

    if not reaches:
        import geopandas as gpd

        shp_gdf = gpd.read_file(shapefile)
        shp_bbox = tuple(float(v) for v in shp_gdf.total_bounds)
        grid_bbox = (
            float(np.min(mg.xvertices)),
            float(np.min(mg.yvertices)),
            float(np.max(mg.xvertices)),
            float(np.max(mg.yvertices)),
        )
        return _err(
            "NO_INTERSECTION",
            "No reaches intersected the model grid. "
            f"grid bbox={grid_bbox}, shapefile bbox={shp_bbox}.",
            "Check that the shapefile and model grid are in the same CRS and that "
            "the river network falls inside the grid extent.",
        )

    # Optional stage-from-raster: sample the raster at each reach's cell
    # centroid; stage = sampled elevation - stage_offset.
    dem_vals = None
    reaches_no_coverage = 0
    if stage_raster:
        from groundwater_mcp.utils.spatial import sample_raster_at_points

        cell_ids = [r["cellid"] for r in reaches]
        cc = mg.xyzcellcenters
        x = np.asarray([float(cc[0][cid[1], cid[2]]) for cid in cell_ids])
        y = np.asarray([float(cc[1][cid[1], cid[2]]) for cid in cell_ids])
        dem_vals = sample_raster_at_points(stage_raster, x, y, mg.crs)
        reaches_no_coverage = int(np.isnan(dem_vals).sum())
        if reaches_no_coverage / len(reaches) > coverage_tolerance:
            return _err(
                "STAGE_RASTER_NO_COVERAGE",
                f"{reaches_no_coverage} of {len(reaches)} river reaches fall "
                "outside the stage_raster extent, so their stage would be guessed "
                "rather than sampled. Use a raster covering the river network, "
                "raise coverage_tolerance, or drop stage_raster.",
            )

    # Conductance is derived, not guessed (7f-H1.2): prefer the shapefile
    # attribute, then the bed-property formula, else fail loudly. The old
    # default of reach-length-as-conductance is dimensionally wrong (L vs L²/T)
    # and is no longer used.
    has_bed_props = (
        bed_k is not None and bed_thickness is not None and channel_width is not None
    )
    if not cond_field and not has_bed_props:
        raise ValueError(
            "No conductance source provided for the river reaches. Provide "
            "cond_field (attribute), or bed_k + bed_thickness + channel_width "
            "(cond = bed_k * channel_width * reach_length / bed_thickness). "
            "The previous default of reach-length-as-conductance is "
            "dimensionally wrong and has been removed."
        )

    def _cond_for(reach) -> float:
        if cond_field:
            return float(reach.get(cond_field))
        assert bed_k is not None and bed_thickness is not None and channel_width is not None
        return float(bed_k) * float(channel_width) * reach["length_m"] / float(bed_thickness)

    # Build stress period data
    sps = stress_periods or [0]
    spd = {}
    for sp in sps:
        records = []
        for i, reach in enumerate(reaches):
            cellid = reach["cellid"]
            if pkg_name == "RIV":
                if stage_raster:
                    assert dem_vals is not None
                    elev = dem_vals[i]
                    if elev is None or elev != elev:  # NaN check
                        elev = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                    stage = float(elev) - stage_offset
                else:
                    stage = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                cond = _cond_for(reach)
                rbot = stage - float(reach.get(depth_field, 1.0)) if depth_field else stage - 1.0
                records.append([list(cellid), stage, cond, rbot])
            elif pkg_name == "DRN":
                elev = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                cond = _cond_for(reach)
                records.append([list(cellid), elev, cond])
            elif pkg_name == "GHB":
                bhead = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                cond = _cond_for(reach)
                records.append([list(cellid), bhead, cond])
        spd[sp] = records

    pkg_cls = _BOUNDARY_PKG_CLASSES[pkg_name]
    existing = gwf.get_package(pkg_name.lower())
    if existing is not None:
        gwf.remove_package(existing)
    pkg_cls(gwf, stress_period_data=spd, save_flows=True)

    written = save_sim(model, gwf.simulation)
    _record_provenance(
        model,
        pkg_name,
        shapefile,
        "import_river_from_shapefile",
        stage_source="raster" if stage_raster else ("attribute" if stage_field else "default"),
    )
    result: dict = {
        "model": model,
        "package": pkg_name,
        "reach_count": len(reaches),
        "stage_source": "raster" if stage_raster else ("attribute" if stage_field else "default"),
        "stress_periods": {sp: len(spd[sp]) for sp in sps},
        "written": written,
    }
    if stage_raster:
        result["reaches_no_raster_coverage"] = reaches_no_coverage
    return result


def _impl_import_obs_from_csv(
    model: str,
    csv_file: str,
    obs_type: str,
    site_col: str,
    date_col: str,
    value_col: str,
    x_col: str | None,
    y_col: str | None,
    layer: int,
) -> dict:
    """Read head/flow observations from CSV and write a MODFLOW 6 OBS file."""
    import flopy.mf6 as mf6
    import pandas as pd

    gwf = get_gwf(model)
    mg = gwf.modelgrid
    ws = resolve_workspace(model)

    df = pd.read_csv(
        csv_file,
        parse_dates=[date_col]
        if date_col in pd.read_csv(csv_file, nrows=0).columns
        else False,
    )

    for col in [site_col, value_col]:
        if col not in df.columns:
            raise ValueError(
                f"Column '{col}' not found in CSV. Available: {list(df.columns)}"
            )

    sites = df[site_col].unique()
    site_to_cellid: dict[str, tuple[int, ...]] = {}

    if x_col and y_col and x_col in df.columns and y_col in df.columns:
        # Map each site to a cell by its mean (x, y) coordinate
        site_coords = df.groupby(site_col)[[x_col, y_col]].mean()

        xcoords = site_coords[x_col].to_numpy()
        ycoords = site_coords[y_col].to_numpy()

        # Find nearest cell centroid for each site
        from groundwater_mcp.utils.spatial import grid_centroids
        ncells_per_layer = mg.ncpl if hasattr(mg, "ncpl") else (mg.nrow * mg.ncol)
        xc_all, yc_all = grid_centroids(mg)
        xc = xc_all[:ncells_per_layer]
        yc = yc_all[:ncells_per_layer]

        for site, sx, sy in zip(site_coords.index, xcoords, ycoords):
            dist = np.hypot(xc - sx, yc - sy)
            nearest = int(np.argmin(dist))
            dis_pkg = gwf.get_package("dis")
            if dis_pkg is not None:
                ncol = int(dis_pkg.ncol.data)
                row_idx = nearest // ncol
                col_idx = nearest % ncol
                cellid: tuple[int, ...] = (layer, row_idx, col_idx)
            else:
                cellid = (layer, nearest)
            site_to_cellid[site] = cellid
    else:
        # No coordinates — create placeholder observations keyed by site name
        for i, site in enumerate(sites):
            site_to_cellid[site] = (layer, i, 0)

    # Write MODFLOW 6 OBS file
    obs_file = ws / f"{gwf.name}.obs"
    obs_type_str = obs_type.upper()

    # Build continuous observation data
    # Format: {obs_file: [(obsname, obs_type, cellid), ...]}
    obsdata = {}
    obs_filename = f"{gwf.name}_{obs_type_str.lower()}.obs.csv"
    records = []
    for site in sites:
        cellid = site_to_cellid[site]
        obsname = str(site)[:40]  # MODFLOW obs names limited to 40 chars
        records.append((obsname, obs_type_str, cellid))
    obsdata[obs_filename] = records

    # Remove existing OBS package if present
    existing_obs = gwf.get_package("obs")
    if existing_obs is not None:
        gwf.remove_package(existing_obs)

    mf6.ModflowUtlobs(gwf, filename=f"{gwf.name}.obs", continuous=obsdata)
    written = save_sim(model, gwf.simulation)

    # Also write a summary CSV of what was imported
    summary_path = ws / f"{gwf.name}_obs_summary.csv"
    summary_rows = []
    site_entries = []
    for site in sites:
        site_df = df[df[site_col] == site]
        summary_rows.append({
            "site": site,
            "cellid": str(site_to_cellid[site]),
            "n_records": len(site_df),
            "date_min": str(site_df[date_col].min()) if date_col in site_df.columns else "",
            "date_max": str(site_df[date_col].max()) if date_col in site_df.columns else "",
            "value_mean": float(site_df[value_col].mean()),
        })
        site_entries.append({
            "site": str(site),
            "cellid": list(site_to_cellid[site]),
            "n_records": int(len(site_df)),
            "values": [float(v) for v in site_df[value_col].tolist()],
            "dates": [str(d) for d in site_df[date_col].tolist()]
            if date_col in site_df.columns
            else [],
        })
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)

    # Persist the observation targets as model state (7f-F1.1): the site →
    # cellid map, observed values and dates live in .gwmcp_meta.json so
    # read_simulated_observations / compare_to_observed / the calibration
    # chain can consume them across sessions.
    meta = read_meta(model)
    meta["observations"] = {
        "type": obs_type_str,
        "layer": int(layer),
        "obs_file": f"{gwf.name}.obs",
        "output_csv": obs_filename,
        "sites": site_entries,
    }
    meta.setdefault("provenance", {})["observations"] = {
        "source": csv_file,
        "tool": "import_obs_from_csv",
        "obs_type": obs_type_str,
    }
    write_meta(model, meta)

    return {
        "model": model,
        "obs_type": obs_type_str,
        "site_count": len(sites),
        "total_records": len(df),
        "obs_file": str(obs_file),
        "summary_file": str(summary_path),
        "site_cellid_map": {s: list(cid) for s, cid in site_to_cellid.items()},
        "written": written,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp) -> None:
    """Register parameterisation tools with the MCP server."""

    @mcp.tool()
    def import_grid_from_shapefile(
        model: str,
        shapefile: str,
        nlay: int,
        layer_surfaces: list[str] = [],
        method: str = "dis",
        target_crs: str | None = None,
        cell_size: float = 500.0,
    ) -> dict:
        """Build a DIS or DISV model grid from a catchment boundary shapefile.

        For method='dis', creates a regular structured grid clipped to the catchment
        polygon (cells outside = IDOMAIN -1). For method='disv', creates a Voronoi
        unstructured grid with seed points inside the polygon.
        Requires set_simulation to have been called first.
        """
        try:
            return _impl_import_grid_from_shapefile(
                model, shapefile, nlay, layer_surfaces, method, target_crs, cell_size
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("GRID_IMPORT_FAILED", str(exc))

    @mcp.tool()
    def assign_top_from_raster(
        model: str,
        raster: str,
        layer: int = 0,
        method: str = "nearest",
        fill: str = "error",
        coverage_tolerance: float = 0.1,
    ) -> dict:
        """Assign model top (layer=0) or layer bottom elevations from a GeoTIFF raster.

        layer=0 sets the model top. layer=N sets the bottom of layer N.
        method selects the sampling: "mean"/"min"/"max" are per-cell zonal
        aggregations (regular DIS grids; the old default silently point-sampled
        regardless), "nearest" and "bilinear" sample at the cell centroids.
        If the raster CRS differs from the model CRS, coordinates are
        reprojected automatically.

        fill controls cells without raster coverage: "error" (default) fails
        when more than coverage_tolerance (0.1 = 10%) of cells are uncovered
        and otherwise median-fills with a warning; "median" always
        median-fills; "nearest" fills from the nearest covered cell.
        cells_no_coverage is always reported."""
        try:
            return _impl_assign_top_from_raster(
                model, raster, layer, method, fill, coverage_tolerance
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except CRSError as exc:
            return _err(
                "CRS_UNKNOWN",
                str(exc),
                "Set a CRS on the model grid first (set_model_crs or "
                "import_grid_from_shapefile with target_crs).",
            )
        except RuntimeError as exc:
            return _err("PACKAGE_MISSING", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("RASTER_ASSIGN_FAILED", str(exc))

    @mcp.tool()
    def assign_k_from_zones(
        model: str,
        shapefile: str,
        k_field: str,
        layer: int | list[int] = 0,
        k33_field: str | None = None,
        icelltype_field: str | None = None,
    ) -> dict:
        """Assign hydraulic conductivity arrays from geological zone polygons.

        Cell centroids are spatially joined to zone polygons. Cells outside all
        zones retain their existing K value and are reported as unmatched.
        Requires NPF package to already exist (run add_npf_package first).
        """
        try:
            return _impl_assign_k_from_zones(
                model, shapefile, k_field, layer, k33_field, icelltype_field
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except RuntimeError as exc:
            return _err("PACKAGE_MISSING", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("K_ASSIGN_FAILED", str(exc))

    @mcp.tool()
    def import_river_from_shapefile(
        model: str,
        shapefile: str,
        package: str = "RIV",
        stage_field: str | None = None,
        cond_field: str | None = None,
        depth_field: str | None = None,
        stage_raster: str | None = None,
        stage_offset: float = 1.0,
        coverage_tolerance: float = 0.1,
        stress_periods: list[int] | None = None,
        bed_k: float | None = None,
        bed_thickness: float | None = None,
        channel_width: float | None = None,
    ) -> dict:
        """Build RIV, DRN, or GHB stress period data from a river/drain shapefile.

        Intersects the river network with the model grid. Stage, conductance,
        and depth values are read from the shapefile attributes if provided,
        otherwise defaults are used (stage=0, depth=1 m). Currently supports
        DIS grids only.

        Conductance is derived, not guessed (7f-H1.2): pass a ``cond_field``
        attribute, or ``bed_k`` + ``bed_thickness`` + ``channel_width`` and the
        tool computes ``cond = bed_k * channel_width * reach_length /
        bed_thickness`` per reach. With no conductance source the call fails
        loudly — the old reach-length-as-conductance default was dimensionally
        wrong.

        stage_raster (a ground-surface elevation GeoTIFF) samples the stage for
        every reach (stage = sampled elevation - stage_offset). If more than
        coverage_tolerance (default 0.1 = 10%) of reaches fall outside the
        raster extent, the call fails with STAGE_RASTER_NO_COVERAGE rather than
        silently guessing those stages; otherwise the uncovered count is
        reported as reaches_no_raster_coverage.

        The model grid must carry a CRS (e.g. built via
        import_grid_from_shapefile) when the shapefile declares one, otherwise
        the call fails with CRS_UNKNOWN — coordinates are never compared in an
        assumed coordinate space.

        NOTE on defaults: a stage of 0.0 makes the river act as a deep drain
        (heads can drop well below the channel, draining the aquifer). Set a
        realistic stage — preferably via stage_raster or the stage_field
        attribute.
        """
        try:
            return _impl_import_river_from_shapefile(
                model,
                shapefile,
                package,
                stage_field,
                cond_field,
                depth_field,
                stress_periods,
                stage_raster,
                stage_offset,
                coverage_tolerance,
                bed_k,
                bed_thickness,
                channel_width,
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except RuntimeError as exc:
            return _err("PACKAGE_MISSING", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("RIVER_IMPORT_FAILED", str(exc))

    @mcp.tool()
    def import_obs_from_csv(
        model: str,
        csv_file: str,
        obs_type: str = "HEAD",
        site_col: str = "site",
        date_col: str = "date",
        value_col: str = "value",
        x_col: str | None = None,
        y_col: str | None = None,
        layer: int = 0,
    ) -> dict:
        """Import head or flow observations from a CSV file.

        Sites are mapped to model cells by (x, y) coordinate (nearest centroid) if
        x_col and y_col are provided, otherwise by sequential order. Writes a
        MODFLOW 6 OBS file and a summary CSV of site-to-cell mappings.
        """
        try:
            return _impl_import_obs_from_csv(
                model, csv_file, obs_type, site_col, date_col, value_col, x_col, y_col, layer
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("OBS_IMPORT_FAILED", str(exc))
