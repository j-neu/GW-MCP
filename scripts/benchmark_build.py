"""benchmark_build.py — measure the wall time and bytes written per builder call.

7f-E1.1 benchmark: a representative 12-call model build on a regional-scale
grid, reporting per-call wall time and the bytes written to the workspace.

The default grid (nlay x nrow x ncol) can be overridden on the command line so
the same script can calibrate E1.3's "same fixture grid" guard.

Strategy:
  --deferred  builder calls defer their writes; a single flush happens at the
              end (the post-7f-E behaviour).
  (default)   builder calls write eagerly, as they do today — the behaviour
              being measured as the baseline.

Usage:
    python scripts/benchmark_build.py [nlay nrow ncol] [--deferred]
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Isolated workspace registry so the benchmark never touches ~/.groundwater-mcp.
import groundwater_mcp.utils.workspace as _ws_module

_BENCH_ROOT = tempfile.mkdtemp(prefix="gw-mcp-bench-")
_ws_module.default_workspace_root = lambda: Path(_BENCH_ROOT)

from groundwater_mcp.tools.builder import (  # noqa: E402
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_add_sto_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.utils.model_store import flush_model  # noqa: E402


def _flush(name: str) -> None:
    """Write a dirty model to disk (the 7f-E deferred-write flush)."""
    flush_model(name)


def _workspace_bytes(ws: Path) -> int:
    return sum(p.stat().st_size for p in ws.glob("*") if p.is_file() and not p.name.startswith("."))


def build_12call(
    name: str, nlay: int, nrow: int, ncol: int, deferred: bool
) -> list[tuple[str, float, int]]:
    """Run the representative 12-call build; return [(call, seconds, bytes_written)].

    Top/botm/K are passed as raster-style arrays (the regional-model case);
    scalar values would write a few hundred bytes and not exercise the
    write-serialisation cost the benchmark exists to measure.
    """
    import numpy as np

    ws = tempfile.mkdtemp(prefix=f"gw-mcp-{name}-")
    calls: list[tuple[str, float, int]] = []
    prev_bytes = 0

    def _call(label: str, fn) -> None:
        nonlocal prev_bytes
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        cur = _workspace_bytes(Path(ws))
        calls.append((label, elapsed, cur - prev_bytes))
        prev_bytes = cur

    top = np.linspace(95.0, 100.0, nrow * ncol, dtype=float).reshape(nrow, ncol)
    botm = [top - 10.0 * (i + 1) for i in range(nlay)]
    k = np.full((nlay, nrow, ncol), 5.0)
    k33 = np.full((nlay, nrow, ncol), 0.5)

    _call("create_model", lambda: _impl_create_model(name, ws, "METERS", "DAYS"))
    _call(
        "set_simulation",
        lambda: _impl_set_simulation(name, 2, [1.0, 9.0], [1, 3], "moderate"),
    )
    _call(
        "add_dis_package",
        lambda: _impl_add_dis_package(name, nlay, nrow, ncol, 250.0, 250.0, top, botm),
    )
    _call("add_npf_package", lambda: _impl_add_npf_package(name, 1, k, k33, True))
    _call("add_ic_package", lambda: _impl_add_ic_package(name, 80.0))
    _call(
        "add_sto_package",
        lambda: _impl_add_sto_package(name, 1, 1e-5, 0.2, [0], True),
    )
    _call("add_oc_package", lambda: _impl_add_oc_package(name, None, None, None, None))
    chd = [[[lay, r, 0], 90.0] for lay in range(nlay) for r in range(nrow)]
    _call(
        "add_boundary CHD",
        lambda: _impl_add_boundary_package(name, "CHD", {"0": chd, "1": chd}, None),
    )
    wel = [[[0, nrow // 2, ncol // 2], -1000.0]]
    _call(
        "add_boundary WEL",
        lambda: _impl_add_boundary_package(name, "WEL", {"0": wel, "1": wel}, None),
    )
    riv = [[[0, nrow // 4, c], 60.0, 1e4, 50.0] for c in range(0, ncol, 10)]
    _call(
        "add_boundary RIV",
        lambda: _impl_add_boundary_package(name, "RIV", {"0": riv}, None),
    )
    drn = [[[0, 3 * nrow // 4, c], 40.0, 1e4] for c in range(0, ncol, 10)]
    _call(
        "add_boundary DRN",
        lambda: _impl_add_boundary_package(name, "DRN", {"0": drn}, None),
    )
    ghb = [[[lay, r, ncol - 1], 50.0, 1e4] for lay in range(nlay) for r in range(nrow)]
    _call(
        "add_boundary GHB",
        lambda: _impl_add_boundary_package(name, "GHB", {"0": ghb}, None),
    )

    if deferred:
        t0 = time.perf_counter()
        _flush(name)
        elapsed = time.perf_counter() - t0
        cur = _workspace_bytes(Path(ws))
        calls.append(("flush (1 write)", elapsed, cur - prev_bytes))

    return calls


def main() -> None:
    nlay, nrow, ncol = 5, 100, 120
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 3:
        nlay, nrow, ncol = int(args[0]), int(args[1]), int(args[2])
    deferred = "--deferred" in sys.argv

    label = f"{nlay} x {nrow} x {ncol} ({nlay*nrow*ncol:,} cells)"
    print(f"Build cost benchmark - grid {label}, strategy: {'deferred' if deferred else 'eager'}")
    print(f"{'call':<24}{'wall s':>10}{'bytes':>14}")
    total_s, total_bytes = 0.0, 0
    for call, elapsed, written in build_12call("bench", nlay, nrow, ncol, deferred):
        total_s += elapsed
        total_bytes += written
        print(f"{call:<24}{elapsed:>10.3f}{written:>14,}")
    print(f"{'TOTAL':<24}{total_s:>10.3f}{total_bytes:>14,}")


if __name__ == "__main__":
    main()
