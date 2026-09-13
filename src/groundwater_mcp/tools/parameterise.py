"""parameterise module — translate processed spatial data into MODFLOW 6 model inputs.

Accepts standard file formats (GeoTIFF, GeoPackage/Shapefile, CSV) that have already
been reprojected and resampled. Raw spatial preprocessing belongs in a companion
geodata-mcp server.
"""

from __future__ import annotations

import re

import numpy as np

from groundwater_mcp.utils.grid import get_dis, get_disu, get_disv
from groundwater_mcp.utils.model_store import (
    ModelReadOnlyError,
    clear_k_base_snapshot,
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


# MODFLOW 6 continuous OBS types accepted by import_obs_from_csv. A compound
# flux observation (e.g. total river discharge over a cell group) is NOT an
# OBS6 continuous type — writing one produces a record MF6 rejects
# ("Observation type not found") — so unsupported types fail loudly instead.
_MF6_CONTINUOUS_OBS_TYPES = {
    "HEAD",
    "DRAWDOWN",
    "DEPTH",
    "CONCENTRATION",
    "TEMPERATURE",
}

# MODFLOW 6 treats '#' as a comment marker and splits OBS records on whitespace,
# so a name like GMS's "POINT_#1" is read as "POINT_" and the remainder becomes a
# comment ("Observation type not found: #").
_OBS_NAME_INVALID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _cellid_as_json(cid):
    """JSON-friendly cell id: a list for DIS/DISV tuples, an int for DISU nodes."""
    return cid if isinstance(cid, int) else list(cid)


def _safe_obs_name(site: str, used: set[str]) -> str:
    """Return an MF6-safe, unique OBS name for *site* (<= 40 chars)."""
    name = _OBS_NAME_INVALID_RE.sub("_", str(site)).strip("_") or "obs"
    name = re.sub(r"_{2,}", "_", name)
    name = name[:40]
    base = name
    i = 1
    while name.lower() in used:
        suffix = f"_{i}"
        name = base[: 40 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name


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

        # Replacing the grid must remove either discretisation type (a DISV
        # model's package also prefix-matches get_package("dis")).
        for existing in (get_dis(gwf), get_disv(gwf)):
            if existing is not None:
                gwf.remove_package(existing)

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

        for existing in (get_dis(gwf), get_disv(gwf)):
            if existing is not None:
                gwf.remove_package(existing)

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


# ---------------------------------------------------------------------------
# Raster-to-array helpers (shared by the assign_*_from_raster tools)
# ---------------------------------------------------------------------------


def _raster_values_for_grid(
    model: str, raster: str, method: str, fill: str, coverage_tolerance: float
) -> dict:
    """Sample ``raster`` over the layer-0 cell footprint of ``model``'s grid.

    Mirrors ``assign_top_from_raster``'s semantics exactly (7e-B5 / 7e-B11.3):
    ``method`` mean/min/max aggregate per cell on regular DIS grids,
    nearest/bilinear sample at cell centroids; ``fill`` controls cells without
    raster coverage. Returns ``values`` shaped (nrow, ncol) for DIS or
    (ncpl,) for DISV, plus ``n_nan`` / ``n_total`` / ``warning``.
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
            "cell values are sampled in a known coordinate space."
        )

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)

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
        if method in ("mean", "min", "max"):
            raise ValueError(
                "method 'mean'/'min'/'max' aggregate whole cells and require a "
                "regular DIS grid; use 'nearest' or 'bilinear' for DISV grids."
            )
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

    return {
        "values": sampled,
        "n_nan": n_nan,
        "n_total": n_total,
        "warning": warning,
    }


def _checked_layers(layer: int | list[int], nlay: int) -> list[int]:
    """Normalise the 0-based ``layer`` argument to a list and range-check it."""
    layers = layer if isinstance(layer, list) else [layer]
    for lyr in layers:
        if not isinstance(lyr, int):
            raise ValueError(f"layer entries must be integers, got '{lyr}'.")
        if lyr >= nlay:
            raise ValueError(f"Layer {lyr} out of range for model with {nlay} layers.")
    if not layers:
        raise ValueError("layer must name at least one layer.")
    return layers


def _expand_raster_spec(raster, layers: list[int], argname: str) -> list[str]:
    """Return one raster path per requested layer.

    A single path is reused for every layer; a list must have one entry per
    layer (or exactly one entry, also reused). Anything else is refused so a
    mismatched list can never silently map the wrong raster onto a layer.
    """
    if isinstance(raster, str):
        return [raster] * len(layers)
    if isinstance(raster, list) and raster:
        if len(raster) == len(layers):
            return [str(r) for r in raster]
        if len(raster) == 1:
            return [str(raster[0])] * len(layers)
        raise ValueError(
            f"{argname} has {len(raster)} entries but {len(layers)} layer(s) "
            "were requested — pass one raster path per layer, or a single "
            "path to reuse it across every layer."
        )
    raise ValueError(
        f"{argname} must be a raster path or a list of raster paths."
    )


def _active_layer_mask(dis_pkg, disv_pkg, lyr: int, shape=None) -> np.ndarray:
    """Boolean active-cell mask for ``lyr``.

    With no explicit ``idomain`` the MODFLOW default is that every cell is
    active, so the mask is all-True for ``shape``.
    """
    pkg = dis_pkg if dis_pkg is not None else disv_pkg
    idm = getattr(pkg, "idomain", None)
    if idm is not None and idm.array is not None:
        return np.asarray(idm.array)[lyr] > 0
    if shape is None:
        return np.ones(1, dtype=bool)
    return np.ones(shape, dtype=bool)


# ---------------------------------------------------------------------------
# Generic raster-to-model-array target table (assign_array_from_raster)
# ---------------------------------------------------------------------------
#
# Each entry describes one MODFLOW 6 array an agent can fill from a GeoTIFF.
# kind == "layer":  a full 3-D cell property array (NPF k/k33, IC strt,
#                   STO ss/sy) written per model layer (layer index 0..nlay-1).
# kind == "period": a per-stress-period grid array on the layer-0 footprint
#                   (RCHA recharge, EVTA surface/rate/depth) written for one
#                   0-based stress period; applies to the topmost active cell
#                   per column (the MF6 default).

_ARRAY_TARGETS: dict[str, dict] = {
    "NPF.k": {
        "kind": "layer", "pkg": "npf", "attr": "k",
        "guard": "positive_active", "units": None,
    },
    "NPF.k33": {
        "kind": "layer", "pkg": "npf", "attr": "k33",
        "guard": "positive_active", "units": None,
    },
    "IC.strt": {"kind": "layer", "pkg": "ic", "attr": "strt", "guard": None, "units": None},
    "STO.ss": {
        "kind": "layer", "pkg": "sto", "attr": "ss",
        "guard": "nonnegative", "units": None,
    },
    "STO.sy": {
        "kind": "layer", "pkg": "sto", "attr": "sy",
        "guard": "nonnegative", "units": None,
    },
    "RCHA.recharge": {
        "kind": "period", "pkg": "rcha", "attr": "recharge",
        "guard": None, "units": "rate",
    },
    "EVTA.surface": {
        "kind": "period", "pkg": "evta", "attr": "surface",
        "guard": None, "units": None,
    },
    "EVTA.rate": {
        "kind": "period", "pkg": "evta", "attr": "rate",
        "guard": "nonnegative", "units": "rate",
    },
    "EVTA.depth": {
        "kind": "period", "pkg": "evta", "attr": "depth",
        "guard": "positive", "units": None,
    },
}


def _package_of_type(gwf, pkg_type: str):
    """The single package of ``pkg_type`` on ``gwf``, or None."""
    for nam in gwf.get_package_list():
        pkg = gwf.get_package(nam)
        if pkg is not None and getattr(pkg, "package_type", "").lower() == pkg_type.lower():
            return pkg
    return None


def _package_attr_array(pkg, attr: str) -> np.ndarray | None:
    """The full .array of a package attribute, or None when undefined."""
    obj = getattr(pkg, attr, None)
    if obj is None:
        return None
    arr = getattr(obj, "array", None)
    if arr is None:
        return None
    return np.asarray(arr, dtype=float)


def _grid_nlay(gwf) -> int:
    for pkg_type in ("dis", "disv"):
        pkg = _package_of_type(gwf, pkg_type)
        if pkg is not None:
            return int(getattr(pkg, "nlay").data)
    raise RuntimeError("No DIS or DISV package found.")


def _active_any_mask(dis_pkg, disv_pkg, nlay: int, shape) -> np.ndarray:
    """Cells active in at least one layer (per-column activity footprint)."""
    mask = np.zeros(shape, dtype=bool)
    for lyr in range(nlay):
        mask |= _active_layer_mask(dis_pkg, disv_pkg, lyr, shape)
    return mask


def _impl_assign_array_from_raster(
    model: str,
    target: str,
    raster: str | list[str],
    layer: int | list[int],
    stress_period: int,
    method: str,
    fill: str,
    coverage_tolerance: float,
    rate_units: str | None,
) -> dict:
    spec = _ARRAY_TARGETS.get(target)
    if spec is None:
        raise ValueError(
            f"Unsupported target '{target}'. Supported targets: "
            f"{', '.join(sorted(_ARRAY_TARGETS))}."
        )

    # The dedicated k/ic tools already implement the exact same write for
    # these targets with matching result shapes — delegate instead of duplicating.
    if target == "NPF.k":
        result = _impl_assign_k_from_raster(
            model, raster, None, layer, method, fill, coverage_tolerance
        )
        result["target"] = target
        return result
    if target == "IC.strt":
        result = _impl_assign_ic_from_raster(
            model, raster, layer, method, fill, coverage_tolerance
        )
        result["target"] = target
        return result

    if spec["kind"] == "period":
        return _impl_assign_period_array_from_raster(
            model, target, spec, raster, stress_period,
            method, fill, coverage_tolerance, rate_units,
        )
    return _impl_assign_layer_array_from_raster(
        model, target, spec, raster, layer, method, fill, coverage_tolerance
    )


def _impl_assign_layer_array_from_raster(
    model: str,
    target: str,
    spec: dict,
    raster: str | list[str],
    layer: int | list[int],
    method: str,
    fill: str,
    coverage_tolerance: float,
) -> dict:
    """Write a per-layer 3-D cell-property array (NPF.k33 / STO.ss / STO.sy)
    from one raster per requested layer."""
    gwf = get_gwf(model)
    pkg_type = spec["pkg"]
    attr = spec["attr"]

    pkg = _package_of_type(gwf, pkg_type)
    if pkg is None:
        raise RuntimeError(
            f"'{pkg_type.upper()}' package not found. Run the builder call "
            f"that creates it first (add_npf_package / add_ic_package / "
            "add_sto_package)."
        )
    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
    nlay = _grid_nlay(gwf)

    layers = _checked_layers(layer, nlay)
    rasters = _expand_raster_spec(raster, layers, "raster")

    arr = _package_attr_array(pkg, attr)
    if arr is None:
        raise RuntimeError(
            f"'{pkg_type.upper()}.{attr}' is not defined on this model — e.g. "
            "add_npf_package was called without k33, or add_sto_package "
            "without sy. Define it first, then assign it from a raster."
        )
    arr3 = arr.copy()

    conv = _package_attr_array(pkg, "iconvert")

    warnings: list[str] = []
    assignments: list[dict] = []
    value_cells: list[np.ndarray] = []
    n_assigned = 0
    n_uncovered = 0

    for i, lyr in enumerate(layers):
        res = _raster_values_for_grid(
            model, rasters[i], method, fill, coverage_tolerance
        )
        values = res["values"]
        if res["warning"]:
            warnings.append(res["warning"])

        guard_active = _active_layer_mask(dis_pkg, disv_pkg, lyr, values.shape)
        if attr == "sy" and conv is not None and conv.shape[0] > lyr:
            guard_active = guard_active & (conv[lyr] > 0)

        if spec["guard"] == "positive_active":
            bad = guard_active & (~np.isfinite(values) | (values <= 0.0))
            if bool(bad.any()):
                raise ValueError(
                    f"target '{target}' from raster '{rasters[i]}' yields "
                    f"{int(bad.sum())} non-positive or non-finite values in "
                    f"active cells of layer {lyr}."
                )
        elif spec["guard"] == "nonnegative":
            bad = guard_active & (~np.isfinite(values) | (values < 0.0))
            if bool(bad.any()):
                raise ValueError(
                    f"target '{target}' from raster '{rasters[i]}' yields "
                    f"{int(bad.sum())} negative or non-finite values in "
                    f"layer {lyr} — storage properties must be >= 0."
                )

        arr3[lyr] = values
        n_assigned += res["n_total"] - res["n_nan"]
        n_uncovered += res["n_nan"]
        if bool(guard_active.any()):
            value_cells.append(values[guard_active])
        else:
            value_cells.append(values[np.isfinite(values)])
        assignments.append(
            {
                "layer": lyr,
                "raster": rasters[i],
                "cells_assigned": int(res["n_total"] - res["n_nan"]),
                "cells_no_coverage": int(res["n_nan"]),
            }
        )

    getattr(pkg, attr).set_data(arr3)
    written = save_sim(model, gwf.simulation)

    combined = np.concatenate([a.ravel() for a in value_cells]) if value_cells else np.array([])
    value_range: dict[str, float | None]
    if combined.size:
        value_range = {
            "min": float(np.min(combined)),
            "max": float(np.max(combined)),
            "mean": float(np.mean(combined)),
        }
    else:
        value_range = {"min": None, "max": None, "mean": None}

    provenance_key = {
        "npf": "k33" if attr == "k33" else "k",
        "sto": f"sto_{attr}",
    }.get(pkg_type, f"{pkg_type}_{attr}")
    _record_provenance(
        model,
        provenance_key,
        rasters[0] if len(set(rasters)) == 1 else ",".join(rasters),
        "assign_array_from_raster",
        target=target,
        method=method,
    )

    result: dict = {
        "model": model,
        "target": target,
        "layers_updated": layers,
        "method": method,
        "assignments": assignments,
        "cells_assigned": int(n_assigned),
        "cells_no_coverage": int(n_uncovered),
        "value_range": value_range,
        "written": written,
    }
    if warnings:
        result["warning"] = "; ".join(dict.fromkeys(warnings))
    return result


def _impl_assign_period_array_from_raster(
    model: str,
    target: str,
    spec: dict,
    raster: str | list[str],
    stress_period: int,
    method: str,
    fill: str,
    coverage_tolerance: float,
    rate_units: str | None,
) -> dict:
    """Write one per-stress-period grid array (RCHA recharge, EVTA surface /
    rate / depth) from a single GeoTIFF over the layer-0 footprint."""
    if isinstance(raster, list):
        raise ValueError(
            f"target '{target}' is a per-stress-period grid array — raster "
            "must be a single path (one GeoTIFF per call), not a list."
        )

    gwf = get_gwf(model)
    pkg_type = spec["pkg"]
    attr = spec["attr"]

    sim = gwf.simulation
    tdis = sim.get_package("tdis") if sim is not None else None
    if tdis is None:
        raise RuntimeError("set_simulation must be called before adding period arrays.")
    nper = int(tdis.nper.array)
    if not (0 <= stress_period < nper):
        raise ValueError(
            f"stress_period {stress_period} out of range for nper={nper}. "
            "Use 0-based indices matching set_simulation."
        )

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
    if dis_pkg is None and disv_pkg is None:
        raise RuntimeError("No DIS or DISV package found.")
    nlay = _grid_nlay(gwf)

    res = _raster_values_for_grid(model, raster, method, fill, coverage_tolerance)
    values = res["values"].astype(float)
    active_any = _active_any_mask(dis_pkg, disv_pkg, nlay, values.shape)

    value_warnings: list[str] = []
    if spec["guard"] == "nonnegative":
        bad = active_any & (~np.isfinite(values) | (values < 0.0))
        if bool(bad.any()):
            value_warnings.append(
                f"{int(bad.sum())} cells have negative {attr} values "
                f"(min {float(np.min(values[active_any & np.isfinite(values)])):.6g})"
            )
    elif spec["guard"] == "positive":
        bad = active_any & (~np.isfinite(values) | (values <= 0.0))
        if bool(bad.any()):
            value_warnings.append(
                f"{int(bad.sum())} cells have non-positive {attr} values "
                f"(min {float(np.min(values[active_any & np.isfinite(values)])):.6g})"
            )

    declared_units: str | None = None
    if spec["units"] == "rate" and rate_units is not None:
        from groundwater_mcp.tools.builder import _RATE_UNITS_TO_MD

        if rate_units not in _RATE_UNITS_TO_MD:
            raise ValueError(
                f"Unrecognised rate_units '{rate_units}'. Accepted: "
                f"{sorted(_RATE_UNITS_TO_MD)}."
            )
        values = values * _RATE_UNITS_TO_MD[rate_units]
        declared_units = rate_units
        meta = read_meta(model)
        meta.setdefault("declared_units", {})["recharge"] = rate_units
        write_meta(model, meta)

    pkg = _package_of_type(gwf, pkg_type)
    created = False
    if pkg is None:
        import flopy.mf6 as mf6

        if pkg_type == "rcha":
            mf6.ModflowGwfrcha(gwf, recharge={stress_period: values}, save_flows=True)
        else:
            mf6.ModflowGwfevta(
                gwf, **{attr: {stress_period: values}}, save_flows=True
            )
        created = True
        pkg = _package_of_type(gwf, pkg_type)
    else:
        getattr(pkg, attr).set_data({stress_period: values})
    written = save_sim(model, gwf.simulation)

    if bool(active_any.any()):
        sel = values[active_any]
    else:
        sel = values[np.isfinite(values)]
    value_range: dict[str, float | None]
    if sel.size:
        value_range = {
            "min": float(np.min(sel)),
            "max": float(np.max(sel)),
            "mean": float(np.mean(sel)),
        }
    else:
        value_range = {"min": None, "max": None, "mean": None}

    provenance_key = {
        ("rcha", "recharge"): "recharge",
        ("evta", "surface"): "et_surface",
        ("evta", "rate"): "et_rate",
        ("evta", "depth"): "et_depth",
    }.get((pkg_type, attr), f"{pkg_type}_{attr}")
    provenance_extra: dict = {
        "target": target,
        "method": method,
        "stress_period": stress_period,
    }
    if declared_units:
        provenance_extra["rate_units"] = declared_units
    _record_provenance(
        model, provenance_key, str(raster), "assign_array_from_raster", **provenance_extra
    )

    result: dict = {
        "model": model,
        "target": target,
        "package": pkg_type.upper(),
        "stress_period": stress_period,
        "created": created,
        "cells_assigned": int(res["n_total"] - res["n_nan"]),
        "cells_no_coverage": int(res["n_nan"]),
        "value_range": value_range,
        "written": written,
    }
    if declared_units:
        result["rate_units"] = declared_units
    if res["warning"]:
        result["warning"] = res["warning"]
    if value_warnings:
        result["value_warnings"] = value_warnings
    return result


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

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)

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

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
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
    clear_k_base_snapshot(model, gwf.name)
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


def _impl_assign_k_from_raster(
    model: str,
    raster: str | list[str],
    k33_raster: str | list[str] | None,
    layer: int | list[int],
    method: str,
    fill: str,
    coverage_tolerance: float,
) -> dict:
    """Assign per-layer K (and optionally k33) to NPF from GeoTIFF rasters.

    See the registered tool docstring for the public contract.
    """
    gwf = get_gwf(model)
    npf_pkg = gwf.get_package("npf")
    if npf_pkg is None:
        raise RuntimeError("NPF package not found. Run add_npf_package first.")

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
    if dis_pkg is not None:
        nlay = int(dis_pkg.nlay.data)
    elif disv_pkg is not None:
        nlay = int(disv_pkg.nlay.data)
    else:
        raise RuntimeError("No DIS or DISV package found.")

    layers = _checked_layers(layer, nlay)
    k_rasters = _expand_raster_spec(raster, layers, "raster")
    k33_rasters = (
        _expand_raster_spec(k33_raster, layers, "k33_raster")
        if k33_raster is not None
        else None
    )

    k_array = np.asarray(npf_pkg.k.array, dtype=float).copy()
    k33_array: np.ndarray | None = None
    if k33_rasters is not None:
        k33_array = (
            np.asarray(npf_pkg.k33.array, dtype=float).copy()
            if npf_pkg.k33.array is not None
            else k_array.copy()
        )

    warnings: list[str] = []
    assignments: list[dict] = []
    k_min_max: list[np.ndarray] = []
    n_assigned = 0
    n_uncovered = 0

    for i, lyr in enumerate(layers):
        res = _raster_values_for_grid(
            model, k_rasters[i], method, fill, coverage_tolerance
        )
        values = res["values"]
        if res["warning"]:
            warnings.append(res["warning"])

        # A non-positive or non-finite K in an active cell crashes MODFLOW's
        # NPF prepcheck with an opaque floating-invalid error (rerun-2 finding).
        # Refuse to write it rather than hand the model a time bomb.
        active = _active_layer_mask(dis_pkg, disv_pkg, lyr, values.shape)
        bad = active & (~np.isfinite(values) | (values <= 0.0))
        if bool(bad.any()):
            raise ValueError(
                f"raster '{k_rasters[i]}' yields {int(bad.sum())} non-positive "
                f"or non-finite K values in active cells of layer {lyr} — K "
                "must be > 0 wherever the model is active. Check the raster "
                "nodata/coverage handling and the value units."
            )

        k_array[lyr] = values
        if k33_rasters is not None:
            k33_res = _raster_values_for_grid(
                model, k33_rasters[i], method, fill, coverage_tolerance
            )
            k33_vals = k33_res["values"]
            if k33_res["warning"]:
                warnings.append(k33_res["warning"])
            bad33 = active & (~np.isfinite(k33_vals) | (k33_vals <= 0.0))
            if bool(bad33.any()):
                raise ValueError(
                    f"k33_raster '{k33_rasters[i]}' yields {int(bad33.sum())} "
                    f"non-positive or non-finite values in active cells of "
                    f"layer {lyr}."
                )
            assert k33_array is not None  # set when k33_rasters is not None
            k33_array[lyr] = k33_vals

        n_assigned += res["n_total"] - res["n_nan"]
        n_uncovered += res["n_nan"]
        if bool(active.any()):
            k_min_max.append(values[active])
        else:
            k_min_max.append(values[np.isfinite(values)])
        assignments.append(
            {
                "layer": lyr,
                "raster": k_rasters[i],
                "cells_assigned": int(res["n_total"] - res["n_nan"]),
                "cells_no_coverage": int(res["n_nan"]),
            }
        )

    npf_pkg.k.set_data(k_array)
    if k33_rasters is not None:
        npf_pkg.k33.set_data(k33_array)
    written = save_sim(model, gwf.simulation)
    clear_k_base_snapshot(model, gwf.name)

    combined = np.concatenate([a.ravel() for a in k_min_max]) if k_min_max else np.array([])
    k_range: dict[str, float | None]
    if combined.size:
        k_range = {"min": float(np.min(combined)), "max": float(np.max(combined))}
    else:
        k_range = {"min": None, "max": None}

    provenance_extra = {"method": method, "rasters": [str(r) for r in k_rasters]}
    if k33_rasters is not None:
        provenance_extra["k33_rasters"] = [str(r) for r in k33_rasters]
    _record_provenance(
        model,
        "k",
        k_rasters[0] if len(set(k_rasters)) == 1 else ",".join(str(r) for r in k_rasters),
        "assign_k_from_raster",
        **provenance_extra,
    )

    result: dict = {
        "model": model,
        "layers_updated": layers,
        "method": method,
        "assignments": assignments,
        "cells_assigned": int(n_assigned),
        "cells_no_coverage": int(n_uncovered),
        "k_range": k_range,
        "written": written,
    }
    if warnings:
        result["warning"] = "; ".join(dict.fromkeys(warnings))
    return result


def _impl_assign_ic_from_raster(
    model: str,
    raster: str | list[str],
    layer: int | list[int],
    method: str,
    fill: str,
    coverage_tolerance: float,
) -> dict:
    """Assign per-layer starting heads (IC strt) from GeoTIFF rasters.

    See the registered tool docstring for the public contract.
    """
    gwf = get_gwf(model)
    ic_pkg = gwf.get_package("ic")
    if ic_pkg is None:
        raise RuntimeError("IC package not found. Run add_ic_package first.")

    dis_pkg = get_dis(gwf)
    disv_pkg = get_disv(gwf)
    if dis_pkg is not None:
        nlay = int(dis_pkg.nlay.data)
    elif disv_pkg is not None:
        nlay = int(disv_pkg.nlay.data)
    else:
        raise RuntimeError("No DIS or DISV package found.")

    layers = _checked_layers(layer, nlay)
    rasters = _expand_raster_spec(raster, layers, "raster")

    strt = np.asarray(ic_pkg.strt.array, dtype=float).copy()
    warnings: list[str] = []
    assignments: list[dict] = []
    head_cells: list[np.ndarray] = []
    n_assigned = 0
    n_uncovered = 0

    for i, lyr in enumerate(layers):
        res = _raster_values_for_grid(
            model, rasters[i], method, fill, coverage_tolerance
        )
        values = res["values"]
        if res["warning"]:
            warnings.append(res["warning"])
        strt[lyr] = values
        n_assigned += res["n_total"] - res["n_nan"]
        n_uncovered += res["n_nan"]
        active = _active_layer_mask(dis_pkg, disv_pkg, lyr, values.shape)
        if bool(active.any()):
            head_cells.append(values[active])
        else:
            head_cells.append(values[np.isfinite(values)])
        assignments.append(
            {
                "layer": lyr,
                "raster": rasters[i],
                "cells_assigned": int(res["n_total"] - res["n_nan"]),
                "cells_no_coverage": int(res["n_nan"]),
            }
        )

    ic_pkg.strt.set_data(strt)
    written = save_sim(model, gwf.simulation)

    combined = np.concatenate([a.ravel() for a in head_cells]) if head_cells else np.array([])
    head_range: dict[str, float | None]
    if combined.size:
        head_range = {
            "min": float(np.min(combined)),
            "max": float(np.max(combined)),
            "mean": float(np.mean(combined)),
        }
    else:
        head_range = {"min": None, "max": None, "mean": None}

    _record_provenance(
        model,
        "ic",
        rasters[0] if len(set(rasters)) == 1 else ",".join(rasters),
        "assign_ic_from_raster",
        method=method,
    )

    result: dict = {
        "model": model,
        "layers_updated": layers,
        "method": method,
        "assignments": assignments,
        "cells_assigned": int(n_assigned),
        "cells_no_coverage": int(n_uncovered),
        "head_range": head_range,
        "written": written,
    }
    if warnings:
        result["warning"] = "; ".join(dict.fromkeys(warnings))
    return result


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
    dis_pkg = get_dis(gwf)
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
    cellid_col: str | None = None,
) -> dict:
    """Read head/flow observations from CSV and write a MODFLOW 6 OBS file."""
    from pathlib import Path

    import flopy.mf6 as mf6
    import pandas as pd

    gwf = get_gwf(model)
    mg = gwf.modelgrid
    ws = resolve_workspace(model)

    obs_type_str = obs_type.upper()
    if obs_type_str not in _MF6_CONTINUOUS_OBS_TYPES:
        raise ValueError(
            f"Unsupported obs_type '{obs_type_str}'. MODFLOW 6 OBS continuous "
            f"types supported here are {sorted(_MF6_CONTINUOUS_OBS_TYPES)}. "
            "Compound flux observations (e.g. total river discharge over a cell "
            "group) are not representable by an OBS6 continuous type — evaluate "
            "them with compute_water_balance instead of registering them as "
            "observations."
        )

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
    site_to_cellid: dict[str, tuple[int, ...] | int] = {}

    if cellid_col and cellid_col in df.columns:
        # Explicit cell ids (e.g. a gauge→cell map). Needed when coordinates are
        # ambiguous — DISU/DISV layers stack in x/y, so nearest-centroid cannot
        # distinguish them.
        disu_only = get_disu(gwf)
        for site in sites:
            raw = df.loc[df[site_col] == site, cellid_col].iloc[0]
            if disu_only is not None:
                node = int(float(raw))
                nnodes = int(disu_only.nodes.data)
                if not (0 <= node < nnodes):
                    raise ValueError(
                        f"Cell id {node} for site {site!r} is out of range on a "
                        f"{nnodes}-node DISU grid (0-based node expected)."
                    )
                site_to_cellid[site] = node + 1  # 1-based DISU OBS node
            else:
                parts = [
                    int(float(p))
                    for p in re.split(r"[,\s]+", str(raw).strip("[](){} "))
                    if p != ""
                ]
                if not parts:
                    raise ValueError(
                        f"Could not parse cell id {raw!r} for site {site!r}."
                    )
                site_to_cellid[site] = tuple(parts) if len(parts) > 1 else parts[0]
    elif x_col and y_col and x_col in df.columns and y_col in df.columns:
        # Map each site to a cell by its mean (x, y) coordinate
        site_coords = df.groupby(site_col)[[x_col, y_col]].mean()

        xcoords = site_coords[x_col].to_numpy()
        ycoords = site_coords[y_col].to_numpy()

        # Find nearest cell centroid for each site
        from groundwater_mcp.utils.spatial import grid_centroids
        disu_pkg = get_disu(gwf)
        dis_pkg = get_dis(gwf)
        xc_all, yc_all = grid_centroids(mg)
        if disu_pkg is not None:
            # DISU node centroids span every node (mg.ncpl is a per-node array,
            # not a count); match against the full node set.
            xc, yc = xc_all, yc_all
        else:
            ncells_per_layer = (
                int(mg.ncpl) if hasattr(mg, "ncpl") else (int(mg.nrow) * int(mg.ncol))
            )
            xc = xc_all[:ncells_per_layer]
            yc = yc_all[:ncells_per_layer]

        for site, sx, sy in zip(site_coords.index, xcoords, ycoords):
            dist = np.hypot(xc - sx, yc - sy)
            nearest = int(np.argmin(dist))
            if disu_pkg is not None:
                # 1-based DISU node number (FloPy does not add 1 for a scalar
                # DISU OBS cellid).
                site_to_cellid[site] = nearest + 1
            elif dis_pkg is not None:
                ncol = int(dis_pkg.ncol.data)
                row_idx = nearest // ncol
                col_idx = nearest % ncol
                cellid: tuple[int, ...] = (layer, row_idx, col_idx)
                site_to_cellid[site] = cellid
            else:
                site_to_cellid[site] = (layer, nearest)
    else:
        # No coordinates — create placeholder observations keyed by site name,
        # sequentially through the cell ids. DIS cell ids are
        # (layer, row, col); DISV cell ids are (layer, node) — a 3-tuple is
        # invalid in an OBS6 file on a DISV grid; DISU cell ids are a single
        # 1-based node number.
        dis_only = get_dis(gwf)
        disu_only = get_disu(gwf)
        for i, site in enumerate(sites):
            if disu_only is not None:
                # MF6 OBS uses 1-based DISU node numbers and (unlike the
                # boundary packages) FloPy does not add 1 for a scalar DISU
                # cellid, so pass the 1-based node here.
                site_to_cellid[site] = i + 1
            elif dis_only is not None:
                site_to_cellid[site] = (layer, i, 0)
            else:
                site_to_cellid[site] = (layer, i)

    # Write MODFLOW 6 OBS file
    obs_file = ws / f"{gwf.name}.obs"

    # Build continuous observation data
    # Format: {obs_file: [(obsname, obs_type, cellid), ...]}
    obsdata = {}
    obs_filename = f"{gwf.name}_{obs_type_str.lower()}.obs.csv"
    records = []
    used_obs_names: set[str] = set()
    site_obs_name: dict[str, str] = {}
    for site in sites:
        cid = site_to_cellid[site]
        obsname = _safe_obs_name(str(site), used_obs_names)
        site_obs_name[str(site)] = obsname
        records.append((obsname, obs_type_str, cid))
    obsdata[obs_filename] = records

    # Replace the model's existing OBS package. A shipped model can carry
    # several continuous OBS6 files (e.g. a head-observation package plus an
    # SFR gage-observation package), so gwf.get_package("obs") returns a
    # single package, a list, or None — never assume one (7f-G). Only the
    # package(s) whose observation file we are about to reuse
    # (<gwf.name>.obs) are removed; obs files owned by other packages are
    # left untouched.
    obs_pkg_file = f"{gwf.name}.obs"
    existing_obs = gwf.get_package("obs")
    if existing_obs is not None:
        if not isinstance(existing_obs, list):
            existing_obs = [existing_obs]
        for obs_pkg in existing_obs:
            if obs_pkg is None:
                continue
            pkg_file = Path(str(getattr(obs_pkg, "filename", "") or ""))
            if pkg_file.name.lower() == obs_pkg_file.lower():
                gwf.remove_package(obs_pkg)

    mf6.ModflowUtlobs(gwf, filename=obs_pkg_file, continuous=obsdata)
    written = save_sim(model, gwf.simulation)

    # Also write a summary CSV of what was imported
    summary_path = ws / f"{gwf.name}_obs_summary.csv"
    summary_rows = []
    site_entries = []
    for site in sites:
        site_df = df[df[site_col] == site]
        obsname = site_obs_name[str(site)]
        summary_rows.append({
            "site": site,
            "obs_name": obsname,
            "cellid": str(site_to_cellid[site]),
            "n_records": len(site_df),
            "date_min": str(site_df[date_col].min()) if date_col in site_df.columns else "",
            "date_max": str(site_df[date_col].max()) if date_col in site_df.columns else "",
            "value_mean": float(site_df[value_col].mean()),
        })
        entry = {
            "site": obsname,
            "cellid": _cellid_as_json(site_to_cellid[site]),
            "n_records": int(len(site_df)),
            "values": [float(v) for v in site_df[value_col].tolist()],
            "dates": [str(d) for d in site_df[date_col].tolist()]
            if date_col in site_df.columns
            else [],
        }
        if obsname != str(site):
            entry["original_site"] = str(site)
        site_entries.append(entry)
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
        "site_cellid_map": {s: _cellid_as_json(cid) for s, cid in site_to_cellid.items()},
        "obs_names": dict(site_obs_name),
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
    def assign_k_from_raster(
        model: str,
        raster: str | list[str],
        layer: int | list[int] = 0,
        k33_raster: str | list[str] | None = None,
        method: str = "nearest",
        fill: str = "error",
        coverage_tolerance: float = 0.1,
    ) -> dict:
        """Assign per-layer hydraulic conductivity (k, and optionally k33) to the
        NPF package from GeoTIFF rasters.

        Each requested model layer samples its raster at the cell centroids
        ("nearest" / "bilinear") or aggregates per cell ("mean" / "min" /
        "max", regular DIS grids only) and writes the result into the NPF k
        (and k33) arrays. Raster values must already be in the model's k units
        (the units declared at add_npf_package, e.g. m/d). Unlike
        assign_k_from_zones no polygon zones are needed — this is the tool for
        per-cell K stored as raster grids (e.g. TX*.tif / CL*.tif layers, or a
        full-resolution K field against a coarse model grid).

        layer is the 0-based model layer index (0..nlay-1); pass a list to
        update several layers in one call. raster (and k33_raster) accept a
        single path — reused for every requested layer — or a list with one
        path per layer. A mismatched list is refused rather than silently
        mapped onto the wrong layer.

        Coverage and fill behave exactly like assign_top_from_raster: cells
        outside the raster extent become NaN and are handled by fill
        ("error" fails beyond coverage_tolerance, "median" / "nearest" fill
        them), and cells_no_coverage is reported. The model grid must carry a
        CRS when the raster declares one, otherwise the call fails with
        CRS_UNKNOWN.

        The call refuses to write a non-positive or non-finite K into an
        active cell — MODFLOW's NPF prepcheck would otherwise crash on it with
        an opaque floating-invalid error. Requires NPF (add_npf_package first)
        and a DIS or DISV grid."""
        try:
            return _impl_assign_k_from_raster(
                model, raster, k33_raster, layer, method, fill, coverage_tolerance
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
            return _err("K_ASSIGN_FAILED", str(exc))

    @mcp.tool()
    def assign_ic_from_raster(
        model: str,
        raster: str | list[str],
        layer: int | list[int] = 0,
        method: str = "nearest",
        fill: str = "error",
        coverage_tolerance: float = 0.1,
    ) -> dict:
        """Assign per-layer starting heads (IC strt) from GeoTIFF rasters.

        Replaces the scalar/per-layer heads set by add_ic_package with
        spatially varying starting heads sampled from a raster (same
        method / fill / coverage_tolerance semantics as assign_top_from_raster;
        mean/min/max aggregates are for regular DIS grids, nearest/bilinear
        sample at cell centroids on any grid). This matters mainly as a good
        initial guess for iterative solves — it has no effect on a converged
        steady-state result.

        layer is the 0-based model layer index (0..nlay-1); pass a list to
        update several layers in one call. raster accepts a single path
        (reused for every requested layer) or a list with one path per layer.
        Requires an IC package (add_ic_package first) and a DIS or DISV grid;
        the model grid must carry a CRS when the raster declares one."""
        try:
            return _impl_assign_ic_from_raster(
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
            return _err("IC_ASSIGN_FAILED", str(exc))

    @mcp.tool()
    def assign_array_from_raster(
        model: str,
        target: str,
        raster: str | list[str],
        layer: int | list[int] = 0,
        stress_period: int = 0,
        method: str = "nearest",
        fill: str = "error",
        coverage_tolerance: float = 0.1,
        rate_units: str | None = None,
    ) -> dict:
        """Apply a GeoTIFF field to any supported MODFLOW 6 model array — the
        generic raster→array tool.

        The AI never carries cell values: it names a *file* and a target from
        the enumerated table below, and the server samples the raster and
        writes the array (same method/fill/coverage_tolerance contract as
        assign_top_from_raster). Supported ``target`` values:

        - ``NPF.k`` / ``NPF.k33`` — per-layer hydraulic conductivity (must be
          positive in active cells). ``layer`` may be a list with one raster
          path per layer, or a single path reused across layers.
        - ``IC.strt`` — per-layer starting heads.
        - ``STO.ss`` / ``STO.sy`` — per-layer specific storage / yield (must
          be >= 0).
        - ``RCHA.recharge`` — per-stress-period recharge array over the grid
          (topmost active cell per column, the MF6 default). Single raster
          path, one ``stress_period`` per call.
        - ``EVTA.surface`` / ``EVTA.rate`` / ``EVTA.depth`` — per-stress-period
          evapotranspiration arrays (surface elevation / maximum ET rate /
          extinction depth). Same single-path, one-period-per-call form.

        Raster values must already be in the model's units, except the rate
        targets ``RCHA.recharge`` and ``EVTA.rate`` which honour ``rate_units``
        (e.g. "mm/yr", "m/d") and convert to m/d, recording the declared units.
        For per-layer targets pass one raster per layer (or a single path
        reused across layers); per-period targets take exactly one raster.
        RCHA/EVTA packages are created on first use; NPF/IC/STO targets need
        their builder call first. The model grid must carry a CRS when the
        raster declares one (CRS_UNKNOWN otherwise).

        Every call returns per-target coverage counts and the written
        value range; odd values (negative ET rates, non-positive ET depth)
        are reported in ``value_warnings`` rather than written silently."""
        try:
            return _impl_assign_array_from_raster(
                model, target, raster, layer, stress_period,
                method, fill, coverage_tolerance, rate_units,
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
            return _err("ARRAY_ASSIGN_FAILED", str(exc))

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
        cellid_col: str | None = None,
    ) -> dict:
        """Import head or flow observations from a CSV file.

        Sites are mapped to model cells by an explicit ``cellid_col`` cell-id
        column if provided, otherwise by (x, y) coordinate (nearest centroid) if
        x_col and y_col are provided, otherwise by sequential order. The
        explicit column is required when coordinates are ambiguous (DISU/DISV
        layers stack in x/y): on DISU it holds a 0-based node id. Coordinate
        mode also works on grids that carry cell geometry. Works on structured
        DIS grids (cell ids are ``(layer, row, col)``), DISV (``(layer, node)``)
        and DISU (scalar node). Writes a MODFLOW 6 OBS file and a summary CSV of
        site-to-cell mappings.
        """
        try:
            return _impl_import_obs_from_csv(
                model, csv_file, obs_type, site_col, date_col, value_col, x_col,
                y_col, layer, cellid_col,
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ModelReadOnlyError as exc:
            return _err("MODEL_ADOPTED_READONLY", str(exc))
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("OBS_IMPORT_FAILED", str(exc))
