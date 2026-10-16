"""R3.2: ``sto:ss`` / ``sto:sy`` calibration targets in ``setup_calibration``."""

from __future__ import annotations

import numpy as np
import pyemu
import pytest

from groundwater_mcp.tools.builder import _impl_add_sto_package
from groundwater_mcp.tools.calibration import _SUPPORTED_TARGETS, _impl_setup_calibration
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_csub_calibration import _csub_model, _register_head_obs


def _sto_model(tmp_path, nlay=2):
    name = _csub_model(tmp_path, nlay=nlay)
    _impl_add_sto_package(name, 1, 1e-5, 0.15, [0], True)
    _register_head_obs(tmp_path, name)
    return name


def test_supported_targets_include_sto():
    assert "sto:ss" in _SUPPORTED_TARGETS
    assert "sto:sy" in _SUPPORTED_TARGETS


def test_setup_calibration_sto_ss_layer_scope(tmp_path):
    name = _sto_model(tmp_path)
    res = _impl_setup_calibration(
        name,
        {"ss1": {"target": "sto:ss", "scope": "layer", "layer": 1, "initial": 3e-5}},
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 1
    assert res["target_file"] == "model.sto_ss.dat"

    flat = np.loadtxt(resolve_workspace(name) / "model.sto_ss.dat").reshape(-1)
    by_layer = flat.reshape(2, -1)
    assert np.all(by_layer[0] == pytest.approx(1e-5))
    assert np.all(by_layer[1] == pytest.approx(3e-5))

    pst = pyemu.Pst(res["pst_file"])
    assert float(pst.parameter_data.loc["ss1", "parval1"]) == pytest.approx(3e-5)


def test_setup_calibration_sto_sy_and_k_assemble_one_pst(tmp_path):
    name = _sto_model(tmp_path)
    res = _impl_setup_calibration(
        name,
        {
            "k": {"target": "npf:k", "scope": "all", "initial": 1.0},
            "sy0": {"target": "sto:sy", "scope": "layer", "layer": 0, "initial": 0.2},
        },
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert sorted(pst.parameter_data.index) == ["k", "sy0"]
    assert len(pst.model_input_data) == 2


def test_setup_calibration_sto_missing_package_errors(tmp_path):
    name = _csub_model(tmp_path)
    _register_head_obs(tmp_path, name)
    with pytest.raises(ValueError, match="STO"):
        _impl_setup_calibration(
            name,
            {"ss": {"target": "sto:ss", "scope": "layer", "layer": 0, "initial": 1e-5}},
        )


def _rch_model(tmp_path, kind, values=None):
    from groundwater_mcp.tools.builder import _impl_add_boundary_package

    name = _csub_model(tmp_path, nlay=1)
    if kind == "RCH":
        vals = values or [0.001, 0.001, 0.001]
        recs = [[[0, r, 1], v] for r, v in enumerate(vals)]
        _impl_add_boundary_package(name, "RCH", {"0": recs}, None)
    else:
        arr = np.full((3, 3), 0.001)
        _impl_add_boundary_package(name, "RCHA", {"0": arr.tolist()}, None)
    _register_head_obs(tmp_path, name, sites={"S1": (0, 1, 1)})
    return name


@pytest.mark.parametrize("kind", ["RCH", "RCHA"])
def test_setup_calibration_rch_recharge(tmp_path, kind):
    name = _rch_model(tmp_path, kind)
    res = _impl_setup_calibration(
        name, {"rech": {"target": "rch:recharge", "scope": "all", "initial": 0.002}}
    )
    assert "error" not in res, res
    assert res["target_file"] == "model.rch_0.dat"
    ws = resolve_workspace(name)
    vals = [float(v) for line in (ws / "model.rch_0.dat").read_text().splitlines()
            for v in line.split()[-1:]] if kind == "RCH" else \
        np.loadtxt(ws / "model.rch_0.dat").reshape(-1).tolist()
    assert all(v == pytest.approx(0.002) for v in vals)
    pst = pyemu.Pst(res["pst_file"])
    assert float(pst.parameter_data.loc["rech", "parval1"]) == pytest.approx(0.002)
    assert float(pst.parameter_data.loc["rech", "parlbnd"]) == pytest.approx(0.0002)


def test_rch_recharge_refuses_heterogeneous_field(tmp_path):
    name = _rch_model(tmp_path, "RCH", values=[0.001, 0.002, 0.003])
    with pytest.raises(ValueError, match="uniform"):
        _impl_setup_calibration(
            name, {"rech": {"target": "rch:recharge", "scope": "all", "initial": 0.002}}
        )


def test_rch_cells_scope_keeps_unclaimed_cells_and_tokenises_groups(tmp_path):
    name = _rch_model(tmp_path, "RCH", values=[0.001, 0.002, 0.003])
    res = _impl_setup_calibration(
        name,
        {
            "ra": {"target": "rch:recharge", "scope": "cells", "cells": [[0, 0, 1]], "initial": 0.005},
            "rb": {"target": "rch:recharge", "scope": "cells", "cells": [[0, 1, 1]], "initial": 0.006},
        },
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 2
    ws = resolve_workspace(name)
    vals = [float(line.split()[-1]) for line in (ws / "model.rch_0.dat").read_text().splitlines() if line.strip()]
    assert vals == pytest.approx([0.005, 0.006, 0.003])  # third cell untouched
    tpl = (ws / "model.rch_0.dat.tpl").read_text().splitlines()
    assert "ra" in tpl[1] and "rb" in tpl[2] and "~" not in tpl[3]


def test_rch_cells_scope_rcha_array(tmp_path):
    name = _rch_model(tmp_path, "RCHA")
    res = _impl_setup_calibration(
        name,
        {"rc": {"target": "rch:recharge", "scope": "cells", "cells": [[0, 1, 1], [0, 2, 2]], "initial": 0.004}},
    )
    assert "error" not in res, res
    flat = np.loadtxt(resolve_workspace(name) / "model.rch_0.dat").reshape(3, 3)
    expected = np.full((3, 3), 0.001)
    expected[1, 1] = expected[2, 2] = 0.004
    assert flat == pytest.approx(expected)


def test_rch_cells_scope_rejects_overlap_and_unknown_cells(tmp_path):
    name = _rch_model(tmp_path, "RCH")
    with pytest.raises(ValueError, match="claimed by both"):
        _impl_setup_calibration(
            name,
            {
                "a": {"target": "rch:recharge", "scope": "cells", "cells": [[0, 0, 1]]},
                "b": {"target": "rch:recharge", "scope": "cells", "cells": [[0, 0, 1]]},
            },
        )
    with pytest.raises(ValueError, match="no RCH record"):
        _impl_setup_calibration(
            name,
            {"a": {"target": "rch:recharge", "scope": "cells", "cells": [[0, 2, 2]]}},
        )


def test_readding_rch_clears_snapshot(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_boundary_package

    name = _rch_model(tmp_path, "RCH")
    _impl_setup_calibration(
        name, {"rech": {"target": "rch:recharge", "scope": "all", "initial": 0.002}}
    )
    snap = resolve_workspace(name) / "model_rch_sp0_pristine.npy"
    assert snap.exists()
    _impl_add_boundary_package(name, "RCH", {"0": [[[0, 1, 1], 0.004]]}, None)
    assert not snap.exists()


def test_readding_sto_clears_snapshot_so_new_base_is_used(tmp_path):
    name = _sto_model(tmp_path)
    spec = {"ss": {"target": "sto:ss", "scope": "layer", "layers": [0, 1], "initial": 2e-5}}
    _impl_setup_calibration(name, spec)
    snap = resolve_workspace(name) / "model_csub_ss_pristine.npy"
    assert snap.exists()
    _impl_add_sto_package(name, 1, 5e-5, 0.15, [0], True)
    assert not snap.exists()
