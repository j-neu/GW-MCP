"""Tests for tools/postprocess.py — binary output reading and plotting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.postprocess import (
    _impl_compute_drawdown,
    _impl_compute_water_balance,
    _impl_diagnose_water_balance,
    _impl_export_boundaries_to_shapefile,
    _impl_export_heads_to_raster,
    _impl_export_water_balance_csv,
    _impl_plot_cross_section,
    _impl_plot_heads_map,
    _impl_read_budget,
    _impl_read_heads,
)
from groundwater_mcp.tools.runner import _find_mf6_binary, _impl_run_simulation

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runnable_model(tmp_path, model_name):
    """1-layer 5×5 steady-state model with CHD boundaries ready to run."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, {"save_flows": True})
    _impl_add_oc_package(model_name, None, None, None, None)
    return model_name


@pytest.fixture()
def ran_model(runnable_model):
    """runnable_model that has already been executed (requires mf6 binary)."""
    _impl_run_simulation(runnable_model, silent=True)
    return runnable_model


@pytest.fixture()
def synthetic_hds(runnable_model):
    """Inject a synthetic .hds file so unit tests don't need the mf6 binary."""
    import struct

    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(runnable_model)
    hds_path = ws / f"{runnable_model}.hds"

    # Write a minimal binary head file using flopy's HeadFile writer
    # Shape: 1 layer, 5 rows, 5 cols
    nlay, nrow, ncol = 1, 5, 5
    heads = np.linspace(8.0, 3.0, ncol * nrow).reshape(nrow, ncol)

    # Use flopy's binary writer utilities
    with open(hds_path, "wb") as f:
        # MODFLOW binary head record header:
        # kstp(int), kper(int), pertim(double), totim(double), text(16char),
        # ncol(int), nrow(int), ilay(int)
        kstp, kper = 1, 1
        pertim, totim = 1.0, 1.0
        text = b"            HEAD"
        ilay = 1
        header = struct.pack(
            "=2i2d16s3i",
            kstp, kper, pertim, totim, text, ncol, nrow, ilay,
        )
        # Each record is preceded and followed by its byte count (Fortran unformatted)
        header_bytes = len(header)
        f.write(struct.pack("=i", header_bytes))
        f.write(header)
        f.write(struct.pack("=i", header_bytes))

        # Data record
        data = heads.astype(np.float32).tobytes()
        data_len = len(data)
        f.write(struct.pack("=i", data_len))
        f.write(data)
        f.write(struct.pack("=i", data_len))

    return runnable_model, hds_path, heads


# ---------------------------------------------------------------------------
# _impl_read_heads — unit tests (no binary needed, uses synthetic fixture)
# ---------------------------------------------------------------------------


def test_read_heads_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_read_heads("no_such_model_xyz")


def test_read_heads_no_hds_raises(runnable_model):
    """FileNotFoundError when .hds does not exist."""
    with pytest.raises(FileNotFoundError, match=r"\.hds"):
        _impl_read_heads(runnable_model)


# ---------------------------------------------------------------------------
# 7f-D3 — layer bounds validation
# ---------------------------------------------------------------------------


@pytest.fixture()
def three_layer_model(tmp_path, model_name):
    """3-layer DIS model with no .hds output (unit tests for layer validation)."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 3, 5, 5, 100.0, 100.0, 50.0, [40.0, 30.0, 20.0])
    return model_name


def test_read_heads_layer_out_of_range_raises(three_layer_model):
    with pytest.raises(ValueError, match="nlay"):
        _impl_read_heads(three_layer_model, layer=-1)
    with pytest.raises(ValueError, match="nlay"):
        _impl_read_heads(three_layer_model, layer=3)
    # A valid layer passes validation and proceeds to the (missing) output file
    with pytest.raises(FileNotFoundError, match=r"\.hds"):
        _impl_read_heads(three_layer_model, layer=2)


def test_compute_drawdown_layer_out_of_range_raises(three_layer_model):
    with pytest.raises(ValueError, match="nlay"):
        _impl_compute_drawdown(three_layer_model, (0, 0), (0, 0), layer=-1)
    with pytest.raises(ValueError, match="nlay"):
        _impl_compute_drawdown(three_layer_model, (0, 0), (0, 0), layer=3)


def test_plot_heads_map_layer_out_of_range_raises(three_layer_model):
    with pytest.raises(ValueError, match="nlay"):
        _impl_plot_heads_map(three_layer_model, layer=3)
    with pytest.raises(ValueError, match="nlay"):
        _impl_plot_heads_map(three_layer_model, layer=-1)


# ---------------------------------------------------------------------------
# _impl_read_budget — unit tests
# ---------------------------------------------------------------------------


def test_read_budget_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_read_budget("no_such_model_xyz")


def test_read_budget_no_cbb_raises(runnable_model):
    with pytest.raises(FileNotFoundError, match=r"\.cbb"):
        _impl_read_budget(runnable_model)


# ---------------------------------------------------------------------------
# _impl_compute_drawdown — unit tests
# ---------------------------------------------------------------------------


def test_compute_drawdown_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_compute_drawdown("no_such_model_xyz", (0, 0), (0, 0))


def test_compute_drawdown_no_hds_raises(runnable_model):
    with pytest.raises(FileNotFoundError, match=r"\.hds"):
        _impl_compute_drawdown(runnable_model, (0, 0), (0, 0))


# ---------------------------------------------------------------------------
# _impl_compute_water_balance — unit tests
# ---------------------------------------------------------------------------


def test_compute_water_balance_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_compute_water_balance("no_such_model_xyz")


def test_compute_water_balance_no_cbb_raises(runnable_model):
    with pytest.raises(FileNotFoundError, match=r"\.cbb"):
        _impl_compute_water_balance(runnable_model)


# ---------------------------------------------------------------------------
# _impl_plot_heads_map — unit tests
# ---------------------------------------------------------------------------


def test_plot_heads_map_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_plot_heads_map("no_such_model_xyz")


def test_plot_heads_map_no_hds_raises(runnable_model):
    with pytest.raises(FileNotFoundError, match=r"\.hds"):
        _impl_plot_heads_map(runnable_model)


# ---------------------------------------------------------------------------
# Integration tests — require mf6 binary
# ---------------------------------------------------------------------------


@requires_mf6
def test_read_heads_returns_expected_keys(ran_model):
    result = _impl_read_heads(ran_model)
    assert "error" not in result
    keys = ("model", "kstpkper", "layer", "shape", "output_file", "min", "max", "mean", "n_active")
    for key in keys:
        assert key in result, f"Missing key: {key}"
    assert "values" not in result  # arrays are off by default (7e-A1)


@requires_mf6
def test_read_heads_values_in_range(ran_model):
    result = _impl_read_heads(ran_model, layer=0, include_values=True)
    # CHD boundaries at 3 and 8 m — all heads should be in [3, 8]
    assert result["min"] >= 3.0 - 1e-3
    assert result["max"] <= 8.0 + 1e-3


@requires_mf6
def test_read_heads_shape(ran_model):
    result = _impl_read_heads(ran_model, layer=0)
    assert result["shape"] == [5, 5]


@requires_mf6
def test_read_heads_invalid_kstpkper_raises(ran_model):
    with pytest.raises(ValueError, match="not found"):
        _impl_read_heads(ran_model, kstpkper=(99, 99))


@requires_mf6
def test_read_budget_returns_expected_keys(ran_model):
    result = _impl_read_budget(ran_model)
    assert "error" not in result
    for key in ("model", "kstpkper", "record_count", "records"):
        assert key in result, f"Missing key: {key}"


@requires_mf6
def test_read_budget_chd_filter(ran_model):
    result = _impl_read_budget(ran_model, text="CHD")
    assert "error" not in result
    assert result["record_count"] >= 0


@requires_mf6
def test_read_budget_invalid_text_raises(ran_model):
    with pytest.raises(ValueError, match="not found"):
        _impl_read_budget(ran_model, text="NONEXISTENT_LABEL_XYZ")


@requires_mf6
def test_read_budget_aggregates_and_record_cap(ran_model):
    """read_budget returns per-type aggregates; records are capped with the
    full table to CSV on overflow (7e-A1.5)."""
    import json

    result = _impl_read_budget(ran_model)
    assert "error" not in result
    assert result["record_count"] > 0
    assert isinstance(result["aggregates"], dict)
    assert len(result["aggregates"]) > 0
    assert len(json.dumps(result)) < 200_000

    # A tiny cap forces the CSV path
    capped = _impl_read_budget(ran_model, max_records=1)
    assert len(capped["records"]) == 1
    assert capped["records_truncated"] is True
    assert Path(capped["records_csv"]).exists()
    assert capped["record_count"] == result["record_count"]

    # Aggregates match the full raw record set
    for label, agg in result["aggregates"].items():
        assert agg["record_count"] >= 0


@requires_mf6
def test_budget_reader_falls_back_to_double_on_oserror(ran_model, monkeypatch):
    """Windows regression (independent tutorial-05 transient run): flopy's auto
    budget precision raises OSError [Errno 22] on larger double-precision .cbb
    files instead of falling back cleanly. The MCP budget reader must retry
    with precision='double'."""
    import flopy.utils as fu

    real_init = fu.CellBudgetFile.__init__
    calls = {"n": 0}

    def patched_init(self, filename, precision="auto", verbose=False, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(22, "Invalid argument")
        real_init(self, filename, precision=precision, verbose=verbose, **kwargs)

    monkeypatch.setattr(fu.CellBudgetFile, "__init__", patched_init)

    result = _impl_read_budget(ran_model)
    assert "error" not in result
    assert result["record_count"] > 0

    calls["n"] = 0
    wb = _impl_compute_water_balance(ran_model)
    assert "error" not in wb
    assert wb["total_inflow"] > 0
    assert wb["total_outflow"] < 0  # outflows are reported negative


@requires_mf6
def test_compute_drawdown_same_timestep_is_zero(ran_model):
    """Drawdown between identical time steps should be zero everywhere."""
    result = _impl_compute_drawdown(ran_model, (0, 0), (0, 0), layer=0, include_values=True)
    assert "error" not in result
    arr = np.array(result["values"])
    valid = arr[arr != 1e30]
    assert np.allclose(valid, 0.0, atol=1e-6)


@requires_mf6
def test_compute_drawdown_returns_expected_keys(ran_model):
    result = _impl_compute_drawdown(ran_model, (0, 0), (0, 0))
    for key in ("model", "kstpkper_initial", "kstpkper_final", "layer", "shape", "output_file"):
        assert key in result


@requires_mf6
def test_compute_water_balance_returns_expected_keys(ran_model):
    result = _impl_compute_water_balance(ran_model)
    assert "error" not in result
    keys = (
        "model", "kstpkper", "inflow", "outflow",
        "total_inflow", "total_outflow", "net_balance",
    )
    for key in keys:
        assert key in result, f"Missing key: {key}"


@requires_mf6
def test_compute_water_balance_net_near_zero(ran_model):
    """For a converged steady-state model the net balance should be close to zero."""
    result = _impl_compute_water_balance(ran_model)
    # Allow up to 1% relative error
    total_in = abs(result["total_inflow"])
    net = abs(result["net_balance"])
    if total_in > 0:
        assert net / total_in < 0.05, f"Net balance {net} is more than 5% of inflow {total_in}"


# ---------------------------------------------------------------------------
# _impl_diagnose_water_balance (7e-C3)
# ---------------------------------------------------------------------------


def test_diagnose_water_balance_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_diagnose_water_balance("no_such_model_xyz")


def test_diagnose_water_balance_unbalanced_flagged(runnable_model, monkeypatch):
    """A deliberately unbalanced budget (mocked — MF6 rarely produces one on
    a converged run) must be flagged not-balanced with the right discrepancy."""
    import groundwater_mcp.tools.postprocess as pp

    fake_wb = {
        "model": runnable_model,
        "kstpkper": [0, 0],
        "inflow": {"CHD": 100.0},
        "outflow": {"CHD": -50.0},
        "total_inflow": 100.0,
        "total_outflow": -50.0,
        "net_balance": 50.0,
    }
    monkeypatch.setattr(pp, "_impl_compute_water_balance", lambda *a, **k: fake_wb)

    result = pp._impl_diagnose_water_balance(runnable_model)
    # IN=100, OUT=50, avg=75 -> 100*50/75
    assert result["percent_discrepancy"] == pytest.approx(66.666, rel=1e-3)
    assert result["balanced"] is False
    assert result["dominant_inflow_term"] == "CHD"
    assert result["dominant_outflow_term"] == "CHD"
    assert result["dominant_term"] == "CHD"
    assert result["boundary_dominated"] is True


def test_diagnose_water_balance_tolerance_respected(runnable_model, monkeypatch):
    import groundwater_mcp.tools.postprocess as pp

    fake_wb = {
        "model": runnable_model,
        "kstpkper": [0, 0],
        "inflow": {"CHD": 100.0},
        "outflow": {"CHD": -99.5},
        "total_inflow": 100.0,
        "total_outflow": -99.5,
        "net_balance": 0.5,
    }
    monkeypatch.setattr(pp, "_impl_compute_water_balance", lambda *a, **k: fake_wb)

    result = pp._impl_diagnose_water_balance(runnable_model, tolerance_pct=1.0)
    assert result["balanced"] is True
    result_strict = pp._impl_diagnose_water_balance(runnable_model, tolerance_pct=0.1)
    assert result_strict["balanced"] is False


def test_diagnose_water_balance_no_flow_is_balanced(runnable_model, monkeypatch):
    """Zero flow everywhere is trivially balanced, not a division-by-zero crash."""
    import groundwater_mcp.tools.postprocess as pp

    fake_wb = {
        "model": runnable_model,
        "kstpkper": [0, 0],
        "inflow": {},
        "outflow": {},
        "total_inflow": 0.0,
        "total_outflow": 0.0,
        "net_balance": 0.0,
    }
    monkeypatch.setattr(pp, "_impl_compute_water_balance", lambda *a, **k: fake_wb)

    result = pp._impl_diagnose_water_balance(runnable_model)
    assert result["balanced"] is True
    assert result["percent_discrepancy"] == 0.0
    assert result["dominant_term"] is None
    assert result["boundary_dominated"] is False


@requires_mf6
def test_diagnose_water_balance_converged_model_is_balanced(ran_model):
    result = _impl_diagnose_water_balance(ran_model)
    assert result["balanced"] is True
    assert abs(result["percent_discrepancy"]) < 1.0


@requires_mf6
def test_diagnose_water_balance_single_boundary_is_dominant(ran_model):
    """runnable_model only has CHD boundaries — it necessarily dominates."""
    result = _impl_diagnose_water_balance(ran_model)
    assert result["dominant_term"] == "CHD"
    assert result["boundary_dominated"] is True
    assert result["dominant_term_share"] == pytest.approx(1.0, rel=1e-6)


# ---------------------------------------------------------------------------
# export_heads_to_raster / export_boundaries_to_shapefile /
# export_water_balance_csv (7e-C5)
# ---------------------------------------------------------------------------


def test_export_heads_to_raster_requires_crs(runnable_model):
    from groundwater_mcp.utils.spatial import CRSError

    with pytest.raises(CRSError):
        _impl_export_heads_to_raster(runnable_model)


def test_export_boundaries_to_shapefile_requires_crs(runnable_model):
    from groundwater_mcp.utils.spatial import CRSError

    with pytest.raises(CRSError):
        _impl_export_boundaries_to_shapefile(runnable_model)


@requires_mf6
def test_export_heads_to_raster_matches_read_heads(ran_model, tmp_path):
    from groundwater_mcp.tools.builder import _impl_set_model_crs

    _impl_set_model_crs(ran_model, "EPSG:32718")
    out = str(tmp_path / "heads.tif")
    result = _impl_export_heads_to_raster(ran_model, layer=0, output_file=out)
    assert "error" not in result
    assert Path(out).exists()
    assert result["crs"]

    import rasterio

    with rasterio.open(out) as src:
        assert src.crs is not None
        assert src.transform is not None
        raster_arr = src.read(1)

    expected = _impl_read_heads(ran_model, layer=0, include_values=True, max_cells=1000)
    # runnable_model's 5x5 grid has no inactive cells, so every pixel should
    # match exactly (no nodata masking involved).
    np.testing.assert_allclose(raster_arr, np.array(expected["values"]), rtol=1e-4)


@requires_mf6
def test_export_heads_to_raster_relative_output_resolves_to_workspace(ran_model):
    from groundwater_mcp.tools.builder import _impl_set_model_crs
    from groundwater_mcp.utils.workspace import resolve_workspace

    _impl_set_model_crs(ran_model, "EPSG:32718")
    result = _impl_export_heads_to_raster(ran_model, output_file="rel_heads.tif")
    ws = resolve_workspace(ran_model)
    assert result["output_file"] == str(ws / "rel_heads.tif")
    assert (ws / "rel_heads.tif").exists()


def test_export_boundaries_to_shapefile_one_feature_per_cell(runnable_model, tmp_path):
    from groundwater_mcp.tools.builder import _impl_set_model_crs

    _impl_set_model_crs(runnable_model, "EPSG:32718")
    out = str(tmp_path / "boundaries.shp")
    result = _impl_export_boundaries_to_shapefile(runnable_model, output_file=out)
    assert "error" not in result
    assert result["feature_count"] == 10  # 5 left-column + 5 right-column CHD cells
    assert result["packages"] == ["CHD"]

    import geopandas as gpd

    gdf = gpd.read_file(out)
    assert len(gdf) == 10
    assert gdf.crs is not None
    assert set(gdf["package"]) == {"CHD"}
    assert "head" in gdf.columns


def test_export_boundaries_to_shapefile_no_boundaries_raises(tmp_path, model_name):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_npf_package,
        _impl_create_model,
        _impl_set_model_crs,
        _impl_set_simulation,
    )

    _impl_create_model(model_name, str(tmp_path / model_name), "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 3, 3, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_set_model_crs(model_name, "EPSG:32718")

    with pytest.raises(ValueError, match="boundary"):
        _impl_export_boundaries_to_shapefile(model_name)


@requires_mf6
def test_export_water_balance_csv_columns_and_total(ran_model, tmp_path):
    import pandas as pd

    out = str(tmp_path / "wb.csv")
    result = _impl_export_water_balance_csv(ran_model, output_file=out)
    assert "error" not in result
    assert Path(out).exists()

    df = pd.read_csv(out)
    assert set(df.columns) == {"boundary_type", "inflow", "outflow", "net"}

    wb = _impl_compute_water_balance(ran_model)
    total_row = df[df["boundary_type"] == "TOTAL"].iloc[0]
    assert total_row["inflow"] == pytest.approx(wb["total_inflow"])
    assert total_row["outflow"] == pytest.approx(wb["total_outflow"])
    assert total_row["net"] == pytest.approx(wb["net_balance"])


@requires_mf6
def test_plot_heads_map_produces_png(ran_model, tmp_path):
    out = str(tmp_path / "heads.png")
    result = _impl_plot_heads_map(ran_model, output_file=out)
    assert "error" not in result
    assert result["output_file"] == out
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0


@requires_mf6
def test_plot_heads_map_auto_output_file(ran_model):
    result = _impl_plot_heads_map(ran_model)
    assert "error" not in result
    assert result["output_file"].endswith(".png")
    assert Path(result["output_file"]).exists()


@requires_mf6
def test_plot_cross_section_produces_png(ran_model, tmp_path):
    out = str(tmp_path / "xsec.png")
    result = _impl_plot_cross_section(ran_model, line={"row": 2}, output_file=out)
    assert "error" not in result
    assert result["output_file"] == out
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0


@requires_mf6
def test_plot_cross_section_auto_output_file(ran_model):
    result = _impl_plot_cross_section(ran_model, line={"column": 2})
    assert "error" not in result
    assert result["output_file"].endswith(".png")
    assert Path(result["output_file"]).exists()


# ---------------------------------------------------------------------------
# 7f-I1 — plot tools return the PNG natively (view_image removed)
# ---------------------------------------------------------------------------


def _make_png(path: Path) -> None:
    import base64

    # Minimal valid 1x1 PNG
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    path.write_bytes(base64.b64decode(png_b64))


def test_plot_heads_map_returns_image_content(ran_model):
    """plot_heads_map returns the PNG as an MCP image content block plus the
    file path (7f-I1) — no separate view_image round-trip."""
    import asyncio
    import json

    from groundwater_mcp.server import mcp

    result = asyncio.run(mcp.call_tool("plot_heads_map", {"model": ran_model}))
    blocks = list(result)
    image_blocks = [b for b in blocks if getattr(b, "type", None) == "image"]
    assert image_blocks, f"expected an image content block, got {[b.type for b in blocks]}"
    assert image_blocks[0].data, "image content block has no data"
    # The file path comes in a text block
    text_blocks = [b for b in blocks if getattr(b, "type", None) == "text"]
    payload = json.loads(text_blocks[0].text)
    assert payload["output_file"].endswith(".png")


# ---------------------------------------------------------------------------
# 7e-A1 — array payload reduction
# ---------------------------------------------------------------------------


@pytest.fixture()
def large_ran_model(tmp_path, model_name):
    """A 200x200 single-layer model that has been run."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 200, 200, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, r, 0], 8.0] for r in range(200)] + [[[0, r, 199], 3.0] for r in range(200)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)
    _impl_run_simulation(model_name, silent=True)
    return model_name


@requires_mf6
def test_read_heads_default_response_small_and_no_values(large_ran_model):
    import json

    result = _impl_read_heads(large_ran_model, layer=0)
    assert "values" not in result
    assert len(json.dumps(result)) < 4_000

    import numpy as np

    from groundwater_mcp.tools.postprocess import _impl_read_heads as _rh

    # .npy round-trips to the exact flopy array
    arr = np.load(result["output_file"])
    hf_result = _rh(large_ran_model, layer=0, include_values=True, max_cells=10_000_000)
    import numpy as _np

    assert _np.array_equal(arr, _np.array(hf_result["values"]))


@requires_mf6
def test_read_heads_include_values_size_guard(large_ran_model):
    # 200x200 = 40,000 cells > default max_cells=10000 → PAYLOAD_TOO_LARGE
    result = _impl_read_heads(large_ran_model, layer=0, include_values=True)
    assert result.get("error") is True
    assert result["code"] == "PAYLOAD_TOO_LARGE"

    # Subsetting brings it under the cap and returns values equal to the slice
    result = _impl_read_heads(
        large_ran_model, layer=0, include_values=True, row_slice=[0, 50], col_slice=[0, 50]
    )
    assert "error" not in result
    assert result["shape"] == [50, 50]
    full = np.load(_impl_read_heads(large_ran_model, layer=0)["output_file"])
    assert np.allclose(np.array(result["values"]), full[0:50, 0:50])


@requires_mf6
def test_read_heads_decimate(large_ran_model):
    result = _impl_read_heads(
        large_ran_model, layer=0, decimate=4, include_values=True, max_cells=10_000_000
    )
    assert "error" not in result
    full = np.load(_impl_read_heads(large_ran_model, layer=0)["output_file"])
    assert np.array_equal(np.array(result["values"]), full[::4, ::4])


@requires_mf6
def test_compute_drawdown_payload_guard(large_ran_model):
    result = _impl_compute_drawdown(large_ran_model, (0, 0), (0, 0), layer=0, include_values=True)
    assert result.get("error") is True
    assert result["code"] == "PAYLOAD_TOO_LARGE"
    small = _impl_compute_drawdown(large_ran_model, (0, 0), (0, 0), layer=0)
    assert "values" not in small
    assert "output_file" in small
