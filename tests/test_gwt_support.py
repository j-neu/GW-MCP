"""GWT (MODFLOW 6 solute transport) support tests (R2.1).

A GWT model is a derived, FMI-coupled simulation exactly like GWE: it reads a
completed flow run's head and budget files and is run after it.
"""

from __future__ import annotations

import numpy as np
import pytest

from groundwater_mcp.tools.runner import _find_mf6_binary


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 not installed")

NCOL = 20


def _build_column(tmp_path, name: str = "gwtcol"):
    """1 x 1 x 20 column, flow left -> right, GWT with a constant-concentration
    inflow at the left cell. Returns the workspace."""
    from groundwater_mcp.tools import builder

    ws = tmp_path / name
    builder._impl_create_model(name, str(ws), "METERS", "DAYS")
    builder._impl_set_simulation(name, 1, [200.0], [20], "moderate")
    builder._impl_add_dis_package(
        name, nlay=1, nrow=1, ncol=NCOL, delr=10.0, delc=10.0, top=10.0, botm=[0.0]
    )
    builder._impl_add_npf_package(name, 0, 10.0, None, True)
    builder._impl_add_ic_package(name, 10.0)
    builder._impl_add_boundary_package(
        name, "CHD",
        {0: [[(0, 0, 0), 10.0, 1.0], [(0, 0, NCOL - 1), 9.0, 0.0]]},
        {"auxiliary": "CONCENTRATION"}, pname="CHD",
    )
    builder._impl_add_oc_package(
        name, f"{name}.hds", f"{name}.cbc", [("HEAD", "ALL"), ("BUDGET", "ALL")], None
    )
    builder._impl_add_gwt_model(name)
    builder._impl_add_dis_package(
        name, nlay=1, nrow=1, ncol=NCOL, delr=10.0, delc=10.0, top=10.0, botm=[0.0],
        component="gwt",
    )
    builder._impl_add_ic_package(name, 0.0, component="gwt")
    builder._impl_add_gwt_adv_package(name, "TVD")
    builder._impl_add_gwt_dsp_package(name, alh=1.0, ath1=0.1)
    builder._impl_add_gwt_mst_package(name, porosity=0.2)
    builder._impl_add_gwt_ssm_package(name, sources=[("CHD", "AUX", "CONCENTRATION")])
    builder._impl_add_oc_package(
        name, f"{name}_gwt.ucn", f"{name}_gwt.cbc", [("CONCENTRATION", "ALL")], None,
        component="gwt",
    )
    return ws


def test_gwt_component_is_registered():
    from groundwater_mcp.utils.components import spec_for

    spec = spec_for("gwt")
    assert spec.oc_value_keyword == "concentration_filerecord"


@requires_mf6
def test_gwt_column_runs_after_flow_and_concentration_advances(tmp_path):
    from groundwater_mcp.tools import postprocess, runner

    _build_column(tmp_path)
    out = runner._impl_run_simulation("gwtcol", silent=True)
    assert out["success"] is True, out
    assert [c["component"] for c in out.get("components", [])] == ["gwt"]

    conc = postprocess._impl_read_concentration("gwtcol")
    assert conc["type"] == "gwt"
    arr = np.load(conc["output_file"])
    assert arr.shape == (1, NCOL)
    profile = arr[0]
    # a front has entered from the source: close to the source value at the
    # inflow cell (cell mixing, so just below it), decaying downstream, never
    # exceeding the source concentration
    assert profile[0] > 0.95
    assert profile[1] > 0.5 and profile[1] > profile[-1] >= 0.0
    assert float(profile.max()) <= 1.0 + 1e-6
    assert np.all(np.diff(profile) <= 1e-6)


@requires_mf6
def test_gwt_concentration_plot(tmp_path):
    from groundwater_mcp.tools import postprocess, runner

    ws = _build_column(tmp_path, "gwtplot")
    assert runner._impl_run_simulation("gwtplot", silent=True)["success"] is True
    res = postprocess._impl_plot_concentration_map(
        "gwtplot", output_file=str(ws / "conc.png")
    )
    assert res["type"] == "gwt"
    assert (ws / "conc.png").exists()


def test_gwt_package_tools_reject_missing_component(tmp_path):
    from groundwater_mcp.tools import builder

    name = "gwtnone"
    builder._impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    with pytest.raises(KeyError):
        builder._impl_add_gwt_adv_package(name, "TVD")


@requires_mf6
def test_gwt_front_travels_at_the_seepage_velocity(tmp_path):
    """Plug-flow check: v = K * i / n = 10 * (1/190) / 0.2 = 0.263 m/d, so
    after 200 d the 50 % front sits v*t = 52.6 m from the source cell centre,
    i.e. at column ~5 of 10 m cells. Numerical dispersion smears the front but
    must not move it by more than a cell."""
    from groundwater_mcp.tools import postprocess, runner

    _build_column(tmp_path, "gwtvel")
    assert runner._impl_run_simulation("gwtvel", silent=True)["success"] is True
    profile = np.load(postprocess._impl_read_concentration("gwtvel")["output_file"])[0]

    x_cells = np.arange(NCOL) * 10.0  # distance from the source cell centre
    front = float(np.interp(0.5, profile[::-1], x_cells[::-1]))
    expected = 10.0 * (1.0 / 190.0) / 0.2 * 200.0
    assert abs(front - expected) < 10.0, (front, expected)


def _call_tool(name: str, args: dict):
    import asyncio
    import json

    from groundwater_mcp.server import mcp

    result = asyncio.run(mcp.call_tool(name, args))
    return json.loads(result[0].text)


def test_gwt_tools_through_the_mcp_layer(tmp_path):
    from groundwater_mcp.tools import builder

    name = "gwtmcp"
    builder._impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    builder._impl_set_simulation(name, 1, [10.0], [1], "moderate")
    builder._impl_add_dis_package(name, 1, 1, 5, 10.0, 10.0, 10.0, [0.0])

    # before add_gwt_model: a clear pointer to it
    early = _call_tool("add_gwt_adv_package", {"model": name})
    assert early["code"] == "MODEL_NOT_FOUND"
    assert "add_gwt_model" in early["suggestion"]

    made = _call_tool("add_gwt_model", {"model": name})
    assert made["component"] == "gwt"
    again = _call_tool("add_gwt_model", {"model": name})
    assert again["code"] == "INVALID_INPUT"

    bad_scheme = _call_tool("add_gwt_adv_package", {"model": name, "scheme": "FANCY"})
    assert bad_scheme["code"] == "INVALID_INPUT"
    bad_sorption = _call_tool(
        "add_gwt_mst_package", {"model": name, "porosity": 0.2, "sorption": "linear"}
    )
    assert bad_sorption["code"] == "INVALID_INPUT"
    assert "bulk_density" in bad_sorption["message"]
    bad_ssm = _call_tool(
        "add_gwt_ssm_package", {"model": name, "sources": [["NOPE", "AUX", "CONCENTRATION"]]}
    )
    assert bad_ssm["code"] == "INVALID_INPUT"

    ok = _call_tool("add_gwt_mst_package", {"model": name, "porosity": 0.25})
    assert ok["package"] == "MST"
    cnc = _call_tool(
        "add_gwt_cnc_package", {"model": name, "stress_period_data": {"0": [[[0, 0, 0], 1.0]]}}
    )
    assert cnc["package"] == "CNC"


@requires_mf6
def test_gwt_survives_flush_and_adoption(tmp_path):
    """A flushed flow+transport set re-adopted in a fresh session recovers the
    transport simulation from disk and runs it (no mocking)."""
    from groundwater_mcp.tools import builder, postprocess, runner
    from groundwater_mcp.utils import model_store

    ws = _build_column(tmp_path, "gwtadopt")
    model_store.flush_model("gwtadopt")
    model_store.invalidate("gwtadopt")
    builder._impl_adopt_model("gwtadopt_ro", str(ws))

    out = runner._impl_run_simulation("gwtadopt_ro", silent=True)
    assert out["success"] is True, out
    assert [c["component"] for c in out.get("components", [])] == ["gwt"]
    conc = postprocess._impl_read_concentration("gwtadopt_ro")
    assert conc["type"] == "gwt" and conc["n_active"] == NCOL
