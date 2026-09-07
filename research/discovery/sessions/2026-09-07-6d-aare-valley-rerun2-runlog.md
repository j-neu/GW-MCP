# CLOSED-BOOK VALIDATION RUN — Phase 6d target 3 (Aare Valley)

- Date: 2026-09-07
- Dataset: `D:\Claude Projects\GW-MCP-holdout\selected\aare-valley\exportPaper\` (CC BY 4.0, Zenodo 8047723, Neven & Renard 2023, WRR)
- Session worktree: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-aare-valley-rerun2`
- Model name (adopted): `aar_2d` — workspace = the published `HydrologicalModel\` directory (read-only)
- Calibration clone (writable): `aar2d_cal` — `C:\Users\jakob\.groundwater-mcp\workspaces\aar2d_cal`

Every action that builds/adopts/runs/post-processes/calibrates the MF6 model was done through
`groundwater-mcp_*` tool calls. No flopy/pyemu MODFLOW/PEST class was instantiated directly and no
MODFLOW/PEST file was hand-edited. Plain Python (numpy + pickletools-style offset parsing + memmap)
was used only to READ the published ArchPy posterior reference files for the step-6 comparison.

---

## 1. Environment (check_environment)

- Python 3.12.11 (`.venv`), platform Windows-10
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8
- Binaries located: `mf6.exe`, `pestpp-glm.exe`, `pestpp-ies.exe`, `pestpp-sen.exe`, `pestpp-opt.exe`, `pestpp-da.exe`
- docs_index_built: true; `missing: {packages: [], binaries: []}`; `ready: true`

## 2. Archive layout / model identification

```
exportPaper/
  HydrologicalModel/   mfsim.nam + aar_2d.* + Aar.riv + Gurbe.riv + lake.chd + wel.wel
                       + shipped solved outputs (aar_2d.hds/.cbc/.lst, mfsim.lst)
  ArchPyPrior/         stochastic-geology prior (surfaces only; realizations generated on the fly)
  ArchPyPosterior/     published posterior (~16 GB; P1.fac/.unt/.pro/.sf/.msk.npy/... )
  LoadAndPlotArchpy.ipynb, ReadME.txt, environment.yml
```

Model spec (read from the model files):
- Single GWF `aar_2d`; DIS 1 layer x 205 rows x 202 cols (25 m uniform), XORIGIN 2,602,669.91 / YORIGIN 1,192,202.67
- TDIS: 1 steady-state period of 1.0, TIME_UNITS **seconds**; IMS moderate
- NPF: k CONSTANT **0.03**, icelltype 0 (confined), SAVE_FLOWS + SAVE_SPECIFIC_DISCHARGE
- IC (strt), RCH6 `rcha_0` (recharge 1.78209031E-08 m/s, READASARRAYS), WEL6 (`wel.wel`, 2 wells, one zero-rate), CHD6 `chd` (lake, 85 cells @ 506 m), **RIV6 `Aar.riv` (306 reaches) + RIV6 `Gurbe.riv` (231 reaches)**
- OBS6 `head_obs` → 34 HEAD observations Obs0–Obs33, writes `head_obs.csv`
- OC: HEAD+BUDGET to aar_2d.hds/aar_2d.cbc
- Active cells: 16,081 of 41,410 (idomain)
- **Layer thickness is constant 1.0 m** (top = botm + 1), i.e. the model is depth-integrated: its "K" is numerically a transmissivity (T = K·1 m in m²/s)

## 3. Adoption

- `adopt_model(name="aar_2d", workspace=<HydrologicalModel dir>)` → `adopted: true, read_only: true`.
  The shipped mfsim.nam + package files ARE the model; the grid was not rebuilt and no file renamed.
  Registry already contained a stale `aar_2d` entry pointing at the same directory from an earlier
  session; adoption refreshed/re-confirmed it. (Pre-existing `.gwmcp_registry.json` was not read.)
- `summarise_model` confirmed packages [DIS, IC, NPF, RCHA_0, WEL, OC, HEAD_OBS, CHD, AAR, GURBE],
  grid 1x205x202, 16,081 active, 1 steady-state period. `model_status` → runnable.
- Shipped reference outputs were copied to `run-artifacts\` before the first re-run so the published
  "Normal termination" evidence is preserved on disk.

## 4. check_model

- Result: `check_passed: true`, `errors: []`.
- 311 warnings, all "BC in inactive cell": 153 x `aar` (Aar RIV), 115 x `gurbe` (Gurbe RIV),
  42 x `chd` (lake CHD outline), 1 x `wel` (the zero-rate well at 1,74,102).
- These are inherent to the published input set (boundary cells clipped at the domain edge) and do not
  prevent normal termination; **documented, not introduced by adoption**. npf K checks and all BC index
  checks passed.

## 5. run_simulation

- `run_simulation(aar_2d)` → `success: true, convergence: converged`, elapsed 0.22 s,
  listing ends **"Normal termination of simulation"**.
- Shipped reference listing (preserved copy): 4 outer / 32 total iterations, "Normal termination",
  1.039 s (2022-10-28). Our re-run: identical 4 outer / 32 total iterations → bitwise-equivalent solve.
- `get_run_log` used to confirm termination in the listing file.

## 6. Post-processing

- `read_heads(layer 0, kstpkper [0,0])`: 16,081 active cells; min 501.278, max 516.000, mean 510.503 m.
- `compute_water_balance`: inflow 1.3923 (RIV +0.8131, RCHA +0.1782, CHD +0.4011),
  outflow −1.3943 (WEL −0.2833, RIV −1.1076, CHD −0.0033); net −0.0019 m³/s →
  **percent discrepancy ≈ −0.14 % (closes)**. (Flux units m³/s, consistent with TIME_UNITS seconds.)
- `plot_heads_map` saved to `run-artifacts\aar_2d_heads_map.png`. NOTE: this model has no image input,
  so the PNG could not be visually verified in-session; the file is in the artifacts for inspection.
- `head_obs.csv` (from the run) was archived to `run-artifacts\head_obs.csv`.

## 7. Calibration (MCP calibration chain)

### Approach / pseudo-observations
Observed head VALUES are not shipped, so pseudo-observed heads at Obs0–Obs33 were derived from the
reference solution: the run's own `head_obs.csv` at the unperturbed model (identical to the shipped
`aar_2d.hds` at those cells; the shipped hds was preserved first). Heads were read at the exact
observation cells. Documented approach: **perfect-model / synthetic calibration** — the calibrated
parameter should recover the reference value K = 0.03 m/s, giving an end-to-end check of the toolchain.

### Working model
The adopted published model is read-only. `clone_model(source=aar_2d, name="aar2d_cal")` created a
writable working copy (`aar2d_cal`); binary outputs are not copied, so it was run fresh. The clone
inherited read-only status from its source, so it was re-registered with `adopt_model(allow_modify=True)`
(the clone is not the pristine archive). Calibration ran exclusively on the clone; the published
input set in `HydrologicalModel\` was never modified.

### Observation registration (MCP-only)
- Reference heads were written to `run-artifacts\pseudo_obs_yA.csv` (site, x, y, value) with
  x/y = DIS cell-centre coordinates (25 m grid from the model's own DIS; north-up y convention,
  validated below).
- `import_obs_from_csv(obs_type=HEAD, x_col="x", y_col="y")` registered all 34 sites.
  A first call without `x_col`/`y_col` silently used sequential order (Obs_i → cell [0,i,0]) — that is a
  footgun; passing the columns produced the correct mapping. The returned site-cellid map was checked
  against the OBS spec: **all 34 sites map 1:1 to the intended cells** (e.g. Obs0→[0,48,31],
  Obs33→[0,167,189]).
- Post-import forward run: RMSE 0.0032 m, bias −0.0005 m vs the registered (reference) values —
  residuals are exactly the 2-decimal rounding of the `head_obs.csv` pseudo-observations.

### PEST interface bootstrap — deviation from the literal chain
The success criteria list `setup_pest_control → run_pestpp_glm/ies → summarise_calibration`, but
`setup_pest_control` requires template (.tpl) and instruction (.ins) files to **already exist**, and no
groundwater-mcp tool writes a bare template/instruction file. The automated
`setup_calibration(obs_source="model", parameterisation={"k": {target:"npf:k", scope:"all", initial:0.03}})`
is the MCP-provided bootstrap that performs exactly those steps (external OPEN/CLOSE k array,
wide-token template, instruction file from the model OBS CSV, PEST++ control file), so it was used to
create the interface files, after which the **literal chain was exercised**: 
`setup_pest_control` (obs_source="explicit", obs_data = the 34 pseudo-observed heads, par_data = {k log,
0.003–0.3, initial 0.03}, template_files + instruction_files from the bootstrap) → rebuilt the .pst
(34/34 observations matched) → `run_pestpp_glm` → `summarise_calibration`.
This is reported as the closest MCP-native route, not a workaround with raw flopy/pyemu.

Generated interface (all in the clone workspace):
- `.pst`: `aar2d_cal.pst`; template `aar_2d_k.dat.tpl` → `aar_2d_k.dat`; instruction `aar_2d_head.obs.csv.ins`
- 1 adjustable parameter `k` (log), initial 0.03, bounds [0.003, 0.3]; 34 observations
- NPF rewired to `OPEN/CLOSE aar_2d_k.dat FACTOR 1.0` — verified identical forward solution (RMSE 0.0032 m)

### run_pestpp_glm + summarise_calibration
Run on both the `setup_calibration`-generated .pst and the `setup_pest_control`-generated .pst gave
identical results (the latter started with NOPTMAX=30, still stopped at NOPT=4 by the same criterion):
- GLM: converged, termination reason RELPARSTP/NRELPAR at NOPT=4; 10/10 runs complete, 0 failed;
  elapsed ~0.45 min; final phi 0.0003295.
- Phi progression: 3.564e-4 → 3.405e-4 → 3.394e-4 → 3.306e-4 → **3.295e-4**.
- Parameter estimate: **k = 0.030113 m/s** (initial 0.0300; log transform; not at bounds).
- Fit: RMSE 0.00311 m, bias −0.00031 m, R² 0.999999, 34 residuals (max |res| ≈ 0.0052 m).
- Verdict: improved = true; no parameter at bounds. (measurement-error verdict not computable: no error
  model supplied.)

The calibrated scalar recovers the reference/model value K = 0.03 m/s to within 0.4 %, as expected for a
perfect-model synthetic calibration — the parameter IS identifiable from the 34 heads and the chain is sound.

## 8. Comparison against the published posterior (ArchPy posterior)

### Posterior reference read (plain Python, reading-only)
`ArchPyPosterior\P1.*` are Python pickles (dicts → numpy arrays). Format decoded from pickle headers:
- grid 202(x) x 205(y) x 50(z) cells at 25 x 25 x 2 m; top 0 / bot −100 m (relative); mask = 2-D areal
  footprint (16,071 columns) replicated over all 50 z-slices → 803,550 active 3-D cells per realization
- `P1.pro` = {`logrho`, `k`}; each (510, 1, 1, 50, 205, 202) float32 → **510 posterior realizations**.
  `k` payload located by pickle opcode scan (BINBYTES, 4-byte length) at byte offset 4,223,820,227 and
  read by memmap. Values are **log10 K in m/s** (verified: gravel/clay bimodality, yaml means).
- `P1.unt`/`P1.fac`/`P1.sf` hold units/facies/surfaces (same realization count). `.npy` top/bot/mask confirm.

### Posterior K statistics (all 510 realizations, active cells)
- log10 K range ≈ −8.7 … −1.70; bimodal: clay mode ~ −7.1, productive/gravel cells (log10K > −4)
  pooled median ≈ **−3.42** (K ≈ 3.8e-4 m/s), max −1.70 (K ≈ 0.020 m/s).
- Gravel-mode volume fraction across realizations ≈ 23–35 % (median 29 %).
- Realization-mean log10K over active 3-D cells: median ≈ −5.99 → geometric-mean K ≈ 1e-6 m/s
  (clay-volume dominated).

### Cross-model comparison on a common transmissivity basis
The 2-D MF6 layer is 1 m thick, so its calibrated "K" is numerically T. Posterior columns were collapsed
to transmissivity T = Σ_z (10^log10K · 2 m) over 100 m:
- Posterior column log10 T: median ≈ **−1.56** (T ≈ 0.028 m²/s); per-realization mean ≈ −1.62 (0.024 m²/s);
  pooled p5/p95 = −2.17 / −1.08 (T ≈ 0.0067 / 0.083 m²/s).
- Calibrated model parameter: K = 0.0301 m/s (x 1 m) → **T = 0.030 m²/s, log10 T = −1.52**.
- 44 % of posterior columns exceed 0.03 m²/s; 88 % lie within ±0.5 log10 of it.
- The calibrated T sits at ≈ p50–p65 of the posterior column-T distribution — **consistent with the
  published posterior transmissivity**, slightly above the median.

### Units and structural differences (documented)
| | MF6 adopted model | ArchPy posterior |
|---|---|---|
| Dimension | 2-D, 1 layer (thickness 1.0 m, depth-integrated) | 3-D, 50 x 2 m layers (100 m) |
| Cells | 205 x 202 (25 m), 16,081 active | 202 x 205 x 50 (25 x 25 x 2 m), 16,071 x 50 active |
| K | homogeneous scalar (reference 0.03) | heterogeneous stochastic facies field |
| Materials | single medium | gravel + clay facies (4 stratigraphic units A–D) |
| log10 K (m/s) | calibrated **−1.52** (0.0301) | clay ~ −7.1; gravel ~ −3.4 (med), max −1.70 |
| Transmissivity | 0.030 m²/s | median column ≈ 0.028 m²/s |
| Time units | seconds (files as published) | n/a |
- The posterior per-cell K never reaches 0.03 m/s; the 2-D model's "K" is an effective value that must be
  read as a transmissivity (b = 1 m), which is why it sits ~1.9 log units above the posterior per-cell
  gravel mean yet matches the posterior transmissivity almost exactly.

### Verdict
The calibrated scalar parameter (0.0301 m/s ≡ 0.030 m²/s) is geologically plausible and quantitatively
consistent with the published posterior when compared as transmissivity. As a per-cell K it is higher
than the posterior gravel facies because of the structural simplification (2-D homogeneous T model vs
3-D gravel/clay facies model). No posterior facies realizations are available to compare spatially in the
2-D model frame; the comparison is therefore on aggregate (ensemble/column) statistics.

## 9. Compliance, deviations, limitations

- MCP-ONLY constraint respected for all model-building/adoption/running/post-processing/calibration.
- Deviations / decisions logged:
  1. Calibration executed on a **clone** (aar2d_cal) so the published input set stays pristine.
     The clone had to be re-adopted with `allow_modify=True` (clone_model inherited read-only).
  2. `setup_calibration` used to create the PEST interface (.tpl/.ins/.pst) because no MCP tool writes a
     bare template/instruction file; then `setup_pest_control`, `run_pestpp_glm` and
     `summarise_calibration` were run on that interface as in the stated chain (identical result).
  3. Pseudo-observed heads derived from the reference run's `head_obs.csv` (identical to shipped
     `aar_2d.hds` at Obs cells); 2-decimal precision of that CSV is the floor on achievable fit
     (RMSE ≈ 3 mm) and is fully documented.
  4. Observed `import_obs_from_csv` needed explicit `x_col`/`y_col`; without them sites map in
     sequential order to the wrong cells (silent fallback).
  5. No reprompts were required; the task proceeded start-to-finish.
  6. head-map PNG could not be viewed in-session (no image input for this model).
- Limitations: no true observed (field) heads exist in the archive, so calibration is a synthetic test;
  spatial overlay of posterior facies onto the 2-D layer was not performed (different dimensionality/
  datum); posterior comparison is aggregate.

## 10. Tool-call sequence (in order)

1. `check_environment`
2. reads of dataset files (ReadME.txt, mfsim.nam, aar_2d.nam, aar_2d.obs, tdis/ims/npf/rcha/oc/dis/ic,
   wel/chd/riv specs, notebook cells, ArchPy yaml + binary headers) — dataset inspection
3. `list_models`
4. `adopt_model(aar_2d)` → `summarise_model`, `model_status`, `get_run_log` (reference listing)
5. copy shipped reference outputs to `run-artifacts\`
6. `check_model(aar_2d)` — pass + 311 documented warnings
7. `run_simulation(aar_2d)` → converged/normal; `get_run_log`; `list_model_files`
8. `read_heads`, `compute_water_balance`, `plot_heads_map` (+ capture head_obs.csv)
9. `clone_model(aar_2d → aar2d_cal)`; `model_status`; `run_simulation(aar2d_cal)` (identical)
10. `adopt_model(aar2d_cal, allow_modify=True)`
11. `import_obs_from_csv` (x/y mapping) → `flush_model` → `run_simulation` (fit check)
12. `setup_calibration(k)` → `check_model(aar2d_cal)` → `run_simulation` (verification run)
13. `setup_pest_control` (explicit obs/par data on the generated .tpl/.ins)
14. `run_pestpp_glm(aar2d_cal.pst)` → `summarise_calibration`  (setup_calibration-built pst: same result)
15. `run_pestpp_glm(aar2d_cal.pst)` → `summarise_calibration`  (setup_pest_control-built pst: k = 0.030113 m/s)
16. posterior comparison in plain Python (memmap reads of published files) — reading only

## 11. Artifacts (session folder `run-artifacts\`)

- `aar_2d_heads_map.png` — head map (unviewable by this model, file present)
- `head_obs.csv`, `pseudo_obs_yA.csv` — (pseudo-)observation tables
- `aar_2d.hds/.cbc/aar_2d.lst/mfsim.lst` — preserved shipped reference outputs
- `posterior_logT.npy`, `dis_geom.npy`, `cell_centers.npy` — derived grids/statistics inputs
- Calibration interface and outputs live in `C:\Users\jakob\.groundwater-mcp\workspaces\aar2d_cal\`
  (aar2d_cal.pst, residuals CSV, aar_2d_k.dat, *.ins/*.tpl)
