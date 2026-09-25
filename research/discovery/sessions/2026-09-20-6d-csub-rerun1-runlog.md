# Run log — Phase 6d target 9 (1DSubsidenceModeling-MF6CSUB, site H201)

Closed-book validation of the groundwater-mcp toolchain on a real 1D MODFLOW 6-CSUB
subsidence benchmark. Every action that builds, runs, post-processes or calibrates the
MF6 model was performed through groundwater-mcp tools only. The repo's `prep_data.py`
was run as data preparation and source CSVs were transformed in ordinary Python; the
repo's `model_functions.py` / `workflow.py` / `ies_functions.py` were **not** run.

- Source (read-only): `D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB`
  (github.com/leila-saberi/1DSubsidenceModeling-MF6CSUB, branch Multi-IB, commit ff5ef1d)
- Session folder (this run): `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-target9-csub-rerun1`
- Model name: `h201csub` (8 chars, <= 16)
- Model workspace: `<session>\mcp_h201_ws`

## 1. Environment (`check_environment`, first call)

`ready: true`, missing: none.
- Python 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`)
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8
- mf6, pestpp-glm, pestpp-ies, pestpp-sen, pestpp-opt, pestpp-da all present
- docs index built; default workspace root `C:\Users\jakob\.groundwater-mcp\workspaces`

## 2. Data preparation

1. Copied `H201\` and `dependencies\` (13.2 MB) from the holdout into the session folder
   (robocopy). Nothing in the holdout tree was modified.
2. Ran the repo's own `H201\prep_data.py` inside the session copy
   (`python H201\prep_data.py`, `PYTHONPATH=<session>` so `import dependencies.project_functions`
   resolves). Exit 0. Produced
   `H201\processed_data\H201.model_property_data.csv` and `H201.ts_data.csv`
   (+ `processed_gwlevels.pdf`).
   Confirmed the stated H201 facts: 2 layers, `cdelay = [nodelay, delay]`,
   Upper 131 ft / Middle 1040 ft.
3. `prep_mcp_inputs.py` (written by me, ordinary pandas only) reproduced the
   *input-generation* logic of `model_functions.initialize_model()` — yearly
   resampling of the processed gw-level series, the union date axis, perlen/nstp,
   and the period-by-period GHB head/conductance records — and dumped
   `mcp_inputs_meta.json` / `mcp_inputs_ghb.json`. No flopy/pyemu MODFLOW objects used.

Derived discretisation: `nper = 158`, `start_date_time = 1903-12-31`,
`perlen = [1, 366, 365, ... , 366]` (1 d initial period, then yearly to 2060-12-31),
`nstp = 1` for every period, `strt = 53.8`, 0 GHB below-bottom warnings.

## 3. Tool-call sequence (MCP only)

| # | Tool | Result |
|---|------|--------|
| 1 | `check_environment` | stack ready |
| 2 | `create_model` (h201csub, FEET/DAYS, ws=mcp_h201_ws) | created |
| 3 | `set_simulation` (nper=158, perlen, nstp, newton=true, ims_complexity=simple, outer_maximum=300, linear_acceleration=bicgstab, under_relaxation=simple, start_date_time=1903-12-31) | total_time 57346 d |
| 4 | `add_dis_package` (2x1x1, delr=delc=1, top=53.8, botm=[-77.2,-1117.2]) | 2 cells |
| 5 | `add_npf_package` (icelltype=1, k=[10,10], k33=[0.01,0.01], k_units=m/d) | written k = 10 (no conversion) |
| 6 | `add_ic_package` (strt=53.8) | ok |
| 7 | `add_sto_package` (iconvert=0, ss=0, sy=0, steady_state=[0]) | per 0 steady, 1–157 transient |
| 8 | `add_boundary_package` (GHB, 158 periods x 2 records, cond=50000) | 2 recs/period |
| 9 | `add_csub_package` (2 interbeds, ndelaycells=19, cg_theta=0.3, cg_ske_cr=[2.5e-7,2.5e-6], sgm=sgs=1.7, obs COMPACTION.01/.02) | n_delay_interbeds=1 |
| 10 | `add_oc_package` (HEAD ALL, BUDGET ALL, PRINT BUDGET ALL) | ok |
| 11 | `flush_model` | written |
| 12 | `check_model` | **timed out (3 attempts)** — see Notes |
| 13 | `run_simulation` | **timed out** |
| 14 | `start_run` + `get_job_status` | success, converged, 0.16 s |
| 15 | `read_compaction` | per-layer compaction + subsidence |
| 16 | `plot_subsidence` | PNG `mcp_h201_ws\gwmcp_e1ocifd2.png` |
| 17 | `import_subsidence_observations` (Date, Subsidence_ft) | 208 obs registered |
| 18 | `setup_calibration` (obs_source=derived; 3 packagedata columns + cg_theta) | 4 pars, 17 matched obs |
| 19 | `start_calibration` (ies, 50 reals) | ~100 s/realization, stalled after 4 runs — cancelled |
| 20 | `add_csub_package` (re-added, same spec) | repaired the model after the cancelled run |
| 21 | `start_run` + `get_job_status` | success, converged, 0.16 s |
| 22 | `setup_calibration` (noptmax=2) | 4 pars, 17 obs |
| 23 | `run_pestpp_ies` (num_reals=8, num_workers=8) | client timed out, PEST++ finished server-side in 1.43 min |
| 24 | `summarise_calibration` | phi 233.06 -> 14.49 -> 9.70; details below |

Reprompts / retries: 3 x `check_model` timeout, 2 x `run_simulation` timeout (switched to
`start_run`), 1 cancelled IES, 1 model repair, 2 x `setup_calibration` (the first was
invalidated by the cancelled run). No tool call was ever replaced by a raw flopy/pyemu call.

## 4. Model built (matches the repo's `model_functions.initialize_model`)

- DIS 2 layers x 1 row x 1 col, delr=delc=1, top=53.8, botm=[-77.2, -1117.2]
- NPF icelltype=1, k=10, k33=0.01 (both layers)
- IC strt=53.8 (= max interpolated gw level, as in the repo)
- STO iconvert=0, ss=0, sy=0; period 0 steady, 1–157 transient
- GHB cond=50000 on both layers, yearly processed heads 1903-12-31 -> 2060
- CSUB packagedata (0-based, 11 fields, `[icsubno, cellid, cdelay, pcs0, thick_frac, rnb, ssv_cc, sse_cr, theta, kv, h0]`):
  - ib 0: `[0, [0,0,0], nodelay, 0, 7.4450367, 5.9099776, 5e-05, 2.5e-07, 0.35, 5e-05, 0]`
  - ib 1: `[1, [1,0,0], delay,   0, 22.9240984, 24.0358417, 5e-04, 2.5e-06, 0.35, 5e-05, 0]`
  - `head_based=false`, `initial_preconsolidation_head=true`, `specified_initial_interbed_state=true`, `ndelaycells=19`
  - `cg_theta=[0.3,0.3]`, `cg_ske_cr=[2.5e-07,2.5e-06]`, `sgm=sgs=1.7`

## 5. Convergence evidence

- Listing: `Normal termination of simulation`, `Elapsed run time: 0.103 Seconds` (start_run: 0.105 s).
- All 158 stress periods solved (`Stress period: 158  Time step: 1`).
- No `WARNING`/`ERROR` lines in `h201csub.lst`; `diagnose_convergence` not needed.
- CSUB interbed strain output: interbed 1 (nodelay) total compaction 7.4e-4 ft;
  interbed 2 (delay) total compaction 8.328 ft, strain 1.51 %.

## 6. Post-processing vs the site's measured subsidence

Prior (uncalibrated) model:
- total cumulative subsidence at 2024-08-06 = **8.35 ft** vs measured **2.89 ft**
- against all 208 measured points: RMSE 3.9637 ft, bias +2.9706 ft, MAE 2.9851 ft
- against the 17 calibration dates: RMSE 4.0891 ft, bias +3.1176 ft (table in `prior_obs_vs_sim.csv`)
- the repo's own *calibrated* base model reaches 3.333 ft at 2061 (H201\output\
  SimulatedSubsidence_H201.csv), i.e. the prior is ~2.5x the calibrated benchmark.

## 7. Calibration (`import_subsidence_observations` -> `setup_calibration` -> `run_pestpp_ies` -> `summarise_calibration`)

Registered derived observation: `H201_sub_data.csv`, `time_col=Date`, `value_col=Subsidence_ft`,
recipe `h201csub.csub.obs.csv` summing the `compaction` columns.

Parameterisation: `csub:packagedata` columns `ssv_cc`, `sse_cr`, `kv` on the delay interbed
(layer index 1) + `csub:cg_theta` (layer 1). 4 adjustable parameters, all log-transformed,
default bounds (0.05x–20x).

Phi progress (IES, 8 realizations, 8 workers, 1.43 min): **233.057 -> 14.4937 -> 9.69558**;
base run phi 11.149 -> 9.410.

Parameter estimates (posterior ensemble mean) vs prior:

| parameter | prior | posterior mean | ratio prior/posterior |
|---|---|---|---|
| cgt (cg_theta, layer 2) | 0.30 | 0.3580 | 0.84 |
| sse_ssv_cc_2 | 5.0e-04 | 1.6904e-04 | 2.96 |
| sse_sse_cr_2 | 2.5e-06 | 1.5644e-06 | 1.60 |
| sse_kv_2 | 5.0e-05 | 2.3667e-05 | 2.11 |

None at bounds. `verdict.improved = true`; `fit_within_measurement_error = false`
(measurement_error 0.1 ft vs RMSE 0.744 ft).

Residual statistics (17 matched observations): RMSE **0.744 ft** (was 4.089 ft), bias
+0.427 ft. Residual pattern: 2005–2011 under-predicted by ~0.8–1.5 ft, 2013–2024 fitted
to <0.2 ft. Full table: `mcp_h201_ws\h201csub_residuals.csv`.
For reference the repo's own calibrated (ib_results) Middle-layer values are
SSE 2.30e-06, SSV 2.57e-04, KV 1.18e-07; our posterior moved in the same direction
(lower SSV, lower SSE, lower KV) but KV stayed ~200x higher because the MCP default
parameter bounds (0.05x–20x) cannot reach a 425x reduction.

## 8. Deviations from the repo's `model_functions.py` build

1. **CSUB BETA / GAMMAW cannot be set.** The repo passes `beta=2.2270e-8, gammaw=62.48`
   (FEET/DAYS units). `add_csub_package` exposes no such arguments, so Flopy/MF6 defaults
   `BETA 4.6512E-10`, `GAMMAW 9806.65` were written. This is a genuine tool-coverage gap.
   Empirically the prior compaction magnitude (~8.3 ft) is consistent with the repo's
   FEET-unit benchmark (repo calibrated base 3.33 ft, observed 2.89 ft) and not with the
   ~157x inflation a naive SI-default gamma_w would give, so MF6 evidently uses the
   head-based formulation here; the parameter-level effect is nevertheless unverified.
2. **IMS controls.** Repo: `complexity=simple, outer_maximum=300, inner_maximum=200,
   outer_dvclose=1e-3, inner_dvclose=1e-3, relaxation_factor=0.97, bicgstab`. MCP exposes
   only complexity/outer_maximum/linear_acceleration/under_relaxation, so inner_maximum and
   both dvclose values fell back to MF6 defaults for SIMPLE. Convergence was still clean.
3. **sgs.** The repo passes `sgs=prop_df.loc["sgm"]` (i.e. 1.7) for both arrays; the processed
   property table itself contains `sgs = 2.0`. I reproduced the repo's behaviour (1.7).
4. **OC budget CSV.** Repo also writes `budgetcsv_filerecord="budget.csv"`; not exposed by
   `add_oc_package`.
5. **No `clean_model` hack.** The repo rewrites the CSUB OBS file name by hand (a Flopy naming
   workaround). The MCP wrote a normal `OBS6 FILEIN h201csub.csub.obs`, so no fix was needed.
6. **Derived-observation date matching.** The derived-obs recipe matches observed dates to
   simulated output dates exactly, so only **17 of 208** measured points (the Jan-1 dates that
   coincide with the yearly stress-period ends) entered the calibration. The monthly
   2004–2024 InSAR series and the pre-2000 levelling data are dropped. This is the single
   largest limitation of the automated chain and the main reason the posterior cannot fully
   reproduce the measured mid-2000s ramp.

## 9. Toolchain observations (actionable)

- `check_model` could not complete within the MCP client timeout on this model (3/3 attempts),
  while the server stayed responsive to cheap calls. Model validity was confirmed by MF6
  `Normal termination` instead.
- Blocking calls (`run_simulation`, `run_pestpp_ies`) exceed the client timeout even though
  `start_run` reports 0.16 s of mf6 runtime; the background job API (`start_run`,
  `start_calibration`, `get_job_status`) is the reliable path.
- `start_calibration` runs PEST++ serially and was ~100 s per realization (foreground trace:
  each `mf6` invocation is 0.2–0.7 s — the cost is between runs, not the model). With
  `num_workers=8` the same IES finished in 1.43 min. `start_calibration` exposes no
  `num_workers`, so the fast path is only reachable through the blocking `run_pestpp_ies`.
- **Cancelling a calibration leaves the model unloadable.** `setup_calibration` rewires CSUB
  to `h201csub.csub_packagedata.dat` / `h201csub.csub_cg_theta.dat`, which PEST++ creates only
  during a run. After `cancel_job`, `run_simulation` and a repeat `setup_calibration` both fail
  with `Unable to open file ... csub_cg_theta.dat`. It was repaired by re-calling
  `add_csub_package` (the in-memory model is still cached; `reloaded_from_disk: false`), but a
  restore/cleanup path would be preferable.
- `describe_package` does not know CSUB (known set excludes it), and
  `search_docs` returned nothing useful for the GAMMAW/BETA unit question.

## 10. Artefacts

- `H201\processed_data\` — prep_data.py outputs
- `mcp_inputs_meta.json`, `mcp_inputs_ghb.json` — prepared discretisation + GHB series
- `prep_mcp_inputs.py`, `compare_subsidence.py` — data prep / analysis only
- `prior_obs_vs_sim.csv` — prior sim vs measured subsidence, all 208 points
- `mcp_h201_ws\` — MF6 model, listing, CSUB obs/compaction/strain outputs, PST, PHI files,
  `h201csub_residuals.csv`
- `mcp_h201_ws\gwmcp_e1ocifd2.png` — `plot_subsidence` prior simulated vs observed
- `mcp_h201_ws\h201csub_compaction.csv` — `read_compaction` series

## 11. Verdict

The MCP toolchain built, ran, post-processed and calibrated a real 1D CSUB benchmark
end-to-end without any raw flopy/pyemu model work. Prior RMSE against the measured
subsidence was 4.09 ft on the calibration dates; IES reduced phi by 96 % (233.1 -> 9.70)
and RMSE to 0.744 ft with no parameter at bounds. Two capability gaps were hit that affect
fidelity rather than feasibility: CSUB `BETA`/`GAMMAW` are not settable, and derived-obs
matching only pairs exact dates (17/208). Robustness gaps: `check_model`/blocking-call
timeouts, no `num_workers` on the background calibration path, and no cleanup/restore after
a cancelled calibration.
