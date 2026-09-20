"""Tests for 7e-A3 — job control (background runs + live progress).

Covers:
  - A3.1  the job registry (submit/poll/cancel) and the start_run /
          get_job_status / cancel_job tools
  - A3.2  MODFLOW 6 progress parsing from the .lst listing file
  - A3.3  PEST++ progress parsing (.iobj for GLM, .phi.actual.csv for IES)

The long-running behaviours are exercised through a fake process stand-in
(``_FakeProc``) injected at the ``_run_process`` seam — a real >5 s model run
is impractical in CI — while the registry, threading, polling, cancellation
and the progress parsers themselves are the real code under test. Real-MF6
integration is covered by the ``requires_mf6`` tests.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from groundwater_mcp.tools.builder import _impl_create_model
from groundwater_mcp.tools.runner import (
    _find_mf6_binary,
    _impl_cancel_job,
    _impl_get_job_status,
    _impl_start_run,
    _parse_mf6_lst_progress,
)
from groundwater_mcp.utils import jobs
from groundwater_mcp.utils.workspace import resolve_workspace


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)


# ---------------------------------------------------------------------------
# Fake process stand-in (a test double for subprocess.Popen)
# ---------------------------------------------------------------------------


class _FakeProc:
    """A ``subprocess.Popen`` stand-in whose ``stdout`` streams *lines* after a
    configurable *delay*. ``kill()`` interrupts the stream promptly so a
    cancelled job drains without waiting out the delay."""

    def __init__(
        self,
        delay: float = 0.5,
        lines: tuple[str, ...] = ("Normal termination of simulation.\n",),
    ) -> None:
        self.delay = delay
        self._lines = tuple(lines)
        self.killed = False
        self.returncode: int | None = None

    @property
    def stdout(self) -> _FakeProc:
        return self

    def __iter__(self):
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if self.killed:
                return
            time.sleep(0.02)
        if self.killed:
            return
        yield from self._lines

    def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0 if not self.killed else 1
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _poll(job_id: str, timeout: float = 10.0) -> dict:
    """Poll get_job_status until the job leaves the running state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = jobs.get_status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running after {timeout}s")


# ---------------------------------------------------------------------------
# A3.1 — the job registry itself
# ---------------------------------------------------------------------------


def test_submit_returns_immediately_and_polls_to_succeeded():
    def slow(_job):
        time.sleep(0.3)
        return {"done": True}

    t0 = time.monotonic()
    job = jobs.submit("test_model", "unit", slow)
    assert time.monotonic() - t0 < 1.0
    assert job.status == "running"

    status = jobs.get_status(job.job_id)
    assert status["status"] == "running"
    assert status["model"] == "test_model"
    assert status["kind"] == "unit"
    assert status["elapsed_s"] >= 0.0

    status = _poll(job.job_id)
    assert status["status"] == "succeeded"
    assert status["result"] == {"done": True}


def test_submit_failed_target_reports_error():
    def boom(_job):
        raise RuntimeError("kaboom")

    job = jobs.submit("test_model", "unit", boom)
    status = _poll(job.job_id)
    assert status["status"] == "failed"
    assert status["error"] == "kaboom"


def test_cancel_job_terminates_running_process():
    proc = _FakeProc(delay=60.0)

    def drain(job):
        for _line in job.process.stdout:
            pass
        return {"returncode": job.process.wait()}

    job = jobs.submit("test_model", "unit", target=drain, process=proc)
    time.sleep(0.1)  # let the worker enter the process
    result = jobs.cancel(job.job_id)
    assert result["status"] == "cancelled"
    assert proc.killed is True
    assert jobs.get_status(job.job_id)["status"] == "cancelled"


def test_get_status_unknown_job_raises():
    with pytest.raises(KeyError):
        jobs.get_status("no_such_job")


def test_cancel_unknown_job_raises():
    with pytest.raises(KeyError):
        jobs.cancel("no_such_job")


def test_cancel_terminates_process_tree(tmp_path):
    """Cancelling a job must terminate the whole process tree.

    The pestpp forward-model chain spawns mf6.exe grandchildren (via the
    python wrapper); killing only the direct child would leave them orphaned
    and spinning at 100 % CPU, file-locking the workspace and stalling every
    subsequent run (modeB rerun-6 finding)."""
    import subprocess
    import sys

    if sys.platform != "win32":
        pytest.skip("tree-kill test targets Windows taskkill; POSIX uses killpg")

    child_pid_file = tmp_path / "child.pid"
    parent_code = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(child_pid_file)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    def drain(job):
        for _line in job.process.stdout:
            pass
        return {"rc": job.process.wait()}

    job = jobs.submit("test_model", "unit", target=drain, process=proc)
    deadline = time.monotonic() + 10.0
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert child_pid_file.exists(), "grandchild never spawned"
    child_pid = int(child_pid_file.read_text().strip())

    result = jobs.cancel(job.job_id)
    assert result["status"] == "cancelled"

    # The grandchild (mf6 stand-in) must be gone, not just the direct child
    gone = False
    for _ in range(100):
        rc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {child_pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        if str(child_pid) not in rc.stdout:
            gone = True
            break
        time.sleep(0.1)
    assert gone, f"grandchild pid {child_pid} still alive after cancel"


# ---------------------------------------------------------------------------
# A3.1 — start_run / get_job_status / cancel_job (fake slow process)
# ---------------------------------------------------------------------------


@pytest.fixture()
def bare_model(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    return model_name


def test_start_run_returns_job_id_immediately_for_slow_model(bare_model, monkeypatch):
    import groundwater_mcp.tools.runner as runner_module

    fake = _FakeProc(delay=6.0)
    monkeypatch.setattr(runner_module, "_find_mf6_binary", lambda: "/fake/mf6")
    monkeypatch.setattr(runner_module, "_run_process", lambda args, cwd: fake)

    t0 = time.monotonic()
    result = _impl_start_run(bare_model)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0
    assert "job_id" in result
    assert result["status"] == "running"
    assert result["kind"] == "mf6"

    status = _poll(result["job_id"], timeout=15.0)
    assert status["status"] == "succeeded"
    assert status["result"]["success"] is True
    assert status["result"]["convergence"] == "converged"
    # the run happened in the background — it took the fake's full delay
    assert status["result"]["elapsed_s"] >= 5.0


def test_start_run_cancel_terminates_process(bare_model, monkeypatch):
    import groundwater_mcp.tools.runner as runner_module

    fake = _FakeProc(delay=60.0)
    monkeypatch.setattr(runner_module, "_find_mf6_binary", lambda: "/fake/mf6")
    monkeypatch.setattr(runner_module, "_run_process", lambda args, cwd: fake)

    result = _impl_start_run(bare_model)
    job_id = result["job_id"]
    time.sleep(0.2)  # let the worker enter the process
    cancelled = _impl_cancel_job(job_id)
    assert cancelled["status"] == "cancelled"
    assert fake.killed is True
    assert _impl_get_job_status(job_id)["status"] == "cancelled"


def test_get_job_status_unknown_job_raises():
    with pytest.raises(KeyError):
        _impl_get_job_status("no_such_job")


def test_cancel_job_unknown_job_raises():
    with pytest.raises(KeyError):
        _impl_cancel_job("no_such_job")


@requires_mf6
def test_start_run_real_model_polls_to_succeeded(tmp_path, model_name):
    """Real MODFLOW 6: start_run returns a job id, the background run
    completes, and the .hds output exists."""
    from groundwater_mcp.tools.builder import (
        _impl_add_boundary_package,
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_add_oc_package,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)

    result = _impl_start_run(model_name)
    status = _poll(result["job_id"], timeout=120.0)
    assert status["status"] == "succeeded"
    assert status["result"]["success"] is True
    assert list(resolve_workspace(model_name).glob("*.hds"))


# ---------------------------------------------------------------------------
# A3.2 — MODFLOW 6 progress parsing from the .lst
# ---------------------------------------------------------------------------

_BRABANT_IOBJ = (
    "iteration,model_runs_completed,total_phi,measurement_phi,regularization_phi,head_obs\n"
    "0,0,3.50288,3.50288,0,3.50288\n"
    "1,17,0.00895693,0.00895693,0,0.00895693\n"
)

_ZENODO_PHI_CSV = (
    "iteration,total_runs,mean,standard_deviation,min,max,0,1,2,3,4,base\n"
    "0,6,98.6668,132.525,0,356.441,83.5876,356.441,100.411,45.4921,6.06965,0\n"
    "1,12,1.05442,1.23767,0,2.81157,0.389781,0.470366,2.81157,0.203169,2.45166,0\n"
    "2,18,0.602587,0.697277,0,1.56577,0.236987,0.26607,1.56577,0.127237,1.41946,0\n"
    "3,24,0.432304,0.497105,0,1.11098,0.173834,0.191072,1.11098,0.0947533,1.02318,0\n"
)


def _multiperiod_lst() -> list[str]:
    """A synthetic 2-period (2 + 3 time steps) MODFLOW 6 listing file shaped
    like real mfsim.lst output (TDIS block + ``Solving:`` markers)."""
    return [
        "                                    MODFLOW 6",
        "                U.S. GEOLOGICAL SURVEY MODULAR HYDROLOGIC MODEL",
        "    2 STRESS PERIOD(S) IN SIMULATION",
        " STRESS PERIOD     LENGTH       TIME STEPS     MULTIPLIER FOR DELT",
        " ----------------------------------------------------------------------------",
        "        1         100.000000          2                    1.000",
        "        2         200.000000          3                    1.000",
        " END OF TDIS PERIODDATA",
        "    Solving:  Stress period:     1    Time step:     1",
        " STRESS PERIOD NO. 1, LENGTH =   100.000000",
        " NUMBER OF TIME STEPS = 2",
        "    Solving:  Stress period:     1    Time step:     2",
        "    Solving:  Stress period:     2    Time step:     1",
        " STRESS PERIOD NO. 2, LENGTH =   200.000000",
        " NUMBER OF TIME STEPS = 3",
        "    Solving:  Stress period:     2    Time step:     2",
        "    Solving:  Stress period:     2    Time step:     3",
        " Normal termination of simulation.",
    ]


def test_parse_mf6_lst_progress_complete_run():
    text = "\n".join(_multiperiod_lst())
    result = _parse_mf6_lst_progress(text)
    assert result["n_stress_periods"] == 2
    assert result["time_steps_per_period"] == [2, 3]
    assert result["total_time_steps"] == 5
    assert result["completed_time_steps"] == 5
    assert result["percent_complete"] == 100.0
    assert result["terminated"] is True
    assert result["current_stress_period"] == 2
    assert result["current_time_step"] == 3


def test_parse_mf6_lst_progress_partial_run():
    lines = _multiperiod_lst()
    text = "\n".join(lines[: lines.index("    Solving:  Stress period:     2    Time step:     1")])
    result = _parse_mf6_lst_progress(text)
    assert result["n_stress_periods"] == 2
    assert result["time_steps_per_period"] == [2, 3]
    assert result["completed_time_steps"] == 2
    assert result["current_stress_period"] == 1
    assert result["current_time_step"] == 2
    assert result["percent_complete"] == 40.0
    assert result["terminated"] is False


def test_parse_mf6_lst_progress_incremental_is_monotonic():
    lines = _multiperiod_lst()
    last = -1.0
    for i in range(1, len(lines) + 1):
        result = _parse_mf6_lst_progress("\n".join(lines[:i]))
        assert result["percent_complete"] >= last - 1e-9, f"regressed at chunk {i}"
        last = result["percent_complete"]


def test_parse_mf6_lst_progress_empty():
    result = _parse_mf6_lst_progress("")
    assert result["n_stress_periods"] == 0
    assert result["total_time_steps"] == 0
    assert result["percent_complete"] == 0.0
    assert result["current_stress_period"] is None


# ---------------------------------------------------------------------------
# A3.3 — PEST++ progress parsing
# ---------------------------------------------------------------------------


def test_pestpp_progress_glm_from_iobj(tmp_path):
    from groundwater_mcp.tools.calibration import _pestpp_progress

    (tmp_path / "mf6brabant.iobj").write_text(_BRABANT_IOBJ)
    progress = _pestpp_progress(tmp_path, "mf6brabant", "glm")
    assert progress["engine"] == "glm"
    assert progress["iteration"] == 1
    assert progress["n_iterations"] == 2
    assert abs(progress["latest_phi"] - 0.00895693) < 1e-6


def test_pestpp_progress_ies_from_phi_csv(tmp_path):
    from groundwater_mcp.tools.calibration import _pestpp_progress

    (tmp_path / "0205.phi.actual.csv").write_text(_ZENODO_PHI_CSV)
    progress = _pestpp_progress(tmp_path, "0205", "ies")
    assert progress["engine"] == "ies"
    assert progress["iteration"] == 3
    assert progress["n_iterations"] == 4
    assert abs(progress["latest_phi"] - 0.432304) < 1e-4


def test_pestpp_progress_ies_without_mean_column(tmp_path):
    from groundwater_mcp.tools.calibration import _pestpp_progress

    (tmp_path / "case.phi.actual.csv").write_text(
        "iteration,total_runs,phi\n0,6,10.0\n1,12,4.0\n"
    )
    progress = _pestpp_progress(tmp_path, "case", "ies")
    assert progress["iteration"] == 1
    assert abs(progress["latest_phi"] - 4.0) < 1e-9


def test_pestpp_progress_missing_files_returns_empty(tmp_path):
    from groundwater_mcp.tools.calibration import _pestpp_progress

    assert _pestpp_progress(tmp_path, "nope", "glm") == {}
    assert _pestpp_progress(tmp_path, "nope", "ies") == {}


# ---------------------------------------------------------------------------
# A3.1/A3.3 — start_calibration background job
# ---------------------------------------------------------------------------


def test_start_calibration_background_progress_and_result(tmp_path, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    name = "cal_job"
    ws = tmp_path / name
    _impl_create_model(name, str(ws), "METERS", "DAYS")
    (ws / "test.pst").write_text("dummy pst\n")
    (ws / "test.iobj").write_text(_BRABANT_IOBJ)

    fake = _FakeProc(delay=1.5)
    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda _exe: "/fake/pestpp-glm")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: fake)

    result = cal._impl_start_calibration(name, "test.pst", method="glm")
    assert result["status"] == "running"
    assert result["kind"] == "glm"
    job_id = result["job_id"]

    # while the fake process still runs, the job reports live phi progress
    deadline = time.monotonic() + 5.0
    saw_progress = False
    while time.monotonic() < deadline:
        status = jobs.get_status(job_id)
        if "progress" in status:
            assert status["progress"]["engine"] == "glm"
            assert status["progress"]["iteration"] == 1
            saw_progress = True
            break
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert saw_progress, "job never reported live progress while running"

    status = _poll(job_id, timeout=10.0)
    assert status["status"] == "succeeded"
    assert status["result"]["converged"] is True
    assert abs(status["result"]["final_phi"] - 0.00895693) < 1e-6
    assert status["result"]["iterations"] == 2


def test_start_calibration_rejects_unknown_method(tmp_path, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    name = "cal_job2"
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    with pytest.raises(ValueError, match="method"):
        cal._impl_start_calibration(name, "test.pst", method="sweep")


def test_start_calibration_accepts_num_workers_and_reports_it(tmp_path, monkeypatch):
    """`num_workers` is part of the run_pestpp_* signature; start_calibration
    must accept it for parity and echo it (PEST++ has no local worker-count
    option, so it must not silently imply parallel execution)."""
    import groundwater_mcp.tools.calibration as cal

    name = "cal_workers"
    ws = tmp_path / name
    _impl_create_model(name, str(ws), "METERS", "DAYS")
    (ws / "test.pst").write_text("dummy pst\n")
    (ws / "test.iobj").write_text(_BRABANT_IOBJ)

    fake = _FakeProc(delay=0.4)
    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda _exe: "/fake/pestpp-glm")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: fake)

    result = cal._impl_start_calibration(name, "test.pst", method="glm", num_workers=4)
    assert result["num_workers"] == 4
    assert "serial" in result["parallelism"].lower()

    status = _poll(result["job_id"], timeout=10.0)
    assert status["status"] == "succeeded"
    assert status["result"]["num_workers"] == 4


def test_start_calibration_rejects_num_workers_below_one(tmp_path):
    import groundwater_mcp.tools.calibration as cal

    name = "cal_workers_bad"
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    with pytest.raises(ValueError, match="num_workers"):
        cal._impl_start_calibration(name, "test.pst", method="glm", num_workers=0)


# ---------------------------------------------------------------------------
# A3.1 — cancellation restores externalised calibration inputs
# ---------------------------------------------------------------------------


def test_cancel_job_runs_on_cancel_hook():
    calls: list[str] = []
    proc = _FakeProc(delay=60.0)

    def drain(job):
        for _line in job.process.stdout:
            pass
        return {"returncode": job.process.wait()}

    job = jobs.submit(
        "test_model",
        "unit",
        target=drain,
        process=proc,
        on_cancel=lambda j: calls.append(j.job_id),
    )
    time.sleep(0.1)  # let the worker enter the process
    jobs.cancel(job.job_id)
    assert calls == [job.job_id], "on_cancel hook did not run exactly once"


def test_on_cancel_hook_not_run_on_success():
    calls: list[str] = []
    job = jobs.submit(
        "test_model",
        "unit",
        target=lambda _j: {"ok": True},
        on_cancel=lambda j: calls.append(j.job_id),
    )
    _poll(job.job_id)
    assert calls == [], "on_cancel must not run for a successful job"


def _build_csub_model(tmp_path, name: str) -> str:
    from groundwater_mcp.tools.builder import (
        _impl_add_boundary_package,
        _impl_add_csub_package,
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_add_oc_package,
        _impl_add_sto_package,
        _impl_set_simulation,
    )

    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "FEET", "DAYS")
    _impl_set_simulation(name, 2, [365.0, 365.0], [1, 1], "simple")
    _impl_add_dis_package(name, 2, 1, 1, 1.0, 1.0, 0.0, [-10.0, -20.0])
    _impl_add_npf_package(name, icelltype=1, k=[1.0, 1.0], k33=[1.0, 1.0], save_flows=True)
    _impl_add_ic_package(name, strt=[-1.0, -1.0])
    _impl_add_sto_package(
        name, iconvert=0, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True
    )
    _impl_add_boundary_package(
        name, "GHB", {0: [[(0, 0, 0), -1.0, 1.0], [(1, 0, 0), -1.0, 1.0]]}, None
    )
    records = [
        [0, [0, 0, 0], "nodelay", 0.0, 0.5, 1.0, 1e-5, 1e-6, 0.2, 1e-6, -1.0],
        [1, [1, 0, 0], "nodelay", 0.0, 0.5, 1.0, 1e-5, 1e-6, 0.2, 1e-6, -1.0],
    ]
    added = _impl_add_csub_package(
        name,
        packagedata=records,
        sgm=[1.7, 1.7],
        sgs=[2.0, 2.0],
        cg_theta=[0.2, 0.2],
        cg_ske_cr=[1e-5, 1e-5],
    )
    assert "error" not in added, added
    _impl_add_oc_package(name, None, None, None, None)
    return name


def test_calibration_cancel_restores_externalised_csub_array(tmp_path, monkeypatch):
    """A killed PEST++ can leave an OPEN/CLOSE substitute file missing, after
    which the model cannot load ("Unable to open file ...csub_cg_theta.dat" —
    6d Target 9 rerun-1). Cancelling must restore it from the base snapshot."""
    import groundwater_mcp.tools.calibration as cal
    from groundwater_mcp.utils import model_store

    name = _build_csub_model(tmp_path, "cancel_csub")
    ws = resolve_workspace(name)
    base = cal._restore_or_snapshot_csub_array(name, "cg_theta")
    ext = cal._impl_rewire_csub_array_external(name, "cg_theta")
    target = ws / ext["external_file"]
    assert target.exists()

    (ws / "case.pst").write_text("dummy pst\n")
    fake = _FakeProc(delay=60.0)
    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda _exe: "/fake/pestpp-glm")
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: fake)

    started = cal._impl_start_calibration(name, "case.pst", method="glm")
    target.unlink()  # the killed forward run left the substitute file missing
    time.sleep(0.1)
    _impl_cancel_job(started["job_id"])

    assert target.exists(), "cancel left the CSUB external array missing"
    np.testing.assert_allclose(np.loadtxt(target), np.ravel(base))
    model_store.invalidate(name)
    assert model_store.get_sim(name) is not None


def test_setup_calibration_heals_empty_externalised_target(tmp_path):
    """A crashed/aborted PEST++ run can leave an externalised target empty while
    the model still OPEN/CLOSEs it, so even a `setup_calibration` re-run fails to
    load (6d Target 9 rerun-2). The restore guard must heal it before any model
    load — asserted via the guard's effect, with validation failing afterwards."""
    import groundwater_mcp.tools.calibration as cal

    name = _build_csub_model(tmp_path, "heal")
    ws = resolve_workspace(name)
    cal._restore_or_snapshot_csub_array(name, "cg_theta")
    ext = cal._impl_rewire_csub_array_external(name, "cg_theta")
    target = ws / ext["external_file"]
    target.write_text("")  # a killed forward run truncated the substitute file

    with pytest.raises(ValueError):
        cal._impl_setup_calibration(name, "not-a-dict", obs_source="derived")

    assert target.read_text().strip(), "setup_calibration did not heal the empty target"
