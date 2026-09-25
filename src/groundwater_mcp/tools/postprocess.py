"""postprocess module — read binary output files and compute derived quantities."""

from __future__ import annotations

import re
from pathlib import Path

import flopy.utils as fu
import numpy as np
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

from groundwater_mcp.utils.components import spec_for
from groundwater_mcp.utils.grid import get_dis, get_disu, get_disv
from groundwater_mcp.utils.model_store import get_gwf, get_model, read_meta
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


# ---------------------------------------------------------------------------
# File finders
# ---------------------------------------------------------------------------


def _oc_file_record(gwf, record_name: str) -> str | None:
    """Return the file name declared in the OC package for *record_name*
    (``head_filerecord`` / ``budget_filerecord``), or None (7e-B13)."""
    oc = gwf.get_package("oc")
    if oc is None:
        return None
    ds = getattr(oc, record_name, None)
    if ds is None:
        return None
    try:
        arr = ds.array
        if arr is None:
            return None
        if hasattr(arr, "dtype") and arr.dtype.names:
            return str(arr[0][arr.dtype.names[0]])
        flat = np.asarray(arr).reshape(-1)
        return str(flat[0]) if flat.size else None
    except Exception:
        return None


_HEAD_EXTENSIONS = (".hds", ".hed")
_BUDGET_EXTENSIONS = (".cbb", ".cbc", ".ccf")


def _resolve_declared_file(workspace: Path, declared: str | None) -> Path | None:
    """Resolve an OC-declared output path against the workspace.

    MODFLOW writes the file relative to the model working directory, so the
    declared record can carry a subdirectory (e.g.
    ``GWF_Model_output/GWF_Model.hds``); the old ``Path(declared).name``
    dropped that directory and failed to find the file. An absolute declared
    path is honoured as-is. Returns None when the declared file is absent (so
    the caller can fall back to a recursive glob).
    """
    if not declared:
        return None
    p = Path(declared)
    cand = p if p.is_absolute() else workspace / p
    return cand if cand.exists() else None


def _find_output_file(
    model: str, workspace: Path, extension: str, component: str = "gwf"
) -> tuple[Path, str | None]:
    """Return (path, warning) for the head output file.

    The file declared in the OC package's ``head_filerecord`` wins — resolved
    relative to the workspace so subdirectory output is found, and accepting
    the GMS ``.hed`` spelling as well as ``.hds``. Otherwise a recursive glob
    match is used. With several undeclared candidates a warning naming them all
    is returned (7e-B13).

    Raises
    ------
    FileNotFoundError
        If no matching file exists.
    """
    exts = _HEAD_EXTENSIONS if extension in _HEAD_EXTENSIONS else (extension,)
    value_keyword = (
        spec_for(component).oc_value_keyword if extension in _HEAD_EXTENSIONS else None
    )
    declared = (
        _oc_file_record(get_model(model, component), value_keyword)
        if value_keyword
        else None
    )
    declared_path = _resolve_declared_file(workspace, declared)
    if declared_path is not None:
        return declared_path, None

    matches: list[Path] = []
    for ext in exts:
        matches.extend(workspace.rglob(f"*{ext}"))
    if not matches:
        raise FileNotFoundError(
            f"No {'/'.join(exts)} file found in {workspace}. "
            "Run the simulation first with run_simulation."
        )
    if len(matches) > 1:
        return matches[0], (
            f"Multiple head files found; using {matches[0].name}. "
            f"Declared in OC: {declared or 'none'}. "
            f"Candidates: {[m.name for m in matches]}"
        )
    return matches[0], None


def _find_budget_file(
    model: str, workspace: Path, component: str = "gwf"
) -> tuple[Path, str | None]:
    """Locate the cell-by-cell budget file (.cbb/.cbc/.ccf).

    Prefers the OC ``budget_filerecord`` (resolved relative to the workspace,
    so subdirectory output is found, and accepting the GMS ``.ccf`` spelling);
    warns when several undeclared candidates exist (7e-B13).
    """
    declared = _oc_file_record(get_model(model, component), "budget_filerecord")
    declared_path = _resolve_declared_file(workspace, declared)
    if declared_path is not None:
        return declared_path, None

    matches: list[Path] = []
    for ext in _BUDGET_EXTENSIONS:
        matches.extend(workspace.rglob(f"*{ext}"))
    if not matches:
        raise FileNotFoundError(
            f"No .cbb/.cbc/.ccf budget file found in {workspace}. "
            "Run the simulation first with run_simulation."
        )
    if len(matches) > 1:
        return matches[0], (
            f"Multiple budget files found; using {matches[0].name}. "
            f"Declared in OC: {declared or 'none'}. "
            f"Candidates: {[m.name for m in matches]}"
        )
    return matches[0], None


def _open_budget_file(path: Path) -> fu.CellBudgetFile:
    """Open a MODFLOW 6 cell-by-cell budget file.

    MODFLOW 6 writes budget files in double precision. FloPy's ``precision
    = "auto"`` is supposed to fall back from single to double, but on Windows
    the single-precision read of a larger file raises ``OSError`` (``[Errno
    22]``, seek past end) instead of returning cleanly, so the fallback never
    runs. Retry explicitly with ``precision="double"`` on that error.
    """
    try:
        return fu.CellBudgetFile(str(path))
    except OSError:
        return fu.CellBudgetFile(str(path), precision="double")


def _csub_obs_csv_path(model: str) -> tuple[Path | None, str | None]:
    """Locate a model's CSUB observation output CSV.

    Prefers ``meta["csub"]["obs_output_csv"]`` (resolved against the
    workspace), then falls back to a recursive glob for ``*csub.obs.csv``
    (which matches ``<gwf>.csub.obs.csv``). With several undeclared candidates
    the first is used and a warning naming them all is returned.
    """
    meta = read_meta(model)
    declared = (meta.get("csub") or {}).get("obs_output_csv")
    ws = resolve_workspace(model)
    if declared:
        p = Path(declared)
        cand = p if p.is_absolute() else ws / p
        if cand.exists():
            return cand, None
    matches = sorted(ws.rglob("*csub.obs.csv"))
    if not matches:
        return None, None
    if len(matches) > 1:
        return matches[0], (
            f"Multiple CSUB observation CSVs found; using {matches[0].name}. "
            f"Declared in meta: {declared or 'none'}. "
            f"Candidates: {[m.name for m in matches]}"
        )
    return matches[0], None


# ---------------------------------------------------------------------------
# CSUB compaction helpers
# ---------------------------------------------------------------------------


def _compaction_column_layers(columns) -> list[tuple[str, int | None]]:
    """Return ``(column_name, layer_index)`` for CSUB layer-compaction columns.

    Matching is case-insensitive: a column counts when its name starts with
    ``compaction`` and is not an elastic/inelastic compaction or an interbed
    percentage column. The optional layer index is taken from the trailing
    digits of the name (``COMPACTION.01``, ``compaction01``, ``compaction-cell.2``
    all parse), so no particular number of layers or separator is assumed.
    """

    matched: list[tuple[str, int | None]] = []
    for col in columns:
        name = str(col).strip()
        low = name.lower()
        if low == "time":
            continue
        if "elastic" in low:  # covers ELASTIC- and INELASTIC-COMPACTION
            continue
        if not low.startswith("compaction"):
            continue
        digits = re.findall(r"\d+", low[len("compaction"):])
        matched.append((name, int(digits[-1]) if digits else None))
    return matched


def _read_strainib(model: str, ws: Path) -> list[dict] | None:
    """Read ``<gwf>.strainib.csv`` (interbed strain/percent compaction) when
    it exists. Prefers the CSUB ``filerecords.strainib`` path from meta, then
    a recursive glob. Returns None when no file is present."""
    import pandas as pd

    declared = ((read_meta(model).get("csub") or {}).get("filerecords") or {}).get(
        "strainib"
    )
    path: Path | None = None
    if declared:
        p = Path(declared)
        cand = p if p.is_absolute() else ws / p
        if cand.exists():
            path = cand
    if path is None:
        matches = sorted(ws.rglob("*strainib.csv"))
        if matches:
            path = matches[0]
    if path is None:
        return None
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    return [
        {str(k).strip().lower(): _scalar(v) for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]


def _impl_read_compaction(model: str, max_rows: int = 500) -> dict:
    """Read MF6 CSUB observation output into per-layer compaction and a
    derived cumulative subsidence series.

    The CSUB obs CSV (``<gwf>.csub.obs.csv``) carries one row per output time;
    layer compaction lives in the ``COMPACTION.<layer>`` columns (MF6
    upper-cases the registered observation names). ``subsidence`` is the
    per-time sum of those compaction columns only — the
    ``ELASTIC-``/``INELASTIC-COMPACTION`` and ``PRECONSTRESS`` columns are
    deliberately excluded. The full table is written to
    ``<model>_compaction.csv``; ``max_rows`` caps the inline lists. Returns an
    ``OUTPUT_FILE_MISSING`` envelope when no CSUB obs CSV exists.
    """
    import pandas as pd

    csv_path, warning = _csub_obs_csv_path(model)
    if csv_path is None:
        return _err(
            "OUTPUT_FILE_MISSING",
            "No CSUB observation output CSV (*csub.obs.csv) found for this model.",
            "Run add_csub_package with observations=... then run_simulation first.",
        )
    ws = resolve_workspace(model)
    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip() for c in df.columns]

    matched = _compaction_column_layers(df.columns)
    if not matched:
        return _err(
            "INVALID_INPUT",
            f"No layer compaction columns found in {csv_path.name}. "
            f"Columns: {[str(c) for c in df.columns]}",
            "Register compaction-cell observations with add_csub_package"
            "(observations={'compaction.01': [('compaction.01', "
            "'compaction-cell', (0, 0, 0))]}) then re-run.",
        )

    times = [float(v) for v in df["time"]] if "time" in df.columns else []
    compaction: dict[str, list[float]] = {}
    layers: list[int] = []
    for col, layer in matched:
        values = [float(v) for v in df[col]]
        compaction[str(layer) if layer is not None else col] = values
        if layer is not None and layer not in layers:
            layers.append(layer)
    layers.sort()

    n = len(df)
    subsidence = [
        float(sum(float(df[col].iloc[i]) for col, _ in matched)) for i in range(n)
    ]

    full = pd.DataFrame({"time": times}) if times else pd.DataFrame(index=range(n))
    for col, _ in matched:
        full[col] = [float(v) for v in df[col]]
    full["subsidence"] = subsidence
    compaction_csv = ws / f"{model}_compaction.csv"
    full.to_csv(compaction_csv, index=False)

    result: dict = {
        "model": model,
        "output_csv": str(csv_path),
        "compaction_csv": str(compaction_csv),
        "times": times[:max_rows],
        "layers": layers,
        "compaction": {k: v[:max_rows] for k, v in compaction.items()},
        "subsidence": subsidence[:max_rows],
        "interbed_strain": _read_strainib(model, ws),
        "n_rows": n,
        "truncated": n > max_rows,
    }
    if warning:
        result["warning"] = warning
    return result


# Model time unit -> days (mirrors calibration._TIME_UNIT_DAYS) so a dated
# observed series can be placed on the simulated elapsed-time axis.
_TIME_UNIT_DAYS = {
    "SECONDS": 1.0 / 86400.0,
    "MINUTES": 1.0 / 1440.0,
    "HOURS": 1.0 / 24.0,
    "DAYS": 1.0,
    "YEARS": 365.0,
}


def _observed_subsidence_series(
    csv_path: Path,
    *,
    start_date_time=None,
    time_units: str = "DAYS",
) -> tuple[list[float], list[float], str]:
    """Return ``(x, y, axis)`` from an observed subsidence CSV.

    The value column is ``Subsidence_ft`` case-insensitively when present,
    else the first numeric column that is not the time column. The time column
    is ``time``/``datetime``/``date`` case-insensitively, else the first column
    (which catches pandas' unnamed index, e.g. ``Unnamed: 0``).

    ``x`` is placed on the **model time axis** so the overlay lines up with the
    simulated series: a numeric time column is already elapsed model time;
    parseable calendar dates are converted to elapsed time via
    ``start_date_time`` in the model's ``time_units``. With neither, ``x`` falls
    back to the row index and ``axis`` reports ``"row-index"`` (the 6d Target 9
    rerun-7 overlay defect: dates silently became ``0..N-1`` and collapsed into
    the corner of a 0–57346-day axis). Raises ``ValueError`` when no numeric
    value column can be identified or the chosen column holds non-numeric
    values.
    """
    import pandas as pd

    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip() for c in df.columns]
    lower = {str(c).lower(): str(c) for c in df.columns}

    time_col = next(
        (lower[k] for k in ("time", "datetime", "date") if k in lower), None
    )
    if time_col is None and len(df.columns) > 1:
        time_col = str(df.columns[0])
    value_col = lower.get("subsidence_ft")
    if value_col is None:
        for col in df.columns:
            if col == time_col:
                continue
            if pd.to_numeric(df[col], errors="coerce").notna().any():
                value_col = str(col)
                break
    if value_col is None:
        raise ValueError(
            f"No numeric subsidence column found in {csv_path.name}. "
            f"Columns: {[str(c) for c in df.columns]}"
        )

    values = pd.to_numeric(df[value_col], errors="coerce")
    if values.isna().any():
        raise ValueError(
            f"Observed subsidence column {value_col!r} contains non-numeric "
            f"values in {csv_path.name}."
        )

    x: list[float] | None = None
    axis = "row-index"
    if time_col is not None:
        numeric_x = pd.to_numeric(df[time_col], errors="coerce")
        if bool(numeric_x.notna().all()):
            x = [float(v) for v in numeric_x]
            axis = "model-time"
        else:
            dates = pd.to_datetime(df[time_col], errors="coerce")
            anchor = (
                pd.to_datetime(str(start_date_time), errors="coerce")
                if start_date_time
                else pd.NaT
            )
            if pd.notna(anchor) and bool(dates.notna().all()):
                days_per_unit = _TIME_UNIT_DAYS.get(str(time_units).upper(), 1.0)
                x = [
                    (stamp - anchor).total_seconds() / 86400.0 / days_per_unit
                    for stamp in dates
                ]
                axis = "model-time"
    if x is None:
        x = [float(i) for i in range(len(df))]
    return x, [float(v) for v in values], axis


def _impl_plot_subsidence(
    model: str,
    observed_csv: str | None = None,
    output_file: str | None = None,
) -> dict:
    """Plot simulated cumulative subsidence against time and save as PNG.

    Consumes ``_impl_read_compaction`` and propagates its error envelope
    unchanged (e.g. ``OUTPUT_FILE_MISSING`` when no CSUB obs CSV exists).
    ``observed_csv`` optionally overlays a measured series, auto-detecting its
    value column (``Subsidence_ft`` case-insensitively preferred, else the
    first numeric non-time column).
    """
    from groundwater_mcp.utils.plotting import figure, save_figure

    result = _impl_read_compaction(model)
    if result.get("error"):
        return result

    ws = resolve_workspace(model)
    times = [float(v) for v in result.get("times", [])]
    subsidence = [float(v) for v in result.get("subsidence", [])]
    x_sim = times if times else [float(i) for i in range(len(subsidence))]

    observed_x: list[float] | None = None
    observed_y: list[float] | None = None
    observed_axis: str | None = None
    obs_path: str | None = None
    if observed_csv:
        p = Path(observed_csv)
        cand = p if p.is_absolute() else ws / p
        if not cand.exists():
            return _err(
                "OUTPUT_FILE_MISSING",
                f"Observed subsidence CSV not found: {cand}",
                "Pass observed_csv as a two-column time,subsidence CSV.",
            )
        try:
            observed_x, observed_y, observed_axis = _observed_subsidence_series(
                cand,
                start_date_time=read_meta(model).get("start_date_time"),
                time_units=str(read_meta(model).get("time_units") or "DAYS"),
            )
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        obs_path = str(cand)

    with figure(figsize=(9, 5)) as fig:
        ax = fig.add_subplot(1, 1, 1)
        ax.plot(x_sim, subsidence, marker="o", color="tab:blue", label="Simulated")
        if observed_x is not None and observed_y is not None:
            ax.plot(
                observed_x,
                observed_y,
                marker="s",
                linestyle="--",
                color="tab:red",
                label="Observed",
            )
            ax.legend()
        ax.set_xlabel("Elapsed time (model time units)")
        ax.set_ylabel("Cumulative subsidence")
        ax.set_title(f"{model} — cumulative subsidence")
        target = _resolve_output_path(ws, output_file, "") if output_file else None
        out_path = save_figure(fig, target, ws)

    return {
        "model": model,
        "output_file": out_path,
        "n_times": len(subsidence),
        "has_observed": observed_x is not None,
        "observed_csv": obs_path,
        "observed_axis": observed_axis,
    }


# ---------------------------------------------------------------------------
# Array stats helper
# ---------------------------------------------------------------------------


def _array_stats(arr: np.ndarray) -> dict:
    """Return min/max/mean for a numeric array, ignoring no-data values.

    MODFLOW 6 writes ``1e30`` for inactive cells and ``-1e30`` for dry
    convertible cells; both are masked via ``abs(v) >= 1e20`` (7e-B14 — the
    old ``arr != 1e30`` filter let the -1e30 sentinel wreck min/mean).
    """
    data = arr[np.abs(arr) < 1e20]
    if data.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(np.nanmin(data)),
        "max": float(np.nanmax(data)),
        "mean": float(np.nanmean(data)),
    }


def _model_nlay(model: str) -> int:
    """Return the number of layers declared by the model's grid (0 if unknown)."""
    gwf = get_gwf(model)
    dis = get_dis(gwf)
    if dis is not None:
        return int(dis.nlay.data)
    disv = get_disv(gwf)
    if disv is not None:
        return int(disv.nlay.data)
    if get_disu(gwf) is not None:
        return 1
    return 0


def _validate_layer(model: str, layer: int) -> None:
    """Reject layer indices outside the model's layer range (7f-D3)."""
    nlay = _model_nlay(model)
    if nlay > 0 and not (0 <= layer < nlay):
        raise ValueError(
            f"layer {layer} out of range: model has nlay={nlay} (valid: 0..{nlay - 1})."
        )


# ---------------------------------------------------------------------------
# Observation targets — the closed observation loop (7f-F)
# ---------------------------------------------------------------------------


def _registered_observations(model: str) -> dict | None:
    """Return the persisted observation targets (7f-F1.1), or None."""
    obs = read_meta(model).get("observations")
    if obs and obs.get("sites"):
        return obs
    return None


def _read_simulated_observations_values(model: str) -> tuple[dict[str, float], Path, float | None]:
    """Parse the MF6 continuous OBS CSV and return the simulated values.

    Returns
    -------
    ``(sim_values, csv_path, last_time)`` where ``sim_values`` maps each
    registered site name to its simulated value at the final output time.

    Raises
    ------
    FileNotFoundError
        When no registered observations exist or the obs CSV has not been
        written yet (i.e. ``run_simulation`` has not run).
    """
    obs = _registered_observations(model)
    if obs is None:
        raise FileNotFoundError(
            "No observation targets are registered for this model. "
            "Run import_obs_from_csv first."
        )
    import pandas as pd

    ws = resolve_workspace(model)
    csv_path = ws / obs["output_csv"]
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No observation output CSV found at {csv_path}. "
            "Run the simulation first with run_simulation."
        )
    df = pd.read_csv(csv_path)
    sim: dict[str, float] = {}
    last_time: float | None = None
    if "time" in df.columns and len(df) > 0:
        last_time = float(df["time"].iloc[-1])
    if len(df) > 0:
        # MODFLOW uppercases observation names in the continuous obs CSV, so
        # match the registered site names case-insensitively (modeB rerun-5).
        col_lookup = {str(col).lower(): str(col) for col in df.columns}
        for entry in obs["sites"]:
            site = str(entry["site"])
            col = site if site in df.columns else col_lookup.get(site.lower())
            if col is not None:
                sim[site] = float(df[col].iloc[-1])
    return sim, csv_path, last_time


def _compute_obs_fit(model: str) -> dict | None:
    """Return observation-fit statistics, or None when no targets are
    registered or the run has not produced the obs CSV yet (7f-F1.3/F1.4).

    Per site: observed = mean of the registered observed values; simulated =
    the value in the model's obs CSV at the final output time. The comparison
    is steady-state-appropriate; for transient models it compares each site's
    mean observation against the final-time simulated value.
    """
    obs = _registered_observations(model)
    if obs is None:
        return None
    try:
        sim, csv_path, last_time = _read_simulated_observations_values(model)
    except FileNotFoundError:
        return None

    rows: list[dict] = []
    for entry in obs["sites"]:
        site = str(entry["site"])
        values = [float(v) for v in entry.get("values", [])]
        if not values or site not in sim:
            continue
        rows.append({
            "site": site,
            "observed": float(np.mean(values)),
            "simulated": sim[site],
        })
    if not rows:
        return None

    observed = np.array([r["observed"] for r in rows])
    simulated = np.array([r["simulated"] for r in rows])
    residual = observed - simulated
    n = int(len(rows))
    rmse = float(np.sqrt(np.mean(residual**2)))
    bias = float(np.mean(residual))
    mae = float(np.mean(np.abs(residual)))
    ss_tot = float(np.sum((observed - observed.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / ss_tot if ss_tot > 0 else None

    worst_idx = np.argsort(np.abs(residual))[::-1][:5]
    worst = [
        {"site": rows[i]["site"], "residual": float(residual[i])}
        for i in worst_idx
    ]
    return {
        "n": n,
        "rmse": rmse,
        "bias": bias,
        "mae": mae,
        "r2": r2,
        "obs_csv": str(csv_path),
        "time": last_time,
        "worst_sites": worst,
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _impl_read_heads(
    model: str,
    kstpkper: tuple[int, int] | None = None,
    layer: int = 0,
    include_values: bool = False,
    max_cells: int = 10000,
    row_slice: list[int] | None = None,
    col_slice: list[int] | None = None,
    decimate: int | None = None,
) -> dict:
    """Read head values from the binary .hds output file.

    By default returns statistics plus an ``output_file`` (a ``.npy`` of the
    layer array in the workspace) instead of the full array, keeping the
    response small on regional grids (7e-A1). ``include_values=True`` returns
    the raw values when the cell count is within ``max_cells`` (else
    PAYLOAD_TOO_LARGE). ``row_slice``/``col_slice`` (``[start, stop]``) and
    ``decimate`` subset the array before any of the above.
    """
    _validate_layer(model, layer)
    ws = resolve_workspace(model)
    hds_path, warning = _find_output_file(model, ws, ".hds")

    hf = fu.HeadFile(str(hds_path))
    kstpkper_list = hf.get_kstpkper()

    if not kstpkper_list:
        raise ValueError("Head file contains no data.")

    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    if target not in kstpkper_list:
        raise ValueError(
            f"kstpkper {target} not found. Available: {kstpkper_list}"
        )

    heads = hf.get_data(kstpkper=target)  # shape: (nlay, nrow, ncol)
    layer_heads = heads[layer]

    if row_slice is not None:
        layer_heads = layer_heads[slice(*row_slice), :]
    if col_slice is not None:
        layer_heads = layer_heads[:, slice(*col_slice)]
    if decimate and decimate > 1:
        layer_heads = layer_heads[::decimate, ::decimate]

    stats = _array_stats(layer_heads)
    n_active = int(np.sum(np.abs(layer_heads) < 1e20))

    result: dict = {
        "model": model,
        "kstpkper": [int(v) for v in target],
        "layer": layer,
        "shape": list(layer_heads.shape),
        "n_active": n_active,
        **stats,
    }
    if warning:
        result["warning"] = warning

    # Always write the array to a .npy so large grids can be pulled from disk.
    npy_path = ws / f"{model}_heads_l{layer}_k{target[0]}_{target[1]}.npy"
    np.save(npy_path, layer_heads)
    result["output_file"] = str(npy_path)

    if include_values:
        n_cells = layer_heads.size
        if n_cells > max_cells:
            return _err(
                "PAYLOAD_TOO_LARGE",
                f"{n_cells} cells exceed max_cells={max_cells}.",
                "Use include_values=False and load the array from output_file "
                "(.npy), or subset/decimate first.",
            )
        result["values"] = layer_heads.tolist()
    return result


def _impl_read_budget(
    model: str,
    text: str | None = None,
    kstpkper: tuple[int, int] | None = None,
    max_records: int = 1000,
) -> dict:
    """Read cell budget records from the binary .cbb output file.

    Returns per-record-type aggregates plus a bounded ``records`` list
    (``max_records``, default 1000). When the full record set exceeds the cap
    the complete table is written to ``<model>_budget_records.csv`` (7e-A1).
    """
    import pandas as pd

    ws = resolve_workspace(model)
    cbb_path, warning = _find_budget_file(model, ws)

    cbf = _open_budget_file(cbb_path)
    kstpkper_list = cbf.get_kstpkper()

    if not kstpkper_list:
        raise ValueError("Budget file contains no data.")

    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]

    unique_texts = cbf.get_unique_record_names(decode=True)

    def _label(t) -> str:
        return t.decode().strip().upper() if isinstance(t, bytes) else t.strip().upper()

    if text is not None:
        text_upper = text.strip().upper()
        matched = next((t for t in unique_texts if text_upper in _label(t)), None)
        if matched is None:
            available = [
                (t.decode().strip() if isinstance(t, bytes) else t.strip())
                for t in unique_texts
            ]
            raise ValueError(
                f"Budget text label '{text}' not found. Available: {available}"
            )
        selected = [matched]
    else:
        selected = list(unique_texts)

    records: list[dict] = []
    aggregates: dict[str, dict] = {}
    for name in selected:
        label = _label(name)
        records_raw = cbf.get_data(kstpkper=target, text=name)
        per_type: list[dict] = []
        for rec in records_raw:
            if hasattr(rec, "dtype") and rec.dtype.names:
                for row in rec:
                    entry = {n: _scalar(row[n]) for n in rec.dtype.names}
                    per_type.append(entry)
            else:
                arr = np.asarray(rec, dtype=float)
                per_type.append({"values_stats": _array_stats(arr)})
        agg_sum = sum(
            next((v for v in e.values() if isinstance(v, (int, float))), 0.0)
            for e in per_type
        )
        aggregates[label] = {"record_count": len(per_type), "sum_first_column": agg_sum}
        for entry in per_type:
            entry.setdefault("record_type", label)
        records.extend(per_type)

    total = len(records)
    result: dict = {
        "model": model,
        "kstpkper": [int(v) for v in target],
        "text_filter": text,
        "record_count": total,
        "aggregates": aggregates,
    }
    if warning:
        result["warning"] = warning
    if total > max_records:
        csv_path = ws / f"{model}_budget_records.csv"
        pd.DataFrame(records).to_csv(csv_path, index=False)
        result["records"] = records[:max_records]
        result["records_csv"] = str(csv_path)
        result["records_truncated"] = True
    else:
        result["records"] = records
        result["records_truncated"] = False
    return result


def _scalar(val) -> float | int | str:
    """Convert a numpy scalar to a Python native type."""
    try:
        if np.issubdtype(type(val), np.integer):
            return int(val)
        if np.issubdtype(type(val), np.floating):
            return float(val)
        if isinstance(val, bytes):
            return val.decode().strip()
        return str(val)
    except Exception:
        return str(val)


def _impl_compute_drawdown(
    model: str,
    kstpkper_initial: tuple[int, int],
    kstpkper_final: tuple[int, int],
    layer: int = 0,
    include_values: bool = False,
    max_cells: int = 10000,
) -> dict:
    """Compute drawdown as the difference in heads between two time steps.

    Returns statistics plus an ``output_file`` (``.npy``) instead of the full
    array by default; ``include_values=True`` returns raw values within
    ``max_cells`` (7e-A1.4).
    """
    _validate_layer(model, layer)
    ws = resolve_workspace(model)
    hds_path, warning = _find_output_file(model, ws, ".hds")

    hf = fu.HeadFile(str(hds_path))
    h_initial = hf.get_data(kstpkper=tuple(kstpkper_initial))[layer]
    h_final = hf.get_data(kstpkper=tuple(kstpkper_final))[layer]

    # drawdown = initial - final (positive = head declined)
    drawdown = h_initial - h_final
    # Mask no-data cells (inactive 1e30 / dry -1e30 sentinels)
    nodata = (np.abs(h_initial) >= 1e20) | (np.abs(h_final) >= 1e20)
    drawdown[nodata] = 1e30

    npy_path = ws / f"{model}_drawdown_l{layer}.npy"
    np.save(npy_path, drawdown)

    result: dict = {
        "model": model,
        "kstpkper_initial": list(kstpkper_initial),
        "kstpkper_final": list(kstpkper_final),
        "layer": layer,
        "shape": list(drawdown.shape),
        "output_file": str(npy_path),
        **_array_stats(drawdown),
    }
    if warning:
        result["warning"] = warning
    if include_values:
        if drawdown.size > max_cells:
            return _err(
                "PAYLOAD_TOO_LARGE",
                f"{drawdown.size} cells exceed max_cells={max_cells}.",
                "Use include_values=False and load output_file, or subset first.",
            )
        result["values"] = drawdown.tolist()
    return result


def _impl_compute_water_balance(
    model: str,
    kstpkper: tuple[int, int] | None = None,
) -> dict:
    """Aggregate budget by boundary type and compute net water balance."""
    ws = resolve_workspace(model)
    cbb_path, warning = _find_budget_file(model, ws)

    cbf = _open_budget_file(cbb_path)
    kstpkper_list = cbf.get_kstpkper()

    if not kstpkper_list:
        raise ValueError("Budget file contains no data.")

    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    unique_texts = cbf.get_unique_record_names(decode=True)

    inflow: dict[str, float] = {}
    outflow: dict[str, float] = {}

    for text_raw in unique_texts:
        label = (text_raw.decode().strip() if isinstance(text_raw, bytes) else text_raw.strip())
        if "FLOW-JA-FACE" in label.upper():
            continue  # internal cell-to-cell flow, not a boundary flux
        try:
            records = cbf.get_data(kstpkper=target, text=text_raw)
        except Exception:
            continue

        in_amt = 0.0
        out_amt = 0.0
        for rec in records:
            arr = np.asarray(rec)
            if arr.dtype.names and "q" in arr.dtype.names:
                q = arr["q"].astype(float)
                in_amt += float(q[q > 0].sum())
                out_amt += float(q[q < 0].sum())
            elif arr.dtype.names:
                # Structured record without a recognised flow field — skip
                pass
            else:
                vals = arr.astype(float).ravel()
                vals = vals[np.abs(vals) < 1e20]
                in_amt += float(vals[vals > 0].sum()) if vals.size > 0 else 0.0
                out_amt += float(vals[vals < 0].sum()) if vals.size > 0 else 0.0

        if in_amt:
            inflow[label] = in_amt
        if out_amt:
            outflow[label] = out_amt

    total_in = sum(inflow.values())
    total_out = sum(outflow.values())
    net = total_in + total_out  # outflow is negative

    return {
        "model": model,
        "kstpkper": list(target),
        "inflow": inflow,
        "outflow": outflow,
        "total_inflow": total_in,
        "total_outflow": total_out,
        "net_balance": net,
        **({"warning": warning} if warning else {}),
    }


def _impl_diagnose_water_balance(
    model: str,
    kstpkper: tuple[int, int] | None = None,
    tolerance_pct: float = 1.0,
    dominance_threshold: float = 0.5,
) -> dict:
    """Diagnose the water balance instead of leaving the modeller to eyeball
    ``compute_water_balance``'s inflow/outflow table (7e-C3).

    Computes the same percent-discrepancy MODFLOW itself reports
    (``100 * (IN - OUT) / ((IN + OUT) / 2)``), names the single largest
    inflow and outflow term, and flags when one boundary type accounts for
    more than ``dominance_threshold`` of all flow through the model (a common
    modelling smell — e.g. the water balance is only closing because a CHD
    boundary is absorbing everything).
    """
    wb = _impl_compute_water_balance(model, kstpkper)

    inflow: dict[str, float] = wb["inflow"]
    outflow: dict[str, float] = wb["outflow"]
    total_in = float(wb["total_inflow"])
    total_out_abs = abs(float(wb["total_outflow"]))
    net = float(wb["net_balance"])

    avg = (total_in + total_out_abs) / 2.0
    percent_discrepancy = (100.0 * net / avg) if avg > 0 else 0.0
    balanced = abs(percent_discrepancy) < tolerance_pct

    dominant_inflow_term = max(inflow, key=lambda k: inflow[k]) if inflow else None
    dominant_outflow_term = min(outflow, key=lambda k: outflow[k]) if outflow else None

    labels = set(inflow) | set(outflow)
    total_magnitude = total_in + total_out_abs
    dominant_term = None
    dominant_term_share = None
    boundary_dominated = False
    if labels and total_magnitude > 0:
        magnitudes = {
            label: abs(inflow.get(label, 0.0)) + abs(outflow.get(label, 0.0))
            for label in labels
        }
        dominant_term = max(magnitudes, key=lambda k: magnitudes[k])
        dominant_term_share = magnitudes[dominant_term] / total_magnitude
        boundary_dominated = dominant_term_share > dominance_threshold

    result: dict = {
        "model": model,
        "kstpkper": wb["kstpkper"],
        "total_inflow": total_in,
        "total_outflow": wb["total_outflow"],
        "net_balance": net,
        "percent_discrepancy": percent_discrepancy,
        "tolerance_pct": tolerance_pct,
        "balanced": balanced,
        "dominant_inflow_term": dominant_inflow_term,
        "dominant_outflow_term": dominant_outflow_term,
        "dominant_term": dominant_term,
        "dominant_term_share": dominant_term_share,
        "boundary_dominated": boundary_dominated,
    }
    if "warning" in wb:
        result["warning"] = wb["warning"]
    return result


# ---------------------------------------------------------------------------
# GIS/table export tools (7e-C5) — the deliverable for a working
# hydrogeologist is a GeoTIFF and a table, not a base64 PNG or a raw MCP
# response.
# ---------------------------------------------------------------------------


def _resolve_output_path(ws: Path, output_file: str | None, default_name: str) -> Path:
    """Resolve an optional output path against the model workspace.

    A relative ``output_file`` resolves against the workspace (not the
    server process's CWD); an absolute path is used as-is; ``None`` uses
    ``default_name`` inside the workspace.
    """
    p = Path(output_file) if output_file else Path(default_name)
    return p if p.is_absolute() else ws / p


def _require_dis_and_crs(gwf):
    """Return (dis, modelgrid), raising when the grid isn't a georeferenceable
    structured DIS grid — shared by the export tools (7e-C5)."""
    from groundwater_mcp.utils.spatial import CRSError

    dis = get_dis(gwf)
    if dis is None:
        raise ValueError(
            "This export requires a structured DIS grid (DISV/DISU are not supported)."
        )
    modelgrid = gwf.modelgrid
    if modelgrid.crs is None:
        raise CRSError(
            "Model grid has no CRS — set one with set_model_crs before exporting "
            "georeferenced output."
        )
    return dis, modelgrid


def _impl_export_heads_to_raster(
    model: str,
    layer: int = 0,
    kstpkper: tuple[int, int] | None = None,
    output_file: str | None = None,
) -> dict:
    """Write a layer of simulated heads to a georeferenced GeoTIFF (7e-C5.1).

    Delegates the actual georeferencing (affine transform, rotation, CRS) to
    flopy's own ``export_array``, which is already tested against rasterio —
    this just prepares the 2D array (masking MF6's inactive/dry sentinels to
    NaN) and resolves the output path.
    """
    import flopy.export.utils as export_utils

    _validate_layer(model, layer)
    gwf = get_gwf(model)
    _dis, modelgrid = _require_dis_and_crs(gwf)
    ws = resolve_workspace(model)
    hds_path, warning = _find_output_file(model, ws, ".hds")

    hf = fu.HeadFile(str(hds_path))
    kstpkper_list = hf.get_kstpkper()
    if not kstpkper_list:
        raise ValueError("Head file contains no data.")
    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    if target not in kstpkper_list:
        raise ValueError(f"kstpkper {target} not found. Available: {kstpkper_list}")

    layer_heads = np.array(hf.get_data(kstpkper=target)[layer], dtype=float)
    layer_heads[np.abs(layer_heads) >= 1e20] = np.nan

    out_path = _resolve_output_path(ws, output_file, f"{model}_heads_l{layer}.tif")
    export_utils.export_array(modelgrid, str(out_path), layer_heads, nodata=-9999.0)

    result: dict = {
        "model": model,
        "layer": layer,
        "kstpkper": [int(v) for v in target],
        "output_file": str(out_path),
        "crs": str(modelgrid.crs),
    }
    if warning:
        result["warning"] = warning
    return result


def _impl_export_boundaries_to_shapefile(model: str, output_file: str | None = None) -> dict:
    """Write every list-based boundary package's stress-period cells to a
    shapefile — one feature per (package, stress period, cell) (7e-C5.2).

    Array-based packages (RCHA/EVTA) apply everywhere by construction and are
    skipped, as are packages whose ``stress_period_data`` has no ``cellid``
    field (e.g. SFR, reach-indexed).
    """
    import geopandas as gpd
    from shapely.geometry import box

    from groundwater_mcp.tools.builder import (
        _ARRAY_BOUNDARY_PKGS,
        _BOUNDARY_PKG_CLASSES,
        _packages_of_type,
    )

    gwf = get_gwf(model)
    _dis, modelgrid = _require_dis_and_crs(gwf)
    ws = resolve_workspace(model)
    xv, yv = modelgrid.xvertices, modelgrid.yvertices

    features: list[dict] = []
    for pkg_name in _BOUNDARY_PKG_CLASSES:
        if pkg_name in _ARRAY_BOUNDARY_PKGS:
            continue
        for pkg in _packages_of_type(gwf, pkg_name):
            spd_attr = getattr(pkg, "stress_period_data", None)
            if spd_attr is None:
                continue
            try:
                data = spd_attr.get_data()
            except Exception:
                continue
            if not data:
                continue
            for kper, rec in data.items():
                if rec is None or "cellid" not in (rec.dtype.names or ()):
                    continue
                for row in rec:
                    try:
                        lay, r, c = (int(i) for i in row["cellid"])
                    except Exception:
                        continue
                    geom = box(
                        float(xv[r, c]), float(yv[r + 1, c + 1]),
                        float(xv[r + 1, c + 1]), float(yv[r, c]),
                    )
                    entry: dict = {
                        "package": pkg_name,
                        "kper": int(kper),
                        "layer": lay,
                        "row": r,
                        "col": c,
                        "geometry": geom,
                    }
                    for field in rec.dtype.names or ():
                        if field != "cellid":
                            entry[field] = _scalar(row[field])
                    features.append(entry)

    if not features:
        raise ValueError(
            "No list-based boundary packages with stress-period data found on this model."
        )

    gdf = gpd.GeoDataFrame(features, crs=modelgrid.crs)
    out_path = _resolve_output_path(ws, output_file, f"{model}_boundaries.shp")
    gdf.to_file(str(out_path))

    return {
        "model": model,
        "output_file": str(out_path),
        "feature_count": len(features),
        "packages": sorted({f["package"] for f in features}),
        "crs": str(modelgrid.crs),
    }


def _impl_export_water_balance_csv(
    model: str,
    kstpkper: tuple[int, int] | None = None,
    output_file: str | None = None,
) -> dict:
    """Write compute_water_balance's inflow/outflow table to a CSV (7e-C5.2),
    one row per boundary type plus a TOTAL row, columns matching
    compute_water_balance's own keys (inflow/outflow/net)."""
    import pandas as pd

    wb = _impl_compute_water_balance(model, kstpkper)
    ws = resolve_workspace(model)

    labels = sorted(set(wb["inflow"]) | set(wb["outflow"]))
    rows = [
        {
            "boundary_type": label,
            "inflow": wb["inflow"].get(label, 0.0),
            "outflow": wb["outflow"].get(label, 0.0),
            "net": wb["inflow"].get(label, 0.0) + wb["outflow"].get(label, 0.0),
        }
        for label in labels
    ]
    rows.append({
        "boundary_type": "TOTAL",
        "inflow": wb["total_inflow"],
        "outflow": wb["total_outflow"],
        "net": wb["net_balance"],
    })

    out_path = _resolve_output_path(ws, output_file, f"{model}_water_balance.csv")
    pd.DataFrame(rows).to_csv(str(out_path), index=False)

    result: dict = {
        "model": model,
        "kstpkper": wb["kstpkper"],
        "output_file": str(out_path),
        "row_count": len(rows),
    }
    if "warning" in wb:
        result["warning"] = wb["warning"]
    return result


def _impl_plot_heads_map(
    model: str,
    layer: int = 0,
    kstpkper: tuple[int, int] | None = None,
    contour_intervals: int = 10,
    output_file: str | None = None,
) -> dict:
    """Plot a plan-view head contour map and save as PNG."""
    import flopy.plot as fplot

    from groundwater_mcp.utils.plotting import figure, save_figure

    _validate_layer(model, layer)
    ws = resolve_workspace(model)
    gwf = get_gwf(model)

    # A DISU grid defined without vertices has no cell x/y, so plan-view
    # plotting is impossible — fail with a clear message, not a bare TypeError.
    from groundwater_mcp.utils.spatial import grid_centroids

    try:
        grid_centroids(gwf.modelgrid)
    except ValueError as exc:
        raise ValueError(
            "plot_heads_map requires cell x/y geometry, which this "
            "discretisation does not carry (a DISU grid defined without "
            "vertices). Use read_heads or compute_water_balance instead."
        ) from exc

    hds_path, warning = _find_output_file(model, ws, ".hds")

    hf = fu.HeadFile(str(hds_path))
    kstpkper_list = hf.get_kstpkper()
    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    heads = hf.get_data(kstpkper=target)

    with figure() as fig:
        ax = fig.add_subplot(1, 1, 1)
        head_layer = np.asarray(heads[layer])
        disu = get_disu(gwf)
        if disu is not None:
            # FloPy's PlotMapView layer helpers derive nlay=nnodes for some
            # DISU grids (e.g. the Neckartal set → nlay 31831, ncpl [1,…]), so
            # contour_array gets a single centroid and cannot triangulate.
            # Plot directly from the cell centroids + node heads instead.
            from matplotlib import tri as mtri

            xc, yc = grid_centroids(gwf.modelgrid)
            h = head_layer.ravel()
            valid_mask = np.isfinite(h) & (np.abs(h) < 1e20)
            x, y, v = xc[valid_mask], yc[valid_mask], h[valid_mask]
            if v.size >= 3:
                triang = mtri.Triangulation(x, y)
                levels = np.linspace(float(v.min()), float(v.max()), contour_intervals + 1)
                cf = ax.tricontourf(triang, v, levels=levels, cmap="viridis", alpha=0.85)
                ax.tricontour(triang, v, levels=levels, colors="navy", linewidths=0.8)
                fig.colorbar(cf, ax=ax, label="Head")
            else:
                sc = ax.scatter(x, y, c=v, cmap="viridis", s=20)
                fig.colorbar(sc, ax=ax, label="Head")
            ax.set_aspect("equal")
            ax.set_title(f"{model} — heads layer {layer}, kstpkper {target}")
            ax.set_xlabel("X")
            ax.set_ylabel("Y")
        else:
            pmv = fplot.PlotMapView(model=gwf, layer=layer, ax=ax)
            pmv.plot_grid(alpha=0.3, lw=0.4)
            valid = head_layer[np.abs(head_layer) < 1e20]
            if valid.size > 1:
                levels = np.linspace(valid.min(), valid.max(), contour_intervals + 1)
                pmv.contour_array(head_layer, levels=levels, colors="navy", linewidths=0.8)
            pmv.plot_array(head_layer, alpha=0.6, cmap="viridis")
            ax.set_title(f"{model} — heads layer {layer}, kstpkper {target}")
            ax.set_xlabel("Column")
            ax.set_ylabel("Row")
        out_path = save_figure(fig, output_file, ws)

    return {
        "model": model,
        "layer": layer,
        "kstpkper": list(target),
        "output_file": out_path,
        **({"warning": warning} if warning else {}),
    }


def _impl_plot_cross_section(
    model: str,
    line: dict,
    kstpkper: tuple[int, int] | None = None,
    output_file: str | None = None,
) -> dict:
    """Plot a cross-section of heads along a given line and save as PNG."""
    import flopy.plot as fplot

    from groundwater_mcp.utils.plotting import figure, save_figure

    ws = resolve_workspace(model)
    hds_path, warning = _find_output_file(model, ws, ".hds")
    gwf = get_gwf(model)

    hf = fu.HeadFile(str(hds_path))
    kstpkper_list = hf.get_kstpkper()
    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    heads = hf.get_data(kstpkper=target)

    with figure() as fig:
        ax = fig.add_subplot(1, 1, 1)
        xc = fplot.PlotCrossSection(model=gwf, line=line, ax=ax)
        xc.plot_grid(alpha=0.3, lw=0.4)
        xc.plot_array(heads, alpha=0.6, cmap="viridis")
        xc.contour_array(heads, colors="navy", linewidths=0.8)
        xc.plot_ibound()
        ax.set_title(f"{model} — cross-section, kstpkper {target}")
        ax.set_xlabel("Distance")
        ax.set_ylabel("Elevation")
        out_path = save_figure(fig, output_file, ws)

    return {
        "model": model,
        "line": line,
        "kstpkper": list(target),
        "output_file": out_path,
        **({"warning": warning} if warning else {}),
    }


def _impl_read_simulated_observations(model: str) -> dict:
    """Read the simulated values the model wrote for the registered
    observation targets (7f-F1.2)."""
    obs = _registered_observations(model)
    if obs is None:
        return _err(
            "MODEL_HAS_NO_OBSERVATIONS",
            "No observation targets are registered for this model.",
            "Run import_obs_from_csv first to register sites.",
        )
    try:
        sim, csv_path, last_time = _read_simulated_observations_values(model)
    except FileNotFoundError as exc:
        return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
    return {
        "model": model,
        "obs_type": obs.get("type"),
        "obs_csv": str(csv_path),
        "time": last_time,
        "sites": sim,
    }


def _impl_compare_to_observed(model: str, output_file: str | None = None) -> dict:
    """Compare the registered observed values against the simulated heads,
    with no PEST setup at all (7f-F1.3)."""
    import pandas as pd

    from groundwater_mcp.utils.plotting import figure, save_figure

    obs = _registered_observations(model)
    if obs is None:
        return _err(
            "MODEL_HAS_NO_OBSERVATIONS",
            "No observation targets are registered for this model.",
            "Run import_obs_from_csv first to register sites.",
        )
    try:
        sim, csv_path, last_time = _read_simulated_observations_values(model)
    except FileNotFoundError as exc:
        return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
    if not sim:
        raise FileNotFoundError(
            f"None of the registered sites appear in the observation CSV {csv_path}."
        )

    ws = resolve_workspace(model)
    rows: list[dict] = []
    for entry in obs["sites"]:
        site = str(entry["site"])
        values = [float(v) for v in entry.get("values", [])]
        if not values or site not in sim:
            continue
        obs_val = float(np.mean(values))
        rows.append({
            "site": site,
            "observed": obs_val,
            "simulated": sim[site],
            "residual": obs_val - sim[site],
        })
    rows.sort(key=lambda r: abs(r["residual"]), reverse=True)

    obs_arr = np.array([r["observed"] for r in rows])
    sim_arr = np.array([r["simulated"] for r in rows])
    residual_arr = obs_arr - sim_arr
    n = len(rows)
    ss_tot = float(np.sum((obs_arr - obs_arr.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual_arr**2)) / ss_tot if ss_tot > 0 else None

    # Per-site residual table (capped; full table always written to CSV)
    cap = 500
    residuals = [
        {"site": r["site"], "observed": r["observed"],
         "simulated": r["simulated"], "residual": r["residual"]}
        for r in rows
    ]
    residuals_csv = ws / f"{model}_obs_residuals.csv"
    pd.DataFrame(residuals).to_csv(residuals_csv, index=False)

    # Scatter plot: observed vs simulated with a 1:1 reference line
    plot_path = ws / (output_file or f"{model}_obs_fit.png")
    with figure() as fig:
        ax = fig.add_subplot(1, 1, 1)
        ax.scatter(obs_arr, sim_arr, s=30, alpha=0.7)
        lo = min(float(obs_arr.min()), float(sim_arr.min()))
        hi = max(float(obs_arr.max()), float(sim_arr.max()))
        ax.plot([lo, hi], [lo, hi], color="navy", linestyle="--", label="1:1")
        ax.set_xlabel("Observed head (m)")
        ax.set_ylabel("Simulated head (m)")
        ax.set_title(f"{model} — observed vs simulated (n={n})")
        ax.legend()
        ax.grid(alpha=0.3)
        plot_path_str = save_figure(fig, str(plot_path), ws)

    return {
        "model": model,
        "n": n,
        "rmse": float(np.sqrt(np.mean(residual_arr**2))),
        "bias": float(np.mean(residual_arr)),
        "mae": float(np.mean(np.abs(residual_arr))),
        "r2": r2,
        "obs_csv": str(csv_path),
        "residuals_csv": str(residuals_csv),
        "scatter_plot": plot_path_str,
        "residuals": residuals[:cap],
        "n_residuals_total": n,
        "worst_sites": residuals[:5],
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register post-processing tools with the MCP server."""

    @mcp.tool()
    def read_heads(
        model: str,
        kstpkper: tuple[int, int] | None = None,
        layer: int = 0,
        include_values: bool = False,
        max_cells: int = 10000,
        row_slice: list[int] | None = None,
        col_slice: list[int] | None = None,
        decimate: int | None = None,
    ) -> dict:
        """Read head values from the binary .hds output file for a given time
        step and layer.

        Returns statistics plus an output_file (.npy of the layer array) by
        default; include_values=True returns raw values within max_cells.
        row_slice/col_slice ([start, stop]) and decimate subset the grid
        (7e-A1)."""
        try:
            return _impl_read_heads(
                model, kstpkper, layer, include_values, max_cells, row_slice, col_slice, decimate
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("READ_HEADS_FAILED", str(exc))

    @mcp.tool()
    def read_budget(
        model: str,
        text: str | None = None,
        kstpkper: tuple[int, int] | None = None,
        max_records: int = 1000,
    ) -> dict:
        """Read cell budget records from the binary .cbb output file.

        Returns per-record-type aggregates plus records (capped at
        max_records; the full table goes to a CSV when it overflows) (7e-A1)."""
        try:
            return _impl_read_budget(model, text, kstpkper, max_records)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("READ_BUDGET_FAILED", str(exc))

    @mcp.tool()
    def compute_drawdown(
        model: str,
        kstpkper_initial: tuple[int, int],
        kstpkper_final: tuple[int, int],
        layer: int = 0,
        include_values: bool = False,
        max_cells: int = 10000,
    ) -> dict:
        """Compute drawdown as the difference in heads between two time steps.

        Returns statistics plus an output_file (.npy) by default;
        include_values=True returns raw values within max_cells (7e-A1)."""
        try:
            return _impl_compute_drawdown(
                model, kstpkper_initial, kstpkper_final, layer, include_values, max_cells
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("COMPUTE_DRAWDOWN_FAILED", str(exc))

    @mcp.tool()
    def compute_water_balance(
        model: str,
        kstpkper: tuple[int, int] | None = None,
    ) -> dict:
        """Compute inflow/outflow by boundary type and net water balance."""
        try:
            return _impl_compute_water_balance(model, kstpkper)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("WATER_BALANCE_FAILED", str(exc))

    @mcp.tool()
    def diagnose_water_balance(
        model: str,
        kstpkper: tuple[int, int] | None = None,
        tolerance_pct: float = 1.0,
        dominance_threshold: float = 0.5,
    ) -> dict:
        """Diagnose the water balance instead of leaving the modeller to
        eyeball compute_water_balance's inflow/outflow table (7e-C3).

        Returns the same percent_discrepancy MODFLOW itself reports
        (100 * (IN-OUT) / ((IN+OUT)/2)) with balanced = |discrepancy| <
        tolerance_pct (default 1%); dominant_inflow_term/dominant_outflow_term
        (the largest single boundary-type contributor to each side); and
        dominant_term/dominant_term_share/boundary_dominated — true when one
        boundary type accounts for more than dominance_threshold (default
        50%) of all flow through the model, a common sign the water balance
        is only closing because that boundary is absorbing everything."""
        try:
            return _impl_diagnose_water_balance(model, kstpkper, tolerance_pct, dominance_threshold)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("DIAGNOSIS_FAILED", str(exc))

    @mcp.tool()
    def export_heads_to_raster(
        model: str,
        layer: int = 0,
        kstpkper: tuple[int, int] | None = None,
        output_file: str | None = None,
    ) -> dict:
        """Write a layer of simulated heads to a georeferenced GeoTIFF
        (7e-C5.1) — a deliverable that opens directly in GIS, instead of a
        base64 PNG or a raw array. Requires a structured DIS grid with a CRS
        set (set_model_crs). MF6's inactive/dry sentinel values are written
        as the GeoTIFF's nodata."""
        from groundwater_mcp.utils.spatial import CRSError

        try:
            return _impl_export_heads_to_raster(model, layer, kstpkper, output_file)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except CRSError as exc:
            return _err("CRS_UNKNOWN", str(exc), "Call set_model_crs first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("EXPORT_FAILED", str(exc))

    @mcp.tool()
    def export_boundaries_to_shapefile(model: str, output_file: str | None = None) -> dict:
        """Write every list-based boundary package's stress-period cells to a
        shapefile (7e-C5.2) — one feature per (package, stress period, cell),
        with the package's own record fields (head, rate, stage, cond, ...)
        as attributes. Requires a structured DIS grid with a CRS set
        (set_model_crs). RCHA/EVTA (array-based) and SFR (reach-indexed, no
        cellid) are not included."""
        from groundwater_mcp.utils.spatial import CRSError

        try:
            return _impl_export_boundaries_to_shapefile(model, output_file)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except CRSError as exc:
            return _err("CRS_UNKNOWN", str(exc), "Call set_model_crs first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("EXPORT_FAILED", str(exc))

    @mcp.tool()
    def export_water_balance_csv(
        model: str,
        kstpkper: tuple[int, int] | None = None,
        output_file: str | None = None,
    ) -> dict:
        """Write compute_water_balance's inflow/outflow table to a CSV
        (7e-C5.2) — one row per boundary type plus a TOTAL row, columns
        matching compute_water_balance's own keys (inflow/outflow/net)."""
        try:
            return _impl_export_water_balance_csv(model, kstpkper, output_file)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("EXPORT_FAILED", str(exc))

    @mcp.tool()
    def read_simulated_observations(model: str) -> dict:
        """Read the simulated values the model wrote for the registered
        observation targets (7f-F1.2).

        Requires observations to have been registered with
        import_obs_from_csv and the model to have been run. Returns each
        site's simulated value at the final output time, keyed by site name."""
        try:
            return _impl_read_simulated_observations(model)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except Exception as exc:
            return _err("READ_OBS_FAILED", str(exc))

    @mcp.tool()
    def compare_to_observed(model: str, output_file: str | None = None) -> dict:
        """Compare registered observed values against simulated heads — RMSE,
        bias, R², mean absolute error, a per-site residual table (CSV), and a
        scatter plot — with no PEST setup at all (7f-F1.3).

        Each site's observed value is the mean of its registered records; the
        simulated value is the model's obs-CSV value at the final output time
        (steady-state appropriate). Requires import_obs_from_csv then
        run_simulation."""
        try:
            return _impl_compare_to_observed(model, output_file)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except Exception as exc:
            return _err("COMPARE_FAILED", str(exc))

    @mcp.tool()
    def read_compaction(model: str, max_rows: int = 500) -> dict:
        """Read CSUB compaction observations into per-layer compaction and a
        derived cumulative subsidence series.

        Matches the model's ``<gwf>.csub.obs.csv`` layer compaction columns
        case-insensitively (so MF6's upper-cased names work), sums them per
        time into ``subsidence``, and returns them alongside
        ``interbed_strain`` from ``<gwf>.strainib.csv`` when present.
        ``max_rows`` caps the inline lists; the full table is always written
        to ``<model>_compaction.csv``. Returns OUTPUT_FILE_MISSING when no
        CSUB obs CSV exists (run add_csub_package with observations then
        run_simulation first)."""
        try:
            return _impl_read_compaction(model, max_rows)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("READ_COMPACTION_FAILED", str(exc))

    @mcp.tool(structured_output=False)
    def plot_subsidence(
        model: str,
        observed_csv: str | None = None,
        output_file: str | None = None,
    ) -> dict | list:
        """Plot simulated cumulative subsidence against time and save as PNG.

        Uses read_compaction's derived subsidence series and, when
        ``observed_csv`` is given, overlays a measured series auto-detected
        from its ``Subsidence_ft`` column (else its first numeric non-time
        column). Returns the PNG natively (ImageContent) together with the
        file path — no separate view_image call is needed (7f-I1)."""
        try:
            result = _impl_plot_subsidence(model, observed_csv, output_file)
            if result.get("error"):
                return result
            return [Image(path=result["output_file"]), result]
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PLOT_FAILED", str(exc))

    @mcp.tool(structured_output=False)
    def plot_heads_map(
        model: str,
        layer: int = 0,
        kstpkper: tuple[int, int] | None = None,
        contour_intervals: int = 10,
        output_file: str | None = None,
    ) -> dict | list:
        """Plot a plan-view head contour map and save as PNG.

        Returns the PNG image natively (ImageContent) together with the file
        path — no separate view_image call is needed (7f-I1)."""
        try:
            result = _impl_plot_heads_map(model, layer, kstpkper, contour_intervals, output_file)
            return [Image(path=result["output_file"]), result]
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PLOT_FAILED", str(exc))

    @mcp.tool(structured_output=False)
    def plot_cross_section(
        model: str,
        line: dict,
        kstpkper: tuple[int, int] | None = None,
        output_file: str | None = None,
    ) -> dict | list:
        """Plot a cross-section of heads along a given line and save as PNG.

        Returns the PNG image natively (ImageContent) together with the file
        path — no separate view_image call is needed (7f-I1)."""
        try:
            result = _impl_plot_cross_section(model, line, kstpkper, output_file)
            return [Image(path=result["output_file"]), result]
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PLOT_FAILED", str(exc))
