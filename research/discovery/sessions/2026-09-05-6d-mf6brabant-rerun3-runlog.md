# run-log.md — mf6brabant target 1, rerun-3 (Phase 6d, CLOSED-BOOK)

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-mf6brabant-rerun3`
Reference data: `D:\Claude Projects\GW-MCP-holdout\selected\mf6brabant` (commit d681f912).
Date: 2026-09-05.

## 1. Stack check (success criterion 1)
`check_environment` (groundwater-mcp) reported a ready stack:
- Python + flopy/pyemu/geopandas/rasterio available, MODFLOW 6 + PEST++ executables located.
- Local docs index present; default workspace root configured.
Everything was built/run/post-processed strictly through groundwater-mcp MCP tool calls.
No flopy/pyemu classes were used to build or run the model; Python (venv) was used only to read/transform the source GeoTIFF/CSV/shapefile data into the data forms the tools accept (GeoTIFFs, zone shapefiles, external list `.dat` files, obs CSVs).

## 2. Reference model facts (from the repository's own scripts/notebooks)
- Steady-state regional Brabant (NL/BE) aquifer model.
- 19 hydrogeological units; reference builds 37 alternating MF6 layers (19 aquifers + 18 confining beds, quasi-3D: aquifer k33 dummy 1e6 m/d, confining k33 = Δz/C from the CL*.tif c-values).
- Grid 450×601 @ 250 m, origin xll=60000 yll=322500, CRS EPSG:28992, units METERS/DAYS, one steady stress period.
- Sources: top/botm `data/topbot/RL*.tif` + `TH*.tif`; K `data/kdc/TX*.tif` + `CL*.tif`; start heads `data/startingheads/HH*.tif`; recharge `data/recharge/RP1.tif`; active domain `data/boundary/ibound.tif` + `boundary.shp`; DRN/GHB/RIV lists `data/mf2005/*.csv`; wells `data/wells/sq_list.csv`.
- Reference boundaries: CHD around the active-domain ring (all 37 layers, head = HH of the aquifer), DRN, GHB, RIV, RCH (array), WEL.

## 3. Capability assessment and deviations (success criterion 2 — documented)
Key capabilities discovered by probing the toolchain on scratch models:
- `import_grid_from_shapefile` builds a DIS grid from the model boundary polygon and sets idomain itself (1 inside / -1 outside); `set_model_crs` not needed afterwards (CRS is set by the importer).
- `assign_top_from_raster` sets the top (layer 0) and each layer bottom (layer N) from GeoTIFF rasters, per layer.
- `assign_k_from_zones` sets spatially variable k (and k33) per model layer from polygon shapefiles.
- Boundary packages accept list data BOTH inline (JSON records) AND via external list files using flopy's `stress_period_data={0: {"filename": "x.dat"}}` form (verified on a probe and on the real model). This is how the full DRN/GHB/CHD sets were ingested — the inline JSON form at the target scale would have required ~10⁶ boundary records (the source CSVs hold 1.13 M DRN / 0.59 M GHB rows at the reference 250 m grid), far beyond a practical agent tool-call payload.
- `add_dis_package` accepts scalar top/botm (per-layer scalars) but **not** 2-D inline arrays for spatially varying `idomain` (only scalar, per-layer scalar list, or a full 3-D array). At the reference 10 M-node scale the 3-D arrays cannot be carried in an agent context, so per-cell idomain is only practical via `import_grid_from_shapefile`.
- No raster→K tool exists (only zone polygons via `assign_k_from_zones`), and no raster→IC tool exists.

**Deviations adopted (closest feasible representation), each documented:**
1. **Resolution**: the full 450×601×37 = 10.0 M-node model with ~1.7 M boundary records and 3-D K/IC arrays is beyond what an agent-driven MCP session can ingest inline (arrays/idomain/K would each be tens of MB of JSON). The model was therefore built on a **coarse but fully regional grid**: 45 rows × 61 cols × 37 layers (≈ 101,565 nodes, 67,525 active), delr = 150250/61 ≈ 2463.1 m, delc = 2500 m, same origin and CRS as the reference. The active/inactive pattern is the reference polygon rasterised at this resolution (1,825 active cells/layer, identical in all 37 layers like the reference). All boundaries were mapped onto the coarse cells by cond-weighted aggregation.
2. **idomain outside the polygon = −1** (set by `import_grid_from_shapefile`) instead of the reference 0; identical for fully inactive columns, no hydraulic difference.
3. **CHD ring** applied on the 19 aquifer layers only (not the 18 confining layers; confining-layer horizontal K is 1e-6 so the rim condition there is hydraulically immaterial). Head = reference HH of the corresponding aquifer sampled at the coarse cell.
4. **DRN / GHB** aggregated per (coarse cell, layer): representative elevation/head = conductance-weighted mean; conductance summed; drop the csv's inert records whose elevation > 200 m (they never activate) and cells with negligible conductance (cond < 1000 m²/d for DRN, < 1e-2 m²/d for GHB — retains ≥ 99.97 % / 100 % of the total boundary conductance).
5. **K** per layer was computed from the 250 m rasters (kh = TX/(RL−TH) per aquifer; kv = Δz·mean(1/C) per confining bed) and upscaled to the coarse grid (transmissivity-weighted horizontal K, vertical-resistance-weighted kv), then applied through `assign_k_from_zones` with one per-active-cell polygon shapefile per layer. So the reference spatial heterogeneity pattern is preserved at the coarse scale rather than replaced by uniform layers.
6. **IC** = per-layer scalar (active-area mean of HH per aquifer; confining layers take the aquifer above, as in the reference). Steady-state only; affects only the starting guess.
7. Recharge applied as RCHA array = areal mean of RP1 per coarse cell (RP1 is already in m/d).
8. Wells (sq_list.csv) mapped by x/y to coarse cells, extraction summed per (cell, layer); ilay (1-based aquifer) → model layer 2·ilay−1.

## 4. Build sequence (groundwater-mcp tool calls)
1. `create_model(brabant_mcp, workspace=…\model\brabant_mcp, METERS/DAYS)`.
   - First attempt with name `mf6brabant` collided with a stale registry entry from an earlier rerun pointing at a non-existent path; model was deleted/unregistered and re-created under the name **brabant_mcp**.
2. `set_simulation(nper=1, perlen=[1], nstp=[1], ims_complexity=MODERATE)` (TDIS+IMS).
3. `import_grid_from_shapefile(boundary.shp, nlay=37, cell_size=2500, dis)` → 45×61×37, CRS EPSG:28992, xoff 60000 yoff 322500.
   - The source `boundary.shp` has no `.prj`; a CRS-qualified copy (`model/boundary_crs.shp`, EPSG:28992) was written from the data and used.
4. `add_npf_package(icelltype=0, k=1e-6 placeholder, k33=1e6)`.
5. 37× `assign_k_from_zones(k_field=k, k33_field=k33, layer=L-1, shapefile=k_layerNN.shp)` (aquifer kh + k33=1e6; confining k=1e-6 + k33=Δz/C). First probe exposed a polygon-geometry bug (zone polygons shifted one row down → 123 active cells unmatched); fixed in the data-prep and re-applied (7240→1825 matched, 0 unmatched active cells).
6. 38× `assign_top_from_raster(layer=0..37, method=nearest, surf_*.tif)` — reference top/botm elevations resampled at the coarse cells (inactive columns filled with the reference-style ordered dummy stack).
7. `add_ic_package(strt=<37 per-layer scalar means of HH>)`.
8. `add_oc_package(head/budget files)`.
9. Boundary packages — each with an external list file prepared from the source CSVs (`chd.dat` 3,971 rec; `drn.dat` 3,757 rec; `ghb.dat` 1,737 rec; `riv.dat` 323 rec; `wel.dat` 970 rec; `recharge.dat` 45×61 array) via
   `add_boundary_package(package=CHD/DRN/GHB/RIV/WEL/RCHA, stress_period_data={0: {"filename": …}})`. A stray duplicate CHD from an earlier pname-less probe was removed by re-adding the pname-less CHD package (the tool replaced the old one); a stale unreferenced `brabant_mcp_0.chd` file was deleted from the workspace.
10. `check_model` → **clean** apart from the expected NPF warning “vertical hydraulic conductivity above 100000” (the reference sets aquifer k33 = 1e6 m/d dummy; carried over intentionally).
11. `model_status` → runnable, no missing required/recommended packages.

## 5. Run and convergence evidence (success criteria 3–4)
- `start_run` (background) → job `f081bbe1d1cb` **succeeded** in ~1.6 s wall-clock.
- `get_job_status`: `convergence: converged`; listing summary ends with **“Normal termination of simulation.”**, returncode 0, sequential single stress period/timestep solve.
- No `auto_fix` or solver escalation needed (IMS MODERATE).

## 6. Post-processing (success criterion 5)
- `read_heads`:
  - layer 1 (model layer 1, top): min −1.94 m, max 78.18 m, mean 15.22 m over 1,825 active cells.
  - layer 7 (mid): min −1.72, max 77.83, mean 15.20.
  - layer 19: min −1.98, max 77.89, mean 14.90.
  - layer 37 (deepest): min −2.46, max 77.89, mean 15.00.
  → Heads are positive regional heads, following the terrain (correlation of top-layer head vs the top surface ≈ 0.98), plausible for a drainage-dominated humid lowland aquifer (polder-like lows near 0 m in the north-west, high recharge-mounded areas to the south-east).
- `compute_water_balance` (kstpkper 0,0): total inflow 1.3771e8 m³/d, total outflow −1.3771e8 m³/d, net **−5.7 m³/d → closes** (relative discrepancy ≈ 4e-6 %).
  - `diagnose_water_balance`: `balanced: true`, percent_discrepancy −4.2e-6 %. Dominant term CHD (≈94 % of gross flow) — the rim fixed-head ring recirculates water between high/low head segments of the ring (gross CHD ≈ 1.29e8 in/out, net CHD ≈ +5e4 m³/d). This is the expected signature of a fixed-head rim on a domain with strong K (the reference is structurally identical); documented as a known feature of the representation, not a mass-balance failure.
- `plot_heads_map` → `model/heads_layer1.png`; `plot_cross_section` (row 22) → `model/crosssection_row22.png` (PNGs written; this model can't display images, files saved to disk).

## 7. Calibration exercise (success criterion 6) — calibrated against the model's OWN outputs
Approach (documented): no field observations are shipped with the target. To exercise the full calibration chain, a clone was made from the converged model and synthetic HEAD observations were sampled from the clone's OWN simulated heads (120 sites on model layer index 6, spatially even over the active domain). Because an unperturbed clone would be a perfect fit (RMSE ≈ 0.0003 m), the calibration model was deliberately started from a **misfitting parameterisation** — initial K = 0.5× the geometric-mean kh of each aquifer layer (uniform per layer, in place of the spatially variable K) — and PEST++ was run to recover better uniform-per-layer K values. The final interface used 5 adjustable aquifer-K parameters (kL01, kL03, kL05, kL07, kL09); the first 37-adjustable-parameter interface was retired after the background-runner stall described below.
Steps:
1. `clone_model(brabant_mcp → brabcal)`.
2. `import_obs_from_csv(obs_layer6.csv, layer=6, 120 sites)` → 120 HEAD observations registered (obs CSV `brabant_mcp.obs`).
3. `run_simulation(brabcal)` → converged, observation_fit RMSE 2.8e-4 m (sanity check: obs are the model's own values).
4. `setup_calibration(obs_source=model, 37 × npf:k layer parameters, noptmax=6)` → `brabcal.pst` (120 obs, log parameters), external k array + template + instruction file + Windows-safe forward wrapper generated.
   - First pass made all 37 layers adjustable (confining near-fixed). A GLM attempt (job `cc32e83e3389`) started iteration 1 and then stalled (see below) and was cancelled. The interface was then regenerated with `partrans="fixed"` on the 18 confining + 14 deep aquifer layers and **5 adjustable aquifer parameters** (kL01, kL03, kL05, kL07, kL09; initial 0.5 × geometric-mean kh), noptmax=4.
5. GLM retry (job `165c901d494b`) also stalled under the background runner and was cancelled.
6. `run_pestpp_ies(num_reals=6, num_workers=1)` (synchronous) → ran to completion server-side (4 IES iterations; the MCP client timed out, outputs complete on disk).
7. `summarise_calibration` → see results below.

### Calibration results
- **Engine invocation note**: PEST++ runs launched through the **background** job runner (`start_calibration`, GLM and IES) stalled on this Windows host — the pestpp child process tree started, but the model wrapper subprocesses never spawned `mf6.exe` (0 CPU, no child) and the jobs were cancelled after ~20–30 min of inactivity. The identical forward-run command (`python gwmcp_run_brabcal.py`, which simply chdir's to the workspace and runs `mf6.exe`) completes in < 1 s with normal termination when run directly, and the **synchronous** `run_pestpp_ies` MCP call executed the same engine successfully (it only exceeded the client response timeout; the engine kept running server-side and wrote all results). This is documented as a toolchain/environment quirk (background calibration spawn on Windows), not a model or PEST-interface problem.
- **Successful IES run** (`run_pestpp_ies`, num_reals=6, noptmax=4 from the .pst): 12 initial + ~150 total model runs through the MCP forward wrapper.
  - Phi trajectory (`brabcal.phi.actual.csv`): iteration 0 mean **78.2** (min 37.2) → iter 1 **15.62** → iter 2 **15.29** → iter 3 **15.17** → iter 4 **15.11**; base-parameter phi 14.85.
  - `summarise_calibration`: RMSE **0.35 m**, bias −0.055 m, R² **0.995** over the 120 head observations; verdict `fit_within_measurement_error: true` (0.35 m < 0.5 m supplied measurement error). Residuals table written to `brabcal_residuals.csv`.
  - Parameter ensemble moved physically sensible amounts to fit the synthetic layer-6 heads (final `brabcal.4.par.csv`): e.g. aquifer-1 K kL01 ≈ 0.6–1.1 (init 1.03), aquifer-3 K kL03 ≈ 1.0–1.3 (init 0.99), aquifer-4 K kL07 ≈ 20–22.5 (init 4.49, pressed toward the 22.47 upper bound to compensate the uniform-per-layer approximation of a spatially variable K), aquifer-5 K kL09 ≈ 0.34–0.48 (init 0.69). Fixed (confining/deep) parameters unchanged.
  - Residual floor ≈ sqrt(14.9/120) ≈ 0.35 m is expected: the calibration model parameterises each layer with a single uniform K while the “true” model (its own output used as observations) has spatially variable per-cell K, so a uniform layer cannot reproduce it exactly.
- Calibration approach satisfied: no committed observations exist in the target; synthetic HEAD observations were derived from the calibrated model's OWN simulated heads (clone + obs at 120 sites, model layer index 6), and the MCP calibration chain (import_obs_from_csv → setup_calibration → pestpp-IES → summarise_calibration) was exercised end-to-end with a clear, documented phi improvement.

## 8. Files produced
- Model workspace: `model/brabant_mcp/` (input set + `brabant_mcp.hds`, `brabant_mcp.cbb`, listings).
- Calibration workspace: `model/brabcal/` (PEST++ interface, phi trajectory, final ensemble `brabcal.4.par.csv`, residuals CSV).
- Prepared data: `model/prep/` (coarse GeoTIFFs, zone shapefiles k_layerNN.shp, aggregated CSVs, payload JSONs, obs CSVs).
- Figures: `model/heads_layer1.png`, `model/crosssection_row22.png` (saved to disk; the images cannot be rendered in this model session).
- Water balance: `model/water_balance.csv`.

## 9. Success-criteria status summary
1. **Stack check** — done (flopy/pyemu/geopandas/rasterio + MF6 + PEST++ present).
2. **Regional build from data via MCP tools** — done; full pipeline exercised at a coarser-but-regional 45×61×37 grid with documented deviations (resolution, CHD layer selection, DRN/GHB aggregation, IC simplification, idomain −1 outside the polygon). Boundary lists ingested via external list files, which the toolchain supports.
3. **check_model** — clean; only the intentional NPF k33 > 1e5 warning (reference aquifer kv = 1e6 dummy) is reported.
4. **Run convergence** — `converged`, “Normal termination of simulation.” in ~1.6 s (get_run_log/lst confirmed).
5. **Post-processing** — read_heads across layers show hydrologically plausible Brabant heads (−2…78 m; layer-1 mean 15.2 m, head closely follows the terrain, corr ≈ 0.98); water balance closes (net −5.7 m³/d on 1.4e8, relative −4.2e-6 %); heads map + cross-section PNG written. CHD rim gross flow dominates (≈94 %), consistent with a prescribed-head rim on high-K strata; documented.
6. **Calibration chain** — exercised end-to-end against the model's OWN outputs (synthetic obs from clone's simulated layer-6 heads): import_obs_from_csv → setup_calibration → pestpp-IES → summarise_calibration. Phi fell 78 → 15.1; RMSE 0.35 m within the 0.5 m measurement error. Background-engine stall on Windows documented; synchronous path works.
7. **run-log.md** — this file.

## 10. Limitations / recommended follow-ups
- Full reference resolution (450×601×37 ≈ 10 M nodes) is not practically ingestible by an agent-driven MCP session: per-layer 3-D DIS/NPF/IC arrays and ~1.7 M DRN/GHB list records would need multi-10 MB inline JSON per call. External-file list support removes the boundary bottleneck; a raster-K and raster-IC assign tool (mirroring assign_top_from_raster) plus a file-based DIS/NPF array path would enable the full-resolution build.
- `assign_k_from_zones` replaces the target layer slice (unmatched cells → NaN) rather than preserving pre-existing values; when applied after a scalar NPF this leaves NaN in inactive cells (harmless for idomain ≤ 0, but worth noting).
- Background `start_calibration` (GLM/IES) model-spawn deadlock on Windows: forward command verified OK standalone and via synchronous `run_pestpp_ies`.
- The CHD rim gross recirculation dominates the balance; if a closer match to reference boundary fluxes were required, the rim condition would need to be re-scaled or replaced by GHB with realistic conductances.
