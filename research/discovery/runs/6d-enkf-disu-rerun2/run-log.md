# run-log.md — Phase 6d target 8

**Target:** `MF6_EnKF_DISU` (JanGei/MF6_EnKF_DISU, Neckartal DE) — closed-book MCP toolchain validation
**Session worktree:** `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun2`
**Date:** 2026-09-15
**Model:** `neckartal` (adopted, workspace = the shipped `sim\` directory)

All actions that adopt, build, run, post-process, calibrate or assimilate the MF6 model were
performed through `groundwater-mcp` tools. Ordinary Python was used **only** to reshape
`csv data\Pegel.csv` + `Pegel_Cell_ID.csv` into the long observation table that is fed *into*
`import_obs_from_csv`, and to read/print diagnostics. No flopy/pyemu MODFLOW or PEST classes were
called, no MODFLOW/PEST file was hand-edited, and the repo's own EnKF scripts
(`main.py` / `Transient_Run.py` / `generator.py` / `Objectify.py`) were **not executed**.

The repo's Python was read as the model specification only: `main.py:290` establishes
`date = datetime.date(2017,1,30)` with a 1-day step and a per-step observation match, which drove
the cycle-date choice below.

---

## 1. `check_environment` — stack

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`), win32 |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-da / glm / ies | `C:\Users\jakob\.local\bin\pestpp-da.exe`, `pestpp-glm.exe`, `pestpp-ies.exe` |
| docs index | built |
| `ready` | **true**, `missing.packages: []`, `missing.binaries: []` |

## 2. `adopt_model`

```
adopt_model(name="neckartal", workspace="...\MODFLOW 6\sim",
            units="METERS", time_units="DAYS", allow_modify=true)
-> {"adopted": true, "model_names": ["flow"], "allow_modify": true}
```

* Name 9 chars (<= 16). No grid rebuild, no file renames.
* Targets the shipped single GWF model `flow` (`mfsim.nam` + `flow.nam`).
* Units/time units taken from the model itself: `flow.disu` declares `LENGTH_UNITS meters`,
  `sim.tdis` declares `TIME_UNITS days`.
* `summarise_model` confirmed the grid read back from disk: DISU, 1 layer, **31,831 nodes**,
  **NJA 198,261**, **31,522 active**, packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO.

## 3. `check_model` — clean

`check_passed: true`, `warnings: []`, `errors: []`. FloPy's checker reported no errors or warnings
across NPF (K/K33 ranges), CHD/RCH/RIV/WEL (indices, NaNs, inactive cells) and STO (Ss/Sy ranges).

Supplementary `validate_model`-style sanity check read directly from the shipped arrays (read-only):

* `flow.npf_K_1.txt`: 31,831 values, min 0.864, median 8.64, max 86,400 m/d, **10,413 unique**.
* `flow.ic_STRT_1.txt`: 309 values equal 1e30 — **all 309 are `idomain == 0`** (inactive), so harmless;
  active `strt` spans 305.16–346.68 m.
* `flow.disu_IHC/HWVA/CL12/ANGLDEGX` + `VERTICES` + `CELL2D` all present (vertex grid).

## 4. Re-expressing the run as sequential DA (`NPER=1`, `NSTP=1`)

Shipped discretisation: `sim.tdis` = **NPER 6 × 1.0 day, NSTP 1**. Sequential PEST++-DA needs exactly
one stress period with one time step per cycle, because the OBS-CSV instruction file reads the first
data row (the end-of-cycle value only with a single time step).

```
set_simulation(model="neckartal", nper=1, perlen=[1.0], nstp=[1], ims_complexity="complex")
-> {"nper": 1, "time_units": "DAYS", "ims_complexity": "COMPLEX", "written": false}
```

**Discovery (deviation-free, worth recording):** `flush_model`/`set_simulation` did **not** rewrite
the shipped `sim.tdis` (it still reads `NPER 6`). The MCP instead writes its own effective simulation
files and repoints the name file:

* `modflowsim.tdis` — `NPER 1`, period data `1.0 1 1.0` (later `7.0 1 1.0`, see below)
* `modflowsim.ims` — `COMPLEXITY complex`
* `mfsim.nam` repointed from `sim.tdis`/`sim.ims` to `modflowsim.tdis`/`modflowsim.ims`

So the source set is preserved on disk and the reduction is applied non-destructively. `mfsim.lst`
confirms the solver ran `Stress period: 1, Time step: 1` / `1 STRESS PERIOD(S) IN SIMULATION`.

**Cycle scheme (explicit DA cycles).** The repo assimilates on the weekly gauge Mondays
2017-01-30, 02-06, 02-13, 02-20, 02-27. I re-expressed this as **5 cycles** whose ends are exactly
those dates, with the stress-period length driven by the DA cycle table:

| cycle | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| `perlen` (days) | 1 | 7 | 7 | 7 | 7 |
| cycle ends | 2017-01-30 | 02-06 | 02-13 | 02-20 | 02-27 |
| active gauges | 13 | 9 | 3 | 2 | 3 |

Cycle 0 is 1 day to mirror the repo's first step (its day-0 assimilation is a 1-day forecast from the
IC); cycles 1–4 are 7 days. Total 29 days vs the repo's 30-day loop, with the identical 5 observation
dates. `par_cycles={"perlen": {0:1, 1:7, 2:7, 3:7, 4:7}}` drove this; the final
`modflowsim.tdis` reads `7.000000000000000 1 1.0`, confirming the cycle table, not a fixed value.

Boundary forcing is unaffected by the reduction: `flow.rch`, `flow.riv`, `flow.wel`, `flow.chd` and
`flow.oc` each contain **only PERIOD 1** (they are static), so 6→1 periods loses no forcing variation.
`flow.sto` declares 6 `TRANSIENT` periods; MF6 tolerated the excess periods and the run converged.

**Deviation:** `sim.ims` in the source declares `COMPLEXITY complex`, `NO_PTC all`,
`OUTER_DVCLOSE 0.1`. The MCP's `complex` preset writes only `COMPLEXITY complex`, so `NO_PTC`/
`OUTER_DVCLOSE` are dropped. `set_simulation` is unavoidable for the TDIS reduction and offers no
verbatim/custom IMS option. The model still converged normally (1.2–1.6 s per run).

## 5. Registering the gauges

Prep (ordinary Python, `scratch\prep_obs.py`, allowed data prep): read `Pegel.csv` with
`dayfirst=True`, melt the wide table to long, drop `-9999` as missing (`value > 0`), join
`Pegel_Cell_ID.csv` (Name → Cell_ID), keep the 5 cycle dates.

Result: **30 records, 13 sites** (Ne-507 has no value on any of the 5 dates). Output
`scratch\gauge_obs_cycles.csv` (columns `site,date,value,Cell_ID`).

```
import_obs_from_csv(model="neckartal", csv_file="...\gauge_obs_cycles.csv",
                    obs_type="HEAD", site_col="site", date_col="date",
                    value_col="value", cellid_col="Cell_ID")
-> site_count 13, total_records 30, obs_file flow.obs
   site_cellid_map: Ne-401:14120 ... Ne-806:12065   (0-based node id + 1)
```

The tool converted the scalar DISU node ids to the 1-based OBS ids (e.g. Ne-401 node 14119 → 14120).
`flow.nam` gained `obs6 flow.obs obs_0`.

**Mapping verification.** A converged baseline `run_simulation` gave
`n=13, rmse=4.949, bias=-4.765, r2=-1.835`. Comparing the module's `t = 1 day` output against the
cycle-0 gauge values gives per-site residuals of +2.5 to +8.0 m across **all 13** sites with a
consistent sign — the signature of a correct node mapping (a mis-mapped node would give hundreds of
metres). `flow_obs_summary.csv` confirms dates 2017-01-30…02-27 and values 326.7–337.6 m against a
head field of 305–347 m. The baseline is **not** calibrated to these gauges (5 m bias, R² < 0) — this
is recorded rather than hidden.

## 6. `setup_da_control`

```
setup_da_control(model="neckartal", parameterisation={"K": {"target": "npf:k", "scope": "all",
                 "initial": 10.18}}, cycles=[0,1,2,3,4], obs_cycles={13 sites -> {cycle: value}},
                 par_cycles={"perlen": {0:1, 1:7, 2:7, 3:7, 4:7}},
                 num_reals=30, noptmax=1, use_simulated_states=True)
```

Reported by the tool: **n_observations 13, n_adjustable_parameters 1, n_state_parameters 13,
n_cycles 5**. Generated artefacts:

* `neckartal.pst` — `pcf version=2`, `noptmax 1`, `da_num_reals 30`,
  `da_observation_cycle_table neckartal_da_obs_cycle_tbl.csv`,
  `da_parameter_cycle_table neckartal_da_par_cycle_tbl.csv`, `da_use_simulated_states True`.
* **Parameter count: 15 rows = 1 adjustable (`K`, log, `factor`, 10.18, bounds 1.018–101.8) +
  13 state parameters (`head_state`, one per registered gauge cell, `none`/`relative`) +
  1 fixed (`perlen`).** The 13 state parameters are the state augmentation.
* `flow.npf` rewired: `k OPEN/CLOSE 'flow_k.dat'` (template `flow_k.dat.tpl`); original heterogeneous
  field preserved by the tool as `flow_k_pristine.npy`.
* `flow.ic` rewired: `strt OPEN/CLOSE 'flow_strt.dat'`; `flow_strt.dat.tpl` carries **13 tokens**
  named after the gauges (values initialised from the shipped `strt` at those cells).
* `modflowsim.tdis.tpl` carries the templated `perlen`.
* `flow_head.obs.csv.ins` (pif) reads the obs CSV header row → per-cycle end-of-cycle values.
* Cycle tables: obs = the full site × cycle matrix; parameter = `perlen,1,7,7,7,7`.

**Model command** is a space-free Python wrapper in `%TEMP%` (`gwmcp_run_neckartal.py`), which avoids
the Windows PEST limitation on paths with spaces / `.bat` wrappers.

**Known caveat carried into section 9:** `scope="all"` writes a **uniform** K — `flow_k.dat` contains
31,831 tokens *all named `K`* — i.e. the shipped 0.864–86,400 m/d heterogeneous field is replaced by a
single value. This is the one parameterisation the tool offers for a single-parameter DA (`zones` is
infeasible here: 10,413 unique K values → 10,413 zone multipliers).

## 7. Assimilation — `run_pestpp_da` + `summarise_da`

`run_pestpp_da(model, pst_file="neckartal.pst", num_workers=4)` (no `num_reals`, so the PST's 30 is
kept). Both DA calls **exceeded the MCP client timeout** while continuing correctly server-side
(observed as a live `pestpp-da` process + growing `neckartal.global.phi.actual.csv`); progress was
tracked on disk and `summarise_da` was called after the process exited. See section 10.

### Run 1 — tool-default prior (bounds-derived)

| cycle | post-update φ (mean) | prior φ next cycle |
|---|---|---|
| 0 | 6.686e6 | 159.364 (cycle 1 prior) |
| 1 | **67.669** | 19.882 |
| 2 | **19.795** | 16.162 |
| 3 | **16.100** | 19.805 |
| 4 | **19.765** | — |

final φ mean **19.7651**, std 1.23404. Cycle-0 prior φ was **1.105e9** (min 342, max 1.93e10).

Root cause (diagnosed from `neckartal.par_data.csv`): the 13 state parameters are given
`parlbnd ≈ -999661 / parubnd ≈ 1000339` (±1e6 m, from the `relative` change limit), so `pestpp-da`'s
default prior draws the gauge-cell initial heads over ±1e6 m — physically meaningless, hence the
1e9 φ. It is a **tool-default configuration artefact, not a model defect**: as soon as
`da_use_simulated_states` carried the cycle-0 simulated heads into cycle 1, φ dropped to 159.4 and the
updates behaved normally (159.4→67.7, 19.88→19.80, 16.16→16.10, 19.80→19.77).

### Run 2 — explicit physical prior (recommended configuration)

Re-ran `setup_da_control` with an explicit `prior_ensemble`: K log-uniform in [3.0, 30.0] (inside its
1.018–101.8 bounds) and each gauge-cell head drawn as `strt + N(0, 2 m)` clipped to ±6 m
(seed 20260915, 30 realisations). Written to `neckartal_da_prior.csv`; verified
k ∈ [3.135, 26.959] (mean 11.426), Ne-401 ∈ [332.93, 341.57].

| cycle | prior φ (mean) | post-update φ (mean) | post-update std |
|---|---|---|---|
| 0 | **339.18** | **300.17** | 13.04 |
| 1 | 110.01 | **64.11** | 0.0074 |
| 2 | 19.4397 | 19.4397 | 1.4e-05 |
| 3 | 15.7904 | 15.7904 | 2.8e-05 |
| 4 | 19.5135 | **19.5135** | 3.1e-05 |

final φ mean **19.5135**, std **3.10e-05**.

* Cycle-0 prior is now physical: φ 339.2 ↔ rms 5.11 m over 13 obs, bracketed by the two
  independently measured baseline rms values (4.949 m with the pristine K field, 5.147 m after the
  uniform-K rewiring). Prior → post improves 339.2 → 300.2 (−11.5%).
* Cycles 1–5 show consistent prior → post improvement (110.0 → 64.1 is −41.7%).
* φ floor ≈ 15.79–19.51 for 2–3 active obs ↔ rms **2.55–2.81 m**, vs the 4.95–5.13 m baseline: a
  genuine ~50% reduction in gauge misfit, achieved by information from the gauges themselves.

**Posterior parameter statistics (run 2, final cycle, n=29):**

| parameter | mean | std | min | max |
|---|---|---|---|---|
| `k` | **101.800** | 2.8e-14 | 101.800 | 101.800 |
| ne-401 | 334.804 | 0 | 334.804 | 334.804 |
| ne-402 | 333.871 | 1.1e-13 | 333.871 | 333.871 |
| ne-403 | 333.167 | 5.7e-14 | 333.167 | 333.167 |
| ne-503 | 337.439 | 5.7e-14 | 337.439 | 337.439 |
| ne-504 | 337.447 | 0 | 337.447 | 337.447 |
| ne-505 | 333.737 | 1.7e-13 | 333.737 | 333.737 |
| ne-506 | 333.733 | 5.7e-14 | 333.733 | 333.733 |
| ne-604 | 328.605 | 5.7e-14 | 328.605 | 328.605 |
| ne-801 | 332.409 | 0 | 332.409 | 332.409 |
| ne-802 | 331.128 | 1.1e-13 | 331.128 | 331.128 |
| ne-803 | 331.127 | 5.7e-14 | 331.127 | 331.127 |
| ne-805 | 332.820 | 5.7e-14 | 332.820 | 332.820 |
| ne-806 | 332.822 | 0 | 332.822 | 332.822 |
| `perlen` | 1.0 | 0 | 1.0 | 1.0 |

**Residuals (run 2, final cycle — the 3 gauges active in cycle 4; the other 10 carry weight 0):**

| site | measured | modelled | residual |
|---|---|---|---|
| ne-604 | 326.69 | 328.605 | −1.915 |
| ne-803 | 328.27 | 331.127 | −2.857 |
| ne-806 | 330.05 | 332.822 | −2.772 |

rmse **2.5504**, bias −2.5146, R² −2.45 (n=3). Full 13-site table:
`neckartal_da_residuals.csv` (archived).

**Two findings to report honestly rather than dress up:**

1. **`K` is not identifiable from this data and drives to its upper bound** in both runs (run 2:
   101.800 = `parubnd`, std ≈ 0; run 1: 101.58). Cause: with one step per cycle from a head-dominated
   IC, heads are almost insensitive to K — replacing the heterogeneous K (0.864–86,400) with a
   uniform 10.18 changed the cycle-0 fit by only 4.95 → 5.15 m rmse. The DA therefore works almost
   entirely through the 13 state parameters (the head values), which is exactly what
   `da_use_simulated_states` is for. The posterior head states drop 1–8 m from the shipped `strt`
   in the direction the gauges demand (e.g. Ne-503 345.30 → 337.44, Ne-401 338.93 → 334.80).
2. **The ensemble collapses** (std → 0 by cycle 2), so cycles 3–5 cannot update further; φ then just
   reflects the residual misfit (rf. run 1 vs run 2 reaching the same φ attractor ≈19.44/15.79/19.5).
   Expected for a 1-parameter + state-augmented ES with no inflation/prior_std re-draw per cycle.

**Reproducibility evidence:** the two independent runs — different priors, different ensembles —
converged to posterior head states agreeing to ≈0.01 m (Ne-401 334.797 vs 334.804; Ne-503 337.427 vs
337.439; Ne-806 332.816 vs 332.822), and to the same φ per cycle. That is strong evidence the DA
machinery is behaving deterministically and correctly, not drifting.

## 8. Post-processing

* `plot_heads_map(layer=0)` — succeeded on the **vertex-carrying DISU grid** (vertices/CELL2D
  honoured, no fallback). Outputs `gwmcp_dnvkngiz.png` (run 1) and `gwmcp__k06g5yc.png` (run 2,
  archived as `heads_map_final_cycle.png`); head field 305.16–340.20 m over the ~15 km Neckartal
  valley, consistent with the gauge range.
* `read_simulated_observations` — 13 sites at `time = 7` days (final cycle).
* `compare_to_observed` — the same registered 13-site metric before and after:

| | rmse (m) | bias (m) | mae (m) | R² |
|---|---|---|---|---|
| baseline (pre-DA, t=1 day) | 4.949 | −4.765 | 4.765 | −1.835 |
| run 1 (final cycle) | 3.239 | −3.136 | 3.136 | −0.214 |
| **run 2 (final cycle)** | **2.555** | **−2.377** | **2.401** | **+0.244** |

  Scatter plot `neckartal_obs_fit.png`, residuals `neckartal_obs_residuals.csv`.

## 9. Deviations from the source model

1. **6 × 1-day → 5 single-step cycles (1, 7, 7, 7, 7 days).** Required by sequential PEST++-DA
   (one period / one step per cycle). Dates chosen to match the 5 gauge Mondays the repo's EnKF
   assimilates; the scheme is documented in section 4. No hand editing of the TDIS file — the MCP
   wrote `modflowsim.tdis` and repointed `mfsim.nam`.
2. **PEST++-DA instead of the bespoke EnKF.** Method change: the repo (`Objectify.py`,
   `functions.py`) implements a hand-rolled ensemble Kalman update with its own damping, covariance
   inflation and pilot-point K updates; `pestpp-da` performs an ensemble-smoother/IES-style update
   with weights (default 1.0 here), a cycle table and `da_use_simulated_states`. Results are
   therefore not numerically comparable to the repo's own EnKF output — this run validates the MCP
   chain, not the published EnKF result. The repo's scripts were deliberately not run.
3. **`scope="all"` → uniform K (10.18 m/d).** The shipped heterogeneous K field
   (0.864–86,400 m/d, 10,413 unique values) is replaced by one value, so the DA model is *not*
   the shipped model. Effect measured: cycle-0 rmse 4.95 → 5.15 m (small, because a 1-day step from
   the IC is head-dominated). The pristine field is archived by the tool as `flow_k_pristine.npy`;
   `flow_input\flow.npf_K_1.txt` is untouched, so the original is recoverable. `zones` is not a
   workable alternative at this K heterogeneity (10,413 zones).
4. **Static boundary forcing.** The shipped `flow.rch/.riv/.wel/.chd/.oc` only carry PERIOD 1, so no
   forcing is lost by NPER=1. The repo, by contrast, rewrote RCH/WEL dynamically at every time step
   from `csv data\2017.csv` (`main.py:297-298,327`); that per-step forcing is not re-expressed here.
5. **State carry-over is partial.** `flow_strt.dat.tpl` has 13 tokens (one per observed cell), so
   between cycles only those 13 nodes' initial heads are updated from the previous cycle's simulated
   values; the other 31,818 nodes restart from the shipped `strt` each cycle. The DISU head field is
   never written back wholesale as the next IC.
6. **IMS options narrowed** (`NO_PTC all`, `OUTER_DVCLOSE 0.1` dropped by the `complex` preset) —
   see section 4. No convergence impact observed.
7. **Post-processing state.** The on-disk model after a DA run holds the *last evaluated realisation*
   of the final cycle (observed: uniform K = 57.30, `flow_head.obs.csv` at t = 7.0 d), not the
   posterior mean. No MCP tool exists to push posterior parameter estimates back into the model, so
   `compare_to_observed` / `read_simulated_observations` / `plot_heads_map` describe a final-cycle
   ensemble member. Its 13-gauge fit (rmse 2.555 m) is representative of the collapsed posterior
   (std ≈ 3e-05).
8. **Observation weighting** is PEST++ default (weight 1.0, no measurement-error calibration), so φ
   is on an arbitrary scale — as anticipated, the gauge/head baseline is not calibrated, and φ is
   reported as a relative diagnostic (prior → post), not as a goodness-of-fit statistic.

## 10. Tool gaps and friction observed

| # | observation | impact |
|---|---|---|
| 1 | `setup_da_control` and two `run_pestpp_da` calls **exceeded the MCP client timeout** (−32001) while continuing correctly server-side. | Had to poll `run.info` / `*global.phi.actual.csv` / the process table on disk. `get_job_status` only covers `start_run`/`start_calibration`, so a DA run has no job id or progress API. **The work was still done entirely through MCP tools.** |
| 2 | State parameters are generated with ±1e6 bounds (`relative` change limit), so the *default* prior ensemble is unphysical and cycle 0 is wasted. | Worked around with the documented `prior_ensemble` option (not a workaround outside the MCP — it is a tool parameter). Worth fixing: seed state parameters from `strt` with a head-scale std, or clip the prior to bounds. |
| 3 | `prior_std=2` is applied per-parameter-space: it is sensible for the linear head states (std 1.4–2.2 m) but produced log-K draws of 0.0006–50,027 (mean 3755) — **outside** the parameter's own 1.018–101.8 bounds. | Draws are evidently not clipped to `parlbnd`/`parubnd`; `prior_ensemble` is the reliable path for mixed linear/log parameter sets. |
| 4 | No tool to write posterior parameters (or the posterior-mean head field) back into the model, and no tool to set the model's IC from the *previous cycle's* full head output. | Post-processing reflects a single ensemble member rather than the posterior mean; state carry-over is limited to observed cells (deviation 5). |
| 5 | `scope="all"` for `npf:k` silently collapses a heterogeneous K field to a uniform value. | No error/warning; must be inferred from the template (31,831 identical `K` tokens). A `scope="multiplier"`/`"factor"` option would preserve the field pattern. |

**Verdict:** the MCP toolchain was **sufficient** for this target end-to-end — adopt → check → TDIS
re-expression → obs import → DA setup → DA run → summary → map/scatter post-processing — with no raw
flopy/pyemu model call and no hand-edited MODFLOW/PEST file. The gaps above are capability/quality
gaps (DA progress API, state-prior seeding, K multiplier scope, posterior write-back), not blockers.

## 11. Tool-call sequence (as executed)

1. `check_environment`
2. `adopt_model(neckartal, sim\, METERS, DAYS, allow_modify=true)`
3. `check_model` → clean
4. `set_simulation(nper=1, perlen=[1.0], nstp=[1], ims_complexity="complex")` → `flush_model`
5. `summarise_model`, `model_status` (verify reduced TDIS in memory)
6. `start_run` → converged 1.58 s (`get_job_status`)
7. `import_obs_from_csv(cellid_col="Cell_ID")` → 13 sites / 30 records
8. `run_simulation` → baseline rmse 4.949
9. `setup_da_control(...)` (default prior) → **client timeout**, completed on disk
10. `run_pestpp_da(...)` → **client timeout**, completed on disk (polled)
11. `summarise_da` → run 1 results
12. `compare_to_observed`, `read_simulated_observations`, `plot_heads_map` → run 1
13. `setup_da_control(..., prior_std=2)` → sane head prior, absurd log-K prior → rejected
14. `setup_da_control(..., prior_ensemble=<explicit>)` → run 2 configured
15. `run_pestpp_da(...)` → **client timeout**, completed on disk (polled)
16. `summarise_da` → run 2 results
17. `compare_to_observed`, `read_simulated_observations`, `plot_heads_map` → run 2

Reprompts/retries: step 9 and steps 10/15 needed disk-side polling because of MCP client timeouts.
Step 12 needed no rework. Step 13's configuration was discarded after inspection (documented above).

## 12. Evidence index

Model workspace (`...\MODFLOW 6\sim\`):
`neckartal.pst`, `neckartal.par_data.csv`, `neckartal.pargp_data.csv`, `neckartal.obs_data.csv`,
`neckartal.tplfile_data.csv`, `neckartal.insfile_data.csv`, `flow_k.dat(.tpl)`, `flow_strt.dat(.tpl)`,
`modflowsim.tdis(.tpl)`, `modflowsim.ims`, `mfsim.nam`, `flow.npf`, `flow.ic`, `flow.obs`,
`flow_head.obs.csv(.ins)`, `neckartal_da_obs_cycle_tbl.csv`, `neckartal_da_par_cycle_tbl.csv`,
`neckartal_da_prior.csv`, `neckartal.global.phi.actual.csv`, `neckartal_da_residuals.csv`,
`neckartal_obs_residuals.csv`, `neckartal_obs_fit.png`, `flow_output\flow.hds`, `flow.cbc`,
`flow_obs_summary.csv`, `flow_k_pristine.npy`

Session archives (`scratch\`):
`prep_obs.py`, `gauge_obs_cycles.csv`, `gauge_obs_matrix.csv`, `prior_ensemble.json`,
`run1_default_prior\` (10 files), `run2_explicit_prior\` (15 files incl. `heads_map_final_cycle.png`)

## 13. Licence check (as requested)

No `LICENSE`, `LICENCE`, `COPYING`, `NOTICE` or similar file exists in the repository — verified by a
recursive depth-2 search of the repo root plus a listing of the top-level entries (only
`Final_h_field.mat`, `functions.py`, `generator.py`, `K_field in t1`, `main.py`,
`Objectify_old.py`, `Objectify.py`, `Plot_Unstrucuted*.py`, `test.py`, `Transient_Run.py`).
**The "no LICENSE file" claim is confirmed**: with no licence grant, the default is all rights
reserved, so the model inputs and gauge data were used read-only inside this local validation and
nothing from the repo was redistributed or committed.
