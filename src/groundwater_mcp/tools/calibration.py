"""calibration module — PEST++ parameter estimation via pyEMU.

PEST++ tools implemented in Phase 5.
UCODE tools are Phase 5b (stubs kept below).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pyemu
from mcp.server.fastmcp import FastMCP

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

        phi_progress = [
            {"iteration": i, "phi": float(v)} for i, v in enumerate(phi_totals)
        ]
        final_phi = float(phi_totals.iloc[-1]) if len(phi_totals) > 0 else None
        return phi_progress, final_phi
    except Exception:
        return [], None


def _parse_par_file(par_file: Path) -> dict[str, float]:
    """Read a PEST-format .par file and return {par_name: value}."""
    values: dict[str, float] = {}
    try:
        lines = par_file.read_text().strip().splitlines()
        # First line is the header ("single point" or similar); skip it.
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    values[parts[0].lower()] = float(parts[1])
                except ValueError:
                    pass
    except Exception:
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
    except Exception:
        return {"rmse": None, "bias": None, "r_squared": None, "n_observations": 0}


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
) -> dict:
    """Build and write a PEST++ control file (.pst) for the model.

    Parameters
    ----------
    model:
        Registered model name.
    obs_data:
        Mapping of observation name → attributes dict.  Recognised keys:
        ``obsval`` (or ``value``), ``weight``, ``obgnme``.
    par_data:
        Mapping of parameter name → attributes dict.  Recognised keys:
        ``parval1`` (or ``initial_value``), ``parlbnd`` (or ``lower_bound``),
        ``parubnd`` (or ``upper_bound``), ``pargp``, ``partrans``.
    template_files:
        Paths to PEST++ template files (.tpl).  Each must already exist.
        The corresponding model input file is derived by stripping the .tpl
        suffix (e.g. ``params.tpl`` → ``params``).
    instruction_files:
        Paths to PEST++ instruction files (.ins).  Each must already exist.
        The corresponding model output file is derived by stripping the .ins
        suffix (e.g. ``heads.ins`` → ``heads``).
    pestpp_options:
        Optional PEST++ options written to the ++options section.  The special
        key ``"model_command_line"`` is extracted and applied to the PST
        control data directly (not written to pestpp_options).
    """
    ws = resolve_workspace(model)
    pestpp_options = dict(pestpp_options or {})

    # Derive paired in/out file names from tpl/ins paths
    in_files = []
    for tpl in template_files:
        p = Path(tpl)
        in_files.append(str(p.with_suffix("")) if p.suffix == ".tpl" else str(p) + ".in")

    out_files = []
    for ins in instruction_files:
        p = Path(ins)
        out_files.append(str(p.with_suffix("")) if p.suffix == ".ins" else str(p) + ".out")

    # Build Pst from template/instruction files
    pst = pyemu.Pst.from_io_files(
        tpl_files=list(template_files),
        in_files=in_files,
        ins_files=list(instruction_files),
        out_files=out_files,
        pst_path=str(ws),
    )

    # Apply model command line (not a pestpp_option — it's control data)
    cmd_line = pestpp_options.pop("model_command_line", "")
    if cmd_line:
        pst.model_command_line = cmd_line

    # Populate observation values and weights
    obs_df = pst.observation_data
    for obs_name, attrs in obs_data.items():
        if obs_name in obs_df.index:
            obs_df.loc[obs_name, "obsval"] = float(
                attrs.get("obsval", attrs.get("value", 0.0))
            )
            obs_df.loc[obs_name, "weight"] = float(attrs.get("weight", 1.0))
            if "obgnme" in attrs:
                obs_df.loc[obs_name, "obgnme"] = str(attrs["obgnme"])

    # Populate parameter bounds and initial values
    par_df = pst.parameter_data
    for par_name, attrs in par_data.items():
        if par_name in par_df.index:
            par_df.loc[par_name, "parval1"] = float(
                attrs.get("parval1", attrs.get("initial_value", 1.0))
            )
            par_df.loc[par_name, "parlbnd"] = float(
                attrs.get("parlbnd", attrs.get("lower_bound", 0.01))
            )
            par_df.loc[par_name, "parubnd"] = float(
                attrs.get("parubnd", attrs.get("upper_bound", 100.0))
            )
            if "pargp" in attrs:
                par_df.loc[par_name, "pargp"] = str(attrs["pargp"])
            if "partrans" in attrs:
                par_df.loc[par_name, "partrans"] = str(attrs["partrans"])

    # Apply remaining PEST++ options
    for key, val in pestpp_options.items():
        pst.pestpp_options[key] = val

    pst_path = ws / f"{model}.pst"
    pst.write(str(pst_path))

    n_adjustable = int((par_df["partrans"] != "fixed").sum())

    return {
        "model": model,
        "pst_file": str(pst_path),
        "n_observations": len(obs_df),
        "n_adjustable_parameters": n_adjustable,
        "n_total_parameters": len(par_df),
    }


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

    result = subprocess.run(
        [exe, pst_path.name],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )

    base_name = pst_path.stem
    phi_csv = ws / f"{base_name}.phi.actual.csv"
    phi_progress, final_phi = _read_phi_csv(phi_csv) if phi_csv.exists() else ([], None)
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


def _impl_summarise_calibration(model: str, pst_file: str) -> dict:
    """Summarise PEST++ calibration results.

    Reads the phi progress CSV, the optimal parameter file (.par), and the
    residuals file (.rei) from the workspace.  Computes RMSE, bias, and R².

    Parameters
    ----------
    model:
        Registered model name.
    pst_file:
        Path to the PST control file used for the calibration run.
    """
    ws = resolve_workspace(model)
    pst_path = _resolve_pst_path(model, pst_file)

    pst = pyemu.Pst(str(pst_path))
    par_df = pst.parameter_data
    base_name = pst_path.stem

    # --- Phi progress ---
    phi_csv = ws / f"{base_name}.phi.actual.csv"
    phi_progress, _ = _read_phi_csv(phi_csv) if phi_csv.exists() else ([], None)

    # --- Residuals ---
    residual_stats: dict = {
        "rmse": None,
        "bias": None,
        "r_squared": None,
        "n_observations": 0,
    }
    residuals: list[dict] = []

    try:
        res_df = pst.res  # reads {base}.rei automatically
        if res_df is not None:
            residual_stats = _compute_residual_stats(res_df)
            residuals = (
                res_df[["name", "measured", "modelled", "residual", "weight"]]
                .rename(columns={"name": "obs_name"})
                .astype({"measured": float, "modelled": float, "residual": float, "weight": float})
                .to_dict("records")
            )
    except Exception:
        pass

    # --- Parameter estimates ---
    par_file = ws / f"{base_name}.par"
    par_values = _parse_par_file(par_file)

    par_estimates = []
    for par_name in par_df.index:
        row = par_df.loc[par_name]
        par_estimates.append(
            {
                "name": par_name,
                "initial_value": float(row["parval1"]),
                "estimated_value": par_values.get(par_name.lower()),
                "lower_bound": float(row["parlbnd"]),
                "upper_bound": float(row["parubnd"]),
                "group": str(row["pargp"]),
                "transform": str(row["partrans"]),
            }
        )

    return {
        "model": model,
        "pst_file": str(pst_path),
        "phi_progress": phi_progress,
        "parameter_estimates": par_estimates,
        "residual_statistics": residual_stats,
        "residuals": residuals,
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
    """Register calibration tools (PEST++ and UCODE) with the MCP server."""

    # --- PEST++ tools ---

    @mcp.tool()
    def setup_pest_control(
        model: str,
        obs_data: dict,
        par_data: dict,
        template_files: list[str],
        instruction_files: list[str],
        pestpp_options: dict | None = None,
    ) -> dict:
        """Generate a PEST++ control file (.pst) for the model.

        obs_data maps observation names to dicts with keys: obsval (or value),
        weight, obgnme.  par_data maps parameter names to dicts with keys:
        parval1 (or initial_value), parlbnd (or lower_bound), parubnd (or
        upper_bound), pargp, partrans.  Pass model_command_line inside
        pestpp_options to set the forward model run command.
        """
        try:
            return _impl_setup_pest_control(
                model, obs_data, par_data, template_files, instruction_files, pestpp_options
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
                return _err(
                    "BINARY_NOT_FOUND", msg, "Install PEST++ with: get-pestpp :"
                )
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
                return _err(
                    "BINARY_NOT_FOUND", msg, "Install PEST++ with: get-pestpp :"
                )
            return _err("PEST_ERROR", msg)
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    @mcp.tool()
    def summarise_calibration(model: str, pst_file: str) -> dict:
        """Summarise PEST++ calibration results: phi progress, parameter estimates, residuals."""
        try:
            return _impl_summarise_calibration(model, pst_file)
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
            return _err("PEST_ERROR", str(exc), "Check forecast_names match observation names in the PST.")
        except Exception as exc:
            return _err("PEST_ERROR", str(exc))

    # --- UCODE tools (Phase 5b stubs) ---

    @mcp.tool()
    def setup_ucode_control(
        model: str,
        obs_data: dict,
        par_data: dict,
        template_files: list[str],
        instruction_files: list[str],
        ucode_options: dict | None = None,
    ) -> dict:
        """Generate a UCODE_2014 main input file (.#ucode) and associated data files."""
        raise NotImplementedError(
            "setup_ucode_control is not yet implemented (Phase 5b)"
        )

    @mcp.tool()
    def run_ucode(model: str, ucode_file: str) -> dict:
        """Run UCODE_2014 parameter estimation and return SSR, convergence, and estimates."""
        raise NotImplementedError("run_ucode is not yet implemented (Phase 5b)")

    @mcp.tool()
    def summarise_ucode_calibration(model: str, ucode_file: str) -> dict:
        """Summarise UCODE calibration results: SSR progress, estimates, sensitivity, residuals."""
        raise NotImplementedError(
            "summarise_ucode_calibration is not yet implemented (Phase 5b)"
        )

    @mcp.tool()
    def run_ucode_uncertainty(
        model: str,
        ucode_file: str,
        forecast_names: list[str],
        method: str = "linear",
    ) -> dict:
        """Compute predictive uncertainty bounds using UCODE linear or MCMC analysis."""
        raise NotImplementedError(
            "run_ucode_uncertainty is not yet implemented (Phase 5b)"
        )
