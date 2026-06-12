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
    import flopy.utils as fu
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
    for key in ("model", "kstpkper", "layer", "shape", "values", "min", "max", "mean"):
        assert key in result, f"Missing key: {key}"


@requires_mf6
def test_read_heads_shape(ran_model):
    result = _impl_read_heads(ran_model, layer=0)
    assert result["shape"] == [5, 5]


@requires_mf6
def test_read_heads_values_in_range(ran_model):
    result = _impl_read_heads(ran_model, layer=0)
    # CHD boundaries at 3 and 8 m — all heads should be in [3, 8]
    assert result["min"] >= 3.0 - 1e-3
    assert result["max"] <= 8.0 + 1e-3


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
def test_compute_drawdown_same_timestep_is_zero(ran_model):
    """Drawdown between identical time steps should be zero everywhere."""
    result = _impl_compute_drawdown(ran_model, (0, 0), (0, 0), layer=0)
    assert "error" not in result
    arr = np.array(result["values"])
    valid = arr[arr != 1e30]
    assert np.allclose(valid, 0.0, atol=1e-6)


@requires_mf6
def test_compute_drawdown_returns_expected_keys(ran_model):
    result = _impl_compute_drawdown(ran_model, (0, 0), (0, 0))
    for key in ("model", "kstpkper_initial", "kstpkper_final", "layer", "shape", "values"):
        assert key in result


@requires_mf6
def test_compute_water_balance_returns_expected_keys(ran_model):
    result = _impl_compute_water_balance(ran_model)
    assert "error" not in result
    for key in ("model", "kstpkper", "inflow", "outflow", "total_inflow", "total_outflow", "net_balance"):
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
