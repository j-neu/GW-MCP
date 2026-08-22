"""7f-I tests — reduce surface area.

I1: plot tools return the PNG natively (ImageContent); view_image removed.
I2: sentence-transformers is an optional extra; search_docs falls back.
I3: describe_package returns the package spec from flopy introspection.
I4: add_disv_package rejects oversized inline payloads (gridprops_file).
I5: export_reproducible_script emits a pure-flopy rebuild script.

See tasks.md § 7f Tier I.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from groundwater_mcp.server import mcp
from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.docs import _impl_describe_package, _impl_search_docs
from groundwater_mcp.tools.runner import _find_mf6_binary
from groundwater_mcp.tools.spec import _impl_export_reproducible_script


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)


def _build_small_model(tmp_path, name: str = "i_model") -> str:
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 1, 5, 5, 500.0, 500.0, 50.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(5)] + [[[0, r, 4], 10.0] for r in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


# ---------------------------------------------------------------------------
# I2 — semantic extra optional
# ---------------------------------------------------------------------------


def test_semantic_search_unavailable_returns_envelope(monkeypatch):
    import groundwater_mcp.tools.docs as docs_module

    monkeypatch.setattr(docs_module, "_semantic_available", lambda: False)
    monkeypatch.setattr(docs_module, "_maybe_start_autobuild", lambda: True)
    monkeypatch.setattr(docs_module, "_text_search", lambda *a, **k: [{"path": "x", "score": 1.0}])

    result = _impl_search_docs("river", method="semantic")
    assert result.get("error") is True
    assert result["code"] == "SEMANTIC_SEARCH_UNAVAILABLE"

    # method='auto' falls back to text
    result = _impl_search_docs("river", method="auto")
    assert result.get("error") is not True
    assert result["method"] == "text"


# ---------------------------------------------------------------------------
# I3 — describe_package
# ---------------------------------------------------------------------------


def test_describe_package_riv():
    result = _impl_describe_package("RIV")
    assert result["package"] == "RIV"
    fields = set(result["stress_period_data"])
    assert {"cellid", "stage", "cond", "rbot"}.issubset(fields)


def test_describe_package_unknown_raises():
    with pytest.raises(ValueError, match="Unknown package"):
        _impl_describe_package("NOTAPKG")


# ---------------------------------------------------------------------------
# I4 — DISV inline payload guard
# ---------------------------------------------------------------------------


def _disv_grid_props(n_cells: int) -> tuple[list, list]:
    vertices = [[i, float(i), 0.0] for i in range(n_cells * 3)]
    cell2d = [[i, float(i), 0.0, 3, 3 * i, 3 * i + 1, 3 * i + 2] for i in range(n_cells)]
    return vertices, cell2d


def test_disv_inline_payload_rejected_when_oversized(tmp_path):
    from groundwater_mcp.server import mcp as server_mcp
    from groundwater_mcp.tools.builder import PayloadTooLargeError, _impl_add_disv_package

    name = "disv_big"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    vertices, cell2d = _disv_grid_props(51_000)

    with pytest.raises(PayloadTooLargeError, match="gridprops_file"):
        _impl_add_disv_package(name, 1, vertices, cell2d, [0.0] * 51000, [[0.0] * 51000])

    # MCP layer returns the PAYLOAD_TOO_LARGE envelope
    result = asyncio.run(server_mcp.call_tool("add_disv_package", {
        "model": name,
        "nlay": 1,
        "vertices": vertices[:3],
        "cell2d": [[0, 0.0, 0.0, 3, 0, 1, 2]] * 51000,
        "top": [0.0] * 51000,
        "botm": [[0.0] * 51000],
    }))
    payload = json.loads(result[0].text)
    assert payload.get("error") is True
    assert payload["code"] == "PAYLOAD_TOO_LARGE"


def test_disv_gridprops_file_accepted(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_disv_package, _impl_set_simulation

    name = "disv_file"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    vertices, cell2d = _disv_grid_props(4)
    props = {
        "vertices": vertices,
        "cell2d": cell2d,
        "top": [0.0, 0.0, 0.0, 0.0],
        "botm": [[0.0, 0.0, 0.0, 0.0]],
    }
    gridprops = tmp_path / "gridprops.json"
    gridprops.write_text(json.dumps(props))

    result = _impl_add_disv_package(
        name, 1, [], [], [], [], gridprops_file=str(gridprops)
    )
    assert "error" not in result
    assert result["grid_type"] == "DISV"
    assert result["ncpl"] == 4


# ---------------------------------------------------------------------------
# I5 — reproducible script
# ---------------------------------------------------------------------------


@requires_mf6
def test_export_reproducible_script_rebuilds_heads(tmp_path):
    import subprocess
    import sys

    from groundwater_mcp.tools.postprocess import _impl_read_heads
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_small_model(tmp_path)
    _impl_run_simulation(name, silent=True)
    expected = _impl_read_heads(name, kstpkper=[0, 0], layer=0, include_values=True)["values"]

    result = _impl_export_reproducible_script(name)
    assert "error" not in result
    script = Path(result["script_file"])
    assert script.exists()

    # Run the emitted script in a clean workspace (no MCP dependency).
    clean = tmp_path / "clean_ws"
    clean.mkdir()
    (clean / "run.py").write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    env = dict(__import__("os").environ)
    subprocess.run(
        [sys.executable, "run.py"],
        cwd=str(clean),
        check=True,
        capture_output=True,
        env=env,
        timeout=120,
    )
    # The script built a runnable model; run it and compare heads.
    import flopy.mf6 as mf6_mod
    import flopy.utils as fu

    sim = mf6_mod.MFSimulation.load(sim_ws=str(clean), verbosity_level=0)
    sim.run_simulation(silent=True)
    hf = fu.HeadFile(str(clean / f"{name}.hds"))
    heads = hf.get_data(kstpkper=(0, 0))
    assert np.allclose(heads[0], expected, atol=1e-6)


# ---------------------------------------------------------------------------
# I1 — view_image removed; plot returns image content (covered in
# test_postprocess; here just verify view_image is gone from the registry)
# ---------------------------------------------------------------------------


def test_view_image_no_longer_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "view_image" not in names
    assert "plot_heads_map" in names
