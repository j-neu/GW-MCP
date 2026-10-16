"""jobs.py — in-process job registry for long-running tool calls (7e-A3).

Long-running tools (MODFLOW 6 runs, PEST++ calibration) execute in a
background thread so the MCP call returns a job id immediately instead of
blocking until the client timeout. ``get_job_status`` reports the running
job's progress parsed live from the files the process writes (the ``.lst``
for MF6, the ``.iobj`` / ``.phi.actual.csv`` for PEST++); ``cancel_job``
terminates the underlying process.

Status transitions: ``running`` → ``succeeded`` | ``failed`` | ``cancelled``.
The worker thread only moves a still-``running`` job forward, so a
cancellation is never overwritten by a late success.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Seconds without a change in a running job's progress before get_status flags
# it ``possibly_stalled``. Informational only: a slow PEST++ iteration or one
# long MF6 time step looks identical to a hang, so nothing is killed.
STALL_AFTER_S = 900.0


def _now() -> float:
    """Monotonic clock (an indirection so tests can drive it)."""
    return time.monotonic()


STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


@dataclass
class Job:
    """One background job: its worker thread, process handle, and progress."""

    job_id: str
    model: str
    kind: str
    target: Callable[[Job], dict] | None = None
    process: Any = None
    progress_fn: Callable[[Job], dict] | None = None
    on_cancel: Callable[[Job], Any] | None = None
    status: str = STATUS_RUNNING
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: dict | None = None
    error: str | None = None
    stall_after_s: float = STALL_AFTER_S
    last_progress_key: str | None = field(default=None, repr=False)
    last_progress_change: float = field(default=0.0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(end - self.started_at, 2)


_jobs: dict[str, Job] = {}


def _new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def submit(
    model: str,
    kind: str,
    target: Callable[[Job], dict],
    process: Any = None,
    progress_fn: Callable[[Job], dict] | None = None,
    on_cancel: Callable[[Job], Any] | None = None,
) -> Job:
    """Start a background job and return its handle.

    Parameters
    ----------
    model:
        Registered model name the job operates on.
    kind:
        Job kind, e.g. ``"mf6"``, ``"glm"`` or ``"ies"``.
    target:
        ``target(job)`` runs the blocking work and returns the result dict.
    process:
        The subprocess handle ``cancel`` terminates (may be ``None``).
    progress_fn:
        ``progress_fn(job)`` returns a progress dict shown by ``get_status``
        while the job runs.
    on_cancel:
        ``on_cancel(job)`` runs after ``cancel`` has terminated the process
        tree, to undo any workspace mutation a killed process left behind
        (e.g. deleting a substitute input file). Exceptions are reported in the
        ``cancel`` result, not raised, so cancellation always succeeds.

    Returns
    -------
    Job
        The registered job (use ``job.job_id`` as the handle).
    """
    job = Job(
        job_id=_new_job_id(),
        model=model,
        kind=kind,
        target=target,
        process=process,
        progress_fn=progress_fn,
        on_cancel=on_cancel,
    )
    _jobs[job.job_id] = job

    def _run() -> None:
        try:
            result = target(job)
            with job._lock:
                job.result = result
                if job.status == STATUS_RUNNING:
                    job.status = STATUS_SUCCEEDED
        except Exception as exc:  # noqa: BLE001 — surfaced in get_status
            with job._lock:
                job.error = str(exc)
                if job.status == STATUS_RUNNING:
                    job.status = STATUS_FAILED
        finally:
            with job._lock:
                job.finished_at = time.monotonic()
                job.target = None

    threading.Thread(target=_run, daemon=True).start()
    return job


def get_status(job_id: str) -> dict:
    """Return the current status and (for finished jobs) the result of a job.

    Raises
    ------
    KeyError
        If no job with ``job_id`` is registered.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise KeyError(
            f"No job with id '{job_id}' found. start_run / start_calibration "
            "return job ids."
        )
    result: dict = {
        "job_id": job.job_id,
        "model": job.model,
        "kind": job.kind,
        "status": job.status,
        "elapsed_s": job.elapsed_s,
    }
    if job.status == STATUS_RUNNING:
        progress: dict = {}
        if job.progress_fn is not None:
            try:
                progress = job.progress_fn(job) or {}
            except Exception:
                progress = {}
            if progress:
                result["progress"] = progress
        # Idle time = how long the observed progress has been unchanged. The
        # first observation starts the clock (a job first polled late is not
        # assumed idle since its start).
        key = repr(sorted(progress.items(), key=lambda kv: str(kv[0])))
        now = _now()
        if job.last_progress_key is None or key != job.last_progress_key:
            job.last_progress_key = key
            job.last_progress_change = now
        idle = round(now - job.last_progress_change, 2)
        result["idle_s"] = idle
        result["possibly_stalled"] = idle > job.stall_after_s
        if result["possibly_stalled"]:
            result["stall_note"] = (
                f"No change in progress for {idle:.0f} s. A single long step "
                "can look like this; if it persists, call cancel_job and use "
                "the synchronous runner (run_pestpp_glm / run_pestpp_ies / "
                "run_simulation), which is the reliable path."
            )
    if job.status in (STATUS_SUCCEEDED, STATUS_FAILED):
        result["result"] = job.result
    if job.error:
        result["error"] = job.error
    return result


def _terminate_process_tree(proc: Any) -> None:
    """Terminate ``proc`` and all of its descendants.

    Killing only the direct child leaves grandchildren orphaned: pestpp's
    forward-model chain spawns a python wrapper which spawns ``mf6.exe``, and
    an orphaned ``mf6.exe`` keeps running (spinning at 100 % CPU) and
    file-locking the workspace — stalling every later run (modeB rerun-6
    finding). Windows: ``taskkill /T /F`` walks the child tree. POSIX: kill
    the process group (requires the job process to have been spawned with
    ``start_new_session=True``). Test doubles without a real ``pid`` fall
    back to ``kill``/``terminate``.
    """
    import os
    import signal
    import subprocess
    import sys

    pid = getattr(proc, "pid", None)
    if pid is not None:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                )
                return
            os.killpg(pid, signal.SIGKILL)
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def cancel(job_id: str) -> dict:
    """Cancel a running job and terminate its process tree.

    Returns ``{"job_id", "status"}`` — ``status`` is ``"cancelled"`` when the
    job was running, or the terminal status when it had already finished. When
    a running job has an ``on_cancel`` hook, it runs after the process tree is
    terminated; a hook failure is reported as ``restore_error``.

    Raises
    ------
    KeyError
        If no job with ``job_id`` is registered.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise KeyError(
            f"No job with id '{job_id}' found. start_run / start_calibration "
            "return job ids."
        )
    with job._lock:
        if job.status != STATUS_RUNNING:
            return {"job_id": job_id, "status": job.status, "note": "job already finished"}
        job.status = STATUS_CANCELLED
        job.finished_at = time.monotonic()
    if job.process is not None:
        _terminate_process_tree(job.process)
    result: dict = {"job_id": job_id, "status": STATUS_CANCELLED}
    if job.on_cancel is not None:
        try:
            job.on_cancel(job)
        except Exception as exc:  # noqa: BLE001 — cancellation must still succeed
            result["restore_error"] = str(exc)
    return result
