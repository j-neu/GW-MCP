# Closed-book validation run — Phase 6d target 6 (neversink_workflow), RERUN-2

Date: 2026-09-11/12  ·  Session worktree: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun2`
Host: win32, PowerShell 7  ·  Working dir at start: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun2`
Data: `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\` (USGS public domain)

Result summary
- Adopt + check + run + postprocess: **all pass**. Run converges to normal termination; water balance closes.
- Baseline run reproduces the shipped solved listing to **max 3.06e-4 m** on 858 head observations and **identically** on the 2 SFR flow observations.
- Calibration chain completed end-to-end: `setup_calibration` -> `run_pestpp_glm` -> `summarise_calibration` (+ `compare_to_observed`). φ 542,101 -> 266,953 -> 245,338; R² ≈ 0.92, RMSE ≈ 27 m vs 337 derived field observations.
- **Deviations / non-MCP-model issues** are documented in §8 (grid active-cell count differs from the brief; `setup_calibration` is not idempotent and damaged NPF K across repeated calls, recovered via `assign_k_from_raster`; PEST model-launch wrapper intermittently deadlocked under host suspend/AV, worked around by serial runs — see §8).

---

## 1. Environment (criterion 1)

`check_environment` (first tool call):

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| geopandas | 1.1.3 |
| rasterio | 1.5.0 |
| numpy / scipy | 2.4.4 / 1.17.1 |
| matplotlib | 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / -ies / -sen / -opt / -da | present in `C:\Users\jakob\.local\bin\` |
| docs index | built (`C:\Users\jakob\.groundwater-mcp\index`) |
| workspace root | `C:\Users\jakob\.groundwater-mcp\workspaces` |
| ready | **true**, missing.packages=[], missing.binaries=[] |

## 2. Model as shipped (reference spec)

`neversink_mf6/` is a single MODFLOW 6 GWF model `neversink`:
- DIS 4 layers × 680 rows × 619 cols, 50 m, METERS; `delr=delc=50`; top/botm/idomain external.
- TDIS: 1 steady stress period, `perlen=1` day, `nstp=1`, TIME_UNITS days, start 2011-01-01.
- NPF (as shipped): `icelltype=1`; k = LAYERED OPEN/CLOSE `k0..k3.dat`; k33 = `k330..k333.dat`.
- RCHA (arrays): `irch.dat`, `rch_000.dat`. CHD: 2026 records (`chd_000.dat`). WEL: 34 (`wel_000.dat`, BOUNDNAMES). SFR: 12316 reaches (`neversink_packagedata.dat`), `neversink.sfr.obs`.
- OBS6 continuous head at USGS/NY-DEC wells -> `neversink.head.obs` (858 columns across 448 sites, layers 1–4).
- OC: HEAD FILEOUT `neversink.hds`, BUDGET FILEOUT `neversink.cbc` (not committed; produced by our run).

Shipped solved listings (`mfsim.lst`, `neversink.list`, `neversink_SFR.chk`) record a converged native-parameter run: *normal termination*, GWF budget IN–OUT = −0.365 m³/d, PERCENT DISCREPANCY = −0.00, SFR IN–OUT = 4.7e-10.

Reference values preserved before any run (copied to `session-neversink-rerun2/reference/`):
`neversink.head.obs`, `neversink.sfr.obs.output.csv`, `neversink.obs`, `mfsim.lst`, `neversink.list`.

## 3. Adoption (criterion 2)

```
adopt_model(name="neversink", workspace="...\neversink_mf6",
            units="METERS", time_units="DAYS", allow_modify=True)
-> {"adopted": true, "allow_modify": true, "model_names": ["neversink"]}
```
Name = `neversink` (9 chars ≤ 16). No grid rebuild, no file renames. `allow_modify=True` was needed because the calibration chain must rewire NPF K and register observations; `check_model`/`run_simulation`/`read_heads` would have worked read-only.

`model_status` -> `runnable: true`, no missing required/recommended packages.

`summarise_model` -> DIS 4×680×619 = 1,683,680 cells; **n_active = 300,236**;
packages DIS, IC, NPF, RCHA, OC, WEL_0, OBS_0, CHD_0, SFR_OBS, SFR_0; 1 steady stress period.

> **Deviation from the brief:** the brief stated "843k active" cells. The shipped `idomain_*.dat` give **300,236 active cells** (layer active counts 85,051 / 13,787 / 11,700 / 189,698). The total grid is 1,683,680 cells as stated. No action taken — reported as-is.

## 4. Pre-run check (criterion 3)

`check_model` -> `check_passed: true`, errors = [].
105 warnings, all pre-existing in the published model: 88 × `chd_0 package: BC in inactive cell`, 17 × `wel_0 package: BC in inactive cell`. These are benign (MF6 ignores BCs on `idomain<=0`); documented, not "fixed".

## 5. Run (criterion 4)

`start_run` (background to avoid client timeout) -> job `dd24f507147b`.

```
status: succeeded  elapsed 29.7 s  returncode 0
listing: "Normal termination of simulation."
```
Warnings in the listing are the shipped deprecation notices (SFR `UNIT_CONVERSION`, IMS `OUTER_HCLOSE`/`OUTER_RCLOSEBND`/`INNER_HCLOSE`, `PRECONDITIONER_DROP_TOLERANCE` ignored) — carried over from the 2021 input set.

## 6. Postprocessing (criterion 5)

- `read_heads(layer=0)` -> layer 1 heads, min 88.10 / max 631.17 / mean 361.49 m; 85,051 active cells. (`.npy` written.)
- `compute_water_balance` (final step):
  inflow  RCHA 489,968.17 + CHD 10,607.27 + SFR 22,787.81 = 523,363.25 m³/d
  outflow WEL 9,881.27 + CHD 13,164.32 + SFR 500,317.75 = 523,363.34 m³/d
  net −0.082 m³/d
- `diagnose_water_balance` -> percent_discrepancy **−1.57e-5 %**, `balanced: true`, RCHA/SFR dominance 0.50, `boundary_dominated: false`.
- `plot_heads_map(layer=0)` -> `gwmcp_wq372t5i.png` (rendered).

### 6a. Reference reproduction (baseline, native K)

Comparing our fresh `neversink.head.obs` (858 values) to the preserved shipped listing:

| metric | value |
|---|---|
| n | 858 |
| max abs head difference | **3.055e-4 m** |
| mean abs head difference | 4.500e-6 m |
| SFR obs (1436500, 1366650) | **identical** to 5 s.f. (−100,940 / −147,140 m³/d) |

The baseline run reproduces the shipped solved listing (native parameter run) essentially exactly.

## 7. Calibration (criterion 6)

### 7a. Observation set derivation (documented)

Observed head/streamflow *values* are not shipped as a ready target table. The source data in `processed_data/` do contain real field measurements:

- `NY_DEC_GW_sites.csv` — 449 NY-DEC wells with `gw_elev_m` (observed groundwater-surface elevation, metres) and projected `x,y` (EPSG:5070, same CRS as the model).
- `NWIS_GW_DV_data.csv` — 1 NWIS head measurement (site `414525074360601`, gw_elev_m 357.182).
- `NWIS_DV_STREAMSTATS_*` / `neversink_inflow.csv` — streamflow/STATS sources (not used: SFR target values were not needed and no ready flow target table exists).

Site names in the NY-DEC file (`obsnme`, e.g. `SV748`, `U1730`, `O10577`) match the model OBS6 site names (case-insensitive): **447/448 model head sites matched**.

Chosen defensible target set (data-prep script `prep_obs.py` / `prep_obs2.py`, plain file/CSV processing — no model building):
- **337 layer-1 head observations** = the 336 matched NY-DEC wells that the model itself observes in layer 1, plus the NWIS site.
- Each observation is the *real field* `gw_elev_m`, mapped by `import_obs_from_csv` to the nearest cell centroid in model layer 1 (0-based layer 0).
- Rationale: layer 1 is the upper model layer, so a field water-level elevation is compared against the shallowest simulated head; restricting to sites the model itself observes in layer 1 keeps the target network faithful to the published model.
- Verification: the tool's nearest-centroid cells matched the model's own OBS6 cells for these sites (e.g. SV748 -> `[0,513,411]` = shipped 1-based `HEAD 1 514 412`).

Reference-derived alternative (offered by the brief) was **not** needed; real field values were available.

### 7b. Registration

`import_obs_from_csv(model, csv=calib_obs_layer1.csv, obs_type=HEAD, layer=0, x/y/value cols)`:
`{"site_count": 337, "total_records": 337}`; wrote `neversink.obs` (OBS6) and `neversink_obs_summary.csv`. (This intentionally replaces the shipped 857-target OBS6 for calibration; the shipped reference was preserved in §2.)

### 7c. Parameterisation

The rerun-2 note points at `setup_calibration`'s **zoned multiplier** NPF K parameterisation, which preserves the shipped K pattern. Zone structure of the shipped K fields (distinct positive K per layer): L1=9, L2=7, L3=3, L4=1.

Attempted 20-parameter (all-layer zones) run was cancelled: the forward runs are cheap (≈30 s) but each PEST Jacobian needs ~21 model runs and the host was heavily loaded/suspending, making a 20-param GLM impractical.

Final setup (`setup_calibration`, `noptmax=2`, `obs_source="model"`):
- `kl1`: 9 zones, layer 1 (base_k 0.050292 … 60.96)
- `kl4`: 1 zone, layer 4 (uniform base_k 0.16764 — flattening is a no-op, so the pattern is preserved)
- 10 adjustable parameters, log-transformed, initial 1.0, bounds 0.1–10 (dimensionless multipliers `k = base_k × multiplier`).
- Outputs: `neversink.pst`, `neversink_k_mult.dat.tpl` -> `neversink_k_mult.dat`, NPF k rewired to external `neversink_k.dat`, instruction file `neversink_head.obs.csv.ins`, forward wrapper.

### 7d. Run

`run_pestpp_glm(num_workers=1)` (foreground call timed out client-side at ~2 min; the server-side GLM continued and completed). Final job output:

```
iobj:
iteration,model_runs_completed,total_phi,measurement_phi,regularization_phi,head_obs
0,0,542101,542101,0,542101
1,18,266953,266953,0,266953
2,38,245338,245338,0,245338
```
φ reduced 542,101 -> 266,953 -> **245,338** (−54.7 %).

### 7e. Result — `summarise_calibration`

Parameter estimates (multipliers):

| param | layer/zone | base_k | estimate |
|---|---|---|---|
| kl1_z1 | L1 z1 | 0.050292 | 1.267 |
| kl1_z2 | L1 z2 | 0.16764 | **10.00 (upper bound)** |
| kl1_z3 | L1 z3 | 1.6764 | 1.191 |
| kl1_z4 | L1 z4 | 3.81 | 0.969 |
| kl1_z5 | L1 z5 | 8.382 | 1.190 |
| kl1_z6 | L1 z6 | 9.144 | 1.931 |
| kl1_z7 | L1 z7 | 22.86 | 3.558 |
| kl1_z8 | L1 z8 | 45.72 | 1.332 |
| kl1_z9 | L1 z9 | 60.96 | 1.174 |
| kl4_z10 | L4 | 0.16764 | 3.883 |

Fit (PEST, 337 obs): **RMSE 26.98 m, bias −9.15 m, R² 0.920**.

`compare_to_observed` (independent of PEST weighting): **RMSE 27.21 m, MAE 15.93 m, bias −9.71 m, R² 0.919** (n=337). Residual table `neversink_obs_residuals.csv`, scatter `neversink_obs_fit.png`.

Baseline (native-K) fit for reference: iteration-0 φ 542,101 -> RMSE sqrt(542101/337) ≈ **40.1 m**. Calibration reduces RMSE to ≈27 m, i.e. a real improvement against field data.

### 7f. Comparison against the shipped reference

- **Baseline vs shipped solved listing:** reproduced to 3.06e-4 m (heads) and exactly (SFR) — §6a.
- **Calibrated vs baseline:** calibration changes the shipped K pattern only by per-zone dimensionless multipliers (kl1_z2 hits the 10× upper bound; layer-4 K ×3.88; other layer-1 zones 0.97–3.56). The shipped K *spatial pattern* is retained.
- Because the shipped listing IS the native-parameter run, the calibrated state is a *scenario* relative to it; the reference comparison is therefore the baseline-vs-listing match plus the field-observation fit improvement.

## 8. Deviations, decisions and non-MCP-model issues

1. **Active-cell count differs from the brief.** Actual 300,236 actives (not 843k). Reported, not changed.
2. **`setup_calibration` is not idempotent and mutated NPF K.** Calling it repeatedly (different parameterisations) rewires NPF `k` to the external `neversink_k.dat`; a layer-scope setup then wrote all-1 K into that external array, so a later zone setup saw a single uniform zone. The shipped `neversink.npf` was overwritten in the process and no pristine copy existed. **Recovery (MCP-only):** `set_model_crs(EPSG:5070, xorigin=1742955, yorigin=2258285)` then `assign_k_from_raster(NPF.k)` from the source `processed_data/Layer{1..4}_Kh.tif` (EPSG:5070, 50 m, aligned to the grid). Verification (`verify_k.py`): restored K matches the shipped `k0..k3.dat` on all active cells except **22/85,051 (L1)** and **2/13,787 (L2)** zone-boundary cells; L3 and L4 exact. This is a real defect: a calibration tool must be safely re-runnable without silently corrupting the base property field.
3. **PEST model-launch wrapper stalled repeatedly.** The generated forward wrapper (`subprocess.run([mf6])` after rewriting a ~28 MB K array) intermittently never spawned `mf6.exe`, leaving `run.info` frozen at `run_id 0`/first perturbation. This coincided with (a) a runaway `find` process consuming a core, (b) Surfshark AV activity, and (c) **the host suspending overnight** (observed clock jump 23:05 -> 09:24, job frozen ~10.4 h). Once the host was awake and GLM was launched with **`num_workers=1`**, runs proceeded (~1–3 min/run). No MCP capability was missing — but the calibration is fragile to host state and the wrapper does not surface a launch failure.
4. **20-param zones -> 10-param (L1 zones + L4).** Reduced for tractability given the host. Layer-4's single zone was included though `summarise`'s uncertainty summary shows it is low-sensitivity (composite scaled sensitivity ≈0.013 vs ≈0.23–0.99 for L1 zones).
5. **`kl1_z2` at its upper bound (10.0).** The dominant layer-1 zone wants more transmissivity than the default ×10 bound allows; bounds were not widened. Flagged for a future run with wider bounds.
6. **OBS6 replaced for calibration.** `import_obs_from_csv` overwrote the shipped `neversink.obs` (857 targets) with the 337-target set. Shipped reference preserved by copy in §2.
7. **Foreground `run_pestpp_glm` and `assign_k_from_raster` client-timeouts.** Both exceeded the ~2-min client timeout but completed server-side (verified via `.iobj`/file timestamps). A background-job entry point for these would be preferable.
8. **Remaining residual bias.** Calibrated bias is −9.7 m (simulated high), and a handful of sites have large residuals (SV2225 −261 m, U7190 −152 m, SV1050 −109 m). A single/zoned layer-1 K multiplier cannot remove local structural error; no further fitting was attempted.

## 9. Tool-call sequence (chronological)

1. `check_environment`
2. `adopt_model`
3. `model_status`, `summarise_model`, `check_model`
4. `start_run` -> `get_job_status` (succeeded)
5. `read_heads`, `compute_water_balance`, `diagnose_water_balance`, `plot_heads_map`
   (+ data-prep: copy reference listings; `prep_obs.py`, `prep_obs2.py`, `inspect_rasters.py`, `verify_k.py`)
6. `import_obs_from_csv` (337 targets)
7. `setup_calibration` (20 zones) -> `start_calibration` (cancelled — too slow)
8. `setup_calibration` (4 layer params) -> `start_calibration` (cancelled — stalled)
9. `setup_calibration` (20 zones, re-read corrupted K) -> discovered cascade
10. `set_model_crs`, `assign_k_from_raster` (K recovery) -> `setup_calibration` (9+1 zones) -> `start_calibration` (cancelled after stall)
11. `run_pestpp_glm` (num_workers=1, completed server-side) -> `summarise_calibration`, `compare_to_observed`

## 10. Reprompts

**0** user reprompts during the run. All steps proceeded from the single initial instruction plus the rerun-2 note; no clarifying question was needed.

## 11. Artifacts

Session folder `session-neversink-rerun2/`:
- `reference/` — `neversink.head.obs`, `neversink.sfr.obs.output.csv`, `neversink.obs`, `mfsim.lst`, `neversink.list`
- `prep_obs.py`, `prep_obs2.py`, `inspect_rasters.py`, `verify_k.py`
- `calib_obs_layer1.csv` (337 field observations), `calib_obs_field.csv`

Model workspace `neversink_mf6/` (now in calibrated configuration): `neversink.pst`, `neversink_head.obs.csv.ins`, `neversink_k.dat.tpl`, `neversink_k_mult.dat`, `neversink_k.dat`, `neversink_obs_residuals.csv`, `neversink_obs_fit.png`, `neversink.iobj`, `neversink.rec`, plus run outputs `neversink.hds/.cbc/.list`, `mfsim.lst`, `gwmcp_wq372t5i.png`.
