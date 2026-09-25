# 6d Target 9 run-log — 1DSubsidenceModeling-MF6CSUB (site H201), closed-book

Date: 2026-09-24 · client: Kilo CLI (MCP server `groundwater-mcp`) · model: `csubH201`
Session work folder: `D:\Claude Projects\GW-MCP\csub-6d\` (holdout left untouched)

## 1. Environment (check_environment)
- Python 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`), Windows 10 19045
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8, whoosh 2.7.4
- binaries: mf6, pestpp-glm/ies/sen/opt/da at `C:\Users\jakob\.local\bin\`; `ready: true`, `missing: {packages: [], binaries: []}`

## 2. Data preparation (allowed — produces inputs, not the model)
1. Copied `H201/` + repo `dependencies/` (13.2 MB) into `csub-6d/`; **nothing written inside the holdout**.
2. Ran the repo's own `prep_data.py` (needed `PYTHONPATH=csub-6d` so `import dependencies.project_functions` resolved — the script's `sys.path.insert(0, os.path.join("..","dependencies"))` inserts the wrong root when run directly). Outputs: `processed_data/H201.model_property_data.csv` (2-layer property table) and `processed_data/H201.ts_data.csv` (daily interpolated dated groundwater levels).
3. `prep_mcp_inputs.py` (ordinary Python) reproduced `model_functions.initialize_model`'s TDIS/GHB/property logic exactly:
   - start 1904-01-01 (min of sub_data 1904-01-01 and ts_data); **nper = 158** (122 historic periods 1904→2024 from annual-mean GHB + 36 predictive periods 2025→2060 reusing the last head);
   - top 53.8, botm [-77.2, -1117.2], strt 53.8, k [10,10] ft/d, k33 [0.01,0.01], GHB cond 50000 ft²/d;
   - CSUB 11-field packagedata (0-based icsubno): `[0,(0,0,0),"nodelay",0,7.445037,5.909978,5e-05,2.5e-07,0.35,5e-05,0]`, `[1,(1,0,0),"delay",0,22.924098,24.035842,0.0005,2.5e-06,0.35,5e-05,0]`; sgm=[1.7,1.7] (sgs replicated as sgm — source quirk), cg_theta=[0.3,0.3], cg_ske_cr=[2.5e-07,2.5e-06], ndelaycells=19, beta=2.227e-08, gammaw=62.48.
   - `sse_cr`/`cg_ske_cr` resolved to 2.5e-07 / 2.5e-06 (the xlsx cells are those literal strings; a `to_string` render of the object column misleadingly showed `0.0`/`3e-6`). The processed CSV and the par_data both confirm 2.5e-07/2.5e-06.

## 3. Build through MCP only (tool-call sequence)
| # | Tool | Outcome |
|---|---|---|
| 1 | `check_environment` | stack ready (above) |
| 2 | `list_models` | no collision for `csubH201` (prior sessions hold `h201csub`, `h201sc1`) |
| 3 | `create_model(csubH201, FEET, DAYS, workspace csub-6d\model)` | stub created |
| 4 | `set_simulation(nper=158, perlen=[...], nstp=1×158, newton=true, start_date_time="1904-01-01", ims_complexity="simple", outer_maximum=300, linear_acceleration="bicgstab")` | TDIS+IMS written |
| 5 | `add_dis_package(2,1,1, delr=delc=1, top=53.8, botm=[-77.2,-1117.2])` | 2 cells |
| 6 | `add_npf_package(icelltype=1, k=[10,10], k33=[0.01,0.01], k_units="ft/d")` | units honoured (k stays 10 ft/d) |
| 7 | `add_ic_package(strt=53.8)` | — |
| 8 | `add_sto_package(iconvert=0, ss=0, steady_state=[0])` | per. 0 steady, 1–157 transient |
| 9 | `add_boundary_package(GHB, 158 periods, [{cell},head,50000])` | 2 records/period |
| 10 | `add_csub_package(packagedata=2 recs, ndelaycells=19, beta, gammaw, sgm, sgs, cg_theta, cg_ske_cr, head_based=false, initial_preconsolidation_head=true, specified_initial_interbed_state=true, update_material_properties=false, 16 obs, filerecords)` | 2 interbeds, 1 delay |
| 11 | `add_oc_package(head+budget SAVE ALL)` | — |
| 12 | `check_model` | **passed**; only the expected 2 STO `ss below 1e-06` warnings (ss=0, matches source) |
| 13 | `start_run` | **converged, Normal termination, 0.19 s**, 158/158 periods |
| 14 | `read_compaction` | per-layer compaction (L1 nodelay 8.26e-4 ft; L2 delay 8.355 ft) + cumulative `subsidence`; interbed strain table |
| 15 | `plot_subsidence(observed_csv=H201_sub_data.csv)` | PNG returned (prior fit) |
| 16 | `import_subsidence_observations(raw sub_data.csv)` | 208 dated observations registered |
| 17 | `setup_calibration(obs_source="derived", 6 params)` | **INVALID_INPUT** — no observed date matched a simulated time (raw survey dates never coincide with period ends) |
| 18 | `import_subsidence_observations(resampled)` | 158 observations on the model's period-end dates |
| 19 | `setup_calibration(obs_source="derived", 4 layer-1 params)` | PST + templates + instruction + forward wrapper generated; 158/158 matched |
| 20 | `start_calibration(ies, 8 reals)` | launched, then **stalled** (~1–5 min per forward launch) → cancelled |
| 21 | `start_calibration(ies, 8 reals)` | same stall (2 launches then ~16 min idle) → cancelled |
| 22 | `run_pestpp_ies(6 reals)` | client `-32001` timeout, but **completed server-side in 2.73 min, 389 forward runs** |
| 23 | `summarise_calibration` | φ 1119.56 → **15.68**, RMSE 0.315 ft, R² 0.925, bias +0.099, no bound-limited parameter |

MCP-only: all build/run/postprocess/calibration went through MCP tools. No flopy/pyemu MODFLOW/PEST classes were called directly; no MODFLOW/PEST file was hand-edited. Ordinary Python was used only for input preparation and analysis.

## 4. Reprompts / retries
1. **`setup_calibration` INVALID_INPUT** (step 17 → 18): the derived-observation matcher requires exact date equality; the raw dated subsidence survey has no date on a stress-period end. Fixed by data prep — resampling the measured series (linear interpolation) onto the 158 model period-end dates (`processed_data/H201_sub_data_resampled.csv`). Retry succeeded (158/158 matched).
2. Two `start_calibration` background jobs cancelled after the host launch stall (environment/known issue, not a tool-input reprompt).

## 5. Convergence evidence (uncorrected, prior parameters)
- `start_run`: `success: true`, `convergence: "converged"`, `returncode: 0`, listing ends `Normal termination of simulation`, 158/158 stress periods, 0.19 s.
- STO `ss=0` warnings in `check_model` are expected (the source sets ss=sy=0 and lets CSUB carry the storage).
- Prior fit vs the measured series: RMSE **3.00 ft**, bias **+1.69 ft**, max |res| 6.08 ft; simulated 8.45 ft at 2024 vs measured 2.89 ft and the repo's own calibrated `base` 2.99 ft — i.e. the prior over-predicts ~3×, as expected before calibration.

## 6. Calibration evidence
- Interface: `obs_source="derived"`, observation = sum of CSUB `COMPACTION.01+COMPACTION.02` per period (`csubh201_subsidence.csv`), 158 observations; 4 adjustable parameters, all on the delay (Middle) interbed: `ssv_ssv_cc_2`, `ssv_sse_cr_2` (`csub:packagedata`), `cgth` (`csub:cg_theta` L1), `cgske` (`csub:cg_ske_cr` L1); log-transformed, bounds = prior×0.05 / ×20.
- Engine: `pestpp-ies`, 389 forward runs, 2.73 min. φ (ensemble mean) per iteration: 1119.56 → 27.51 → 17.25 → 16.10 → 15.93 → 15.84 → 15.79 → 15.75 → 15.72 → 15.70 → **15.68** (−98.6 %; base realisation 1422.96 → 15.667).
- Parameter estimates (prior → posterior mean): `ssv_ssv_cc_2` 5.0e-4 → **1.415e-4** (×0.28); `ssv_sse_cr_2` 2.5e-6 → **1.512e-5** (×6.0); `cgth` 0.30 → **0.187**; `cgske` 2.5e-6 → **1.508e-5** (×6.0). **None at a bound.**
- Residuals (158): RMSE **0.315 ft**, bias **+0.099 ft**, R² **0.925** (prior RMSE 3.00 → 0.315, ~90 % reduction). Full table `model/csubH201_residuals.csv`.
- The elastic-storage recovery (sse_cr up) alongside the inelastic-storage reduction (ssv_cc down) reproduces the measured rebound segments the flat-inelastic prior could not.

## 7. Deviations from the source model (`model_functions.py`)
- **IMS**: source sets `complexity="simple"` + `inner_maximum=200` + `relaxation_factor=0.97`; `set_simulation` exposes only `ims_complexity`/`outer_maximum`/`linear_acceleration`, so IMS = SIMPLE + outer_maximum 300 + bicgstab (inner/relaxation left at the SIMPLE preset). Documented tool limitation.
- **Head observations**: the source also builds a separate head OBS package (HD.01/HD.02). No generic head-observation MCP tool exists; the CSUB model does not need them, so they were omitted.
- **Calibration observation dates**: the source calibrates on the raw dated subsidence survey; the MCP derived-observation matcher requires observed dates to equal simulated output dates, so the series was resampled to the period-end dates (linear interpolation). The predictive window 2025–2061 (no measurements) is assigned a flat pseudo-observation equal to the last measured value (2.89 ft); with constant predictive heads the simulated series is flat there, so these add no calibration information.
- **`sse_cr`/`cg_ske_cr`** = 2.5e-07/2.5e-06 (per par_data), not the 0.0/3e-06 an initial console render suggested.
- Everything else (start date, 158 periods, top/botm/strt, k/k33, GHB 50000 + exact heads, both interbeds, `sgs=sgm`, theta 0.35, ndelaycells 19, beta/gammaw) matches the source.

## 8. MCP findings (v0.3.0 backlog candidates)
1. **Background `start_calibration` launch stall — now isolated to the background runner, not the engine and not the MCP server process tree.** On this host the background IES job performed **2 forward launches then idled ~16 min** (and ~35–100 s gaps in an earlier 30-real job), each wrapper executing `mf6` in **0.2 s**. The **synchronous `run_pestpp_ies` on the identical PST ran 389 forward runs in 2.73 min** (~0.4 s/run) and completed the calibration. So the VS Code / process-tree diagnosis in the rerun-6 findings does not explain it: the synchronous MCP path is fast on the same tree. Highest-value fix: make `start_calibration` spawn forwards the way the synchronous runner does, and/or add a launch watchdog that fails fast when the wrapper trace shows no `mf6` launch within N seconds.
2. **Derived-observation matching is exact-date only** (no tolerance/nearest). The raw dated survey produced 0 matches; only after resampling to the model's output dates did the 158 observations bind. (Repeats the already-filed item.)
3. `setup_calibration` externalises targets/templates and writes the forward wrapper **before** it validates the derived-observation date match, so a failed call leaves partial artifacts (pristine `.npy`/`.dat`/`.tpl` present even though the call returned `INVALID_INPUT`).
4. `plot_subsidence` with `observed_csv=` plots the observed series against its **row index**, not the model time axis, so the overlay collapses to x≈0 and cannot be read as a fit (repeats the already-filed time-axis-convention item).
5. No MCP tool pushes the calibrated parameter values back into the model for a calibrated forward run/plot; the calibrated fit is available only as `summarise_calibration` residual statistics.

## 9. Outcome vs criteria
1. environment — **pass** · 2. copy + prep_data — **pass** · 3. MCP-only build + `check_model` + run — **pass** (converged, normal termination) · 4. `read_compaction` + `plot_subsidence` + comparison — **pass** · 5. derived obs → `setup_calibration` → IES → `summarise_calibration` — **pass** (φ −98.6 %, RMSE 0.315 ft, R² 0.925, no bound); completed via the **synchronous** `run_pestpp_ies` because the background job stalls · 6. run-log — this file.

**MCP-only violations: 0.** **Human reprompts: 1** (setup_calibration date-match → resample).
Total time: ~50 min.
