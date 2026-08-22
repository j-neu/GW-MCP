# Mode B session — tutorial 05 (natural language)

- **Date**: 2026-08-22
- **Client / model**: Agent Manager worktree session (`modeb-tutorial05-rerun5`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack
  (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PESTPP-GLM 5.2.16)
- **Working dir**: `GW-MCP-holdout/modeB/tutorial05/data` (closed-book;
  dispatched from the main repo with the absolute data path, all model files
  in `data\model`)
- **Prompt used**: the verbatim Mode B prompt from
  `research/discovery/playbooks/modeB-manual-layer3.md`, dispatched with a
  short preamble (data-folder absolute path + write a `run-log.md`). A copy of
  the agent's own run log is at
  `GW-MCP-holdout/modeB/tutorial05/data/run-log.md` (folder reset afterwards).

## Tool-call sequence (42 MCP calls)

1. `check_environment` — stack ready.
2. shell list — 7 staged data files found.
3. shell Python (geopandas/rasterio/pandas) — inspect CRS/geometry/attrs/obs/DEM.
4. `create_model(tut05, data\model)`.
5. `set_simulation(nper=1, perlen=[1], nstp=[1])` — steady state, single SP.
6. `import_grid_from_shapefile(dis, nlay=1, 200 m, activeZone.shp, EPSG:32718)` — 17×16, 272 cells.
7. `summarise_model` — DIS only confirmed.
8. `describe_model` — top is a uniform default (to be replaced by DEM).
9. shell Python — DEM in-polygon range 18–129 m.
10. `list_model_files` + read `tut05.dis` — top=0, botm=−1.
11. shell Python (rasterio) — derive `dem_bottom_100.tif` (= DEM − 100 m).
12. `assign_top_from_raster(dem_clipped.tif)` — top 21–119 m.
13. `assign_top_from_raster(dem_bottom_100.tif, layer=1)` — bottom −79..19 m.
14. `add_npf_package(icelltype=1, k=5.0)`.
15. `add_ic_package(strt=50)`.
16. `add_oc_package(head/budget)`.
17. `import_river_from_shapefile(RIV, cond_field=RIVCONDUC1, stage_raster=dem)` — 29 reaches.
18. shell Python — intersect CHD lines with grid → 18 + 20 cells.
19. `add_boundary_package(CHD, pname=chd_high, 70 m)` — 18 cells, north.
20. `add_boundary_package(CHD, pname=chd_lower, 40 m)` — 20 cells, S/W/E.
21. shell Python — map 29 wells to cells.
22. `add_boundary_package(WEL)` — 29 wells.
23. `model_status` — runnable.
24. `check_model` — clean.
25. `run_simulation` — converged, normal termination (0.22 s).
26. `compute_water_balance` — CHD-dominated (~42 036 m³/d in / ~42 035 out).
27. `validate_model` — warning: 68 convertible cells head above top (boundary-forced).
28. `diagnose_water_balance` — balanced (0.0029%), boundary-dominated by CHD (99.9998%).
29. `read_heads` — heads 40–70 m, mean 49.8 m.
30. `plot_heads_map` — `model\heads_map.png`.
31. `import_obs_from_csv(wells_obs.csv, lowercase sites)` — 29 sites.
32. `run_simulation` — re-run with OBS.
33. `compare_to_observed` — **FAILED**: obs CSV names uppercased by MODFLOW (W1..W29) vs registered lowercase (w1..w29) → no match. **Tool defect (backlog).**
34. shell Python — write `wells_obs_upper.csv` (uppercased site names; data transform).
35. `import_obs_from_csv(wells_obs_upper.csv)` — W1..W29.
36. `run_simulation` — converged; observation_fit RMSE 15.20 m, bias −13.29 m.
37. `compare_to_observed` — residuals + scatter; worst W26 (−28.8 m).
38. `setup_calibration(parameterisation={k: npf:k, scope all, initial 5}, obs_source=model)` — .pst + template + ins + wrapper; 29 obs matched.
39. `check_parameter_sensitivity(k=5)` — sensitivity 1.09e-7 (K does not control the head field).
40. `calibrate(par_data={k}, template_files=tut05_k.dat.tpl, noptmax=10)` — GLM chosen; phi 6696.83 unchanged (no gradient).
41. `summarise_calibration` — k=5.0 unchanged, RMSE 15.20, bias −13.29, R² −6.49; verdict improved=True, nothing identifiable.
42. `export_model_report` — `model\tut05_report.md`.

## Reprompts

- **0** (single-prompt session; no user follow-ups needed).

## Outcome vs criteria

- **Build: pass** — 1-layer DIS grid (~200 m, DEM top), RIV/CHD/WEL, NPF/IC/OC in `data\model`; `check_model` clean; `model_status` runnable.
- **Check: pass** — `check_model` no errors/warnings; `validate_model` one aggregated head-above-top warning (68 cells, boundary-forced, not a convergence failure).
- **Run: pass** — converged, "Normal termination of simulation"; `diagnose_water_balance` percent discrepancy 0.0029% → balanced.
- **Postprocess: pass** — water balance, head map PNG, `read_heads`, obs residual table + scatter all produced.
- **Calibrate: partial** — the full MCP chain ran end-to-end (`setup_calibration` → `check_parameter_sensitivity` → `calibrate`/GLM → `summarise_calibration`), GLM "OPTIMIZATION COMPLETE", but K was non-identifiable (sensitivity 1.09e-7, phi flat at 6696.83, K stuck at 5.0). The tools reported the situation correctly and the agent documented rather than worked around it.

## Known-limitation notes / MCP findings

- **`compare_to_observed` obs-name case matching (NEW DEFECT, filed in tasks.md):** MODFLOW uppercases observation names in the continuous obs CSV (W1..W29); sites registered via `import_obs_from_csv` keep the caller's case (w1..w29). `compare_to_observed`/`read_simulated_observations`/`run_simulation.observation_fit` matched case-sensitively → no sites matched on first attempt. Agent worked around it by re-importing an uppercased copy of the obs CSV (a data transform, allowed). **Fixed 2026-08-22** (`_read_simulated_observations_values` now matches columns case-insensitively; regression test `test_obs_matching_is_case_insensitive`).
- **Calibration non-identifiability (modelling-decision outcome, NOT a tool defect):** steady state, no recharge, negligible wells, homogeneous K, and the shapefile river conductance `RIVCONDUC1=0.001` (inert river) leave the head field fully pinned by the 70/40 m CHD boundaries. `check_parameter_sensitivity` correctly returned 1.09e-7 and GLM could not move K. Rerun-4 reached K=36.28 m/d by deliberately using the strong-drain default conductance instead of the attribute; this run kept the attribute (a defensible closed-book choice).
- **Aquifer bottom derived as DEM − 100 m** (no bottom raster supplied; data transform, documented deviation).
- **Obs re-import with `wells_obs_upper.csv`** was required only because of the case-matching defect above; after the fix a single import suffices.
- No GAP-capability proposals (UZF/MAW/STO/DISU/GWT) this run.
- Closed-book respected: no groundwater-mcp source/tests/tutorial PDFs/reference models read (per the run log).

## MCP-only violations

- **0** — shell Python was limited to reading/transforming the staged shapefile/CSV/raster data and DEM-derived bottom surfaces (explicitly allowed by the constraint); all model build/run/postprocess/calibrate actions went through the MCP tools.

## Started from the build_model_from_data MCP prompt?

- **No** — dispatched with the verbatim playbook prompt (C6 verification still open; intended for rerun-6).

## Time

- Not recorded in the run log (dispatched 2026-08-22 ~11:05 UTC; finished ~13:45 UTC per session idleness).
