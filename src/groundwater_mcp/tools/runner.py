"""runner module — execute MODFLOW 6 and retrieve run results."""

from __future__ import annotations

import contextlib
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from io import StringIO
from pathlib import Path

import numpy as np
from mcp.server.fastmcp import FastMCP

from groundwater_mcp.tools.builder import _transient_like_without_sto
from groundwater_mcp.tools.postprocess import _compute_obs_fit
from groundwater_mcp.utils import jobs
from groundwater_mcp.utils.components import UnknownComponentError
from groundwater_mcp.utils.grid import get_dis
from groundwater_mcp.utils.model_store import (
    ModelReadOnlyError,
    component_sim_names,
    flush_model,
    get_component_sim,
    get_gwf,
    get_model,
    get_sim,
    invalidate,
    save_sim,
)
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


# ---------------------------------------------------------------------------
# Convergence auto-fix ladder (7f-H2)
# ---------------------------------------------------------------------------

# Ordered solver remedies applied on non-convergence when auto_fix=True: an
# escalation from a modest solver towards an aggressive Newton-friendly
# configuration, stopping at the first rung that converges.
_IMS_RUNGS: list[dict] = [
    {"complexity": "moderate", "outer_maximum": 100},
    {"complexity": "complex", "outer_maximum": 1000},
    {"complexity": "complex", "outer_maximum": 2000, "relaxation_factor": 0.9},
    {
        "complexity": "complex",
        "outer_maximum": 2000,
        "relaxation_factor": 0.97,
        "linear_acceleration": "BCGS",
    },
]


def _apply_ims_rung(ims, rung: dict) -> list[dict]:
    """Apply one solver rung to the IMS package; return the from/to changes."""
    changes: list[dict] = []
    for setting, value in rung.items():
        data = getattr(ims, setting, None)
        old = None
        if data is not None:
            try:
                old = data.array
                data.set_data(value)
            except Exception:
                continue
        changes.append({"setting": setting, "from": old, "to": value})
    return changes


# ---------------------------------------------------------------------------
# Binary detection
# ---------------------------------------------------------------------------


def _find_mf6_binary() -> str:
    """Locate the MODFLOW 6 executable on the system.

    Checks PATH first, then common install locations created by ``get-modflow``.

    Returns
    -------
    str
        Absolute path to the mf6 (or mf6.exe on Windows) binary.

    Raises
    ------
    RuntimeError
        If the binary cannot be found in any expected location.
    """
    exe_name = "mf6.exe" if platform.system() == "Windows" else "mf6"

    # 1. Standard PATH lookup
    found = shutil.which(exe_name)
    if found:
        return found

    # 2. Common locations written by get-modflow and conda
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / exe_name,
        home / ".local" / "share" / "flopy" / "bin" / exe_name,
        home / "modflow" / exe_name,
        Path("/usr/local/bin") / exe_name,
        Path("/opt/local/bin") / exe_name,
    ]

    # 3. FloPy package bin directory (populated by some get-modflow invocations)
    try:
        import flopy
        candidates.append(Path(flopy.__file__).parent / "bin" / exe_name)
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        f"MODFLOW 6 binary ('{exe_name}') not found in PATH or common install locations. "
        "Install with: get-modflow :"
    )


# ---------------------------------------------------------------------------
# Job control (7e-A3) — background runs with live progress and cancellation
# ---------------------------------------------------------------------------


def _run_process(args: list[str], cwd: str):
    """Spawn a subprocess capturing stdout+stderr, returning the Popen handle.

    A module-level seam so tests can substitute a fake process; production
    behaviour is a plain ``subprocess.Popen`` with combined output. The
    process is spawned in its own process group/session so ``cancel_job`` can
    terminate the whole tree (grandchildren included) on any platform.
    """
    return subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


_MF6_SOLVING_RE = re.compile(
    r"Solving:\s*Stress period:\s*(\d+)\s*Time step:\s*(\d+)", re.IGNORECASE
)


def _parse_mf6_lst_progress(text: str) -> dict:
    """Parse MODFLOW 6 listing-file progress (7e-A3.2).

    Reads the number of stress periods and per-period time-step counts from
    the TDIS block, and the current stress period / time step from the
    ``Solving:  Stress period: N  Time step: M`` markers. ``percent_complete``
    is the share of completed time steps — monotonically non-decreasing as the
    listing file grows.
    """
    n_stress_periods = 0
    time_steps_per_period: list[int] = []
    in_period_table = False
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+STRESS PERIOD\(S\) IN SIMULATION", line)
        if m:
            n_stress_periods = int(m.group(1))
            continue
        if "STRESS PERIOD" in line and "LENGTH" in line and "TIME STEPS" in line:
            in_period_table = True
            continue
        if "END OF TDIS PERIODDATA" in line:
            in_period_table = False
            continue
        if in_period_table:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    time_steps_per_period.append(int(parts[2]))
                except ValueError:
                    pass

    solves = _MF6_SOLVING_RE.findall(text)
    current = (int(solves[-1][0]), int(solves[-1][1])) if solves else None
    terminated = "normal termination" in text.lower()
    completed = len(solves)
    total = sum(time_steps_per_period)
    percent = round(completed / total * 100.0, 1) if total else (100.0 if terminated else 0.0)

    return {
        "n_stress_periods": n_stress_periods,
        "time_steps_per_period": time_steps_per_period,
        "current_stress_period": current[0] if current else None,
        "current_time_step": current[1] if current else None,
        "completed_time_steps": completed,
        "total_time_steps": total,
        "percent_complete": percent,
        "terminated": terminated,
    }


def _impl_start_run(model: str) -> dict:
    """Start MODFLOW 6 in the background and return a job id (7e-A3.1).

    The run executes in a worker thread so the call returns immediately; poll
    with ``get_job_status`` and stop with ``cancel_job``. The finished job's
    ``result`` matches ``run_simulation``'s shape (success, convergence,
    elapsed_s, listing_summary, observation_fit).
    """
    # Flush staged changes so the binary reads the current input set (7f-E1.2).
    flushed = flush_model(model)
    sim = get_sim(model)
    exe = _find_mf6_binary()
    ws = resolve_workspace(model)

    mnames = list(sim.model_names)
    gwf = sim.get_model(model) if model in mnames else None
    if gwf is None and mnames:
        gwf = sim.get_model(mnames[0])
    trap, sto_msg = _transient_like_without_sto(sim, gwf) if gwf is not None else (False, "")

    proc = _run_process([exe], str(ws))
    lines: deque[str] = deque(maxlen=5000)

    def _worker(job) -> dict:
        t0 = time.monotonic()
        success = False
        for line in proc.stdout:
            if "normal termination" in line.lower():
                success = True
            lines.append(line)
        returncode = proc.wait()
        # Evict from cache so post-processing tools reload from the new
        # binary outputs (same as run_simulation).
        invalidate(model)
        tail = list(lines)[-20:] if len(lines) > 20 else list(lines)
        result: dict = {
            "model": model,
            "success": success,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "convergence": "converged" if success else "failed",
            "listing_summary": "\n".join(tail),
            "flushed": flushed,
            "returncode": returncode,
        }
        result["observation_fit"] = _compute_obs_fit(model)
        if trap:
            result["warning"] = sto_msg
        return result

    def _progress(job) -> dict:
        lst_files = list(ws.glob("*.lst"))
        if not lst_files:
            return {}
        lst = next((f for f in lst_files if f.name == "mfsim.lst"), lst_files[0])
        try:
            return _parse_mf6_lst_progress(lst.read_text(errors="replace"))
        except Exception:
            return {}

    job = jobs.submit(model, "mf6", _worker, process=proc, progress_fn=_progress)
    return {
        "model": model,
        "job_id": job.job_id,
        "kind": "mf6",
        "status": "running",
        "note": "Poll progress with get_job_status; stop with cancel_job.",
    }


def _impl_get_job_status(job_id: str) -> dict:
    """Return the status, live progress, and (when finished) result of a job."""
    return jobs.get_status(job_id)


def _impl_cancel_job(job_id: str) -> dict:
    """Cancel a running background job and terminate its process."""
    return jobs.cancel(job_id)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _fast_stress_period_data(sim):
    """Make FloPy's ``sim.check`` cheap and CSUB-safe.

    FloPy's ``_check_oc`` re-materialises ``stress_period_data.data`` (the whole
    pandas-backed list converted to a recarray) twice per stress period, so a
    period-rich boundary package makes ``check`` O(nper^2): 158 GHB periods took
    ~62 s of a 65 s check on the 6d Target 9 model and exceeded the MCP client
    timeout. The same method calls ``spd.data.keys()`` on any package that
    reports ``has_stress_period_data`` but holds no records (CSUB), raising
    ``AttributeError: 'NoneType' object has no attribute 'keys'``.

    For the duration of the check, memoise each stress-period list's ``data``
    property per instance and present ``None`` as an empty mapping, then restore
    the original property. The workaround touches only the list ``data``
    property on the classes actually used by this simulation.
    """
    list_classes: set[type] = set()
    for mname in list(sim.model_names):
        try:
            model = sim.get_model(mname)
            package_names = list(model.get_package_list())
        except Exception:
            continue
        for pname in package_names:
            try:
                pkg = model.get_package(pname)
            except Exception:
                continue
            spd = getattr(pkg, "stress_period_data", None)
            if spd is not None:
                list_classes.add(type(spd))

    # ``data`` may be defined on a base class; patch the defining class so the
    # temporary property is what every instance resolves.
    owners: dict[type, property] = {}
    for cls in list_classes:
        for base in cls.__mro__:
            prop = base.__dict__.get("data")
            if isinstance(prop, property):
                owners[base] = prop
                break

    cache: dict[int, object] = {}

    def _getter(original: property):
        def _cached(self):
            key = id(self)
            if key not in cache:
                value = original.fget(self)
                cache[key] = {} if value is None else value
            return cache[key]

        return _cached

    try:
        for owner, prop in owners.items():
            owner.data = property(_getter(prop))
        yield
    finally:
        for owner, prop in owners.items():
            owner.data = prop


def _impl_check_model(model: str) -> dict:
    """Run FloPy's model checker and return structured warnings and errors."""
    # Flush staged changes so the check validates the on-disk state that a run
    # would consume (7f-E1.2).
    flushed = flush_model(model)
    sim = get_sim(model)

    # Capture any stdout/stderr that FloPy's check() writes
    buf = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        with _fast_stress_period_data(sim):
            check_results = sim.check(verbose=True, level=1)
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    captured = buf.getvalue()

    warnings: list = []
    errors: list = []

    # Try to extract structured data from check result objects
    if check_results is not None:
        result_list = check_results if isinstance(check_results, list) else [check_results]
        for chk in result_list:
            try:
                arr = chk.summary_array
                if arr is not None and len(arr) > 0:
                    for row in arr:
                        entry = {
                            "type": str(row["type"]),
                            "package": str(row["package"]),
                            "description": str(row["desc"]),
                        }
                        if str(row["type"]).lower() == "error":
                            errors.append(entry)
                        else:
                            warnings.append(entry)
            except (AttributeError, KeyError, TypeError):
                pass

    # Fall back to parsing raw text output if no structured data came back.
    # Only classify lines that *begin with* or are *labelled* as error/warning —
    # skip informational "no errors" lines which also contain those words.
    if not warnings and not errors and captured:
        for line in captured.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if "no errors" in lower or "no warnings" in lower:
                continue
            if lower.startswith("error") or ": error" in lower:
                errors.append(stripped)
            elif lower.startswith("warning") or ": warning" in lower:
                warnings.append(stripped)

    # Loud guard: a transient-looking model with no STO silently runs as
    # steady state — surface it here so the agent fixes it before running.
    gwf = sim.get_model(model) if model in sim.model_names else None
    if gwf is None:
        mnames = list(sim.model_names)
        gwf = sim.get_model(mnames[0]) if mnames else None
    if gwf is not None:
        trap, sto_msg = _transient_like_without_sto(sim, gwf)
        if trap:
            warnings.append({"type": "warning", "package": "STO", "description": sto_msg})

    return {
        "model": model,
        "warnings": warnings,
        "errors": errors,
        "check_passed": len(errors) == 0,
        "raw_output": captured[:4000],
        "flushed": flushed,
    }


def _impl_run_simulation(model: str, silent: bool = False, auto_fix: bool = False) -> dict:
    """Run MODFLOW 6 and return convergence status and timing.

    With ``auto_fix=True``, a non-converged run is retried through a bounded
    escalation ladder of solver settings (7f-H2); the applied changes are
    reported in ``auto_fix_applied`` and the model files reflect the final
    successful configuration.
    """
    # Flush staged changes so the binary reads the current input set (7f-E1.2).
    flushed = flush_model(model)
    sim = get_sim(model)
    exe = _find_mf6_binary()

    mnames = list(sim.model_names)
    gwf = sim.get_model(model) if model in mnames else None
    if gwf is None and mnames:
        gwf = sim.get_model(mnames[0])
    trap, sto_msg = _transient_like_without_sto(sim, gwf) if gwf is not None else (False, "")

    ws = resolve_workspace(model)

    def _run_once() -> tuple[bool, list, float]:
        sim.set_sim_path(str(ws))
        sim.exe_name = exe
        t0 = time.monotonic()
        try:
            success, buff = sim.run_simulation(silent=silent, report=True)
        except Exception as exc:
            raise RuntimeError(f"MODFLOW 6 run failed: {exc}") from exc
        return success, buff, time.monotonic() - t0

    success, buff, elapsed = _run_once()
    auto_fix_applied: list[dict] = []

    if not success and auto_fix:
        ims = sim.get_package("ims")
        if ims is not None:
            try:
                for rung in _IMS_RUNGS:
                    changes = _apply_ims_rung(ims, rung)
                    # Stage the IMS mutation so the flush actually writes it
                    # (7f-E1.2 deferred writes).
                    save_sim(model, sim)
                    flush_model(model)
                    success, buff, elapsed = _run_once()
                    auto_fix_applied.append({"rung": rung, "changes": changes})
                    if success:
                        break
            except ModelReadOnlyError:
                # An adopted read-only model cannot be solver-fixed in place;
                # report the original failure (clone it first to auto-fix).
                pass

    # Run derived component simulations (e.g. an FMI-coupled heat model) after
    # the flow model — heat advection reads the flow run's output. A heat run
    # is skipped when the flow run failed.
    component_results: list[dict] = []
    for cname in component_sim_names(model):
        csim = get_component_sim(model, cname)
        if not success:
            component_results.append(
                {"component": cname, "success": False, "skipped": "flow run failed"}
            )
            continue
        try:
            csim.exe_name = exe
            t0 = time.monotonic()
            csuccess, cbuff = csim.run_simulation(silent=silent, report=True)
            component_results.append(
                {
                    "component": cname,
                    "success": csuccess,
                    "elapsed_s": round(time.monotonic() - t0, 2),
                }
            )
            if not csuccess:
                success = False
                if cbuff:
                    tail = cbuff[-20:] if len(cbuff) > 20 else cbuff
                    listing_summary = "\n".join(tail)
        except Exception as exc:
            component_results.append(
                {"component": cname, "success": False, "error": str(exc)}
            )
            success = False

    # Evict from cache so post-processing tools reload from updated binary outputs
    invalidate(model)

    convergence = "converged" if success else "failed"
    tail = buff[-20:] if buff and len(buff) > 20 else (buff or [])
    listing_summary = "\n".join(tail)

    result: dict = {
        "model": model,
        "success": success,
        "elapsed_s": round(elapsed, 2),
        "convergence": convergence,
        "listing_summary": listing_summary,
        "flushed": flushed,
    }
    if auto_fix_applied:
        result["auto_fix_applied"] = auto_fix_applied
    # Closed observation loop (7f-F1.4): when observations are registered and
    # the run produced the obs CSV, report the fit so every run answers
    # "is this any good?". Null when no targets are registered or the run did
    # not produce the CSV (e.g. convergence failure).
    result["observation_fit"] = _compute_obs_fit(model)
    if component_results:
        result["components"] = component_results
    if trap:
        assert sto_msg is not None
        result["warning"] = sto_msg
        result["listing_summary"] = "WARNING: " + sto_msg + "\n" + result["listing_summary"]
        print(f"WARNING: {sto_msg}", file=sys.stderr)
    return result


def _impl_get_run_log(model: str, tail: int = 100, component: str = "gwf") -> dict:
    """Return the last N lines of the MODFLOW listing file."""
    ws = resolve_workspace(model)

    lst_files = list(ws.glob("*.lst"))
    if not lst_files:
        raise FileNotFoundError(
            f"No listing file (.lst) found in workspace {ws}. "
            "Run the simulation first with run_simulation."
        )

    # Default (gwf) keeps the historical mfsim.lst preference. For a coupled
    # component, prefer that model's own listing file when it exists.
    lst_file = None
    if component.lower() != "gwf":
        comp_name = str(get_model(model, component).name)
        lst_file = next((f for f in lst_files if f.name == f"{comp_name}.lst"), None)
    if lst_file is None:
        lst_file = next((f for f in lst_files if f.name == "mfsim.lst"), lst_files[0])

    lines = lst_file.read_text(errors="replace").splitlines()
    tail_lines = lines[-tail:] if len(lines) > tail else lines

    # Try to extract the convergence information block
    convergence_table = ""
    for i, line in enumerate(tail_lines):
        upper = line.upper()
        if "CONVERGENCE" in upper or "INNER ITERATION" in upper:
            convergence_table = "\n".join(tail_lines[i:])
            break

    return {
        "model": model,
        "listing_file": str(lst_file),
        "total_lines": len(lines),
        "tail_lines": tail_lines,
        "convergence_table": convergence_table,
    }


# ---------------------------------------------------------------------------
# diagnose_convergence (7e-C1)
# ---------------------------------------------------------------------------

# MF6's own log rarely states *why* a run failed to converge — it just stops
# short of "normal termination". These thresholds/checks recover the root
# cause from the model configuration itself, which is deterministic and
# inspectable even when the listing file's iteration tables are not.

_CLOSURE_FLOOR = 1e-9  # tighter than this is unresolvable at double precision
_K_CONTRAST_THRESHOLD = 1e4


def _count_active_components(idomain_arr) -> int:
    """Count face-connected regions of active cells (idomain > 0).

    Uses scipy's default (non-diagonal) connectivity, matching a DIS grid's
    cell-to-cell adjacency. DISV/DISU grids are not handled — idomain here
    only ever comes from a DIS package.
    """
    from scipy import ndimage

    active = np.asarray(idomain_arr) > 0
    if not active.any():
        return 0
    _labels, n = ndimage.label(active)
    return int(n)


def _k_contrast(npf, dis) -> tuple[float | None, float | None, float | None]:
    """Max/min ratio of NPF k (and k33, if present) over active cells.

    Returns (ratio, k_min, k_max), or (None, None, None) when there is no
    positive-valued K to compare (e.g. everything filtered out).
    """
    values = [np.asarray(npf.k.array, dtype=float)]
    k33 = getattr(npf, "k33", None)
    k33_arr = None
    if k33 is not None:
        try:
            k33_arr = k33.array
        except Exception:
            k33_arr = None
    if k33_arr is not None:
        values.append(np.asarray(k33_arr, dtype=float))

    idomain = getattr(dis, "idomain", None) if dis is not None else None
    mask_layer = None
    if idomain is not None:
        try:
            mask_layer = np.asarray(idomain.array) > 0
        except Exception:
            mask_layer = None

    pieces: list[np.ndarray] = []
    for v in values:
        if mask_layer is not None and mask_layer.shape == v.shape:
            pieces.append(v[mask_layer])
        else:
            pieces.append(v.ravel())
    arr = np.concatenate(pieces) if pieces else np.array([])
    arr = arr[arr > 0]
    if arr.size == 0:
        return None, None, None
    k_min, k_max = float(arr.min()), float(arr.max())
    return (k_max / k_min if k_min > 0 else None), k_min, k_max


def _classify_convergence_failure(sim, gwf) -> tuple[str, list[str], dict]:
    """Infer why a non-converged run failed from the model configuration.

    Checked in order (first match wins): an outer/inner closure tolerance
    tighter than double precision can resolve, an idomain that splits the
    active domain into disconnected regions, convertible cells starting at
    or below their bottom elevation (with or without the Newton-Raphson
    formulation on), and hydraulic conductivity spanning many orders of
    magnitude. Falls back to "unclassified" when none of these hold.
    """
    ims = sim.get_package("ims")
    if ims is not None:
        for attr in ("outer_dvclose", "inner_dvclose"):
            data = getattr(ims, attr, None)
            if data is None:
                continue
            try:
                value = data.array
                value = float(value) if value is not None else None
            except (TypeError, ValueError):
                value = None
            if value is not None and value < _CLOSURE_FLOOR:
                return (
                    "closure_too_tight",
                    [
                        f"{attr}={value:g} is tighter than MF6 can resolve in double "
                        "precision at typical head scales — loosen it (e.g. 1e-4 to 1e-2 "
                        "in the model's length units), or reconfigure with "
                        "set_simulation(ims_complexity=...) instead of a hand-set value.",
                        "run_simulation(auto_fix=True) escalates IMS settings automatically "
                        "and reports exactly what changed.",
                    ],
                    {attr: value},
                )

    dis = get_dis(gwf)
    if dis is not None:
        idomain = getattr(dis, "idomain", None)
        if idomain is not None:
            try:
                n_components = _count_active_components(idomain.array)
            except Exception:
                n_components = 1
            if n_components > 1:
                return (
                    "disconnected_active_domain",
                    [
                        f"idomain splits the active domain into {n_components} separate "
                        "regions with no cell-to-cell path between them — the solver cannot "
                        "balance flow across the gap.",
                        "Set idomain=0 on the isolated region if it is not meant to be part "
                        "of this model, or add connecting active cells so every active cell "
                        "is reachable from the rest of the domain.",
                    ],
                    {"n_disconnected_regions": n_components},
                )

    npf = gwf.get_package("npf")
    ic = gwf.get_package("ic")
    botm = None
    if dis is not None and getattr(dis, "botm", None) is not None:
        try:
            botm = np.asarray(dis.botm.array, dtype=float)
        except Exception:
            botm = None

    if npf is not None:
        icelltype = np.asarray(npf.icelltype.array)
        convertible = icelltype != 0
        dry_risk = 0
        if convertible.any() and ic is not None and botm is not None:
            try:
                strt = np.asarray(ic.strt.array, dtype=float)
                if strt.shape == botm.shape == convertible.shape:
                    dry_risk = int(((strt <= botm) & convertible).sum())
            except Exception:
                dry_risk = 0

        if convertible.any() and dry_risk > 0:
            newton_on = bool(gwf.newtonoptions.get_data())
            evidence = {
                "convertible_cells": int(convertible.sum()),
                "dry_risk_cells": dry_risk,
            }
            if not newton_on:
                return (
                    "newton_needed",
                    [
                        f"{dry_risk} convertible cell(s) (icelltype != 0) start at or below "
                        "their bottom elevation and the Newton-Raphson formulation is off — "
                        "under the standard formulation those cells go dry and the matrix "
                        "stops being smooth, a classic non-convergence cause for unconfined "
                        "layers.",
                        "Rebuild the GWF model with newtonoptions=['NEWTON'] (flopy: "
                        "ModflowGwf(..., newtonoptions=['NEWTON'])) — not yet exposed by a "
                        "groundwater-mcp builder tool; export_reproducible_script gives a "
                        "flopy starting point to edit. Cells will not dry when Newton is "
                        "active.",
                    ],
                    evidence,
                )
            return (
                "dry_cells",
                [
                    f"{dry_risk} convertible cell(s) start at or below their bottom "
                    "elevation even with Newton-Raphson active — saturated thickness is "
                    "near zero there, which still slows or stalls convergence.",
                    "Review the K field and boundary stresses near those cells (excessive "
                    "pumping or a low starting head is often the real cause), or phase "
                    "stresses in over multiple stress periods instead of applying them from "
                    "a dry start.",
                ],
                evidence,
            )

        k_ratio, k_min, k_max = _k_contrast(npf, dis)
        if k_ratio is not None and k_ratio > _K_CONTRAST_THRESHOLD:
            return (
                "k_contrast",
                [
                    f"NPF k spans {k_ratio:.1e}x across active cells (min={k_min:.3g}, "
                    f"max={k_max:.3g}) — the resulting matrix is ill-conditioned.",
                    "Increase solver robustness with "
                    "set_simulation(ims_complexity='complex'), and double-check the K field "
                    "for a units mismatch or data-entry error before assuming the contrast "
                    "is physically real.",
                ],
                {"k_ratio": k_ratio, "k_min": k_min, "k_max": k_max},
            )

    return (
        "unclassified",
        [
            "No specific configuration defect was detected (closure tolerance, idomain "
            "connectivity, Newton/dry-cell risk, and K contrast all look reasonable) — the "
            "cause is likely in the stress data or grid geometry itself.",
            "Inspect get_run_log(model, tail=200) for the outer-iteration table near the "
            "point of failure, or try run_simulation(auto_fix=True) to escalate solver "
            "settings.",
        ],
        {},
    )


def _impl_diagnose_convergence(model: str) -> dict:
    """Classify why a MODFLOW 6 run did not converge and recommend a fix.

    Confirms non-convergence from the listing file ("normal termination"
    absent), then inspects the model configuration for the root cause —
    outer/inner closure tolerance, idomain connectivity, Newton/dry-cell risk,
    and K contrast — since MF6's own log rarely states one explicitly.
    """
    ws = resolve_workspace(model)
    lst_files = list(ws.glob("*.lst"))
    if not lst_files:
        raise FileNotFoundError(
            f"No listing file (.lst) found in workspace {ws}. "
            "Run the simulation first with run_simulation."
        )
    lst_file = next((f for f in lst_files if f.name == "mfsim.lst"), lst_files[0])
    progress = _parse_mf6_lst_progress(lst_file.read_text(errors="replace"))

    if progress["terminated"]:
        return {
            "model": model,
            "converged": True,
            "failure_class": "converged",
            "recommendations": [],
            "evidence": {},
        }

    sim = get_sim(model)
    gwf = get_gwf(model)
    failure_class, recommendations, evidence = _classify_convergence_failure(sim, gwf)

    return {
        "model": model,
        "converged": False,
        "failure_class": failure_class,
        "recommendations": recommendations,
        "evidence": evidence,
        "progress": progress,
    }


# ---------------------------------------------------------------------------
# validate_model (7e-C2)
# ---------------------------------------------------------------------------


def _heads_for_validation(model: str, gwf, ws: Path) -> tuple[np.ndarray | None, str]:
    """Return (heads array, source) for physical-plausibility checks.

    Prefers simulated heads from the .hds output; falls back to the model's
    initial conditions (IC strt) when the model has not been run yet.
    """
    import flopy.utils as fu

    from groundwater_mcp.tools.postprocess import _find_output_file

    try:
        hds_path, _warning = _find_output_file(model, ws, ".hds")
        hf = fu.HeadFile(str(hds_path))
        kstpkper_list = hf.get_kstpkper()
        if kstpkper_list:
            return np.asarray(hf.get_data(kstpkper=kstpkper_list[-1]), dtype=float), "simulated"
    except Exception:
        pass
    ic = gwf.get_package("ic")
    if ic is not None:
        try:
            return np.asarray(ic.strt.array, dtype=float), "initial_conditions"
        except Exception:
            pass
    return None, "none"


def _boundary_cells_in_inactive(gwf, idomain) -> dict[str, int]:
    """Count list-based boundary stress-period cells sitting on an inactive
    (idomain <= 0) cell, per package type.

    Array-based packages (RCHA/EVTA) apply everywhere by construction and are
    skipped; packages whose stress_period_data has no ``cellid`` field (e.g.
    SFR, reach-indexed) are skipped too.
    """
    from groundwater_mcp.tools.builder import (
        _ARRAY_BOUNDARY_PKGS,
        _BOUNDARY_PKG_CLASSES,
        _packages_of_type,
    )

    counts: dict[str, int] = {}
    for pkg_name in _BOUNDARY_PKG_CLASSES:
        if pkg_name in _ARRAY_BOUNDARY_PKGS:
            continue
        for pkg in _packages_of_type(gwf, pkg_name):
            spd_attr = getattr(pkg, "stress_period_data", None)
            if spd_attr is None:
                continue
            try:
                data = spd_attr.get_data()
            except Exception:
                continue
            if not data:
                continue
            bad = 0
            for rec in data.values():
                if rec is None or "cellid" not in (rec.dtype.names or ()):
                    continue
                for row in rec:
                    try:
                        idx = tuple(int(i) for i in row["cellid"])
                        if idomain[idx] <= 0:
                            bad += 1
                    except Exception:
                        continue
            if bad:
                counts[pkg_name] = counts.get(pkg_name, 0) + bad
    return counts


_VALIDATE_K_CONTRAST_THRESHOLD = 1e6


def _impl_validate_model(model: str) -> dict:
    """Check the model for physical-plausibility defects, aggregated into one
    finding per defect type instead of one warning per cell.

    Checks: heads above the layer top / below the layer bottom (using
    simulated heads if the model has run, else initial conditions), NPF K
    spanning more than 6 orders of magnitude, an idomain that splits the
    active domain into disconnected regions (DIS grids only), and boundary
    stress-period cells sitting on an inactive cell — the last of these
    produced 569,796 individual FloPy-checker warnings on a real regional
    model (zenodo-21381071) before this aggregation existed.
    """
    flushed = flush_model(model)
    gwf = get_gwf(model)
    ws = resolve_workspace(model)

    findings: list[dict] = []

    dis = get_dis(gwf)
    idomain = None
    top = None
    botm = None
    if dis is not None:
        idomain_data = getattr(dis, "idomain", None)
        if idomain_data is not None:
            try:
                idomain_arr = idomain_data.array
                idomain = np.asarray(idomain_arr) if idomain_arr is not None else None
            except Exception:
                idomain = None
        try:
            top = np.asarray(dis.top.array, dtype=float)
        except Exception:
            top = None
        try:
            botm = np.asarray(dis.botm.array, dtype=float)
        except Exception:
            botm = None

    if idomain is not None:
        n_components = _count_active_components(idomain)
        if n_components > 1:
            findings.append({
                "type": "disconnected_active_cells",
                "severity": "error",
                "message": (
                    f"idomain splits the active domain into {n_components} separate "
                    "regions with no cell-to-cell path between them."
                ),
                "count": n_components,
            })

    npf = gwf.get_package("npf")
    if npf is not None:
        k_ratio, k_min, k_max = _k_contrast(npf, dis)
        if k_ratio is not None and k_ratio > _VALIDATE_K_CONTRAST_THRESHOLD:
            findings.append({
                "type": "k_contrast",
                "severity": "warning",
                "message": (
                    f"NPF k spans {k_ratio:.1e}x across active cells (min={k_min:.3g}, "
                    f"max={k_max:.3g}) — more than 6 orders of magnitude."
                ),
                "k_ratio": k_ratio,
                "k_min": k_min,
                "k_max": k_max,
            })

    if botm is not None:
        heads, heads_source = _heads_for_validation(model, gwf, ws)
        if heads is not None and heads.shape == botm.shape:
            finite = np.abs(heads) < 1e20
            active_mask = (
                idomain > 0
                if idomain is not None and idomain.shape == botm.shape
                else np.ones_like(botm, dtype=bool)
            )

            below = (heads < botm) & active_mask & finite
            n_below = int(below.sum())
            if n_below:
                findings.append({
                    "type": "head_below_bottom",
                    "severity": "error",
                    "message": (
                        f"{n_below} active cell(s) have a head below the layer's own "
                        f"bottom elevation ({heads_source} heads) — the saturated "
                        "thickness there is negative, a physically impossible state."
                    ),
                    "count": n_below,
                    "heads_source": heads_source,
                })

            if top is not None and top.shape == botm.shape[1:]:
                layer_top = np.concatenate([top[np.newaxis, ...], botm[:-1]], axis=0)
                above = (heads > layer_top) & active_mask & finite
                if npf is not None:
                    try:
                        convertible = np.asarray(npf.icelltype.array) != 0
                        if convertible.shape == above.shape:
                            above = above & convertible
                    except Exception:
                        pass
                n_above = int(above.sum())
                if n_above:
                    findings.append({
                        "type": "head_above_top",
                        "severity": "warning",
                        "message": (
                            f"{n_above} active, convertible (unconfined) cell(s) have a "
                            f"head above the layer top ({heads_source} heads) — implausible "
                            "unless the layer is deliberately flooded."
                        ),
                        "count": n_above,
                        "heads_source": heads_source,
                    })

    if idomain is not None:
        by_pkg = _boundary_cells_in_inactive(gwf, idomain)
        total = sum(by_pkg.values())
        if total:
            findings.append({
                "type": "boundary_in_inactive_cell",
                "severity": "warning",
                "message": (
                    f"{total} boundary stress-period cell(s) sit on an inactive "
                    f"(idomain<=0) cell across {', '.join(sorted(by_pkg))} — MF6 ignores "
                    "them, so this is wasted/misleading stress data rather than a "
                    "run-time error."
                ),
                "count": total,
                "by_package": by_pkg,
            })

    return {
        "model": model,
        "findings": findings,
        "clean": len(findings) == 0,
        "flushed": flushed,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register runner tools with the MCP server."""

    @mcp.tool()
    def check_model(model: str) -> dict:
        """Run FloPy's pre-run model checker and return structured warnings and errors."""
        try:
            return _impl_check_model(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("CHECK_FAILED", str(exc))

    @mcp.tool()
    def run_simulation(model: str, silent: bool = False, auto_fix: bool = False) -> dict:
        """Run the MODFLOW 6 simulation and return convergence status and timing.

        auto_fix=True retries a non-converged run through a bounded escalation
        ladder of solver settings (complexity moderate→complex, more outer
        iterations, relaxation, linear acceleration) and reports the applied
        changes in auto_fix_applied."""
        try:
            return _impl_run_simulation(model, silent, auto_fix)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except RuntimeError as exc:
            msg = str(exc)
            if "not found" in msg.lower() or "binary" in msg.lower():
                return _err(
                    "BINARY_NOT_FOUND", msg, "Install MODFLOW 6 with: get-modflow :"
                )
            return _err("CONVERGENCE_FAILED", msg)
        except Exception as exc:
            return _err("RUN_FAILED", str(exc))

    @mcp.tool()
    def diagnose_convergence(model: str) -> dict:
        """Classify why a MODFLOW 6 run did not converge and recommend a fix.

        Reads the listing file to confirm the run did not reach "normal
        termination", then inspects the model configuration for the root
        cause: closure_too_tight (outer/inner dvclose unresolvable at double
        precision), disconnected_active_domain (idomain splits the active
        domain), newton_needed / dry_cells (convertible cells at/below their
        bottom elevation, with Newton off or already on respectively), or
        k_contrast (K spans >4 orders of magnitude). Returns converged=True,
        failure_class="converged" when the run succeeded."""
        try:
            return _impl_diagnose_convergence(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "OUTPUT_FILE_MISSING", str(exc), "Run the simulation first."
            )
        except Exception as exc:
            return _err("DIAGNOSIS_FAILED", str(exc))

    @mcp.tool()
    def validate_model(model: str) -> dict:
        """Check the model for physical-plausibility defects the FloPy
        checker doesn't aggregate.

        Findings (each collapsed into one entry with a count, not one per
        cell): head_below_bottom / head_above_top (simulated heads if the
        model has run, else initial conditions), k_contrast (NPF K spanning
        >6 orders of magnitude), disconnected_active_cells (idomain splits
        the DIS active domain), and boundary_in_inactive_cell (list-based
        boundary cells sitting on idomain<=0 — this alone was 569,796
        individual warnings on a real regional model). Returns clean=True,
        findings=[] when none are found."""
        try:
            return _impl_validate_model(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("VALIDATION_FAILED", str(exc))

    @mcp.tool()
    def get_run_log(model: str, tail: int = 100, component: str = "gwf") -> dict:
        """Return the last N lines of the MODFLOW listing file (.lst).

        ``component`` (default "gwf") selects a coupled component's listing
        file when it exists; otherwise mfsim.lst is used."""
        try:
            return _impl_get_run_log(model, tail, component)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "OUTPUT_FILE_MISSING", str(exc), "Run the simulation first."
            )
        except Exception as exc:
            return _err("LOG_READ_FAILED", str(exc))

    @mcp.tool()
    def start_run(model: str) -> dict:
        """Start the MODFLOW 6 simulation in the background and return a job
        id immediately (7e-A3).

        The run executes in a worker thread instead of blocking until the
        client timeout. Poll progress and the final result with
        get_job_status(job_id) — while running it reports live stress-period /
        time-step progress parsed from the .lst — and stop the run with
        cancel_job(job_id). The finished job's result has the same shape as
        run_simulation: success, convergence, elapsed_s, listing_summary,
        observation_fit."""
        try:
            return _impl_start_run(model)
        except UnknownComponentError as exc:
            return _err("INVALID_INPUT", str(exc))
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except RuntimeError as exc:
            msg = str(exc)
            if "not found" in msg.lower() or "binary" in msg.lower():
                return _err(
                    "BINARY_NOT_FOUND", msg, "Install MODFLOW 6 with: get-modflow :"
                )
            return _err("START_RUN_FAILED", msg)
        except Exception as exc:
            return _err("START_RUN_FAILED", str(exc))

    @mcp.tool()
    def get_job_status(job_id: str) -> dict:
        """Poll the status of a background job started by start_run or
        start_calibration.

        Returns status (running/succeeded/failed/cancelled), elapsed_s and,
        while running, live progress — stress period / time step / percent
        complete for MF6 runs (from the .lst), iteration + latest phi for
        PEST++ jobs (from .iobj / .phi.actual.csv), or the per-cycle post-update
        phi for DA runs (from <case>.global.phi.actual.csv). Finished jobs
        include the result dict (same shape as run_simulation / run_pestpp_glm /
        run_pestpp_ies / run_pestpp_da)."""
        try:
            return _impl_get_job_status(job_id)
        except KeyError as exc:
            return _err(
                "JOB_NOT_FOUND",
                str(exc),
                "Pass the job_id returned by start_run or start_calibration.",
            )
        except Exception as exc:
            return _err("JOB_STATUS_FAILED", str(exc))

    @mcp.tool()
    def cancel_job(job_id: str) -> dict:
        """Cancel a running background job (start_run / start_calibration) and
        terminate its process. Reports 'cancelled' when the job was running,
        or the job's terminal status when it had already finished."""
        try:
            return _impl_cancel_job(job_id)
        except KeyError as exc:
            return _err(
                "JOB_NOT_FOUND",
                str(exc),
                "Pass the job_id returned by start_run or start_calibration.",
            )
        except Exception as exc:
            return _err("JOB_CANCEL_FAILED", str(exc))
