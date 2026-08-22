# Mode B session — tutorial 05 (natural language) rerun-8

- **Date**: 2026-08-22
- **Client / model**: Agent Manager worktree session (`modeb-tutorial05-rerun8`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack
  (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PESTPP-GLM 5.2.16) — fixed tool set.
- **Working dir**: `GW-MCP-holdout/modeB/tutorial05/data` (closed-book; model
  files in `data\model`, registered as `tut05`).
- **Prompt used**: the verbatim Mode B prompt from
  `research/discovery/playbooks/modeB-manual-layer3.md`, dispatched with the
  standard preamble. Run log at `GW-MCP-holdout/modeB/tutorial05/data/run-log.md`.
- **Notable**: first closed-book run in which calibration **identified K** —
  the make-or-break decision was interpreting the wells' `Q` attribute as
  m³/s rather than m³/d (see below).

## Tool-call sequence

1. `check_environment` — ready.
2. `create_model(tut05, data\model)`.
3. `set_simulation(nper=1, perlen=[1], nstp=[1])` — steady state.
4. `import_grid_from_shapefile(activeZone.shp, dis, 200 m, EPSG:32718, layer_surfaces=[dem_clipped.tif])` — 17×16; the single `layer_surfaces` entry did not populate `top` (tool expects nlay+1 surfaces), so top was assigned explicitly.
5. `assign_top_from_raster(dem_clipped.tif, layer=0, mean)` — top 22.1–119.7 m; botm −1 m default.
6. `add_npf_package(icelltype=1, k=1, k33=0.1)`.
7. `add_ic_package(strt=50)`.
8. `add_oc_package`.
9. `import_river_from_shapefile(RIV, cond_field=RIVCONDUC1, stage_raster=dem, stage_offset=1)` — 29 reaches.
10. Python — densify CHD lines → 18 cells @70 m (north/east), 20 @40 m (west/SE); map wells to cells.
11. `add_boundary_package(CHD ×2, WEL ×29)` — first WEL attempt omitted the layer index (PACKAGE_ERROR, corrected to `[layer,row,col]`).
12. `import_obs_from_csv(wells_obs.csv, value_col=head_m)` — 29 sites.
13. `model_status` runnable; `check_model` pass.
14. `run_simulation` — converged; initial fit RMSE 10.67, bias −8.06.
15. `compute_water_balance`/`diagnose_water_balance` — balanced (0.0004%), >99% CHD.
16. `plot_heads_map` — heads_map.png.
17. `setup_calibration({k: npf:k, initial=1, bounds 0.05–20})` — rewire + tpl/ins/pst/wrapper.
18. `run_pestpp_glm` — client timed out; pestpp-glm kept running server-side.
19. `start_calibration(glm)` — raced the orphaned process in the same workspace; diagnosed, `cancel_job` (tree-kill) stopped both, removed stale artifacts, restarted cleanly.
20. `check_parameter_sensitivity(k=1)` — **≈1e-6** (non-identifiable: ~100% CHD-driven, verbatim Q≈0.014 m³/d). Decision: interpret well `Q` as **m³/s**, rebuild WEL with Q×86400 (total ≈ −3836 m³/d).
21. `run_simulation` (K=1, converted Q) — converged but 3 big-well cells went dry → re-setup `initial=5`, bounds 0.1–500.
22. `run_simulation` (K=5) — converged, no dry cells; RMSE 8.55.
23. `check_parameter_sensitivity(k=5)` — **0.0087** → K identifiable.
24. `start_calibration(glm)` — **succeeded**: converged after 4 iterations (PHIREDSTP/NPHISTP), phi 2119.5 → 1942.1, 49.9 min (per-iteration FOSM slow).
25. `summarise_calibration` — K = 3.32 m/d; posterior stdev (log10) 0.92 → 0.05; RMSE 8.18, bias −2.22, MAE 6.42.
26–28. Final `run_simulation` (RMSE 8.18), `compute_water_balance` (balanced 0.0002%; CHD share 86.7%), `plot_heads_map` (calibrated), `compare_to_observed` (residuals + scatter).

## Reprompts

- **0**.

## Outcome vs criteria

- **Build: pass** — 1-layer DIS grid (~200 m, DEM top, botm −1), RIV/CHD/WEL, NPF/IC/OC.
- **Check: pass** — `check_model` clean.
- **Run: pass** — all MF6 runs converged / "Normal termination" (exit 0).
- **Postprocess: pass** — water balances close (0.0004% → 0.0002%), head maps, obs fit + residuals.
- **Calibrate: PASS (first in the closed-book series)** — full chain ran end-to-end and K was identified:
  **K = 3.32 m/d**, phi 2119.5 → 1942.1 (−8.4%), RMSE 10.67 → 8.18 m, bias −8.06 → −2.22 m,
  GLM converged (PHIREDSTP/NPHISTP, NOPT=3 of 10), posterior stdev 0.92 → 0.05.

## Key decision (well-rate unit interpretation)

The wells' `Q` attribute (−0.014 m³/d ≈ 14 L/d per well) is physically
implausible for pumping wells and is consistent with SI m³/s. Rebuilding WEL
with Q×86400 gave a total abstraction of ≈3836 m³/d, making the wells a real
sink (≈26% of outflow) and — critically — making K identifiable
(sensitivity 0.0087 vs ≈1e-6 with verbatim Q). This mirrors rerun-4's
strong-drain river choice: the dataset's calibration is only achievable when
the agent makes a defensible hydrogeological interpretation that the bare
attributes do not state. It is a data/documentation gap (attribute units
undocumented), not a tool defect.

## Fix verification

- **Process-tree cancel: verified live.** After the `run_pestpp_glm` client-timeout orphan, `cancel_job` terminated the orphaned pestpp-glm/mf6 tree so a clean `start_calibration` could proceed.
- **`start_calibration` background path: verified live.** GLM ran to convergence through the background job (49.9 min, polled).
- **CRS persistence: verified** — no CRS_UNKNOWN after `setup_calibration` rewrites.
- **Obs-name case-insensitivity: verified** — lowercase CSV sites matched without re-import.

## Known-limitation notes / MCP findings

- **Well-rate units undocumented** (`Q` in `wells.shp`): the calibration result hinges on the agent's m³/s interpretation. Consider whether `add_boundary_package`/tools.md should note rate-unit expectations (model time units).
- **`import_grid_from_shapefile(layer_surfaces=...)` expects nlay+1 surfaces** (top + one per layer bottom); passing only the DEM for a single layer leaves flat defaults. Tool-description clarity item.
- **Client-timeout orphan + background-job race**: `run_pestpp_glm` that exceeds the client timeout keeps running server-side; starting a background job in the same workspace races it. The agent recovered with `cancel_job` (tree-kill) — consider documenting that `run_pestpp_glm`/`run_pestpp_ies` should be reserved for fast jobs and `start_calibration` preferred (as the prompt guide already advises).
- Residual pattern: sites at 30–34 m sit below the 40 m CHD floor and away from sinks — unreachable with this boundary geometry; three distinct recorded values occur at one cell (synthetic scatter). Not a tool issue.

## MCP-only violations

- **0** — plain Python limited to data transformation (line densification, cell mapping, unit conversion); all model build/run/postprocess/calibrate actions via MCP tools. The stale-artifact cleanup was `Remove-Item` on PEST++ run outputs (not model input files).

## Started from the build_model_from_data MCP prompt?

- **No** — verbatim playbook prompt.

## Time

- Not recorded precisely (started ~17:27 UTC; GLM alone 49.9 min; finished by ~21:30 local).
