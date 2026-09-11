"""Zoned NPF K multiplier parameterisation tests (`setup_calibration` scope="zones")."""

from __future__ import annotations

import csv  # noqa: F401
import subprocess
import sys

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


def test_round_sig_array_rounds_to_significant_figures():
    from groundwater_mcp.tools.calibration import _round_sig_array

    out = _round_sig_array(np.array([0.0502921, 0.1676449, 60.96001]), 6)
    assert list(out) == pytest.approx([0.0502921, 0.1676449, 60.96])


def test_derive_zones_groups_equal_values_and_sorts():
    from groundwater_mcp.tools.calibration import _derive_zones

    zids, zones = _derive_zones(np.array([5.0, 1.0, 5.0, 1.0, 1.0]), max_zones=10)
    assert zones == [(1.0, 3), (5.0, 2)]
    assert list(zids) == [2, 1, 2, 1, 1]


def test_derive_zones_excludes_nonpositive_and_nan():
    from groundwater_mcp.tools.calibration import _derive_zones

    zids, zones = _derive_zones(np.array([1.0, -0.0, 0.0, np.nan, 2.0]), max_zones=10)
    assert zones == [(1.0, 1), (2.0, 1)]
    assert zids[1] == 0 and zids[2] == 0 and zids[3] == 0


def test_derive_zones_raises_when_no_positive_cells():
    from groundwater_mcp.tools.calibration import _derive_zones

    with pytest.raises(ValueError, match="no positive"):
        _derive_zones(np.array([0.0, -1.0]), max_zones=10)


def test_derive_zones_raises_over_cap():
    from groundwater_mcp.tools.calibration import _derive_zones

    with pytest.raises(ValueError, match="max_zones"):
        _derive_zones(np.array([1.0, 2.0, 3.0]), max_zones=2)


def _write_mult_files(tmp_path, base, zone, mult):
    base_p = tmp_path / "k_base.dat"
    zone_p = tmp_path / "k_zone.dat"
    mult_p = tmp_path / "k_mult.dat"
    out_p = tmp_path / "k.dat"
    np.savetxt(base_p, np.asarray(base, dtype=float).reshape(-1), fmt="%.10g")
    np.savetxt(zone_p, np.asarray(zone, dtype=int).reshape(-1), fmt="%d")
    np.savetxt(mult_p, np.asarray(mult, dtype=float).reshape(-1), fmt="%.10g")
    return base_p, zone_p, mult_p, out_p


def test_apply_k_multipliers_scales_zoned_cells_only(tmp_path):
    from groundwater_mcp.tools.calibration import _apply_k_multipliers

    base_p, zone_p, mult_p, out_p = _write_mult_files(
        tmp_path,
        base=[2.0, 2.0, 2.0, 2.0],
        zone=[0, 1, 2, 1],
        mult=[3.0, 10.0],
    )
    k = _apply_k_multipliers(base_p, zone_p, mult_p, out_p)
    # zone 0 fixed; zone1 ×3; zone2 ×10
    assert list(k) == pytest.approx([2.0, 6.0, 20.0, 6.0])
    assert list(np.loadtxt(out_p)) == pytest.approx([2.0, 6.0, 20.0, 6.0])


def test_apply_k_multipliers_identity_at_one(tmp_path):
    from groundwater_mcp.tools.calibration import _apply_k_multipliers

    base_p, zone_p, mult_p, out_p = _write_mult_files(
        tmp_path,
        base=[0.05, 0.05, 60.96],
        zone=[1, 1, 2],
        mult=[1.0, 1.0],
    )
    k = _apply_k_multipliers(base_p, zone_p, mult_p, out_p)
    assert list(k) == pytest.approx([0.05, 0.05, 60.96])


def _build_zoned_model(tmp_path, name="zoned_model"):
    """1 layer × 5 × 5, two K zones (1.0 in cols 0, 5.0 elsewhere)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 50.0, [30.0])
    k = np.full((1, 5, 5), 5.0)
    k[0, :, 0] = 1.0
    _impl_add_npf_package(name, icelltype=0, k=k, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(5)] + [[[0, r, 4], 10.0] for r in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def test_normalise_zoned_builds_global_indices(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert norm["grid"]["type"] == "DIS"
    assert len(norm["zones"]) == 2
    assert [z["base_k"] for z in norm["zones"]] == [1.0, 5.0]
    assert norm["zones"][0]["name"] == "k_z1"
    assert norm["zones"][1]["name"] == "k_z2"
    assert norm["zones"][0]["n_cells"] == 5
    assert norm["zones"][1]["n_cells"] == 20
    assert norm["zones"][0]["initial"] == 1.0
    assert norm["zone_map"].reshape(5, 5)[0, 0] == 1
    assert norm["zone_map"].reshape(5, 5)[0, 1] == 2


def test_normalise_zoned_requires_layer(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="requires 'layer'"):
        _normalise_zoned_parameterisation(
            name, {"k": {"target": "npf:k", "scope": "zones"}}
        )


def test_normalise_zoned_raises_on_no_positive_layer(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="out of range"):
        _normalise_zoned_parameterisation(
            name, {"k": {"target": "npf:k", "scope": "zones", "layer": 9}}
        )


def test_normalise_zoned_raises_on_name_too_long(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="12"):
        _normalise_zoned_parameterisation(
            name, {"averylongprefix": {"target": "npf:k", "scope": "zones", "layer": 0}}
        )


def test_normalise_zoned_raises_on_max_zones(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="max_zones"):
        _normalise_zoned_parameterisation(
            name,
            {"k": {"target": "npf:k", "scope": "zones", "layer": 0, "max_zones": 1}},
        )


def test_normalise_zoned_disv_layer(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_disv_package
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = "zoned_disv"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    vertices = [[0, 0.0, 0.0], [1, 100.0, 0.0], [2, 100.0, 100.0], [3, 0.0, 100.0]]
    cell2d = [[0, 33.3, 33.3, 3, 0, 1, 2], [1, 66.6, 66.6, 3, 0, 2, 3]]
    _impl_add_disv_package(name, 1, vertices, cell2d, [50.0, 50.0], [[40.0, 40.0]])
    _impl_add_npf_package(name, icelltype=0, k=np.array([[1.0, 4.0]]), k33=None, save_flows=True)
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert norm["grid"]["type"] == "DISV"
    assert norm["grid"]["ncpl"] == 2
    assert [z["base_k"] for z in norm["zones"]] == [1.0, 4.0]


def test_generate_zone_mult_tpl_has_one_wide_token_per_zone(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _impl_generate_zone_mult_tpl,
        _normalise_zoned_parameterisation,
    )

    name = _build_zoned_model(tmp_path)
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    out = _impl_generate_zone_mult_tpl(name, norm["zones"], "zoned_model_k_mult.dat")
    text = open(out["tpl_path"]).read().splitlines()
    assert text[0].strip() == "ptf ~"
    # exactly one token line per zone
    assert len(text) == 1 + len(norm["zones"])
    assert "k_z1" in text[1] and "k_z2" in text[2]
    # tokens are wide (>= 15 chars of content)
    for line in text[1:]:
        assert len(line) - 2 >= 15


def _mf6_available():
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")


def test_generate_forward_wrapper_default_unchanged(tmp_path):
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper

    if not _mf6_available():
        pytest.skip("MODFLOW 6 binary not installed")
    name = _build_zoned_model(tmp_path)
    out = _generate_forward_wrapper(name)
    body = open(out["wrapper_path"]).read()
    assert "_apply_k_multipliers" not in body


@requires_mf6
def test_generate_forward_wrapper_multiplier_applies_k(tmp_path):
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper
    from groundwater_mcp.utils.model_store import get_gwf
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_zoned_model(tmp_path)
    gwf_name = get_gwf(name).name
    ws = resolve_workspace(name)
    base = np.full(25, 2.0)
    zone = np.zeros(25, dtype=int)
    zone[:5] = 1
    zone[5:] = 2
    np.savetxt(ws / f"{gwf_name}_k_base.dat", base, fmt="%.10g")
    np.savetxt(ws / f"{gwf_name}_k_zone.dat", zone, fmt="%d")
    np.savetxt(ws / f"{gwf_name}_k_mult.dat", np.array([3.0, 5.0]), fmt="%.10g")

    out = _generate_forward_wrapper(name, multiply_k=True)
    proc = subprocess.run(
        [sys.executable, out["wrapper_path"]], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    k = np.loadtxt(ws / f"{gwf_name}_k.dat")
    assert list(k[:5]) == pytest.approx([6.0] * 5)
    assert list(k[5:]) == pytest.approx([10.0] * 20)
