# Mode B session — tutorial 05 (natural language) rerun-6

- **Date**: 2026-08-22
- **Client / model**: Agent Manager worktree session (`modeb-tutorial05-rerun6`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack
  (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PESTPP-GLM 5.2.16)
- **Working dir**: `GW-MCP-holdout/modeB/tutorial05/data` (closed-book;
  model files in `data\model`)
- **Started from the `build_model_from_data` MCP prompt?** **YES** (C6
  verification) — the dispatch opened with the rendered prompt
  (model="tut05", transient=False, has_zone_shapefile=False), then the Mode B
  task list + closed-book/MCP-only constraints.
- **Prompt used**: rendered `build_model_from_data` guide (steps 1–18, with
  the 8/10 numbering skipped) + the verbatim Mode B assignment. The agent's
  run log is at `GW-MCP-holdout/modeB/tutorial05/data/run-log.md` (folder
  reset afterwards).

## Tool-call sequence

Build/run/postprocess (MCP tools throughout; plain Python only for
reading/transforming GIS/CSV data):
1. `check_environment` — stack ready (Python 3.12.11, flopy 3.10.0, pyemu 1.4.0, mf6 + pestpp binaries).
2. `create_model(tut05, data\model)`.
3. `set_simulation(nper=1, perlen=[1], nstp=[1], ims_complexity=moderate)` — steady state.
4. `import_grid_from_shapefile(activeZone.shp, dis, 200 m, EPSG:32718)` — 17×16 = 272 cells; CRS set in-call (guide step 5 skipped as instructed).
5. `assign_top_from_raster(dem_clipped.tif, layer=0, method=mean)` — top 22.1–119.7 m.
6. `add_npf_package(icelltype=0, k=10, k33=1)` — confined, uniform K=10 (calibration target).
7. `add_ic_package(strt=50)`.
8. `add_boundary_package(CHD)` (38 cells: 18 @70 m north/NE, 20 @40 m S/W/SE) + `add_boundary_package(WEL)` (29 wells, Q) + `import_river_from_shapefile(RIV, cond_field=RIVCONDUC1, stage_raster=dem, stage_offset=1)` (29 reaches).
9. `import_obs_from_csv(wells_obs.csv)` — 29 HEAD targets.
10. `add_oc_package` — tut05.hds / tut05.cbb.
11. `check_model` — clean (0 errors/warnings).
12. `run_simulation(auto_fix=True)` — converged, normal termination (0.17 s).
13. `validate_model` — `clean: true` (no findings).
14. `compute_water_balance` / `diagnose_water_balance` — CHD 69 776 in / 69 777 out, discrepancy −0.0011 % → balanced; CHD 99.9998 % of flow.
15. `compare_to_observed` — n=29, RMSE 15.76 m, bias −13.95 m, R² −7.06.
16. `plot_heads_map` — heads_baseline.png.
17. `setup_calibration(parameterisation={k: npf:k all, initial 10}, obs_source=model, noptmax=5)` — .pst + tpl + ins + wrapper.
18. `check_parameter_sensitivity(k=10, delta=0.1)` — sensitivity **4.4×10⁻⁸** (K carries no head information).
19. `start_calibration` (background) — **unreliable on this machine**: pestpp forward chain intermittently spawned spinning `mf6.exe`; GLM stalled on its first Jacobian run across three clean-state attempts; IES with 10 reals impractically slow. `summarise_calibration` correctly reported the died-before-residuals case.
20. `run_pestpp_glm` (direct) — completed (client call timed out; process finished server-side).
21. `summarise_calibration(pst, measurement_error=2)` — phi flat 7199.69 at iterations 0–3; **K = 10.0 m/d (unchanged)**; RMSE 15.76, bias −13.95, R² −7.06; verdict: fit not within measurement error, K not identifiable.
22. `export_boundaries_to_shapefile` + `export_water_balance_csv` — deliverables; required a `set_model_crs` re-set (see findings).

## Reprompts

- **0**.

## Outcome vs criteria

- **Build: pass** — 1-layer DIS grid (~200 m, DEM top), RIV/CHD/WEL, NPF/IC/OC; guide followed with **zero ordering errors** (C6).
- **Check: pass** — `check_model` clean; `validate_model` clean.
- **Run: pass** — converged, normal termination.
- **Postprocess: pass** — water balance (balanced), head map, obs fit + residuals, shapefile/CSV exports.
- **Calibrate: partial (non-identifiable)** — full MCP chain ran; K unidentifiable (sensitivity ≈ 1e-8, flat phi). Tools surfaced it correctly; agent documented rather than worked around.

## Known-limitation notes / MCP findings

- **K non-identifiability is a data/model-configuration limit, not a tool defect (confirmed across rerun-5 and rerun-6):** steady state, confined, no recharge, negligible wells, inert river (RIVCONDUC1=0.001) → head field pinned by the 70/40 m CHD boundaries; K cancels out of the steady equation. Observed heads (30–46 m) are unreachable below the 40 m CHD. Rerun-4 found K=36.28 only by making the river a strong drain (default ~720 m²/d conductance instead of the attribute); rerun-5/6 agents honoured the attribute. The diagnostic chain (`check_parameter_sensitivity`, flat-phi GLM, `summarise_calibration` verdict) is the tools doing their job.
- **`start_calibration` background-job forward-run instability (NEW FINDING):** the pestpp forward-model chain under the worker-thread subprocess spawn intermittently started `mf6.exe` processes that spun at 100 % CPU without terminating (forward runs ~2 min vs 0.05 s standalone; GLM stalled on its first Jacobian across three clean-state attempts). Filed in tasks.md as a 7e-A3 follow-up. The direct `run_pestpp_glm` path worked (client timeout tolerated).
- **CRS lost after `setup_calibration` rewrites (NEW FINDING):** the georeferenced exporters reported the grid CRS missing after the calibration rewire (`import_grid_from_shapefile` had set it in-call); re-set with `set_model_crs`. Filed in tasks.md for verification.
- `export_heads_to_raster` rejected the grid as non-uniform (`delr=200` vs `delc=194.117`); head-map PNG used instead. Expected, not a defect.
- No GAP-capability proposals.
- Closed-book respected: no groundwater-mcp source/tests/tutorial PDFs/reference models read (per the run log).

## MCP-only violations

- **0** — plain Python limited to data inspection/transforms; all model build/run/postprocess/calibrate actions via MCP tools. The `start_calibration` instability was worked around by switching to `run_pestpp_glm` (an MCP tool), not by raw flopy/pyemu.

## Time

- ~39 minutes (13:54–14:33 local, per the run log).
