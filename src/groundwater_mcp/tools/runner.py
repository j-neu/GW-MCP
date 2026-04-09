"""runner module — execute MODFLOW 6 and retrieve run results."""

from __future__ import annotations

import platform
import shutil
import sys
import time
from io import StringIO
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from groundwater_mcp.utils.model_store import get_sim, invalidate
from groundwater_mcp.utils.workspace import resolve_workspace


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _err(code: str, message: str, suggestion: str = "") -> dict:
    return {"error": True, "code": code, "message": message, "suggestion": suggestion}


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
# Tool implementations
# ---------------------------------------------------------------------------


def _impl_check_model(model: str) -> dict:
    """Run FloPy's model checker and return structured warnings and errors."""
    sim = get_sim(model)

    # Capture any stdout/stderr that FloPy's check() writes
    buf = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
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

    return {
        "model": model,
        "warnings": warnings,
        "errors": errors,
        "check_passed": len(errors) == 0,
        "raw_output": captured[:4000],
    }


def _impl_run_simulation(model: str, silent: bool = False) -> dict:
    """Run MODFLOW 6 and return convergence status and timing."""
    exe = _find_mf6_binary()

    sim = get_sim(model)
    ws = resolve_workspace(model)
    sim.set_sim_path(str(ws))
    sim.exe_name = exe

    t0 = time.monotonic()
    try:
        success, buff = sim.run_simulation(silent=silent, report=True)
    except Exception as exc:
        raise RuntimeError(f"MODFLOW 6 run failed: {exc}") from exc
    elapsed = time.monotonic() - t0

    # Evict from cache so post-processing tools reload from updated binary outputs
    invalidate(model)

    convergence = "converged" if success else "failed"
    tail = buff[-20:] if buff and len(buff) > 20 else (buff or [])
    listing_summary = "\n".join(tail)

    return {
        "model": model,
        "success": success,
        "elapsed_s": round(elapsed, 2),
        "convergence": convergence,
        "listing_summary": listing_summary,
    }


def _impl_get_run_log(model: str, tail: int = 100) -> dict:
    """Return the last N lines of the MODFLOW listing file."""
    ws = resolve_workspace(model)

    lst_files = list(ws.glob("*.lst"))
    if not lst_files:
        raise FileNotFoundError(
            f"No listing file (.lst) found in workspace {ws}. "
            "Run the simulation first with run_simulation."
        )

    # Prefer mfsim.lst (main listing file) over model-specific ones
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
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register runner tools with the MCP server."""

    @mcp.tool()
    def check_model(model: str) -> dict:
        """Run FloPy's pre-run model checker and return structured warnings and errors."""
        try:
            return _impl_check_model(model)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except Exception as exc:
            return _err("CHECK_FAILED", str(exc))

    @mcp.tool()
    def run_simulation(model: str, silent: bool = False) -> dict:
        """Run the MODFLOW 6 simulation and return convergence status and timing."""
        try:
            return _impl_run_simulation(model, silent)
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
    def get_run_log(model: str, tail: int = 100) -> dict:
        """Return the last N lines of the MODFLOW listing file (.lst)."""
        try:
            return _impl_get_run_log(model, tail)
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except FileNotFoundError as exc:
            return _err(
                "OUTPUT_FILE_MISSING", str(exc), "Run the simulation first."
            )
        except Exception as exc:
            return _err("LOG_READ_FAILED", str(exc))
