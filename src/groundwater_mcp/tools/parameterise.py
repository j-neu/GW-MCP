"""parameterise module — translate processed spatial data into MODFLOW 6 model inputs.

Accepts standard file formats (GeoTIFF, GeoPackage/Shapefile, CSV) that have already
been reprojected and resampled. Raw spatial preprocessing belongs in a companion
geodata-mcp server.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from groundwater_mcp.utils.model_store import get_gwf, get_sim, save_sim
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


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
        sample_raster_at_points,
    )

    gwf = get_gwf(model)
    ws = resolve_workspace(model)
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

        save_sim(model, gwf.simulation)
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
        }

    elif method == "disv":
        props = disv_grid_props_from_shapefile(shapefile, cell_size, target_crs)
        ncpl = props["ncpl"]

        if layer_surfaces and len(layer_surfaces) == nlay + 1:
            # Placeholder: flat layers (full surface assignment via assign_top_from_raster)
            top = np.zeros(ncpl, dtype=float)
            botm = [np.full(ncpl, float(-(i + 1))) for i in range(nlay)]
        else:
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

        save_sim(model, gwf.simulation)
        return {
            "model": model,
            "grid_type": "DISV",
            "nlay": nlay,
            "ncpl": ncpl,
            "nvert": props["nvert"],
            "ncells": nlay * ncpl,
            "cell_size": cell_size,
            "crs": props["crs"],
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


def _impl_assign_top_from_raster(
    model: str,
    raster: str,
    layer: int,
    method: str,
) -> dict:
    """Sample a GeoTIFF and assign to model top or a layer bottom."""
    from groundwater_mcp.utils.spatial import grid_centroids, sample_raster_at_points

    gwf = get_gwf(model)
    mg = gwf.modelgrid

    # Get cell centroids (top-layer only for multi-layer sampling by centroid x,y)
    xc_all, yc_all = grid_centroids(mg)
    # For structured grids, centroids are the same for all layers in x,y
    # We only need unique (x, y) pairs = nrow*ncol (DIS) or ncpl (DISV)
    ncells_per_layer = mg.ncpl if hasattr(mg, "ncpl") else (mg.nrow * mg.ncol)
    xc = xc_all[:ncells_per_layer]
    yc = yc_all[:ncells_per_layer]

    model_crs = str(mg.crs) if mg.crs else None
    sampled = sample_raster_at_points(raster, xc, yc, src_crs=model_crs)

    n_nan = int(np.isnan(sampled).sum())
    if n_nan > 0:
        warnings.warn(f"{n_nan} cells had no raster coverage and were set to NaN.")

    # Fill NaN with nearest valid value (forward-fill by index as simple fallback)
    if n_nan > 0:
        valid_vals = sampled[~np.isnan(sampled)]
        if len(valid_vals) > 0:
            fill_val = float(np.nanmedian(sampled))
            sampled = np.where(np.isnan(sampled), fill_val, sampled)

    dis_pkg = gwf.get_package("dis")
    disv_pkg = gwf.get_package("disv")

    if dis_pkg is not None:
        nrow = int(dis_pkg.nrow.data)
        ncol = int(dis_pkg.ncol.data)
        arr = sampled.reshape(nrow, ncol)
        if layer == 0:
            dis_pkg.top.set_data(arr)
        else:
            botm = dis_pkg.botm.array.copy()
            botm[layer - 1] = arr
            dis_pkg.botm.set_data(botm)
    elif disv_pkg is not None:
        if layer == 0:
            disv_pkg.top.set_data(sampled)
        else:
            botm = disv_pkg.botm.array.copy()
            botm[layer - 1] = sampled
            disv_pkg.botm.set_data(botm)
    else:
        raise RuntimeError("No DIS or DISV package found. Add a grid first.")

    save_sim(model, gwf.simulation)
    return {
        "model": model,
        "raster": raster,
        "layer": layer,
        "cells_assigned": int(ncells_per_layer),
        "cells_no_coverage": n_nan,
        "min": float(np.nanmin(sampled)),
        "max": float(np.nanmax(sampled)),
        "mean": float(np.nanmean(sampled)),
    }


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
            raise ValueError(f"Column '{col}' not found in shapefile. Available: {list(gdf.columns)}")

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
            k33_array = npf_pkg.k33.array.copy() if npf_pkg.k33.array is not None else k_array.copy()
        if icelltype_field:
            ict_array = npf_pkg.icelltype.array.copy()

        for lyr in layers:
            if lyr >= nlay:
                raise ValueError(f"Layer {lyr} out of range for model with {nlay} layers.")
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
                raise ValueError(f"Layer {lyr} out of range for model with {nlay} layers.")
            k_array[lyr] = k_vals
            if k33_field:
                k33_array = npf_pkg.k33.array.copy() if npf_pkg.k33.array is not None else k_array.copy()
                k33_array[lyr] = values[k33_field]
                npf_pkg.k33.set_data(k33_array)

        npf_pkg.k.set_data(k_array)
    else:
        raise RuntimeError("No DIS or DISV package found.")

    save_sim(model, gwf.simulation)

    zone_counts = {}
    gdf_indexed = gdf.reset_index(drop=True)
    for i, row_ in gdf_indexed.iterrows():
        zone_counts[str(row_[k_field])] = int((k_vals == row_[k_field]).sum())

    return {
        "model": model,
        "layers_updated": layers,
        "zone_count": len(gdf),
        "cells_matched": int(ncells_per_layer - n_unmatched),
        "cells_unmatched": n_unmatched,
        "k_range": {"min": float(np.nanmin(k_vals)), "max": float(np.nanmax(k_vals))},
    }


def _impl_import_river_from_shapefile(
    model: str,
    shapefile: str,
    package: str,
    stage_field: str | None,
    cond_field: str | None,
    depth_field: str | None,
    stress_periods: list[int] | None,
) -> dict:
    """Intersect river/drain polylines with the model grid and add boundary package."""
    import flopy.mf6 as mf6
    from groundwater_mcp.utils.spatial import intersect_lines_with_dis_grid
    from groundwater_mcp.tools.builder import _BOUNDARY_PKG_CLASSES

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
    reaches = intersect_lines_with_dis_grid(shapefile, mg, attr_cols)

    if not reaches:
        return _err(
            "NO_INTERSECTION",
            "No reaches intersected the model grid.",
            "Check that the shapefile and model grid share the same CRS.",
        )

    # Build stress period data
    sps = stress_periods or [0]
    spd = {}
    for sp in sps:
        records = []
        for reach in reaches:
            cellid = reach["cellid"]
            if pkg_name == "RIV":
                stage = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                cond = float(reach.get(cond_field, reach["length_m"])) if cond_field else reach["length_m"]
                rbot = stage - float(reach.get(depth_field, 1.0)) if depth_field else stage - 1.0
                records.append([list(cellid), stage, cond, rbot])
            elif pkg_name == "DRN":
                elev = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                cond = float(reach.get(cond_field, reach["length_m"])) if cond_field else reach["length_m"]
                records.append([list(cellid), elev, cond])
            elif pkg_name == "GHB":
                bhead = float(reach.get(stage_field, 0.0)) if stage_field else 0.0
                cond = float(reach.get(cond_field, reach["length_m"])) if cond_field else reach["length_m"]
                records.append([list(cellid), bhead, cond])
        spd[sp] = records

    pkg_cls = _BOUNDARY_PKG_CLASSES[pkg_name]
    existing = gwf.get_package(pkg_name.lower())
    if existing is not None:
        gwf.remove_package(existing)
    pkg_cls(gwf, stress_period_data=spd)

    save_sim(model, gwf.simulation)
    return {
        "model": model,
        "package": pkg_name,
        "reach_count": len(reaches),
        "stress_periods": {sp: len(spd[sp]) for sp in sps},
    }


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
    import pandas as pd
    import flopy.mf6 as mf6

    gwf = get_gwf(model)
    mg = gwf.modelgrid
    ws = resolve_workspace(model)

    df = pd.read_csv(csv_file, parse_dates=[date_col] if date_col in pd.read_csv(csv_file, nrows=0).columns else False)

    for col in [site_col, value_col]:
        if col not in df.columns:
            raise ValueError(f"Column '{col}' not found in CSV. Available: {list(df.columns)}")

    sites = df[site_col].unique()
    site_to_cellid: dict[str, tuple] = {}

    if x_col and y_col and x_col in df.columns and y_col in df.columns:
        # Map each site to a cell by its mean (x, y) coordinate
        site_coords = df.groupby(site_col)[[x_col, y_col]].mean()
        model_crs = str(mg.crs) if mg.crs else None

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
                nrow = int(dis_pkg.nrow.data)
                ncol = int(dis_pkg.ncol.data)
                row_idx = nearest // ncol
                col_idx = nearest % ncol
                cellid = (layer, row_idx, col_idx)
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
    save_sim(model, gwf.simulation)

    # Also write a summary CSV of what was imported
    summary_path = ws / f"{gwf.name}_obs_summary.csv"
    summary_rows = []
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
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)

    return {
        "model": model,
        "obs_type": obs_type_str,
        "site_count": len(sites),
        "total_records": len(df),
        "obs_file": str(obs_file),
        "summary_file": str(summary_path),
        "site_cellid_map": {s: list(cid) for s, cid in site_to_cellid.items()},
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
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("GRID_IMPORT_FAILED", str(exc))

    @mcp.tool()
    def assign_top_from_raster(
        model: str,
        raster: str,
        layer: int = 0,
        method: str = "mean",
    ) -> dict:
        """Assign model top (layer=0) or layer bottom elevations from a GeoTIFF raster.

        layer=0 sets the model top. layer=N sets the bottom of layer N.
        The raster is sampled at cell centroids. If the raster CRS differs from the
        model CRS, coordinates are reprojected automatically.
        """
        try:
            return _impl_assign_top_from_raster(model, raster, layer, method)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except RuntimeError as exc:
            return _err("PACKAGE_MISSING", str(exc))
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
        stress_periods: list[int] | None = None,
    ) -> dict:
        """Build RIV, DRN, or GHB stress period data from a river/drain polyline shapefile.

        Intersects the river network with the model grid. Stage, conductance, and
        depth values are read from the shapefile attributes if provided, otherwise
        defaults are used (stage=0, cond=intersection length, depth=1 m).
        Currently supports DIS grids only.
        """
        try:
            return _impl_import_river_from_shapefile(
                model, shapefile, package, stage_field, cond_field, depth_field, stress_periods
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
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
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("OBS_IMPORT_FAILED", str(exc))
