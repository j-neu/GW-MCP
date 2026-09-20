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
import datetime
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyemu
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_csub_package,
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


# The elapsed-day axis of the calibration test models: ``start_date_time`` is
# fixed so an elapsed time (0.0, 366.0, ...) maps to a calendar date.
_MODEL_START_DATE = "1904-01-01"


def _csub_model(tmp_path, name="model", nlay=2, k33=True):
    """A small DIS model carrying NPF ``k``/``k33`` (the Task 2 helper shape).

    The default GWF name is ``model`` so the generated external arrays are
    ``model_k.dat`` / ``model_k33.dat``.
    """
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "FEET", "DAYS")
    _impl_set_simulation(
        name, 1, [1.0], [1], "moderate", start_date_time=_MODEL_START_DATE
    )
    _impl_add_dis_package(name, nlay, 3, 3, 100.0, 100.0, 50.0, [-30.0] * nlay)
    _impl_add_npf_package(
        name,
        icelltype=1,
        k=1.0,
        k33=(0.1 if k33 else None),
        save_flows=True,
        k_units="ft/d",  # FEET model: declare k in its own units (1.0 / 0.1)
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


def _install_csub(tmp_path, name, nlay=None, ninterbeds=None, cg_theta=None):
    """Add a CSUB package with one no-delay interbed per layer (test helper).

    ``ssv_cc``/``sse_cr`` base values are ``0.05``/``0.02`` (the ``_rec``
    defaults in ``test_csub.py``) so selected-column bounds are predictable.
    ``nlay`` defaults to the model's own layer count; ``cg_theta`` defaults to
    ``0.2`` per layer.
    """
    if nlay is None:
        nlay = int(get_gwf(name).dis.nlay.array)
    if ninterbeds is None:
        ninterbeds = nlay
    records = [
        [
            i,
            [min(i, nlay - 1), 0, 0],
            "nodelay",
            0.0,
            0.5,
            2.0,
            0.05,
            0.02,
            0.35,
            1e-6,
            0.0,
        ]
        for i in range(ninterbeds)
    ]
    res = _impl_add_csub_package(
        name,
        packagedata=records,
        cg_theta=list(cg_theta) if cg_theta is not None else [0.2] * nlay,
        cg_ske_cr=[1e-5] * nlay,
    )
    assert "error" not in res, res
    return res


def _register_subsidence_obs(
    tmp_path,
    name,
    dates=None,
    values=None,
    sim_times=None,
    sim_csv=None,
):
    """Register a derived subsidence target and fake the CSUB obs CSV (Task 8).

    The model is not run in these tests, so the CSUB obs CSV the wrapper will
    consume at run time is written by hand. Simulated times default to the
    elapsed days from the model ``start_date_time`` (``1904-01-01``) to each
    observed date, exercising the elapsed-time -> calendar-date conversion
    (Critical 1). Returns ``(dates, values)``.
    """
    from groundwater_mcp.tools.parameterise import (
        _impl_import_subsidence_observations,
    )

    dates = list(dates or ["1904-01-01", "1905-01-01"])
    values = list(values or [0.0, 0.5])
    obs_csv = tmp_path / f"{name}_sub_data.csv"
    with obs_csv.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Date", "Subsidence_ft"])
        for date, value in zip(dates, values):
            writer.writerow([date, value])
    res = _impl_import_subsidence_observations(
        name,
        str(obs_csv),
        time_col="Date",
        value_col="Subsidence_ft",
    )
    assert "error" not in res, res

    sim_times = list(sim_times) if sim_times is not None else [
        float(
            (
                datetime.date.fromisoformat(date)
                - datetime.date.fromisoformat(_MODEL_START_DATE)
            ).days
        )
        for date in dates
    ]
    ws = resolve_workspace(name)
    target = str(sim_csv) if sim_csv else f"{name}.csub.obs.csv"
    with (ws / target).open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "COMPACTION.01", "COMPACTION.02"])
        for sim_time in sim_times:
            writer.writerow([sim_time, 0.1, 0.2])
    return dates, values


def _mf6_available():
    from groundwater_mcp.tools.calibration import _find_mf6_binary

    try:
        _find_mf6_binary()
    except RuntimeError:
        return False
    return True


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
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


# ---------------------------------------------------------------------------
# Target registry: csub:packagedata / csub:cg_theta / csub:cg_ske_cr (Task 7)
# ---------------------------------------------------------------------------


def test_supported_targets_include_csub():
    from groundwater_mcp.tools.calibration import _SUPPORTED_TARGETS

    assert "csub:packagedata" in _SUPPORTED_TARGETS
    assert "csub:cg_theta" in _SUPPORTED_TARGETS
    assert "csub:cg_ske_cr" in _SUPPORTED_TARGETS


def test_setup_calibration_csub_packagedata_columns(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)  # add_csub_package helper
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "ssv": {
                "target": "csub:packagedata",
                "columns": ["ssv_cc", "sse_cr"],
                "lower_factor": 0.05,
                "upper_factor": 20.0,
                "partrans": "none",
            }
        },
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 4  # 2 columns x 2 interbeds
    assert any(t.endswith("packagedata.dat.tpl") for t in res["template_files"])
    assert res["target_files"] == ["model.csub_packagedata.dat"]

    # The template carries one wide token per (column x interbed); every other
    # packagedata field is preserved verbatim.
    tpl = Path(res["template_file"])
    lines = tpl.read_text().splitlines()
    assert lines[0].replace(" ", "") == "ptf~"
    assert len(lines) == 3  # header + 2 interbeds
    names = pyemu.pst_utils.parse_tpl_file(str(tpl))
    assert sorted(names) == [
        "ssv_sse_cr_1",
        "ssv_sse_cr_2",
        "ssv_ssv_cc_1",
        "ssv_ssv_cc_2",
    ]

    pst = pyemu.Pst(res["pst_file"])
    par = pst.parameter_data
    assert len(par) == 4
    assert float(par.loc["ssv_ssv_cc_1", "parval1"]) == pytest.approx(0.05)
    assert float(par.loc["ssv_ssv_cc_1", "parlbnd"]) == pytest.approx(0.05 * 0.05)
    assert float(par.loc["ssv_ssv_cc_1", "parubnd"]) == pytest.approx(0.05 * 20.0)
    assert (par["partrans"] == "none").all()


def test_setup_calibration_multi_target_pst(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "ssv": {
                "target": "csub:packagedata",
                "columns": ["ssv_cc"],
                "layers": [0],
                "lower_factor": 0.05,
                "upper_factor": 20.0,
                "partrans": "none",
            },
            "cgtheta": {
                "target": "csub:cg_theta",
                "scope": "layer",
                "layer": 0,
                "initial": 0.35,
            },
            "k33": {
                "target": "npf:k33",
                "scope": "layer",
                "layer": 0,
                "initial": 0.1,
            },
        },
    )
    assert "error" not in res, res
    assert Path(res["pst_file"]).exists()
    assert res["n_adjustable_parameters"] == 3
    assert len(res["template_files"]) == 3
    assert len(res["target_files"]) == 3
    assert "model.csub_packagedata.dat" in res["target_files"]
    assert "model.csub_cg_theta.dat" in res["target_files"]
    assert "model_k33.dat" in res["target_files"]

    pst = pyemu.Pst(res["pst_file"])
    assert sorted(pst.parameter_data.index) == ["cgtheta", "k33", "ssv_ssv_cc_1"]
    assert len(pst.model_input_data) == 3


def test_setup_calibration_cg_theta_layer_scope(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "cgtheta": {
                "target": "csub:cg_theta",
                "scope": "layer",
                "layer": 1,
                "initial": 0.3,
            }
        },
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 1
    assert res["target_file"] == "model.csub_cg_theta.dat"

    ws = resolve_workspace(name)
    ext = ws / "model.csub_cg_theta.dat"
    assert ext.exists()
    flat = np.loadtxt(ext).reshape(-1)
    # flopy writes the LAYERED array as nrow rows per layer; the requested layer
    # gets its initial value on every cell and layer 0 keeps the base 0.2.
    by_layer = flat.reshape(2, -1)
    assert np.all(by_layer[0] == pytest.approx(0.2))
    assert np.all(by_layer[1] == pytest.approx(0.3))

    pst = pyemu.Pst(res["pst_file"])
    assert float(pst.parameter_data.loc["cgtheta", "parval1"]) == pytest.approx(0.3)


def test_setup_calibration_cg_ske_cr_layer_scope(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "ske": {
                "target": "csub:cg_ske_cr",
                "scope": "layer",
                "layer": 0,
                "initial": 2e-5,
            }
        },
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 1
    assert res["target_file"] == "model.csub_cg_ske_cr.dat"
    ws = resolve_workspace(name)
    flat = np.loadtxt(ws / "model.csub_cg_ske_cr.dat").reshape(-1)
    by_layer = flat.reshape(2, -1)
    assert np.all(by_layer[0] == pytest.approx(2e-5))
    assert np.all(by_layer[1] == pytest.approx(1e-5))


def test_setup_calibration_cg_theta_requires_layer_scope(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    with pytest.raises(ValueError, match="scope"):
        _impl_setup_calibration(
            name,
            {"cgtheta": {"target": "csub:cg_theta", "scope": "all", "initial": 0.3}},
        )


def test_setup_calibration_cg_theta_layer_out_of_range(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    with pytest.raises(ValueError, match="out of range"):
        _impl_setup_calibration(
            name,
            {
                "cgtheta": {
                    "target": "csub:cg_theta",
                    "scope": "layer",
                    "layer": 5,
                    "initial": 0.3,
                }
            },
        )


def test_setup_calibration_csub_packagedata_rejects_unknown_column(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    with pytest.raises(ValueError, match="column"):
        _impl_setup_calibration(
            name,
            {
                "ssv": {
                    "target": "csub:packagedata",
                    "columns": ["bogus"],
                    "partrans": "none",
                }
            },
        )


def test_setup_calibration_csub_packagedata_layers_filter(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "ssv": {
                "target": "csub:packagedata",
                "columns": ["ssv_cc"],
                "layers": [1],
                "partrans": "none",
            }
        },
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 1
    tpl_text = Path(res["template_file"]).read_text()
    # Only the second interbed (layer 1) carries a token.
    assert "ssv_ssv_cc_2" in tpl_text
    assert "ssv_ssv_cc_1" not in tpl_text


def test_setup_calibration_csub_packagedata_pst_substitutes_correct_file(tmp_path):
    """Guard the Task 1 spike's silent no-substitution pitfall.

    The .pst's model-input mapping must name the same file the CSUB package
    opens, and ``write_input_files`` must substitute into *that* file (not a
    basename-stripped copy at the workspace root while the model reads a
    subfolder, and not an un-substituted literal).
    """
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "ssv": {
                "target": "csub:packagedata",
                "columns": ["ssv_cc"],
                "lower_factor": 0.05,
                "upper_factor": 20.0,
                "partrans": "none",
            }
        },
    )
    assert "error" not in res, res
    ws = resolve_workspace(name)
    external = ws / "model.csub_packagedata.dat"
    assert "model.csub_packagedata.dat" in (ws / "model.csub").read_text()

    pst = pyemu.Pst(res["pst_file"])
    pst.parameter_data.loc["ssv_ssv_cc_1", "parval1"] = 0.012
    pst.parameter_data.loc["ssv_ssv_cc_2", "parval1"] = 0.013
    pst.write_input_files(pst_path=str(ws))

    lines = external.read_text().splitlines()
    values = [float(line.split()[-5]) for line in lines]  # ssv_cc is 5th from end
    assert values == pytest.approx([0.012, 0.013])


def test_setup_calibration_csub_packagedata_reexternalises_after_inline_readd(
    tmp_path,
):
    """Regression: an existing target file must not mask an inline package.

    Trigger (Task 7 review): ``setup_calibration`` externalises packagedata,
    then ``add_csub_package`` re-adds the package *inline* while the stale
    external file survives and meta loses ``packagedata_filename``. A second
    ``setup_calibration`` must re-externalise from the package rather than
    short-circuit on ``Path.exists()``, otherwise MF6 reads inline records and
    the .pst substitutes the stale file with zero effect (spike §6.1).
    """
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    spec = {
        "ssv": {
            "target": "csub:packagedata",
            "columns": ["ssv_cc"],
            "lower_factor": 0.05,
            "upper_factor": 20.0,
            "partrans": "none",
        }
    }
    first = _impl_setup_calibration(name, spec)
    assert "error" not in first, first
    ws = resolve_workspace(name)
    external = ws / "model.csub_packagedata.dat"
    assert "OPEN/CLOSE" in (ws / "model.csub").read_text()

    # Re-add the package inline; the stale external file is left in place and
    # meta["csub"] is rewritten without packagedata_filename.
    _install_csub(tmp_path, name)
    assert "packagedata_filename" not in (read_meta(name).get("csub") or {})

    second = _impl_setup_calibration(name, spec)
    assert "error" not in second, second
    csub_text = (ws / "model.csub").read_text()
    assert "OPEN/CLOSE" in csub_text
    assert "model.csub_packagedata.dat" in csub_text
    assert Path(second["template_file"]).name == "model.csub_packagedata.dat.tpl"

    # And the substituted value reaches the exact file the .csub opens.
    pst = pyemu.Pst(second["pst_file"])
    pst.parameter_data.loc["ssv_ssv_cc_1", "parval1"] = 0.019
    pst.parameter_data.loc["ssv_ssv_cc_2", "parval1"] = 0.021
    pst.write_input_files(pst_path=str(ws))
    values = [
        float(line.split()[-5])
        for line in external.read_text().splitlines()
        if line.strip()
    ]
    assert values == pytest.approx([0.019, 0.021])


def test_setup_calibration_csub_packagedata_restores_pristine_baseline(tmp_path):
    """A repeated setup must rebase on the pristine, not the substituted file.

    Trigger (Important 3): a second ``setup_calibration`` after a PEST run read
    the *substituted* external packagedata, so initial values and bounds drifted
    with every rerun.
    """
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    spec = {
        "ssv": {
            "target": "csub:packagedata",
            "columns": ["ssv_cc"],
            "lower_factor": 0.05,
            "upper_factor": 20.0,
            "partrans": "none",
        }
    }
    first = _impl_setup_calibration(name, spec)
    assert "error" not in first, first
    ws = resolve_workspace(name)
    external = ws / "model.csub_packagedata.dat"
    pristine = ws / "model.csub_packagedata_pristine.dat"
    assert pristine.exists()
    base = [
        float(line.split()[-5])
        for line in pristine.read_text().splitlines()
        if line.strip()
    ]
    assert base == pytest.approx([0.05, 0.05])
    current = [
        float(line.split()[-5])
        for line in external.read_text().splitlines()
        if line.strip()
    ]
    assert current == pytest.approx(base)

    # Simulate a PEST run substituting the parameter values into the file.
    pst = pyemu.Pst(first["pst_file"])
    pst.parameter_data.loc["ssv_ssv_cc_1", "parval1"] = 0.5
    pst.parameter_data.loc["ssv_ssv_cc_2", "parval1"] = 0.6
    pst.write_input_files(pst_path=str(ws))
    substituted = [
        float(line.split()[-5])
        for line in external.read_text().splitlines()
        if line.strip()
    ]
    assert substituted == pytest.approx([0.5, 0.6])

    second = _impl_setup_calibration(name, spec)
    assert "error" not in second, second
    restored = [
        float(line.split()[-5])
        for line in external.read_text().splitlines()
        if line.strip()
    ]
    assert restored == pytest.approx(base)
    pst2 = pyemu.Pst(second["pst_file"])
    assert float(pst2.parameter_data.loc["ssv_ssv_cc_1", "parval1"]) == pytest.approx(
        base[0]
    )


def test_add_csub_package_clears_cg_theta_pristine_snapshot(tmp_path):
    """A deliberate cg_theta edit must not be reverted at the next setup.

    Trigger (Important 4): ``_restore_or_snapshot_csub_array`` restored a stale
    ``<gwf>_csub_cg_theta_pristine.npy`` even after ``add_csub_package`` changed
    the array.
    """
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)  # cg_theta 0.2
    _register_head_obs(tmp_path, name)
    spec = {
        "cgtheta": {
            "target": "csub:cg_theta",
            "scope": "layer",
            "layer": 0,
            "initial": 0.2,
        }
    }
    first = _impl_setup_calibration(name, spec)
    assert "error" not in first, first
    ws = resolve_workspace(name)
    snapshot = ws / "model_csub_cg_theta_pristine.npy"
    assert snapshot.exists()
    assert np.load(snapshot) == pytest.approx([0.2, 0.2])

    # Deliberate edit: re-add the package with a new cg_theta. The stale
    # snapshot must be invalidated, or the next setup silently reverts it.
    _install_csub(tmp_path, name, cg_theta=[0.4, 0.4])
    assert not snapshot.exists()

    spec["cgtheta"]["initial"] = 0.4
    second = _impl_setup_calibration(name, spec)
    assert "error" not in second, second
    by_layer = np.loadtxt(ws / "model.csub_cg_theta.dat").reshape(-1).reshape(2, -1)
    # Layer 1 is not parameterised, so its base value is the real regression
    # signal: only an invalidated snapshot yields 0.4 rather than the stale 0.2.
    assert np.all(by_layer[0] == pytest.approx(0.4))
    assert np.all(by_layer[1] == pytest.approx(0.4))
    pst2 = pyemu.Pst(second["pst_file"])
    assert float(pst2.parameter_data.loc["cgtheta", "parval1"]) == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Task 8 — derived time-series observations (obs_source="derived")
# ---------------------------------------------------------------------------

def test_derived_time_key_matches_calendar_dates_not_numeric_years():
    from groundwater_mcp.tools.calibration import _derived_time_key

    # Slash and ISO forms fold to the same calendar date.
    assert _derived_time_key("1/25/1935") == _derived_time_key("1935-01-25")
    assert _derived_time_key("1935-01-25") == "1935-01-25"
    # Critical 1 regression: an elapsed day count must never be read as a year.
    assert _derived_time_key(11347.0) == "num:11347.0"
    assert _derived_time_key(11347.0) != "1134-01-01"
    # With the model start date, an elapsed day count converts to a date.
    assert (
        _derived_time_key(5.0, start_date_time="1935-01-25")
        == "1935-01-30"
    )
    # A setup-time time_map literal wins over the start-date arithmetic.
    assert _derived_time_key(10.0, time_map={"10.0": "2001-03-04"}) == "2001-03-04"
    assert _derived_time_key(0.0) == "num:0.0"
    assert _derived_time_key("nodelay") == "str:nodelay"
    assert _derived_time_key("") is None
    assert _derived_time_key(None) is None


def test_derived_time_axis_matches_elapsed_days_to_non_january_dates(tmp_path):
    """An elapsed-day axis with non-January-1 observations matches every date.

    Mirrors the holdout shape: ``TIME_UNITS DAYS`` with a real start date, so
    the CSUB obs CSV ``time`` column is elapsed days while the observations are
    calendar dates (Critical 1).
    """
    from groundwater_mcp.tools.calibration import _derived_observation_plan
    from groundwater_mcp.tools.builder import _impl_set_simulation

    name = _csub_model(tmp_path, nlay=1)
    # Re-anchor the model to a non-January-1 start date.
    _impl_set_simulation(
        name, 1, [1.0], [1], "moderate", start_date_time="1935-01-25"
    )
    _install_csub(tmp_path, name)
    _register_subsidence_obs(
        tmp_path,
        name,
        dates=["1935-01-25", "1935-05-05"],
        values=[0.1, 0.3],
        sim_times=[0.0, 100.0],
    )

    group = _derived_observation_plan(name)[0]
    assert group["start_date_time"] == "1935-01-25"
    assert group["n_total"] == 2
    assert group["dates"] == ["1935-01-25", "1935-05-05"]
    assert group["skipped"] == []
    assert group["deferred"] is False
    assert group["time_map"]["100.0"] == "1935-05-05"


def test_derived_sum_columns_prefix_and_elastic_exclusion():
    from groundwater_mcp.tools.calibration import _derived_sum_columns

    columns = [
        "time",
        "COMPACTION.01",
        "compaction.02",
        "ELASTIC-COMPACTION.01",
        "INELASTIC-COMPACTION.01",
        "PRECONSTRESS.01",
    ]
    assert _derived_sum_columns(columns, ["compaction"]) == [
        "COMPACTION.01",
        "compaction.02",
    ]


def test_build_derived_obs_interface_tokens_values_and_pif(tmp_path):
    from groundwater_mcp.tools.calibration import _build_derived_obs_interface

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name, values=[0.0, 0.5])
    ws = resolve_workspace(name)

    ins_paths, obs_data, output_files = _build_derived_obs_interface(name, ws)

    assert output_files == ["model_subsidence.csv"]
    assert sorted(obs_data) == ["subsidence_1", "subsidence_2"]
    assert obs_data["subsidence_1"]["obsval"] == pytest.approx(0.0)
    assert obs_data["subsidence_2"]["obsval"] == pytest.approx(0.5)
    assert obs_data["subsidence_2"]["weight"] == pytest.approx(1.0)
    assert obs_data["subsidence_2"]["obgnme"] == "subsidence_obs"

    ins = Path(ins_paths[0])
    assert ins.name == "model_subsidence.csv.ins"
    text = ins.read_text()
    assert text.startswith("pif")
    assert "!subsidence_1!" in text
    # The pif reads the header then one data row per matched observation; the
    # `~,~` group discards the leading `time` field (spike semantics).
    assert "l1 ~,~" in text
    assert pyemu.pst_utils.parse_ins_file(str(ins)) == [
        "subsidence_1",
        "subsidence_2",
    ]


def test_derived_observation_plan_skips_unmatched_dates(tmp_path):
    from groundwater_mcp.tools.calibration import _derived_observation_plan

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    # Only the 1904-01-01 simulated row exists (elapsed day 0), so the
    # 1905-01-01 observation must skip.
    _register_subsidence_obs(tmp_path, name, sim_times=[0.0])

    plan = _derived_observation_plan(name)
    assert len(plan) == 1
    group = plan[0]
    assert group["n_total"] == 2
    assert group["dates"] == ["1904-01-01"]
    assert group["skipped"] == ["1905-01-01"]
    assert group["tokens"] == ["subsidence_1"]
    assert group["deferred"] is False


def test_derived_observation_plan_defers_without_sim_csv(tmp_path):
    from groundwater_mcp.tools.calibration import _derived_observation_plan

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name)
    # Remove the faked CSUB obs CSV: the model has not run, so matching defers.
    (resolve_workspace(name) / "model.csub.obs.csv").unlink()

    group = _derived_observation_plan(name)[0]
    assert group["deferred"] is True
    assert group["dates"] == ["1904-01-01", "1905-01-01"]
    assert group["skipped"] == []


def test_setup_calibration_derived_obs_builds_pif(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name)

    res = _impl_setup_calibration(
        name,
        {
            "ssv": {
                "target": "csub:packagedata",
                "columns": ["ssv_cc"],
                "partrans": "none",
            }
        },
        obs_source="derived",
    )
    assert "error" not in res, res
    text = Path(res["instruction_file"]).read_text()
    assert text.startswith("pif")
    assert text.count("l") >= 2  # one read per observed date


def test_setup_calibration_derived_reports_skips_and_pst(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name, sim_times=[0.0])

    res = _impl_setup_calibration(
        name,
        {
            "ssv": {
                "target": "csub:packagedata",
                "columns": ["ssv_cc"],
                "partrans": "none",
            }
        },
        obs_source="derived",
    )
    assert "error" not in res, res
    report = res["derived_observations"]["subsidence"]
    assert report["n_observations"] == 2
    assert report["n_matched"] == 1
    assert report["skipped_dates"] == ["1905-01-01"]
    assert report["matching_deferred"] is False
    assert report["output_csv"] == "model_subsidence.csv"
    assert res["obs_source"] == "derived"
    assert res["n_observations"] == 1

    pst = pyemu.Pst(res["pst_file"])
    assert list(pst.observation_data.index) == ["subsidence_1"]
    assert res["forward_wrapper"] is not None
    assert res["model_command"][0]
    assert Path(res["forward_wrapper"]).exists()


def test_setup_calibration_derived_requires_registered_observations(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    with pytest.raises(ValueError, match="derived"):
        _impl_setup_calibration(
            name,
            {
                "ssv": {
                    "target": "csub:packagedata",
                    "columns": ["ssv_cc"],
                    "partrans": "none",
                }
            },
            obs_source="derived",
        )


def test_needs_forward_wrapper_true_for_derived_observations(tmp_path, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    # A space-free MF6 path would normally need no wrapper.
    monkeypatch.setattr(cal, "_find_mf6_binary", lambda: r"C:\bin\mf6.exe")
    assert cal._needs_forward_wrapper(name) is False

    _register_subsidence_obs(tmp_path, name)
    assert cal._needs_forward_wrapper(name) is True


def test_generate_forward_wrapper_injects_stdlib_derived_step(tmp_path):
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name)

    out = _generate_forward_wrapper(name)
    body = Path(out["wrapper_path"]).read_text()

    assert "DERIVED = [" in body
    assert "def _derive_subsidence():" in body
    assert "model_subsidence.csv" in body
    assert "numpy" not in body
    assert "pandas" not in body
    assert "groundwater_mcp" not in body


def test_derived_wrapper_step_materialises_subsidence_csv(tmp_path):
    """Execute only the generated stdlib derived step against a faked obs CSV."""
    from groundwater_mcp.tools.calibration import _derived_wrapper_source

    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name)
    ws = resolve_workspace(name)

    imports, step = _derived_wrapper_source(name)
    assert "import csv" in imports
    script = tmp_path / "run_derived.py"
    script.write_text(
        "import os\n"
        + imports
        + f"WS = {str(ws)!r}\n"
        + step
    )
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    derived = (ws / "model_subsidence.csv").read_text().splitlines()
    assert derived[0] == "time,sim-subsidence-ft"
    assert len(derived) == 3  # header + one row per observation
    assert derived[1].endswith(",0.3")
    assert derived[2].endswith(",0.3")




