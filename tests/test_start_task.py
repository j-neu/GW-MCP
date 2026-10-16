"""R3.4: heavy tools run as background tasks through start_task."""

from __future__ import annotations

import time

import pytest

from groundwater_mcp.tools.runner import _impl_start_task
from groundwater_mcp.utils import jobs
from tests.test_solver_controls import _model


def _wait(job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = jobs.get_status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.2)
    raise AssertionError("task did not finish")


def test_check_model_runs_as_a_background_task(tmp_path):
    name = _model(tmp_path, "task1")
    started = _impl_start_task(name, "check_model")
    assert started["status"] == "running" and started["kind"] == "task:check_model"
    done = _wait(started["job_id"])
    assert done["status"] == "succeeded", done
    result = done["result"]
    assert result["task"] == "check_model" and result["model"] == name


def test_task_failure_surfaces_as_job_error(tmp_path):
    name = _model(tmp_path, "task2")
    started = _impl_start_task(
        name,
        "assign_top_from_raster",
        {"raster": str(tmp_path / "missing.tif"), "layer": 0},
    )
    done = _wait(started["job_id"])
    assert done["status"] == "failed", done
    assert done["error"]


def test_unknown_task_and_arguments_fail_before_starting(tmp_path):
    name = _model(tmp_path, "task3")
    with pytest.raises(ValueError, match="Unknown task"):
        _impl_start_task(name, "delete_everything")
    with pytest.raises(ValueError, match="Unknown argument"):
        _impl_start_task(name, "check_model", {"bogus": 1})


def test_tasks_on_one_model_run_one_at_a_time(tmp_path):
    from groundwater_mcp.tools import runner

    name = _model(tmp_path, "task4")
    active = {"now": 0, "max": 0}

    import threading

    guard = threading.Lock()

    def slow(model):
        with guard:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.4)
        with guard:
            active["now"] -= 1
        return {"ok": True}

    original = runner._BACKGROUND_TASKS["flush_model"]
    runner._BACKGROUND_TASKS["flush_model"] = (__name__, "_slow_for_test")
    globals()["_slow_for_test"] = slow
    try:
        a = _impl_start_task(name, "flush_model")
        b = _impl_start_task(name, "flush_model")
        assert _wait(a["job_id"])["status"] == "succeeded"
        assert _wait(b["job_id"])["status"] == "succeeded"
    finally:
        runner._BACKGROUND_TASKS["flush_model"] = original
        globals().pop("_slow_for_test", None)
    assert active["max"] == 1
