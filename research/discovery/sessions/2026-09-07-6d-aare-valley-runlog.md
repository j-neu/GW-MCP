# Phase 6d — Target 3 (Aare Valley): Closed-Book MCP Validation Run Log

**Date:** 2026-09-07
**Session folder:** `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-aare-valley`
**Model:** MODFLOW 6 `aar_2d` — Aare Valley (Neven & Renard 2023, WRR; Zenodo 8047723; CC BY 4.0)
**Rule observed:** every action that builds/adopts/runs/post-processes/calibrates the MF6 model went
through a `groundwater-mcp` tool. No flopy/pyemu model-building, and no hand-editing of MODFLOW/PEST files.
Ordinary Python (numpy/pandas) was used **only** to (a) build the pseudo-observation CSV from an MCP-exported
reference-head `.npy`, and (b) read the published ArchPy posterior pickles (a reference dataset, not a model build).

---

## 1. Environment (check_environment)

- Python 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`), Windows 10, x64.
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8.
- Binaries: `mf6.exe`, `pestpp-glm.exe`, `pestpp-ies.exe`, `pestpp-sen.exe`, `pestpp-opt.exe`, `pestpp-da.exe`
  (all present, `C:\Users\jakob\.local\bin`). Docs index built. `ready: true`.
- MF6 runtime banner during runs: **MODFLOW 6 v6.7.0 (02/05/2026 build)** — newer than the flopy 3.3.4
  (2022) that wrote the files; deterministic steady state reproduces bit-identical heads.

## 2. Archive layout and model identification

```
exportPaper/
  HydrologicalModel/    mfsim.nam + aar_2d.{dis,dis.grb,ic,ims,npf,obs,oc,rcha,tdis,nam} + Aar.riv, Gurbe.riv,
                        lake.chd, wel.wel  (RCH/WEL/CHD/RIV BCs), solved aar_2d.hds/.cbc/.lst + mfsim.lst
                        ("Normal termination of simulation" shipped)
  ArchPyPrior/          P1.{yaml,top,bot,msk}.npy, P1.fd/.lbh/.ud/.sf/.sfb
  ArchPyPosterior/      + P1.fac (4.2 GB), P1.pro (8.4 GB), P1.unt (4.2 GB)  — 510 posterior realizations
  LoadAndPlotArchpy.ipynb, ReadME.txt, environment.yml
```

Single GWF model `aar_2d` (mfsim.nam). Grid: DIS 1 layer × 205 rows × 202 cols, `delr=delc=25 m`,
top/botm ≈ 500–580 m, XORIGIN/YORIGIN (2 602 669.91, 1 192 202.67) (LV95-style). **Steady state**,
`TIME_UNITS seconds`, NPER=1 (perlen 1, nstp 1), no STO package. IMS `moderate`.
Packages (aar_2d.nam): DIS6, IC6, NPF6, RCH6 (`aar_2d.rcha`), WEL6 (`wel.wel`), OC6, OBS6 (`aar_2d.obs`,
34 HEAD obs Obs0–Obs33 → `head_obs.csv`), CHD6 (`lake.chd`), and **two RIV6 packages**: `Aar.riv` (aar) and
`Gurbe.riv` (gurbe). All list BCs carry `SAVE_FLOWS`.
NPF: `icelltype=0` (confined), `k CONSTANT 0.03` (**m/s** — the paper's SI convention; the whole file set is m/s, s, m).
RCH rate 1.782e-8 m/s; WEL −0.283333 m³/s at (1,17,32); lake CHD + RIV stage/cond/bottom records.

## 3. Tool-call sequence, decisions, and deviations

| # | Tool / action | Result | Notes |
|---|---------------|--------|-------|
| 1 | `check_environment` | ready | stack above |
| 2 | inspect layout / model files | MF6 model identified | dataset files only |
| 3 | `adopt_model(name="aar_2d", workspace=<HydrologicalModel>, units=METERS, time_units=SECONDS)` | adopted, read-only | honours "point the workspace at the HydrologicalModel directory"; no files rewritten, nothing renamed |
| 4 | `summarise_model` | 1×205×202, 16 081 active, packages incl. AAR/GURBE, no STO | |
| 5 | `check_model` (pristine) | **check_passed, 0 errors**; 311 warnings | all "BC in inactive cell" (153 Aar.riv, 115 Gurbe.riv, 42 lake.chd, 1 wel) — **shipped as-is** in the published files; documented, not altered |
| 6 | `read_heads(kstpkper=[0,0], layer=0)` on shipped `aar_2d.hds` | min 501.278 / max 516.000 / mean 510.503 m | reference heads extracted **before any run** could overwrite the shipped outputs; wrote `aar_2d_heads_l0_k0_0.npy` into the HydrologicalModel dir |
| 7 | `clone_model(source=aar_2d, name=aar_cal)` | clone at `C:\Users\jakob\.groundwater-mcp\workspaces\aar_cal` | keeps the published archive pristine for running/calibration |
| 8 | `check_model` on clone | identical to #5 | |
| 9 | `run_simulation(aar_cal)` | success, converged, **normal termination**, 0.92 s wall (0.34 s MF6) | 4 outer iters; max change −16.97 → −0.563 → −0.041 → −4.8e-3 (*accepted*) |
| 10 | `get_run_log` | convergence evidence | see §4 |
| 11 | `read_heads` (clone) | **identical** to shipped reference stats | deterministic reproduction of the published solution |
| 12 | `compute_water_balance` | closes | see §5 |
| 13 | `plot_heads_map` → `heads_map.png` | written | **image could not be visually inspected**: this model has no image input support; file (154 KB) is in the workspace |
| 14 | `import_obs_from_csv` (pseudo-obs) | refused `MODEL_ADOPTED_READONLY` | `clone_model` registers adopt-style **read-only** models |
| — | **Decision** | re-register clone writable | `delete_model(aar_cal, remove_files=false)` then `adopt_model(name="aar_cal", workspace=<clone dir>, allow_modify=True)`; pristine published dir still untouched |
| 15 | `import_obs_from_csv` | 34 sites → cells exactly matching shipped OBS6 cellids | obs registry + replacement OBS6 package writing `aar_2d_head.obs.csv` |
| 16 | `setup_calibration(parameterisation={k: npf:k, scope all, initial 0.03})` | pst + template + instruction file + rewired NPF k to external array `aar_2d_k.dat` | 1 adjustable log-K parameter, bounds [0.003, 0.3]; 34 observations; model cmd = mf6.exe |
| 17 | `run_simulation` (rewired model) | normal termination; obs fit RMSE 2.2e-8 m | external-array NPF runs; `aar_2d_head.obs.csv` name matches instruction file |
| 18 | `run_pestpp_glm` | converged, final φ 1.49e-14, 4 iters, 10 runs / 0 failed | termination PHIREDSTP; k estimate 0.0300000002 (unchanged) |
| 19 | `summarise_calibration(measurement_error=0.05 m)` | see §6 | |
| 20 | `check_parameter_sensitivity` | k sensitivity ≈ 1.5e-5 | heads are boundary-dominated; K weakly identified |
| 21 | plain-python posterior read | `posterior_k_stats.json`, `posterior_facies_split.json` | reading the published ArchPy reference |

### Deviations / decisions
1. **No in-place mutation of the published model.** Adopted read-only at `HydrologicalModel`, ran/calibrated on
   a clone. The one file added by the MCP to the published folder is `aar_2d_heads_l0_k0_0.npy` (reference layer
   exported by `read_heads`); no published input file was modified or deleted.
2. **Clone models are read-only in the registry.** Calibration requires writes (obs registration, NPF rewire), so
   the clone was re-adopted with `allow_modify=True` (MCP's own suggested remedy).
3. **Observed head values are not shipped** → pseudo-observed heads were derived at the 34 Obs cells from the
   **shipped reference `aar_2d.hds`** (extracted via MCP `read_heads`), sampled at the exact OBS6 cellids from
   `aar_2d.obs` (1-based → 0-based). Values (e.g. Obs0 = 506.478, Obs33 = 515.746 m) agree with the model's own
   `head_obs.csv` to the printed digits.
4. **Heads-map figure** could not be eyeballed (no image input for this model) — reported as generated file only.
5. **Posterior comparison** used the published ArchPy pickles directly (dataset-native format; ArchPy/geoarchpy is a
   py3.11-only stack and unavailable here), with `P1.msk.npy` masking.

## 4. Convergence evidence (get_run_log tail, mfsim.lst)

```
Solving:  Stress period 1, Time step 1
SLN_1 OUTER ITERATION SUMMARY
Model   1  18 iters  -16.9662         1_GWF-(1,152,169)
Model   2  10 iters   -0.56298        1_GWF-(1,165,127)
Model   3   3 iters   -4.09e-02       1_GWF-(1,151,149)
Model   4   1 iters   -4.79e-03  *    1_GWF-(1,172,107)
4 CALLS TO NUMERICAL SOLUTION ... 32 TOTAL ITERATIONS
Run end date ... 17:12:15   Elapsed run time: 0.343 Seconds
Normal termination of simulation.
```

Shipped listing (`HydrologicalModel/mfsim.lst`) also states normal termination. Re-run heads are **bit-identical**
to the shipped reference (min/max/mean match to all shown digits) → the MCP-run model reproduces the published
solution.

## 5. Post-processing

- **read_heads (layer 0, sp 1):** min 501.2780, max 516.0003, mean 510.5035 m over 16 081 active cells
  (identical for shipped and re-run `aar_2d.hds`).
- **compute_water_balance (kstpkper 0,0):**
  | term | inflow | outflow |
  |---|---|---|
  | RIV (Aar+Gurbe) | +0.8131 | −1.1076 |
  | CHD (lake) | +0.4011 | −0.0033 |
  | RCHA | +0.1782 | — |
  | WEL | — | −0.2833 |
  | **TOTAL** | **+1.3923** | **−1.3943** |
  net = −0.0019 m³/s → **closes** (≈ −0.14 % of mean throughput). Rivers are net-losing; lake CHD is the main
  inflow; well −0.283 m³/s. All BC packages carry SAVE_FLOWS so the budget is complete.
- **plot_heads_map:** `C:\Users\jakob\.groundwater-mcp\workspaces\aar_cal\heads_map.png` (not visually verified,
  see deviation 4).

## 6. Calibration (MCP chain against the 34 shipped obs points)

Chain used: `import_obs_from_csv` → `setup_calibration` (obs_source="model") → `run_pestpp_glm` →
`summarise_calibration`. (setup_pest_control is the manual twin; the automated setup_calibration is the
intended path once obs are registered from the model.)

- Parameter: **k** — single uniform log10 K over all active cells (NPF rewired to external array `aar_2d_k.dat`).
  Initial 0.03 m/s (= shipped value), log transform, bounds [0.003, 0.3] m/s.
- Observations: 34 pseudo-head targets Obs0–Obs33 (values = shipped reference heads; weight 1; see deviation 3).
- GLM: **converged**, termination PHIREDSTP (φ unchanged over 3 iterations), φ_final = 1.49e-14, 4 iterations,
  10 forward runs, 0 failed, ~19 s.
- Estimate: **k = 0.0300000002 m/s** (log10 k = −1.523). No parameter at bounds.
- Residuals: RMSE 2.1e-8 m, bias −6e-9 m, R² = 1.0, all |residual| < 5e-8 m; fit within the assumed 0.05 m
  measurement error. `aar_cal_residuals.csv` written.

**Interpretation / caveats (documented, not hidden):**
- The pseudo-observations were generated by the model itself (shipped reference solution of the uniform-0.03 model),
  so the "perfect" fit (φ ≈ 0) and the unchanged k are expected — the run is a **closed-loop self-calibration**
  that verifies the chain executes end-to-end, not an independent test of parameter identifiability.
- A sensitivity screen (`check_parameter_sensitivity`, Δ=10 %) gives k sensitivity ≈ **1.5e-5** (mean relative
  head change per relative K change). The steady-state head field is pinned by the lake CHD and river stages, so
  these 34 heads carry almost no information about a uniform K — the calibrated value is therefore dominated by the
  prior/initial (0.03 m/s) and should not be read as a data-derived effective conductivity.

## 7. Comparison of calibrated K with the published ArchPy posterior

**Posterior object read** (`ArchPyPosterior/P1.yaml`, `P1.pro`, `P1.msk.npy`): ArchPy grid 202×205×50
(2 m vertical, 25 m horizontal — the **same 25 m / 202×205 raster** as the MF6 grid; valley mask ~16 071
cells/layer on average vs MF6 16 081 active). 510 stored realizations of **log10 K (m/s)**; facies Gravel (log10K mean −2.0)
and Clay (mean −7.0), within-facies SGS, variogram ranges 200/200/20 m; one pile P1, units A–D.

Masked statistics over the ensemble (all 510 members × masked cells):
| quantity | value |
|---|---|
| domain mean log10 K | −5.99 (±1.86) |
| K geometric mean | 1.0e-6 m/s |
| K arithmetic mean (volume-weighted, ~ effective T/b proxy) | 3.3e-4 m/s |
| shallow top-50 m mean log10 K | −5.61 (K_geo 2.5e-6 m/s) |
| gravel (log10K > −3.5) volume fraction | 16.2 % (per-realization σ 1.5 %) |
| gravel mean log10 K | −2.91 (K_geo ≈ 1.2e-3 m/s) |
| clay mean log10 K | −6.59 (K_geo ≈ 2.6e-7 m/s) |
| per-realization mean log10 K | −6.0 ± 0.1 (range −6.2 … −5.7) |

**vs calibrated MF6 uniform k = 0.03 m/s (log10 k = −1.52):**

- The calibrated MF6 value sits ~1.4 orders of magnitude above the **gravel** end-member (posterior log-mean −2.9)
  and ~4.5 orders above the posterior **volume-weighted geometric mean**. It does not represent the posterior's
  central K; it is essentially the synthetic "truth" value (0.03 m/s) used to generate the observed heads in the
  published forward model, recovered by the self-calibration.
- **Units:** both datasets are K in **m/s** (MF6 NPF `k CONSTANT 0.03` m/s with TIME_UNITS seconds; ArchPy
  property `k` = log10(K m/s), means −2/−7). No conversion ambiguity; note the notebook colorbar label
  "K log10[m²/s²]" is a typo for m/s.
- **Structural differences (why a direct match is not expected):**
  1. **Dimensionality/geometry:** MF6 is a **single confined layer** (1×205×202) representing an effective
     2-D aquifer; ArchPy posterior is **3-D, 50×2 m layers over 100 m** of Quaternary fill with clay/gravel
     unit architecture (channelised gravel bodies in clay).
  2. **K structure:** MF6 K is **uniform** (single scalar); posterior K is **heterogeneous, bimodal**
     (gravel ~1e-2–2e-2 m/s vs clay ~1e-7 m/s), spatially correlated (r ≈ 200 m), with the clay-dominated
     volume lowering the volumetric mean.
  3. **Role in the experiment:** the MF6 model is the *synthetic forward model* used to generate the 34
     "observed" heads (uniform K 0.03 m/s); the ArchPy posterior is the *stochastic geology* conditioned on
     geophysical (ERT) + hydrogeological data. The two are different model classes of the same site, not two
     estimates of the same scalar.
  4. Grid raster (25 m, 202×205) and valley footprint match; coordinate origins are expressed in different
     projected CRSs (MF6 DIS ≈ LV95-style 2.60M/1.19M; ArchPy origin 383 703 / 5 193 064 ≈ UTM-32N-style), so
     cell-wise overlay would require reprojection. Comparison here is therefore statistical (masked log-K
     distributions), which is appropriate given the model-class difference.

## 8. Capabilities exercised / gaps found

Everything required by the success criteria was achievable **through groundwater-mcp tools alone**:
adopt (incl. read-only + allow_modify), clone, check, run, run-log verify, read heads, water balance,
heads map, obs import, automated PEST setup, GLM run, calibration summary, sensitivity screen.
No capability gap forced a raw-flopy/pyemu workaround.

Minor observations (not blockers):
- `clone_model` yields a read-only registry entry; a writable working model needed the documented
  delete→re-adopt(`allow_modify=True`) dance.
- `read_heads` wrote its `.npy` under the **model workspace** with an auto-generated name, ignoring the
  requested absolute `output_file` path.
- `plot_heads_map` returns a PNG; no visual QA possible in this text-only session.
- Posterior reading required plain Python (dataset pickle format); ArchPy itself is not installable in the
  provided py3.12 env (its stack pins py3.11). This is reference reading, not model work, so it does not violate
  the MCP-only constraint.

## 9. Artifacts

- `C:\Users\jakob\.groundwater-mcp\workspaces\aar_cal\` — clone, run outputs (`aar_2d.hds/.cbc`, `mfsim.lst`,
  `head_obs.csv`, `aar_2d_head.obs.csv`), `heads_map.png`, calibration (`aar_cal.pst`, `aar_2d_k.dat[.tpl]`,
  `aar_2d_head.obs.csv.ins`, `aar_cal_residuals.csv`), re-adopted working model.
- Published folder now also holds `aar_2d_heads_l0_k0_0.npy` (MCP reference-head export; no published input modified).
- Session folder (`6d-aare-valley`): `run-log.md`, `make_pseudo_obs.py`, `pseudo_obs_head.csv`,
  `read_posterior_k.py`, `posterior_k_stats.json`, `posterior_facies_split.py`, `posterior_facies_split.json`.

## 10. Verdict against success criteria

1. `check_environment` first and stack reported — **done** (§1).
2. Archive inspected, MF6 model identified and **adopted** (`aar_2d`) from `HydrologicalModel/`, no rebuild/no
   renames — **done**.
3. `check_model` clean (0 errors; 311 shipped "BC in inactive cell" warnings documented) — **done**.
4. `run_simulation` **normal termination / converged** (~1 s), verified via `get_run_log` — **done**.
5. `read_heads`, `compute_water_balance` (closes, −0.14 %), `plot_heads_map` — **done**.
6. Calibration chain run against the 34 obs (pseudo-obs derived from shipped `aar_2d.hds`, documented) and
   compared with the ArchPy posterior incl. units and structural differences — **done**.
7. This `run-log.md` — **done**.
