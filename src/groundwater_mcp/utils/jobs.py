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

Workspace claims (R3.3): at most one MF6/PEST++ process runs in a model
workspace at a time. Two pestpp instances in one workspace overwrite each
other's run files (observed as a stall at "loading parcov" after a timed-out
``start_calibration`` was retried). ``claim_workspace`` refuses a second
process in this server, and a lock file carrying the process PID refuses one
while an orphan from an earlier server session is still alive.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
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
    workspace: Path | None = None
    claim_token: str | None = None
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


# ---------------------------------------------------------------------------
# Workspace claims (R3.3)
# ---------------------------------------------------------------------------

LOCK_FILE = ".gwmcp_process.lock"


class WorkspaceBusyError(RuntimeError):
    """Another MF6/PEST++ process already runs in the workspace."""


# resolved workspace path -> {"token", "holder", "job_id"}
_claims: dict[str, dict] = {}
_claims_guard = threading.Lock()


def _key(ws: Path | str) -> str:
    return str(Path(ws).resolve())


def pid_alive(pid: int | None) -> bool:
    """Return True when a process with ``pid`` is still running."""
    if pid is None or int(pid) <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock(ws: Path | str) -> dict | None:
    path = Path(ws) / LOCK_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def claim_workspace(ws: Path | str, holder: str) -> str:
    """Reserve ``ws`` for one process; return the claim token.

    Raises :class:`WorkspaceBusyError` when this server already runs a process
    there, or when the workspace lock file names a process that is still alive
    (an orphan from an earlier server session). A lock file whose process has
    exited is stale and is removed.
    """
    key = _key(ws)
    with _claims_guard:
        held = _claims.get(key)
        if held is not None:
            job = f" (job {held['job_id']})" if held.get("job_id") else ""
            raise WorkspaceBusyError(
                f"A {held['holder']} process is already running in this "
                f"workspace{job}. Wait for it (get_job_status) or stop it "
                "(cancel_job) before starting another; two MF6/PEST++ processes "
                "in one workspace overwrite each other's files."
            )
        lock = _read_lock(ws)
        if lock is not None:
            pid = lock.get("pid")
            if pid_alive(pid):
                raise WorkspaceBusyError(
                    f"A {lock.get('holder', 'MF6/PEST++')} process (pid {pid}) "
                    "left by an earlier server session is still running in this "
                    "workspace. Call release_workspace_lock(model) to terminate "
                    "it, then retry."
                )
            (Path(ws) / LOCK_FILE).unlink(missing_ok=True)
        token = uuid.uuid4().hex
        _claims[key] = {"token": token, "holder": holder, "job_id": None}
        return token


def attach_pid(ws: Path | str, pid: int | None, job_id: str | None = None) -> None:
    """Record the claimed workspace's process PID (and job id) in its lock file."""
    key = _key(ws)
    with _claims_guard:
        held = _claims.get(key)
        if held is None:
            return
        if job_id is not None:
            held["job_id"] = job_id
        holder = held["holder"]
    if pid is not None:
        try:
            (Path(ws) / LOCK_FILE).write_text(
                json.dumps({"pid": int(pid), "holder": holder, "server_pid": os.getpid()})
            )
        except OSError:
            pass


def release_workspace(ws: Path | str, token: str | None = None) -> None:
    """Drop the claim on ``ws`` (only when ``token`` matches, if given)."""
    key = _key(ws)
    with _claims_guard:
        held = _claims.get(key)
        if held is None or (token is not None and held["token"] != token):
            return
        del _claims[key]
    (Path(ws) / LOCK_FILE).unlink(missing_ok=True)


class _PidHandle:
    """Minimal process handle for a PID this server did not spawn."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def kill(self) -> None:
        import signal

        os.kill(self.pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def force_release_workspace(ws: Path | str) -> dict:
    """Terminate the process tree named in the lock file and clear the lock.

    For a process orphaned by an earlier server session. Processes this server
    started are refused: stop those with ``cancel_job`` so their job state and
    input restore stay consistent.
    """
    key = _key(ws)
    with _claims_guard:
        held = _claims.get(key)
    if held is not None:
        raise WorkspaceBusyError(
            f"The workspace is held by this server's job {held.get('job_id')}; "
            "stop it with cancel_job instead."
        )
    lock = _read_lock(ws)
    terminated = None
    if lock:
        pid = lock.get("pid")
        if pid is not None and pid_alive(pid):
            _terminate_process_tree(_PidHandle(int(pid)))
            terminated = int(pid)
    (Path(ws) / LOCK_FILE).unlink(missing_ok=True)
    return {"workspace": str(ws), "terminated_pid": terminated, "lock_cleared": lock is not None}


def submit(
    model: str,
    kind: str,
    target: Callable[[Job], dict],
    process: Any = None,
    progress_fn: Callable[[Job], dict] | None = None,
    on_cancel: Callable[[Job], Any] | None = None,
    workspace: Path | str | None = None,
    claim_token: str | None = None,
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
    workspace, claim_token:
        The workspace claimed with :func:`claim_workspace` for this job's
        process; the claim is released when the job finishes or is cancelled.

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
        workspace=Path(workspace) if workspace is not None else None,
        claim_token=claim_token,
    )
    _jobs[job.job_id] = job
    if job.workspace is not None and claim_token is not None:
        attach_pid(job.workspace, getattr(process, "pid", None), job.job_id)

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
            if job.workspace is not None and job.claim_token is not None:
                release_workspace(job.workspace, job.claim_token)

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
    if job.workspace is not None and job.claim_token is not None:
        release_workspace(job.workspace, job.claim_token)
    return result


def terminate_running_jobs() -> None:
    """Cancel every running job, terminating its process tree.

    Registered with ``atexit`` so a server shutdown does not leave a pestpp /
    mf6 tree running and file-locking a workspace (the orphaned ``pestpp-da``
    left spinning at 100 % CPU in the 6d reruns).
    """
    for job_id, job in list(_jobs.items()):
        if job.status == STATUS_RUNNING:
            try:
                cancel(job_id)
            except Exception:
                pass


atexit.register(terminate_running_jobs)
