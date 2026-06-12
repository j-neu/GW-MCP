"""postprocess module — read binary output files and compute derived quantities."""

from __future__ import annotations

from pathlib import Path

import numpy as np

import flopy.utils as fu
from mcp.server.fastmcp import FastMCP

from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.workspace import resolve_workspace


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


# ---------------------------------------------------------------------------
# File finders
# ---------------------------------------------------------------------------


def _find_output_file(workspace: Path, extension: str) -> Path:
    """Return the first file with the given extension in *workspace*.

    Raises
    ------
    FileNotFoundError
        If no matching file exists.
    """
    matches = list(workspace.glob(f"*{extension}"))
    if not matches:
        raise FileNotFoundError(
            f"No {extension} file found in {workspace}. "
            "Run the simulation first with run_simulation."
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Array stats helper
# ---------------------------------------------------------------------------


def _array_stats(arr: np.ndarray) -> dict:
    """Return min/max/mean for a numeric array, ignoring no-data values."""
    data = arr[arr != 1e30]  # MODFLOW no-data sentinel
    if data.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(np.nanmin(data)),
        "max": float(np.nanmax(data)),
        "mean": float(np.nanmean(data)),
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _impl_read_heads(
    model: str,
    kstpkper: tuple[int, int] | None = None,
    layer: int = 0,
) -> dict:
    """Read head values from the binary .hds output file."""
    ws = resolve_workspace(model)
    hds_path = _find_output_file(ws, ".hds")

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

    return {
        "model": model,
        "kstpkper": list(target),
        "layer": layer,
        "shape": list(layer_heads.shape),
        "values": layer_heads.tolist(),
        **_array_stats(layer_heads),
    }


def _impl_read_budget(
    model: str,
    text: str | None = None,
    kstpkper: tuple[int, int] | None = None,
) -> dict:
    """Read cell budget records from the binary .cbb output file."""
    ws = resolve_workspace(model)
    cbb_path = _find_output_file(ws, ".cbb")

    cbf = fu.CellBudgetFile(str(cbb_path))
    kstpkper_list = cbf.get_kstpkper()

    if not kstpkper_list:
        raise ValueError("Budget file contains no data.")

    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]

    unique_texts = cbf.get_unique_record_names(decode=True)

    if text is not None:
        text_upper = text.strip().upper()
        # Partial match: allow short labels like "WEL" to match "         WEL"
        def _label(t) -> str:
            return t.decode().strip().upper() if isinstance(t, bytes) else t.strip().upper()

        matched = next((t for t in unique_texts if text_upper in _label(t)), None)
        if matched is None:
            available = [
                (t.decode().strip() if isinstance(t, bytes) else t.strip())
                for t in unique_texts
            ]
            raise ValueError(
                f"Budget text label '{text}' not found. Available: {available}"
            )
        records_raw = cbf.get_data(kstpkper=target, text=matched)
    else:
        records_raw = cbf.get_data(kstpkper=target)

    records = []
    for rec in records_raw:
        if hasattr(rec, "dtype") and rec.dtype.names:
            # Structured array (e.g. list-type budget)
            for row in rec:
                entry = {name: _scalar(row[name]) for name in rec.dtype.names}
                records.append(entry)
        else:
            # Plain ndarray — return stats only
            arr = np.asarray(rec, dtype=float)
            records.append({"values_stats": _array_stats(arr)})

    return {
        "model": model,
        "kstpkper": list(target),
        "text_filter": text,
        "record_count": len(records),
        "records": records,
    }


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
) -> dict:
    """Compute drawdown as the difference in heads between two time steps."""
    ws = resolve_workspace(model)
    hds_path = _find_output_file(ws, ".hds")

    hf = fu.HeadFile(str(hds_path))
    h_initial = hf.get_data(kstpkper=tuple(kstpkper_initial))[layer]
    h_final = hf.get_data(kstpkper=tuple(kstpkper_final))[layer]

    # drawdown = initial - final (positive = head declined)
    drawdown = h_initial - h_final
    # Mask no-data cells
    nodata = (h_initial == 1e30) | (h_final == 1e30)
    drawdown[nodata] = 1e30

    return {
        "model": model,
        "kstpkper_initial": list(kstpkper_initial),
        "kstpkper_final": list(kstpkper_final),
        "layer": layer,
        "shape": list(drawdown.shape),
        "values": drawdown.tolist(),
        **_array_stats(drawdown),
    }


def _impl_compute_water_balance(
    model: str,
    kstpkper: tuple[int, int] | None = None,
) -> dict:
    """Aggregate budget by boundary type and compute net water balance."""
    ws = resolve_workspace(model)
    cbb_path = _find_output_file(ws, ".cbb")

    cbf = fu.CellBudgetFile(str(cbb_path))
    kstpkper_list = cbf.get_kstpkper()

    if not kstpkper_list:
        raise ValueError("Budget file contains no data.")

    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    unique_texts = cbf.get_unique_record_names(decode=True)

    inflow: dict[str, float] = {}
    outflow: dict[str, float] = {}

    for text_raw in unique_texts:
        label = (text_raw.decode().strip() if isinstance(text_raw, bytes) else text_raw.strip())
        try:
            records = cbf.get_data(kstpkper=target, text=text_raw)
        except Exception:
            continue

        total = 0.0
        for rec in records:
            arr = np.asarray(rec)
            if arr.dtype.names and "q" in arr.dtype.names:
                total += float(arr["q"].sum())
            elif arr.dtype.names and "FLOW-JA-FACE" in arr.dtype.names:
                pass  # skip internal cell-to-cell flow
            elif arr.dtype.names:
                # Structured record without a recognised flow field — skip
                pass
            else:
                vals = arr.astype(float).ravel()
                vals = vals[vals != 1e30]
                total += float(vals.sum()) if vals.size > 0 else 0.0

        if total >= 0:
            inflow[label] = total
        else:
            outflow[label] = total

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
    }


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

    ws = resolve_workspace(model)
    hds_path = _find_output_file(ws, ".hds")
    gwf = get_gwf(model)

    hf = fu.HeadFile(str(hds_path))
    kstpkper_list = hf.get_kstpkper()
    target = tuple(kstpkper) if kstpkper is not None else kstpkper_list[-1]
    heads = hf.get_data(kstpkper=target)

    with figure() as fig:
        ax = fig.add_subplot(1, 1, 1)
        pmv = fplot.PlotMapView(model=gwf, layer=layer, ax=ax)
        pmv.plot_grid(alpha=0.3, lw=0.4)
        head_layer = heads[layer]
        valid = head_layer[head_layer != 1e30]
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
    hds_path = _find_output_file(ws, ".hds")
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
    ) -> dict:
        """Read head values from the binary .hds output file for a given time step and layer."""
        try:
            return _impl_read_heads(model, kstpkper, layer)
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
    ) -> dict:
        """Read cell budget records from the binary .cbb output file."""
        try:
            return _impl_read_budget(model, text, kstpkper)
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
    ) -> dict:
        """Compute drawdown as the difference in heads between two time steps."""
        try:
            return _impl_compute_drawdown(model, kstpkper_initial, kstpkper_final, layer)
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
    def plot_heads_map(
        model: str,
        layer: int = 0,
        kstpkper: tuple[int, int] | None = None,
        contour_intervals: int = 10,
        output_file: str | None = None,
    ) -> dict:
        """Plot a plan-view head contour map and save as PNG."""
        try:
            return _impl_plot_heads_map(model, layer, kstpkper, contour_intervals, output_file)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PLOT_FAILED", str(exc))

    @mcp.tool()
    def plot_cross_section(
        model: str,
        line: dict,
        kstpkper: tuple[int, int] | None = None,
        output_file: str | None = None,
    ) -> dict:
        """Plot a cross-section of heads along a given line and save as PNG."""
        try:
            return _impl_plot_cross_section(model, line, kstpkper, output_file)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("OUTPUT_FILE_MISSING", str(exc), "Run run_simulation first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PLOT_FAILED", str(exc))
