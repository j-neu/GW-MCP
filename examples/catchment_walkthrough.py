"""Worked example: build, run, calibrate and re-run a catchment model.

Everything below goes through the same tool surface an MCP client (Claude,
Cursor, ...) uses, via ``mcp.call_tool``. It is a *twin experiment*: a "true"
model with K = 20 m/d produces synthetic head observations, then the model is
rebuilt with a wrong K = 5 m/d, calibrated with PEST++, and the calibrated K is
written back and re-run.

Run it from the repository root (needs the mf6 and pestpp-glm binaries; see
README "Install"):

    uv run python examples/catchment_walkthrough.py

The spatial inputs are the Tutorial 04 fixtures shipped in tests/fixtures.
"""

from __future__ import annotations

import asyncio
import csv
import json
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np

from groundwater_mcp.server import mcp

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tutorial_04"
TRUE_K = 20.0
START_K = 5.0


def call(tool: str, **args):
    """Call one MCP tool and return its decoded JSON result (raising on error)."""
    result = asyncio.run(mcp.call_tool(tool, args))
    # image-returning tools put the PNG first and the result dict last
    payload = json.loads(next(c.text for c in reversed(result) if hasattr(c, "text")))
    if isinstance(payload, dict) and payload.get("error"):
        raise SystemExit(f"{tool} failed: {payload.get('code')}: {payload.get('message')}")
    return payload


def show(title: str, **values) -> None:
    print(f"\n== {title}")
    for key, value in values.items():
        print(f"   {key}: {value}")


def build(model: str, workspace: Path, k: float, wells: list) -> dict:
    call("create_model", name=model, workspace=str(workspace), units="METERS", time_units="DAYS")
    call("set_simulation", model=model, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    grid = call(
        "import_grid_from_shapefile",
        model=model, shapefile=str(FIXTURES / "activeZone.shp"), nlay=1,
        layer_surfaces=[], method="dis", cell_size=500.0,
    )
    call(
        "assign_top_from_raster",
        model=model, raster=str(FIXTURES / "dem_clipped.tif"), method="mean",
    )
    nrow, ncol = grid["nrow"], grid["ncol"]
    chd = [[[0, r, 0], 60.0] for r in range(nrow)] + [[[0, r, ncol - 1], 40.0] for r in range(nrow)]
    call("add_boundary_package", model=model, package="CHD", stress_period_data={"0": chd})
    call("add_boundary_package", model=model, package="WEL", stress_period_data={"0": wells})
    call("add_npf_package", model=model, icelltype=0, k=k, save_flows=True)
    call("add_ic_package", model=model, strt=50.0)
    call("add_oc_package", model=model)
    return grid


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="gwmcp_example_"))
    print(f"workspace root: {root}")

    # ---- 1. the "true" model, used only to make observations ---------------
    wells = [[[0, 3, 3], -3000.0]]
    grid = build("truth", root / "truth", TRUE_K, wells)
    show("grid from shapefile", type=grid["grid_type"], nrow=grid["nrow"], ncol=grid["ncol"],
         crs=grid["crs"])
    check = call("check_model", model="truth")
    show("check_model", passed=check.get("check_passed", check.get("success")))
    run = call("run_simulation", model="truth", silent=True)
    show("true model run", success=run["success"], convergence=run["convergence"])

    obs_cells = [(2, 2), (3, 2), (3, 4), (4, 3), (4, 4), (2, 4)]
    heads = np.load(call("read_heads", model="truth", layer=0)["output_file"])
    obs_csv = root / "observations.csv"
    # The grid is the catchment's bounding box cut into nrow x ncol cells, so
    # cell centres follow from the shapefile bounds (grid CRS = shapefile CRS).
    xmin, ymin, xmax, ymax = gpd.read_file(FIXTURES / "activeZone.shp").total_bounds
    delr, delc = (xmax - xmin) / grid["ncol"], (ymax - ymin) / grid["nrow"]
    with open(obs_csv, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["site", "date", "value", "x", "y"])
        for i, (r, c) in enumerate(obs_cells):
            x = xmin + (c + 0.5) * delr
            y = ymax - (r + 0.5) * delc
            writer.writerow([f"H{i + 1}", "2020-01-01", float(heads[r, c]), x, y])
    show("synthetic observations", n=len(obs_cells),
         head_range=f"{heads[tuple(zip(*obs_cells))].min():.2f} .. "
                    f"{heads[tuple(zip(*obs_cells))].max():.2f} m")

    # ---- 2. the model to calibrate, started from a wrong K ------------------
    build("catchment", root / "catchment", START_K, wells)
    imported = call(
        "import_obs_from_csv", model="catchment", csv_file=str(obs_csv),
        obs_type="HEAD", site_col="site", date_col="date", value_col="value",
        x_col="x", y_col="y", layer=0,
    )
    show("observations registered", sites=imported["site_count"], mapping=imported["site_mapping"])
    call("run_simulation", model="catchment", silent=True)
    before = call("compare_to_observed", model="catchment")
    show("before calibration (K = 5 m/d)", rmse=round(before["rmse"], 4), n=before["n"])

    # ---- 3. calibrate ------------------------------------------------------
    setup = call(
        "setup_calibration", model="catchment",
        parameterisation={"k": {"target": "npf:k", "scope": "all", "initial": START_K,
                                "allow_flatten": True}},
        noptmax=8,
    )
    show("setup_calibration", parameters=setup.get("n_adjustable_parameters"),
         observations=setup.get("n_observations"))
    glm = call("run_pestpp_glm", model="catchment", pst_file=setup["pst_file"])
    show("pestpp-glm", converged=glm.get("converged"), iterations=glm.get("iterations"),
         final_phi=glm.get("final_phi"))
    summary = call("summarise_calibration", model="catchment", pst_file=setup["pst_file"])
    estimate = summary["parameter_estimates"][0]
    show("calibrated parameter", name=estimate["name"], estimate=estimate["estimated_value"],
         truth=TRUE_K, rmse=summary["residual_statistics"]["rmse"])

    # ---- 4. write the calibration back and run the calibrated model --------
    applied = call("apply_calibration_result", model="catchment", pst_file=setup["pst_file"])
    show("apply_calibration_result", engine=applied["engine"], parameters=applied["parameters"])
    call("run_simulation", model="catchment", silent=True)
    after = call("compare_to_observed", model="catchment")
    show("after calibration", rmse=round(after["rmse"], 6), n=after["n"])

    plot = call("plot_heads_map", model="catchment", layer=0,
                output_file=str(root / "calibrated_heads.png"))
    show("calibrated head map", file=plot.get("output_file", plot))
    balance = call("diagnose_water_balance", model="catchment")
    show("water balance", percent_discrepancy=round(balance["percent_discrepancy"], 6),
         balanced=balance["balanced"])


if __name__ == "__main__":
    main()
