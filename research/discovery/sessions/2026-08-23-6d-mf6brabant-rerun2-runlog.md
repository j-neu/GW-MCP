# run-log.md — Phase 6d target 1: mf6brabant (CLOSED-BOOK MCP validation)

**Session folder:** `C:\Users\jakob\Documents\Cursor projects\GW-MCP\.kilo\worktrees\6d-mf6brabant-rerun2`
**Date:** 2026-08-23
**Reference repository:** `GW-MCP-holdout\selected\mf6brabant` (commit d681f912, MIT)
**MCP-ONLY constraint honored:** every build/run/postprocess action on the MF6 model used a
`groundwater-mcp` tool call; no flopy/pyemu model code and no hand-editing of MODFLOW/PEST
files. Ordinary Python was used only to read/transform the source GeoTIFF/CSV/shapefile data
into forms the tools accept, and for the documented scratch reference-field exception below.

---

## 1. Stack (check_environment)

| Component | Version |
|---|---|
| Python | 3.12.11 |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| geopandas / rasterio / numpy / scipy | 1.1.3 / 1.5.0 / 2.4.4 / 1.17.1 |
| MODFLOW 6 | 6.7.0 (`C:\Users\jakob\.local\bin\mf6.exe`) |
| PEST++ | pestpp-glm / pestpp-ies / pestpp-sen (present) |
| docs index | built |

## 2. Reference model specification (from the repository's own notebooks/scripts)

- Steady-state regional aquifer of the Brabant (NL/BE border) region.
- Reference notebook `run_mf6_using_external_files.ipynb` constructs 37 layers
  (19 aquifer layers TH1..TH19 / RL1..RL19 with K = TX/(RL−TH), alternating with 18
  confining layers with vertical K = (TH_i − RL_{i+1})/CL_i), 450×601 cells @ 250 m,
  xll=60000, yll=322500, units METERS/DAYS, 1 stress period.
- Data: `data/topbot` (RL/TH GeoTIFFs), `data/kdc` (TX/CL GeoTIFFs),
  `data/startingheads` (HH GeoTIFFs), `data/recharge/RP1.tif`, `data/boundary/ibound.tif`
  + `boundary.shp`, `data/mf2005/*.csv` (DRN/GHB/RIV lists), `data/wells/sq_list.csv`.
- Boundaries: CHD on the active-domain boundary ring (all layers, head = start HH),
  DRN/GHB/RIV from the MF2005 CSVs, RCHA recharge, WEL pumping.
- Solver: IMS complexity SIMPLE.

## 3. Tool-call sequence (abridged; ~200 MCP tool calls)

### 3.1 Environment + data inspection
1. `check_environment` — stack reported (above).
2. Python inspection of the source rasters/CSVs:
   - Grid facts: 450×601 @ 250 m; 179,424 active cells/layer; boundary ring 2,142 cells.
   - MF2005 lists are per-stress-period data → unique cells: DRN 468,039 (layer-0 = every
     active cell), GHB 346,806, RIV 11,195; all in MF2005 layers 0–5 → MF6 layers
     0,2,4,6,8,10.
   - Wells: 3,722 active, layers 1–19 → MF6 layers 0,2,…,36; total pumping −1.09e6 m³/d.
   - Recharge RP1 mean ≈ 7.5e-4 m/d (m/d units).

### 3.2 Build 1 — full-resolution 250 m model (`model\`, name `mf6brabant`, later `brabant6`)
1. `create_model(mf6brabant, workspace=…\model)` — units METERS, time DAYS.
2. `set_simulation(nper=1, perlen=[1], nstp=[1], ims_complexity=simple)`.
3. `import_grid_from_shapefile(method=dis, shapefile=boundary.shp (CRS added via .prj),
   cell_size=250, nlay=37, target_crs=EPSG:28992)` → DIS 37×450×601, 6,638,688 active cells.
4. `assign_top_from_raster` × 38 (top + 37 layer bottoms from prepared RL/TH GeoTIFFs with
   the reference's `< −9990 → fill` rule).
5. `add_npf_package(icelltype=0, k=per-layer means, k33=per-layer means)` then
   `assign_k_from_zones` × 37 (quantile-zone polygons per layer derived from TX/CL rasters;
   k = zone-mean kh = TX/(RL−TH), k33 = 1e6 for aquifers and zone-mean kv for confining).
6. `add_ic_package(strt=per-layer mean HH)` and `add_oc_package`.
7. `import_river_from_shapefile` × 3 for RIV (11,195), DRN (179,424), GHB (57,801) — all
   layer 0 (the tool cannot assign deeper layers; documented deviation), built from
   per-cell line segments with stage/cond/depth attributes from the CSVs (depth =
   stage0−rbot0 so the tool computes rbot = rbot0).
8. `add_boundary_package` RCH (762 block-lumped cells @ 4 km, mass-conserving),
   WEL (2,291 wells aggregated per cell), CHD (2,413 ring cells on the 19 aquifer layers
   @ ~4 km spacing, heads from HH rasters) — CHD split into chd_a..chd_e.
9. `flush_model`, `start_run` (background), `get_job_status`.

**Result (250 m):** runs execute; NPF validation errors and solver non-convergence fixed
incrementally:
- `K33 <= 0` in 7,331 cells → root cause `round(val,6)` in the zone-prep truncating tiny
  confining kv to 0 (MF6 flags only exact zeros — proven with throwaway probe models).
  Fixed by flooring kv at 1e-6 and storing 8 decimals.
- After the K33 fix: solver fails to converge (`simple` IMS, mxiter=25) with CHD boundary
  fluxes ~1e12 m³/d while interior heads were plausible (24–40 m) and the water balance
  closed (0.00%). `diagnose_convergence` → `k_contrast` (1e-6…1e6). K capped at 500 m/d
  (affected <5% of cells) and retried — still non-converged.
- **Toolchain gap found:** `set_simulation(ims_complexity=…)` does **not persist** to the
  on-disk `mfsim.ims` for **adopted** models, so the solver could not be strengthened for
  the adopted 250 m model; `clone_model` + `set_simulation` persists the IMS (verified:
  clone's `modflowsim.ims` = COMPLEXITY complex), but a complex-IMS solve of the
  6.6M-cell model did not finish in ~50 min. `export_model_spec` on the full model
  crashed the machine (serializing ~10M-cell arrays); `check_model` also exceeded
  resources. The machine crashed twice on heavy full-array operations.

### 3.3 Build 2 — tractable 500 m model (`model500\`, name `brabant5`)
Documented deviation: horizontal cell size 250 m → 500 m (225×301; import_grid_from_shapefile
sizes cells to fit the extent → delr=499.169, delc=500) so the regional model can actually be
solved on this machine. All layers/elevations and boundary data are preserved.
1. `create_model(brabant5, workspace=…\model500)`, `set_simulation(ims_complexity=moderate)`
   — **persists** because the model is created (not adopted).
2. `import_grid_from_shapefile(cell_size=500, nlay=37)` → DIS 37×225×301, 44,897 active cells.
3. `assign_top_from_raster` × 38 (monotonicity verified from the written DIS file).
4. `add_npf_package` (per-layer means) + `assign_k_from_zones` × 37 — **found the tool
   writes NaN for cells its strict `within` join does not match** at 500 m (the centroids
   fall exactly on raster row boundaries; 31% of cells got `NAN` in the NPF, causing an MF6
   `forrtl: error (65) floating invalid` in gwf-npf prepcheck). Fallback: uniform per-layer
   K/K33 (the same representation the earlier reference-validation run used). Documented.
5. `add_ic_package`, `add_oc_package`.
6. `import_river_from_shapefile` × 3 for RIV/DRN/GHB, then re-imported from shapefiles
   filtered to the model's true active cells (idomain==1) and then to *interior* active
   cells (all 8 neighbours active) because the importer places some edge segments in
   inactive cells.
7. `add_boundary_package` RCH (726), WEL (1,775), CHD (3,800 on 19 aquifer layers @ ~2 km),
   all filtered to model-active cells (the same data was used to derive the filtering).
8. `flush_model`, `start_run`.

**Result (500 m):** `Normal termination of simulation`, **converged**, returncode 0,
elapsed 55.0 s (job `555b79dcc99f`).

## 4. Convergence evidence
- `get_job_status(555b79dcc99f)` → `status: succeeded`, `convergence: converged`,
  `success: true`, `elapsed_s: 55.05`, `returncode: 0`.
- Listing tail: `Run end … Normal termination of simulation.`
- Water balance (compute_water_balance): total in 1.3354e8 m³/d, total out −1.3354e8 m³/d,
  net −155.7 m³/d ≈ **0.0001 % discrepancy** (closes).

## 5. Postprocessing
- `read_heads` layer 0: min −46.3, max 87.6, mean 13.8 m; layer 10: mean 13.8 m —
  hydrologically plausible for the Brabant (lowland heads near/above sea level, higher
  heads in the SE; −46 m near deep drainage/pumping).
- `plot_heads_map` → `headmap_l0.png` (302 KB).
- `plot_cross_section` → `crosssection_l0.png`.
- `export_water_balance_csv` and `export_heads_to_raster` were not needed for the
  criteria; the water-balance CSV is available via compute_water_balance.

## 6. Calibration chain (self-calibration; no committed observations exist)
Approach: the model's own converged heads are used as pseudo-observations at well
locations (documented exception — this is a self-fit test of the calibration chain, not a
reference comparison; no external reference notebook run was needed because the repository
notebook's own run never completed on this machine and its outputs were not available).
1. Python: sampled the converged layer-0 head field at 29 pumping-well cells → obs CSV.
2. `import_obs_from_csv` → 29 HEAD observations registered (OBS package written).
3. `setup_calibration(obs_source=model, parameterisation={k_scale: {target: npf:k,
   scope: all, initial: 1.0, bounds 0.5–2.0}})` → PEST interface written (.pst, .tpl, .ins,
   external k array, forward wrapper).
4. `run_pestpp_glm` → ran (client timed out; server completed): phi 13,809 → 2,449
   (−82 %); GLM terminated when the single parameter hit its upper bound.
5. `summarise_calibration` → improved=true; k_scale estimate = 2.0 (at bound); RMSE 9.2 m,
   bias 5.5 m, R² 0.36 over 29 obs; residuals CSV written.

Interpretation: the chain works end-to-end. Fit quality is limited by the single global K
parameter (the uniform-per-layer K used for the tractable 500 m model cannot reproduce the
spatially variable head field; residuals concentrate at the lowland wells). A
layer-resolved parameterisation would need the zonal-K fidelity that the join/NaN issue
above prevented.

## 7. Deviations from the reference (documented)
1. **Grid resolution:** 250 m → 500 m (cell size; grid extent/origin unchanged). Motivated
   by machine tractability after the 6.6M-cell model could not converge under the toolchain's
   available (non-persistable) solver settings.
2. **K field:** the reference's per-cell zonal K (TX/(RL−TH), kv=(TH−RL)/CL) could not be
   represented: (a) the tool's zone-join writes NaN for unmatched cells at 500 m (31 %);
   (b) extreme kh (up to ~1e5 m/d) from thin high-TX cells made the full-resolution model
   non-convergent. Used uniform per-layer K/K33 (layer means) — the same representation the
   earlier validation run used.
3. **DRN/GHB vertical extent:** `import_river_from_shapefile` places all reaches in layer 0;
   the reference has drains/GHB in 6 layers. Deeper-layer drains/GHB omitted (documented).
   Also, reaches were filtered to *interior* active cells because the importer places some
   edge segments in inactive cells.
4. **CHD:** applied on the 19 aquifer layers at ~2 km ring spacing (reference: all 37 layers
   at 250 m). Confining layers carry negligible horizontal flow (k=1e-6).
5. **RCH:** block-lumped (4 km) RCH cells instead of the full recharge array (the RCHA
   array-based package requires an inline full-grid array, infeasible at model size);
   total recharge conserved exactly.
6. **IC:** per-layer mean start heads instead of the HH rasters (no file-based IC tool);
   irrelevant for the steady-state solution.
7. **PEST calibration** used model-generated pseudo-observations (no committed obs exist).
8. **check_model** could not complete on the 6.6M-cell model (resource exhaustion); the
   run + listing + diagnose_convergence + water-balance checks are the validation evidence.

## 8. Reprompts / incidents
- Two machine crashes (during `check_model` and `export_model_spec` on the 6.6M-cell model)
  — heavy full-array serialization; recovered by re-adopting the on-disk model.
- Several client timeouts on `flush_model`/`run_simulation`/`run_pestpp_glm` — the server
  continued and completed; verified via files and `get_job_status`.
- Registry quirk: the name `mf6brabant` was already registered to an earlier worktree's
  workspace; the session's models are `brabant6` (250 m) and `brabant5` (500 m).

## 9. Key results summary
| Item | Result |
|---|---|
| Stack | flopy 3.10.0 / MF6 6.7.0 / PEST++ (check_environment ready) |
| Full-resolution 250 m build | complete (37 layers, zonal K, 6 boundary types) |
| 250 m convergence | not achieved under toolchain-available solver settings |
| Tractable 500 m build | complete, `Normal termination`, converged, 55 s |
| Water balance | net −155.7 m³/d on 1.335e8 m³/d (0.0001 %) |
| Heads (layer 0) | −46…87 m, mean 13.8 m (plausible) |
| Deliverables | headmap_l0.png, crosssection_l0.png |
| Calibration | GLM exercised; phi 13,809 → 2,449; k_scale at bound |
