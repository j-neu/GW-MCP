# run-log.md — Phase 6d target 9, rerun-5 (closed-book)

Target: `1DSubsidenceModeling-MF6CSUB` (github.com/leila-saberi/1DSubsidenceModeling-MF6CSUB, branch
`Multi-IB`, commit `ff5ef1deafd9aaa228440bee9736f776233f8d74`), site **H201** (repo's own `__main__` example).
Built and run **entirely through groundwater-mcp tools** (MF6 CSUB).

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-target9-csub-rerun5`

---

## 1. Stack (check_environment)

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| numpy / scipy / pandas | 2.4.4 / 1.17.1 / 2.3.x |
| geopandas / rasterio / matplotlib | 1.1.3 / 1.5.0 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / -ies / -da / -sen / -opt | `C:\Users\jakob\.local\bin\` |
| docs index | built (`C:\Users\jakob\.groundwater-mcp\index`) |
| ready / missing | `true` / none |

No permission prompts and no reprompts occurred in this session.

## 2. Data preparation (allowed: inputs only, not the model)

1. Copied `H201\` and `dependencies\` from the holdout into the session folder. The holdout tree was
   **not** modified and nothing was executed inside it (all paths read-only).
2. Ran the repo's own `H201\prep_data.py` (i.e. `prep_data(True)`, delay enabled) with cwd = copied
   `H201\`. It produced `H201\processed_data\H201.model_property_data.csv`, `H201.ts_data.csv`,
   `processed_gwlevels.pdf`.
   * Deviation note: the script does `sys.path.insert(0, "..\dependencies")` but then imports
     `dependencies.project_functions...`, which only resolves when the repo *root* is importable. It
     works in-repo because `workflow.py` inserts the cwd. I therefore ran it with
     `PYTHONPATH=<session root>`; the script itself was used unmodified.
3. Reproduced `initialize_model()`'s time discretisation + GHB series in ordinary Python
   (`prep_model_inputs.py`, `emit_fragments.py`) → `model_inputs.json`, emitting plain JSON. No
   flopy/pyemu MODFLOW or PEST classes were used anywhere outside the MCP.

Processed property table (per aquifer/layer): top 53.8 ft, botm [-77.2, -1117.2] ft,
`cdelay = [nodelay, delay]`, `thick_frac_0 = [7.445037, 22.924098]`, `rnb_0 = [5.909978, 24.035842]`,
`ssv_cc = [5e-5, 5e-4]`, `sse_cr = [0, 3e-6]`, `theta = 0.35`, `kv = 5e-5`,
`cg_theta = [0.3, 0.3]`, `cg_ske_cr = [0, 3e-6]`, `sgm = 1.7`, `sgs = 2.0`, `k = 10.0`, `k33 = 0.01`.

## 3. Tool-call sequence (model build → run → post-process)

```
create_model(h201csub, FEET/DAYS, ws=<session>\mf6\H201csub)
set_simulation(nper=158, perlen=[1,366,365,...], nstp=158×1, start_date_time=1903-12-31,
               newton=true, ims_complexity=simple, outer_maximum=300, linear_acceleration=bicgstab)
add_dis_package(nlay=2, nrow=1, ncol=1, delr=delc=1, top=53.8, botm=[-77.2,-1117.2])
add_npf_package(icelltype=[1,1], k=[10,10], k33=[0.01,0.01], k_units="ft/d")
add_ic_package(strt=53.8)
add_sto_package(iconvert=[0,0], ss=[0,0], sy=[0,0], steady_state=[0])
add_boundary_package(GHB, 158 periods × 2 cells, cond=50000)
add_csub_package(packagedata=2 interbeds, ndelaycells=19, initial_preconsolidation_head=true,
                 specified_initial_interbed_state=true, sgm=[1.7,1.7], sgs=[2,2],
                 cg_theta=[0.3,0.3], cg_ske_cr=[0,3e-6], observations=16 records,
                 filerecords={strainib, package_convergence})
add_oc_package(printrecord BUDGET ALL, saverecord HEAD/BUDGET ALL, hds, cbc)
check_model  -> check_passed=true, 0 errors, 2 warnings (STO ss below 1e-6 -> ss=0 by design)
start_run -> get_job_status -> succeeded, converged, normal termination, 158 periods, 0.22 s
read_compaction / plot_subsidence / compute_water_balance / read_heads / compare_scenarios
```

## 4. Convergence / correctness evidence

* `check_model`: `check_passed: true`; no errors. Only warnings are the expected
  `sto package: specific storage values below checker threshold of 1e-06` (the repo sets `ss=0`).
* Run: `Normal termination of simulation`, all 158 stress periods solved, elapsed 0.16–0.22 s.
* `compute_water_balance` (period 158): GHB inflow 1.0851e-4, GHB outflow -1.0851e-4, net balance
  +2.2e-9; CSUB-CGELASTIC/CSUB-WATERCOMP terms ~1e-19. Water balance closed.
* `read_heads` (layer 1, final period) = 27.24532 ft = exactly the GHB head applied in period 157,
  as expected with `ss=sy=0` (heads are boundary-controlled, so compaction is a pure CSUB response).
* `compare_scenarios(h201csub, h201sc1)`: max head difference 0 (heads identical); only CSUB budget
  terms differ — confirms the two runs differ solely in CSUB parameters.

## 5. Post-processing: simulated vs measured subsidence

`read_compaction` (base/prior run): final cumulative subsidence **7.1888 ft** (layer 1 = 0.0000 ft,
layer 2 = 7.1888 ft); decomposition `INELASTIC-COMPACTION.02 = 7.1872`, `ELASTIC-... = 0.0017`.
`interbed-strain`: interbed 2 (delay, Middle) 1.30 % compaction of 551.0 ft; interbed 1 (no-delay,
Upper) 0. All compaction is driven by the Middle aquifer's late-record head decline to −43 ft
(min processed Middle level −68.2 ft, 2014-05-30).

`plot_subsidence` → `mf6\H201csub\gwmcp_fk639y8_.png` (simulated vs measured overlay, returned).

Residuals vs `H201\source_data\H201_sub_data.csv` at the 17 model times that coincide with measured
dates (see §7 for why only 17):

| run | final sim | RMSE | MAE | bias | max abs |
|---|---|---|---|---|---|
| `h201csub` (prior) | 7.1888 ft | 3.3675 | 2.9018 | +1.8104 | 4.9675 |
| `h201sc1` (scenario) | 2.8684 ft | 1.0999 | 0.7756 | −0.6451 | 2.0325 |
| measured | 2.890 ft (last), 3.050 ft (max) | | | | |

The prior run over-predicts from 2016 onward (r = +4.4 to +5.0 ft). This is a *parameter* effect,
not a build defect: the repo's own shipped `output\SimulatedSubsidence_H201.csv` `base` column is
the **calibrated** run (2.99 ft at 2024-12-01 vs 2.89 ft measured), and the repo's shipped
`ib_results_H201_ibbylayer.xlsx` shows its data assimilation reduced exactly the parameters I chose
to expose (Middle `SSE` 3e-6 → 2.30e-6, `SSV` 5e-4 → 2.57e-4, `KV` 5e-5 → 1.18e-7).

## 6. Calibration (criterion 5) — interface built, PEST++ engine wedged

Interface (all via MCP), `obs_source="derived"`:

* `import_subsidence_observations(H201_sub_data.csv)` → 208 measured values; sim source
  `h201csub.csub.obs.csv`, `sum_cols=["compaction"]`, `time_col="time"`.
* `setup_calibration(parameterisation={packagedata columns [ssv_cc, sse_cr, kv] on layer 1 with
  lower_factor 0.001 / upper_factor 100; csub:cg_ske_cr layer 1}, noptmax=4)` → `h201csub.pst` with
  **4 adjustable parameters** (`ssv_ssv_cc_2` 5e-4, `ssv_sse_cr_2` 3e-6, `ssv_kv_2` 5e-5, `cg` 3e-6,
  all log-transformed), 2 template files (`h201csub.csub_packagedata.dat.tpl`,
  `h201csub.csub_cg_ske_cr.dat.tpl`), an instruction file, and a space-free Python forward wrapper
  (`C:\Users\jakob\AppData\Local\Temp\gwmcp_run_h201csub.py`).
* **17 of the 208 measured dates matched** model output times; the rest were reported as
  `skipped_dates` (see §7).

Engine attempts and evidence:

| attempt | tool | outcome | evidence |
|---|---|---|---|
| 1 | `start_calibration(ies, num_reals=20)` | **wedged** | realizations 0–4 completed, then `run.info` frozen at `realization:5` for >4 min; `pestpp-ies` burning ~1 core (293→313 s CPU/20 s) with **no mf6 and no wrapper child**; wrapper trace showed only 3 `mf6_done` entries, each 0.16–0.19 s |
| 2 | `start_calibration(ies, num_reals=10)` (the single allowed retry) | **wedged** | reached `realization:2` then froze with the same signature (trace stuck at 7 `mf6_done`; `pestpp-ies` +14.8 s CPU/15 s wall; no children) |
| 3 | `start_calibration(glm)` (diagnostic: is the wedge IES-specific?) | **wedged** | died during the first Jacobian perturbation (`run.info` = `par_name:SSV_SSV_CC_2`, `.iobj` header only) — so the wedge is PEST++/host-level, not IES-specific |

All three were stopped with `cancel_job`; after each cancel the externalised CSUB inputs were
**restored to their pristine priors** (verified in `h201csub.csub_packagedata.dat` /
`h201csub.csub_cg_ske_cr.dat`) and the model continued to run normally
(`start_run` → converged, normal termination, 0.158 s).

So **no phi progress, no PEST++ parameter estimates and no PEST++ residual statistics can be
reported** — this is the documented failure required by criterion 5. It is not an MCP-tool defect
and not a model defect: `pestpp-ies` executes each MF6 forward run correctly (0.16–0.19 s) and then
spin-wedges between realizations; the only plausibly related environmental factor is heavy host
contention (~24 unrelated `python.exe` processes were resident, and observed throughput was
~45–85 s wall per realization vs the ~9 s implied by the reference note that a 4-real IES takes
~37 s).

**Actionable recommendations** (in priority order):
1. Re-run `start_calibration(ies, num_reals=10)` on a quiet host; the interface is intact and needs
   no rebuild (`h201csub.pst` + templates + wrapper already exist).
2. If the wedge recurs, use `setup_calibration(..., noptmax=1..2)` to cut the iteration count, or
   reduce `num_reals` to 4–5 so each attempt is short enough to retry cheaply.
3. Build the TDIS at a finer frequency (`freq="1M"` instead of the repo `__main__` default `"Y"`) so
   that all 208 measured dates — not 17 — are matched; this materially improves the observation
   information content and is what the repo's own published runs evidently used (their
   `SimulatedSubsidence_H201.csv` is monthly and their `ib_results` has 10 interbeds, i.e. they ran
   with `quantiles`).

## 7. Deviations from the source model (`model_functions.py` / `prep_data.py`)

1. **`freq="Y"`** kept, being the `__main__` default that defines the H201 example: 122 historic +
   36 predictive periods to 2060-12-31 → 158 periods of 1 time step; only 17 measured subsidence
   dates coincide with model output times. (The repo's *published* outputs are monthly.)
2. **One interbed per aquifer** (`quantiles=None`) as in `model_functions.py`; the repo's shipped
   `ib_results`/published DA used `quantiles` → 10 interbeds. Total clay thickness and the
   `thick_frac × rnb` thickness bookkeeping are identical either way
   (`rnb_i·thick_frac_i` sums to 551.0 ft for the Middle).
3. **`sgs = 2.0`** taken from the processed property table. `model_functions.py:317` passes
   `sgs = prop_df.loc["sgm"]` (1.7) — i.e. `sgm` is used for `sgs`, an apparent bug. Deviation
   recorded; `sgm = 1.7` matches both.
4. **`pcs0 = 0.0` for both interbeds**, matching `model_functions.py:234` (hard-coded `0.0`), which
   overrides the property table's `pcs0 = [-200, +50]`. This is why the prior run produces no
   inelastic compaction before ~2016 (head must drop below 0 ft) while the measurements already show
   ~2.3 ft by 2014 — the residual-negative bias seen in §5 for 2005–2014.
5. **`beta` / `gammaw` not passed** to `add_csub_package`: the MCP's FEET defaults are
   `GAMMAW 62.48` / `BETA 2.227E-08`, verified in the generated `h201csub.csub` — identical to the
   values `model_functions.py:313-314` sets explicitly.
6. **No head OBS6 package**: the repo adds a `ModflowUtlobs` package for layer heads; not needed
   here because heads are read through `read_heads`.
7. **No `budgetcsv_filerecord`**: `add_oc_package` exposes no `budgetcsv` argument (`budget.csv` in
   the repo build); head/budget binary + print records are equivalent for this workflow.
8. **Faithful reproduction of two `initialize_model` quirks** (deliberate, to stay bit-comparable):
   (a) the injected `start_datetime − 1 day` (1903-12-31) becomes period 0, a 1-day steady period;
   (b) the prediction loop writes `ghbdata[kper + kper_pred]` with `kper` already incremented, so it
   **overwrites the last historic GHB key**. The resulting period→head mapping, including the
   one-period lag of GHB heads behind `perlen`, is the repo's own.
9. **`start_date_time = 1903-12-31`** and IC `strt = 53.8 ft` (= max processed groundwater level,
   which equals the model top) as computed by `initialize_model`.

## 8. MCP-only compliance

Every action that builds, runs, post-processes or parameterises the MF6 model went through a
groundwater-mcp tool call: `create_model`, `set_simulation`, `add_dis_package`, `add_npf_package`,
`add_ic_package`, `add_sto_package`, `add_boundary_package`, `add_csub_package`, `add_oc_package`,
`check_model`, `start_run`, `get_job_status`, `cancel_job`, `read_heads`, `read_compaction`,
`compute_water_balance`, `plot_subsidence`, `compare_scenarios`, `clone_model`,
`import_subsidence_observations`, `setup_calibration`, `start_calibration`.

Ordinary Python was used only for (a) running the repo's `prep_data.py` and transforming the source
CSVs into plain JSON inputs, and (b) reading **my own** model outputs to tabulate residuals
(`residuals_vs_measured.py`, `compare_repo_outputs.py`, `decompose_compaction.py`). No flopy/pyemu
MODFLOW or PEST class was called directly, no MODFLOW/PEST file was hand-edited, and the repo's
`model_functions.py` / `workflow.py` / `ies_functions.py` were **never executed**.

## 9. Artifacts

| artifact | path |
|---|---|
| model workspace | `mf6\H201csub\` |
| scenario workspace | `mf6\H201csub_sc1\` |
| compaction series | `mf6\H201csub\h201csub_compaction.csv` |
| subsidence plot | `mf6\H201csub\gwmcp_fk639y8_.png` |
| PEST input set | `mf6\H201csub\h201csub.pst`, `*.tpl`, `*.ins` |
| prep outputs | `H201\processed_data\H201.model_property_data.csv`, `H201.ts_data.csv` |
| prepared model inputs | `model_inputs.json`, `mcp_fragments.json` |
| helper scripts | `prep_model_inputs.py`, `emit_fragments.py`, `residuals_vs_measured.py`, `compare_repo_outputs.py`, `decompose_compaction.py` |
