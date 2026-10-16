"""R3.3: one MF6/PEST++ process per workspace, detached stdin, orphan cleanup.

The background ``start_calibration`` stall had two recorded shapes: a
timed-out call retried by the client spawned a second pestpp in the same
workspace (the two collided at "loading parcov"), and a frozen forward-run
chain left a pestpp tree spinning after the job was abandoned. These tests pin
the fences: a workspace claim that refuses a second process (in this server or
an orphan from an earlier one, via a lock file carrying the PID), children
spawned with stdin detached from the server's MCP stdio pipe, and cleanup of
the claim and the process tree on finish, cancel, explicit release and exit.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from groundwater_mcp.tools.builder import _impl_create_model
from groundwater_mcp.utils import jobs
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_job_control import _BRABANT_IOBJ, _FakeProc, _poll


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


@pytest.fixture
def cal_model(tmp_path, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    name = "lock_model"
    ws = tmp_path / name
    _impl_create_model(name, str(ws), "METERS", "DAYS")
    (ws / "test.pst").write_text("dummy pst\n")
    (ws / "test.iobj").write_text(_BRABANT_IOBJ)
    monkeypatch.setattr(cal, "_find_pestpp_binary", lambda _exe: "/fake/pestpp-glm")
    return name


# ---------------------------------------------------------------------------
# the claim itself
# ---------------------------------------------------------------------------


def test_second_claim_on_a_workspace_is_refused(tmp_path):
    jobs.claim_workspace(tmp_path, "pestpp-glm")
    try:
        with pytest.raises(jobs.WorkspaceBusyError, match="pestpp-glm"):
            jobs.claim_workspace(tmp_path, "pestpp-ies")
    finally:
        jobs.release_workspace(tmp_path)
    jobs.claim_workspace(tmp_path, "pestpp-ies")
    jobs.release_workspace(tmp_path)


def test_lock_file_with_a_live_foreign_pid_blocks_the_workspace(tmp_path):
    orphan = _sleeper()
    try:
        (tmp_path / jobs.LOCK_FILE).write_text(
            json.dumps({"pid": orphan.pid, "holder": "pestpp-da", "server_pid": -1})
        )
        with pytest.raises(jobs.WorkspaceBusyError, match=str(orphan.pid)):
            jobs.claim_workspace(tmp_path, "pestpp-glm")
    finally:
        orphan.kill()
        orphan.wait()


def test_stale_lock_file_with_a_dead_pid_is_cleared(tmp_path):
    (tmp_path / jobs.LOCK_FILE).write_text(
        json.dumps({"pid": _dead_pid(), "holder": "pestpp-da", "server_pid": -1})
    )
    jobs.claim_workspace(tmp_path, "pestpp-glm")
    jobs.release_workspace(tmp_path)
    assert not (tmp_path / jobs.LOCK_FILE).exists()


def test_attach_pid_writes_the_lock_file_and_release_removes_it(tmp_path):
    jobs.claim_workspace(tmp_path, "pestpp-glm")
    jobs.attach_pid(tmp_path, 4321)
    data = json.loads((tmp_path / jobs.LOCK_FILE).read_text())
    assert data["pid"] == 4321 and data["holder"] == "pestpp-glm"
    jobs.release_workspace(tmp_path)
    assert not (tmp_path / jobs.LOCK_FILE).exists()


def test_force_release_terminates_the_recorded_orphan(tmp_path):
    orphan = _sleeper()
    (tmp_path / jobs.LOCK_FILE).write_text(
        json.dumps({"pid": orphan.pid, "holder": "pestpp-da", "server_pid": -1})
    )
    out = jobs.force_release_workspace(tmp_path)
    assert out["terminated_pid"] == orphan.pid
    assert orphan.wait(timeout=15) is not None
    assert not (tmp_path / jobs.LOCK_FILE).exists()
    jobs.claim_workspace(tmp_path, "pestpp-glm")
    jobs.release_workspace(tmp_path)


# ---------------------------------------------------------------------------
# start_calibration / start_run / synchronous runners honour the claim
# ---------------------------------------------------------------------------


def test_start_calibration_twice_refuses_the_second(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    fake = _FakeProc(delay=3.0)
    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: fake)
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    try:
        with pytest.raises(jobs.WorkspaceBusyError, match=first["job_id"]):
            cal._impl_start_calibration(cal_model, "test.pst", method="ies")
    finally:
        jobs.cancel(first["job_id"])


def test_finished_job_releases_the_workspace(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeProc(delay=0.2))
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    assert _poll(first["job_id"])["status"] == "succeeded"
    second = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    assert _poll(second["job_id"])["status"] == "succeeded"


def test_cancelled_job_releases_the_workspace(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeProc(delay=5.0))
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    jobs.cancel(first["job_id"])
    second = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    jobs.cancel(second["job_id"])


def test_failed_spawn_releases_the_workspace(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    def _boom(args, cwd):
        raise OSError("spawn failed")

    monkeypatch.setattr(cal, "_run_process", _boom)
    with pytest.raises(OSError):
        cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    jobs.claim_workspace(resolve_workspace(cal_model), "check")
    jobs.release_workspace(resolve_workspace(cal_model))


def test_synchronous_pestpp_run_is_refused_while_a_job_runs(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeProc(delay=3.0))
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    try:
        with pytest.raises(jobs.WorkspaceBusyError):
            cal._run_pestpp_blocking(["/fake/pestpp-glm", "test.pst"], resolve_workspace(cal_model))
    finally:
        jobs.cancel(first["job_id"])


def test_start_run_is_refused_while_a_calibration_runs(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal
    import groundwater_mcp.tools.runner as runner

    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeProc(delay=3.0))
    monkeypatch.setattr(runner, "_run_process", lambda args, cwd: _FakeProc(delay=0.1))
    monkeypatch.setattr(runner, "_find_mf6_binary", lambda: "/fake/mf6")
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    try:
        with pytest.raises(jobs.WorkspaceBusyError):
            runner._impl_start_run(cal_model)
    finally:
        jobs.cancel(first["job_id"])


def test_run_pestpp_blocking_returns_output_and_releases(tmp_path):
    import groundwater_mcp.tools.calibration as cal

    res = cal._run_pestpp_blocking([sys.executable, "-c", "print('hello')"], tmp_path)
    assert res.returncode == 0 and "hello" in res.stdout
    jobs.claim_workspace(tmp_path, "check")
    jobs.release_workspace(tmp_path)


# ---------------------------------------------------------------------------
# children never inherit the server's stdin (the MCP stdio pipe)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["calibration", "runner"])
def test_background_spawn_detaches_stdin(module, monkeypatch, tmp_path):
    import importlib

    mod = importlib.import_module(f"groundwater_mcp.tools.{module}")
    seen: dict = {}

    class _Recorder:
        def __init__(self, args, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(mod.subprocess, "Popen", _Recorder)
    mod._run_process(["x"], str(tmp_path))
    assert seen.get("stdin") is subprocess.DEVNULL


def test_blocking_spawn_detaches_stdin(tmp_path):
    import groundwater_mcp.tools.calibration as cal

    code = "import sys; sys.stdout.write(repr(sys.stdin.read()))"
    t0 = time.monotonic()
    res = cal._run_pestpp_blocking([sys.executable, "-c", code], tmp_path)
    assert res.stdout == "''"
    assert time.monotonic() - t0 < 30


# ---------------------------------------------------------------------------
# tool surface
# ---------------------------------------------------------------------------


def _call(tool: str, **args) -> dict:
    import asyncio

    from groundwater_mcp.server import mcp

    result = asyncio.run(mcp.call_tool(tool, args))
    return json.loads(next(c.text for c in reversed(result) if hasattr(c, "text")))


def test_busy_workspace_surfaces_as_workspace_busy_error_code(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeProc(delay=3.0))
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    try:
        out = _call("start_calibration", model=cal_model, pst_file="test.pst")
        assert out.get("code") == "WORKSPACE_BUSY", out
        out = _call("run_pestpp_glm", model=cal_model, pst_file="test.pst")
        assert out.get("code") == "WORKSPACE_BUSY", out
    finally:
        jobs.cancel(first["job_id"])


def test_release_workspace_lock_tool_terminates_an_orphan(cal_model):
    ws = resolve_workspace(cal_model)
    orphan = _sleeper()
    (ws / jobs.LOCK_FILE).write_text(
        json.dumps({"pid": orphan.pid, "holder": "pestpp-da", "server_pid": -1})
    )
    out = _call("release_workspace_lock", model=cal_model)
    assert out["terminated_pid"] == orphan.pid, out
    assert orphan.wait(timeout=15) is not None


def test_release_workspace_lock_tool_refuses_a_live_job(cal_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal

    monkeypatch.setattr(cal, "_run_process", lambda args, cwd: _FakeProc(delay=3.0))
    first = cal._impl_start_calibration(cal_model, "test.pst", method="glm")
    try:
        out = _call("release_workspace_lock", model=cal_model)
        assert out.get("code") == "WORKSPACE_BUSY" and "cancel_job" in out["message"]
    finally:
        jobs.cancel(first["job_id"])


# ---------------------------------------------------------------------------
# server exit leaves no orphans
# ---------------------------------------------------------------------------


def test_terminate_running_jobs_kills_live_process_trees(tmp_path):
    proc = _sleeper()

    def _target(_job):
        proc.wait()
        return {}

    job = jobs.submit("exit_model", "glm", _target, process=proc, workspace=tmp_path)
    jobs.terminate_running_jobs()
    assert proc.wait(timeout=15) is not None
    assert _poll(job.job_id)["status"] == "cancelled"
