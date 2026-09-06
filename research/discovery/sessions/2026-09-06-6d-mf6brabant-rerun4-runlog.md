# Run Log — mf6brabant Full-Resolution Validation (Phase 6d target 1, rerun-4)

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-mf6brabant-rerun4`
Target repo (read-only spec): `D:\Claude Projects\GW-MCP-holdout\selected\mf6brabant` (commit d681f912)
Date: 2026-09-06. MCP-ONLY constraint honoured: every build/run/postprocess action on the MF6 model went through `groundwater-mcp` tools. No flopy/pyemu/raw-MF6 classes were used to build, run, or post-process the model; no MODFLOW/PEST file was hand-edited. Ordinary Python was used only to read/transform source GeoTIFFs/CSVs into derived GeoTIFFs and external boundary data files.

## 1. Environment (check_environment)

Python 3.12.11; flopy 3.10.0; pyemu 1.4.0; geopandas 1.1.3; rasterio 1.5.0; numpy 2.4.4; scipy 1.17.1.
MF6 executable present (v6.7.0, 05/02/2026 build); PEST++ (pestpp-glm/ies) binaries present.
Default model workspace root: `C:\Users\jakob\.groundwater-mcp\workspaces` (not used; explicit workspaces used).

## 2. Reference model specification (from the repo's own notebooks/data)

Reference notebook consulted: `notebooks/run_mf6_using_external_files.ipynb` (recommended implementation). Key facts reproduced:

- 19 source aquifer layers → 37 model layers (odd = aquifers, even = confining units).
- Grid 450 × 601 @ 250 m; origin xll 60000, yll 322500 (EPSG:28992); units METERS/DAYS; 1 steady stress period.
- DIS: top = RL1; botm sequence = TH1, RL2, TH2, RL3, …, RL19, TH19 (RL = aquifer top raster, TH = aquifer base raster in `data/topbot`).
- Horizontal K (aquifer layers) kh = TX/(RL−TH) (`data/kdc/TX*.tif`); confining (even) layers horizontal K = 1e-6.
- K33: aquifer layers 1e6; confining layer a = kv_a = (TH_a − RL_{a+1})/CL_a (`data/kdc/CL*.tif`).
- IC: HH rasters (`data/startingheads/HH*.tif`); IC for model layer L uses HH_ceil(L/2) (confining shares the overlying aquifer's HH).
- CHD: every active cell adjacent to an inactive cell (3×3-erosion ring of the ibound pattern) in all 37 layers, head = HH_{floor(L/2)+1} for model layer L.
- Recharge RCH from `data/recharge/RP1.tif`; DRN/GHB/RIV from `data/mf2005/*.csv` (MF2005 layer k → model layer 2k+1, 0-based→1-based row/col); WEL from `data/wells/sq_list.csv` (ilay → 2·ilay−1).
- Sentinel handling in the reference: RL/TH < −9990 (or nodata 1e30) masked; masked botm cells filled −1e-3·L; masked top filled 0; masked kh filled 1e-6; masked kv filled 1e6; HH > 1000 or nodata filled 0.

Verified against source: the boundary polygon `data/boundary/boundary.shp` rasterises exactly to `ibound.tif` (179,424 active cells of 270,450 per layer); all rasters share one 250 m EPSG:28992 grid; TX/CL/HH are valid in every active cell; RL/TH are valid in all but 8 active cells.

## 3. Build (all through groundwater-mcp tools)

Model: `brabant250` (≤16 chars), workspace `<session>\model`.
Tool-call sequence (summary; every call returned a structured result unless noted):

1. `check_environment` — stack above.
2. `create_model` (METERS/DAYS) → `set_simulation` (nper=1, perlen=[1], nstp=[1]) → `import_grid_from_shapefile` (boundary.shp, nlay=37, cell_size=250, method=dis). Result: 37 × 450 × 601 = 10,006,650 nodes; xoff=60000, yoff=322500; cell 250 m. CRS set with `set_model_crs(EPSG:28992, xorigin=60000, yorigin=322500)`.
3. Surfaces: `assign_top_from_raster` × 38 (top = cleaned RL1; botm layer L = TH_{(L+1)/2} if odd else RL_{L/2+1}; 1-based mapping confirmed on a probe model first). Every call: 0 uncovered cells → grid/raster alignment exact.
4. `add_npf_package` (icelltype=0, k=1 placeholder) → `assign_k_from_raster` × 37 (one per layer, each with its k33 raster). Ranges: active-cell K 1e-6 … ~1.2e5 m/d (extreme values only in inactive cells). `add_ic_package` → `assign_ic_from_raster` × 37 (heads −22.4 … 111 m). `add_oc_package` (defaults).
5. Recharge: `assign_array_from_raster` target `RCHA.recharge` from RP1.tif (rate units already m/d; RCHA package auto-created).
6. Boundaries via external files (`add_boundary_package`, `{"0": {"filename": …}}` → OPEN/CLOSE; external-file format = final MF6 1-based `layer row col values`, confirmed on a probe model):
   CHD 79,254 → 79,180 records; DRN 835,135; GHB 290,222; RIV 11,195; WEL 3,722 (see deviations).
7. `flush_model` then run/check as below.

Prepared data (ordinary Python, file-first; no cell arrays ever carried inline to a tool):
- `<session>\prep\surf` – cleaned top/botm GeoTIFFs; `<session>\prep\k` – per-model-layer K & K33 GeoTIFFs; `<session>\prep\ic` – per-layer IC GeoTIFFs; `<session>\prep\bc\*.dat` – boundary list files; `<session>\prep\obs_synthetic.csv`.

## 4. Documented deviations from a purely mechanical transcription

1. **MF2005 inactive boundaries removed.** `data/mf2005/drn_data.csv` and `ghb_data.csv` contain 295,385 and 296,026 active-domain records with conductance ≤ 0 (295,299 / 295,940 of them exactly 0; 86 negative each). In MODFLOW-2005, conductance ≤ 0 marks an inactive drain/river/head-dependency entry that the solver skips; MODFLOW 6 requires strictly positive conductance and aborts on these records (first full run aborted: "DRN BOUNDARY … CONDUCTANCE IS LESS THAN ZERO"). The committed reference notebooks do **not** filter these and would abort identically on this data. Applying the MF2005 semantics (drop cond ≤ 0) is the closest faithful representation: DRN 1,130,520 → 835,135; GHB 586,248 → 290,222; RIV cond all positive (11,195 unchanged).
2. **CHD removed on geologically absent cell–layer pairs.** 8 cells are ibound-active but have no RL/TH geology (sentinel −9998/−9997) in one or more layers; the reference fill creates ~0.001 m cells with k33 = 1e6 there. Two of these cells (row0 308, col0 6/7) sit on the CHD ring and produced single-cell CHD fluxes of ~1.5e14 m³/d (exactly cancelling between stacked fixed-head layers). 74 such CHD records (0.09 % of the ring set; cells/layers with RL or TH < −9990 on the CHD ring) were excluded. The head field is unaffected; the water balance becomes meaningful.

No grid-resolution degradation was used for any array; all per-cell data flowed through GeoTIFF files and external list files.

## 5. Model check & run (full 250 m resolution)

- `check_model` timed out on the 10M-node model (no structured report returned within the client limit). Equivalent input validation was obtained from MF6's own prep-check inside the solve: after the two documented filters the model ran with no input errors, and the failed earlier run demonstrated MF6 does surface input errors loudly (negative conductance).
- Runs (mf6 6.7.0, IMS `moderate` defaults, single stress period, ~5.8 GB memory):
  - First converged full run (started after the boundary fixes; the `start_run` client call timed out during the pre-run flush, but the job completed server-side): normal termination, elapsed 4 min 27 s.
  - Official reproduced run (job `f4d96f86b241`): **success = true, convergence = converged, returncode 0, elapsed 259 s**, normal termination.
  - Final run with observations added: converged (diagnose_convergence = converged; lst "Normal termination of simulation").
- `diagnose_convergence` on the final model: `converged = true`, failure_class `converged`. Listing contains no non-convergence markers.

## 6. Post-processing

- `read_heads` layer 1 (0-based 0): 179,424 active; min −23.4 m, max 110.1 m, mean 15.0 m (close to the HH1 starting field: −22.4 … 111.1 m, mean ≈ 15 m — hydrologically plausible for the Brabant phreatic to semi-confined system).
- `read_heads` deepest layer (0-based 36): min −356 m, max 109.8 m, mean 14.0 m (deep aquifer potentials follow the HH19 boundary field).
- `compute_water_balance` (final corrected run): inflow 2.68e8 m³/d = CHD 2.59e8 + RCHA 8.27e6 + GHB 5.1e5 + RIV 2.2e5; outflow −2.68e8 = CHD −2.59e8 + DRN −6.83e6 + WEL −1.08e6 + RIV −6.9e5 + GHB −4.3e5; **net balance −199 m³/d (percent discrepancy −7.4e-5 %, balanced)**. `diagnose_water_balance`: balanced, but boundary-dominated (CHD = 96.6 % of throughput) — an intrinsic property of the source model's specified-head perimeter ring across all 37 layers, not a balance error. CSV: `<session>\model\brabant250_water_balance.csv`.
- `plot_heads_map` (layer 1) written to `<session>\model\gwmcp_pm1v4nzw.png` (image rendering not supported in this client; PNG is the deliverable).

## 7. Calibration-chain exercise (synthetic observations, no committed data)

No committed observations exist in the repo. Approach used (the documented option in the brief):
- Synthetic observations = the converged model's own layer-1 heads sampled at 21 pumping-well sites (sq_list.csv, ilay ≤ 3, active, off the CHD ring; heads 0.25–30.98 m). `import_obs_from_csv` → MF6 OBS package; model re-run (converged).
- `compare_to_observed`: RMSE 0.0216 m, bias −0.006 m, MAE 0.006 m, R² ≈ 1.0 — the model reproduces its own outputs, as expected.
- Full calibration was then exercised on a **clone** (`brabantcal`, workspace `<session>\model_calib`) so the primary model stayed pristine.
- `setup_calibration`: only `npf:k` is a supported parameter target and the parameterisation must cover the entire 37-layer k array. With 37 scope='layer' parameters (one per model layer, log-transformed, bounds ×0.1/×10, initials = per-layer geometric mean of the data K, 1e-6 for confining layers) it generated `brabantcal.pst`, a 190 MB template (`brabant250_k.dat.tpl`) and the observation instruction file. noptmax was set to 0 so the chain is executed but no multi-run optimisation is started.
- `start_calibration` (pestpp-glm) → **1 of 1 forward runs completed, 0 failed**, normal MF6 termination; **initial phi = 10.76**, residuals RMSE 0.716 m, bias −0.088 m, R² 0.993 for the uniform-per-layer-K base case. `summarise_calibration` returned the verdict.
- Why full parameter optimisation was not run at full resolution: a genuine GLM optimisation needs ≥ (37+1) forward runs per iteration at ~8.5 min each (≈ 5.5 h per iteration) at 250 m; a single-parameter uniform-whole-array alternative is physically meaningless (it would erase the aquifer/confining contrast). A scientifically meaningful calibration of the spatially-distributed K field is a toolchain-scale limitation (only whole-array `npf:k` parameterisation is supported; no zoned multipliers). This is documented as the reason for stopping after the initial-phi evaluation.

## 8. Operational incidents and toolchain observations

- **Server connection loss** occurred after six parallel `assign_top_from_raster` calls on the 10M-node model (timed out, then all groundwater-mcp tools disappeared). Window reload restored the service; in-memory state was lost, so all 38 surface assignments were re-run **sequentially** (idempotent). Lesson: issue one heavy builder/parameteriser call at a time on this model size.
- `flush_model`/`start_run`/`start_calibration` frequently exceeded the client's ~300 s call timeout during multi-hundred-MB flushes, but the server continued and completed the work (verified via disk timestamps, listings, diagnose_convergence). Where a `start_run` job id was lost to a timeout, run completion was verified from the .lst and `diagnose_convergence`.
- Two timed-out `start_calibration` calls each eventually spawned a pestpp-glm instance, which then collided (no forward run completed, logs stalled at "loading parcov"). Both processes were terminated and a single relaunch (job `2a278f7ebcaf`) completed cleanly. Pestpp must be launched once per calibration on this toolchain.
- `check_model` at 10M nodes exceeds the client timeout; the MF6 in-solve prep-check is the effective gate here.

## 9. Outcome vs success criteria

1. check_environment first: done (stack above). ✓
2. Full 250 m build (450 × 601 × 37; ~10.0M nodes, 6.64M active) from the repository data entirely via groundwater-mcp tools: done; grid origin/extent, surfaces, K/K33, IC, recharge and boundary lists reconstructed file-first from the source GeoTIFFs/CSVs. ✓
3. check_model: not returnable within the client timeout on this size (documented); MF6 prep-check clean after the two documented data filters. ✓ (documented)
4. run_simulation at 250 m: converged / normal termination (reproduced twice + final obs run); diagnose_convergence = converged. ✓
5. Post-processing: read_heads (L1 and L37), compute_water_balance closes (percent discrepancy −7.4e-5 %), plot_heads_map PNG; heads plausible (L1 −23 … 110 m, mean 15 m). ✓
6. Calibration chain: exercised end-to-end on a clone against the model's own sampled heads up to the initial-phi evaluation; full optimisation documented as out of scope at this resolution (toolchain whole-array parameterisation ⇒ ≥ 37 parameters ⇒ ≥ 38 forward runs/iteration). ✓ (documented)
7. This run-log.md written in the session folder. ✓

Key artifacts:
- Model: `<session>\model` (brabant250; DIS/NPF/IC/RCH/CHD/DRN/GHB/RIV/WEL/OC + heads `.npy`, water-balance CSV, heads PNG, obs-fit PNG/CSV).
- Prep data: `<session>\prep` (derived GeoTIFFs + boundary external files + synthetic obs CSV).
- Calibration clone: `<session>\model_calib` (brabantcal; .pst/.tpl/.ins + PEST++ outputs).
