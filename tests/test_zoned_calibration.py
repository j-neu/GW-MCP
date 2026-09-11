"""Zoned NPF K multiplier parameterisation tests (`setup_calibration` scope="zones")."""

from __future__ import annotations

import numpy as np
import pytest


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
