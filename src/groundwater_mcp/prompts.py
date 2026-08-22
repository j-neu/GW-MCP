"""prompts.py — MCP prompts encoding tool-call ordering (7e-C6).

FastMCP prompts are reusable message templates a client can request by name.
These two encode the build and calibrate orderings an agent otherwise infers
from tool descriptions and trial and error — the same ordering constraints
``model_status``/``next_steps`` (7e-C8) surface at runtime as errors when
skipped.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register MCP prompts with the server."""

    @mcp.prompt()
    def build_model_from_data(
        model: str,
        has_grid_shapefile: bool = True,
        has_dem: bool = True,
        has_zone_shapefile: bool = True,
        has_boundary_data: bool = True,
        has_observations: bool = True,
        transient: bool = False,
    ) -> str:
        """Guide for building a MODFLOW 6 model from real spatial data,
        end to end, in the order groundwater-mcp actually requires."""
        steps = [
            "1. check_environment() — verify the local stack (mf6/pestpp "
            "binaries, packages, docs index) before doing anything else.",
            f'2. create_model(model="{model}", workspace=...) — registers the '
            "workspace; nothing else works until this exists.",
            "3. set_simulation(model, nper, perlen, nstp, ims_complexity) — "
            "TDIS+IMS MUST exist before the grid is built: "
            "import_grid_from_shapefile and add_sto_package both require it.",
        ]
        if has_grid_shapefile:
            steps.append(
                "4. import_grid_from_shapefile(model, shapefile, nlay, method, "
                "target_crs) — builds the grid, and sets its CRS in the same "
                "call if target_crs is passed (then skip step 5)."
            )
        else:
            steps.append(
                "4. add_dis_package(model, nlay, nrow, ncol, delr, delc, top, "
                "botm) or add_disv_package — builds the grid from explicit "
                "dimensions."
            )
        steps.append(
            "5. set_model_crs(model, crs) — every spatial tool after this "
            "point needs the grid to carry a CRS to compare coordinates "
            "against shapefile/raster data; skip only if step 4 already set "
            "target_crs."
        )
        if has_dem:
            steps.append(
                "6. assign_top_from_raster(model, raster, layer, method, "
                "fill) — samples layer elevations from a DEM; needs the "
                "grid + CRS from steps 4-5."
            )
        steps.append(
            "7. add_npf_package(model, icelltype, k, k33, k_units) — "
            "hydraulic properties. MUST exist before assign_k_from_zones, "
            "which edits this package's K array in place rather than "
            "creating it."
        )
        if has_zone_shapefile:
            steps.append(
                "8. assign_k_from_zones(model, shapefile, k_field, layer) — "
                "distributes K from geological zone polygons; requires "
                "step 7 first."
            )
        steps.append(
            "9. add_ic_package(model, strt) — starting heads, informed by "
            "the DEM (step 6) or boundary data."
        )
        if transient:
            steps.append(
                "10. add_sto_package(model, iconvert, ss, sy, steady_state) "
                "— REQUIRED for any model with more than one stress "
                "period/time step; without it a multi-step model silently "
                "runs as steady state. Needs TDIS from step 3."
            )
        if has_boundary_data:
            steps.append(
                "11. import_river_from_shapefile / add_boundary_package "
                "(CHD, WEL, RIV, DRN, RCH, GHB, ...) — boundary conditions; "
                "needs the grid + CRS."
            )
        if has_observations:
            steps.append(
                "12. import_obs_from_csv(model, csv_file, obs_type, "
                "site_col, date_col, value_col) — registers calibration "
                "targets so read_simulated_observations / "
                'compare_to_observed / setup_pest_control(obs_source="model")'
                " can use them later."
            )
        steps.append(
            "13. add_oc_package(model) — declares the head/budget output "
            "files."
        )
        steps.append(
            "14. check_model(model) — FloPy's checker plus the STO/"
            "transient trap warning; fix anything it flags before running."
        )
        steps.append(
            "15. run_simulation(model, auto_fix=True) for a short model, "
            "or start_run(model) + get_job_status(job_id) for anything "
            "that might run more than a minute or two — it never blocks "
            "the client."
        )
        steps.append(
            "16. validate_model(model) and diagnose_water_balance(model) "
            "— check physical plausibility and budget closure before "
            "trusting the results; diagnose_convergence(model) if "
            "run_simulation reported failure."
        )
        if has_observations:
            steps.append(
                "17. compare_to_observed(model) — RMSE/bias/R² against "
                "the registered observations; no calibration needed for "
                "this alone."
            )
        steps.append(
            "18. read_heads / compute_water_balance / plot_heads_map / "
            "export_heads_to_raster / export_boundaries_to_shapefile — "
            "inspect and export the finished model."
        )
        return "\n".join(steps)

    @mcp.prompt()
    def calibrate_model(model: str, use_ensemble: bool = False) -> str:
        """Guide for calibrating a model's parameters against observed
        data via PEST++, using the automated setup_calibration path."""
        steps = [
            f'1. Confirm "{model}" has run successfully (run_simulation / '
            "start_run) and has registered observation targets "
            "(import_obs_from_csv, or check summarise_model for an "
            "existing observations count) — calibration needs both.",
            "2. setup_calibration(model, parameterisation, "
            'obs_source="model", noptmax=10) — emits the whole PEST '
            "interface (external-array rewire, wide-token template, "
            "instruction file from the model's OBS CSV, Windows-safe "
            "forward wrapper, safe .pst defaults) in one call. "
            "parameterisation maps a parameter name to a spec dict, e.g. "
            '{"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}.',
            "3. check_parameter_sensitivity(model, parameters, "
            "template_files) — optional cheap n+1 screen to catch an "
            "insensitive parameter before spending a full calibration run "
            "on it.",
        ]
        if use_ensemble:
            steps.append(
                '4. start_calibration(model, pst_file, method="ies", '
                "num_reals) or run_pestpp_ies directly — iterative "
                "ensemble smoother; prefer start_calibration for anything "
                "that might exceed the client timeout, then poll "
                "get_job_status(job_id)."
            )
        else:
            steps.append(
                '4. start_calibration(model, pst_file, method="glm") or '
                "run_pestpp_glm directly — linear regression calibration; "
                "prefer start_calibration for anything that might exceed "
                "the client timeout, then poll get_job_status(job_id). "
                "calibrate(model, par_data, template_files) will choose "
                "GLM vs IES automatically if you're unsure which to use."
            )
        steps.append(
            "5. summarise_calibration(model, pst_file) — phi progress, "
            "parameter estimates vs priors, residual statistics, and a "
            "verdict (improved, parameters_at_bounds, identifiable, "
            "fit_within_measurement_error)."
        )
        if use_ensemble:
            steps.append(
                "6. run_ies_uncertainty(model, pst_file, forecast_names) "
                "— forecast ensemble percentiles from the calibrated "
                "realizations."
            )
        return "\n".join(steps)
