"""PESTPP-DA engine exposure (run_pestpp_da).

The engine wrapper runs the DA binary against a caller-supplied DA-ready PST.
These tests pin the option injection (num_reals -> da_num_reals, da_* option
passthrough, noptmax = iterations/cycle and NOT the ensemble size) and the
return schema without launching a real assimilation run.
"""

from __future__ import annotations

import csv
import time
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
    _impl_add_sto_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.calibration import (
    _impl_run_pestpp_da,
    _impl_setup_calibration,
    _impl_setup_da_control,
    _impl_start_calibration,
    _pestpp_progress,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils import jobs
from groundwater_mcp.utils.workspace import resolve_workspace


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
        name,
        str(pst_file),
        num_reals=7,
        da_options={"da_observation_cycle_table": "obs_cycle_tbl.csv"},
        noptmax=0,
    )

    assert "pestpp-da" in str(seen["cmd"][0])
    assert result["num_reals"] == 7
    assert result["noptmax"] == 0
    assert result["converged"] is True

    pst = pyemu.Pst(str(pst_file))
    # Ensemble size is da_num_reals, NOT noptmax (which is iterations/cycle).
    assert str(pst.pestpp_options["da_num_reals"]) == "7"
    assert int(pst.control_data.noptmax) == 0
    assert str(pst.pestpp_options["da_observation_cycle_table"]) == "obs_cycle_tbl.csv"


def test_run_pestpp_da_noptmax_is_not_ensemble_size(tmp_path, monkeypatch):
    """Regression: noptmax must not be overwritten from num_reals, and an
    omitted noptmax leaves the DA-ready PST's own value untouched (7f-DA)."""
    name, pst_file = _model_with_pst(tmp_path, "dapst3")
    from groundwater_mcp.tools import calibration as cal

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(cal.subprocess, "run", lambda *a, **k: _Result())

    _impl_run_pestpp_da(name, str(pst_file), num_reals=25)

    pst = pyemu.Pst(str(pst_file))
    # Fixture PST was built with setup_calibration(noptmax=1); it must survive.
    assert int(pst.control_data.noptmax) == 1
    assert str(pst.pestpp_options["da_num_reals"]) == "25"


def test_run_pestpp_da_omitted_num_reals_preserves_pst_ensemble(tmp_path, monkeypatch):
    """An omitted num_reals must preserve the DA-ready PST's da_num_reals.

    Regression (Task 5): the default used to be 50, silently clobbering the
    ensemble size a setup_da_control(num_reals=N) PST carried, even when no
    prior file capped the run.
    """
    name, pst_file = _model_with_pst(tmp_path, "dapst4")
    pst = pyemu.Pst(str(pst_file))
    pst.pestpp_options["da_num_reals"] = 6
    pst.write(str(pst_file))

    from groundwater_mcp.tools import calibration as cal

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(cal.subprocess, "run", lambda *a, **k: _Result())

    result = _impl_run_pestpp_da(name, str(pst_file))

    pst_after = pyemu.Pst(str(pst_file))
    assert str(pst_after.pestpp_options["da_num_reals"]) == "6"
    assert result["num_reals"] == 6


def test_run_pestpp_da_missing_pst_raises(tmp_path):
    name, _ = _model_with_pst(tmp_path, "dapst2")
    with pytest.raises(FileNotFoundError):
        _impl_run_pestpp_da(name, "does_not_exist.pst", num_reals=5)


# ---------------------------------------------------------------------------
# Task 8 — DA background job (start_calibration method="da")
# ---------------------------------------------------------------------------

_DA_PHI_CSV = (
    "cycle,iteration,mean,standard_deviation,min,max,0,1,base\n"
    "0,0,339.18,20.0,300.0,380.0,300.0,380.0,0\n"
    "0,1,300.17,13.04,288.0,315.0,288.0,315.0,0\n"
    "1,0,110.01,5.0,100.0,120.0,100.0,120.0,0\n"
    "1,1,64.11,2.0,60.0,68.0,60.0,68.0,0\n"
)


class _FakeDAProc:
    """A ``subprocess.Popen`` stand-in for the DA background job.

    ``stdout`` blocks for ``delay`` seconds so the worker thread is still
    running while a test polls ``get_job_status`` (live-progress coverage).
    """

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.killed = False
        self.returncode = 0

    @property
    def stdout(self):
        if self.delay:
            time.sleep(self.delay)
        return iter(("da ok\n",))

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _da_ready_pst(tmp_path, name: str = "dastart") -> tuple[str, Path]:
    """A DA-ready PST from setup_da_control, for the background-job tests."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    _impl_add_dis_package(name, 1, 3, 3, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    _impl_add_sto_package(name, iconvert=0, ss=1e-4, sy=None, steady_state=[], save_flows=True)
    _impl_add_boundary_package(
        name, "CHD", {"0": [[[0, 0, 0], 40.0], [[0, 2, 2], 10.0]]}, None
    )
    _impl_add_oc_package(name, None, None, None, None)

    obs_csv = tmp_path / f"{name}_obs.csv"
    with open(obs_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cell"])
        writer.writerow(["S1", "2020-01-01", 30.0, "0 0 1"])
        writer.writerow(["S2", "2020-01-01", 29.0, "0 1 1"])
        writer.writerow(["S3", "2020-01-01", 28.0, "0 2 1"])
    _impl_import_obs_from_csv(
        name, str(obs_csv), "HEAD", "site", "date", "value", None, None, 0,
        cellid_col="cell",
    )
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles={
            "S1": {0: 32.0, 1: 33.0},
            "S2": {0: 30.0, 1: 31.0},
            "S3": {0: 28.0, 1: 29.0},
        },
        num_reals=4,
        noptmax=1,
    )
    assert "error" not in res, res
    return name, Path(res["pst_file"])


def test_pestpp_progress_da_from_global_phi_csv(tmp_path):
    """The "da" engine reports the per-cycle post-update phi."""
    (tmp_path / "case.global.phi.actual.csv").write_text(_DA_PHI_CSV)
    progress = _pestpp_progress(tmp_path, "case", "da")
    assert progress["engine"] == "da"
    assert progress["n_cycles"] == 2
    assert progress["cycle"] == 1
    assert abs(progress["latest_phi"] - 64.11) < 1e-6


def test_start_calibration_da_background_job(tmp_path, monkeypatch):
    """start_calibration(method="da") runs pestpp-da in the background."""
    import groundwater_mcp.tools.calibration as cal

    name, pst_file = _da_ready_pst(tmp_path, "dastart")
    ws = resolve_workspace(name)
    (ws / f"{pst_file.stem}.global.phi.actual.csv").write_text(_DA_PHI_CSV)

    fake = _FakeDAProc(delay=1.0)
    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda exe: f"/fake/{exe}")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: fake)

    result = _impl_start_calibration(name, str(pst_file), method="da", num_reals=4)
    assert result["status"] == "running"
    assert result["kind"] == "da"
    job_id = result["job_id"]

    # num_reals maps to da_num_reals (the DA ensemble size)
    assert str(pyemu.Pst(str(pst_file)).pestpp_options["da_num_reals"]) == "4"

    # while the fake still runs, the job reports live per-cycle progress
    deadline = time.monotonic() + 5.0
    saw_progress = False
    while time.monotonic() < deadline:
        status = jobs.get_status(job_id)
        if "progress" in status:
            assert status["progress"]["engine"] == "da"
            assert status["progress"]["n_cycles"] == 2
            saw_progress = True
            break
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert saw_progress, "DA job never reported live progress while running"

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        status = jobs.get_status(job_id)
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert status["status"] == "succeeded", status

    body = status["result"]
    assert body["converged"] is True
    assert body["cycles"] == 2
    assert body["num_reals"] == 4
    assert body["noptmax"] == 1
    assert abs(body["final_phi_mean"] - float(np.mean([300.17, 64.11]))) < 1e-6
    assert abs(body["final_phi_std"] - float(np.std([300.17, 64.11]))) < 1e-6


def test_start_calibration_rejects_unknown_method_before_workspace():
    """An unknown method is still rejected up front (before any workspace IO)."""
    import groundwater_mcp.tools.calibration as cal

    with pytest.raises(ValueError, match="method"):
        cal._impl_start_calibration("no_such_model", "x.pst", method="sweep")


def _wait(job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = jobs.get_status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running after {timeout}s")


def test_start_calibration_da_omitted_num_reals_preserves_pst(tmp_path, monkeypatch):
    """An omitted num_reals must not resize a setup_da_control PST (was 50)."""
    import groundwater_mcp.tools.calibration as cal

    name, pst_file = _da_ready_pst(tmp_path, "dapreserve")
    ws = resolve_workspace(name)
    (ws / f"{pst_file.stem}.global.phi.actual.csv").write_text(_DA_PHI_CSV)
    # setup_da_control(num_reals=4) wrote da_num_reals 4
    assert str(pyemu.Pst(str(pst_file)).pestpp_options["da_num_reals"]) == "4"

    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda exe: f"/fake/{exe}")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeDAProc())

    result = _impl_start_calibration(name, str(pst_file), method="da")
    status = _wait(result["job_id"])
    assert status["status"] == "succeeded", status
    assert status["result"]["num_reals"] == 4  # preserved, not defaulted to 50
    assert str(pyemu.Pst(str(pst_file)).pestpp_options["da_num_reals"]) == "4"


def test_start_calibration_da_provided_num_reals_writes_pst(tmp_path, monkeypatch):
    """An explicit num_reals still writes da_num_reals."""
    import groundwater_mcp.tools.calibration as cal

    name, pst_file = _da_ready_pst(tmp_path, "dawrite")
    ws = resolve_workspace(name)
    (ws / f"{pst_file.stem}.global.phi.actual.csv").write_text(_DA_PHI_CSV)

    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda exe: f"/fake/{exe}")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeDAProc())

    result = _impl_start_calibration(name, str(pst_file), method="da", num_reals=7)
    status = _wait(result["job_id"])
    assert status["status"] == "succeeded", status
    assert status["result"]["num_reals"] == 7
    assert str(pyemu.Pst(str(pst_file)).pestpp_options["da_num_reals"]) == "7"


def test_start_calibration_ies_omitted_num_reals_preserves_pst(tmp_path, monkeypatch):
    """The IES path gets the same preserve-when-omitted semantics as DA."""
    import groundwater_mcp.tools.calibration as cal

    name, pst_file = _model_with_pst(tmp_path, "iespreserve")
    pst = pyemu.Pst(str(pst_file))
    pst.pestpp_options["ies_num_reals"] = 6
    pst.write(str(pst_file))

    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda exe: f"/fake/{exe}")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeDAProc())

    status = _wait(_impl_start_calibration(name, str(pst_file), method="ies")["job_id"])
    assert status["status"] == "succeeded", status
    assert status["result"]["num_reals"] == 6
    assert str(pyemu.Pst(str(pst_file)).pestpp_options["ies_num_reals"]) == "6"

    status = _wait(
        _impl_start_calibration(name, str(pst_file), method="ies", num_reals=9)["job_id"]
    )
    assert status["result"]["num_reals"] == 9
    assert str(pyemu.Pst(str(pst_file)).pestpp_options["ies_num_reals"]) == "9"
