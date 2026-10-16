"""SFR / MAW / LAK / UZF through ``add_advanced_package`` (R2.2, R2.3).

The advanced packages have per-feature ``packagedata`` / ``connectiondata`` /
``perioddata`` instead of a stress-period list, so they cannot go through
``add_boundary_package``. Each is verified with a real MODFLOW 6 run.
"""

from __future__ import annotations

import pytest

from groundwater_mcp.tools.runner import _find_mf6_binary


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 not installed")

SFR_PACKAGEDATA = [
    [0, [0, 1, 0], 10.0, 5.0, 0.001, 9.0, 1.0, 1e-3, 0.03, 1, 1.0, 0],
    [1, [0, 1, 1], 10.0, 5.0, 0.001, 8.9, 1.0, 1e-3, 0.03, 2, 1.0, 0],
    [2, [0, 1, 2], 10.0, 5.0, 0.001, 8.8, 1.0, 1e-3, 0.03, 1, 1.0, 0],
]
SFR_CONNECTIONS = [[0, -1], [1, 0, -2], [2, 1]]
MAW_PACKAGEDATA = [[0, 0.1, 0.0, 8.0, "THIEM", 1]]
MAW_CONNECTIONS = [[0, 0, [0, 1, 2], 10.0, 0.0, 0.0, 0.0]]
UZF_PACKAGEDATA = [
    [i, [0, 1, i + 1], 1, -1, 1.0, 1e-3, 0.05, 0.3, 0.1, 3.5] for i in range(3)
]
UZF_PERIODDATA = [[i, 1e-4, 0, 0, 0, 0, 0, 0] for i in range(3)]
LAK_PACKAGEDATA = [[0, 9.0, 1]]
LAK_CONNECTIONS = [[0, 0, [0, 1, 2], "VERTICAL", 0.1, 0.0, 0.0, 0.0, 0.0]]


def _flow_model(tmp_path, name: str) -> str:
    from groundwater_mcp.tools import builder

    builder._impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    builder._impl_set_simulation(name, 1, [10.0], [1], "simple")
    builder._impl_add_dis_package(name, 1, 3, 5, 10.0, 10.0, 10.0, [0.0])
    builder._impl_add_npf_package(name, 1, 1.0, None, True)
    builder._impl_add_ic_package(name, 8.0)
    builder._impl_add_boundary_package(
        name, "CHD", {0: [[[0, r, 4], 7.0] for r in range(3)]}, None
    )
    builder._impl_add_oc_package(name, None, None, None, None)
    return name


def _run_and_balance(name: str) -> dict:
    from groundwater_mcp.tools.postprocess import _impl_compute_water_balance
    from groundwater_mcp.tools.runner import _impl_run_simulation

    out = _impl_run_simulation(name, silent=True)
    assert out["success"] is True, out
    return _impl_compute_water_balance(name)


def _terms(balance: dict) -> set[str]:
    return set(balance["inflow"]) | set(balance["outflow"])


@requires_mf6
def test_sfr_reaches_route_inflow_and_exchange_with_the_aquifer(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_advanced_package

    name = _flow_model(tmp_path, "advsfr")
    result = _impl_add_advanced_package(
        name, "SFR", SFR_PACKAGEDATA, SFR_CONNECTIONS, {0: [[0, "INFLOW", 5.0]]}
    )
    assert result["package"] == "SFR"
    assert result["counts"] == {"nreaches": 3}
    assert any("SFR" in t for t in _terms(_run_and_balance(name)))


@requires_mf6
def test_maw_well_pumps_at_its_rate(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_advanced_package

    name = _flow_model(tmp_path, "advmaw")
    result = _impl_add_advanced_package(
        name, "MAW", MAW_PACKAGEDATA, MAW_CONNECTIONS, {0: [[0, "RATE", -5.0]]}
    )
    assert result["counts"] == {"nmawwells": 1}
    wb = _run_and_balance(name)
    assert any("MAW" in t for t in _terms(wb))
    maw_out = sum(v for k, v in wb["outflow"].items() if "MAW" in k)
    assert maw_out == pytest.approx(-5.0, rel=1e-3)


@requires_mf6
def test_uzf_cells_receive_infiltration(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_advanced_package

    name = _flow_model(tmp_path, "advuzf")
    result = _impl_add_advanced_package(
        name, "UZF", UZF_PACKAGEDATA, None, {0: UZF_PERIODDATA},
        options={"simulate_et": False, "simulate_gwseep": False},
    )
    assert result["counts"] == {"nuzfcells": 3}
    assert any("UZF" in t for t in _terms(_run_and_balance(name)))


@requires_mf6
def test_lak_lake_exchanges_with_the_aquifer(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_advanced_package

    name = _flow_model(tmp_path, "advlak")
    result = _impl_add_advanced_package(
        name, "LAK", LAK_PACKAGEDATA, LAK_CONNECTIONS, {0: [[0, "RAINFALL", 0.001]]}
    )
    assert result["counts"] == {"nlakes": 1, "noutlets": 0, "ntables": 0}
    assert any("LAK" in t for t in _terms(_run_and_balance(name)))


def test_advanced_package_validation(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_advanced_package

    name = _flow_model(tmp_path, "advbad")
    with pytest.raises(ValueError, match="Choose from"):
        _impl_add_advanced_package(name, "WELL", MAW_PACKAGEDATA, MAW_CONNECTIONS)
    with pytest.raises(ValueError, match="packagedata"):
        _impl_add_advanced_package(name, "SFR", [], SFR_CONNECTIONS)
    with pytest.raises(ValueError, match="connectiondata"):
        _impl_add_advanced_package(name, "SFR", SFR_PACKAGEDATA, None)


def test_add_boundary_package_points_advanced_packages_to_their_tool(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_boundary_package

    name = _flow_model(tmp_path, "advptr")
    with pytest.raises(ValueError, match="add_advanced_package"):
        _impl_add_boundary_package(name, "SFR", {0: []}, None)


def test_advanced_packages_count_as_boundaries_in_model_status(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_advanced_package, _impl_summarise_model

    name = _flow_model(tmp_path, "advsum")
    _impl_add_advanced_package(
        name, "SFR", SFR_PACKAGEDATA, SFR_CONNECTIONS, {0: [[0, "INFLOW", 5.0]]}
    )
    boundaries = _impl_summarise_model(name).get("boundary_types", [])
    assert "SFR" in boundaries


def test_advanced_package_tool_through_the_mcp_layer(tmp_path):
    import asyncio
    import json

    from groundwater_mcp.server import mcp

    name = _flow_model(tmp_path, "advmcp")
    result = asyncio.run(
        mcp.call_tool(
            "add_advanced_package",
            {
                "model": name,
                "package": "MAW",
                "packagedata": MAW_PACKAGEDATA,
                "connectiondata": MAW_CONNECTIONS,
                "perioddata": {"0": [[0, "RATE", -1.0]]},
            },
        )
    )
    payload = json.loads(result[0].text)
    assert payload["package"] == "MAW"

    bad = json.loads(
        asyncio.run(
            mcp.call_tool(
                "add_advanced_package",
                {"model": name, "package": "NOPE", "packagedata": [[0]]},
            )
        )[0].text
    )
    assert bad["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# MVR — water mover (R2.4)
# ---------------------------------------------------------------------------


def _mover_model(tmp_path, name: str, well_mover: bool = True) -> str:
    from groundwater_mcp.tools import builder

    _flow_model(tmp_path, name)
    builder._impl_add_boundary_package(
        name, "WEL", {0: [[[0, 1, 0], -2.0]]},
        {"mover": True} if well_mover else None, pname="wel_0",
    )
    builder._impl_add_advanced_package(
        name, "SFR",
        [
            [0, [0, 1, 1], 10.0, 5.0, 0.001, 9.0, 1.0, 1e-3, 0.03, 1, 1.0, 0],
            [1, [0, 1, 2], 10.0, 5.0, 0.001, 8.9, 1.0, 1e-3, 0.03, 1, 1.0, 0],
        ],
        [[0, -1], [1, 0]],
        {0: [[0, "INFLOW", 0.0]]},
        options={"mover": True},
        pname="sfr_0",
    )
    return name


@requires_mf6
def test_mvr_moves_well_water_to_the_stream(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_mvr_package

    name = _mover_model(tmp_path, "mvrok")
    result = _impl_add_mvr_package(
        name, ["wel_0", "sfr_0"], {0: [["wel_0", 0, "sfr_0", 0, "FACTOR", 1.0]]}
    )
    assert result["counts"] == {"maxmvr": 1, "maxpackages": 2}
    wb = _run_and_balance(name)
    assert any("MVR" in t or "TO-MVR" in t for t in _terms(wb)), _terms(wb)


def test_mvr_rejects_unknown_and_non_mover_packages(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_mvr_package

    name = _mover_model(tmp_path, "mvrbad", well_mover=False)
    with pytest.raises(ValueError, match="nope"):
        _impl_add_mvr_package(name, ["nope", "sfr_0"], {0: [["nope", 0, "sfr_0", 0, "FACTOR", 1.0]]})
    with pytest.raises(ValueError, match="mover"):
        _impl_add_mvr_package(
            name, ["wel_0", "sfr_0"], {0: [["wel_0", 0, "sfr_0", 0, "FACTOR", 1.0]]}
        )


def test_mvr_validates_the_record_shape(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_mvr_package

    name = _mover_model(tmp_path, "mvrshape")
    with pytest.raises(ValueError, match="FACTOR"):
        _impl_add_mvr_package(
            name, ["wel_0", "sfr_0"], {0: [["wel_0", 0, "sfr_0", 0, "HALF", 1.0]]}
        )
    with pytest.raises(ValueError, match="not in packages"):
        _impl_add_mvr_package(
            name, ["wel_0"], {0: [["wel_0", 0, "sfr_0", 0, "FACTOR", 1.0]]}
        )
