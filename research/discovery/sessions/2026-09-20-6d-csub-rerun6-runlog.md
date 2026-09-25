# Run log — Phase 6d target 9, H201 (1DSubsidenceModeling-MF6CSUB, MODFLOW 6 CSUB)

Closed-book validation run (rerun-6). MCP-only build; the H201 source folder and the repo's
`dependencies\` tree were copied into this session folder and never run inside the holdout.

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-target9-csub-rerun6\csub_h201\`
Holdout (read-only, untouched): `D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB\`

---

## 1. Environment (`check_environment`, first call)

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| numpy / scipy / pandas | 2.4.4 / 1.17.1 / 2.x |
| geopandas / rasterio / matplotlib | 1.1.3 / 1.5.0 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` (6.7.0 02/05/2026) |
| pestpp-glm / ies / sen / opt / da | all present in `C:\Users\jakob\.local\bin` |
| docs index | built, `C:\Users\jakob\.groundwater-mcp\index` |
| ready | true |

## 2. Data preparation (allowed: produces inputs, not the model)

1. Copied `H201\` and `dependencies\` from the holdout into `csub_h201\` (holdout unchanged).
2. Ran the repo's own `prep_data.py` **in the copy** (`H201\`, with `PYTHONPATH=csub_h201`).
   Output: `H201\processed_data\H201.model_property_data.csv`, `H201.ts_data.csv`,
   `processed_gwlevels.pdf`.
3. `make_payloads.py` (ordinary Python, no flopy/pyemu) reproduces the TDIS/GHB/CSUB logic of the
   repo's `model_functions.initialize_model` and writes `prep_inputs.json` — the literal payloads
   handed to the MCP build tools.

Processed property table used (from the repo's own prep):

| property | layer 0 (Upper) | layer 1 (Middle) |
|---|---|---|
| top / botm | 53.8 / -77.2 | 53.8 / -1117.2 |
| k / k33 | 10.0 / 0.01 | 10.0 / 0.01 |
| cdelay | nodelay | delay |
| pcs0 (passed) | 0.0 | 0.0 |
| thick_frac | 7.4450367 | 22.9240984 |
| rnb | 5.9099776 | 24.0358417 |
| ssv_cc | 5e-05 | 5e-04 |
| sse_cr | 2.5e-07 | 2.5e-06 |
| theta | 0.35 | 0.35 |
| kv | 5e-05 | 5e-05 |
| cg_theta | 0.3 | 0.3 |
| cg_ske_cr | 2.5e-07 | 2.5e-06 |
| sgm (sgs) | 1.7 (1.7) | 1.7 (1.7) |

Derived from the dated groundwater-level series (`ts_data.csv`): 122 historic annual stress periods
(1903-12-31 → 2024-12-31) + 36 constant-head predictive periods to 2060 = **158 periods**, GHB
conductance 50000 ft²/d on both layers, GHB heads = the layer-wise annual mean of the
time-interpolated observation series.

## 3. Model build — MCP tool calls only

Model `h201csub`, workspace `csub_h201\model_ws`, FEET/DAYS.

| # | tool call (arguments summarised) |
|---|---|
| 1 | `create_model(name=h201csub, units=FEET, time_units=DAYS, workspace=…\csub_h201\model_ws)` |
| 2 | `set_simulation(nper=158, perlen=[1,366,365,365,365,…], nstp=[1]×158, start_date_time=1903-12-31, newton=true, ims_complexity=moderate, outer_maximum=300, linear_acceleration=bicgstab)` |
| 3 | `add_dis_package(nlay=2, nrow=1, ncol=1, delr=1, delc=1, top=53.8, botm=[-77.2,-1117.2])` |
| 4 | `add_npf_package(icelltype=1, k=[10,10], k33=[0.01,0.01], k_units="ft/d")` |
| 5 | `add_ic_package(strt=53.8)` |
| 6 | `add_sto_package(iconvert=0, ss=0, sy=0, steady_state=[0])` |
| 7 | `add_boundary_package(package=GHB, stress_period_data={0..157: [[lay,0,0], head, 50000]})` — 2 records × 158 periods |
| 8 | `add_csub_package(packagedata=[[0,[0,0,0],"nodelay",0,7.4450,5.90998,5e-5,2.5e-7,0.35,5e-5,0],[1,[1,0,0],"delay",0,22.9241,24.0358,5e-4,2.5e-6,0.35,5e-5,0]], ndelaycells=19, cg_theta=[0.3,0.3], cg_ske_cr=[2.5e-7,2.5e-6], sgm=[1.7,1.7], sgs=[1.7,1.7], head_based=false, initial_preconsolidation_head=true, specified_initial_interbed_state=true, update_material_properties=false, observations={"h201csub.csub.obs.csv": compaction.01/02 (cell), delay-head.02.00/.09/.18, delay-preconstress.02.00/.09/.18})` |
| 9 | `add_oc_package(saverecord=[["HEAD","ALL"],["BUDGET","ALL"]])` |
| 10 | `check_model()` → `check_passed=true`, 2 benign warnings (`sto package: specific storage values below checker threshold of 1e-06`, i.e. the source model's ss=0 storage). |
| 11 | `start_run()` → succeeded, converged, 0.16 s, "Normal termination of simulation." |

Verified against the source build by reading the generated `h201csub.csub`:
`GAMMAW 62.48000000`, `BETA 2.22700000E-08`, `INITIAL_PRECONSOLIDATION_HEAD`,
`SPECIFIED_INITIAL_INTERBED_STATE`, `NDELAYCELLS 19`, NINTERBEDS 2, packagedata identical to the
property table. (The beta/gammaw unit-system defaults were used, not passed explicitly — they equal
the source model's explicit values.)

### Deviations from the repo's `model_functions.py`
1. **Packaging.** The repo builds and runs with raw flopy (`MFSimulation`, `set_all_data_external`,
   `pyemu.os_utils.run`). Here the same model is built/run only through MCP tools. Physics is
   unchanged; the concrete differences are:
   - IMS: the source sets `complexity="simple"` plus explicit `outer_dvclose=inner_dvclose=1e-3`,
     `inner_maximum=200`, `relaxation_factor=0.97`. The MCP `set_simulation` exposes
     `ims_complexity`, `outer_maximum`, `linear_acceleration` (and `under_relaxation`), but not
     `outer_dvclose`/`inner_dvclose`/`inner_maximum`/`relaxation_factor`. Used
     `ims_complexity="moderate"`, `outer_maximum=300`, `linear_acceleration="bicgstab"`.
     The model converged on the first attempt, so this did not degrade the solution.
   - `sgs` in the source is written as `prop_df.loc["sgm"]` (a repo quirk: `sgs = sgm = 1.7`), not
     the prepared `sgs = 2.0`. Reproduced faithfully as 1.7.
   - `pcs0` is passed as 0.0 for both interbeds (the source has this line commented out) and
     `initial_preconsolidation_head=true` is set (the source forces this whenever `head_based` is
     false, overriding its own `specified_initial_interbed_state=False` argument).
   - The source also writes `zdisplacement`/`package_convergence`/`strainib` file records and a
     head-observation package; the MCP `add_csub_package` has no filerecord arguments for those and
     they are pure outputs, so they are omitted. `read_compaction` therefore reports
     `interbed_strain: null`.
2. **Comparison baseline caveat.** The shipped `H201\output\SimulatedSubsidence_H201.csv` is
   produced by the repo's **Multi-IB** branch variant: its `ib_results_H201_ibbylayer.xlsx` lists
   **10 interbeds** (5 per layer, total clay 43.5 ft Upper / 84.4 ft Middle), whereas `prep_data.py`
   + `model_functions.py`'s own `__main__` path (and this run, per the task's spec) aggregate the
   clay into **one interbed per layer** (`thick_frac*rnb` = 44 ft Upper / 551 ft Middle). The
   shipped `base` series is therefore not directly comparable to a single-interbed build; the
   measured series from `sub_data.csv` is used as the calibration target instead.

## 4. Post-processing (MCP tools)

- `read_compaction(max_rows=5)` → `h201csub_compaction.csv` (per-layer `COMPACTION.01/02` + summed
  `subsidence`), 158 rows.
- `plot_subsidence(observed_csv=H201\source_data\H201_sub_data.csv)` → PNG returned; the observed
  series is plotted on its own (calendar) axis so the two curves are not x-aligned in that figure.

Prior (uncalibrated) model vs measured subsidence on the 17 dates the annual model shares with the
observation file (`subsidence` = Σ layer compaction; measured = `Subsidence_ft`):

| date | sim prior (ft) | measured (ft) |
|---|---|---|
| 1904-01-01 | 0.000 | 0.00 |
| 2005-01-01 | 2.250 | 1.58 |
| 2006-01-01 | 2.237 | 1.53 |
| 2008-01-01 | 2.284 | 1.59 |
| 2010-01-01 | 2.262 | 1.93 |
| 2011-01-01 | 2.312 | 2.01 |
| 2013-01-01 | 2.314 | 2.27 |
| 2014-01-01 | 2.296 | 2.26 |
| 2016-01-01 | 6.710 | 2.31 |
| 2017-01-01 | 8.503 | 2.40 |
| 2018-01-01 | 8.463 | 2.48 |
| 2019-01-01 | 8.410 | 2.57 |
| 2020-01-01 | 8.356 | 2.66 |
| 2021-01-01 | 8.369 | 2.75 |
| 2022-01-01 | 8.370 | 2.79 |
| 2023-01-01 | 8.442 | 2.87 |
| 2024-01-01 | 8.448 | 2.91 |

**Prior RMSE = 4.09 ft** (8.45 ft vs 2.91 ft at 2024). The step at 2016 is driven by the processed
Middle-aquifer head series: the raw observations stop at 2014-05-30 (-68.2 ft) and resume
2017-10-12 (+7.2 ft), so `prep_data.py`'s time interpolation produces annual mean heads of
-43.1 ft (2015) and -43.9 ft (2016) at that node, which drives a large, irreversible inelastic
compaction increment. This is a property of the repo's own preparation, reproduced faithfully.

## 5. Calibration chain

1. `import_subsidence_observations(name=subsidence, observed_csv=H201\source_data\H201_sub_data.csv)`
   → 208 observations registered; sim source `h201csub.csub.obs.csv`, `sum_cols=["compaction"]`,
   `time_col="time"`, start date 1903-12-31.
2. `setup_calibration(obs_source="derived", noptmax=…, parameterisation={…})` → `h201csub.pst`,
   3 templates (`h201csub.csub_cg_ske_cr.dat.tpl`, `h201csub_k33.dat.tpl`,
   `h201csub.csub_packagedata.dat.tpl`), instruction file, space-free Python forward wrapper
   (`C:\Users\jakob\AppData\Local\Temp\gwmcp_run_h201csub.py`).
   - **6 adjustable parameters** (all log-transformed): `ssv_ssv_cc_1` 5e-05 (Upper `ssv_cc`),
     `ssv_sse_cr_1` 2.5e-07 (Upper `sse_cr`), `ssv_ssv_cc_2` 5e-04 (Middle `ssv_cc`),
     `ssv_sse_cr_2` 2.5e-06 (Middle `sse_cr`), `cg` (`cg_ske_cr`, layer 1) 2.5e-06, `k33` 0.01.
   - **17 matched observations** out of 208: the model writes output only at stress-period ends
     (annual), so only the observations that fall on the sim time axis are matched; the other 191
     are reported as `skipped_dates`.

### 5.1 IES / GLM do not complete (reproduced stall)

`start_calibration` was attempted four times. Observed behaviour (identical signature):

- PEST++ runs the **base/initial ensemble** fine for the first few realizations, then spins at
  **exactly 100 % CPU** (`pestpp-ies.exe` 311 s CPU in 314 s wall) with `.rec` frozen and no `.phi`
  file written.
- The MCP forward wrapper (`C:\…\Temp\gwmcp_run_h201csub.py`, run as a child of pestpp) is alive
  but blocked at ~0.016 s CPU. Its own trace file
  (`C:\…\Temp\gwmcp_run_h201csub.trace`) stops at `stage=mf6_start` with **no `stage=mf6_done`**,
  and **no `mf6.exe` process exists** while this persists.
- Between successive successful runs the wrapper's MF6 launch took 51 s, 81 s, 245 s, 267 s and
  144 s wall respectively, while MF6 itself reports `Elapsed run time: 0.095–0.158 s` and
  `Normal termination of simulation`.
- `run.info` freezes (`realization:3`, then `realization:1`, then `par_name:__base__` for GLM) for
  1–4.5 minutes at a time; no `h201csub.<i>.phi.actual.csv` is ever produced.
- Isolating components: `mf6.exe -v` from a normal shell returns in **0.05 s**, and a plain
  `start_run()` through the MCP server (same model, same binary) completed in **0.14 s**
  ("Normal termination"). So MF6 and the MCP server's own run path are healthy; the blockage is
  specifically in the PEST++-driven forward-run launch of `mf6.exe` by the generated wrapper
  (`subprocess.run([MF6], stdin/stdout/stderr=DEVNULL)`, whose `mf6_start` never returns).
- Attempts: IES `num_reals=16` (stalled at realization 3), IES `num_reals=10` (stalled at
  realization 1), IES `num_reals=8, noptmax=1` (base run never completed), GLM (base run blocked
  144 s then completed; killed while waiting), GLM relaunched (see below). Each attempt was
  terminated with `cancel_job`, which stopped the PEST++ process and restored the externalised
  inputs; `check_model` still passes afterwards.
- Note this is **not** the previously fixed pipe deadlock: the wrapper passes
  `stdin/stdout/stderr=DEVNULL` to MF6 (verified in the generated wrapper), MF6's own listing shows
  normal termination, and the model run itself is 0.1 s. The stall is in the process-launch path
  under PEST++, not in MF6's stdio.

### 5.2 What the last GLM attempt did compute (and where it stopped)

The final GLM attempt got furthest. Its own record (`h201csub.rec`) reads:

```
   -----    Starting pestpp-glm Iterations    ----
OPTIMISATION ITERATION NUMBER: 1
  Iteration type: base parameter solution
 warning: failed to compute parameter derivative for SSV_SSV_CC_1
 warning: failed to compute parameter derivative for SSV_SSE_CR_1
 warning: failed to compute parameter derivative for CG
 warning: failed to compute parameter derivative for SSV_SSV_CC_2
 warning: failed to compute parameter derivative for SSV_SSE_CR_2
  Starting phi for this iteration                     Total : 285.023
  Number of terms in the jacobian equal to zero: 1 / 17 (5.9%)

    Parameters that went out of bounds while computing jacobian
      Parameter
        Name
      ----------
            CG
  SSV_SSE_CR_1
  SSV_SSV_CC_1
  SSV_SSE_CR_2
  SSV_SSV_CC_2
   ...calculating lambda upgrade vector: 0.1 … 1000   (5 / 5)
starting FOSM uncertainty analyses for iteration 0
posterior parameter covariance matrix written to file 'h201csub.1.post.cov'
current parameter uncertainty summary:
                name   prior_mean   prior_stdev … post_mean   post_stdev
                 k33           -2           0.5         -2           0.5      → h201csub.0.par.usum.csv
```

- **Base phi (prior misfit) = 285.023** (measurement phi, with the FOSM-reweighted observation
  weights). This is the only `phi` the chain produced; there is no post-upgrade phi.
- **`h201csub.sen` contains a single parameter**, `k33` (CSS 2.8e-09 ≈ 0). The five CSUB parameters
  are absent because their derivatives were never computed.
- **`h201csub.0.par.usum.csv` likewise lists only `k33`** (`-2` → `-2` in log space), i.e. no
  parameter estimate differs from its prior.
- The attempt then required the next forward run for the lambda search and **never launched another
  wrapper** (trace frozen after 3 `mf6_done` events, `run.info` frozen at `run_id 2 scale(0.75)` for
  11+ minutes, `pestpp-glm` at 100 % CPU with a wrapper child at ~0 CPU).
- Trace accounting: the first GLM Jacobian needs 1 base + 6 perturbation runs = 7 forward runs; the
  wrapper trace shows only **3** completed `mf6_done` events, which is exactly why 5 of 6
  derivatives "failed to compute".

The derived-observation interface itself is sound: the base-run residuals in
`h201csub.0.fosm_reweight.rei` reproduce the manual prior comparison of §4 exactly
(`2017-01-01`: measured 2.40000, modelled 8.50284; `2024-01-01`: 2.91000 vs 8.44812), so the
date mapping, the `sum_cols=["compaction"]` sum and the instruction file all work.

**Capability gap / actionable error (criterion 5).** The MCP calibration chain
(`setup_calibration` → `start_calibration`/`run_pestpp_ies`/`run_pestpp_glm` → `summarise_calibration`)
could not be driven to a completed iteration on this model. Two coupled defects were observed:

1. *Harness/launch (primary).* The PEST++-driven forward wrapper does not reliably launch `mf6.exe`.
   The wrapper child sits at ~0 s CPU with its own trace stuck at `stage=mf6_start` (or with no
   trace line at all), `mf6.exe` never appears in the process table, yet `pestpp-ies/glm` busy-waits
   at exactly 100 % CPU and the model-output files do not change for 1–11+ minutes. When a launch
   does succeed it takes 51/81/144/245/267 s wall although MF6 reports `Elapsed run time 0.095–0.158 s`.
   The last blocked launch eventually cleared after ≈12 min: the wrapper logged `mf6_start` at
   23:32:28 and MF6 finally finished at 23:44:42 (`mfsim.lst`: "Run end date and time (…)
   2026/09/20 23:44:42 … Elapsed run time: 0.104 Seconds … Normal termination of simulation").
   MF6 itself is healthy: `mf6.exe -v` returns in 0.05 s, and `start_run()`/`run_simulation()` through
   the MCP server (same binary, same workspace) complete in 0.14–0.16 s with "Normal termination".
   So the blockage is in the PEST++→wrapper→MF6 spawn path, not in MF6 or in the MCP server's own
   run path. Plausible causes worth testing on the MCP side: the wrapper/PEST++ children inherit the
   stdio MCP server's stdout (the JSON-RPC transport), so console output can block on a full pipe,
   and `subprocess.run([mf6], stdin/stdout/stderr=DEVNULL)` under PEST++ has no console of its own.
   Suggested fixes: give the PEST++ job and the wrapper an explicit console
   (`CREATE_NO_WINDOW`/`DETACHED_PROCESS` is not sufficient by itself), redirect their stdout/stderr
   away from the MCP transport, and/or drive the ensemble through a proper run manager (PANTHER)
   instead of serially through PEST++'s busy-wait.
2. *Silent degradation.* Because those runs never happened, PEST++ emitted only warnings
   (`failed to compute parameter derivative …`) and continued with a zero Jacobian rather than
   failing: the 5 CSUB parameters were reported "out of bounds while computing jacobian", `h201csub.sen`
   kept only `k33`, and no `.phi.actual.csv`/`.iobj` row was produced, so `summarise_calibration` has
   nothing to summarise and `run_pestpp_*` never returns an error to the caller.

This was **not** worked around: no raw flopy/pyemu/PEST++ invocation and no hand-editing of the PEST
or MF6 files was used. The two `csub:packagedata` templates, the `cg` template and the `k33` template
were verified to be correct (`h201csub.csub_packagedata.dat.tpl` places `~ ssv_ssv_cc_1 ~` /
`~ ssv_sse_cr_1 ~` in interbed row 1 and `~ ssv_ssv_cc_2 ~` / `~ ssv_sse_cr_2 ~` in row 2; the CSUB
package is rewired to `OPEN/CLOSE 'h201csub.csub_packagedata.dat'` and `OPEN/CLOSE
'h201csub.csub_cg_ske_cr.dat'`, NPF to `OPEN/CLOSE 'h201csub_k33.dat'`).

## 6. Reprompts / decisions / deviations summary

- Tool calls used (in order): `check_environment`; (copies + `prep_data.py` + `make_payloads.py`
  outside the MCP, as permitted data preparation); `create_model`, `set_simulation`,
  `add_dis_package`, `add_npf_package`, `add_ic_package`, `add_sto_package`,
  `add_boundary_package`, `add_csub_package`, `add_oc_package`, `check_model`, `start_run`,
  `get_job_status`, `read_compaction`, `plot_subsidence`,
  `import_subsidence_observations`, `setup_calibration`, `start_calibration`,
  `get_job_status`, `cancel_job` (×5: IES-16, IES-10, IES-8, GLM, GLM),
  `check_parameter_sensitivity` (rejected: needs head-obs targets), `run_simulation` (timed out),
  `start_run`, `get_job_status`, `check_model`.
- No user reprompts and no clarification rounds were needed; every model-building/running/
  post-processing/calibration action went through an MCP tool.
- Decisions: (a) reproduced the repo's TDIS/GHB/CSUB construction in ordinary Python and passed the
  literal payloads to the MCP tools (rather than letting the LLM re-derive values by hand);
  (b) used only the two `compaction` cell observations plus the delay diagnostics as CSUB
  observations, so the derived subsidence is an unambiguous sum of layer compaction;
  (c) kept the source's `sgs = sgm` quirk; (d) fell back from IES to GLM (the setup tool's own
  recommendation for 6 parameters) when IES stalled.
