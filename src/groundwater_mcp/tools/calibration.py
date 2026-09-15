"""calibration module — PEST++ parameter estimation via pyEMU."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
from mcp.server.fastmcp import FastMCP

from groundwater_mcp.tools.runner import _find_mf6_binary
from groundwater_mcp.utils import jobs
from groundwater_mcp.utils.grid import get_dis, get_disu, get_disv
from groundwater_mcp.utils.model_store import (
    flush_model,
    get_gwf,
    read_meta,
    save_sim,
    write_meta,
)
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


# ---------------------------------------------------------------------------
# Binary detection
# ---------------------------------------------------------------------------


def _find_pestpp_binary(exe_name: str) -> str:
    """Locate a PEST++ executable on the system.

    Checks PATH first, then common install locations.

    Parameters
    ----------
    exe_name:
        Base executable name, e.g. ``"pestpp-glm"`` or ``"pestpp-ies"``.

    Returns
    -------
    str
        Absolute path to the executable.

    Raises
    ------
    RuntimeError
        If the binary cannot be found.
    """
    if platform.system() == "Windows":
        exe_name = exe_name + ".exe"

    # 1. Standard PATH lookup
    found = shutil.which(exe_name)
    if found:
        return found

    # 2. Common install locations
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / exe_name,
        home / "pestpp" / "bin" / exe_name,
        home / "bin" / exe_name,
        home / ".local" / "share" / "pestpp" / "bin" / exe_name,
        Path("/usr/local/bin") / exe_name,
        Path("/opt/local/bin") / exe_name,
    ]

    # 3. FloPy package bin directory (some get-pestpp invocations write here)
    try:
        import flopy

        candidates.append(Path(flopy.__file__).parent / "bin" / exe_name)
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        f"PEST++ binary '{exe_name}' not found in PATH or common install locations. "
        "Install with: get-pestpp :"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_pst_path(model: str, pst_file: str) -> Path:
    """Return an absolute Path for a PST file, resolving relative paths against the workspace."""
    p = Path(pst_file)
    if p.is_absolute():
        return p
    return resolve_workspace(model) / pst_file


def _read_phi_csv(phi_csv: Path) -> tuple[list[dict], float | None]:
    """Parse a PEST++ phi.actual.csv and return (phi_progress, final_phi).

    The CSV has observation group names as columns and one row per iteration
    (GLM) or per realisation per iteration (IES). We sum all numeric columns
    to get a total phi for each row, then collapse by iteration index.
    """
    try:
        import pandas as pd

        phi_df = pd.read_csv(phi_csv, index_col=0)
        numeric = phi_df.select_dtypes(include="number")
        phi_totals = numeric.sum(axis=1)

        phi_progress = [{"iteration": i, "phi": float(v)} for i, v in enumerate(phi_totals)]
        final_phi = float(phi_totals.iloc[-1]) if len(phi_totals) > 0 else None
        return phi_progress, final_phi
    except OSError:
        return [], None


def _read_iobj_phi(iobj_path: Path) -> tuple[list[dict], float | None]:
    """Parse a PESTPP-GLM ``.iobj`` file into (phi_progress, final_phi).

    pestpp-glm writes its iteration objective-function history to
    ``<case>.iobj`` (header: ``iteration,model_runs_completed,total_phi,
    measurement_phi,regularization_phi,<obsgroup>``) — it never writes
    ``.phi.actual.csv`` (that is pestpp-ies output). Reading the wrong file is
    why GLM phi/iterations were silently always empty (7e-B1.1).
    """
    try:
        df = pd.read_csv(iobj_path)
        total = (
            df["total_phi"]
            if "total_phi" in df.columns
            else df.select_dtypes(include="number").iloc[:, 0]
        )
        phi_progress = [{"iteration": int(i), "phi": float(v)} for i, v in enumerate(total)]
        final_phi = float(total.iloc[-1]) if len(total) > 0 else None
        return phi_progress, final_phi
    except OSError:
        return [], None


def _read_glm_phi(ws: Path, base_name: str) -> tuple[list[dict], float | None]:
    """Read GLM objective-function history, branching on engine (7e-B1.1).

    pestpp-glm writes ``<case>.iobj``; pestpp-ies writes
    ``<case>.phi.actual.csv``. Return ``(phi_progress, final_phi)`` from the
    file that exists (the IES file falling back to the old IES reader).
    """
    iobj = ws / f"{base_name}.iobj"
    if iobj.exists():
        return _read_iobj_phi(iobj)
    phi_csv = ws / f"{base_name}.phi.actual.csv"
    if phi_csv.exists():
        return _read_phi_csv(phi_csv)
    return [], None


def _read_ies_phi(ws: Path, base_name: str) -> tuple[list[dict], float | None]:
    """Parse a PESTPP-IES ``<case>.phi.actual.csv`` into (phi_progress, final_phi).

    The CSV has one row per iteration; the ``mean`` column holds the
    ensemble-mean phi (with std/min/max and per-realisation columns besides),
    so the mean is the reported phi. Without a ``mean`` column the numeric
    columns (excluding metadata) are averaged.
    """
    phi_csv = ws / f"{base_name}.phi.actual.csv"
    if not phi_csv.exists():
        return [], None
    try:
        df = pd.read_csv(phi_csv)
    except (OSError, pd.errors.ParserError):
        return [], None
    if "iteration" not in df.columns:
        return [], None
    progress: list[dict] = []
    for _, row in df.iterrows():
        if "mean" in df.columns and pd.notna(row["mean"]):
            phi: float | None = float(row["mean"])
        else:
            values = []
            for key, value in row.items():
                if key in ("iteration", "total_runs"):
                    continue
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
            phi = float(np.mean(values)) if values else None
        progress.append({"iteration": int(row["iteration"]), "phi": phi})
    final_phi = progress[-1]["phi"] if progress else None
    return progress, final_phi


def _latest_ensemble_file(ws: Path, base_name: str, suffix: str) -> Path | None:
    """Return the highest-iteration pestpp-ies ensemble file ``<case>.<N>.csv``.

    ``suffix`` is ``"par"`` or ``"obs"``. The iteration number is sorted
    numerically (a lexicographic sort would misorder iteration 10 before 9).
    """
    pattern = re.compile(rf"\.(\d+)\.{re.escape(suffix)}\.csv$")
    files = []
    for p in ws.glob(f"{base_name}.*.{suffix}.csv"):
        m = pattern.search(p.name)
        if m is not None:
            files.append((int(m.group(1)), p))
    if not files:
        return None
    return max(files, key=lambda t: t[0])[1]


def _parameter_ensemble_stats(par_csv: Path, drop_base: bool = False) -> dict[str, dict]:
    """Compute per-parameter ensemble statistics from a parameter-ensemble CSV.

    Columns are parameter names, rows are realisations (a non-numeric leading
    index / ``real_name`` column holds the realisation id). Returns a dict keyed
    by lower-case parameter name with ``mean``/``std``/``min``/``max``/``n``.

    ``drop_base`` removes the ``base`` row pestpp-da writes alongside the
    realisations (it is the base parameter set, not an ensemble member).
    """
    df = pd.read_csv(par_csv)
    if drop_base and len(df.columns) > 0:
        id_col = "real_name" if "real_name" in df.columns else df.columns[0]
        df = df[df[id_col].astype(str).str.lower() != "base"]
    ensemble: dict[str, dict] = {}
    for col in df.select_dtypes(include="number").columns:
        vals = df[col].dropna().astype(float)
        if len(vals) == 0:
            continue
        ensemble[str(col).lower()] = {
            "mean": float(vals.mean()),
            "std": float(vals.std(ddof=0)),
            "min": float(vals.min()),
            "max": float(vals.max()),
            "n": int(len(vals)),
        }
    return ensemble


def _read_ies_parameter_ensemble(ws: Path, base_name: str) -> dict[str, dict]:
    """Read the final pestpp-ies parameter ensemble ``<case>.<N>.par.csv``.

    Returns a dict keyed by lower-case parameter name with
    ``mean``/``std``/``min``/``max``/``n``. ``{}`` when no ensemble file exists.
    """
    par_csv = _latest_ensemble_file(ws, base_name, "par")
    if par_csv is None:
        return {}
    return _parameter_ensemble_stats(par_csv)



def _read_ies_obs_ensemble(ws: Path, base_name: str, pst) -> pd.DataFrame | None:
    """Residuals for an IES run without a ``.rei``: from the final observation
    ensemble ``<case>.<N>.obs.csv`` against the PST observed values.

    Returns a DataFrame with the same columns ``pst.res`` exposes (name,
    measured, modelled, residual, weight) so the shared residual-processing
    path can consume it. The modelled value for each observation is the
    ensemble mean across realisations. ``None`` when no ensemble file exists.
    """
    obs_csv = _latest_ensemble_file(ws, base_name, "obs")
    if obs_csv is None:
        return None
    obs_df = pd.read_csv(obs_csv)
    rows: list[dict] = []
    for col in obs_df.select_dtypes(include="number").columns:
        obs_name = str(col)
        if obs_name not in pst.observation_data.index:
            continue
        obs_row = pst.observation_data.loc[obs_name]
        measured = float(obs_row["obsval"])
        weight = float(obs_row["weight"])
        modelled = float(obs_df[col].dropna().astype(float).mean())
        rows.append(
            {
                "name": obs_name,
                "measured": measured,
                "modelled": modelled,
                "residual": measured - modelled,
                "weight": weight,
            }
        )
    if not rows:
        return None
    return pd.DataFrame(rows)


def _detect_pestpp_engine(ws: Path, base_name: str) -> str:
    """Detect which PEST++ engine produced a run's artifacts.

    pestpp-glm leaves ``<case>.par`` and ``<case>.iobj``; pestpp-ies leaves
    per-iteration ensemble files ``<case>.<N>.par.csv`` / ``<case>.<N>.obs.csv``
    and never a plain ``<case>.par``. A ``.par`` wins when both exist (a real
    run produces one or the other, never both).

    pestpp-da leaves per-cycle outputs ``<case>.global.phi.actual.csv`` /
    ``<case>.global.<cycle>.pe.csv``, and its per-cycle iteration files
    (``<case>.<cycle>.par.csv``) would otherwise read as IES — so DA is checked
    between GLM and IES.
    """
    if (ws / f"{base_name}.par").exists():
        return "glm"
    if (
        (ws / f"{base_name}.global.phi.actual.csv").exists()
        or any(ws.glob(f"{base_name}.global.*.pe.csv"))
        or any(ws.glob(f"{base_name}.global.*.oe.csv"))
    ):
        return "da"
    if any(ws.glob(f"{base_name}.*.par.csv")):
        return "ies"
    return "glm"


def _read_da_cycle_phi(ws: Path, base_name: str) -> list[dict]:
    """Parse pestpp-da's per-cycle phi file ``<case>.global.phi.actual.csv``.

    Columns are ``cycle,iteration,mean,standard_deviation,min,max,<reals...>``,
    with two rows per cycle (iteration 0 = prior, >=1 = post-update). The
    reported per-cycle phi is the post-update (highest-iteration) ensemble mean.
    Returns one ``{"cycle", "phi", "phi_std"}`` per cycle in cycle order; ``[]``
    when the file is absent or malformed.
    """
    phi_csv = ws / f"{base_name}.global.phi.actual.csv"
    if not phi_csv.exists():
        return []
    try:
        df = pd.read_csv(phi_csv)
    except (OSError, pd.errors.ParserError):
        return []
    if "cycle" not in df.columns or "mean" not in df.columns:
        return []
    cycles: list[dict] = []
    for cycle, group in df.groupby("cycle", sort=True):
        if "iteration" in group.columns:
            group = group.sort_values("iteration")
        row = group.iloc[-1]
        mean = row["mean"]
        std = (
            row["standard_deviation"]
            if "standard_deviation" in df.columns
            else None
        )
        cycles.append(
            {
                "cycle": int(cycle),
                "phi": float(mean) if pd.notna(mean) else None,
                "phi_std": float(std) if std is not None and pd.notna(std) else None,
            }
        )
    return cycles


def _read_da_parameter_ensemble(ws: Path, base_name: str) -> dict[str, dict]:
    """Posterior parameter statistics from the final pestpp-da cycle ensemble.

    pestpp-da writes ``<case>.global.<cycle>.pe.csv`` (columns ``real_name``
    then the parameter names, with a ``base`` row alongside the realisations).
    The highest cycle's file is the posterior; the ``base`` row is excluded.
    """
    pe_csv = _latest_ensemble_file(ws, base_name, "pe")
    if pe_csv is None:
        return {}
    return _parameter_ensemble_stats(pe_csv, drop_base=True)


def _latest_da_residual_file(ws: Path, base_name: str) -> Path | None:
    """Return the highest cycle/iteration pestpp-da ``<case>.<c>.<i>.base.rei``."""
    pattern = re.compile(r"\.(\d+)\.(\d+)\.base\.rei$")
    files = []
    for p in ws.glob(f"{base_name}.*.base.rei"):
        m = pattern.search(p.name)
        if m is not None:
            files.append(((int(m.group(1)), int(m.group(2))), p))
    if not files:
        return None
    return max(files, key=lambda t: t[0])[1]


def _pestpp_progress(ws: Path, base_name: str, engine: str) -> dict:
    """Live progress for a running PEST++ job (7e-A3.3).

    Reads the current iteration and latest phi from ``<case>.iobj`` (GLM) or
    ``<case>.phi.actual.csv`` (IES); returns ``{}`` before either exists.
    """
    if engine == "glm":
        progress, _ = _read_glm_phi(ws, base_name)
    else:
        progress, _ = _read_ies_phi(ws, base_name)
    if not progress:
        return {}
    return {
        "engine": engine,
        "iteration": int(progress[-1]["iteration"]),
        "latest_phi": progress[-1]["phi"],
        "n_iterations": len(progress),
    }


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


def _impl_start_calibration(
    model: str,
    pst_file: str,
    method: str = "glm",
    num_reals: int = 50,
) -> dict:
    """Start a PEST++ calibration in the background and return a job id (7e-A3).

    ``method`` is ``"glm"`` (pestpp-glm, default) or ``"ies"`` (pestpp-ies).
    The calibration executes in a worker thread so the call returns
    immediately; poll with ``get_job_status`` (which reports live iteration +
    phi from ``<case>.iobj`` / ``<case>.phi.actual.csv``) and stop with
    ``cancel_job``. The finished job's ``result`` matches
    ``run_pestpp_glm`` / ``run_pestpp_ies``.
    """
    if method not in ("glm", "ies"):
        raise ValueError(f"method must be 'glm' or 'ies', got '{method}'.")
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)
    base_name = pst_path.stem

    # Flush staged model changes so the forward model reads the current input
    # set (7f-E1.2).
    flush_model(model)

    exe = _find_pestpp_binary("pestpp-glm" if method == "glm" else "pestpp-ies")
    if method == "ies":
        pst = pyemu.Pst(str(pst_path))
        pst.pestpp_options["ies_num_reals"] = num_reals
        pst.write(str(pst_path))

    proc = _run_process([exe, pst_path.name], str(ws))
    lines: deque[str] = deque(maxlen=5000)

    def _worker(job) -> dict:
        for line in proc.stdout:
            lines.append(line)
        returncode = proc.wait()
        if method == "glm":
            phi_progress, final_phi = _read_glm_phi(ws, base_name)
            return {
                "model": model,
                "pst_file": str(pst_path),
                "converged": returncode == 0,
                "final_phi": final_phi,
                "iterations": len(phi_progress),
                "stdout": "".join(lines)[-3000:],
            }
        phi_csv = ws / f"{base_name}.phi.actual.csv"
        final_phi_mean: float | None = None
        final_phi_std: float | None = None
        iterations = 0
        if phi_csv.exists():
            phi_progress, _ = _read_phi_csv(phi_csv)
            iterations = len(phi_progress)
            if phi_progress:
                phi_vals = [row["phi"] for row in phi_progress]
                final_phi_mean = float(np.mean(phi_vals))
                final_phi_std = float(np.std(phi_vals))
        return {
            "model": model,
            "pst_file": str(pst_path),
            "converged": returncode == 0,
            "final_phi_mean": final_phi_mean,
            "final_phi_std": final_phi_std,
            "iterations": iterations,
            "num_reals": num_reals,
            "stdout": "".join(lines)[-3000:],
        }

    job = jobs.submit(
        model,
        method,
        _worker,
        process=proc,
        progress_fn=lambda _j: _pestpp_progress(ws, base_name, method),
    )
    return {
        "model": model,
        "job_id": job.job_id,
        "kind": method,
        "pst_file": str(pst_path),
        "status": "running",
        "note": "Poll progress with get_job_status; stop with cancel_job.",
    }


def _parse_par_file(par_file: Path) -> dict[str, float]:
    """Read a PEST-format .par file and return {par_name: value}.

    Raises
    ------
    OSError / UnicodeDecodeError
        When the file cannot be read (a malformed .par must surface as an
        error rather than silently returning ``{}`` — 7e-B3).
    """
    values: dict[str, float] = {}
    lines = par_file.read_text().strip().splitlines()
    # First line is the header ("single point" or similar); skip it.
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2:
            try:
                values[parts[0].lower()] = float(parts[1])
            except ValueError:
                pass
    return values


def _compute_residual_stats(res_df) -> dict:
    """Compute RMSE, bias, and R² from a pyEMU residuals DataFrame."""
    try:
        active = res_df[res_df["weight"] > 0]
        if len(active) == 0:
            return {"rmse": None, "bias": None, "r_squared": None, "n_observations": 0}

        measured = active["measured"].astype(float)
        modelled = active["modelled"].astype(float)
        resid = measured - modelled

        rmse = float(np.sqrt((resid**2).mean()))
        bias = float(resid.mean())
        ss_res = float((resid**2).sum())
        ss_tot = float(((measured - measured.mean()) ** 2).sum())
        r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

        return {
            "rmse": rmse,
            "bias": bias,
            "r_squared": r_squared,
            "n_observations": len(active),
        }
    except (KeyError, TypeError, ValueError, pd.errors.ParserError):
        return {"rmse": None, "bias": None, "r_squared": None, "n_observations": 0}


# ---------------------------------------------------------------------------
# PEST++ tool implementations
# ---------------------------------------------------------------------------


def _parse_ins_obs_names(ins_path: Path) -> list[str]:
    """Extract observation names from a PEST++ instruction file.

    Supports both classic PEST instruction files (``l2 w w !W1! !W2!``) and
    pyemu's pif/jif (usecol-style) instruction files. Returns ``[]`` if no
    names can be found.
    """
    text = ins_path.read_text()
    lines = text.splitlines()
    if not lines:
        return []
    header = lines[0].strip().lower()
    if header.startswith(("pif", "jif")):
        try:
            names = pyemu.pst_utils.parse_ins_file(str(ins_path))
            if names:
                return list(names)
        except (ValueError, TypeError, KeyError):
            pass
    # Classic PEST format: tokens enclosed in !...!
    return re.findall(r"!([^!]+)!", text)


def _build_model_obs_interface(model: str, ws: Path) -> tuple[list[str], dict, list[str]]:
    """Build the obs interface from registered observation targets (7f-F1.5).

    Returns ``(instruction_file_paths, obs_data, output_files)`` for use by
    ``setup_pest_control(obs_source="model")``.  The generated instruction
    file is a pyemu pif that reads the model's obs CSV (first data row — the
    single row for the steady-state models this is aimed at); each site's
    observed value is the mean of its registered records.
    """
    import numpy as np

    from groundwater_mcp.utils.model_store import read_meta

    obs = read_meta(model).get("observations")
    if not obs or not obs.get("sites"):
        raise ValueError(
            "obs_source='model' requires observation targets registered via "
            "import_obs_from_csv. No 'observations' entry found in "
            ".gwmcp_meta.json for this model."
        )

    output_csv = str(obs["output_csv"])
    entries = list(obs["sites"])

    # PEST caps observation names at 20 characters; the obs CSV columns are
    # the (up to 40-char) OBS package names, so tokens are read positionally.
    names: list[str] = []
    for entry in entries:
        name = str(entry["site"])[:20]
        names.append(name)
    if len(set(names)) != len(names):
        raise ValueError(
            "Obs names collide after truncation to 20 characters (PEST "
            "obsnme limit). Use shorter, distinct site names."
        )

    ins_path = str(ws / f"{output_csv}.ins")
    _impl_generate_ins_from_obs_csv(str(ws / output_csv), ins_path=ins_path, obs_names=names)

    obs_data = {
        name: {
            "obsval": float(np.mean([float(v) for v in entry["values"]])),
            "weight": 1.0,
            "obgnme": str(obs.get("type", "HEAD")).lower() + "_obs",
        }
        for name, entry in zip(names, entries)
    }
    return [str(ins_path)], obs_data, [output_csv]


# ---------------------------------------------------------------------------
# H3 — cheap sensitivity screen (7f-H3)
# ---------------------------------------------------------------------------

_SENSITIVITY_TOLERANCE = 1e-3


def _tpl_substitute(tpl: Path, target: Path, values: dict[str, float]) -> None:
    """Write the model-input file for *values* from a template, preserving
    token widths so fixed-width files stay valid. The template header line
    (``ptf ~``) and the token markers are not part of the model input file."""
    lines = tpl.read_text().splitlines()
    marker = lines[0].split()[1]
    out = []
    for line in lines[1:]:
        new = line
        for name, value in values.items():
            pat = re.compile(
                re.escape(marker) + r"\s*" + re.escape(name) + r"\s*" + re.escape(marker)
            )
            m = pat.search(new)
            if m:
                token = m.group(0)
                inner_len = len(token) - 2 * len(marker)
                inner = f"{value!s}".center(inner_len)
                new = new[: m.start()] + inner + new[m.end() :]
        out.append(new)
    target.write_text("\n".join(out) + "\n")


def _impl_check_parameter_sensitivity(
    model: str,
    parameters: dict[str, float],
    template_files: list[str],
    delta: float = 0.1,
) -> dict:
    """Cheap n+1 forward-run sensitivity screen (7f-H3.1).

    ``parameters`` maps parameter name → base value. A template may define one
    token per parameter (the legacy one-template-per-parameter case) or several
    tokens (e.g. a zoned ``<gwf>_k_mult.dat.tpl`` with a token per zone). Each
    template's target file must be one the model actually reads (e.g. an NPF
    ``k`` array via ``OPEN/CLOSE hk.dat`` with template ``hk.dat.tpl``). Runs the
    base model, then each parameter at ``base * (1 + delta)`` with every other
    token at its base value, and reports per-parameter sensitivity = mean
    relative change of the simulated observation set.
    """
    from groundwater_mcp.tools.postprocess import _read_simulated_observations_values
    from groundwater_mcp.tools.runner import _impl_run_simulation

    ws = resolve_workspace(model)

    tpl_targets: list[tuple[Path, Path]] = []
    all_tokens: list[str] = []
    for tpl_name in template_files:
        tpl = Path(tpl_name) if Path(tpl_name).is_absolute() else ws / tpl_name
        if not tpl.exists():
            raise FileNotFoundError(f"Template file not found: {tpl}")
        first = tpl.read_text().splitlines()[0].strip().lower()
        if not first.startswith(("ptf", "jtf")):
            raise ValueError(f"Template file must start with [ptf,jtf]: {tpl}")
        names = pyemu.pst_utils.parse_tpl_file(str(tpl))
        unknown = [n for n in names if n not in parameters]
        if unknown:
            raise ValueError(
                f"Template {tpl.name} defines tokens {unknown} not in "
                f"parameters {list(parameters)}."
            )
        for n in names:
            if n not in all_tokens:
                all_tokens.append(n)
        tpl_targets.append((tpl, tpl.with_suffix("")))

    # Every parameter must appear in at least one template. A parameter absent
    # from every template is never substituted, so the screen would record a
    # spurious sensitivity of 0.0 with run_succeeded=True — fail loudly instead.
    missing = [name for name in parameters if name not in all_tokens]
    if missing:
        raise ValueError(
            f"Parameter(s) {missing} do not appear in any template token. "
            f"Template token(s): {all_tokens}. Every key of 'parameters' must "
            "appear in at least one template."
        )

    base_run = _impl_run_simulation(model, silent=True)
    if not base_run["success"]:
        return _err(
            "CONVERGENCE_FAILED",
            "Base run failed before the sensitivity analysis.",
            "Check the model converges first (run_simulation).",
        )
    base_sim, _, _ = _read_simulated_observations_values(model)
    base_values = {k: v for k, v in base_sim.items() if v is not None and abs(v) > 1e-12}
    if not base_values:
        return _err(
            "MODEL_HAS_NO_OBSERVATIONS",
            "No simulated observation values to measure sensitivity against. "
            "Register observations with import_obs_from_csv and re-run.",
        )

    results: dict = {}
    for name in parameters:
        # Perturb one parameter while holding every other template token at its
        # base value, so multi-token (zoned) templates stay valid on disk.
        substituted = {
            tok: (parameters[tok] * (1.0 + delta) if tok == name else parameters[tok])
            for tok in all_tokens
        }
        originals = {
            target: (target.read_bytes() if target.exists() else None)
            for _, target in tpl_targets
        }
        try:
            for tpl, target in tpl_targets:
                _tpl_substitute(tpl, target, substituted)
                _maybe_apply_zone_multipliers(model, target)
            run = _impl_run_simulation(model, silent=True)
        finally:
            for _, target in tpl_targets:
                original = originals[target]
                if original is not None:
                    target.write_bytes(original)
                _maybe_apply_zone_multipliers(model, target)
            flush_model(model)
        if not run["success"]:
            results[name] = {"sensitivity": None, "run_succeeded": False}
            continue
        sim, _, _ = _read_simulated_observations_values(model)
        rel = [
            abs(sim[site] - base) / base
            for site, base in base_values.items()
            if site in sim and sim[site] is not None
        ]
        results[name] = {
            "sensitivity": float(np.mean(rel)) if rel else None,
            "run_succeeded": True,
        }

    # Persist the sensitivity results so setup_pest_control can warn on
    # insensitive parameters (7f-H3.2).
    meta = read_meta(model)
    meta["sensitivity"] = {
        "delta": delta,
        "parameters": results,
        "insensitive": [
            k
            for k, r in results.items()
            if r.get("sensitivity") is not None and r["sensitivity"] < _SENSITIVITY_TOLERANCE
        ],
    }
    write_meta(model, meta)

    return {
        "model": model,
        "delta": delta,
        "n_forward_runs": len(parameters) + 1,
        "parameters": results,
    }


def _choose_method(
    n_adjustable: int, n_observations: int, time_budget_minutes: float
) -> tuple[str, str]:
    """Choose GLM vs IES for a calibration problem (7f-H4.1).

    IES (iterative ensemble smoother) handles many adjustable parameters
    cheaply per run; GLM (gradient-based) is the best small-problem default.
    """
    if n_adjustable > 50:
        return "ies", (
            f"{n_adjustable} adjustable parameters > 50 — IES handles high-"
            "dimensional problems without a Jacobian."
        )
    if time_budget_minutes < 5:
        return "glm", (
            f"time_budget of {time_budget_minutes:.0f} min is tight — GLM is "
            "the fastest single-start option for this small problem."
        )
    return "glm", (
        f"{n_adjustable} adjustable parameters and {n_observations} observations "
        "— GLM (gradient-based) is appropriate for this size."
    )


def _impl_calibrate(
    model: str,
    par_data: dict,
    template_files: list[str],
    time_budget_minutes: float = 30.0,
    noptmax: int = 10,
    num_reals: int = 50,
) -> dict:
    """Choose and run the calibration method (7f-H4.1).

    Builds the PEST interface from the registered observation targets
    (``obs_source="model"``), chooses GLM vs IES from the problem size and
    time budget, and runs the chosen engine.
    """
    obs_meta = read_meta(model).get("observations")
    n_obs = len(obs_meta.get("sites", [])) if obs_meta else 0
    n_adjustable = sum(
        1 for attrs in par_data.values() if str(attrs.get("partrans", "log")).lower() != "fixed"
    )
    method, rationale = _choose_method(n_adjustable, n_obs, time_budget_minutes)

    setup = _impl_setup_pest_control(
        model=model,
        obs_data={},
        par_data=par_data,
        template_files=template_files,
        instruction_files=[],
        obs_source="model",
        pestpp_options={"noptmax": int(noptmax)},
    )
    if setup.get("error"):
        return setup
    pst_file = setup["pst_file"]

    if method == "glm":
        result = _impl_run_pestpp_glm(model, pst_file, num_workers=1)
    else:
        result = _impl_run_pestpp_ies(model, pst_file, num_reals=num_reals, num_workers=1)

    result["method"] = method
    result["rationale"] = rationale
    result["n_adjustable_parameters"] = n_adjustable
    result["n_observations"] = n_obs
    return result


# ---------------------------------------------------------------------------
# 7e-A2 — automated calibration setup (setup_calibration)
# ---------------------------------------------------------------------------


def _impl_rewire_npf_k_external(model: str, filename: str | None = None) -> dict:
    """Rewrite the NPF package so ``k`` is read via ``OPEN/CLOSE <file>``.

    The current ``k`` array is written to the external file (flopy handles the
    on-disk write) so a PEST template can target it. The model runs unchanged
    afterwards — the array values are identical, only their storage moved.

    Parameters
    ----------
    model:
        Registered model name.
    filename:
        External-array filename (relative to the workspace). Defaults to
        ``<gwf_name>_k.dat``.

    Returns
    -------
    dict
        ``{model, package, keyword, external_file, written}``.
    """
    gwf = get_gwf(model)
    npf = gwf.get_package("npf")
    if npf is None:
        raise ValueError(
            "No NPF package found; run add_npf_package before rewiring k to an external array."
        )
    filename = filename or f"{gwf.name}_k.dat"
    k_arr = np.asarray(npf.k.array)
    npf.k.set_data({"filename": filename, "data": k_arr})
    sim = gwf.simulation
    save_sim(model, sim)
    flush_model(model)
    return {
        "model": model,
        "package": "NPF",
        "keyword": "k",
        "external_file": filename,
        "written": True,
    }


_SUPPORTED_TARGETS = ("npf:k",)
_TPL_TOKEN_WIDTH = 15


def _restore_or_snapshot_k_base(model: str) -> np.ndarray:
    """Return the base NPF ``k`` array, snapshotting it on first use.

    ``setup_calibration`` rewires NPF ``k`` to an external file that a later
    setup call may overwrite. Without a snapshot, a repeated or mixed-scope
    setup parameterises a mutated field and can silently flatten K (the
    neversink rerun-2 finding: a layer-scope setup wrote its absolute
    ``initial`` into the shared external array, and a later zones setup then saw
    a single uniform zone).

    The base array is captured once in ``<gwf>_k_pristine.npy`` and restored
    into NPF before every setup, which makes ``setup_calibration`` safely
    re-runnable. A tool that deliberately changes ``k`` clears the snapshot via
    ``model_store.clear_k_base_snapshot`` so the next setup re-snapshots the new
    field rather than reverting the edit.
    """
    gwf = get_gwf(model)
    npf = gwf.get_package("npf")
    if npf is None:
        raise ValueError(
            "No NPF package found; run add_npf_package before setup_calibration."
        )
    path = resolve_workspace(model) / f"{gwf.name}_k_pristine.npy"
    current = np.asarray(npf.k.array, dtype=float)
    if path.exists():
        k = np.load(path)
        if current.shape != k.shape:
            raise ValueError(
                f"NPF k shape {current.shape} does not match the pristine "
                f"snapshot shape {k.shape}."
            )
    else:
        k = current.copy()
        np.save(path, k)
    npf.k.set_data(k)
    return k


def _round_sig_array(values: np.ndarray, sig: int = 6) -> np.ndarray:
    """Round an array to `sig` significant figures, element-wise.

    Used to group K cells into zones: float representation noise must not
    split a shipped zone value into two zones, while the shipped values
    (0.050292, 0.16764, ...) stay distinct.
    """
    arr = np.asarray(values, dtype=float)
    out = np.array(arr, dtype=float, copy=True)
    nz = np.isfinite(arr) & (arr != 0)
    x = np.abs(arr[nz])
    exp = np.floor(np.log10(x))
    factor = 10.0 ** (sig - 1 - exp)
    out[nz] = np.sign(arr[nz]) * (np.round(x * factor) / factor)
    return out


def _derive_zones(k_layer, max_zones: int) -> tuple[np.ndarray, list[tuple[float, int]]]:
    """Group a layer's cells into zones of equal positive K value.

    Returns ``(zone_ids, zones)``: zone_ids is an int array the same shape as
    ``k_layer`` with 0 for fixed (non-positive/non-finite) cells, and zones is
    a list of ``(base_k, n_cells)`` sorted ascending by base_k.
    """
    k_arr = np.asarray(k_layer, dtype=float)
    flat = k_arr.reshape(-1)
    positive = np.isfinite(flat) & (flat > 0)
    if not positive.any():
        raise ValueError("layer has no positive K cells to zone.")
    rounded = _round_sig_array(flat, 6)
    values = np.unique(rounded[positive])
    if len(values) > max_zones:
        raise ValueError(
            f"layer has {len(values)} distinct K values, more than "
            f"max_zones={max_zones}; use a coarser zone input or raise max_zones."
        )
    zone_ids = np.zeros(k_arr.shape, dtype=int)
    zone_ids_flat = zone_ids.reshape(-1)
    zones: list[tuple[float, int]] = []
    for i, v in enumerate(values, start=1):
        mask = positive & (rounded == v)
        zone_ids_flat[mask] = i
        zones.append((float(v), int(mask.sum())))
    return zone_ids, zones


def _apply_k_multipliers(base_path, zone_path, mult_path, out_path) -> np.ndarray:
    """Write ``k = base_k × multiplier[zone]`` (zone 0 fixed) to ``out_path``.

    The ``base`` and ``zone`` arrays must be the same length (one entry per
    model cell) and every positive zone id must index an available multiplier.
    Both are validated up front so a malformed zone map raises a clear
    ``ValueError`` instead of a raw numpy ``IndexError`` mid-run.
    """
    base = np.loadtxt(base_path, dtype=float).reshape(-1)
    zone = np.loadtxt(zone_path, dtype=int).reshape(-1)
    mult = np.atleast_1d(np.loadtxt(mult_path, dtype=float)).reshape(-1)
    if base.size != zone.size:
        raise ValueError(
            f"base ({base.size}) and zone ({zone.size}) arrays must be the "
            "same length."
        )
    if zone.size and int(zone.min()) < 0:
        raise ValueError("zone ids must be non-negative (0 marks a fixed cell).")
    max_zone = int(zone.max()) if zone.size else 0
    if max_zone > mult.size:
        raise ValueError(
            f"zone map references zone {max_zone} but only {mult.size} "
            "multiplier(s) provided."
        )
    factor = np.ones_like(base, dtype=float)
    zoned = zone > 0
    factor[zoned] = mult[zone[zoned] - 1]
    k = base * factor
    np.savetxt(out_path, k, fmt="%.10g")
    return k


def _maybe_apply_zone_multipliers(model: str, target: Path) -> None:
    """Apply zone multipliers to the NPF k file when *target* is the
    multiplier file of a zoned setup; otherwise do nothing."""
    gwf = get_gwf(model)
    ws = resolve_workspace(model)
    base = ws / f"{gwf.name}_k_base.dat"
    zone = ws / f"{gwf.name}_k_zone.dat"
    if target.name == f"{gwf.name}_k_mult.dat" and base.exists() and zone.exists():
        _apply_k_multipliers(base, zone, target, ws / f"{gwf.name}_k.dat")


def _normalise_zoned_parameterisation(model: str, parameterisation: dict) -> dict:
    """Validate and normalise a ``setup_calibration`` zoned parameterisation.

    Every spec must use ``scope="zones"`` with a ``layer``; zones are derived
    from equal positive K values within that layer. Zone indices are global,
    contiguous and ordered by ``(layer ascending, base K ascending)``.
    """
    if not isinstance(parameterisation, dict):
        raise ValueError(
            "parameterisation must be a dict mapping parameter name → spec, "
            f"got {type(parameterisation).__name__}."
        )
    if not parameterisation:
        raise ValueError("parameterisation must name at least one parameter.")
    gwf = get_gwf(model)
    npf = gwf.get_package("npf")
    if npf is None:
        raise ValueError(
            "No NPF package found; run add_npf_package before zoned parameterisation."
        )
    dis = get_dis(gwf)
    disv = get_disv(gwf)
    if dis is not None and disv is None:
        nlay = int(dis.nlay.data)
        nrow = int(dis.nrow.data)
        ncol = int(dis.ncol.data)
        per_layer = nrow * ncol
        grid = {
            "type": "DIS",
            "nlay": nlay,
            "nrow": nrow,
            "ncol": ncol,
            "per_layer": per_layer,
            "ncell": nlay * per_layer,
        }
    elif disv is not None:
        nlay = int(disv.nlay.data)
        ncpl = int(disv.ncpl.data)
        per_layer = ncpl
        grid = {
            "type": "DISV",
            "nlay": nlay,
            "ncpl": ncpl,
            "per_layer": per_layer,
            "ncell": nlay * per_layer,
        }
    else:
        disu = get_disu(gwf)
        if disu is None:
            raise ValueError("No grid package (DIS/DISV/DISU) found on the model.")
        per_layer = int(disu.nodes.data)
        nlay = 1
        grid = {
            "type": "DISU",
            "nlay": nlay,
            "nnodes": per_layer,
            "per_layer": per_layer,
            "ncell": per_layer,
        }

    k_base = np.asarray(npf.k.array, dtype=float).reshape(-1)
    if k_base.size != grid["ncell"]:
        raise ValueError(
            f"NPF k has {k_base.size} values; grid has {grid['ncell']} cells."
        )

    specs: list[tuple[str, dict, int]] = []
    for name, spec in parameterisation.items():
        key = str(name)
        if not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise ValueError(
                f"Parameter prefix '{key}' must contain only letters, digits and underscores."
            )
        if not isinstance(spec, dict):
            raise ValueError(f"Parameter '{key}' must be a spec dict.")
        scope = spec.get("scope", "all")
        if scope != "zones":
            raise ValueError(
                "Zoned parameterisation cannot be combined with scope "
                f"'{scope}' (parameter '{key}'); all specs must use scope='zones'."
            )
        target = spec.get("target")
        if target not in _SUPPORTED_TARGETS:
            raise ValueError(
                f"Unsupported parameterisation target '{target}'. Supported: "
                f"{list(_SUPPORTED_TARGETS)}."
            )
        layer = spec.get("layer")
        if layer is None:
            raise ValueError(f"Parameter '{key}' scope=zones requires 'layer'.")
        layer = int(layer)
        if not (0 <= layer < nlay):
            raise ValueError(
                f"Parameter '{key}' layer {layer} out of range (nlay={nlay})."
            )
        specs.append((key, spec, layer))

    if len({s[2] for s in specs}) != len(specs):
        raise ValueError("Each layer may appear in at most one zones spec.")

    zone_map = np.zeros(grid["ncell"], dtype=int)
    parameters: list[dict] = []
    zones_out: list[dict] = []
    next_index = 1
    for key, spec, layer in sorted(specs, key=lambda s: s[2]):
        max_zones = int(spec.get("max_zones", 50))
        if max_zones < 1:
            raise ValueError(f"Parameter '{key}' max_zones must be >= 1.")
        initial = float(spec.get("initial", 1.0))
        if not np.isfinite(initial) or initial <= 0:
            raise ValueError(f"Parameter '{key}' initial multiplier must be positive.")
        lower_factor = float(spec.get("lower_factor", 0.1))
        upper_factor = float(spec.get("upper_factor", 10.0))
        if lower_factor >= 1.0 or upper_factor <= 1.0:
            raise ValueError(
                f"Parameter '{key}': lower_factor must be < 1 and upper_factor > 1."
            )
        partrans = str(spec.get("partrans", "log")).lower()

        offset = layer * per_layer
        slice_ids, zone_vals = _derive_zones(
            k_base[offset : offset + per_layer], max_zones
        )
        for local_id, (base_k, n_cells) in enumerate(zone_vals, start=1):
            pname = f"{key}_z{next_index}"
            if len(pname) > 12:
                raise ValueError(
                    f"Zone parameter name '{pname}' is {len(pname)} characters; "
                    "PEST caps parameter names at 12. Use a shorter prefix."
                )
            zone_map[offset : offset + per_layer][slice_ids == local_id] = next_index
            parameters.append(
                {
                    "name": pname,
                    "target": "npf:k",
                    "scope": "zones",
                    "layer": layer,
                    "initial": initial,
                    "lower_bound": initial * lower_factor,
                    "upper_bound": initial * upper_factor,
                    "partrans": partrans,
                }
            )
            zones_out.append(
                {
                    "name": pname,
                    "index": next_index,
                    "layer": layer,
                    "base_k": base_k,
                    "n_cells": n_cells,
                    "initial": initial,
                    "lower_bound": initial * lower_factor,
                    "upper_bound": initial * upper_factor,
                    "partrans": partrans,
                }
            )
            next_index += 1

    return {
        "grid": grid,
        "k_base": k_base,
        "zone_map": zone_map,
        "zones": zones_out,
        "parameters": parameters,
    }


def _normalise_parameterisation(model: str, parameterisation: dict) -> dict:
    """Validate and normalise a ``setup_calibration`` parameterisation spec.

    A parameterisation maps parameter name → spec dict::

        {
            "target": "npf:k",              # model array to parameterise
            "scope": "all" | "layer" | "cells",
            "layer": 0,                      # required when scope == "layer"
            "cells": [[0, 0, 0], ...],       # required when scope == "cells"
            "initial": 5.0,                  # base value (required, > 0)
            "lower_factor": 0.1,             # bound = initial * factor
            "upper_factor": 10.0,
            "partrans": "log",               # default "log"
        }

    Returns the grid info plus per-parameter resolved cell indices::

        {
            "grid": {"type": "DIS"|"DISV", "nlay": ..., "nrow": ...,
                     "ncol": ..., "ncpl": ..., "ncell": ...},
            "cell_to_flat": callable,
            "parameters": [{name, target, scope, layer, cells (flat list),
                            initial, lower_bound, upper_bound, partrans}],
            "cell_param": {flat_index: name},
        }
    """
    if not parameterisation:
        raise ValueError("parameterisation must name at least one parameter.")
    gwf = get_gwf(model)
    dis = get_dis(gwf)
    disv = get_disv(gwf)
    if dis is not None:
        nlay, nrow, ncol = (
            int(dis.nlay.data),
            int(dis.nrow.data),
            int(dis.ncol.data),
        )
        ncell = nlay * nrow * ncol

        def cell_to_flat(cell) -> int:
            if len(cell) != 3:
                raise ValueError(f"Cell {cell} must be [layer, row, col] on a DIS grid.")
            lay, r, c = (int(v) for v in cell)
            if not (0 <= lay < nlay and 0 <= r < nrow and 0 <= c < ncol):
                raise ValueError(f"Cell {cell} out of bounds on a {nlay}x{nrow}x{ncol} grid.")
            return lay * (nrow * ncol) + r * ncol + c

        grid = {"type": "DIS", "nlay": nlay, "nrow": nrow, "ncol": ncol, "ncell": ncell}
    elif disv is not None:
        nlay, ncpl = int(disv.nlay.data), int(disv.ncpl.data)
        ncell = nlay * ncpl

        def cell_to_flat(cell) -> int:
            if len(cell) != 2:
                raise ValueError(f"Cell {cell} must be [layer, node] on a DISV grid.")
            lay, node = (int(v) for v in cell)
            if not (0 <= lay < nlay and 0 <= node < ncpl):
                raise ValueError(f"Cell {cell} out of bounds on a {nlay}x{ncpl} DISV grid.")
            return lay * ncpl + node

        grid = {"type": "DISV", "nlay": nlay, "ncpl": ncpl, "ncell": ncell}
    else:
        disu = get_disu(gwf)
        if disu is None:
            raise ValueError("No grid package (DIS/DISV/DISU) found on the model.")
        nnodes = int(disu.nodes.data)
        nlay, ncell = 1, nnodes

        def cell_to_flat(cell) -> int:
            if isinstance(cell, (int, np.integer)):
                node = int(cell)
            else:
                if len(cell) != 1:
                    raise ValueError(f"Cell {cell} must be a node id on a DISU grid.")
                node = int(cell[0])
            if not (0 <= node < nnodes):
                raise ValueError(f"Cell {cell} out of bounds on a {nnodes}-node DISU grid.")
            return node

        grid = {"type": "DISU", "nlay": nlay, "nnodes": nnodes, "ncell": ncell}

    params: list[dict] = []
    for name, spec in parameterisation.items():
        name = str(name)
        if len(name) > 12:
            raise ValueError(
                f"Parameter name '{name}' is {len(name)} characters; PEST caps "
                "parameter names at 12 characters. Use a shorter name."
            )
        if not isinstance(spec, dict):
            raise ValueError(f"Parameter '{name}' must be a spec dict.")
        target = spec.get("target")
        if target not in _SUPPORTED_TARGETS:
            raise ValueError(
                f"Unsupported parameterisation target '{target}'. Supported: "
                f"{list(_SUPPORTED_TARGETS)}."
            )
        scope = spec.get("scope", "all")
        if scope not in ("all", "layer", "cells"):
            raise ValueError(f"scope must be 'all', 'layer' or 'cells', got '{scope}'.")
        if "initial" not in spec:
            raise ValueError(f"Parameter '{name}' is missing required 'initial'.")
        initial = float(spec["initial"])
        if not np.isfinite(initial) or initial <= 0:
            raise ValueError(f"Parameter '{name}' initial must be a positive number.")
        lower_factor = float(spec.get("lower_factor", 0.1))
        upper_factor = float(spec.get("upper_factor", 10.0))
        if lower_factor >= 1.0 or upper_factor <= 1.0:
            raise ValueError(f"Parameter '{name}': lower_factor must be < 1 and upper_factor > 1.")

        cells: list[int] = []
        if scope == "all":
            cells = list(range(ncell))
        elif scope == "layer":
            layer = spec.get("layer")
            if layer is None:
                raise ValueError(f"Parameter '{name}' scope=layer requires 'layer'.")
            layer = int(layer)
            if not (0 <= layer < nlay):
                raise ValueError(f"Parameter '{name}' layer {layer} out of range (nlay={nlay}).")
            per_layer = ncell // nlay
            cells = list(range(layer * per_layer, (layer + 1) * per_layer))
        else:  # scope == "cells"
            raw_cells = spec.get("cells")
            if not raw_cells:
                raise ValueError(f"Parameter '{name}' scope=cells requires 'cells'.")
            cells = [cell_to_flat(c) for c in raw_cells]

        params.append(
            {
                "name": name,
                "target": target,
                "scope": scope,
                "layer": spec.get("layer"),
                "cells": cells,
                "initial": initial,
                "lower_bound": initial * lower_factor,
                "upper_bound": initial * upper_factor,
                "partrans": str(spec.get("partrans", "log")).lower(),
            }
        )

    # Assign cells to parameters; every cell must be claimed exactly once.
    cell_param: dict[int, str] = {}
    for p in params:
        for idx in p["cells"]:
            if idx in cell_param:
                raise ValueError(
                    f"Cell {idx} is claimed by both '{cell_param[idx]}' and "
                    f"'{p['name']}' — parameter scopes must not overlap."
                )
            cell_param[idx] = p["name"]
    if len(cell_param) != ncell:
        raise ValueError(
            f"Parameterisation covers {len(cell_param)} of {ncell} cells; "
            f"{ncell - len(cell_param)} cells are unassigned. Add a parameter "
            "with scope='all' (or cover every cell) so the template can be "
            "written for the whole array."
        )

    return {
        "grid": grid,
        "cell_to_flat": cell_to_flat,
        "parameters": params,
        "cell_param": cell_param,
    }


def _impl_generate_tpl(model: str, parameterisation: dict, target_file: str | None = None) -> dict:
    """Generate a PEST template for the parameterised cells (7e-A2.2).

    One wide fixed-width token per array cell in the external file's layout
    (layer-major, then row/node-major), each referencing the parameter that
    owns the cell. The template is written as ``<target_file>.tpl`` so the
    ``.tpl``-stripped name is the file the model actually reads.

    Returns ``{tpl_path, target, parameters}``.
    """
    ws = resolve_workspace(model)
    norm = _normalise_parameterisation(model, parameterisation)
    gwf = get_gwf(model)

    if target_file is None:
        target_file = f"{gwf.name}_k.dat"
    tpl_path = ws / f"{target_file}.tpl"

    order: dict[int, str] = {}
    for idx in range(norm["grid"]["ncell"]):
        order[idx] = norm["cell_param"][idx]
    lines = ["ptf ~"]
    for idx in range(norm["grid"]["ncell"]):
        name = order[idx]
        lines.append("~" + f"{name:^{_TPL_TOKEN_WIDTH}s}" + "~")
    tpl_path.write_text("\n".join(lines) + "\n")

    return {
        "tpl_path": str(tpl_path),
        "target": str(ws / target_file),
        "parameters": norm["parameters"],
    }


def _impl_generate_zone_mult_tpl(model: str, zones: list[dict], target_file: str) -> dict:
    """Generate a PEST template with exactly one wide token per zone.

    The target file holds one multiplier per line, in ``zones`` order — the
    order the forward wrapper reads and the order the returned ``zones`` list
    reports.
    """
    ws = resolve_workspace(model)
    if not zones:
        raise ValueError("zones must contain at least one zone to template.")
    tpl_path = ws / f"{target_file}.tpl"
    lines = ["ptf ~"]
    for zone in zones:
        lines.append("~" + f"{zone['name']:^{_TPL_TOKEN_WIDTH}s}" + "~")
    tpl_path.write_text("\n".join(lines) + "\n")
    return {"tpl_path": str(tpl_path), "target": str(ws / target_file)}


def _impl_generate_ins_from_obs_csv(
    csv_path: str, ins_path: str | None = None, obs_names: list[str] | None = None
) -> dict:
    """Generate a canonical pyemu pif instruction file from an OBS CSV (7e-A2.3).

    The MF6 OBS continuous CSV has a ``time`` column followed by one column
    per observation site. The generated pif skips the header row and the
    ``time`` token, then reads each site's value::

        pif ~
        l1
        l1 ~,~ !S01! !S02! ...

    When ``obs_names`` is given (e.g. the obs CSV does not exist yet because
    the model has not run), the header is not read; names are taken verbatim.
    Names are truncated to PEST's 20-character obsnme cap; a collision after
    truncation is a hard error.

    Returns ``{ins_path, obs_names}``.
    """
    if obs_names is None:
        p = Path(csv_path)
        if not p.exists():
            raise FileNotFoundError(f"Observation CSV not found: {csv_path}")
        cols = list(pd.read_csv(p, nrows=0).columns)
        obs_names = [str(c)[:20] for c in cols if str(c) != "time"]
    if not obs_names:
        raise ValueError(f"No observation columns found in {csv_path}.")
    if len(set(obs_names)) != len(obs_names):
        raise ValueError(
            "Observation names collide after truncation to 20 characters "
            "(PEST obsnme limit). Use shorter, distinct site names."
        )
    if ins_path is None:
        ins_path = f"{csv_path}.ins"
    lines = [
        "pif ~",
        "l1",
        "l1 " + "".join(f"~,~   !{n}!  " for n in obs_names).strip(),
    ]
    Path(ins_path).write_text("\n".join(lines) + "\n")
    return {"ins_path": ins_path, "obs_names": obs_names}


def _generate_forward_wrapper(model: str, multiply_k: bool = False) -> dict:
    """Generate a Python forward-run wrapper at a space-free path (7e-A2.4).

    PEST++ on Windows cannot execute ``.bat``/``.cmd`` wrappers (it hangs
    normalising ``cmd /c``) and cannot launch executables whose path contains
    spaces. This helper emits a plain ``.py`` wrapper — placed at a path with
    no spaces, in the workspace when the workspace path is space-free and in a
    space-free system directory otherwise — that runs MODFLOW 6 in the model
    workspace (the OBS package writes the observations CSV as part of the
    run). The returned ``model_command`` references the wrapper via the quoted
    current Python executable.

    Returns ``{wrapper_path, model_command}`` where ``model_command`` is a
    one-element list suitable for ``pst.model_command``.
    """
    ws = resolve_workspace(model)
    # The wrapper runs the model, so the current in-memory input set must be
    # on disk first (deferred writes, 7f-E1.2).
    flush_model(model)
    try:
        mf6_exe = _find_mf6_binary()
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc} The forward-model wrapper needs the MODFLOW 6 binary; "
            "install it with: get-modflow :"
        ) from exc

    wrapper_name = f"gwmcp_run_{model}.py"
    if " " not in str(ws):
        wrapper_path = ws / wrapper_name
    else:
        candidates = [Path(tempfile.gettempdir()), Path.home()]
        space_free = next((c for c in candidates if " " not in str(c)), None)
        if space_free is None:
            raise RuntimeError(
                "No space-free directory found for the forward-model wrapper. "
                "PEST++ on Windows cannot launch executables whose path "
                "contains spaces; set the workspace at a path without spaces "
                "or set TMP to a space-free location."
            )
        wrapper_path = space_free / wrapper_name

    if multiply_k:
        gwf_name = get_gwf(model).name
        base_name = f"{gwf_name}_k_base.dat"
        zone_name = f"{gwf_name}_k_zone.dat"
        mult_name = f"{gwf_name}_k_mult.dat"
        k_name = f"{gwf_name}_k.dat"
        # Self-contained: the multiplier logic is inlined (no import from
        # groundwater_mcp), so a PEST++ forward run does not depend on the
        # installed package or on any private helper.
        wrapper_path.write_text(
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            "\n"
            "import numpy as np\n"
            "\n"
            f"WS = {str(ws)!r}\n"
            f"MF6 = {mf6_exe!r}\n"
            f"BASE = os.path.join(WS, {base_name!r})\n"
            f"ZONE = os.path.join(WS, {zone_name!r})\n"
            f"MULT = os.path.join(WS, {mult_name!r})\n"
            f"KFILE = os.path.join(WS, {k_name!r})\n"
            "\n"
            "os.chdir(WS)\n"
            "base = np.loadtxt(BASE, dtype=float).reshape(-1)\n"
            "zone = np.loadtxt(ZONE, dtype=int).reshape(-1)\n"
            "mult = np.atleast_1d(np.loadtxt(MULT, dtype=float)).reshape(-1)\n"
            "factor = np.ones_like(base, dtype=float)\n"
            "zoned = zone > 0\n"
            "factor[zoned] = mult[zone[zoned] - 1]\n"
            'np.savetxt(KFILE, base * factor, fmt="%.10g")\n'
            "proc = subprocess.run([MF6], cwd=WS)\n"
            "sys.exit(proc.returncode)\n"
        )
    else:
        wrapper_path.write_text(
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            f"\nWS = {str(ws)!r}\n"
            f"MF6 = {mf6_exe!r}\n"
            "\n"
            "os.chdir(WS)\n"
            "proc = subprocess.run([MF6], cwd=WS)\n"
            "sys.exit(proc.returncode)\n"
        )

    # pestpp runs the model command with cwd = the model workspace; reference
    # the wrapper by relative name when it lives there, absolute otherwise.
    cmd_target = wrapper_path.name if wrapper_path.parent == ws else str(wrapper_path)
    model_command = [f'"{sys.executable}" {cmd_target}']
    return {"wrapper_path": str(wrapper_path), "model_command": model_command}


def _needs_forward_wrapper(model: str) -> bool:
    """True when the default model command (the MF6 binary directly) cannot
    be launched by pestpp — the workspace or the binary path contains spaces."""
    if " " in str(resolve_workspace(model)):
        return True
    try:
        return " " in _find_mf6_binary()
    except RuntimeError:
        return False


def _impl_setup_calibration_zoned(
    model: str,
    parameterisation: dict,
    obs_source: str = "model",
    noptmax: int = 10,
) -> dict:
    """Emit a zoned/multiplier PEST interface for NPF k (scope="zones").

    Writes the base K field and an integer zone map, rewires NPF k to an
    external ``OPEN/CLOSE`` file, generates a one-token-per-zone multiplier
    template, and forces a forward wrapper that applies
    ``k = base_k × multiplier[zone]`` before each MODFLOW 6 run. At the default
    multiplier 1.0 the written K field equals the base field.
    """
    ws = resolve_workspace(model)
    _restore_or_snapshot_k_base(model)
    norm = _normalise_zoned_parameterisation(model, parameterisation)
    gwf_name = get_gwf(model).name

    # Validate the observation source up front so a rejected call does not
    # leave a half-configured workspace (base/zone files written, NPF rewired).
    if obs_source != "model":
        raise ValueError(
            f"setup_calibration supports obs_source='model', got '{obs_source}'."
        )
    obs_meta = read_meta(model).get("observations")
    if not obs_meta or not obs_meta.get("sites"):
        raise ValueError(
            "obs_source='model' requires observation targets registered via "
            "import_obs_from_csv. No 'observations' entry found in "
            ".gwmcp_meta.json for this model."
        )

    base_name = f"{gwf_name}_k_base.dat"
    zone_name = f"{gwf_name}_k_zone.dat"
    mult_name = f"{gwf_name}_k_mult.dat"
    k_name = f"{gwf_name}_k.dat"

    np.savetxt(ws / base_name, norm["k_base"], fmt="%.10g")
    np.savetxt(ws / zone_name, norm["zone_map"], fmt="%d")
    _impl_rewire_npf_k_external(model, filename=k_name)

    tpl = _impl_generate_zone_mult_tpl(model, norm["zones"], mult_name)
    tpl_path = Path(tpl["tpl_path"])

    ins_paths, obs_data, output_files = _build_model_obs_interface(model, ws)

    wrapper = _generate_forward_wrapper(model, multiply_k=True)
    model_command = wrapper["model_command"]

    par_data = {
        p["name"]: {
            "parval1": p["initial"],
            "parlbnd": p["lower_bound"],
            "parubnd": p["upper_bound"],
            "partrans": p["partrans"],
            "pargp": "gwmcp",
        }
        for p in norm["parameters"]
    }
    pestpp_options: dict = {"noptmax": int(noptmax), "model_command": model_command}
    if output_files:
        pestpp_options["output_files"] = output_files

    setup = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(tpl_path)],
        instruction_files=ins_paths,
        obs_source="explicit",
        pestpp_options=pestpp_options,
        _suppress_command_warning=True,
    )
    if setup.get("error"):
        return setup

    initial_values = {p["name"]: p["initial"] for p in norm["parameters"]}
    _tpl_substitute(tpl_path, Path(tpl["target"]), initial_values)
    mult = np.array([initial_values[p["name"]] for p in norm["parameters"]])
    factor = np.where(norm["zone_map"] > 0, mult[norm["zone_map"] - 1], 1.0)
    np.savetxt(ws / k_name, norm["k_base"] * factor, fmt="%.10g")

    result: dict = {
        "model": model,
        "pst_file": setup["pst_file"],
        "template_file": str(tpl_path),
        "target_file": tpl["target"],
        "instruction_file": ins_paths[0],
        "external_array": str(ws / k_name),
        "forward_wrapper": wrapper["wrapper_path"],
        "n_observations": setup["n_observations"],
        "n_adjustable_parameters": setup["n_adjustable_parameters"],
        "n_total_parameters": setup["n_total_parameters"],
        "parameters": [
            {
                "name": p["name"],
                "scope": p["scope"],
                "initial": p["initial"],
                "lower_bound": p["lower_bound"],
                "upper_bound": p["upper_bound"],
                "partrans": p["partrans"],
            }
            for p in norm["parameters"]
        ],
        "zones": norm["zones"],
        "grid": norm["grid"],
        "model_command": setup["model_command"],
        "next_steps": (
            "Run the calibration with run_pestpp_glm (or run_pestpp_ies for "
            "many parameters), then summarise_calibration."
        ),
    }
    if any(z["initial"] != 1.0 for z in norm["zones"]):
        result["warning"] = (
            "One or more zone multipliers have initial != 1.0, so the initial "
            "state is not the shipped base K field."
        )
    return result


def _impl_setup_calibration(
    model: str,
    parameterisation: dict,
    obs_source: str = "model",
    noptmax: int = 10,
) -> dict:
    """Automated calibration setup (7e-A2): emit the whole PEST interface.

    One call generates every file the calibration chain needs, with zero
    hand-authored artifacts:

    1.  NPF ``k`` is rewired to an external array (``OPEN/CLOSE <file>``) so a
        template can target it (A2.1).
    2.  A template with wide fixed-width tokens (>= 15 chars) is generated over
        the parameterised cells — scope ``all``, ``layer`` or ``cells`` (zones)
        (A2.2).
    3.  The instruction file is generated from the model's OBS CSV header
        (A2.3).
    4.  When the default forward command would be unsafe on Windows (spaces in
        the workspace or the MF6 binary path), a Python wrapper is written at a
        space-free path (A2.4).
    5.  The ``.pst`` is assembled with safe numeric defaults: ``derinclb > 0``
        on every parameter group and default bounds base/10–base×10 (A2.5).

    ``parameterisation`` maps parameter name → spec dict:

    ``{"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}``
    (scope may be ``"all"``, ``"layer"`` with ``layer``, or ``"cells"`` with
    ``cells`` as a list of ``[layer, row, col]`` — DIS — or ``[layer, node]``
    — DISV. ``lower_factor``/``upper_factor`` default 0.1/10.0 and set the
    bounds from ``initial``; ``partrans`` defaults to ``"log"``.)

    ``obs_source`` must be ``"model"`` (the default): observation targets
    registered by ``import_obs_from_csv`` provide the observed values and the
    instruction file reads the model's obs CSV.

    The template is applied with the initial parameter values so the on-disk
    input array matches the PST's initial state. Run the calibration with
    ``run_pestpp_glm``/``run_pestpp_ies`` (or ``calibrate``) afterwards.
    """
    if not isinstance(parameterisation, dict):
        raise ValueError(
            "parameterisation must be a dict mapping parameter name → "
            f"spec, got {type(parameterisation).__name__}."
        )
    zone_specs = {
        str(n): s
        for n, s in parameterisation.items()
        if isinstance(s, dict) and s.get("scope") == "zones"
    }
    if zone_specs:
        if len(zone_specs) != len(parameterisation):
            raise ValueError(
                "Zoned parameterisation cannot be combined with scope "
                "'all'/'layer'/'cells'; use scope='zones' for every parameter."
            )
        return _impl_setup_calibration_zoned(model, parameterisation, obs_source, noptmax)
    ws = resolve_workspace(model)
    norm = _normalise_parameterisation(model, parameterisation)
    _restore_or_snapshot_k_base(model)

    # 1. Rewire NPF k to an external array so the template can target it.
    ext_file = None
    if any(p["target"] == "npf:k" for p in norm["parameters"]):
        ext_file = _impl_rewire_npf_k_external(model)["external_file"]

    # 2. Generate the wide-token template over the external array.
    tpl = _impl_generate_tpl(model, parameterisation, target_file=ext_file)
    tpl_path = Path(tpl["tpl_path"])

    # 3. Observation interface from the registered targets (obs_source="model").
    if obs_source != "model":
        raise ValueError(f"setup_calibration supports obs_source='model', got '{obs_source}'.")
    obs_meta = read_meta(model).get("observations")
    if not obs_meta or not obs_meta.get("sites"):
        raise ValueError(
            "obs_source='model' requires observation targets registered via "
            "import_obs_from_csv. No 'observations' entry found in "
            ".gwmcp_meta.json for this model."
        )
    ins_paths, obs_data, output_files = _build_model_obs_interface(model, ws)

    # 4. Forward-model command: the wrapper only when the default MF6 command
    #    would be unsafe on Windows.
    wrapper = None
    model_command = None
    if _needs_forward_wrapper(model):
        wrapper = _generate_forward_wrapper(model)
        model_command = wrapper["model_command"]
        wrapper = wrapper["wrapper_path"]

    # 5. Assemble the PST with safe numeric defaults.
    par_data: dict = {}
    for p in norm["parameters"]:
        par_data[p["name"]] = {
            "parval1": p["initial"],
            "parlbnd": p["lower_bound"],
            "parubnd": p["upper_bound"],
            "partrans": p["partrans"],
            "pargp": "gwmcp",
        }
    pestpp_options: dict = {"noptmax": int(noptmax)}
    if output_files:
        pestpp_options["output_files"] = output_files
    if model_command is not None:
        pestpp_options["model_command"] = model_command
    setup = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(tpl_path)],
        instruction_files=ins_paths,
        obs_source="explicit",
        pestpp_options=pestpp_options,
        _suppress_command_warning=model_command is not None,
    )
    if setup.get("error"):
        return setup

    # Apply the template with the initial parameter values so the on-disk
    # array matches the PST's initial state.
    initial_values = {p["name"]: p["initial"] for p in norm["parameters"]}
    _tpl_substitute(tpl_path, Path(tpl["target"]), initial_values)

    return {
        "model": model,
        "pst_file": setup["pst_file"],
        "template_file": str(tpl_path),
        "target_file": tpl["target"],
        "instruction_file": ins_paths[0],
        "external_array": str(ws / ext_file) if ext_file else None,
        "forward_wrapper": wrapper,
        "n_observations": setup["n_observations"],
        "n_adjustable_parameters": setup["n_adjustable_parameters"],
        "n_total_parameters": setup["n_total_parameters"],
        "parameters": [
            {
                "name": p["name"],
                "scope": p["scope"],
                "initial": p["initial"],
                "lower_bound": p["lower_bound"],
                "upper_bound": p["upper_bound"],
                "partrans": p["partrans"],
            }
            for p in norm["parameters"]
        ],
        "model_command": setup["model_command"],
        "next_steps": (
            "Run the calibration with run_pestpp_glm (or run_pestpp_ies for "
            "many parameters), then summarise_calibration."
        ),
    }


# ---------------------------------------------------------------------------
# DA-ready control file (7f-DA): cycle tables + da_* options
# ---------------------------------------------------------------------------


def _write_cycle_table(
    path: Path, names: list[str], cycles: list[int], values: dict
) -> None:
    """Write a PEST++-DA cycle table (header = '' then integer cycles)."""
    lines = ["," + ",".join(str(int(c)) for c in cycles)]
    for name in names:
        by_cycle = values.get(name, {})
        row = [
            f"{by_cycle[c]:g}" if c in by_cycle and by_cycle[c] is not None else ""
            for c in cycles
        ]
        lines.append(f"{name}," + ",".join(row))
    path.write_text("\n".join(lines) + "\n")


_DA_STATE_TOKEN_WIDTH = 30


def _impl_rewire_ic_strt_external(model: str, filename: str | None = None) -> dict:
    """Rewrite the IC package so ``strt`` is read via ``OPEN/CLOSE <file>``.

    Mirrors :func:`_impl_rewire_npf_k_external`: the current starting-head array
    is written to the external file (FloPy handles the on-disk write, so the
    model runs unchanged afterwards) and the IC package reads it. This is the
    hook the DA state parameters need — each cycle's end-of-cycle heads are
    carried into the next cycle's IC through this file.
    """
    gwf = get_gwf(model)
    ic = gwf.get_package("ic")
    if ic is None:
        raise ValueError(
            "No IC package found; run add_ic_package before rewiring strt to an "
            "external array."
        )
    filename = filename or f"{gwf.name}_strt.dat"
    arr = np.asarray(ic.strt.array, dtype=float)
    ic.strt.set_data({"filename": filename, "data": arr})
    save_sim(model, gwf.simulation)
    flush_model(model)
    return {
        "model": model,
        "package": "IC",
        "keyword": "strt",
        "external_file": filename,
        "array": arr,
        "written": True,
    }


def _da_cell_flat_index(model: str, cellid) -> int:
    """Flat (C-order) index of a registered observation cell.

    ``import_obs_from_csv`` stores DIS/DISV cell ids as ``(layer, row, col)`` /
    ``(layer, node)`` and DISU node ids as a scalar 1-based ``node``. The flat
    index matches the layout of the external IC array the template is written
    against.
    """
    gwf = get_gwf(model)
    dis = get_dis(gwf)
    disv = get_disv(gwf)
    if dis is not None and disv is None:
        nlay, nrow, ncol = (
            int(dis.nlay.data),
            int(dis.nrow.data),
            int(dis.ncol.data),
        )
        parts = [int(v) for v in cellid]
        if len(parts) != 3:
            raise ValueError(
                f"Observation cell {cellid!r} must be (layer, row, col) on a DIS grid."
            )
        lay, r, c = parts
        if not (0 <= lay < nlay and 0 <= r < nrow and 0 <= c < ncol):
            raise ValueError(f"Observation cell {cellid!r} is out of bounds on the grid.")
        return lay * (nrow * ncol) + r * ncol + c
    if disv is not None:
        nlay, ncpl = int(disv.nlay.data), int(disv.ncpl.data)
        parts = [int(v) for v in cellid]
        if len(parts) != 2:
            raise ValueError(
                f"Observation cell {cellid!r} must be (layer, node) on a DISV grid."
            )
        lay, node = parts
        if not (0 <= lay < nlay and 0 <= node < ncpl):
            raise ValueError(f"Observation cell {cellid!r} is out of bounds on the grid.")
        return lay * ncpl + node
    disu = get_disu(gwf)
    if disu is not None:
        # DISU cell ids are scalar 1-based node numbers (import_obs_from_csv
        # stores ``node + 1``); the flat index is the 0-based node.
        nnodes = int(disu.nodes.data)
        if isinstance(cellid, (int, np.integer)):
            node = int(cellid)
        else:
            parts = [int(v) for v in cellid]
            if len(parts) != 1:
                raise ValueError(
                    f"Observation cell {cellid!r} must be a 1-based node id on a "
                    "DISU grid."
                )
            node = parts[0]
        flat = node - 1
        if not (0 <= flat < nnodes):
            raise ValueError(f"Observation cell {cellid!r} is out of bounds on the grid.")
        return flat
    raise ValueError(
        "setup_da_control IC state parameterisation supports DIS, DISV and DISU "
        "grids only; this model has none of them."
    )


def _impl_generate_ic_tpl(
    model: str,
    state_cells: dict[int, str],
    ic_base: np.ndarray,
    target_file: str,
) -> dict:
    """Generate the state-augmented IC template.

    One value per line (the external-array layout MODFLOW 6 reads
    sequentially); cells that host a state parameter carry a wide token named
    for the state, every other cell keeps its current starting head. The wide
    token matters: pestpp-da writes full-precision simulated heads into it.
    """
    ws = resolve_workspace(model)
    tpl_path = ws / f"{target_file}.tpl"
    flat = np.asarray(ic_base, dtype=float).reshape(-1)
    lines = ["ptf ~"]
    for idx, value in enumerate(flat):
        name = state_cells.get(idx)
        if name is None:
            lines.append(f"{value:.10g}")
        else:
            lines.append("~" + f"{name:^{_DA_STATE_TOKEN_WIDTH}}" + "~")
    tpl_path.write_text("\n".join(lines) + "\n")
    return {"tpl_path": str(tpl_path), "target": str(ws / target_file)}


def _impl_generate_tdis_tpl(model: str, perlen_name: str) -> dict:
    """Template the TDIS stress-period length so a cycle table can drive it.

    With ``NPER=1``/``NSTP=1`` there is exactly one stress-period length per DA
    cycle; the token is named for the fixed forcing parameter.
    """
    gwf = get_gwf(model)
    sim = gwf.simulation
    tdis = sim.get_package("tdis")
    if tdis is None:
        raise ValueError("No TDIS package found; run set_simulation before setup_da_control.")
    target_file = Path(str(getattr(tdis, "filename", "mfsim.tdis"))).name
    time_units_attr = getattr(tdis, "time_units", None)
    time_units = str(time_units_attr.array) if time_units_attr is not None else "days"
    ws = resolve_workspace(model)
    tpl_path = ws / f"{target_file}.tpl"
    text = (
        "ptf ~\n"
        "BEGIN options\n"
        f"  TIME_UNITS  {time_units}\n"
        "END options\n"
        "BEGIN dimensions\n"
        "  NPER  1\n"
        "END dimensions\n"
        "BEGIN perioddata\n"
        f"  ~{perlen_name:^{_TPL_TOKEN_WIDTH}}~  1  1.0\n"
        "END perioddata\n"
    )
    tpl_path.write_text(text)
    return {"tpl_path": str(tpl_path), "target": str(ws / target_file)}


def _validate_da_prior_spec(
    par_names: list[str],
    prior_ensemble: dict | None,
    prior_std: float | None,
    num_reals: int,
) -> None:
    """Validate the ``da_parameter_ensemble`` spec without touching the model.

    Split out of :func:`_impl_write_da_prior_ensemble` so ``setup_da_control``
    can reject a bad prior *before* it rewires NPF ``k`` / IC ``strt`` (a bad
    prior must not leave the workspace reading uniform ``k``). With neither
    ``prior_ensemble`` nor ``prior_std`` supplied there is nothing to validate.
    """
    if prior_ensemble is None and prior_std is None:
        return
    if prior_ensemble is not None and prior_std is not None:
        raise ValueError(
            "Supply either prior_ensemble or prior_std, not both; prior_ensemble "
            "is an explicit table, prior_std draws one from the parameter values."
        )
    if prior_ensemble is not None:
        if not isinstance(prior_ensemble, dict):
            raise ValueError("prior_ensemble must map parameter name → list of realisations.")
        known = {str(n).lower() for n in par_names}
        unknown: list[str] = []
        lengths: set[int] = set()
        for raw, vals in prior_ensemble.items():
            if str(raw).lower() not in known:
                unknown.append(str(raw))
                continue
            lengths.add(len(vals))
        if unknown:
            raise ValueError(
                f"prior_ensemble names unknown parameter(s) {unknown}; the "
                f"control file parameters are {par_names}."
            )
        if len(lengths) != 1:
            raise ValueError(
                "prior_ensemble columns must all hold the same number of "
                f"realisations, got lengths {sorted(lengths)}."
            )
        if next(iter(lengths)) < 1:
            raise ValueError("prior_ensemble must contain at least one realisation.")
    else:
        if prior_std is None or float(prior_std) <= 0.0:
            raise ValueError("prior_std must be a positive number.")
        if int(num_reals) < 1:
            raise ValueError("num_reals must be a positive integer.")


def _impl_write_da_prior_ensemble(
    model: str,
    pst: pyemu.Pst,
    prior_ensemble: dict | None = None,
    prior_std: float | None = None,
    num_reals: int = 50,
) -> dict:
    """Write a pyemu ``ParameterEnsemble`` CSV for ``da_parameter_ensemble``.

    Either ``prior_ensemble`` (a mapping of parameter name → list of
    realisations) or ``prior_std`` (draw ``num_reals`` realisations around each
    adjustable parameter's ``parval1`` with that standard deviation — in log10
    space for ``partrans='log'`` parameters) may be given, not both. Parameters
    not named in ``prior_ensemble`` are filled with their control-file value,
    matching the ensemble it would draw internally from the bounds.

    The draw is done here rather than with ``ParameterEnsemble.from_gaussian_draw``
    because pyemu 1.4.0's ``Cov`` lowercases parameter names, which collides with
    the uppercase state-parameter names this control file can carry.
    """
    ws = resolve_workspace(model)
    par_names = [str(n) for n in pst.parameter_data.index]
    _validate_da_prior_spec(par_names, prior_ensemble, prior_std, num_reals)
    by_lower = {n.lower(): n for n in par_names}

    if prior_ensemble is not None:
        series: dict[str, list[float]] = {}
        for raw, vals in prior_ensemble.items():
            series[by_lower[str(raw).lower()]] = [float(v) for v in vals]
        n_reals = len(next(iter(series.values())))
        df = pd.DataFrame(index=range(n_reals))
        for name in par_names:
            if name in series:
                df[name] = series[name]
            else:
                df[name] = float(pst.parameter_data.loc[name, "parval1"])
    else:
        assert prior_std is not None  # validated by _validate_da_prior_spec
        n_reals = int(num_reals)
        rng = np.random.default_rng()
        std = float(prior_std)
        df = pd.DataFrame(index=range(n_reals))
        for name in par_names:
            row = pst.parameter_data.loc[name]
            base = float(row["parval1"])
            transform = str(row["partrans"]).lower()
            if transform in ("fixed", "tied"):
                df[name] = base
            elif transform == "log":
                df[name] = 10.0 ** (np.log10(base) + rng.normal(0.0, std, n_reals))
            else:
                df[name] = base + rng.normal(0.0, std, n_reals)

    # PEST/PEST++ names are lowercased, so emit lowercase columns to line up with
    # the control file once it is read back.
    df.columns = [str(c).lower() for c in df.columns]
    pe = pyemu.ParameterEnsemble(pst, df, istransformed=False)
    out_path = ws / f"{model}_da_prior.csv"
    pe.to_csv(str(out_path))
    return {"file": str(out_path), "num_reals": int(pe.shape[0])}


def _impl_setup_da_control(
    model: str,
    parameterisation: dict,
    cycles: list[int],
    obs_cycles: dict,
    obs_weights: dict | None = None,
    par_cycles: dict | None = None,
    num_reals: int = 50,
    noptmax: int = 1,
    use_simulated_states: bool = True,
    da_options: dict | None = None,
    prior_ensemble: dict | None = None,
    prior_std: float | None = None,
) -> dict:
    """Build a DA-ready PEST++ **version 2** control file (7f-DA).

    Reuses the ``setup_calibration`` NPF-``k`` external-array rewire/template
    machinery, additionally parametrises the IC ``strt`` array as the DA
    *state* (one state parameter per registered observation site, sharing the
    observation name so ``da_use_simulated_states`` can carry each cycle's
    simulated heads into the next cycle), and writes the cycle tables and
    ``da_*`` options ``pestpp-da`` v5.2.16 accepts.

    ``cycles`` are DA cycle indices; ``obs_cycles`` maps each registered site
    name to ``{cycle: observed value}``. Sequential DA runs one MODFLOW 6
    stress period / one time step per cycle, so ``NPER=1``/``NSTP=1`` is
    required (the canonical MF6-OBS-CSV instruction file reads the first data
    row, which is the end-of-cycle value). ``par_cycles`` optionally supplies
    per-cycle values for fixed forcing parameters (a ``perlen`` entry templates
    the TDIS stress-period length); ``da_options`` are extra ``da_*`` keywords.
    ``prior_ensemble`` / ``prior_std`` optionally write a pyemu parameter
    ensemble CSV and point ``da_parameter_ensemble`` at it; when neither is
    given, pestpp-da draws the prior internally from the parameter bounds.
    """
    ws = resolve_workspace(model)

    # -- validate inputs ---------------------------------------------------
    if not cycles:
        raise ValueError("cycles must name at least one DA cycle index.")
    cycles = [int(c) for c in cycles]
    if len(set(cycles)) != len(cycles):
        raise ValueError(f"cycles must be unique, got {cycles}.")

    if not use_simulated_states:
        raise ValueError(
            "use_simulated_states=False is not supported: pestpp-da v5.2.16 "
            "requires final-to-initial state linkages that setup_da_control "
            "does not emit, so the resulting PST is rejected at run time. "
            "Only use_simulated_states=True is supported."
        )

    gwf = get_gwf(model)
    sim = gwf.simulation
    tdis = sim.get_package("tdis")
    if tdis is None:
        raise ValueError(
            "set_simulation must be called before setup_da_control so the "
            "stress-period discretisation is known."
        )
    nper = int(np.asarray(tdis.nper.array).item())
    perioddata = np.asarray(tdis.perioddata.array)
    nstp = (
        perioddata["nstp"].astype(int)
        if perioddata.dtype.names
        else perioddata.reshape(-1, 3)[:, 1].astype(int)
    )
    if nper != 1 or nstp.size != 1 or int(nstp[0]) != 1:
        raise ValueError(
            "Sequential PEST++-DA needs one MODFLOW 6 stress period with one "
            f"time step per cycle (NPER=1, NSTP=1); this model has NPER={nper}, "
            f"NSTP={nstp.tolist()}. Call set_simulation(model, 1, "
            "[period_length], [1], ...)."
        )

    obs_meta = read_meta(model).get("observations")
    if not obs_meta or not obs_meta.get("sites"):
        raise ValueError(
            "setup_da_control requires observation targets registered via "
            "import_obs_from_csv. No 'observations' entry found in "
            ".gwmcp_meta.json for this model."
        )
    site_entries = list(obs_meta["sites"])
    site_names = [str(entry["site"]) for entry in site_entries]
    if len(set(site_names)) != len(site_names):
        raise ValueError("Registered observation site names are not unique.")

    raw_obs_cycles = obs_cycles
    obs_cycles = {}
    for k, vals in (raw_obs_cycles or {}).items():
        if not isinstance(vals, dict):
            raise ValueError(
                f"obs_cycles['{k}'] must map a cycle index to an observed value."
            )
        obs_cycles[str(k)] = {
            int(c): float(v) for c, v in vals.items() if v is not None
        }
    missing = [s for s in site_names if s not in obs_cycles]
    extra = [s for s in obs_cycles if s not in site_names]
    if missing:
        raise ValueError(
            f"obs_cycles is missing registered site(s) {missing}; every "
            "registered site needs a per-cycle observed-value mapping."
        )
    if extra:
        raise ValueError(
            f"obs_cycles names site(s) {extra} that are not registered "
            f"observations ({site_names})."
        )
    cycle_set = set(cycles)
    for site in site_names:
        bad = [c for c in obs_cycles[site] if int(c) not in cycle_set]
        if bad:
            raise ValueError(
                f"obs_cycles['{site}'] refers to cycle(s) {bad} not in cycles {cycles}."
            )

    # -- validate everything that needs no model write ---------------------
    # Grid support, state-cell mapping and the forcing/name checks all run
    # before ``_restore_or_snapshot_k_base`` and the K/IC rewires, so a rejected
    # setup leaves NPF ``k`` and IC ``strt`` untouched (the 6d run log's
    # secondary finding: a failed DISU setup left uniform K=1).
    norm = _normalise_parameterisation(model, parameterisation)

    name_by_flat: dict[int, str] = {}
    for entry, site in zip(site_entries, site_names):
        idx = _da_cell_flat_index(model, entry["cellid"])
        if idx in name_by_flat:
            raise ValueError(
                f"Observation sites {name_by_flat[idx]!r} and {site!r} map to the "
                "same cell; DA state parameters must be one per cell."
            )
        name_by_flat[idx] = site

    k_param_names = [p["name"] for p in norm["parameters"]]
    raw_par_cycles = par_cycles
    par_cycles = {}
    for k, vals in (raw_par_cycles or {}).items():
        if not isinstance(vals, dict):
            raise ValueError(
                f"par_cycles['{k}'] must map a cycle index to a fixed value."
            )
        par_cycles[str(k)] = {
            int(c): float(v) for c, v in vals.items() if v is not None
        }
    collisions = [n for n in par_cycles if n in k_param_names]
    if collisions:
        raise ValueError(
            f"par_cycles key(s) {collisions} collide with adjustable parameter "
            "name(s); a parameter cannot be both calibrated and driven by the "
            "parameter cycle table, which would override the calibrated value "
            "every cycle. Rename the forcing parameter or remove it from the "
            "parameterisation."
        )
    forcing_names = [n for n in par_cycles if n not in k_param_names]
    if len(forcing_names) > 1:
        raise ValueError(
            "A single-time-step DA model has one per-cycle forcing slot "
            "(the TDIS stress-period length); supply at most one "
            f"par_cycles parameter outside the K parameterisation, got "
            f"{forcing_names}."
        )
    par_names = list(k_param_names) + list(site_names) + list(forcing_names)
    if len(set(par_names)) != len(par_names):
        raise ValueError(
            "DA parameter names collide (K parameter names, observation/state "
            "names and forcing names must be distinct): "
            f"{sorted({n for n in par_names if par_names.count(n) > 1})}."
        )

    # Observation weights must name registered sites; validated here (not at the
    # assembly below) so a bad weight is rejected before any model write.
    weights = {str(k): float(v) for k, v in (obs_weights or {}).items()}
    unknown_w = [k for k in weights if k not in site_names]
    if unknown_w:
        raise ValueError(
            f"obs_weights names unknown observation(s) {unknown_w}; registered "
            f"sites are {site_names}."
        )

    # The prior-ensemble spec (da_parameter_ensemble) is likewise pure: reject a
    # bad/conflicting prior before the K/IC rewire.
    _validate_da_prior_spec(par_names, prior_ensemble, prior_std, num_reals)

    # -- parameters: K rewire + template (reuses the setup_calibration path) --
    _restore_or_snapshot_k_base(model)
    ext_file = _impl_rewire_npf_k_external(model)["external_file"]
    k_tpl = _impl_generate_tpl(model, parameterisation, target_file=ext_file)
    k_tpl_path = Path(k_tpl["tpl_path"])
    k_target = Path(k_tpl["target"])
    k_initial = {p["name"]: p["initial"] for p in norm["parameters"]}
    _tpl_substitute(k_tpl_path, k_target, k_initial)

    # -- IC state parameterisation ----------------------------------------
    ic_info = _impl_rewire_ic_strt_external(model)
    ic_base = ic_info["array"]
    ic_target = Path(ws / ic_info["external_file"])
    ic_tpl = _impl_generate_ic_tpl(model, name_by_flat, ic_base, ic_info["external_file"])
    ic_tpl_path = Path(ic_tpl["tpl_path"])
    ic_initial = {
        name: float(np.asarray(ic_base).reshape(-1)[idx])
        for idx, name in name_by_flat.items()
    }
    _tpl_substitute(ic_tpl_path, ic_target, ic_initial)

    # -- OBS instruction file (first data row = end-of-cycle value) --------
    output_csv = str(obs_meta["output_csv"])
    ins_path = ws / f"{output_csv}.ins"
    _impl_generate_ins_from_obs_csv(
        str(ws / output_csv), ins_path=str(ins_path), obs_names=site_names
    )

    # -- optional per-cycle fixed forcing parameters -----------------------
    tdis_tpl = None
    if forcing_names:
        tdis_tpl = _impl_generate_tdis_tpl(model, forcing_names[0])
        perlen = par_cycles[forcing_names[0]]
        initial = next(
            (float(perlen[c]) for c in cycles if c in perlen and perlen[c] is not None),
            1.0,
        )
        _tpl_substitute(
            Path(tdis_tpl["tpl_path"]), Path(tdis_tpl["target"]), {forcing_names[0]: initial}
        )

    # -- assemble the version-2 control file ------------------------------
    pst = pyemu.pst_utils.generic_pst(par_names, site_names)

    for p in norm["parameters"]:
        name = p["name"]
        pst.parameter_data.loc[name, "parval1"] = float(p["initial"])
        pst.parameter_data.loc[name, "parlbnd"] = float(p["lower_bound"])
        pst.parameter_data.loc[name, "parubnd"] = float(p["upper_bound"])
        pst.parameter_data.loc[name, "partrans"] = str(p["partrans"])
        pst.parameter_data.loc[name, "pargp"] = "k"
    for name in site_names:
        pst.parameter_data.loc[name, "parval1"] = float(ic_initial[name])
        pst.parameter_data.loc[name, "parlbnd"] = float(ic_initial[name]) - 1.0e6
        pst.parameter_data.loc[name, "parubnd"] = float(ic_initial[name]) + 1.0e6
        pst.parameter_data.loc[name, "partrans"] = "none"
        pst.parameter_data.loc[name, "pargp"] = "head_state"
    for name in forcing_names:
        first = par_cycles[name]
        pst.parameter_data.loc[name, "parval1"] = next(
            (float(first[c]) for c in cycles if c in first and first[c] is not None),
            1.0,
        )
        pst.parameter_data.loc[name, "parlbnd"] = 1.0e-8
        pst.parameter_data.loc[name, "parubnd"] = 1.0e6
        pst.parameter_data.loc[name, "partrans"] = "fixed"
        pst.parameter_data.loc[name, "pargp"] = "forcing"
    pst.parameter_data["cycle"] = -1

    # Observation values come from the cycle table; weights must be non-zero in
    # obs_data.csv (da_weight_cycle_table is ignored by pestpp-da v5.2.16).
    pst.observation_data["obsval"] = 0.0
    pst.observation_data["weight"] = [weights.get(n, 1.0) for n in site_names]
    pst.observation_data["obgnme"] = str(obs_meta.get("type", "HEAD")).lower()
    pst.observation_data["cycle"] = -1
    pst.observation_data["state_par_link"] = ""

    # Model IO sections carry the DA cycle column (all-cycle = -1).
    in_files = [
        [k_tpl_path.name, k_target.name, -1],
        [ic_tpl_path.name, ic_target.name, -1],
    ]
    if tdis_tpl is not None:
        in_files.append([Path(tdis_tpl["tpl_path"]).name, Path(tdis_tpl["target"]).name, -1])
    pst.model_input_data = pd.DataFrame(
        in_files, columns=["pest_file", "model_file", "cycle"]
    )
    pst.model_input_data.index = [row[0] for row in in_files]
    pst.model_output_data = pd.DataFrame(
        [[ins_path.name, output_csv, -1]], columns=["pest_file", "model_file", "cycle"]
    )
    pst.model_output_data.index = [ins_path.name]

    # Forward command: the MF6 binary (or a space-free Python wrapper).
    wrapper = None
    if _needs_forward_wrapper(model):
        wrapper = _generate_forward_wrapper(model)
        pst.model_command = list(wrapper["model_command"])
    else:
        try:
            pst.model_command = [_find_mf6_binary()]
        except RuntimeError:
            pass  # keep pyemu's default; only needed for an actual run

    obs_tbl = ws / f"{model}_da_obs_cycle_tbl.csv"
    par_tbl = ws / f"{model}_da_par_cycle_tbl.csv"
    _write_cycle_table(obs_tbl, site_names, cycles, obs_cycles)
    _write_cycle_table(par_tbl, list(par_cycles.keys()), cycles, par_cycles)

    # Optional weight cycle table. pestpp-da v5.2.16 accepts but ignores it, so
    # the authoritative weights are the non-zero values in obs_data.csv above;
    # it is emitted only when the caller supplies obs_weights, for other builds.
    weight_tbl = None
    if obs_weights:
        weight_tbl = ws / f"{model}_da_weight_cycle_tbl.csv"
        _write_cycle_table(
            weight_tbl,
            site_names,
            cycles,
            {n: {c: weights.get(n, 1.0) for c in cycles} for n in site_names},
        )

    # Optional prior parameter ensemble: rows = realisations, columns =
    # parameters, read by pestpp-da via da_parameter_ensemble. Its row count is
    # the ensemble size, so it also sets da_num_reals.
    prior_tbl = None
    if prior_ensemble is not None or prior_std is not None:
        prior_tbl = _impl_write_da_prior_ensemble(
            model,
            pst,
            prior_ensemble=prior_ensemble,
            prior_std=prior_std,
            num_reals=num_reals,
        )
        num_reals = prior_tbl["num_reals"]

    pst.pestpp_options["da_num_reals"] = int(num_reals)
    pst.pestpp_options["da_observation_cycle_table"] = obs_tbl.name
    pst.pestpp_options["da_parameter_cycle_table"] = par_tbl.name
    if weight_tbl is not None:
        pst.pestpp_options["da_weight_cycle_table"] = weight_tbl.name
    if prior_tbl is not None:
        pst.pestpp_options["da_parameter_ensemble"] = Path(prior_tbl["file"]).name
    pst.pestpp_options["da_use_simulated_states"] = bool(use_simulated_states)
    for key, value in (da_options or {}).items():
        pst.pestpp_options[key] = value
    pst.control_data.noptmax = int(noptmax)

    pst.rectify_pgroups()
    pst.parameter_groups["derinclb"] = 0.01

    pst_path = ws / f"{model}.pst"
    pst.write(str(pst_path), version=2)

    cycle_tables = {"obs": str(obs_tbl), "parameter": str(par_tbl)}
    if weight_tbl is not None:
        cycle_tables["weight"] = str(weight_tbl)

    result: dict = {
        "model": model,
        "pst_file": str(pst_path),
        "template_file": str(k_tpl_path),
        "target_file": str(k_target),
        "ic_template_file": str(ic_tpl_path),
        "ic_target_file": str(ic_target),
        "cycle_tables": cycle_tables,
        "n_observations": len(site_names),
        "n_adjustable_parameters": len(norm["parameters"]),
        "n_state_parameters": len(site_names),
        "n_cycles": len(cycles),
        "model_command": list(pst.model_command),
        "next_steps": (
            "Run the assimilation with run_pestpp_da(model, pst_file), then "
            "summarise_da."
        ),
    }
    if wrapper is not None:
        result["forward_wrapper"] = wrapper["wrapper_path"]
    if prior_tbl is not None:
        result["prior_ensemble_file"] = prior_tbl["file"]
    return result


# ---------------------------------------------------------------------------
# PEST++ tool implementations
# ---------------------------------------------------------------------------


def _impl_setup_pest_control(
    model: str,
    obs_data: dict,
    par_data: dict,
    template_files: list[str],
    instruction_files: list[str],
    pestpp_options: dict | None = None,
    obs_source: str = "explicit",
    _suppress_command_warning: bool = False,
) -> dict:
    """Build and write a PEST++ control file (.pst) for the model.

    Parameters
    ----------
    model:
        Registered model name.
    obs_data:
        Mapping of observation name → attributes dict.  Recognised keys:
        ``obsval`` (or ``value``), ``weight``, ``obgnme``.
        Observation names MUST match the tokens in the instruction file(s);
        a name that cannot be aligned is a hard error (no silent drop).
    par_data:
        Mapping of parameter name → attributes dict.  Recognised keys:
        ``parval1`` (or ``initial_value``), ``parlbnd`` (or ``lower_bound``),
        ``parubnd`` (or ``upper_bound``), ``pargp``, ``partrans``.
        Parameter names MUST match the tokens in the template file(s).
    template_files:
        Paths to PEST++ template files (.tpl).  Each must already exist and
        start with a ``ptf``/``jtf`` header.  The corresponding model input
        file is derived by stripping the .tpl suffix (e.g. ``params.tpl`` →
        ``params``).  **The derived name must exactly match the file the model
        actually reads** — e.g. an NPF ``OPEN/CLOSE hk.dat`` needs a template
        named ``hk.dat.tpl`` so the parameterised K array is written to
        ``hk.dat``.  If the model input file has a different name, pass it
        explicitly via ``pestpp_options["input_files"]`` (list parallel to
        ``template_files``).
    instruction_files:
        Paths to PEST++ instruction files (.ins).  Each must already exist.
        The corresponding model output file is derived by stripping the .ins
        suffix (e.g. ``heads.ins`` → ``heads``).  If the model output file
        has a different name, pass it via ``pestpp_options["output_files"]``
        (list parallel to ``instruction_files``).

        Instruction files may use classic PEST tokens (``!name!``) or pyemu's
        pif/jif format.  When using pif, the header must be ``pif @`` (or
        ``jif @``) and each line follows pyemu's fixed-width reader syntax,
        e.g. ``l1 !dum! !o0001!`` (skip the first token, read ``o0001``).
        The ``[l1]…@o0001@`` PEST style is NOT accepted by pyemu's pif
        parser — use ``l1 !dum! !o0001!`` instead.
    obs_source:
        ``"explicit"`` (default) requires ``obs_data`` + ``instruction_files``
        to be supplied.  ``"model"`` builds both from the observation targets
        registered by ``import_obs_from_csv`` (7f-F1.5): an instruction file
        is generated that reads the model's obs CSV (first output row), and
        each site's observed value is the mean of its registered records.
    pestpp_options:
        Optional PEST++ options written to the ++options section.  Special
        keys handled here (not written to ++options):

        - ``"model_command_line"`` (str) or ``"model_command"`` (str|list):
          the forward-model run command.  pyemu 1.4.0 stores this as a list
          on ``pst.model_command``; the default is ``model.bat``.
        - ``"output_files"`` (list): explicit model output file names,
          parallel to ``instruction_files`` (for when the output file is not
          the instruction file with ``.ins`` stripped).
        - ``"input_files"`` (list): explicit model input file names, parallel
          to ``template_files`` (for when the template's target differs from
          the ``.tpl``-stripped name — e.g. ``hk.dat.tpl`` → ``hk.dat``).
        - ``"noptmax"``: native PEST control data (not a pestpp '++' arg).

        On Windows, the default model command resolves the MF6 binary
        directly (``<mf6-exe>``) instead of a ``cmd /c model.bat`` wrapper,
        which fails under ``NoDefaultCurrentDirectoryInExePath=1``.
    """
    ws = resolve_workspace(model)
    pestpp_options = dict(pestpp_options or {})

    # Flush staged model changes: pestpp invokes the forward model (MF6) which
    # reads the on-disk input set (7f-E1.2).
    flush_model(model)

    if obs_source == "model":
        instruction_files, obs_data, output_files = _build_model_obs_interface(model, ws)
        if output_files:
            pestpp_options["output_files"] = output_files
    elif obs_source != "explicit":
        raise ValueError(f"obs_source must be 'explicit' or 'model', got '{obs_source}'.")

    # Resolve template/instruction paths relative to the workspace
    def _resolve(p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else ws / p

    tpl_paths = [_resolve(t) for t in template_files]
    ins_paths = [_resolve(i) for i in instruction_files]

    # Validate template files exist and start with ptf/jtf
    for tpl in tpl_paths:
        if not tpl.exists():
            raise FileNotFoundError(f"Template file not found: {tpl}")
        first = tpl.read_text().splitlines()[0].strip()
        if not first.lower().startswith(("ptf", "jtf")):
            raise ValueError(f"Template file must start with [ptf,jtf], not: {first!r}")
    for ins in ins_paths:
        if not ins.exists():
            raise FileNotFoundError(f"Instruction file not found: {ins}")

    # Extract parameter names from template files
    par_names: list[str] = []
    for tpl in tpl_paths:
        par_names.extend(pyemu.pst_utils.parse_tpl_file(str(tpl)))

    # Extract observation names from instruction files
    obs_names: list[str] = []
    for ins in ins_paths:
        obs_names.extend(_parse_ins_obs_names(ins))
    if not obs_names:
        raise ValueError(
            "No observation names found in the instruction file(s). "
            "Instruction files must use classic PEST tokens (!name!) or "
            "pyemu pif/jif (usecol) format."
        )

    # Build the Pst from the parsed names (not from_io_files — that cannot
    # parse classic PEST instruction files in pyemu 1.4.0)
    pst = pyemu.pst_utils.generic_pst(par_names, obs_names)

    # Derive paired in/out file names from tpl/ins paths (relative, so the
    # PST contains no absolute paths — pestpp-glm rejects absolute paths
    # with spaces as "wrong number of tokens").
    in_files = [p.name[:-4] if p.suffix.lower() == ".tpl" else p.name + ".in" for p in tpl_paths]
    out_files = [p.name[:-4] if p.suffix.lower() == ".ins" else p.name + ".out" for p in ins_paths]
    output_files = pestpp_options.pop("output_files", None)
    if output_files is not None:
        if len(output_files) != len(ins_paths):
            raise ValueError("len(output_files) must equal len(instruction_files)")
        out_files = [Path(o).name for o in output_files]
    input_files = pestpp_options.pop("input_files", None)
    if input_files is not None:
        if len(input_files) != len(tpl_paths):
            raise ValueError("len(input_files) must equal len(template_files)")
        in_files = [Path(f).name for f in input_files]

    pst.model_input_data = pd.DataFrame(
        {"pest_file": [p.name for p in tpl_paths], "model_file": in_files},
        index=[p.name for p in tpl_paths],
    )
    pst.model_output_data = pd.DataFrame(
        {"pest_file": [p.name for p in ins_paths], "model_file": out_files},
        index=[p.name for p in ins_paths],
    )

    # Apply model command line.  pyemu 1.4.0 stores it as a list on
    # pst.model_command (NOT model_command_line).
    cmd_line = pestpp_options.pop("model_command_line", None)
    if cmd_line is None:
        cmd_line = pestpp_options.pop("model_command", None)
    if cmd_line is not None:
        if isinstance(cmd_line, str):
            pst.model_command = [cmd_line]
        else:
            pst.model_command = list(cmd_line)
    elif platform.system() == "Windows":
        # Default forward command: run MF6 directly.  A bare `model.bat`
        # fails under NoDefaultCurrentDirectoryInExePath=1, and `cmd /c`
        # is path-normalised by pestpp into `cmd \c` (invalid).
        try:
            mf6_exe = _find_mf6_binary()
            pst.model_command = [f'"{mf6_exe}"']
        except RuntimeError:
            pass  # keep pyemu's default model.bat

    # Populate observation values and weights — validate alignment with the
    # instruction-file tokens; raise instead of silently dropping.
    obs_df = pst.observation_data
    obs_index = {str(n).lower(): n for n in obs_df.index}
    unmatched: list[str] = []
    for obs_name, attrs in obs_data.items():
        key = str(obs_name).lower()
        if key not in obs_index:
            unmatched.append(obs_name)
            continue
        canonical = obs_index[key]
        obs_df.loc[canonical, "obsval"] = float(attrs.get("obsval", attrs.get("value", 0.0)))
        obs_df.loc[canonical, "weight"] = float(attrs.get("weight", 1.0))
        if "obgnme" in attrs:
            obs_df.loc[canonical, "obgnme"] = str(attrs["obgnme"])
    if unmatched:
        available = sorted({str(n) for n in obs_df.index})
        raise ValueError(
            "Observation name(s) in obs_data not found in the instruction "
            f"file(s): {unmatched}. Available observation names from the "
            f"instruction file(s): {available}. obs_data keys must match the "
            "tokens in the instruction file(s)."
        )

    # Populate parameter bounds and initial values — validate alignment.
    par_df = pst.parameter_data
    par_index = {str(n).lower(): n for n in par_df.index}
    unmatched_par: list[str] = []
    for par_name, attrs in par_data.items():
        key = str(par_name).lower()
        if key not in par_index:
            unmatched_par.append(par_name)
            continue
        canonical = par_index[key]
        parval1 = float(attrs.get("parval1", attrs.get("initial_value", 1.0)))
        # Safe numeric defaults (7e-A2.5): base/10–base×10 rather than the
        # old blanket 0.01–100, which stressed the Newton solve on real models
        # (zenodo run 1) when the base was far from 1.
        parlbnd = float(attrs.get("parlbnd", attrs.get("lower_bound", parval1 / 10.0)))
        parubnd = float(attrs.get("parubnd", attrs.get("upper_bound", parval1 * 10.0)))
        par_df.loc[canonical, "parval1"] = parval1
        par_df.loc[canonical, "parlbnd"] = parlbnd
        par_df.loc[canonical, "parubnd"] = parubnd
        if "pargp" in attrs:
            par_df.loc[canonical, "pargp"] = str(attrs["pargp"])
        if "partrans" in attrs:
            par_df.loc[canonical, "partrans"] = str(attrs["partrans"])
    if unmatched_par:
        available = sorted({str(n) for n in par_df.index})
        raise ValueError(
            "Parameter name(s) in par_data not found in the template "
            f"file(s): {unmatched_par}. Available parameter names from the "
            f"template file(s): {available}. par_data keys must match the "
            "tokens in the template file(s)."
        )

    # Apply remaining PEST++ options. noptmax is native PEST control data,
    # not a pestpp '++' argument (pestpp rejects unknown ++ args and exits
    # before producing output).
    for key, val in pestpp_options.items():
        if key == "noptmax":
            pst.control_data.noptmax = int(val)
        else:
            pst.pestpp_options[key] = val

    # Safe numeric defaults (7e-A2.5): derinclb defaults to 0.0 in pyemu's
    # generic_pst, which makes pestpp compute a zero relative derivative
    # increment (zero Jacobian) — the Mode B rerun-4 "calibration doesn't
    # work" bug. rectify_pgroups first so newly-added groups (e.g. a custom
    # pargp in par_data) exist, then set a nonzero increment on every group.
    pst.rectify_pgroups()
    pst.parameter_groups["derinclb"] = 0.01

    pst_path = ws / f"{model}.pst"
    pst.write(str(pst_path))

    n_adjustable = int((par_df["partrans"] != "fixed").sum())

    result: dict = {
        "model": model,
        "pst_file": str(pst_path),
        "n_observations": len(obs_df),
        "n_observations_matched": len(obs_df) - len(unmatched),
        "n_adjustable_parameters": n_adjustable,
        "n_total_parameters": len(par_df),
        "model_command": list(pst.model_command),
    }

    # Warn on insensitive parameters when a sensitivity screen has run (7f-H3.2).
    sens_meta = read_meta(model).get("sensitivity")
    if sens_meta:
        insensitive = set(sens_meta.get("insensitive", []))
        matching = insensitive & set(par_df.index)
        if matching:
            result["warning"] = (
                "Parameter(s) flagged insensitive by check_parameter_sensitivity "
                f"(relative head change < {_SENSITIVITY_TOLERANCE}): "
                f"{sorted(matching)}. Calibration may not constrain them."
            )

    # Windows forward-command guidance: pestpp cannot execute .bat/.cmd
    # wrappers (it normalises /c → \\c and the process hangs) and cannot
    # launch executables whose path contains spaces (GetExitCodeProcess
    # failure). Surface a warning so the agent fixes the command before a
    # confusing runtime failure. setup_calibration generates a known-good
    # command itself, so it suppresses this advisory.
    if platform.system() == "Windows" and not _suppress_command_warning:
        for tok in pst.model_command or []:
            lower = tok.lower()
            if lower.endswith((".bat", ".cmd")):
                result["warning"] = (
                    "model_command points at a .bat/.cmd wrapper, which pestpp "
                    "cannot execute on Windows (it hangs normalising 'cmd /c'). "
                    "Use a direct executable or a space-free Python wrapper "
                    "script, e.g. a copy of the wrapper at a path without spaces."
                )
                break
            first = lower.split()[0].strip('"')
            if " " in first:
                result["warning"] = (
                    "model_command contains a space in the executable path, "
                    "which pestpp on Windows cannot launch (GetExitCodeProcess "
                    "fails on quoted space paths). Copy the wrapper/executable "
                    "to a space-free path and reference that."
                )
                break

    return result


def _impl_run_pestpp_glm(
    model: str,
    pst_file: str,
    num_workers: int = 1,
) -> dict:
    """Run PESTPP-GLM (gradient-based parameter estimation).

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the PST control file (absolute or relative to workspace).
    num_workers:
        Number of parallel workers.  Values > 1 are noted in the return dict;
        parallel execution (PANTHER) is not managed automatically.
    """
    exe = _find_pestpp_binary("pestpp-glm")
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)

    # Flush staged model changes so the forward model reads the current input
    # set (7f-E1.2).
    flush_model(model)

    result = subprocess.run(
        [exe, pst_path.name],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )

    base_name = pst_path.stem
    # GLM writes its iteration history to <case>.iobj, not .phi.actual.csv
    # (7e-B1.1); reading the wrong file silently empties phi_progress.
    phi_progress, final_phi = _read_glm_phi(ws, base_name)
    iterations = len(phi_progress)

    converged = result.returncode == 0

    return {
        "model": model,
        "pst_file": str(pst_path),
        "converged": converged,
        "final_phi": final_phi,
        "iterations": iterations,
        "stdout": result.stdout[-3000:] if result.stdout else "",
        "stderr": result.stderr[-1000:] if result.stderr else "",
    }


def _impl_run_pestpp_da(
    model: str,
    pst_file: str,
    num_reals: int | None = None,
    num_workers: int = 1,
    da_options: dict | None = None,
    noptmax: int | None = None,
) -> dict:
    """Run PESTPP-DA (generalized sequential/batch data assimilation).

    The caller supplies a DA-ready PST. The ensemble size is the
    ``da_num_reals`` ``++`` option; when ``num_reals`` is given it is written
    to that option, and when it is omitted the PST's existing ``da_num_reals``
    is preserved (mirroring the ``noptmax`` handling) so a
    ``setup_da_control(num_reals=N)`` PST is not silently resized. The PEST
    control ``noptmax`` is the number of update *iterations per assimilation
    cycle*, not the ensemble size — ``0`` performs no update (base values only);
    use ``>=1`` for one ensemble-Kalman update per cycle. When ``noptmax`` is
    omitted the PST's own value is preserved. (PEST++ manual §12;
    ``pestpp/pestpp-da_benchmarks`` reference PST.)

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the PST control file.
    num_reals:
        Ensemble size, written to ``da_num_reals``. ``None`` leaves the PST's
        existing ``da_num_reals`` unchanged.
    num_workers:
        Number of parallel workers (see run_pestpp_glm note on parallelism).
    da_options:
        Extra ``++`` options written into the PST. PEST++-DA recognises the
        cycle options ``da_observation_cycle_table``,
        ``da_parameter_cycle_table``, ``da_weight_cycle_table``,
        ``da_parameter_ensemble``, ``da_hotstart_cycle``, ``da_stop_cycle``,
        ``da_use_simulated_states`` and ``da_noptmax_schedule``. There is no
        ``da_cycle`` / ``da_obs_cycle_table`` / ``da_ensemble`` — an
        unrecognised ``++`` arg is a fatal control-file parse error.
    noptmax:
        Update iterations per assimilation cycle. ``None`` leaves the PST's
        existing ``noptmax`` unchanged.
    """
    exe = _find_pestpp_binary("pestpp-da")
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)
    if not pst_path.exists():
        raise FileNotFoundError(f"PST control file not found: {pst_path}")

    # Flush staged model changes so the forward model reads the current input
    # set (7f-E1.2).
    flush_model(model)

    pst = pyemu.Pst(str(pst_path))
    if noptmax is not None:
        pst.control_data.noptmax = int(noptmax)
    if num_reals is not None:
        pst.pestpp_options["da_num_reals"] = int(num_reals)
    for key, value in (da_options or {}).items():
        pst.pestpp_options[key] = value
    pst.write(str(pst_path))

    # Report the ensemble size the run will actually use: the value just set, or
    # the PST's own preserved da_num_reals.
    effective_reals = pst.pestpp_options.get("da_num_reals")
    effective_reals = int(effective_reals) if effective_reals is not None else None

    result = subprocess.run(
        [exe, pst_path.name],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )

    base_name = pst_path.stem
    phi_csv = ws / f"{base_name}.phi.actual.csv"

    final_phi_mean: float | None = None
    final_phi_std: float | None = None
    cycles = 0

    if phi_csv.exists():
        phi_progress, _ = _read_phi_csv(phi_csv)
        cycles = len(phi_progress)
        if phi_progress:
            phi_vals = [row["phi"] for row in phi_progress]
            final_phi_mean = float(np.mean(phi_vals))
            final_phi_std = float(np.std(phi_vals))

    converged = result.returncode == 0

    return {
        "model": model,
        "pst_file": str(pst_path),
        "converged": converged,
        "final_phi_mean": final_phi_mean,
        "final_phi_std": final_phi_std,
        "cycles": cycles,
        "num_reals": effective_reals,
        "noptmax": int(pst.control_data.noptmax),
        "stdout": result.stdout[-3000:] if result.stdout else "",
        "stderr": result.stderr[-1000:] if result.stderr else "",
    }


def _impl_run_pestpp_ies(
    model: str,
    pst_file: str,
    num_reals: int = 50,
    num_workers: int = 1,
) -> dict:
    """Run PESTPP-IES (iterative ensemble smoother).

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the PST control file.
    num_reals:
        Number of realisations in the ensemble.
    num_workers:
        Number of parallel workers (see run_pestpp_glm note on parallelism).
    """
    exe = _find_pestpp_binary("pestpp-ies")
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)

    # Flush staged model changes so the forward model reads the current input
    # set (7f-E1.2).
    flush_model(model)

    # Inject num_reals into the PST before running
    pst = pyemu.Pst(str(pst_path))
    pst.pestpp_options["ies_num_reals"] = num_reals
    pst.write(str(pst_path))

    result = subprocess.run(
        [exe, pst_path.name],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )

    base_name = pst_path.stem
    phi_csv = ws / f"{base_name}.phi.actual.csv"

    final_phi_mean: float | None = None
    final_phi_std: float | None = None
    iterations = 0

    if phi_csv.exists():
        phi_progress, _ = _read_phi_csv(phi_csv)
        iterations = len(phi_progress)
        if phi_progress:
            phi_vals = [row["phi"] for row in phi_progress]
            final_phi_mean = float(np.mean(phi_vals))
            final_phi_std = float(np.std(phi_vals))

    converged = result.returncode == 0

    return {
        "model": model,
        "pst_file": str(pst_path),
        "converged": converged,
        "final_phi_mean": final_phi_mean,
        "final_phi_std": final_phi_std,
        "iterations": iterations,
        "num_reals": num_reals,
        "stdout": result.stdout[-3000:] if result.stdout else "",
        "stderr": result.stderr[-1000:] if result.stderr else "",
    }


def _impl_summarise_calibration(
    model: str,
    pst_file: str,
    measurement_error: float | None = None,
    max_residuals: int = 500,
) -> dict:
    """Summarise PEST++ calibration results.

    Auto-detects the engine from the run artifacts (GLM ``<case>.par``/``.iobj``
    vs IES ``<case>.*.par.csv``/``.obs.csv``) and reads the matching outputs:
    phi progress, parameter estimates (GLM: the optimal ``.par``; IES: the
    final ensemble ``.par.csv`` mean + spread), and residuals (from the ``.rei``
    or, for IES without one, the final observation ensemble).  Computes RMSE,
    bias, and R², plus a calibration verdict (7f-H4.2): whether phi improved
    versus the previous run, which parameters sit at their bounds, which
    parameters are identifiable (from check_parameter_sensitivity), and whether
    the fit is within a supplied measurement_error.

    ``residuals`` is capped at ``max_residuals`` (default 500, 7e-A1.6); the
    full residual table is always written to ``<model>_residuals.csv`` and
    ``residual_statistics`` is computed over ALL observations.

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the PST control file used for the calibration run.
    measurement_error:
        Optional observation uncertainty (same units as heads); the verdict's
        ``fit_within_measurement_error`` is ``rmse <= measurement_error``.
    max_residuals:
        Cap on the ``residuals`` list returned in the response.
    """
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)

    pst = pyemu.Pst(str(pst_path))
    par_df = pst.parameter_data
    base_name = pst_path.stem
    engine = _detect_pestpp_engine(ws, base_name)

    # --- Phi progress ---
    # GLM writes <case>.iobj, IES writes <case>.phi.actual.csv. The IES file is
    # read with the ensemble-mean reader (its iteration row has mean/std/min/max
    # plus per-realisation columns — summing them is not a phi value).
    if engine == "ies":
        phi_progress, _ = _read_ies_phi(ws, base_name)
    else:
        phi_progress, _ = _read_glm_phi(ws, base_name)

    # --- Residuals ---
    # A missing residual source means the PEST++ run died before writing
    # residuals — the old behaviour silently reported
    # `rmse: None, n_observations: 0` as a *success*, which an agent reads as
    # "ran, zero observations" rather than "died before residuals". Fail loudly
    # instead (7e-B2). pestpp-ies writes no .rei when the run is stopped early
    # but does write a final observation ensemble, so the IES path falls back
    # to that ({case}.{N}.obs.csv vs the PST measured values) before failing.
    residual_stats: dict = {
        "rmse": None,
        "bias": None,
        "r_squared": None,
        "n_observations": 0,
    }
    residuals: list[dict] = []

    rei_candidates = [
        ws / f"{base_name}.res",
        ws / f"{base_name}.rei",
        ws / f"{base_name}.base.rei",
    ]
    res_df = None
    if any(p.exists() for p in rei_candidates):
        res_df = pst.res  # reads {base}.res/.rei automatically
    elif engine == "ies":
        res_df = _read_ies_obs_ensemble(ws, base_name, pst)
    if res_df is not None:
        residual_stats = _compute_residual_stats(res_df)
        residuals = (
            res_df[["name", "measured", "modelled", "residual", "weight"]]
            .rename(columns={"name": "obs_name"})
            .astype({"measured": float, "modelled": float, "residual": float, "weight": float})
            .to_dict("records")
        )
    elif engine == "ies":
        raise FileNotFoundError(
            f"No residual file ({base_name}.res / .rei / .base.rei) and no "
            f"ensemble observation file ({base_name}.*.obs.csv) found in {ws}. "
            "The PEST++ run died before writing residuals — check the run log "
            "(the .pst stdout/stderr) for convergence or parameter-bound issues, "
            "then re-run the calibration."
        )
    else:
        raise FileNotFoundError(
            f"No residual file ({base_name}.res / .rei / .base.rei) found in "
            f"{ws}. The PEST++ run died before writing residuals — check the "
            "run log (the .pst stdout/stderr) for convergence or parameter-"
            "bound issues, then re-run the calibration."
        )

    # --- Parameter estimates ---
    # GLM: {base}.par (single best-fit point). IES: the final parameter
    # ensemble {base}.{N}.par.csv — the reported estimate is the ensemble mean,
    # with the ensemble spread alongside.
    if engine == "ies":
        ensemble = _read_ies_parameter_ensemble(ws, base_name)
    else:
        ensemble = {}
    par_file = ws / f"{base_name}.par"
    par_values = _parse_par_file(par_file) if engine == "glm" else {}

    par_estimates = []
    for par_name in par_df.index:
        row = par_df.loc[par_name]
        info = ensemble.get(par_name.lower())
        est: dict = {
            "name": par_name,
            "initial_value": float(row["parval1"]),
            "estimated_value": info["mean"] if info else par_values.get(par_name.lower()),
            "lower_bound": float(row["parlbnd"]),
            "upper_bound": float(row["parubnd"]),
            "group": str(row["pargp"]),
            "transform": str(row["partrans"]),
        }
        if info:
            est["ensemble_mean"] = info["mean"]
            est["ensemble_std"] = info["std"]
            est["ensemble_min"] = info["min"]
            est["ensemble_max"] = info["max"]
            est["n_realizations"] = info["n"]
        par_estimates.append(est)

    # --- Verdict, not just numbers (7f-H4.2) ---
    final_phi = phi_progress[-1]["phi"] if phi_progress else None
    meta = read_meta(model)
    prior_phi = (meta.get("calibration") or {}).get("last_phi")
    improved = None
    if final_phi is not None:
        improved = prior_phi is None or final_phi < prior_phi

    parameters_at_bounds: list[str] = []
    for est in par_estimates:
        est_val = est["estimated_value"]
        if est_val is None:
            continue
        rng = est["upper_bound"] - est["lower_bound"]
        if rng <= 0:
            continue
        tol = 0.01 * rng
        if abs(est_val - est["lower_bound"]) <= tol or abs(est_val - est["upper_bound"]) <= tol:
            parameters_at_bounds.append(est["name"])

    sensitivity = meta.get("sensitivity")
    if sensitivity:
        identifiable = [p for p in par_df.index if p not in set(sensitivity.get("insensitive", []))]
    else:
        identifiable = None

    fit_within_measurement_error = None
    if measurement_error is not None and residual_stats.get("rmse") is not None:
        fit_within_measurement_error = residual_stats["rmse"] <= measurement_error

    verdict = {
        "improved": improved,
        "final_phi": final_phi,
        "prior_phi": prior_phi,
        "parameters_at_bounds": parameters_at_bounds,
        "identifiable": identifiable,
        "fit_within_measurement_error": fit_within_measurement_error,
    }

    # Record phi so the next run can report whether it improved.
    if final_phi is not None:
        meta.setdefault("calibration", {})["last_phi"] = final_phi
        write_meta(model, meta)

    # Residuals are capped in the response; the full table goes to a CSV and
    # residual_statistics is always computed over all observations (7e-A1.6).
    residuals_csv = ws / f"{model}_residuals.csv"
    if residuals:
        pd.DataFrame(residuals).to_csv(residuals_csv, index=False)
    capped_residuals = residuals[:max_residuals]

    return {
        "model": model,
        "pst_file": str(pst_path),
        "engine": engine,
        "phi_progress": phi_progress,
        "parameter_estimates": par_estimates,
        "residual_statistics": residual_stats,
        "residuals": capped_residuals,
        "residuals_csv": str(residuals_csv),
        "n_residuals_total": len(residuals),
        "verdict": verdict,
    }


def _impl_summarise_da(
    model: str,
    pst_file: str,
    max_residuals: int = 500,
) -> dict:
    """Summarise a pestpp-da sequential assimilation run.

    Reads the artifacts pestpp-da v5.2.16 leaves behind: the per-cycle phi file
    ``<case>.global.phi.actual.csv`` (post-update ensemble-mean phi per cycle),
    the final-cycle parameter ensemble ``<case>.global.<cycle>.pe.csv``
    (posterior ``mean``/``std``/``min``/``max`` per parameter, excluding the
    ``base`` row), and the latest base residual file
    ``<case>.<cycle>.<iter>.base.rei`` (per-cycle residuals — the observed
    values are the cycle-table values for that cycle).

    ``residuals`` is capped at ``max_residuals``; the full table is written to
    ``<model>_da_residuals.csv`` and ``residual_statistics`` is computed over
    all observations.

    Raises ``FileNotFoundError`` when no DA run outputs exist at all (no
    per-cycle phi file and no per-cycle parameter ensemble) — a missing run
    must fail loudly rather than return an empty success envelope.

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the DA-ready PST control file used for the run.
    max_residuals:
        Cap on the ``residuals`` list returned in the response.
    """
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)
    if not pst_path.exists():
        raise FileNotFoundError(f"PST control file not found: {pst_path}")
    base_name = pst_path.stem

    # No run outputs at all means pestpp-da was never run (or died before
    # writing its cycle artifacts). Fail loudly (7e-B2) rather than returning a
    # success envelope with empty cycles/residuals that an agent can misread as
    # "ran with zero observations". A legitimate noptmax=0 no-update run still
    # writes the per-cycle phi and ensemble files, so it is not caught here.
    has_cycle_phi = (ws / f"{base_name}.global.phi.actual.csv").exists()
    has_parameter_ensemble = any(ws.glob(f"{base_name}.global.*.pe.csv"))
    if not has_cycle_phi and not has_parameter_ensemble:
        raise FileNotFoundError(
            f"No pestpp-da run outputs found in {ws}: neither "
            f"{base_name}.global.phi.actual.csv nor a per-cycle parameter "
            f"ensemble ({base_name}.global.<cycle>.pe.csv) exists. The "
            "assimilation has not run (or died before writing its outputs) — "
            "check the run log (the .pst stdout/stderr), then run it with "
            "run_pestpp_da."
        )

    cycles = _read_da_cycle_phi(ws, base_name)
    final = cycles[-1] if cycles else None
    parameter_ensemble = _read_da_parameter_ensemble(ws, base_name)

    residual_stats: dict = {
        "rmse": None,
        "bias": None,
        "r_squared": None,
        "n_observations": 0,
    }
    residuals: list[dict] = []
    rei_path = _latest_da_residual_file(ws, base_name)
    if rei_path is not None:
        res_df = pyemu.pst.pst_utils.read_resfile(str(rei_path))
        residual_stats = _compute_residual_stats(res_df)
        residuals = (
            res_df[["name", "measured", "modelled", "residual", "weight"]]
            .rename(columns={"name": "obs_name"})
            .astype({"measured": float, "modelled": float, "residual": float, "weight": float})
            .to_dict("records")
        )

    residuals_csv = ws / f"{model}_da_residuals.csv"
    if residuals:
        pd.DataFrame(residuals).to_csv(residuals_csv, index=False)

    return {
        "model": model,
        "pst_file": str(pst_path),
        "engine": "da",
        "cycles": [{"cycle": c["cycle"], "phi": c["phi"]} for c in cycles],
        "final_phi_mean": final["phi"] if final else None,
        "final_phi_std": final["phi_std"] if final else None,
        "parameter_ensemble": parameter_ensemble,
        "residual_statistics": residual_stats,
        "residuals": residuals[:max_residuals],
        "residuals_csv": str(residuals_csv),
        "n_residuals_total": len(residuals),
    }


def _impl_run_ies_uncertainty(
    model: str,
    pst_file: str,
    forecast_names: list[str],
) -> dict:
    """Compute predictive uncertainty from the PESTPP-IES posterior ensemble.

    Reads the latest observation ensemble CSV produced by pestpp-ies, extracts
    the columns listed in ``forecast_names``, and returns percentile statistics.

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the PST control file used for the IES run.
    forecast_names:
        Names of observations that were tracked as forecasts (weight=0 during
        calibration but listed in the PST observation data).
    """
    import pandas as pd

    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)
    base_name = pst_path.stem

    # Find the latest iteration observation ensemble: {base}.{N}.obs.csv
    obs_csvs = sorted(ws.glob(f"{base_name}.*.obs.csv"))
    if not obs_csvs:
        raise FileNotFoundError(
            f"No ensemble observation files ({base_name}.*.obs.csv) found in {ws}. "
            "Run pestpp-ies first with forecast observations defined in the PST."
        )

    latest_obs = pd.read_csv(obs_csvs[-1], index_col=0)

    missing = [f for f in forecast_names if f not in latest_obs.columns]
    if missing:
        available = list(latest_obs.columns[:20])
        raise ValueError(
            f"Forecast names not found in ensemble output: {missing}. "
            f"Available columns (first 20): {available}"
        )

    forecasts: dict[str, dict] = {}
    for fc_name in forecast_names:
        col = latest_obs[fc_name].dropna().astype(float)
        p5, p95 = np.percentile(col, [5, 95])
        forecasts[fc_name] = {
            "mean": float(col.mean()),
            "std": float(col.std()),
            "p5": float(p5),
            "p95": float(p95),
            "n_realizations": int(len(col)),
        }

    return {
        "model": model,
        "pst_file": str(pst_path),
        "ensemble_file": str(obs_csvs[-1]),
        "forecasts": forecasts,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register calibration tools (PEST++) with the MCP server."""

    # --- PEST++ tools ---

    @mcp.tool()
    def setup_calibration(
        model: str,
        parameterisation: dict,
        obs_source: str = "model",
        noptmax: int = 10,
    ) -> dict:
        """Automated calibration setup (7e-A2): generate the whole PEST interface
        with zero hand-written files.

        parameterisation maps a parameter name to a spec dict:

          {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}

        scope is "all" (whole array), "layer" (with "layer": N), or "cells"
        (with "cells": [[layer,row,col], ...] — DIS — or [[layer,node], ...]
        — DISV). Optional keys: lower_factor/upper_factor (default 0.1/10.0)
        set the bounds from initial; partrans defaults to "log". Parameter
        names are capped at 12 characters (PEST).

        scope may also be "zones" (with "layer": N): zones are derived from
        equal positive K values in that layer and each zone becomes a
        dimensionless multiplier parameter (initial default 1.0, bounds
        0.1-10). A generated forward wrapper applies k = base_k × multiplier
        before each run, preserving the base K pattern. One zones spec per
        layer; zones specs cannot be mixed with all/layer/cells.

        This call: (1) rewires NPF k to an external OPEN/CLOSE array,
        (2) generates a wide-token template (>= 15 chars) over the
        parameterised cells, (3) generates the instruction file from the
        model's OBS CSV header, (4) writes a Python forward wrapper at a
        space-free path when the default MF6 command would be unsafe on
        Windows, and (5) assembles the .pst with safe numeric defaults
        (derinclb > 0, bounds base/10–base×10).

        obs_source must be "model": observation targets registered via
        import_obs_from_csv provide the observed values and the instruction
        file reads the model's obs CSV. Run the calibration afterwards with
        run_pestpp_glm / run_pestpp_ies (or calibrate), then
        summarise_calibration."""
        try:
            return _impl_setup_calibration(model, parameterisation, obs_source, noptmax)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except RuntimeError as exc:
            msg = str(exc)
            if "MODFLOW 6" in msg or "binary" in msg.lower():
                return _err("BINARY_NOT_FOUND", msg, "Install MODFLOW 6 with: get-modflow :")
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def setup_da_control(
        model: str,
        parameterisation: dict,
        cycles: list[int],
        obs_cycles: dict,
        obs_weights: dict | None = None,
        par_cycles: dict | None = None,
        num_reals: int = 50,
        noptmax: int = 1,
        use_simulated_states: bool = True,
        da_options: dict | None = None,
        prior_ensemble: dict | None = None,
        prior_std: float | None = None,
    ) -> dict:
        """Build a DA-ready PEST++ v2 control file (cycle tables + da_* options).

        For sequential ensemble data assimilation with pestpp-da. ``cycles`` are
        DA cycle indices, e.g. [0, 1, 2]. ``obs_cycles`` maps each registered
        observation site name to a per-cycle observed value, e.g.
        {"S1": {0: 30.0, 1: 29.0}}. ``obs_weights`` optionally sets a non-zero
        weight per site (da_weight_cycle_table is ignored by pestpp-da v5.2.16,
        so weights live in obs_data.csv). ``par_cycles`` optionally supplies
        per-cycle values for fixed forcing parameters — a ``perlen`` entry
        templates the TDIS stress-period length and drives it from the
        parameter cycle table. A ``par_cycles`` key that names an adjustable
        parameter is rejected with INVALID_INPUT (the cycle table would override
        the calibrated value every cycle). ``use_simulated_states=False`` is
        rejected with INVALID_INPUT — pestpp-da v5.2.16 requires final-to-initial
        state linkages this tool does not emit, so only ``True`` is supported.

        ``prior_ensemble`` (mapping of parameter name to a list of realisations)
        or ``prior_std`` (draw ``num_reals`` realisations around each adjustable
        parameter's value with that standard deviation) optionally writes
        ``<model>_da_prior.csv`` and points the ``da_parameter_ensemble`` option
        at it; supply at most one. When neither is given, pestpp-da draws the
        prior internally from the parameter bounds. The written ensemble's row
        count becomes the DA ensemble size (``da_num_reals``).

        The tool rewires NPF k and the IC strt array to external OPEN/CLOSE
        files, generates the K template plus a state-augmented IC template (one
        state parameter per observed cell, sharing the observation name so
        da_use_simulated_states can carry each cycle's simulated heads into the
        next cycle), writes the observation instruction file, and assembles a
        version-2 .pst carrying a `cycle` column and the da_* options. The model
        must run one stress period with one time step per cycle (NPER=1,
        NSTP=1) — otherwise the OBS-CSV instruction file would not read the
        end-of-cycle value; a clear error is returned otherwise.

        Run the assimilation afterwards with run_pestpp_da, then
        summarise_da."""
        try:
            return _impl_setup_da_control(
                model,
                parameterisation,
                cycles,
                obs_cycles,
                obs_weights,
                par_cycles,
                num_reals,
                noptmax,
                use_simulated_states,
                da_options,
                prior_ensemble,
                prior_std,
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except RuntimeError as exc:
            msg = str(exc)
            if "MODFLOW 6" in msg or "binary" in msg.lower():
                return _err("BINARY_NOT_FOUND", msg, "Install MODFLOW 6 with: get-modflow :")
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def setup_pest_control(
        model: str,
        obs_data: dict,
        par_data: dict,
        template_files: list[str],
        instruction_files: list[str],
        pestpp_options: dict | None = None,
        obs_source: str = "explicit",
    ) -> dict:
        """Generate a PEST++ control file (.pst) for the model.

        obs_data maps observation names to dicts with keys: obsval (or value),
        weight, obgnme.  par_data maps parameter names to dicts with keys:
        parval1 (or initial_value), parlbnd (or lower_bound), parubnd (or
        upper_bound), pargp, partrans.

        The instruction file(s) must already exist and define the observation
        tokens (classic PEST `!name!` or pyemu pif/jif).  obs_data keys MUST
        match those tokens exactly (case-insensitive); a mismatch raises an
        error instead of silently dropping observations.

        obs_source: "explicit" (default) requires obs_data + instruction_files.
        "model" builds both from the observation targets registered by
        import_obs_from_csv (7f-F1.5): an instruction file is generated that
        reads the model's obs CSV (first output row — the single row for the
        steady-state models this targets) and each site's observed value is
        the mean of its registered records. With obs_source="model" you still
        supply par_data and template_files but may omit instruction_files and
        obs_data.

        Template files must start with a `ptf`/`jtf` header.  The model input
        file a template writes is the .tpl filename with the suffix stripped
        (e.g. `hk.dat.tpl` → `hk.dat`) — name templates so the derived target
        matches the file the model actually reads, or override it with
        `pestpp_options["input_files"]`.  Parameter tokens must be wide
        fixed-width (e.g. `@          k          @`); narrow tokens truncate
        substituted values and zero out the Jacobian.

        pestpp_options special keys: "model_command_line" (str) or
        "model_command" (str|list) sets the forward-model run command
        (default on Windows: the located MF6 binary); "output_files" (list,
        parallel to instruction_files) sets explicit model output filenames;
        "input_files" (list, parallel to template_files) sets explicit model
        input filenames; "noptmax" is native PEST control data.  On Windows,
        the model command must be a direct executable or a space-free Python
        wrapper — pestpp cannot run .bat/.cmd wrappers or space-containing
        paths.
        """
        try:
            return _impl_setup_pest_control(
                model,
                obs_data,
                par_data,
                template_files,
                instruction_files,
                pestpp_options,
                obs_source,
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "PEST_ERROR",
                str(exc),
                "Ensure template and instruction files exist in the workspace.",
            )
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def start_calibration(
        model: str,
        pst_file: str,
        method: str = "glm",
        num_reals: int = 50,
    ) -> dict:
        """Start PEST++ calibration (GLM or IES) in the background and return
        a job id immediately (7e-A3).

        method is "glm" (pestpp-glm, default) or "ies" (pestpp-ies); for IES,
        num_reals sets the ensemble size. The calibration runs in a worker
        thread instead of blocking until the client timeout. Poll progress and
        the final result with get_job_status(job_id) — while running it
        reports live iteration + phi parsed from <case>.iobj (GLM) or
        <case>.phi.actual.csv (IES) — and stop it with cancel_job(job_id).
        The finished job's result matches run_pestpp_glm / run_pestpp_ies."""
        try:
            return _impl_start_calibration(model, pst_file, method, num_reals)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except FileNotFoundError as exc:
            return _err(
                "PEST_ERROR",
                str(exc),
                "Ensure the PST control file exists in the workspace.",
            )
        except RuntimeError as exc:
            msg = str(exc)
            if "not found" in msg.lower() or "binary" in msg.lower():
                return _err("BINARY_NOT_FOUND", msg, "Install PEST++ with: get-pestpp :")
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def run_pestpp_glm(
        model: str,
        pst_file: str,
        num_workers: int = 1,
    ) -> dict:
        """Run PESTPP-GLM (gradient-based parameter estimation) and return convergence results."""
        try:
            return _impl_run_pestpp_glm(model, pst_file, num_workers)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except RuntimeError as exc:
            msg = str(exc)
            if "not found" in msg.lower() or "binary" in msg.lower():
                return _err("BINARY_NOT_FOUND", msg, "Install PEST++ with: get-pestpp :")
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def run_pestpp_ies(
        model: str,
        pst_file: str,
        num_reals: int = 50,
        num_workers: int = 1,
    ) -> dict:
        """Run PESTPP-IES (iterative ensemble smoother) and return ensemble phi statistics."""
        try:
            return _impl_run_pestpp_ies(model, pst_file, num_reals, num_workers)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except RuntimeError as exc:
            msg = str(exc)
            if "not found" in msg.lower() or "binary" in msg.lower():
                return _err("BINARY_NOT_FOUND", msg, "Install PEST++ with: get-pestpp :")
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def run_pestpp_da(
        model: str,
        pst_file: str,
        num_reals: int | None = None,
        num_workers: int = 1,
        da_options: dict | None = None,
        noptmax: int | None = None,
    ) -> dict:
        """Run PESTPP-DA (ensemble data assimilation) and return phi statistics.

        Requires a DA-ready PST: pass cycle options (e.g.
        ``{"da_observation_cycle_table": "obs_cycle_tbl.csv",
        "da_parameter_cycle_table": "par_cycle_tbl.csv",
        "da_weight_cycle_table": "weight_cycle_tbl.csv"}``) or a PST already
        carrying ``da_*`` options. ``num_reals`` is the ensemble size (written
        to ``da_num_reals``); when omitted the PST's own ``da_num_reals`` is
        preserved (so a ``setup_da_control(num_reals=N)`` PST keeps N). The
        optional ``noptmax`` sets the number of update iterations per
        assimilation cycle (0 performs no update — base values only; use >=1
        for one ensemble-Kalman update per cycle) and preserves the PST's own
        value when omitted."""
        try:
            return _impl_run_pestpp_da(
                model, pst_file, num_reals, num_workers, da_options, noptmax
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "PEST_ERROR",
                str(exc),
                "Ensure the PST control file exists in the workspace.",
            )
        except RuntimeError as exc:
            msg = str(exc)
            if "not found" in msg.lower() or "binary" in msg.lower():
                return _err("BINARY_NOT_FOUND", msg, "Install PEST++ with: get-pestpp :")
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def summarise_calibration(
        model: str,
        pst_file: str,
        measurement_error: float | None = None,
        max_residuals: int = 500,
    ) -> dict:
        """Summarise PEST++ calibration results: phi progress, parameter
        estimates, residuals (capped at max_residuals; full table to CSV),
        and a verdict (7f-H4.2) — whether phi improved
        versus the previous run, parameters at their bounds, identifiability,
        and fit within a supplied measurement_error."""
        try:
            return _impl_summarise_calibration(model, pst_file, measurement_error, max_residuals)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "OUTPUT_FILE_MISSING",
                str(exc),
                "Run pestpp-glm or pestpp-ies first.",
            )
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def summarise_da(
        model: str,
        pst_file: str,
        max_residuals: int = 500,
    ) -> dict:
        """Summarise a pestpp-da sequential assimilation run.

        Reports per-cycle phi (the post-update ensemble mean from
        ``<case>.global.phi.actual.csv``), the final-cycle phi mean/std, the
        posterior parameter statistics (``mean``/``std``/``min``/``max`` from
        the final ``<case>.global.<cycle>.pe.csv``, excluding the ``base``
        row), and residuals from the latest per-cycle base ``.rei`` (capped at
        ``max_residuals``; the full table is written to CSV)."""
        try:
            return _impl_summarise_da(model, pst_file, max_residuals)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "OUTPUT_FILE_MISSING",
                str(exc),
                "Run pestpp-da (run_pestpp_da) first.",
            )
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def check_parameter_sensitivity(
        model: str,
        parameters: dict[str, float],
        template_files: list[str],
        delta: float = 0.1,
    ) -> dict:
        """Run a cheap n+1 forward-run sensitivity screen (7f-H3.1).

        parameters maps parameter name → base value, one per template file.
        Each template's target file must be one the model actually reads (e.g.
        an NPF ``k`` array via OPEN/CLOSE with template ``hk.dat.tpl``).
        Returns per-parameter sensitivity (mean relative change of the
        simulated observations) and records it so setup_pest_control warns on
        insensitive parameters. Run this before committing to calibration."""
        try:
            return _impl_check_parameter_sensitivity(model, parameters, template_files, delta)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("PEST_ERROR", str(exc), "Ensure template files exist in the workspace.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("SENSITIVITY_FAILED", str(exc))

    @mcp.tool()
    def calibrate(
        model: str,
        par_data: dict,
        template_files: list[str],
        time_budget_minutes: float = 30.0,
        noptmax: int = 10,
        num_reals: int = 50,
    ) -> dict:
        """Choose and run the calibration method (7f-H4.1).

        Builds the PEST interface from the registered observation targets
        (obs_source="model"), chooses GLM vs IES from the adjustable-parameter
        count, observation count and time_budget_minutes, and runs the chosen
        engine. The method and its rationale appear in the result."""
        try:
            return _impl_calibrate(
                model, par_data, template_files, time_budget_minutes, noptmax, num_reals
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err("PEST_ERROR", str(exc), "Ensure template files exist in the workspace.")
        except RuntimeError as exc:
            return _err(
                "BINARY_NOT_FOUND",
                str(exc),
                "Install PEST++ with: get-pestpp :",
            )
        except Exception as exc:
            return _err("CALIBRATE_FAILED", str(exc))

    @mcp.tool()
    def run_ies_uncertainty(
        model: str,
        pst_file: str,
        forecast_names: list[str],
    ) -> dict:
        """Compute predictive uncertainty bounds from the PESTPP-IES posterior ensemble."""
        try:
            return _impl_run_ies_uncertainty(model, pst_file, forecast_names)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "OUTPUT_FILE_MISSING",
                str(exc),
                "Run pestpp-ies first with forecast observations defined.",
            )
        except ValueError as exc:
            return _err(
                "PEST_ERROR",
                str(exc),
                "Check forecast_names match observation names in the PST.",
            )
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))
