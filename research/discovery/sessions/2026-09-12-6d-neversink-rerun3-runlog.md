# Closed-book validation run — Phase 6d target 6 (neversink_workflow), RERUN-3

Session: 2026-09-12. Working dir: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3`
Model: DOI-USGS `neversink_workflow` / `neversink_mf6` (Neversink–Rondout basin, NY; flopy 3.3.3 / modflow-setup 2021).
Constraint: every build/adopt/run/postprocess/calibrate action went through a `groundwater-mcp` tool. No flopy/pyemu MODFLOW or PEST classes were called directly; no MODFLOW/PEST files were hand-edited. Python was used only to read shipped reference listings / obs CSVs and to prepare the observation CSV.

## Outcome (summary)

| Criterion | Result |
|---|---|
| 1. check_environment | ready=True; full stack present |
| 2. adopt_model | `neversink` at `...\neversink_mf6`, runnable, pristine (read-only) |
| 3. check_model | check_passed=True (105 pre-existing warnings, documented) |
| 4. run_simulation | converged, **Normal termination**, ~28 s |
| 5. postprocess | read_heads ✓, water balance closes ✓ (disc −1.6e-5 %), plot_heads_map ✓ |
| 6. calibration chain | setup_calibration → run_pestpp_glm → summarise_calibration: phi 725,261 → 327,897 |
| 7. run-log.md | this file |
| Reprompts | **0** (no clarifying questions asked) |
| MCP-only violations | **0** |

## 1. Environment (check_environment)

Python 3.12.11 at `D:\Claude Projects\GW-MCP\.venv`. Packages: flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8. Executables: mf6 `C:\Users\jakob\.local\bin\mf6.exe`, pestpp-glm, pestpp-ies, pestpp-sen, pestpp-opt, pestpp-da. Local docs index built. Nothing missing.

## 2. Model adoption

- `adopt_model(name="neversink", workspace="...\neversink_workflow\neversink_mf6", units=METERS, time_units=DAYS)`.
- Adopted read-only (pristine); the shipped `mfsim.nam` + package files **are** the model. No grid rebuild, no file renames.
- The model is 4 layers × 680 rows × 619 cols @ 50 m; 1,683,680 cells (≈350k active); single steady stress period (perlen 1 day from 2011-01-01); DIS/IC/NPF/RCH/OC/WEL/CHD/SFR + OBS6 (857 head-obs entries at 448 unique USGS/NY-DEC wells) + SFR obs. `model_status` runnable=True.

## 3. check_model

`check_passed=True`. 105 warnings, all pre-existing in the shipped model and reproduced by the shipped reference run:
- 88 CHD records in inactive cells, 17 WEL records in inactive cells.
The reference `mfsim.lst` terminated normally with the identical model, so these are accepted structural quirks (idomain vs boundary placement), not new defects introduced by adoption.

## 4. Simulation

`start_run` job `545953d5345d` → status **succeeded**, `converged=True`, **Normal termination of simulation**, elapsed ≈ 28 s (first MF6 run). `get_run_log` tail confirms `Normal termination of simulation.`; only deprecation warnings (SFR UNIT_CONVERSION, IMS OUTER_HCLOSE/INNER_HCLOSE) and the benign `PRECONDITIONER_DROP_TOLERANCE` notice.

## 5. Post-processing (base model)

- `read_heads(layer=0)`: shape 680×619, 85,051 active cells, min 88.10 m, max 631.17 m, mean 361.49 m.
- `compute_water_balance`: total inflow 523,363.25 m³/d, total outflow 523,363.34 m³/d, net −0.082 m³/d. `diagnose_water_balance`: **balanced=True**, discrepancy −1.6e-5 % (< 1 % tolerance); no single boundary dominates.
  Inflow: RCHA 489,968.17; SFR 22,787.81; CHD 10,607.27. Outflow: SFR 500,317.75; CHD 13,164.32; WEL 9,881.27.
- `plot_heads_map(layer=0)` rendered (PNG returned).
- `validate_model`: pre-existing conditions only — 64 disconnected `idomain` regions, 11,545 cells head-below-bottom, 189,897 convertible cells above top. All are in the shipped model (the native run terminated normally); reported for transparency, not introduced here.

## 6. Calibration

### Observation set (derived + documented)

Observed head VALUES are not shipped as a ready target table. They were derived from the field data in `processed_data/`:

- **447 NY-DEC wells** (`NY_DEC_GW_sites.csv`): observed head = `gw_elev_m` (land-surface elevation minus measured depth-to-water; verified `gw_elev_m = ls_elev_m − GW_Depth_ft × 0.3048`, e.g. SV700: 422.376 − 100 × 0.3048 = 391.896).
- **1 NWIS well** (`NWIS_GW_DV_data.csv` / `_sites.csv`): site 414525074360601, `gw_elev_m` = 357.182.

The 448 derived sites are an **exact one-to-one match** with the 448 unique site names in the model's own OBS6 package (`neversink.obs`), confirming this is the model's intended observation set. Prepared CSV: `obs\obs_heads_field.csv` (columns site,date,value,x,y,source). Scripts: `scripts\make_obs.py`.

**Layer choice.** The MCP obs registration (`import_obs_from_csv`) maps all sites to a single model layer per registration (repeat imports replace, they do not merge per-site layers — verified). Coverage analysis of the 448 well cells:
- layer 1 active at 337 sites, layer 2 at 40, layer 3 at 32, **layer 4 at 448**.
Layer 4 is the only model layer active at every well, so the calibration target set was registered at **layer 4** (index 3). This is defensible because the reference run's vertical head gradient at multi-layer sites is small (median 1.09 m, p95 3.56 m) versus the 40 m native misfit. Mapping is via nearest cell centroid on the model grid (CRS EPSG:5070); every mapped cell is active.

### Setup

- Base model left pristine. `clone_model("neversink" → "neversink_cal")` at `C:\Users\jakob\AppData\Local\Temp\kilo\neversink_cal`; re-adopted with `allow_modify=True`.
- `import_obs_from_csv` registered the 448 observed heads.
- `setup_calibration(obs_source="model", parameterisation={k_l0..k_l3: zones})` → **448 observations, 20 adjustable parameters** — one dimensionless multiplier per distinct shipped-K zone (9/7/3/1 per layer), bounds 0.1–10, log-transformed. The zones table reports `base_k` exactly matching the shipped K values (0.050292, 0.16764, 1.6764, 3.81, 8.382, 9.144, 22.86, 45.72, 60.96 m/d), so the shipped K **pattern is preserved** and each multiplier scales its zone's base K (fix (a) confirmed).
- `setup_calibration` was called three times in the session (first at layer 1, then twice at layer 4 with noptmax 10 and 5). The base K array was regenerated correctly each time with no corruption; the zone base_k values were identical across calls (fix (b), safe re-runnability, confirmed).

### Run

Chosen engine: **pestpp-glm** (20 parameters, 448 observations → gradient-based).
Two `start_calibration` (background) attempts **hung**: pestpp-glm spawned the generated forward wrapper, but the wrapper deadlocked before launching MF6 (wrapper CPU frozen, no `mf6` child, no K-array rewrite, stuck at the base run) — reproduced on a second attempt. Using the synchronous `run_pestpp_glm(num_workers=1)` executed the same `.pst` successfully; the MCP client request timed out (~client-side), but the PEST++ job continued server-side and ran to completion. Results were read with `summarise_calibration`. This start_calibration hang is the one toolchain issue observed (see "Deviations / issues").

### Results

phi progress (sum of squared weighted residuals):

| iter | model runs | phi | RMSE (m) |
|---|---|---|---|
| 0 (native) | 0 | 725,261 | 40.24 |
| 1 | 30 | 372,568 | 28.84 |
| 2 | 59 | 371,562 | 28.80 |
| 3 | 107 | 328,261 | 27.07 |
| 4 | 154 | 328,029 | 27.06 |
| 5 | 202 | **327,897** | **27.05** |

Residual statistics at the optimum (448 obs, weight 1): **RMSE 27.05 m, bias −6.56 m, R² 0.914**.
Estimated multipliers (dimensionless, base K × mult): k_l0_z1 1.11, z2 **10.0 (bound)**, z3 1.25, z4 1.00, z5 1.24, z6 2.95, z7 4.20, z8 1.68, z9 1.16; k_l1_z10 8.56, z11 1.00, z12 1.13, z13 **10.0 (bound)**, z14 1.70, z15 0.97, z16 1.11; k_l2_z17 1.03, z18 2.24, z19 8.25; k_l3_z20 6.63.

`summarise_calibration.verdict`: `parameters_at_bounds=[k_l0_z2, k_l1_z13]` (both hit the upper bound 10.0 — these zones are insensitive at the current level and would need a wider bound). `improved=false` here is a bookkeeping artefact: the verdict compares against a *previously recorded* calibration in-session (none), not against the native baseline; versus the native prior (phi 725,261) the fit improved 54.8 %.

## 7. Reference comparison (calibrated vs shipped native run)

Shipped `mfsim.lst`/`neversink.list` reproduce the native-parameter run, which our base adoption re-ran identically. Comparing both against the same 448 field observations at the same (layer-4) cells:

| | RMSE (m) | bias (m) | R² |
|---|---|---|---|
| Native (reference) | 40.24 | +24.38 | 0.811 |
| Calibrated (GLM) | **27.05** | **−6.56** | **0.914** |

RMSE reduced **32.8 %**; the systematic +24 m high bias is reduced to −6.6 m. Largest residual improvements are at sites with large DEM/depth-derived elevation error; the largest remaining residuals (SV2225 −257 m, SV1527 −145 m, SV1790 −113 m) come from NY-DEC rows whose `GW_Depth` is a round sentinel (500/1000 ft), i.e. observation-quality issues that K cannot correct — see Limitations.

## Deviations from the source model

1. **Outputs regenerated in place.** Running the base model rewrites `neversink.hds/.cbc/.list/neversink.head.obs/mfsim.lst` etc. in `neversink_mf6\` (the workspace is the model dir). No *input* file was modified; the run reproduces the native parameter solution.
2. **Calibration uses a clone, not the shipped dir.** `neversink_cal` at `...\Temp\kilo\neversink_cal` is a copy; base remains pristine.
3. **Observation representation.** `import_obs_from_csv` rewrote the clone's `neversink.obs` from the original 857 per-layer entries to 448 single-layer (layer-4) entries with output `neversink_head.obs.csv`. The base model's original OBS package is untouched.
4. **NPF rewired for calibration (clone only).** k = one external array (`neversink_k.dat`) with per-zone multipliers; k33 still reads the shipped `k33*.dat`. IC/DIS/BC/SFR unchanged.
5. **noptmax capped at 5** on the clone to bound runtime (≈40 s/forward run); source model has no such cap.

## Limitations / issues

- **Observed-set quality.** `gw_elev_m` is derived from depth-to-water plus a raster land surface; a subset of wells carry round sentinel depths (500/1000 ft) that produce implausible water levels (11 wells with |native residual| > 100 m). These were retained to avoid cherry-picking; they dominate the residual tail and cap achievable fit.
- **Single-layer registration.** The MCP registers one layer per observation set, so it cannot reproduce the model's original per-well screened-layer mapping (337 layer-1 wells + 111 deeper). Layer 4 was used for all 448 (see rationale above).
- **Toolchain issue (not an MCP-only violation):** `start_calibration` (background GLM) hung twice — the generated forward wrapper deadlocked before launching MF6. The synchronous `run_pestpp_glm` ran the identical `.pst` to completion. The `start_calibration` background runner and this generated wrapper appear incompatible in this uv-venv environment; `run_pestpp_glm` (with a client timeout during the long run) was the working path.

## Tool-call sequence

check_environment → adopt_model(neversink) → model_status / summarise_model → check_model → start_run → get_job_status → read_heads → compute_water_balance → diagnose_water_balance → plot_heads_map → validate_model → clone_model(neversink→neversink_cal) → delete_model(neversink_cal) → adopt_model(neversink_cal, allow_modify=True) → import_obs_from_csv (×4) → setup_calibration (×3) → start_calibration (×3, hung) → run_pestpp_glm (completed) → summarise_calibration (×2) → get_run_log → list_models. (Plus read-only Python for reference/CSV parsing and obs-CSV preparation.)

## Artefacts

- Run log: `run-log.md` (this file).
- Observed set: `obs\obs_heads_field.csv` (448 sites), plus prepared shallow/deep splits.
- Scripts (data prep/reference reading only): `scripts\make_obs.py`, `split_obs.py`, `analyze.py`, `check_layers.py`, `layer_coverage.py`, `compare_layers.py`, `residuals.py`, `quality.py`, `compare_calibration.py`.
- Calibration workspace (clone): `C:\Users\jakob\AppData\Local\Temp\kilo\neversink_cal` (`neversink_cal.pst`, `.par`, `.rei`, `.rec`, `.iobj`, `neversink_cal_residuals.csv`).
