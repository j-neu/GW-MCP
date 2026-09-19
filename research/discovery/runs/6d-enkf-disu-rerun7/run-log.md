# Run log — Phase 6d target 8: MF6_EnKF_DISU (Neckartal, DISU, sequential DA)

Date: 2026-09-17
Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun7`
Target data: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (github.com/JanGei/MF6_EnKF_DISU, cloned 2026-09-13)

## 0. Provenance / licence check

- No `LICENSE` / `LICENSE.txt` anywhere in the clone (checked at repo root: both `False`).
- **No git metadata**: `git log` / `git remote` fail with "not a git repository" — the clone carries no
  history, so no commit hash or licence can be verified from the checkout itself.
- Not a code-reuse target for this run; used only as a model/gauge specification.

## 1. Environment (`check_environment`)

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-* | glm, ies, sen, opt, da all present in `C:\Users\jakob\.local\bin` |
| docs index | built |
| ready | **true**, `missing: {packages: [], binaries: []}` |

## 2. Shipped model (verified by reading the target's own files, not the MCP source)

`NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim\`
mfsim.nam → TDIS6 `sim.tdis`, gwf6 `flow.nam` `flow`; packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO.

- DISU: `NODES 31831`, `NJA 198261`, `NVERT 11430`; `idomain` 0 → **31,522 active** / 309 inactive.
- `flow.disu` uses OPEN/CLOSE external arrays in `flow_input\` (20 files) plus VERTICES/CELL2D.
- NPF K: 31,831 values, **10,413 unique**, range 0.864 … 86,400 (dominant: 8.64 ×10,773, 0.864 ×10,225, 86,400 ×351).
- `sim.tdis` shipped: `NPER 6`, six periods of perlen 1.0, `NSTP 1`, `TIME_UNITS days` (a 6 × 1-day transient).
- STO: `ss 1e-4`, `sy 0.01`, all six periods TRANSIENT; IMS `COMPLEXITY complex`.
- Shipped `mfsim.lst` ends "Normal termination" (6.9 s) — the model runs as shipped.

## 3. Gauge data (ordinary Python prep, `prep_obs.py`)

- `csv data\Pegel.csv`: wide table, `Date` + 14 gauges, m; `-9999` = missing, 421 dated rows (2003–2019).
- `csv data\Pegel_Cell_ID.csv`: 14 gauges → scalar DISU node ids.
- Coverage is irregular per site. In the model window (2017) the densest sampling is 13 of 14 gauges
  on a handful of dates (`2017-01-30`, `2017-03-27`, `2017-04-06`, `2017-06-19`, `2017-08-03`,
  `2017-08-29`); `Ne-507` has **no** data before 2019-01-15 and was therefore excluded.
- Produced `observations_long.csv` — 78 rows = 13 sites × 6 cycle-end dates, columns
  `site,date,value,Cell_ID` (0-based DISU node ids from the repo's own map).
- Cycle lengths (perlen, days) = gap between consecutive cycle ends, simulation start 2017-01-01:
  `[29, 56, 10, 74, 45, 26]` (total 240 d).

## 4. MCP tool-call sequence and outcomes

1. `check_environment` → stack ready (§1).
2. `adopt_model(name="neckartal_r7", workspace="E:\...\MODFLOW 6\sim", allow_modify=true, METERS, DAYS)`
   → `adopted: true`, `model_names: ["flow"]`. **No records/`,**. Registry already contained stale
   entries from earlier sessions pointing at the same directory (`neckartal`, `neckartal_da`,
   `neckartal_disu`); the E: copy was verified byte-identical to the D: holdout copy
   (`flow.npf` SHA256 `A296DD14…B4BB3F9D`) and still pristine (NPER 6, NPF→`flow_input/`), so it had
   not been mutated by those sessions. A fresh name (`neckartal_r7`) was used.
3. `check_model` → **clean**: `check_passed: true`, no warnings, no errors.
   `model_status` → `runnable: true`, no missing packages.
4. `set_simulation(model, 1, [29], [1], ims_complexity="complex")`
   → `written: false` (deferred). The tool did **not** hand-edit the shipped files: it wrote new
   `modflowsim.tdis` (NPER 1, perlen 29, NSTP 1) and `modflowsim.ims` and re-pointed `mfsim.nam` at
   them. Shipped `sim.tdis`/`sim.ims` remain untouched. Solver kept at `complex` to match the source.
5. `import_obs_from_csv(cellid_col="Cell_ID", site/date/value cols, obs_type="HEAD")`
   → 13 sites / 78 records; `flow.obs` with `FILEOUT flow_head.obs.csv`; node ids converted to 1-based
   OBS ids (14119→14120, …, 12064→12065) exactly as intended.
6. `run_simulation` (cycle-0 forcing, 29 d) → **converged**, 1.86 s.
   Fit: RMSE 2.176 m, bias −2.121 m, MAE 2.121 m, R² 0.462.
   `read_simulated_observations` + `compare_to_observed` confirm each gauge reports at its mapped cell
   (residuals −1.5…−3.2 m; model runs 1.5–3.2 m high).
7. `setup_da_control(parameterisation={"k_mult": {scope:"multiplier", target "npf:k", log}}, cycles=[0..5],
   obs_cycles=<13 sites × 6 cycles>, par_cycles={"perlen": {0:29,…,5:26}}, num_reals=30, noptmax=1,
   use_simulated_states=True)` → **client timeout** (`MCP error -32001`), server completed ~24 s later.
   Result recovered by reading the workspace: `neckartal_r7.pst` (pcf v2), `flow_k_mult.dat.tpl`
   (one wide token), `flow_strt.dat.tpl` (state-augmented IC), `modflowsim.tdis.tpl`,
   `flow_head.obs.csv.ins` (pif, `l1` header-skip + `l1` data line), `neckartal_r7_da_obs_cycle_tbl.csv`,
   `neckartal_r7_da_par_cycle_tbl.csv`. NPF rewired `k → flow_k.dat`, IC rewired `strt → flow_strt.dat`.
   **Parameters: 15 — 13 `head_state` (one per registered site, shared-name with the observations) +
   `k_mult` (log, 0.1–10) + `perlen` (fixed, cycle-table driven).**
8. `start_calibration(model, pst, method="da")` → job `ffa6d3f4e33d`.
   Progress polled with `get_job_status`, on-disk state with file inspection (read-only).
   After ~13 min the job was still at **cycle 0, realization 3 of 30**; cancelled with `cancel_job`
   (→ `cancelled`).
9. Diagnosis of the stall, then a controlled re-test in a path **without spaces**:
   - `clone_model(source="neckartal", name="neck_da7", workspace="C:\Users\jakob\AppData\Local\Temp\kilo\neck_da7")`
     → **`CLONE_FAILED`**: the clone was written but the external OPEN/CLOSE arrays
     (`flow_input/flow.disu_IHC_1.txt`, …) were not copied, so the clone is not loadable.
     *(MCP gap #1: `clone_model` does not carry a model's external array directory.)*
   - Workaround-free alternative: a byte-identical directory copy of the pristine holdout into a
     space-free path + `adopt_model(name="neck_da7")`. The copy is file management only — no model or
     PEST file was edited by hand and every model operation still went through MCP tools.
   - Re-ran `set_simulation` / `import_obs_from_csv` / `run_simulation` → converged 1.81 s, fit
     **identical** to the E: workspace (RMSE 2.17577758561295) → byte-equivalent model.
   - `setup_da_control` (same arguments) → client timeout again, completed server-side;
     `neck_da7.pst` inspected.
10. `start_calibration(method="da")` on `neck_da7` → job `7eed1ea0a965`.
    Ended after **504.38 s**: `status: succeeded`, but `converged: false`, `cycles: 0`,
    `final_phi_mean: null`, `final_phi_std: null`.
11. `summarise_da` → `cycles: []`, no phi, empty parameter ensemble, 0 residuals.
12. Criterion-8 post-processing on a **pristine** copy (`neck_base7`, space-free, adopted):
    shipped 6 × 1-day model → converged 5.8 s; `plot_heads_map` renders the vertex-carrying DISU grid
    (305.16–343.07 m); `compare_to_observed` → RMSE 3.870 m, bias −3.769 m, R² −0.702.

## 5. DA blocker — evidence

Reproduced in **two** independent workspaces (E: with a space in the path, C: without).

- pestpp-da dispatches the model through an **MCP-generated Python forward wrapper**
  (`python.exe gwmcp_run_neck_da7.py`); the wrapper exists because the `multiplier` K scope requires a
  pre-run `k = base_k × factor` step that MODFLOW cannot express itself.
- The wrapper's inputs are internally consistent (checked: `flow_k_zone.dat` = 31,831 × value 1;
  `flow_k_mult.dat` = 1 value → `mult[zone-1]` resolves), so the wrapper script itself is sound.
- **The wrapper process does not progress or exit.** In `neck_da7` it was created at 17:16:39
  (pestpp record `pid: 23872`), sat with **0.0156 s of CPU** (one clock tick) for ~3.5 min, MF6 finally
  launched at 17:20:16, and the wrapper was **still alive with the same frozen CPU 4+ min after its MF6
  child had terminated**.
- MF6 itself is fine and fast: every listing ends `Normal termination` with
  `Elapsed run time: 1.78–1.80 Seconds`.
- Consequence: no run is ever recorded. `neck_da7.rec` contains the cycle-0 prologue once
  (`processing cycle 0` ×1, `running initial ensemble of size 30` ×1) and **zero run records**;
  `neckartal_r7.rec` was 0 bytes; `.rst` 0 bytes.
- `neck_da7.global.phi.actual.csv` contains only its header row — **no phi was ever computed for any
  cycle**, so there is no per-cycle phi, no posterior and no residuals to report.
- Throughput observed: E: run reached only cycle 0 / realization 3 in 7 min, then stalled for a further
  5+ min; neck_da7 never left cycle 0 / realization 0 in 8.4 min. Effective cost ≈ 30–215 s per forward
  run against 1.8 s of actual MF6 time — the model portion was never the bottleneck.
- Same behaviour with the workspace on a different drive and with no space in the path → **not**
  path-related.

### Alternatives considered and rejected (deliberately, per the MCP-only rule)

- **Direct-K scopes** would remove the wrapper, but this model's field must be covered completely:
  - `scope="cells"` with 6 spread nodes was rejected by the tool (`Parameterisation covers 6 of 31831
    cells; 31825 cells are unassigned`), and `cells` entries must be **scalar node ids** on DISU
    (`Cell [0, 0] must be a node id on a DISU grid`).
  - `scope="all"` (or `cells` mixed with `all`) makes the field **uniform**, destroying the
    10,413-value heterogeneous K field — explicitly excluded by the task as solver-hostile.
  - `scope="zones"` uses the same wrapper mechanism, so it is affected identically.
- No hand-run of `pestpp-da`, no hand-run of the wrapper, no hand-editing of `neck_da7.pst`/templates,
  and no raw flopy/pyemu — all such escape hatches were left unused, so this run does not invalidate
  the toolchain test.

## 6. Deviations from the source model / stated plan

| # | Deviation | Why |
|---|---|---|
| D1 | Time re-expression: shipped `NPER 6 × 1 d` → **one 1-day-class stress period per DA cycle**, perlen driven by the cycle table (`[29,56,10,74,45,26]`, 240 d total) | sequential PEST++-DA requires NPER=1/NSTP=1 per cycle with the obs read from the first data row; the shipped 6-day discretisation carries only static RCH/RIV/WEL/CHD forcing, so cycle length is unconstrained by the model. Not a TDIS hand-edit — `set_simulation` wrote `modflowsim.tdis`. |
| D2 | DA cycles are the six **2017 gauge dates** with 13-gauge coverage, not the six shipped simulation days | the shipped 6 consecutive days carry no gauge data, so a 6-day schedule could not inform anything; each cycle now ends on a real, well-observed date. |
| D3 | `Ne-507` (node 10692) dropped | no observations before 2019-01-15 — outside the model window. 13 of 14 gauges registered. |
| D4 | Method change: repo's bespoke Python EnKF (`main.py`/`Transient_Run.py`/`generator.py`, raw flopy, 365 daily steps from 2017-01-01) → **PEST++-DA** via the MCP | the repo's EnKF is out of scope for this run and must not be executed. Its observation schedule (daily steps, `sum(value>5) > 8` gate) informed the cycle-date choice. |
| D5 | Model placed in a byte-identical copy of the holdout (`neck_da7`, `neck_base7`, space-free) after `clone_model` failed | `clone_model` does not copy external OPEN/CLOSE arrays. The E: workspace was adopted first exactly as instructed and all criteria 1–6 evidence comes from it. |
| D6 | A pristine second copy (`neck_base7`) was adopted for criterion-8 post-processing | the E:/space-free workspaces had already been rewired by `setup_da_control` (`k → flow_k.dat`, `strt → flow_strt.dat`) and the last DA realization's K, so a clean baseline was needed for a representative heads map. |
| D7 | DA cycles/ensemble: 6 cycles, `num_reals=30`, `noptmax=1`, `use_simulated_states=True` | as prescribed. `noptmax=1` is required for any update (0 performs none in v5.2.16). |

## 7. Results delivered

- Baseline (shipped K, cycle-0 forcing, 29 d, converged): RMSE **2.176 m**, bias **−2.121 m**,
  MAE 2.121 m, R² 0.462 — the uncalibrated shipped field runs 1.5–3.2 m high at all 13 gauges, i.e. a
  usable, non-arbitrary phi scale.
- Shipped 6 × 1-day model (converged, 5.8 s), pristine copy: RMSE 3.870 m, bias −3.769 m, R² −0.702
  (the site's registered value is the mean of its six 2017 dates, so this is not a like-for-like fit).
- `plot_heads_map` on the DISU vertex grid: heads 305.16–343.07 m over the Neckartal valley extent;
  file `C:\Users\jakob\AppData\Local\Temp\kilo\neck_base7_ws\sim\gwmcp_weoiawh9.png`.
- `compare_to_observed` / `read_simulated_observations` / `flow_head.obs.csv` confirm the 13-gauge
  site→cell mapping (1-based node ids 11202…23970).
- Generated PSTs: `E:\...\MODFLOW 6\sim\neckartal_r7.pst` and
  `C:\Users\jakob\AppData\Local\Temp\kilo\neck_da7_ws\sim\neck_da7.pst`
  (13 state parameters + `k_mult` + `perlen`, `da_num_reals 30`, `da_use_simulated_states True`).
- **No per-cycle phi, no posterior parameter statistics and no residuals exist** — the cycle-0 initial
  ensemble of 30 runs never completed (`cycles: 0`).

## 8. Capability gaps reported (not worked around)

1. **`start_calibration(method="da")` / pestpp-da cannot execute this DISU model when the DA setup uses a
   pattern-preserving K parameterisation.** The `multiplier` (and `zones`) scope requires an MCP-generated
   Python forward wrapper; under pestpp-da that wrapper stalls for ~30–215 s per run before starting MF6,
   does not exit after its MF6 child finishes, and consequently no realization is ever recorded
   (`cycles: 0`, `converged: false`, empty `.rec`, header-only phi file). Sequential DA was therefore not
   delivered, and no substitute model was run in its place.
2. **`clone_model` cannot clone a model whose packages use external OPEN/CLOSE arrays** — it writes the
   nam/package files but not the referenced `flow_input\*` files, so the clone is unloadable
   (`CLONE_FAILED`).
3. **`setup_da_control` exceeds the MCP client timeout** on this model (~90 s server work vs the client
   timeout). It does complete server-side and its artifacts are usable, but the call is not
   retry-safe/idempotent, so the result has to be recovered from the workspace rather than from the tool
   response. (Same class of issue is likely for `setup_calibration` on large grids.)
4. `setup_da_control`'s `cells` scope cannot partially cover an array and does not accept `[layer, node]`
   tuples on DISU (scalar node ids required), which removes the only pattern-preserving wrapper-free
   parameterisation.

## 9. Reprompts / retries / anomalies worth noting

- `adopt_model` refused the name `neckartal` (registry stale from earlier sessions) → re-issued as
  `neckartal_r7`.
- `setup_da_control` timed out client-side **twice**; both times the server-side call completed and the
  artifacts were verified on disk. No retry was issued against a partially written state (a retry would
  have rewritten the PST).
- `SUM(robocopy)` used twice for byte-identical copies after `clone_model` failed; no content was altered.
- The first DA job (`ffa6d3f4e33d`) was cancelled after 13 min at cycle 0 / realization 3; the second
  (`7eed1ea0a965`) ran 504 s and terminated itself with no cycles. Neither produced phi.

## 10. Reproduce

```
python prep_obs.py                                   # -> observations_long.csv (78 rows, 13 sites)
# then, all via groundwater-mcp:
check_environment
adopt_model(neckartal_r7, "E:\...\MODFLOW 6\sim", allow_modify=true, METERS, DAYS)
check_model / model_status
set_simulation(neckartal_r7, 1, [29], [1], ims_complexity="complex")
import_obs_from_csv(neckartal_r7, observations_long.csv, cellid_col="Cell_ID", obs_type="HEAD")
run_simulation(neckartal_r7)                          # converged, RMSE 2.176 m
setup_da_control(model, {"k_mult": {target:"npf:k", scope:"multiplier", initial:1, partrans:"log"}},
                 cycles=[0..5], obs_cycles=<Pegel 2017 values>, par_cycles={"perlen": {...}},
                 num_reals=30, noptmax=1, use_simulated_states=true)
start_calibration(model, pst, method="da")            # <- stalls at cycle 0, no phi (see §5)
```
