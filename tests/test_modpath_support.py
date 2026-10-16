"""MODPATH 7 particle tracking on a completed MODFLOW 6 flow run (R1.4)."""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from groundwater_mcp.tools.runner import _find_mf6_binary


def _binaries_available() -> bool:
    try:
        _find_mf6_binary()
    except RuntimeError:
        return False
    return shutil.which("mp7") is not None


requires_mp7 = pytest.mark.skipif(
    not _binaries_available(), reason="MODFLOW 6 / MODPATH 7 not installed"
)

NCOL = 10


def _flow(tmp_path, name: str = "mpcol", run: bool = True) -> str:
    """1 x 3 x 10 plug-flow column: CHD 10 m (left) / 9 m (right), K = 10 m/d."""
    from groundwater_mcp.tools import builder, runner

    builder._impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    builder._impl_set_simulation(name, 1, [100.0], [1], "moderate")
    builder._impl_add_dis_package(name, 1, 3, NCOL, 10.0, 10.0, 10.0, [0.0])
    builder._impl_add_npf_package(name, 0, 10.0, None, True)
    builder._impl_add_ic_package(name, 9.0)
    builder._impl_add_boundary_package(
        name, "CHD",
        {0: [[[0, r, 0], 10.0] for r in range(3)] + [[[0, r, NCOL - 1], 9.0] for r in range(3)]},
        None,
    )
    builder._impl_add_oc_package(name, None, None, None, None)
    if run:
        assert runner._impl_run_simulation(name, silent=True)["success"] is True
    return name


@requires_mp7
def test_forward_particles_travel_at_the_seepage_velocity(tmp_path):
    """v = K * i / n = 10 * (1/90) / 0.3 = 0.370 m/d, so two interior
    particles released one 10 m cell apart arrive 10 / v = 27.0 d apart."""
    from groundwater_mcp.tools.runner import _impl_run_modpath

    name = _flow(tmp_path)
    result = _impl_run_modpath(name, release_cells=[[0, 1, c] for c in range(1, NCOL - 1)])
    assert result["n_particles"] == NCOL - 2
    assert result["direction"] == "forward"
    by_start = {tuple(p["start_cell"]): p for p in result["particles"]}
    t = [by_start[(0, 1, c)]["travel_time"] for c in range(1, NCOL - 1)]
    assert all(b < a for a, b in zip(t, t[1:]))  # nearer the sink arrives sooner
    expected = 10.0 / (10.0 * (1.0 / 90.0) / 0.3)
    for a, b in zip(t[:-1], t[1:]):
        assert (a - b) == pytest.approx(expected, rel=0.05)
    # every particle ends in the strong sink at the downstream boundary
    assert result["status_counts"] == {"no exit face (strong sink)": NCOL - 2}


@requires_mp7
def test_backward_tracking_ends_upstream(tmp_path):
    from groundwater_mcp.tools.runner import _impl_run_modpath

    name = _flow(tmp_path, "mpback")
    fwd = _impl_run_modpath(name, release_cells=[[0, 1, 5]])
    back = _impl_run_modpath(name, direction="backward", release_cells=[[0, 1, 5]])
    f, b = fwd["particles"][0], back["particles"][0]
    assert f["end"]["x"] > f["start"]["x"]
    assert b["end"]["x"] < b["start"]["x"]


@requires_mp7
def test_modpath_writes_arrays_and_defaults_to_layer_zero(tmp_path):
    from pathlib import Path

    from groundwater_mcp.tools.runner import _impl_run_modpath

    name = _flow(tmp_path, "mpdef")
    result = _impl_run_modpath(name)  # default: every active cell of layer 0
    assert result["n_particles"] == 3 * NCOL
    assert Path(result["pathlines_npy"]).exists()
    assert Path(result["endpoints_npy"]).exists()
    ends = np.load(result["endpoints_npy"])
    assert len(ends) == 3 * NCOL


@requires_mp7
def test_modpath_plot(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_modpath_pathlines
    from groundwater_mcp.tools.runner import _impl_run_modpath
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _flow(tmp_path, "mpplot")
    _impl_run_modpath(name, release_cells=[[0, r, 1] for r in range(3)])
    out = tmp_path / "paths.png"
    res = _impl_plot_modpath_pathlines(name, output_file=str(out))
    assert out.exists() and res["n_pathlines"] == 3
    assert resolve_workspace(name).exists()


def test_modpath_validation(tmp_path):
    from groundwater_mcp.tools.runner import _impl_run_modpath

    name = _flow(tmp_path, "mpbad", run=False)
    with pytest.raises(ValueError, match="direction"):
        _impl_run_modpath(name, direction="sideways")
    with pytest.raises(ValueError, match="porosity"):
        _impl_run_modpath(name, porosity=0.0)
    with pytest.raises(ValueError, match="out of range"):
        _impl_run_modpath(name, release_cells=[[0, 99, 0]])
    with pytest.raises(FileNotFoundError, match="run_simulation"):
        _impl_run_modpath(name)


@requires_mp7
def test_modpath_tools_through_the_mcp_layer(tmp_path):
    import asyncio
    import json

    from groundwater_mcp.server import mcp

    name = _flow(tmp_path, "mpmcp")
    out = json.loads(
        asyncio.run(
            mcp.call_tool("run_modpath", {"model": name, "release_cells": [[0, 1, 2]]})
        )[0].text
    )
    assert out["n_particles"] == 1
    bad = json.loads(
        asyncio.run(
            mcp.call_tool("run_modpath", {"model": name, "direction": "sideways"})
        )[0].text
    )
    assert bad["code"] == "INVALID_INPUT"
