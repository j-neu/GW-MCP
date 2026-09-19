# Run log — Phase 6d target 8: MF6_EnKF_DISU (Neckartal, DE), sequential DA

**Date:** 2026-09-16
**Session worktree:** `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun6`
**Data:** `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (github.com/JanGei/MF6_EnKF_DISU, cloned 2026-09-13)
**Constraint:** MCP-only for everything that builds/runs/post-processes/assimilates the MF6 model.
Ordinary Python used only to reshape the gauge CSVs into the observation table.

**OUTCOME: steps 1–6 and 8 completed. Step 7 (the sequential DA execution) is BLOCKED — the
MCP DA forward-run path deadlocks reproducibly (4/4 attempts). No workaround was attempted.**

---

## 0. Licence check

`Get-ChildItem -Filter LICENSE* -Recurse` over the repo root → **no LICENSE file present**
(confirmed empty). The repo root holds only `main.py`, `Transient_Run.py`, `generator.py`,
`Objectify*.py`, `functions.py`, `Plot_Unstrucuted*.py`, `test.py`, `Final_h_field.mat`,
`K_field in t1`, `csv data/`, `data/`, `Modellgebiet/`, `NeckartalModel1718/`. Treat as
unlicensed / no reuse grant.

## 1. Environment (`check_environment`, first call)

| item | value |
|---|---|
| Python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / -ies / -sen / -opt / **-da** | all present in `C:\Users\jakob\.local\bin\` |
| docs index | built |
| `ready` | `true`, `missing.packages=[]`, `missing.binaries=[]` |

## 2. Model specification (read from the target repo — the model is the spec)

Runnable MF6 set: `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim\`

- `mfsim.nam` → single GWF model `flow` (`flow.nam`), solution group 1, `sim.ims`.
- `sim.tdis`: `TIME_UNITS days`, **NPER 6**, six periods of `1.0` day × 1 step.
- `flow.disu`: **NODES 31831, NJA 198261, NVERT 11430**, `LENGTH_UNITS meters`;
  top/bot/area/idomain/iac/ja/ihc/cl12/hwva/angldegx all `OPEN/CLOSE` into `flow_input\`;
  **VERTICES + CELL2D present**.
- `flow.npf`: `K33OVERK`, `icelltype`/`k`/`k33` external; **k = 10,413 unique values**
  (range 0.864 – 86,400 m/d) — matches the task brief exactly.
- `flow.ic`: `strt` external (`1e30` sentinel on the 309 inactive nodes; active 305.16–345.5 m).
- `flow.chd` (MAXBOUND 6), `flow.rch` (10182), `flow.riv` (686), `flow.wel` (610):
  **period-1 data only**, reused by all shipped periods.
- `flow.sto`: `iconvert 1`, `ss 1e-4`, `sy 0.01`, TRANSIENT periods 1–6.
- `flow.oc`: budget + head FILEOUT into `flow_output\`.
- `flow.nam`: `NEWTON` active.
- Grid counts confirmed independently: 31,522 active / 309 inactive.

## 3. Tool-call sequence

| # | tool | result |
|---|---|---|
| 1 | `check_environment` | stack ready |
| 2 | `adopt_model(name="neckartal_disu", workspace=<sim dir>, allow_modify=true, units=METERS, time_units=DAYS)` | adopted, `model_names=["flow"]` |
| 3 | `check_model` | **clean** (no errors, no warnings) |
| 4 | `model_status` | `runnable: true`, nothing missing |
| 5 | `set_simulation(nper=1, perlen=[56], nstp=[1], ims_complexity="complex")` | nper 1, total_time 56 d |
| 6 | `check_model` + `validate_model` | both **clean** |
| 7 | `start_run` / `run_simulation` | converged, 1.70 s, 1 period × 1 step |
| 8 | `import_obs_from_csv(cellid_col="Cell_ID")` | 13 sites, 78 records |
| 9 | `run_simulation` | converged; obs fit RMSE 1.0556 m, R² 0.8671 |
| 10 | `compare_to_observed`, `read_simulated_observations` | 13-site residual table (mapping verified) |
| 11 | `setup_da_control(...)` | 1st call rejected (see reprompts); 2nd call → `.pst` + templates |
| 12 | `start_calibration(method="da", num_reals=50)` | job `fe51f045076c` → **deadlock** |
| 13 | `cancel_job(fe51f045076c)` | cancelled |
| 14 | `start_calibration(method="da", num_reals=50)` (retry) | job `cede35a25c41` → **deadlock** |
| 15 | `cancel_job(cede35a25c41)` | cancelled |
| 16 | `start_calibration(method="da", num_reals=4)` | job `e5eda6a446db` → **deadlock** |
| 17 | `cancel_job(e5eda6a446db)` | cancelled |
| 18 | `run_pestpp_da(num_reals=4, num_workers=1)` | **client timeout / hang** |
| 19 | `flush_model` / `run_simulation` on `neckartal_disu` | RUN_FAILED — truncated external K (DA residue) |
| 20 | `adopt_model(name="neckartal_base", workspace=<pristine backup>)` | adopted |
| 21 | `set_simulation` + `import_obs_from_csv` + `run_simulation` on `neckartal_base` | converged, identical fit |
| 22 | `plot_heads_map` | PNG produced (DISU + vertices OK) |
| 23 | `compare_to_observed` (with `.png` output path), `read_simulated_observations` | residual table + scatter |

### Reprompts / corrections needed

1. **`setup_da_control` `par_cycles`** — first call passed
   `par_cycles={"perlen": [56,28,14,12,15,36]}` (a list) →
   `INVALID_INPUT: par_cycles['perlen'] must map a cycle index to a fixed value.`
   Corrected to `{"perlen": {"0":56,"1":28,"2":14,"3":12,"4":15,"5":36}}` → accepted.
2. **`compare_to_observed` `output_file`** — passing a `.csv` path →
   `COMPARE_FAILED: Format 'csv' is not supported`. Corrected to a `.png` path; the tool then
   wrote both the scatter PNG and its own residuals CSV.

### Notable tool behaviour (not an error, but worth recording)

`set_simulation` reported `nper=1` while the on-disk `sim.tdis` still said `NPER 6`. The
subsequent `check_model` flush **re-rendered the active simulation under a new stem**:
it wrote `modflowsim.tdis` (NPER 1, perlen 56) and `modflowsim.ims`, and rewrote `mfsim.nam`
to point at them, leaving the original `sim.tdis`/`sim.ims` orphaned on disk. The model ran
correctly from the new set. Not a blocker, but the stale `sim.tdis` is confusing without this note.

## 4. Re-expressing the shipped run as sequential DA

The shipped TDIS is 6 periods × 1 step of 1 day (6 simulated days, constant CHD/RCH/RIV/WEL).
PEST++-DA needs **one stress period with one time step per cycle**, because the canonical
OBS-CSV instruction file reads the first data row.

Applied via `set_simulation(model, 1, [56], [1], ims_complexity="complex")` — i.e. the model is
left as a single 56-day, single-step period, and the per-cycle length is then driven by
`par_cycles={"perlen": {...}}` from the DA parameter cycle table. No TDIS file was hand-edited.

**Cycle design (deviation, documented):** the gauge table is a survey series, not daily data
(421 rows, 2003-02-12 → 2019-04-29). Coverage analysis:

- max gauges present on any single date = **13 of 14**; no date has all 14;
- `Ne-507` reports **only** 2019-01-15 … 2019-04-29 (16 values) → excluded;
- selected 6 cycle-end dates in the model's 2017/18 era with a **common 13-gauge subset**:

| cycle | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| cycle-end date | 2016-03-10 | 2016-04-07 | 2016-04-21 | 2016-05-03 | 2016-05-18 | 2016-06-23 |
| perlen (d) | 56 | 28 | 14 | 12 | 15 | 36 |

IC reference date 2016-01-14 (the preceding gauge survey date); total simulated time **161 days**
(vs. the shipped 6 days). Cycle lengths are real day-gaps, so the DA time axis matches the
observation series rather than the shipped 1-day-per-period template.

Data prep (`prep_obs.py`, ordinary Python only): melt `Pegel.csv` wide→long, drop `-9999`
as missing, join `Pegel_Cell_ID.csv`, keep the 6 cycle dates → `obs_gauges_long.csv`
(`site,date,value,Cell_ID`, 78 rows = 13 sites × 6 cycles). `Cell_ID` is the **0-based** scalar
DISU node id stated in the brief.

`import_obs_from_csv(cellid_col="Cell_ID")` → 13 sites, 78 records; it converted 0-based → 1-based
OBS ids correctly (14119→14120, 10692→10693, …).

## 5. Gauge mapping verification (step 5)

Baseline run (single 56-day step), `compare_to_observed`:

| metric | value |
|---|---|
| n | 13 |
| RMSE | **1.0556 m** |
| bias | −0.9811 m |
| MAE | 0.9811 m |
| R² | **0.8671** |

Per-site residuals all within ±1.9 m (worst: Ne-504 −1.89 m, Ne-506 −1.39 m, Ne-805 −1.28 m).
Gauge observed values are 326–338 m and simulated heads at the mapped nodes are 328–338 m, so a
wrong node/offset mapping would show residuals of tens of metres. **The 13 gauges are verified to
map to the intended nodes.** Water balance closes: inflow 62,146.0 / outflow −62,132.2,
net +13.8 (0.02 %). Baseline is *already* calibrated — phi has a meaningful, non-arbitrary scale.

## 6. DA setup (`setup_da_control`) — completed successfully

```
parameterisation = {"k_mult": {"target":"npf:k","scope":"multiplier","initial":1.0,"partrans":"log"}}
cycles           = [0,1,2,3,4,5]
obs_cycles       = {13 sites} -> {cycle: gauge value}
par_cycles       = {"perlen": {0:56,1:28,2:14,3:12,4:15,5:36}}
num_reals        = 50
noptmax          = 1          (v5.2.16: 0 performs NO update)
use_simulated_states = True
```

Returned:

- **`.pst`: `sim\neckartal_disu.pst`** — `pcf version=2`, `noptmax 1`, `da_num_reals 50`,
  `da_observation_cycle_table`, `da_parameter_cycle_table`, `da_use_simulated_states True`.
- **n_adjustable_parameters = 1** → `k_mult`, log-transformed, scope `multiplier`
  (single dimensionless factor on the existing K field, so the 10,413-value heterogeneous
  pattern is preserved — `scope="all"` would have collapsed it to one uniform value).
- **n_state_parameters = 13** (one per observed cell), sharing the observation names so
  `da_use_simulated_states` can carry heads between cycles. `state_bounds` 5.0–8.99 m.
- **n_observations = 13**, **n_cycles = 6**.
- Templates: `flow_k_mult.dat.tpl` (one wide token `~    k_mult     ~`), `flow_strt.dat.tpl`
  (13 state tokens), `modflowsim.tdis.tpl`.
- Cycle tables: `neckartal_disu_da_par_cycle_tbl.csv` (`perlen,56,28,14,12,15,36`) and
  `neckartal_disu_da_obs_cycle_tbl.csv` (13 sites × 6 cycles) — both correct.
- NPF `k` rewired to `OPEN/CLOSE 'flow_k.dat'`; IC `strt` rewired to `OPEN/CLOSE 'flow_strt.dat'`.
- `model_command`: `"D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe" C:\Users\jakob\AppData\Local\Temp\gwmcp_run_neckartal_disu.py`

## 7. BLOCKED — the DA execution deadlocks (4/4 attempts)

| attempt | tool | reals | outcome |
|---|---|---|---|
| A | `start_calibration(method="da")` | 50 | progressed to `run.info: realization 2`, then hung > 6 min |
| B | `start_calibration(method="da")` | 50 | hung at `realization 0`, > 6 min |
| C | `start_calibration(method="da")` | 4 | hung at `realization 0`, > 4 min |
| D | `run_pestpp_da` (sync) | 4 | client timeout (`MCP error -32001`) |

Identical signature every time:

- `pestpp-da.exe` burns **100 % of one core** (e.g. 366 s CPU / 350 s wall; 387 → 407 s CPU in 20 s)
  while "running initial ensemble of size 50".
- The spawned model command is **frozen**: process tree
  `pestpp-da.exe → .venv\Scripts\python.exe (stub) → uv cpython-3.12.11 python.exe (wrapper)`,
  with the interpreter at **0.016 s CPU and 9 MB working set** — i.e. blocked immediately after
  interpreter start. It never gets as far as importing numpy.
- **`mf6.exe` never starts** in the background attempts; `flow_output\flow.hds|.cbc` never update.
- `neckartal_disu.log` and `.rec` stop at `...running initial ensemble of size 50`; no error is
  ever emitted.
- `sim\flow_k.dat` is left **truncated mid-write (122,995 of 412,638 bytes)** — the residue of a
  wrapper suspended during `np.savetxt`.
- Progress is not merely slow: it is zero. Attempts B and C never completed a single realization
  in >4–6 minutes, and reducing the ensemble 50 → 4 changed nothing.

The generated wrapper (`C:\Users\jakob\AppData\Local\Temp\gwmcp_run_neckartal_disu.py`, read as
diagnostics — a tool *artifact*, not repo source) is trivial and not itself slow:

```python
base = np.loadtxt(BASE); zone = np.loadtxt(ZONE); mult = np.loadtxt(MULT)
factor = np.ones_like(base); zoned = zone > 0
factor[zoned] = mult[zone[zoned]-1]
np.savetxt(KFILE, base*factor, fmt="%.10g")
proc = subprocess.run([MF6], cwd=WS)     # <- never reached in the hung attempts
```

### Most probable cause (unconfirmed — reported as hypothesis, not fact)

The MCP builds `model_command` as
`"<venv python> <space-free temp wrapper>"`. The wrapper path is space-free (as the tool
intends), but the **interpreter path is not**: `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`
contains a space, and it is a venv redirector that re-spawns a *second* process
(`uv\...\cpython-3.12.11\...\python.exe`). The MCP's own documented Windows constraint
(`setup_pest_control` docstring) says pestpp "cannot run .bat/.cmd wrappers or space-containing
paths" on Windows. A two-level, space-containing spawn chain is the leading candidate for
pestpp-da losing synchronization with its child and then busy-waiting forever.

What I could and could not control from the tool surface:

- the wrapper *is* at a space-free path (good);
- the interpreter is fixed to the MCP server's `sys.executable`, which is not space-free;
- `setup_da_control` exposes no `model_command` override (`da_options` is documented as `da_*`
  options only), so the command cannot be corrected from the tool surface;
- `scope="multiplier"` **requires** a Python wrapper (it computes `k = base_k × factor`), and
  `scope="all"` is explicitly documented as infeasible here (single-value template / oversized
  template), so "drop the wrapper" is not an available route.

I therefore stopped, per the run's MCP-only rule. **No raw flopy/pyemu/PEST workaround was used**,
and the repo's own EnKF (`main.py`, `Transient_Run.py`, `generator.py`) was never executed.

### Resulting workspace state

The adopted model `neckartal_disu` is left **non-runnable**: the DA preparation rewired NPF `k` to
`OPEN/CLOSE 'flow_k.dat'`, and the aborted DA left that file truncated, so
`run_simulation` returns
`RUN_FAILED: Not enough data in file ...\flow_k.dat for data "k". Expected data size 31831 but only found 0.`
`flush_model` reports nothing pending, so the MCP cannot repair it, and repairing it would mean
hand-writing a MODFLOW input file — exactly what this run forbids.

The pristine shipped copy was preserved before any modification at
`...\MODFLOW 6\_sim_backup_shipped\` (60 files, 72.4 MB) and was re-registered as a second model
`neckartal_base` so that step 8 could still be delivered.

## 8. Post-processing (delivered on the pristine baseline `neckartal_base`)

`neckartal_base` = `_sim_backup_shipped`, re-`adopt_model`ed, `set_simulation(1, [56], [1])`,
same obs re-imported, `run_simulation` → converged in 1.72 s, **and it reproduces the baseline
exactly** (RMSE 1.0555854023175097, bias −0.9810980977368331, R² 0.8671324330530341), confirming
the DA setup itself did not perturb the physics and that the model is deterministic.

- `plot_heads_map(layer 0, kstpkper [0,0])` →
  `neckartal_base_heads_map.png`. Works on this vertex-carrying DISU grid via CELL2D geometry
  (no CRS needed). Head range 305.16–340.92 m over the Neckar valley corridor.
- `compare_to_observed(output_file=...obs_fit.png)` → `neckartal_base_obs_fit.png` +
  `neckartal_base_obs_residuals.csv`.
- `read_simulated_observations` → 13 per-site simulated heads (t = 56 d).

Per-site residual table (observed = mean of the 6 registered cycle values; simulated at t = 56 d):

| site | observed | simulated | residual |
|---|---|---|---|
| Ne-401 | 333.377 | 334.508 | −1.131 |
| Ne-402 | 331.457 | 332.626 | −1.169 |
| Ne-403 | 331.562 | 331.944 | −0.383 |
| Ne-503 | 337.750 | 338.342 | −0.592 |
| Ne-504 | 336.465 | 338.351 | −1.886 |
| Ne-505 | 331.502 | 332.326 | −0.824 |
| Ne-506 | 330.948 | 332.336 | −1.388 |
| Ne-604 | 326.942 | 328.038 | −1.097 |
| Ne-801 | 329.808 | 330.650 | −0.841 |
| Ne-802 | 328.698 | 329.315 | −0.616 |
| Ne-803 | 328.720 | 329.325 | −0.605 |
| Ne-805 | 330.245 | 331.521 | −1.276 |
| Ne-806 | 330.582 | 331.528 | −0.946 |

**No per-cycle phi, posterior parameter statistics, or DA residuals can be reported** — the
assimilation never executed. In particular there is **no cycle-0 prior → post-update phi
improvement to show**, because no update step ever ran. The baseline phi scale is *not*
arbitrary (RMSE ≈ 1 m on a 13-site, 326–338 m head field), so a properly executing DA would have
had a meaningful target phi to improve on; that opportunity was lost to the deadlock.

## 9. Deviations from the source model (summary)

| # | shipped | this run | why |
|---|---|---|---|
| 1 | TDIS NPER 6 × 1 day × 1 step | `set_simulation(1, [56], [1])` + `par_cycles` perlen | PEST++-DA needs exactly one step per cycle; the OBS instruction file reads the first data row |
| 2 | 6 simulated days | 6 cycles = 161 days | cycle lengths are the real day-gaps between the chosen gauge survey dates |
| 3 | bespoke Python EnKF (`main.py`, 30 daily steps from 2017-01-30, assimilating only days with >7 gauges) | PEST++-**DA** (ensemble data assimilation) | method change required by the MCP DA toolchain; the repo's EnKF was not run |
| 4 | gauge rows for all 14 gauges incl. Ne-507 | 13 gauges, Ne-507 excluded | Ne-507 only reports in 2019 and never co-occurs with the other 13 |
| 5 | 6-day template time axis | 6 real survey dates 2016-03-10 … 2016-06-23 | no daily multi-gauge coverage exists; chosen window maximises the common gauge subset |
| 6 | NPF `k` from `flow_input/flow.npf_K_1.txt` | rewired to `OPEN/CLOSE 'flow_k.dat'` (base × multiplier) by `setup_da_control` | needed for the DA multiplier parameterisation; **left truncated by the aborted DA** |
| 7 | IC `strt` from `flow_input/flow.ic_STRT_1.txt` | rewired to `OPEN/CLOSE 'flow_strt.dat'` (13 state tokens) | needed for `da_use_simulated_states` |
| 8 | shipped `sim.tdis`/`sim.ims` | MCP flush re-rendered `modflowsim.tdis`/`modflowsim.ims`; `mfsim.nam` repointed | tool behaviour; original files left orphaned on disk |
| 9 | — | ensemble size 50 for the real attempts, 4 for the minimal diagnostic | throughput probe after the first deadlock |
| 10 | — | baseline delivered via `neckartal_base` (pristine backup copy) | adopted model left non-runnable by the DA residue |

## 10. Deliverables in this folder

- `prep_obs.py` — gauge-table prep (ordinary Python only; no model objects)
- `obs_gauges_long.csv` — 78-row observation table fed to `import_obs_from_csv`
- `cycles.json` — cycle dates, perlen, and the `obs_cycles` map
- `neckartal_base_heads_map.png` — step 8 heads map
- `neckartal_base_obs_fit.png`, `neckartal_base_obs_residuals.csv` — step 8 gauge fit
- `run-log.md` — this file

## 11. Bottom line

Steps 1–6 are complete and verified: the shipped DISU model adopts and checks clean, the TDIS is
correctly reduced to one step per cycle, 13 real gauges are registered and **proven** to map to the
right nodes (RMSE 1.06 m, R² 0.87), and a correct PEST++-DA control file with 1 `k_mult`
multiplier parameter, 13 state parameters and 6 cycles is generated.

Step 7 cannot be completed: **the MCP toolchain cannot execute the sequential DA on this model.**
`start_calibration(method="da")` and `run_pestpp_da` both deadlock — `pestpp-da` spins at 100 % CPU
while its spawned `python → wrapper` chain is frozen at ~0 CPU before it can even import numpy, so
`mf6.exe` never runs. The most likely cause is the generated `model_command` embedding a
space-containing two-level interpreter (`...\Claude Projects\...\.venv\Scripts\python.exe` →
`uv\...\cpython-3.12.11\...\python.exe`), which contradicts the MCP's own documented rule that
pestpp cannot run space-containing paths on Windows. There is no tool-level override for the DA
model command, and `scope="multiplier"` makes the wrapper mandatory — so this is a genuine
toolchain capability gap, reported rather than worked around.
