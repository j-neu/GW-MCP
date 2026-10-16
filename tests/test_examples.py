"""The worked examples must keep running end to end (R5.2)."""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import pytest

from groundwater_mcp.tools.calibration import _find_pestpp_binary
from groundwater_mcp.tools.runner import _find_mf6_binary


def _binaries_available() -> bool:
    try:
        _find_mf6_binary()
        _find_pestpp_binary("pestpp-glm")
    except RuntimeError:
        return False
    return True


@pytest.mark.skipif(not _binaries_available(), reason="mf6 / pestpp-glm not installed")
def test_catchment_walkthrough_recovers_the_true_conductivity(capsys):
    path = Path(__file__).resolve().parents[1] / "examples" / "catchment_walkthrough.py"
    spec = importlib.util.spec_from_file_location("catchment_walkthrough", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()

    out = capsys.readouterr().out
    estimate = float(re.search(r"estimate: ([0-9.eE+-]+)", out).group(1))
    assert estimate == pytest.approx(module.TRUE_K, rel=1e-3)
    assert "balanced: True" in out
    after_rmse = float(re.search(r"after calibration\n\s+rmse: ([0-9.eE+-]+)", out).group(1))
    assert after_rmse < 1e-3


@pytest.mark.skipif(
    not _binaries_available() or shutil.which("mp7") is None,
    reason="mf6 / mp7 not installed",
)
def test_capture_zone_example_matches_the_analytical_width():
    path = Path(__file__).resolve().parents[1] / "examples" / "capture_zone.py"
    spec = importlib.util.spec_from_file_location("capture_zone", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = module.main()

    # Particles start on a 100 m spacing, so the captured count can only match
    # W / spacing to within one particle.
    expected = out["analytical_width"] / out["spacing"]
    assert abs(out["captured"] - expected) <= 1.0
    assert out["captured"] >= 1
