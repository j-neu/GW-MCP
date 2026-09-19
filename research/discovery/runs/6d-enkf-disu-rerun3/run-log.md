# Run log — Phase 6d target 8: MF6_EnKF_DISU (Neckartal DE), sequential DA via groundwater-mcp

Date: 2026-09-15 · Session worktree: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun3`
Target: `D:\Claude Projects\GW-MCP-holdout\selected\MF6_EnKF_DISU` (github.com/JanGei/MF6_EnKF_DISU, cloned 2026-09-13)

**Outcome in one line:** steps 1–6 and 8 completed through MCP tools only; the sequential DA (step 7)
**could not run in the mandated workspace** — `start_calibration(method="da")` stalls inside `pestpp-da`
(100 % CPU, no child MODFLOW runs, log frozen at "making runs"). Root cause isolated by controlled
experiment: with a **space-free** copy of the same model the identical MCP configuration completes the full
6-cycle assimilation in **7.8 min**. The difference is the model command the MCP generates for a
space-containing workspace path (Python wrapper) versus none (direct `mf6.exe`).

---

## 0. Environment (`check_environment`)

| | |
|---|---|
| Python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio / numpy / scipy / matplotlib | 1.1.3 / 1.5.0 / 2.4.4 / 1.17.1 / 3.10.8 |
| binaries | mf6, pestpp-glm, pestpp-ies, pestpp-sen, pestpp-opt, pestpp-da (all present) |
| docs index | built |
| workspace root | `C:\Users\jakob\.groundwater-mcp\workspaces` |
| `ready` | true, `missing` = {} |

**Licence check (step 1 request):** a recursive search of the target repository for
`LICENSE* / COPYING* / *.license` returns **nothing** — the repository (as cloned 2026-09-13) has **no licence
file**, so it is unlicensed (all rights reserved) by default; use for comparison/validation only.

## 1. Reconnaissance (read-only, target repo files only)

* Runnable model: `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim` — `mfsim.nam` + `flow.nam`
  (single GWF model `flow`): DISU 31 831 nodes / NJA 198 261 / 31 522 active, VERTICES 11 430 + CELL2D
  present; `DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO`; external arrays in `flow_input\`; shipped outputs
  `flow_output\flow.hds/.cbc`.
* `sim.tdis`: `TIME_UNITS days`, **NPER 6**, each period **1 × 1.0-day** step, no calendar start date.
* `flow.disu`: `LENGTH_UNITS meters`. `NEWTON` on, IMS `COMPLEXITY complex`.
* Shipped 6-period run: **Normal termination, Elapsed run time 6.902 s** (`mfsim.lst`) → single runs are cheap.
* K field: 10 325 distinct values, active range 0.864 – 86 400 m/d, geometric mean 10.18 (dominant zones
  8.64 and 0.864 m/d; 351 gravel cells at 86 400).
* Gauge data: `csv data\Pegel.csv` (wide, day-first dates, −9999 = missing) + `csv data\Pegel_Cell_ID.csv`
  (14 gauges → scalar DISU node ids). Around 2017 the network is an irregular ~weekly survey, and only on
  some dates are many gauges reported at once.
* Repo's own EnKF (`main.py` / `Transient_Run.py` / `generator.py`, 15 members, pilot-point K fields):
  assimilates on a daily loop starting **2017-01-30**, only on dates present in `Pegel.csv`, and only when
  > 7 gauges report. **Not executed** (raw flopy; out of scope for this run).

## 2. Adopt (`adopt_model`)

`adopt_model(name="neckartal", workspace=<sim dir>, allow_modify=true, units="METERS", time_units="DAYS")`
→ adopted, `model_names=["flow"]`, DISU 1 layer / 31 831 nodes / 198 261 NJA / 31 522 active.
No grid rebuild, no file renaming. (A safety copy of the untouched sim directory was made at
`<worktree>\_pristine_sim_backup\sim` before any write.)

## 3. `check_model`

Clean: `check_passed=true`, `warnings=[]`, `errors=[]` (all NPF/CHD/RCH/RIV/WEL/STO checks pass).

## 4. Re-express the run as single-step DA cycles (`set_simulation`)

`set_simulation(model, 1, [7.0], [1], ims_complexity="complex")` → NPER 1, NSTP 1 (`written:false`, staged;
flushed by the next call). TDIS was **not** hand-edited.

Cycle design (decision, documented deviation):

| cycle | ends on (Pegel date) | perlen (d) | gauges reported |
|---|---|---|---|
| 0 | 2017-01-30 | 1 | 13 |
| 1 | 2017-02-06 | 7 | 9 |
| 2 | 2017-02-13 | 7 | 3 |
| 3 | 2017-02-20 | 7 | 2 |
| 4 | 2017-02-27 | 7 | 3 |
| 5 | 2017-03-06 | 7 | 3 |

Rationale: the shipped model carries no calendar dates, the repo's EnKF starts at 2017-01-30 with the
shipped IC as the state, and the OBS-CSV instruction file only reads the end-of-cycle value with one time
step per period. Cycle 0 is the repo's own first assimilation day (1 day from the IC); cycles 1–5 are the
weekly survey cadence (7 days), so each cycle ends exactly on an observation date (no time offset).
Perlen is supplied per cycle through the DA parameter cycle table (the MCP templates TDIS perlen), so this
is cycle-table-driven rather than six hand-written periods.

## 5. Register the gauges

Data prep with ordinary Python only (`da_prep\prep_obs.py`, no flopy/pyemu):
`Pegel.csv` (wide → long, day-first, −9999 → dropped) joined to `Pegel_Cell_ID.csv`
→ `da_prep\obs_long.csv` (`site,date,value,Cell_ID,cycle`, 33 rows, 13 gauges; **Ne-507 is −9999 on every
cycle date**, so 13 of 14 gauges are registered).

`import_obs_from_csv(csv_file=obs_long.csv, cellid_col="Cell_ID", site_col="site", date_col="date",
value_col="value", obs_type="HEAD")` → `site_count=13`, `total_records=33`, site names preserved, node ids
converted 0-based → 1-based (e.g. Ne-401 14119 → 14120), `flow.obs` + `flow_obs_summary.csv` written.

**Mapping verification** (step 5 asks for this): baseline `run_simulation` → converged in 3.1 s. Independently
cross-checked the shipped `strt`/`K`/`top`/`bot`/`idomain` at the 13 nodes:

* all 13 nodes are active cells inside their layer interval,
* IC head − gauge reading is **+2.7 … +9.3 m for all 13 gauges** (simulated too high), with the correct
  relative ordering, i.e. a consistent *baseline offset*, not a node-mapping error.

Baseline gauge fit (`compare_to_observed`): n = 13, **RMSE 3.80 m, bias −3.69 m, R² −0.68**. The shipped
head state is simply not calibrated to the 2017 gauges (consistent with the repo overwriting `IC.strt` with
its own spin-up field `Final_h_field.mat`). This is the arbitrary phi scale the task anticipated.

## 6. DA setup (`setup_da_control`) — mandated configuration

```
parameterisation = {"k": {"target": "npf:k", "scope": "all", "initial": 10.1786}}   # log-transformed
cycles           = [0..5]
obs_cycles       = {13 sites -> {cycle: Pegel value}}          (blanks left for cycles without data)
par_cycles       = {"perlen": {0:1, 1:7, 2:7, 3:7, 4:7, 5:7}}
num_reals        = 30, noptmax = 1, use_simulated_states = True
```

* **The call exceeded the MCP client timeout** (`-32001 Request timed out`, ~90 s) **but completed
  server-side** — the model's `.gwmcp_history.jsonl` records *"wrote PEST control (13 observations)"* and all
  artefacts exist. The caller therefore never receives the tool's own result object (= capability gap b).
* Generated: `neckartal.pst` (v2, `da_num_reals 30`, both cycle tables, `da_use_simulated_states True`,
  `noptmax 1`), `flow_k.dat.tpl`, `flow_strt.dat.tpl`, `modflowsim.tdis.tpl`, `flow_head.obs.csv.ins`,
  `neckartal_da_obs_cycle_tbl.csv`, `neckartal_da_par_cycle_tbl.csv`, `neckartal.par_data.csv` etc.
* Parameter inventory: **1 adjustable `k` (partrans log, bounds 1.01786 – 101.786) + 13 `head_state`
  parameters + 1 fixed `perlen`** → `n_state_parameters = 13`.
* Cycle tables verified: obs cycle table has the correct per-cycle gauge values (cycle 0 = 2017-01-30,
  cycle 5 = 2017-03-06) with blanks where a gauge has no record; par cycle table = `perlen 1,7,7,7,7,7`.
* State bounds: `strt ± max(obs spread, |strt − mean(obs)|, 5 m)` → 5 – 10 m per site.
* **Side effect to be aware of:** `scope="all"` writes **one wide token per cell** (31 522 tokens,
  `flow_k.dat.tpl` = 605 kB) and the target `flow_k.dat` becomes a **single uniform value** (10.1786).
  The shipped 10 325-zone K field is thereby replaced by one uniform K (`flow_k_pristine.npy` is saved but
  no MCP tool restores it).

## 7. `start_calibration(method="da")` — blocked in the mandated workspace

Three attempts, all in `...\MODFLOW 6\sim` (workspace path contains spaces):

| job | reals | observed behaviour |
|---|---|---|
| `235baac24590` | 30 | MF6 realizations did run (`mfsim.lst` writes at 20:18:38, 20:20:50; ~90–130 s wall each, MF6 itself 1.2 s) → `run.info` reached `da_cycle:0 realization:3` and then **stopped advancing for > 10 min**; `pestpp-da` burned 100 % of a core (322 s CPU), no `mf6` child process, no file writes; `neckartal.log` frozen at *"making runs"*. |
| `157f324dd67d` | 5 | Stalled at `da_cycle:0 realization:0` for > 7 min (100 % CPU, 0 file writes after 20:30:10); two **idle** python wrapper processes left behind. |
| `4a1ba22d1fdd` | 5 | Repeat with **no external polling of the workspace at all** (to rule out my own file access): realization 0's MF6 run only completed after ~5 min, realization 1 then stalled > 5 min. → the stall is not an artefact of observation. |

All three were stopped with `cancel_job`, which returned `cancelled` and cleanly removed the whole process
tree (verified: no `pestpp-*`/`mf6` processes left).

Additional probing in the same workspace:

* `setup_da_control(scope="cells", 12 nodes)` → `INVALID_INPUT`: *"Parameterisation covers 12 of 31831
  cells; 31819 cells are unassigned. Add a parameter with scope='all' (or cover every cell)"* — i.e. **no
  compact K parameterisation exists**: any K parameter must cover the whole array, so the template always
  carries one token per cell (31 522).
* DISU `cells` entries must be **scalar node ids** (passing `[layer, node]` → `INVALID_INPUT`).
* `parameterisation={}` → `INVALID_INPUT` ("must name at least one parameter").
* `clone_model(necksrc → space-free dir)` → `CLONE_FAILED` (flopy `ihc`/`_get_data` error on this DISU model).
* `adopt_model` of a copy nested one level too deep → `MODEL_FILES_NOT_FOUND` (my copy layout, not an MCP defect).

### 7b. Controlled experiment — root cause of the stall

The shipped input set was copied (ordinary file copy) to a **space-free** workspace
`C:\Users\jakob\AppData\Local\Temp\kilo\neckns`, adopted via `adopt_model(name="neckns", ...)`, reduced with
`set_simulation(1,[1],[1])`, re-registered with the same `import_obs_from_csv`, and run through the **same**
`setup_da_control` configuration and `start_calibration(da, num_reals=5)`.

| | mandated workspace (`...Claude Projects...`) | space-free copy (`...Temp\kilo\neckns`) |
|---|---|---|
| `setup_da_control` | client timeout (~90 s), response lost | **returned in seconds** |
| `.pst` model command line | `"D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe" C:\Users\jakob\AppData\Local\Temp\gwmcp_run_neckartal.py` | `C:\Users\jakob\.local\bin\mf6.exe` |
| DA result | stalls indefinitely at 100 % CPU | **succeeded: 6 cycles in 7.8 min, 42 model runs** |

The MCP generates the Python-wrapper command precisely because the workspace path contains spaces (its own
`setup_pest_control` documentation warns that pestpp cannot run space-containing paths / wrapper scripts on
Windows). In practice that wrapper command is **not drivable by `pestpp-da` v5.2.16**: `pestpp-da` spins at
100 % CPU inside *"making runs"* while the wrapper processes sit idle and no MODFLOW run is launched.
Direct `mf6.exe` works. Everything else (model, grid, observations, parameterisation, cycle tables) is
identical, which is why this is recorded as the root cause and not as "the model is too big".

## 8. DA results (space-free control run, 5 reals, noptmax 1, shipped model + scope-all uniform K)

Per-cycle phi (post-update, from `summarise_da` / `neckns.global.phi.actual.csv`):

| cycle | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| post-update phi | 286.48 | 64.11 | 19.44 | 19.46 | 19.14 | **18.94** |
| obs used | 13 | 9 | 3 | 2 | 3 | 3 |

* Cycle-0 prior → posterior: **phi mean 349.89 (std 16.14, min 331.70, max 373.35) → 286.48 (std 17.27)**,
  i.e. the gauge observations *did* inform the parameter (−18 % phi; RMSE 5.19 → 4.70 m over 13 gauges).
* Final cycle: **phi mean 18.9381, std 1.68 × 10⁻⁵** (ensemble fully collapsed), 3 observations
  (Ne-604, Ne-803, Ne-806 of 2017-03-06) → RMSE 2.51 m, bias −2.47 m (`r_squared −2.43` is meaningless with
  3 near-identical observations).
* **Posterior parameter statistics (final cycle):** `k` mean = **101.786 = exactly `parubnd`**, std 0,
  **5/5 realizations at the upper bound**; `head_state`: 13 parameters, 25 of 65 parameter-realizations
  (38.5 %) at their lower bound; no parameter retains ensemble spread after cycle 1.
* Post-DA model check (`run_simulation` + `compare_to_observed`, same posterior state, 13 sites vs their mean
  observed values): **RMSE 3.85 → 2.55 m, bias −3.74 → −2.38 m, R² −0.72 → +0.24**.
* **Interpretation (no fabricated fit):** per-cycle phi is *not* comparable across cycles because the gauge
  network thins out (13→9→3→2→3→3); most of the cycle-1→2 drop is the observation-count change. The
  assimilation machinery is demonstrably correct, but with a single uniform K parameter replacing a
  10 325-zone K field the parameter is **unidentifiable and rails at its bound**, so the posterior is
  numerically consistent yet physically degenerate. The gauge/head baseline of the shipped state is
  uncalibrated (R² < 0 before the DA), which sets the phi scale.

## 9. Post-processing (`plot_heads_map`, `compare_to_observed`, `read_simulated_observations`)

* `plot_heads_map` **works on this vertex-carrying DISU grid** and renders the real geometry
  (Gauss-Krüger coordinates x ≈ 3.496–3.510 × 10⁶, y ≈ 5.371–5.377 × 10⁶, matching the repo's pilot-point
  coordinates): shipped model → `_pristine_sim_backup\sim\gwmcp_*.png` (layer 0, kstpkper (0,5)),
  DA posterior → `C:\Users\jakob\AppData\Local\Temp\kilo\neckns\gwmcp_*.png` (kstpkper (0,0)).
* `compare_to_observed` → residuals CSV + scatter PNG (`necksrc_obs_residuals.csv` / `_fit.png`,
  `neckns_obs_residuals.csv` / `_fit.png`); `read_simulated_observations` returns all 13 site values.
* Because the DA could not be produced in the mandated workspace, the "final cycle" gauge fit above is taken
  from the space-free control run; the shipped-model fit (RMSE 3.85 m, 6 × 1-day periods) is reported from
  an untouched copy of the shipped input set (`necksrc`).

## 10. Deviations from the source model

1. **TDIS re-expression:** shipped 6 × 1-day periods → 1 period / 1 time step per cycle, cycle lengths
   1, 7, 7, 7, 7, 7 d supplied through the DA parameter cycle table (36-day simulated window vs 6 d shipped).
   Required by the OBS-CSV instruction-file semantics; done with `set_simulation`, not by editing files.
2. **Calendar dates:** the model stores none; the cycle↔date mapping (cycle k ends on the k-th Pegel survey
   date, IC ≈ 2017-01-29) is my reconstruction from the repo's EnKF start date 2017-01-30.
3. **Method change:** bespoke EnKF (15 members, pilot-point K, damped state+parameter update, daily forcing
   updates) → **PEST++-DA v5.2.16** ensemble smoother with sequential state carry-over
   (`use_simulated_states`, 13 dynamic states transferred obs→par per cycle).
4. **K parameterisation:** pilot-point/kriged heterogeneous K → **single uniform K** (scope "all"). This is
   forced by the tool ("cells" scope is rejected unless every cell is covered) and is the largest physical
   deviation; it is why the posterior K rails at its bound.
5. **Forcing:** the repo rewrites recharge/pumping every day inside its own loop; the MCP DA only
   cycle-drives `perlen`, so RCH/RIV/WEL/CHD stay at the shipped period-1 values for the whole window.
6. **Observation subset:** 13 of 14 gauges (Ne-507 missing for all cycle dates) and 33 site-dates, versus the
   repo's daily assimilation on dates where Pegel has a row.
7. **Workspace:** the mandated DA ran (and stalled) in the shipped `sim` directory; the delivered DA results
   come from an identical copy of the same input set at a space-free path. The mandated workspace is left in
   the DA-rewired state (`flow.npf` K = OPEN/CLOSE `flow_k.dat` uniform; `flow_strt.dat` = posterior state;
   `modflowsim.tdis` NPER 1; `.pst`/templates present). There is no MCP tool to restore the pristine K in
   place — re-adopt from the untouched source (or `<worktree>\_pristine_sim_backup\sim`) if needed.

## 11. Capability gaps found (for the MCP maintainers)

| # | Gap | Evidence |
|---|---|---|
| a | **Sequential DA cannot run when the workspace path contains spaces.** The MCP falls back to a Python wrapper model command; `pestpp-da` v5.2.16 never drives it (100 % CPU spin in "making runs", no MODFLOW child, no file writes, indefinite). | 3 jobs stall in `...\Claude Projects\...`; identical config at a space-free path succeeds in 7.8 min; `.pst` command line differs (`python.exe wrapper.py` vs `mf6.exe`). |
| b | `setup_da_control` on a 31.8 k-node DISU model takes > 90 s (31 522-token template) and **exceeds the MCP client timeout**, so the tool's result object is lost even though the call completes. | `MCP error -32001`, artefacts + `.gwmcp_history.jsonl` entry present. |
| c | **No compact K parameterisation:** every K parameter must cover all cells → one template token per cell; a 12-cell subset is refused; `parameterisation={}` is refused. Heterogeneous / pilot-point-style K (what the repo's EnKF actually does) is impossible. | `INVALID_INPUT` messages quoted in §7. |
| d | `clone_model` fails on this DISU model (flopy `ihc`/`_get_data` error), so the documented "copy before scenario" route is unavailable here. | `CLONE_FAILED` |
| e | No tool to restore a pre-DA array (`flow_k_pristine.npy` is written by `setup_da_control` but nothing consumes it). | §10.7 |

Not worked around: no flopy/pyemu MODFLOW or PEST class was called, no MODFLOW/PEST file was hand-edited, and
the repo's EnKF scripts were not executed. The only "outside" actions were ordinary file copies for a safety
back-up of the shipped inputs and for the space-free control workspace, and ordinary Python for the
`Pegel.csv` → observation-table reshape that was then imported with `import_obs_from_csv`.

## 12. Tool-call sequence (abridged)

`check_environment` → `adopt_model(neckartal)` → `summarise_model` → `check_model` → `set_simulation(1,7,1)` →
`import_obs_from_csv` → `run_simulation` → `read_simulated_observations` → `compare_to_observed` →
`setup_da_control` (timeout/C) → `start_calibration(da,30)` (stall) → `cancel_job` →
`start_calibration(da,5)` (stall) → `cancel_job` → `start_calibration(da,5)` (quiet re-run, stall) →
`cancel_job` → `setup_da_control(cells)` (INVALID_INPUT) → `setup_da_control({})` (INVALID_INPUT) →
`adopt_model(necksrc)` → `import_obs_from_csv` → `run_simulation` → `compare_to_observed` +
`plot_heads_map` → `clone_model` (CLONE_FAILED) → file copy to space-free path → `adopt_model(neckns)` →
`set_simulation` → `import_obs_from_csv` → `setup_da_control` (OK, direct `mf6.exe`) →
`start_calibration(da,5)` → **succeeded 7.8 min** → `get_job_status` → `summarise_da` → `run_simulation` →
`compare_to_observed` + `plot_heads_map`.

## 13. Artefacts

* Observations: `da_prep\obs_long.csv`, `da_prep\prep_obs.py`
* Mandated workspace (stalled, DA-rewired): `...\MODFLOW 6\sim\neckartal.pst`, `flow_k.dat.tpl`,
  `flow_strt.dat.tpl`, `neckartal_da_obs_cycle_tbl.csv`, `neckartal_da_par_cycle_tbl.csv`, `neckartal.log`,
  `neckartal.rec`, `run.info`
* Shipped-model postprocess: `<worktree>\_pristine_sim_backup\sim\{necksrc_obs_residuals.csv,
  necksrc_obs_fit.png, gwmcp_*.png}`
* Successful DA control run: `C:\Users\jakob\AppData\Local\Temp\kilo\neckns\{neckns.pst, neckns.log,
  neckns.global.phi.actual.csv, neckns.global.*.pe.csv, neckns.global.*.pcs.csv, neckns.5.1.par.csv,
  neckns.5.1.obs.csv, neckns_da_residuals.csv, neckns_obs_fit.png, gwmcp_*.png}`
