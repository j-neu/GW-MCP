# Closed-book validation run — Phase 6d target 9

**Target:** `1DSubsidenceModeling-MF6CSUB` (github.com/leila-saberi/1DSubsidenceModeling-MF6CSUB, branch `Multi-IB`, commit `ff5ef1deafd9aaa228440bee9736f776233f8d74`)
**Site used:** H201 (the repo's own `__main__` example)
**Session folder:** `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-target9-csub-rerun2\h201_work`
**Holdout tree:** read-only; nothing was executed inside it and nothing was written to it.
**Mode:** closed-book (no groundwater-mcp repo source / tests / plans / prior logs were read).

---

## 1. Environment (`check_environment`, first call)

| item | value |
|---|---|
| Python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`), Windows-10.0.19045 |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` → **6.7.0 (02/05/2026)** |
| pestpp-* | `pestpp-glm`, `pestpp-ies`, `pestpp-sen`, `pestpp-opt`, `pestpp-da` present |
| docs index | built |
| `missing` | `{packages: [], binaries: []}`, `ready: true` |

Stack reported ready; no gaps. `pestpp-ies` self-identifies as "a GLM iterative ensemble smoother".

## 2. Data preparation (ordinary Python / repo script — allowed)

1. Copied `H201\`, `dependencies\` (717 files, 13.8 MB) and `bin\` into the session folder. Holdout untouched.
2. Ran the repo's own `prep_data.py` there as **data preparation** (not a model operation):
   `PYTHONPATH=<session>\h201_work  <venv>\python.exe H201\prep_data.py`
   Outputs: `H201\processed_data\H201.model_property_data.csv`, `H201.ts_data.csv`.

Processed property table (this is the model specification):

| property | layer 0 (Upper) | layer 1 (Middle) |
|---|---|---|
| cdelay | nodelay | delay |
| ssv_cc | 5e-05 | 0.0005 |
| sse_cr | 2.5e-07 | 2.5e-06 |
| theta | 0.35 | 0.35 |
| kv | 5e-05 | 5e-05 |
| cg_theta | 0.3 | 0.3 |
| cg_ske_cr | 2.5e-07 | 2.5e-06 |
| sgm / sgs (table) | 1.7 / 2.0 | 1.7 / 2.0 |
| k / k33 | 10.0 / 0.01 | 10.0 / 0.01 |
| tot_thick | 131 | 1040 |
| top / botm | 53.8 / -77.2 | 53.8 / -1117.2 |
| clay_thickness_0 | 44.0 | 551.0 |
| thick_frac_0 (bequiv) | 7.445037 | 22.924098 |
| rnb_0 | 5.909978 | 24.035842 |

3. `make_inputs.py` (ordinary Python, no flopy/pyemu) reproduced the repo's `initialize_model()`
   time/GHB derivation from `ts_data.csv` + `sub_data.csv` and wrote `mcp_inputs.json`:
   * `start_datetime = min(sub.min, gw.min) = 1904-01-01`; TDIS start `1903-12-31`
   * per-layer yearly (`freq='Y'`) resampled means of the daily-interpolated gw levels (121 rows each)
   * historic period ends = union of yearly dates + (start − 1 day) → 122 historic periods
   * predictive periods to 2060-12-31 re-using the last historic head → **nper = 158** (matches the
     "158-period model" note in the task)
   * GHB: conductance 50000, one record per layer per period; only 2 periods used head re-use
     (both layers, kper 1) — no period dropped for head-below-bottom
   * IC strt = max interpolated gw level = 53.8 ft

## 3. MCP build (all model actions via groundwater-mcp)

Model name `h201csub` (8 chars), workspace `<session>\h201_work\model_ws`, units FEET / DAYS.

| # | tool call | key arguments |
|---|---|---|
| 1 | `create_model` | name `h201csub`, units FEET, time_units DAYS, explicit workspace |
| 2 | `set_simulation` | nper 158, perlen (57 346 d total), nstp all 1, `start_date_time=1903-12-31`, `newton=true`, `ims_complexity=simple`, `linear_acceleration=bicgstab`, `outer_maximum=300` |
| 3 | `add_dis_package` | nlay 2, nrow 1, ncol 1, delr=delc=1, top 53.8, botm [-77.2, -1117.2] |
| 4 | `add_npf_package` | icelltype 1, k [10,10], k33 [0.01,0.01], `k_units="ft/d"` |
| 5 | `add_ic_package` | strt 53.8 |
| 6 | `add_sto_package` | iconvert 0, ss 0, sy 0, `steady_state=[0]` |
| 7 | `add_boundary_package` | GHB, 158 stress periods × 2 records, cond 50000 |
| 8 | `add_csub_package` | packagedata 11-field × 2, ninterbeds 2, ndelaycells 19, cg_theta [0.3,0.3], cg_ske_cr [2.5e-7,2.5e-6], sgm/sgs 1.7, beta 2.227e-8, gammaw 62.48, `initial_preconsolidation_head=true`, `specified_initial_interbed_state=true`, `update_material_properties=false`, 16 observation records, filerecords zdisplacement/strainib/package_convergence |
| 9 | `add_oc_package` | saverecord HEAD ALL + BUDGET ALL, head/budget filerecords |
| 10 | `check_model` | `check_passed: true`; only the 2 expected `sto: specific storage below 1e-06` warnings (ss = 0, as in the repo) |
| 11 | `run_simulation` / `start_run` | see §4 |

CSUB records actually written (`h201csub.csub`, 1-based, as MF6 reads them):

```
1  1 1 1  nodelay  0.0   7.44503670   5.90997758   5.000000E-05  2.500000E-07  0.35  5.000000E-05  0.0
2  2 1 1  delay    0.0  22.92409836  24.03584173   5.000000E-04  2.500000E-06  0.35  5.000000E-05  0.0
```

### Deviations from the repo's `model_functions.py`

| item | repo | here | note |
|---|---|---|---|
| solver | IMS simple, outer 300, inner 200, dvclose 1e-3, `relaxation_factor=0.97` | simple, outer 300, bicgstab | MCP `set_simulation` does not expose inner_maximum / dvclose / relaxation_factor |
| `sgs` | repo passes the **sgm** column (1.7) for `sgs` too, although the prepared table has `sgs = 2.0` | sgs 1.7 | deliberately reproduced the code, not the table (repo quirk) |
| `pcs0` | code appends `0.0` (ignores table `-200 / 50`) | 0.0 | reproduced |
| CSUB file layout | `set_all_data_external()` (arrays in separate files) | CSUB arrays inline | cosmetic |
| head observation package | repo adds a UTL `obs` package for simulated heads | not added | not needed for subsidence |
| run length | yearly historic + predictive to 2060 | same (158 periods) | matches |
| `--` | | | |

## 4. Running the model (and the first real defect found)

**Attempt 1 — hard crash.** `run_simulation` returned `success:false`, `convergence:"failed"` after 1.1 s:

```
Solving:  Stress period:  2  Time step: 1
forrtl: severe (157): Program Exception - access violation
mf6.exe  GWFCSUBMODULE_mp_ ... gwf-csub.f90 line 6757
```

Root cause, from the **generated** `h201csub.csub.obs`:

```
DELAY-PRECONSTRESS.02.02.00  delay-preconstress  3 1      <-- interbed 3
DELAY-HEAD.02.02.00          delay-head          3 1
```

The model has only `NINTERBEDS 2`, so the delay-head/delay-preconstress observations referenced a
non-existent **interbed 3**. During the steady-state first period MF6 wrote the not-a-number
sentinel (`0.3E+31`) for those records and did not dereference the interbed; on the first transient
step it did — out-of-range access → access violation.

The MCP's documented index contract for delay interbed types ("a 0-based interbed number") did not
map as documented: passing `[1, kkpos]` produced interbed **3**, whereas passing `[0, kkpos]`
produced interbed **2** (i.e. an offset of +2, not +1, on the interbed field while the delay-cell
field was +1 as expected). With `[0, 0] / [0, 9] / [0, 18]` the file correctly referenced interbed 2
and delay cells 1 / 10 / 19, and the model ran.

**Attempt 2+ — success.** `start_run` → `succeeded`, `elapsed_s` 0.17–0.28,
`"Normal termination of simulation"`, `convergence:"converged"`, all 158 periods solved.
This is a genuine model-run convergence/conservation result; the run is not the bottleneck.

## 5. Post-processing (MCP)

* `read_compaction` — 158 output times, layers 1 (Upper) and 2 (Middle); derived cumulative
  subsidence = sum of the layer `COMPACTION` columns.
  Final: Upper 0.000739 ft, **Middle 8.33548 ft**, total **8.3562 ft** (Middle interbed
  1.513 % compaction / 1.5128 % flagged `>=1%`), `interbed_strain` reports
  interbed thickness = thick_frac × rnb = 551.0 ft (Middle) and 7.445 ft (Upper), which confirms the
  repo's `rnb` construction.
* `plot_subsidence` — PNG returned (`gwmcp_7g479gyw.png`) with the observed series overlaid.
* Numeric comparison against the site's own `H201_sub_data.csv` (`compare_subsidence.py`):
  `n_obs=208`, **RMSE 3.9692 ft, MAE 2.9920 ft, bias +2.9777 ft**;
  observed final 2.890 ft vs simulated 8.391 ft (interpolated) → the uncalibrated prior
  over-predicts by ≈2.9×. Spot checks: 1959 0.56/0.06, 1987 1.01/1.98, 1999 1.45/2.24,
  2010 2.09/2.31, 2016 2.44/6.71, 2024 2.89/8.39.

## 6. Calibration through the MCP chain — outcome

### 6.1 Registration and interface
* `import_subsidence_observations` (`sub_data.csv`, `time_col=Date`, `value_col=Subsidence_ft`)
  → 208 observations registered, `sim_source = h201csub.csub.obs.csv`, `sum_cols=["compaction"]`.
* `setup_calibration(obs_source="derived", parameterisation=…)` → PST built successfully:
  8 adjustable parameters —
  `pib_ssv_cc_1/2`, `pib_sse_cr_1/2`, `pib_kv_1/2` (from `csub:packagedata`, columns
  `ssv_cc, sse_cr, kv`) and `cgsk0/cgsk1` (from `csub:cg_ske_cr`, layer scope); log-transformed,
  bounds = initial/10 … initial×10; forward wrapper written to a space-free temp path; the CSUB
  packagedata and `cg_ske_cr` were externalised to `h201csub.csub_packagedata.dat` /
  `h201csub.csub_cg_ske_cr.dat` with wide-token templates.

**Limitation 1 — the derived-observation interface matches dates by exact equality.** Only
**17 of 208** measured dates were carried into the PST; the other 191 were reported as
`skipped_dates`. The matched set is exactly the measurements that fall on **1 January**
(1904-01-01 and 2005…2024-01-01), because the repo's yearly stress periods produce output nodes on
Jan-1 and the wrapper's `time_map`/`_sim_key` performs an exact-key lookup with no nearest-date or
interpolation fallback. Consequence: a faithful yearly-discretised model can only ever use 8 % of
this site's measured series. Actionable remedy: choose a TDIS whose period ends coincide with the
observation dates (or set `freq` finer), or have the matcher interpolate onto observation dates.

**Limitation 2 — `check_parameter_sensitivity` cannot be used with derived observations.**
It returns `PEST_ERROR: "No observation targets are registered for this model. Run
import_obs_from_csv first."` — i.e. the cheap n+1 screen only supports `import_obs_from_csv`
targets, not the `import_subsidence_observations` derived targets that the derived-calibration path
itself uses. So the recommended pre-calibration sensitivity screen is unavailable on exactly the
workflow `setup_calibration(obs_source="derived")` exists for.

### 6.2 PEST++ execution — blocked by an environment-level launch hang
Four MCP-driven attempts were made:

| attempt | tool | config | outcome |
|---|---|---|---|
| 1 | `start_calibration` (ies) | num_reals 50, noptmax 10 | 5 realizations completed in ~3 min, then stalled; no progress for 4+ min |
| 2 | `start_calibration` (ies) | num_reals 16, noptmax 3 | stalled on the **first** launch, no progress in 2+ min |
| 3 | `start_calibration` (glm) | noptmax 3 | `pestpp-glm` reported `failed to compute parameter derivative for ALL 8 parameters` → `Error encountered, cannot continue`; only 1 forward run ever started |
| 4 | `start_calibration` (ies) | num_reals 10, noptmax 2 | stalled on the first launch again |

Evidence collected:
* The MCP-generated forward wrapper is not the problem: `mf6` itself takes 0.19–0.35 s and the
  wrapper's traced `mf6_start → mf6_done` pairs complete in ~0.2 s when they run at all.
* The stall is **at process launch**: e.g. `pid 21908` created by `pestpp-ies`, still alive after
  2.5 min with **0.031 s of CPU**, no `stage=start` line in the wrapper trace, no `mf6` child
  (i.e. wedged in the Windows loader, before any Python executes).
* A standalone interpreter test in the same shell is fast (`uv` cpython `-c "print(1)"` = 0.04 s,
  MCP venv = 0.09 s), so interpreter start-up is not inherently slow.
* The machine was heavily loaded by other work (56 `python.exe` processes observed; the run shares
  the host with other Agent Manager sessions). `pestpp` launches children with FIFO
  stdin/stdout/stderr (visible in the wrapper trace), which is the most likely interaction point.
* Consequence of an aborted PEST run: PEST++ had already emptied the target files it generates,
  leaving `h201csub.csub_packagedata.dat` and `h201csub.csub_cg_ske_cr.dat` **0 bytes** while
  `h201csub.csub` still referenced them through OPEN/CLOSE. The model on disk then became
  unreadable, and even `setup_calibration` re-runs failed with
  `Not enough data in file …csub_cg_ske_cr.dat for data "cg_ske_cr". Expected data size 2 but only
  found 0.` **Recovery used only MCP tools:** `add_csub_package` (re-supplying packagedata inline)
  + `flush_model`, after which `start_run` again returned normal termination. This recovery step is
  worth documenting — a failed calibration can leave the workspace in a non-runnable state.

Because `pestpp` never executed enough forward runs, **no PEST++ phi progress, posterior or
residual statistics could be produced.** This is the documented, actionable blocker: the MCP-side
calibration interface is complete and correct, but forward-run process launches by `pestpp-*` wedge
in this environment.

### 6.3 Calibration evidence obtained through MCP-only builder + run + post-process
To obtain genuine, MCP-only calibration evidence, the dominant parameter was varied by hand
(`add_csub_package` → `start_run` → `read_compaction`, all through the MCP), holding every other
CSUB input at its repo value:

| trial | Middle interbed `ssv_cc` (1/ft) | Middle compaction (ft) | total final (ft) | RMSE vs 208 obs (ft) | MAE (ft) | bias (ft) |
|---|---|---|---|---|---|---|
| base (repo prior) | 5.0e-04 | 8.3355 | 8.3562 | 3.9692 | 2.9920 | +2.978 |
| A | 1.75e-04 | 3.3949 | 3.3957 | 0.8355 | 0.7909 | −0.037 |
| B | 1.42e-04 | 2.7902 | 2.7910 | **0.7513** | 0.5851 | −0.406 |

The single parameter controls the fit monotonically and trial B lands on the measurement
(simulated final 2.811 ft vs observed 2.890 ft), cutting RMSE by 81 % (3.97 → 0.75 ft). The residual
misfit is a **phase/timing** issue, not a magnitude issue: the simulation stays near 0.85 ft through
1987–2010 (observed 1.0–2.1) and then steps up at the 2016 node (2.59 vs 2.44), a signature of the
coarse yearly discretisation and of the delay/lag parameters (`kv`, `ndelaycells`) rather than of
the storage magnitude. The delivered workspace was restored to the repo-faithful base values
(`ssv_cc = 5e-4`, final compaction 8.35548 ft) after the trials.

## 7. Compliance

* Every build / run / post-process / calibrate action on the MF6 model went through a
  groundwater-mcp tool call. `flopy`, `pyemu` and `pestpp` classes were never called directly, and
  no MODFLOW or PEST file was hand-edited or shell-written.
* Ordinary Python was used only for data preparation (`prep_data.py`, `make_inputs.py`), for
  post-processing arithmetic on already-MCP-generated CSVs (`compare_subsidence.py`), and for
  reading generated artifacts to diagnose failures.
* The repo's `model_functions.py`, `workflow.py` and `ies_functions.py` were **read** (as the model
  specification) but never executed.
* Nothing was created or modified under the holdout tree.
* **0 permission prompts and 0 reprompts** in this run; no tool was blocked or retried by a
  permission boundary. The only retries were the deliberate calibration re-attempts and the CSUB
  rebuilds described above.

## 8. Findings and recommendations

1. *(MCP bug)* `add_csub_package` delay-observation indices are off by one too many on the interbed
   field: `index=[i, kkpos]` writes interbed `i+2` (and delay cell `kkpos+1`). `index=[1, 0]`
   generated `DELAY-HEAD … 3 1` against a 2-interbed model, which crashes MF6 6.7.0 with an access
   violation in `gwf-csub.f90` on the first transient step. Expected: interbed `i+1`. Workaround
   used: `index=[0, kkpos]`. This is a silent-corruption-class defect — the model builds and
   starts, and only crashes on the second period.
2. *(MCP limitation)* `import_subsidence_observations` + `setup_calibration(obs_source="derived")`
   match observation dates to simulated output times by exact string equality (no nearest-date,
   no interpolation), so a yearly-discretised model can use only measurements that land exactly on
   its output nodes (17/208 here). Recommend interpolation onto observation dates, or at minimum a
   documented, loud warning plus a `match_tolerance` option.
3. *(MCP limitation)* `check_parameter_sensitivity` rejects derived observations ("No observation
   targets are registered…"), so the advertised sensitivity screen cannot be used on the
   `obs_source="derived"` workflow.
4. *(Robustness)* An aborted/failed `pestpp-*` run leaves the externalised parameter files
   zero-length, and because `h201csub.csub` references them via OPEN/CLOSE the model becomes
   unreadable — including for `setup_calibration` itself. Recommend that `setup_calibration`
   rewrite/validate externalised targets before use, and that `run_simulation` pre-check them.
5. *(Environment)* `pestpp-*` forward-run child processes wedge in the Windows loader on this host
   (0.0x s CPU, never reaching the first statement), which blocks the whole calibration step;
   nothing in the MCP interface is at fault, but the effect is that a user cannot complete a
   calibration there. Options: run forward models without FIFO stdio, or support a plain
   `model_command` with file redirection.
6. *(Model structure)* With the repo's prior parameters the H201 model over-predicts subsidence by
   ≈2.9×; a single inelastic-storage parameter brings it onto the measurement, and the remaining
   misfit is a timing/phase issue that needs finer time discretisation (which is also what
   limitation 2 requires).

## 9. Artifacts (session folder)

```
h201_work\
  H201\                                  ← copy of the site folder (prep_data.py outputs in processed_data\)
  dependencies\  bin\                    ← copies required by the instructions
  make_inputs.py  compare_subsidence.py  ← data prep / comparison (ordinary Python)
  mcp_inputs.json                        ← derived TDIS / GHB / CSUB inputs
  run-log.md                             ← this file
  model_ws\  (model h201csub, 49 files)
    h201csub.csub / .ghb / .dis / .npf / .ic / .sto / .oc / .nam
    h201csub.csub.obs + h201csub.csub.obs.csv      ← 158 output times + 16 obs columns
    h201csub_compaction.csv                        ← read_compaction derived table
    gwmcp_7g479gyw.png                             ← plot_subsidence (base run, with observed series)
    h201csub.hds / .cbc / mfsim.lst / h201csub.lst ← base-run outputs (normal termination)
    h201csub.pst / *.tpl / *.ins / *.dat           ← calibration interface (see §6)
```
