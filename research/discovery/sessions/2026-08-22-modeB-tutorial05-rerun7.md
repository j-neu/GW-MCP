# Mode B session — tutorial 05 (natural language) rerun-7

- **Date**: 2026-08-22
- **Client / model**: Agent Manager worktree session (`modeb-tutorial05-rerun7`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack
  (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PESTPP-GLM 5.2.16) — first run on the
  **fixed tool set** (obs-name case-insensitive matching, CRS persistence,
  process-tree cancel).
- **Working dir**: `GW-MCP-holdout/modeB/tutorial05/data` (closed-book;
  model files in `data\model`, registered as `t05modeb`).
- **Prompt used**: the verbatim Mode B prompt from
  `research/discovery/playbooks/modeB-manual-layer3.md`, dispatched with the
  standard preamble (data-folder absolute path + write `run-log.md`). The
  agent's run log is at `GW-MCP-holdout/modeB/tutorial05/data/run-log.md`
  (folder reset afterwards).

## Tool-call sequence (43 calls)

1. `check_environment` — ready (mf6 + pestpp binaries).
2. bash list — staged data found.
3. `list_models` — registry check (stale earlier-rerun entries noted).
4–5. bash — shapefile/DEM/CSV attributes, CRS, bounds; well Q range; DEM stats.
6. `create_model(t05modeb, data\model)`.
7. `set_simulation(nper=1, perlen=[1], nstp=[1])` — steady state, IMS moderate.
8. `import_grid_from_shapefile(activeZone.shp, dis, 200 m, EPSG:32718)` — 17×16 = 272 cells (200 × 194.1 m, non-square).
9. `summarise_model` — grid present, 272 active cells.
10. `export_model_spec` — default top=0 / botm=−1.
11. bash — write `bottom_const.tif` (constant 0 m, DEM grid) — data-prep artefact.
12. `assign_top_from_raster(dem_clipped.tif, layer=0)` — mean 59.8 m.
13. `assign_top_from_raster(bottom_const.tif, layer=1)` — bottom 0 m.
14. `add_npf_package(icelltype=1, k=1, k33=0.1)` — unconfined.
15. `add_ic_package(strt=50)`.
16. `add_oc_package`.
17–18. bash — CHD/WEL cell assignments + stress-period JSON payloads.
19–20. `add_boundary_package(CHD, chd_high 18@70 m; chd_lower 20@40 m)`.
21. `add_boundary_package(WEL, 29)`.
22. `import_river_from_shapefile(RIV, cond_field=RIVCONDUC1, stage_raster=dem, stage_offset=1)` — 29 reaches.
23. `check_model` — PASS.
24. `run_simulation` — converged (0.14 s).
25. `compute_water_balance` — CHD 3954.08/3953.44, RIV 0.59, WEL 0.044 out; net +0.0035.
26. `plot_heads_map` — heads_map.png.
27. `diagnose_water_balance` — balanced (0.000088%), CHD-dominated (99.99%).
28. `read_heads` — min 40, max 70, mean 49.7 m.
29. `export_heads_to_raster` — FAILED: GeoTIFF needs a uniform (square-cell) grid (tool limitation; PNG used).
30. `export_water_balance_csv`.
31. `import_obs_from_csv` — FAILED: column `value` not found (CSV has `head_m`).
32. `import_obs_from_csv(value_col='head_m')` — 29 sites mapped.
33. `run_simulation` — converged; obs fit RMSE 10.64, bias −8.02, R² −2.67.
34. `compare_to_observed(output_file=*.csv)` — FAILED: output_file must be an image format.
35. `compare_to_observed(output_file=obs_fit_initial.png)` — RMSE 10.64; residual CSV; worst w5/w20 (−21.9 m).
36. `setup_calibration({k: npf:k all, initial 1})` — 1 param (log, 0.1–10), 29 obs, wrapper generated.
37. `check_parameter_sensitivity(k@1, delta=0.1)` — sensitivity 1.1×10⁻⁶.
38. `calibrate(GLM)` — converged after 3 iterations, phi flat 3282.09.
39. `summarise_calibration(measurement_error=2)` — K = 1.0 unchanged; fit NOT within measurement error; no identifiable parameters.
40–43. final `run_simulation` + `plot_heads_map` + `compute_water_balance` + `get_run_log` — all clean.

## Reprompts

- **0**.

## Outcome vs criteria

- **Build: pass** — 1-layer DIS grid (~200 m, DEM top, constant-0 bottom documented as a deviation), RIV/CHD/WEL, NPF/IC/OC.
- **Check: pass** — `check_model` clean.
- **Run: pass** — 3 runs converged, "Normal termination of simulation".
- **Postprocess: pass** — water balance (balanced, 0.000088%), head map, obs fit + residuals, water-balance CSV.
- **Calibrate: partial (non-identifiable)** — full chain (`setup_calibration` → `check_parameter_sensitivity` → `calibrate`/GLM → `summarise_calibration`) executed cleanly; K non-identifiable (sensitivity 1.1e-6, phi flat, K stuck at 1.0). Third independent confirmation that the tutorial-05 data limit the K identifiability, not the tools.

## Fix verification (this run ran on the fixed tool set)

- **CRS persistence: verified.** The georeferenced export path passed the CRS check — `export_heads_to_raster` failed only on the square-cell requirement (INVALID_INPUT), never `CRS_UNKNOWN`; no `set_model_crs` re-set was needed after `setup_calibration`.
- **Obs-name case-insensitivity: verified.** `import_obs_from_csv` + `compare_to_observed` matched the lowercase `w1..w29` sites directly — no `wells_obs_upper` re-import workaround.
- **Background-calibration path: partially exercised.** `calibrate` (auto GLM/IES chooser) ran to completion with no stall; the run did not explicitly use the `start_calibration` + `get_job_status` background path this time (the `calibrate` helper was used), so the process-tree-cancel fix remains covered by `test_cancel_terminates_process_tree` rather than this run.

## Known-limitation notes / MCP findings

- **`export_heads_to_raster` requires a uniform (square-cell) DIS grid** — hit a second time (rerun-6, rerun-7); the 200×194.1 m grid from `import_grid_from_shapefile`'s bounding-box derivation is not square. Already open in tasks.md rerun-6 backlog.
- **`compare_to_observed.output_file` accepts only image formats** — passing a `.csv` extension errors; the residual CSV is written automatically alongside. Tool-description clarity item.
- **`import_obs_from_csv` default column is `value`** — this dataset's CSV uses `head_m`, so `value_col` was required; the tool errored clearly rather than guessing.
- No GAP-capability proposals; closed-book respected (no source/tests/PDFs/reference models read, per the run log).
- Modelling decisions differed from rerun-5/6 (unconfined icelltype=1, constant-0 bottom, K init 1, `calibrate` helper) — RMSE 10.64 vs rerun-6's 15.76 — but the CHD-dominated head field still makes uniform K non-identifiable.

## MCP-only violations

- **0** — plain Python limited to data inspection/transforms (`bottom_const.tif` creation, CHD/WEL cell mapping, JSON payloads); all model build/run/postprocess/calibrate actions via MCP tools.

## Started from the build_model_from_data MCP prompt?

- **No** — verbatim playbook prompt (C6 already verified in rerun-6).

## Time

- Not recorded in the run log (dispatched 2026-08-22 ~17:15 UTC; finished by ~19:27 local).
