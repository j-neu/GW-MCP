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
