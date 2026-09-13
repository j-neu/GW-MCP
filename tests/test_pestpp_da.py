"""PESTPP-DA engine exposure (run_pestpp_da).

The engine wrapper runs the DA binary against a caller-supplied DA-ready PST.
These tests pin the option injection (num_reals -> noptmax, da_* passthrough)
and the return schema without launching a real assimilation run.
"""

from __future__ import annotations

import csv
from pathlib import Path

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
from groundwater_mcp.tools.calibration import _impl_run_pestpp_da, _impl_setup_calibration
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv


def _model_with_pst(tmp_path, name: str = "dapst"):
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    _impl_add_dis_package(name, 1, 2, 2, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    _impl_add_boundary_package(name, "CHD", {"0": [[[0, 0, 0], 40.0], [[0, 1, 1], 10.0]]}, None)
    _impl_add_oc_package(name, None, None, None, None)

    obs_csv = tmp_path / f"{name}_obs.csv"
    with open(obs_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        writer.writerow(["S1", "2020-01-01", 30.0, 50.0, 50.0])
        writer.writerow(["S2", "2020-01-01", 20.0, 150.0, 150.0])
    _impl_import_obs_from_csv(
        name, str(obs_csv), "HEAD", "site", "date", "value", "x", "y", 0
    )
    res = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 2.0}},
        obs_source="model",
        noptmax=1,
    )
    assert "error" not in res, res
    return name, Path(res["pst_file"])


def test_run_pestpp_da_injects_options(tmp_path, monkeypatch):
    name, pst_file = _model_with_pst(tmp_path, "dapst")
    from groundwater_mcp.tools import calibration as cal

    seen = {}

    class _Result:
        returncode = 0
        stdout = "da ok"
        stderr = ""

    def fake_run(cmd, cwd=None, capture_output=True, text=True):
        seen["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(cal.subprocess, "run", fake_run)

    result = _impl_run_pestpp_da(
        name, str(pst_file), num_reals=7, da_options={"da_cycle": 1}
    )

    assert "pestpp-da" in str(seen["cmd"][0])
    assert result["num_reals"] == 7
    assert result["converged"] is True

    pst = pyemu.Pst(str(pst_file))
    assert int(pst.control_data.noptmax) == 7
    assert str(pst.pestpp_options["da_cycle"]) == "1"


def test_run_pestpp_da_missing_pst_raises(tmp_path):
    name, _ = _model_with_pst(tmp_path, "dapst2")
    with pytest.raises(FileNotFoundError):
        _impl_run_pestpp_da(name, "does_not_exist.pst", num_reals=5)
