"""Worked example: the capture zone of a pumping well, checked analytically.

A pumping well sits in an aquifer with a uniform regional gradient. Particles
are released along a line upstream of the well and tracked forward with
MODPATH 7: the ones that end in the well are inside its capture zone. For
steady uniform flow the capture zone far upstream has the classic width

    W = Q / (K * b * i)

(Q pumping rate, K conductivity, b thickness, i regional gradient), so the
number of released particles that reach the well can be checked against
W / spacing.

Everything goes through the same tool surface an MCP client uses (mcp.call_tool).
Run it from the repository root (needs the mf6 and mp7 binaries):

    uv run python examples/capture_zone.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from groundwater_mcp.server import mcp

NROW = NCOL = 21
CELL = 100.0  # m
K = 10.0  # m/d
THICKNESS = 10.0  # m
H_WEST, H_EAST = 30.0, 20.0  # m, fixed heads on the west / east boundaries
Q = 200.0  # m3/d pumped
WELL = (0, NROW // 2, NCOL // 2)
RELEASE_COL = 3  # particles start on this column, upstream (west) of the well


def call(tool: str, **args):
    result = asyncio.run(mcp.call_tool(tool, args))
    payload = json.loads(next(c.text for c in reversed(result) if hasattr(c, "text")))
    if isinstance(payload, dict) and payload.get("error"):
        raise SystemExit(f"{tool} failed: {payload.get('code')}: {payload.get('message')}")
    return payload


def show(title: str, **values) -> None:
    print(f"\n== {title}")
    for key, value in values.items():
        print(f"   {key}: {value}")


def analytical_width() -> float:
    gradient = (H_WEST - H_EAST) / ((NCOL - 1) * CELL)
    return Q / (K * THICKNESS * gradient)


def main() -> dict:
    root = Path(tempfile.mkdtemp(prefix="gwmcp_capture_"))
    print(f"workspace root: {root}")
    model = "capture"

    call("create_model", name=model, workspace=str(root / model), units="METERS", time_units="DAYS")
    call("set_simulation", model=model, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    call("add_dis_package", model=model, nlay=1, nrow=NROW, ncol=NCOL, delr=CELL, delc=CELL,
         top=THICKNESS, botm=[0.0])
    call("add_npf_package", model=model, icelltype=0, k=K, save_flows=True)
    call("add_ic_package", model=model, strt=25.0)
    chd = [[[0, r, 0], H_WEST] for r in range(NROW)]
    chd += [[[0, r, NCOL - 1], H_EAST] for r in range(NROW)]
    call("add_boundary_package", model=model, package="CHD", stress_period_data={"0": chd})
    call("add_boundary_package", model=model, package="WEL",
         stress_period_data={"0": [[list(WELL), -Q]]})
    call("add_oc_package", model=model)

    run = call("run_simulation", model=model, silent=True)
    show("flow run", success=run["success"], convergence=run["convergence"])
    balance = call("diagnose_water_balance", model=model)
    show("water balance", percent_discrepancy=round(balance["percent_discrepancy"], 6),
         balanced=balance["balanced"])

    release = [[0, r, RELEASE_COL] for r in range(NROW)]
    tracks = call("run_modpath", model=model, direction="forward", release_cells=release,
                  porosity=0.3)
    captured = [
        p for p in tracks["particles"]
        if abs(p["end"]["x"] - (WELL[2] + 0.5) * CELL) < CELL and
        abs(p["end"]["y"] - (NROW - WELL[1] - 0.5) * CELL) < CELL
    ]
    width = analytical_width()
    show("capture zone", released=len(release), captured=len(captured),
         captured_width_m=len(captured) * CELL, analytical_width_m=round(width, 1))
    plot = call("plot_modpath_pathlines", model=model, output_file=str(root / "pathlines.png"))
    show("pathline plot", file=plot.get("output_file", plot))
    return {"captured": len(captured), "analytical_width": width, "spacing": CELL}


if __name__ == "__main__":
    main()
