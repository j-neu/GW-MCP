"""CSUB calibration target-registry tests (Task 6: ``npf:k33``).

Covers the generalised package-array machinery added by Task 6:

- ``_SUPPORTED_TARGETS`` gains ``npf:k33``.
- ``_impl_rewire_npf_array_external`` / ``_restore_or_snapshot_package_array``
  handle both ``k`` and ``k33`` (the ``k``-named helpers remain aliases).
- ``_normalise_parameterisation`` accepts ``npf:k33`` for the
  ``all``/``layer``/``cells`` scopes; the zones/multiplier normalisers reject
  it (those stay ``npf:k``-only).
- ``setup_calibration`` threads the target keyword through the rewire,
  snapshot and template so a ``npf:k33`` call targets ``<gwf>_k33.dat``.
- ``model_store.clear_k_base_snapshot`` clears both pristine snapshots.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pyemu
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
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.model_store import (
    clear_k_base_snapshot,
    get_gwf,
    read_meta,
)
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csub_model(tmp_path, name="model", nlay=2, k33=True):
    """A small DIS model carrying NPF ``k``/``k33`` (the Task 2 helper shape).

    The default GWF name is ``model`` so the generated external arrays are
    ``model_k.dat`` / ``model_k33.dat``.
    """
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "FEET", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate")
    _impl_add_dis_package(name, nlay, 3, 3, 100.0, 100.0, 50.0, [-30.0] * nlay)
    _impl_add_npf_package(
        name,
        icelltype=1,
        k=1.0,
        k33=(0.1 if k33 else None),
        save_flows=True,
    )
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(3)] + [
        [[0, r, 2], 10.0] for r in range(3)
    ]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _register_head_obs(tmp_path, name, sites=None):
    """Register head observations at interior cells (test_da_control pattern)."""
    sites = sites or {"S1": (0, 1, 1), "S2": (1, 1, 1)}
    csv_path = tmp_path / f"{name}_obs.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cell"])
        for i, (site, cell) in enumerate(sites.items()):
            writer.writerow(
                [site, "2020-01-01", 30.0 - i, " ".join(str(c) for c in cell)]
            )
    _impl_import_obs_from_csv(
        name,
        str(csv_path),
        "HEAD",
        "site",
        "date",
        "value",
        None,
        None,
        0,
        cellid_col="cell",
    )


# ---------------------------------------------------------------------------
# Target registry
# ---------------------------------------------------------------------------


def test_supported_targets_include_k33():
    from groundwater_mcp.tools.calibration import _SUPPORTED_TARGETS

    assert "npf:k33" in _SUPPORTED_TARGETS
    assert "npf:k" in _SUPPORTED_TARGETS


def test_normalise_parameterisation_accepts_k33_scopes(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_parameterisation

    name = _csub_model(tmp_path, nlay=2)
    all_norm = _normalise_parameterisation(
        name, {"k33_1": {"target": "npf:k33", "scope": "all", "initial": 0.1}}
    )
    assert len(all_norm["cell_param"]) == 18

    layer_norm = _normalise_parameterisation(
        name,
        {"k33_1": {"target": "npf:k33", "scope": "layer", "layer": 0, "initial": 0.1}},
    )
    assert len(layer_norm["cell_param"]) == 9
    assert layer_norm["parameters"][0]["target"] == "npf:k33"

    cells_norm = _normalise_parameterisation(
        name,
        {
            "k33_1": {
                "target": "npf:k33",
                "scope": "cells",
                "cells": [[0, 0, 0], [0, 0, 1]],
                "initial": 0.1,
            }
        },
    )
    assert len(cells_norm["cell_param"]) == 2


def test_normalise_parameterisation_k33_missing_array_raises(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_parameterisation

    name = _csub_model(tmp_path, nlay=1, k33=False)
    with pytest.raises(ValueError, match="k33"):
        _normalise_parameterisation(
            name, {"k33_1": {"target": "npf:k33", "scope": "all", "initial": 0.1}}
        )


def test_zoned_parameterisation_rejects_k33(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _csub_model(tmp_path, nlay=2)
    with pytest.raises(ValueError, match="npf:k33"):
        _normalise_zoned_parameterisation(
            name, {"k33_1": {"target": "npf:k33", "scope": "zones", "layer": 0}}
        )


def test_multiplier_parameterisation_rejects_k33(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_multiplier_parameterisation

    name = _csub_model(tmp_path, nlay=2)
    with pytest.raises(ValueError, match="npf:k33"):
        _normalise_multiplier_parameterisation(
            name,
            {"k33_1": {"target": "npf:k33", "scope": "multiplier", "initial": 1.0}},
        )


# ---------------------------------------------------------------------------
# Generalised rewire / snapshot
# ---------------------------------------------------------------------------


def test_rewire_npf_array_external_k33_preserves_arrays(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _impl_rewire_npf_array_external,
        _impl_rewire_npf_k_external,
    )

    name = _csub_model(tmp_path, nlay=2)
    gwf = get_gwf(name)
    k_before = np.asarray(gwf.get_package("npf").k.array, dtype=float).copy()
    k33_before = np.asarray(gwf.get_package("npf").k33.array, dtype=float).copy()

    result = _impl_rewire_npf_array_external(name, "k33")
    assert result["keyword"] == "k33"
    assert result["external_file"] == "model_k33.dat"

    ws = resolve_workspace(name)
    npf_text = (ws / "model.npf").read_text()
    assert "OPEN/CLOSE" in npf_text
    assert "model_k33.dat" in npf_text
    assert (ws / "model_k33.dat").exists()

    gwf = get_gwf(name)
    np.testing.assert_allclose(
        np.asarray(gwf.get_package("npf").k33.array, dtype=float), k33_before
    )
    # k is untouched by the k33 rewire.
    np.testing.assert_allclose(
        np.asarray(gwf.get_package("npf").k.array, dtype=float), k_before
    )

    # The k-named helper remains a thin alias for keyword="k".
    alias = _impl_rewire_npf_k_external(name)
    assert alias["keyword"] == "k"
    assert alias["external_file"] == "model_k.dat"


def test_rewire_npf_array_external_rejects_unknown_keyword(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_rewire_npf_array_external

    name = _csub_model(tmp_path, nlay=1)
    with pytest.raises(ValueError, match="keyword"):
        _impl_rewire_npf_array_external(name, "k22")


def test_restore_or_snapshot_package_array_k33_roundtrip(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _restore_or_snapshot_k_base,
        _restore_or_snapshot_package_array,
    )

    name = _csub_model(tmp_path, nlay=1)
    base = _restore_or_snapshot_package_array(name, "k33")
    np.testing.assert_allclose(base, 0.1)

    snap = resolve_workspace(name) / "model_k33_pristine.npy"
    assert snap.exists()

    gwf = get_gwf(name)
    npf = gwf.get_package("npf")
    npf.k33.set_data(np.full(npf.k33.array.shape, 9.0))
    restored = _restore_or_snapshot_package_array(name, "k33")
    np.testing.assert_allclose(restored, 0.1)
    np.testing.assert_allclose(np.asarray(npf.k33.array, dtype=float), 0.1)

    # The k-named helper is still the keyword="k" alias.
    np.testing.assert_allclose(_restore_or_snapshot_k_base(name), 1.0)


def test_clear_k_base_snapshot_clears_both_arrays(tmp_path):
    from groundwater_mcp.tools.calibration import _restore_or_snapshot_package_array

    name = _csub_model(tmp_path, nlay=1)
    _restore_or_snapshot_package_array(name, "k")
    _restore_or_snapshot_package_array(name, "k33")
    ws = resolve_workspace(name)
    assert (ws / "model_k_pristine.npy").exists()
    assert (ws / "model_k33_pristine.npy").exists()

    assert clear_k_base_snapshot(name, "model") is True
    assert not (ws / "model_k_pristine.npy").exists()
    assert not (ws / "model_k33_pristine.npy").exists()
    assert clear_k_base_snapshot(name, "model") is False


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------


def test_generate_tpl_k33_default_target(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl, _tpl_substitute

    name = _csub_model(tmp_path, nlay=2)
    result = _impl_generate_tpl(
        name,
        {"k33_1": {"target": "npf:k33", "scope": "layer", "layer": 0, "initial": 0.1}},
    )
    assert Path(result["target"]).name == "model_k33.dat"
    tpl = Path(result["tpl_path"])
    assert tpl.name == "model_k33.dat.tpl"

    lines = tpl.read_text().splitlines()
    assert lines[0].lower().startswith("ptf")
    assert len(lines) - 1 == 18  # full external array, layer-major
    for tok in lines[1:10]:
        assert len(tok) - 2 >= 15  # wide fixed-width token
    names = pyemu.pst_utils.parse_tpl_file(str(tpl))
    assert sorted(names) == ["k33_1"]

    # Layer 1 is unparameterised and keeps its base value; layer 0 gets the
    # initial value.
    _tpl_substitute(tpl, Path(result["target"]), {"k33_1": 0.25})
    arr = np.loadtxt(result["target"])
    assert arr.shape == (18,)
    assert np.all(arr[:9] == pytest.approx(0.25))
    assert np.all(arr[9:] == pytest.approx(0.1))


# ---------------------------------------------------------------------------
# setup_calibration end to end (no run)
# ---------------------------------------------------------------------------


def test_setup_calibration_k33_layer_scope(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {"k33_1": {"target": "npf:k33", "scope": "layer", "layer": 0, "initial": 0.1}},
    )
    assert "error" not in res, res
    assert res["target_file"] == "model_k33.dat"
    assert Path(res["pst_file"]).exists()
    assert Path(res["template_file"]).name == "model_k33.dat.tpl"


def test_setup_calibration_k33_pst_uses_initial_and_derinclb(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=1)
    _register_head_obs(tmp_path, name, sites={"S1": (0, 1, 1)})
    res = _impl_setup_calibration(
        name,
        {"k33_1": {"target": "npf:k33", "scope": "all", "initial": 0.2}},
    )
    assert "error" not in res, res

    pst = pyemu.Pst(res["pst_file"])
    par = pst.parameter_data
    assert float(par.loc["k33_1", "parval1"]) == pytest.approx(0.2)
    assert float(par.loc["k33_1", "parlbnd"]) == pytest.approx(0.02)
    assert float(par.loc["k33_1", "parubnd"]) == pytest.approx(2.0)
    assert (pst.parameter_groups["derinclb"] > 0).all()
    assert float(pst.parameter_groups.loc["gwmcp", "derinclb"]) == pytest.approx(0.01)

    # The external array was substituted with the initial value.
    ws = resolve_workspace(name)
    np.testing.assert_allclose(np.loadtxt(ws / "model_k33.dat"), 0.2)
    meta = read_meta(name)
    assert "observations" in meta
