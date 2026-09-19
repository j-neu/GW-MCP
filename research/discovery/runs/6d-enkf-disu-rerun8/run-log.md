# CLOSED-BOOK VALIDATION RUN — Phase 6d target 8

**Target:** `MF6_EnKF_DISU` (`github.com/JanGei/MF6_EnKF_DISU`), Neckartal (DE), sequential DA.
**Model:** DISU 31,831 nodes / NJA 198,261 / 31,522 active, vertices + CELL2D.
**Run date:** 2026-09-17. **MCP-only** (no flopy/pyemu MODFLOW or PEST classes called directly; no hand-edited MODFLOW/PEST files; repo EnKF scripts not executed).
**Workspace:** `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim` (adopted in place — not copied).
**Session folder:** `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun8`

---

## 1. Environment (`check_environment`)

`ready=true`, `missing = none`.

| item | value |
|---|---|
| Python | 3.12.11 (`.venv`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / ies / sen / opt / **da** | `C:\Users\jakob\.local\bin\pestpp-*.exe` |

Docs index built; workspace root `C:\Users\jakob\.groundwater-mcp\workspaces`.

### Source / licence check
`E:\GW-MCP-holdout\selected\MF6_EnKF_DISU` contains **no LICENSE, LICENCE, COPYING or NOTICE file anywhere** (recursive, case-insensitive), and no README/`.md`/`.txt`/`.rst` at the root. The repo carries no explicit licence — treat as all-rights-reserved by the author pending clarification. (Beyond the run scope; recorded for completeness.)

### Model facts read from the shipped files (the spec)
- `flow.disu`: `LENGTH_UNITS meters`; NODES 31831, NJA 198261, NVERT 11430; top/bot/area/idomain + iac/ja/ihc/cl12/hwva/angldegx external in `flow_input\`; VERTICES + CELL2D present.
- `sim.tdis`: `TIME_UNITS days`, **NPER 6**, six 1-day periods.
- Packages: DISU, NPF, IC, CHD, OC, RCH, RIV, WEL, STO. CHD/RCH/RIV/WEL carry **only PERIOD 1** data (MF6 reuses it), so shortening NPER is lossless for them.
- NPF `k`: min 0.864, max 86,400, **10,413 unique** (active-cell geo-mean 10.18, median 8.64) → matches the brief.
- Inactive cells: 31,831 − 31,522 = **309**.
- Repo's own DA is bespoke Python (`main.py`, `Transient_Run.py`, `generator.py`, `Objectify.py`; 15-member EnKF, pilot-point kriging, hand damping) and was **not** run.

---

## 2. Tool-call sequence

| # | call | result |
|---|---|---|
| 1 | `check_environment` | ready, nothing missing |
| 2 | `list_models` | registry holds stale `neckartal`, `neckartal_r7`, `neckartal_da`, `neckartal_disu`, `neckartal_base` (some aliasing this same sim dir); `neckartal_r8` free |
| 3 | `adopt_model` | `neckartal_r8`, workspace = sim dir, `units=METERS`, `time_units=DAYS`, `allow_modify=true` → `adopted=true`, `model_names=["flow"]`; grid **not** rebuilt, files **not** renamed |
| 4 | `summarise_model` | DISU, n_active 31522, NPER 6; units m / d, k m/d, recharge m/d |
| 5 | `check_model` | **clean** — 0 errors, 0 warnings |
| 6 | `set_simulation(nper=1, perlen=[7], nstp=[1], ims_complexity="complex")` | NPER 1, 1 step, total time 7 d |
| 7 | `check_model` | **clean** after the TDIS change |
| 8 | Python data prep | long obs table (site,date,value,Cell_ID) → `artifacts\obs_neckartal.csv` |
| 9 | `import_obs_from_csv(cellid_col="Cell_ID")` | 13 sites / 33 records; 0-based node → 1-based OBS id |
| 10 | `flush_model` | OBS staged write committed |
| 11 | `run_simulation` (pre-DA baseline) | converged 3.20 s; fit RMSE 3.801, bias −3.692, R² −0.676 |
| 12 | `setup_da_control` | **client timeout −32001**, but server completed (artefacts verified) |
| 13 | `start_calibration(method="da", num_reals=24)` | job `308becd89395`, ran 877 s, `succeeded`, `converged=true`, 80 model runs |
| 14 | `get_job_status` ×4 | live cycle/phi progress |
| 15 | `summarise_da` | per-cycle phi, posterior stats, residuals |
| 16 | `read_simulated_observations` | 13 final-cycle heads |
| 17 | `compare_to_observed` | RMSE 2.553, bias −2.375, MAE 2.398, R² 0.244 |
| 18 | `plot_heads_map` | `artifacts\heads_map_final_cycle.png` |
| 19 | `read_heads` | layer 0: min 305.16 / max 340.20 / mean 324.56, n_active 31522 |

**Reprompts:** 2.
1. `compare_to_observed` was first given `output_file=...compare_final_cycle.csv` → `COMPARE_FAILED: Format 'csv' is not supported` (the parameter is a plot image, not a table). Re-issued with `.png`; the residuals table is returned separately as `neckartal_r8_obs_residuals.csv`.
2. `setup_da_control` client timeout (see §5) — resolved by verifying server-side artefacts rather than re-calling.

---

## 3. Observation construction (step 5)

`csv data\Pegel.csv` (421 dates × 14 gauges, dayfirst dates, `-9999` = missing) + `csv data\Pegel_Cell_ID.csv` (Name → 0-based DISU node). Pure-Python reshape to `(site, date, value, Cell_ID)`.

**Cycle dates.** Gauges are weekly/monthly, so the DA cycles were anchored on the repo's own assimilation start date, `2017-01-30` (hard-coded in `main.py`), and stepped on the weekly gauge cadence:

| cycle | date | obs sites | obs count |
|---|---|---|---|
| 0 | 2017-01-30 | all except Ne-507 | 13 |
| 1 | 2017-02-06 | Ne-401/402/403/604/801/802/803/805/806 | 9 |
| 2 | 2017-02-13 | Ne-604/803/806 | 3 |
| 3 | 2017-02-20 | Ne-803/806 | 2 |
| 4 | 2017-02-27 | Ne-604/803/806 | 3 |
| 5 | 2017-03-06 | Ne-604/803/806 | 3 |

33 records, **13 distinct sites**. All 14 `Cell_ID`s were validated as in-range **and** active nodes (e.g. Ne-401 → 0-based 14119 → OBS id 14120). **Ne-507 (node 10692) has no observation in any 2017 window** — it reports only in Jan–Mar 2019 (1–2 gauges/date that window covers), so registering it in a 2017 sequence would add a gaugeless parameter. It is therefore excluded, and the reason is recorded rather than silently dropped.

The tool wrote a canonical `flow.obs` (`continuous ... HEAD <node>` with no `TIME` entries) → MF6 records the obs at the single time step, which is exactly why the NPER=1/NSTP=1 collapse in step 4 is required.

---

## 4. DA configuration (step 6)

`setup_da_control`:
- `parameterisation = {"k": {"target": "npf:k", "scope": "all", "initial": 10.18}}` (log-transformed; bounds default 1.018–101.8).
- `cycles = [0,1,2,3,4,5]`; `obs_cycles` = 13 sites → per-cycle values from §3.
- `par_cycles = {"perlen": {0..5: 7}}` — cycle-table-driven stress-period length (7 d each).
- `num_reals = 24`, `noptmax = 1`, `use_simulated_states = True`.

**Generated `.pst`** (`neckartal_r8.pst`, pcf version=2): `da_num_reals 24`, `da_observation_cycle_table`, `da_parameter_cycle_table`, `da_use_simulated_states True`, `noptmax 1`, `svdmode 1`; templates `flow_k.dat.tpl`, `flow_strt.dat.tpl`, `modflowsim.tdis.tpl`; instruction `flow_head.obs.csv.ins`; model command `…\mf6.exe`.

**State-parameter count: 13** (`head_state`, one per registered gauge node). Together with the 1 adjustable `k` (log) and 1 `forcing` `perlen` (fixed) the `.pst` holds 15 parameters, of which **14 are adjustable** (1 K + 13 states).

K was collapsed to a single value: `flow_k.dat` = 31,831 × **10.18** (unique = 1). `flow_strt.dat` holds the `1e30` dry/inactive sentinel on exactly **309** cells = the 309 inactive nodes.

Tool-driven rewiring (not hand edits): `flow.npf` k → `OPEN/CLOSE flow_k.dat`; `flow.ic` strt → `OPEN/CLOSE flow_strt.dat`; `mfsim.nam` → `modflowsim.tdis` / `modflowsim.ims`; `flow.nam` gains the `obs6` package.

---

## 5. Missing capability / defects observed (reported, not worked around)

1. **`setup_da_control` client timeout on scope `all`.** The call returned `MCP error -32001: Request timed out` after ~60 s, but the server completed the work ~84 s in (artefacts timestamped 18:12:10–18:12:34). Cause: the uniform-K template spans the full 31,831-node grid (~544 KB `.tpl`), i.e. the "all"-scope template size quoted in the tool's own documentation. **Capability gap:** the tool exposes no way to raise the client timeout or to ask for a single-token uniform-K template (the pattern-preserving `multiplier` scope is explicitly out of scope for this run). No workaround was attempted — the server-completed artefacts were verified and used. Worth fixing so a legitimate `all`-scope setup on a large grid does not surface as a failure.
2. **`compare_to_observed(output_file=…)` is an image path**, not a table path; a `.csv` value fails with `Format 'csv' is not supported`. Minor API surprise; trivial to hit.
3. No gap was hit that would have forced a raw-flopy/pyemu workaround. The entire adopt → TDIS collapse → obs registration → DA setup → DA run → post-process chain was MCP-only.

---

## 6. Convergence / phi evidence (steps 4 & 7)

- Baseline (shipped inputs, 1 weekly step): **converged**, 3.2 s, normal termination.
- DA job `308becd89395`: `succeeded`, 877.3 s (14.62 min), 80 model runs, 24 realisations, 6 cycles, `converged=true`. `pestpp-da` reported "analysis complete".

**Per-cycle ensemble phi** (`summarise_da`, = `global.phi.actual.csv` post-update mean):

| cycle | obs count | phi | phi / obs |
|---|---|---|---|
| 0 prior (iter 0) | 13 | **285.362** (std 98.93; min 87.8, max 483.4) | 21.95 |
| 0 post (iter 1) | 13 | **83.709** (std 0.0746) | 6.44 |
| 1 | 9 | 63.9691 | 7.11 |
| 2 | 3 | 19.4395 | 6.48 |
| 3 | 2 | 15.7904 | 7.90 |
| 4 | 3 | 19.5135 | 6.50 |
| 5 | 3 | 18.359 | 6.12 |

**Honest reading.** The only genuine posterior update is **cycle 0: prior mean phi 285.36 → 83.71** (ensemble collapse from std 98.9 to 0.075), a 3.4× reduction in per-observation phi (21.95 → 6.44). **Cycles 1–5 show prior ≡ post to all reported digits** (`global.phi.actual.csv` rows `cycle,0` and `cycle,1` are identical: 63.9691, 19.4395, 15.7904, 19.5135, 18.359) — no update occurred, because the ensemble collapsed after cycle 0: **K is at its upper bound (101.8) in every one of the 24 members (std 0)** and head-state spread fell to ~1e-13. With zero parameter spread the Kalman gain is degenerate, so the sequential cycles carry no information.

The eye-catching 83.7 → 18.4 "improvement" across cycles is dominated by the observation count falling 13 → 3; normalised per-observation phi is flat (~6.1–7.9) after cycle 0. Baseline note per the brief: the shipped head/K state fits these 2017 gauges poorly (baseline RMSE 3.80 m, model high by ~3.7 m), so the phi scale is arbitrary and no calibrated fit is claimed.

Forcing note: the shipped RCH/RIV/WEL/CHD packages are single-period constants, so cycle-to-cycle physical forcing is constant; the cycles differ only in duration and observations.

---

## 7. DA results (step 7)

- `final_phi_mean = 36.797`, `final_phi_std = 26.834` (ensemble spread from `result`), last-cycle **BASE** phi `18.359`.
  (Note: `summarise_da` reports `final_phi_mean = 18.359`, `std = 3.18e-05`; the 36.797 ± 26.834 figure is the one returned in the job result. The difference is ensemble-mean vs base/global accounting; the collapsed ensemble makes them converge. Both are reported rather than reconciled by hand.)
- **Posterior parameters** (23 realisations after one drop):
  - `k` = **101.8 / 101.8 / 101.8** (mean/std/min/max) → **pinned at the upper bound**; the update wanted K above the default `10 × initial` bound. The shipped K spans 0.864–86,400 m/d (5 orders), so the default ±factor-10 bound around 10.18 is too narrow for this field — documented, **not** widened (no workaround).
  - `head_state` (13): means 328.605 (Ne-604) … 337.447 (Ne-504) m, std ~1e-13 — collapsed.
  - `perlen` 7.0 (fixed forcing) throughout.
  - `pestpp-da` change summary: `k` 100 % at upper bound; `head_state` 38.46 % of realisations at lower bound.
- **Residuals** (final cycle, the 3 weighted gauges only; the 10 unobserved-in-cycle-5 sites carry weight 0 and measured 0.0):

| site | measured | modelled | residual |
|---|---|---|---|
| Ne-604 | 326.79 | 328.605 | −1.815 |
| Ne-803 | 328.37 | 331.127 | −2.757 |
| Ne-806 | 330.09 | 332.822 | −2.732 |

  → RMSE 2.474, bias −2.435, R² −2.370, n = 3. Full table: `neckartal_r8_da_residuals.csv`.

---

## 8. Post-processing (step 8)

- `plot_heads_map(layer=0)` → `artifacts\heads_map_final_cycle.png`. The vertex-carrying DISU grid rendered correctly (plan view, X ≈ 3.496–3.510 e6, Y ≈ 5.371–5.377 e6; head range 305.16–340.20 m). `read_heads` (layer 0, final step): min 305.16, max 340.20, mean 324.56, n_active 31,522.
- `read_simulated_observations` (final cycle, t = 7 d) → 13 node heads, e.g. Ne-401 334.804, Ne-604 328.605, Ne-806 332.822.
- `compare_to_observed` (final-cycle heads vs each site's mean observed value): **n = 13, RMSE 2.553 m, bias −2.375 m, MAE 2.398 m, R² 0.244**; scatter `artifacts\compare_final_cycle.png`; table `neckartal_r8_obs_residuals.csv`. Largest residuals: Ne-506 −3.51, Ne-805 −3.08, Ne-801 −3.05 m.
  **Caveat:** this diagnostic compares the final-cycle head against the *mean of all registered records* for each site (which span cycles 0–5), so it is not a like-for-like temporal comparison; it is still the tool's canonical fit check and it does improve on the pre-DA baseline (RMSE 3.801 → 2.553, R² −0.676 → +0.244).

---

## 9. Deviations from the source model

1. **6-period transient → single-step DA cycles.** Shipped `sim.tdis` NPER=6 × 1 day → `set_simulation(nper=1, perlen=[7], nstp=[1])`, with the stress-period length then driven per cycle by `par_cycles` (`perlen = 7` for all six cycles). Cycle dates 2017-01-30 … 2017-03-06 (weekly gauge cadence), anchored on the repo's own assimilation date. Heads carry between cycles via `da_use_simulated_states`. Cycle *durations* therefore changed from 1 d to 7 d; the boundary packages are single-period constants so only the storage response differs. Required by the canonical single-row OBS-CSV instruction file.
2. **Uniform-K collapse (scope `all`).** The shipped heterogeneous K field (0.864–86,400 m/d, 10,413 unique values) is replaced by **one** value (initial 10.18 m/d, bounds 1.018–101.8). Deliberate and prescribed: the pattern-preserving `multiplier` scope needs a helper that stalls under the background DA job on this 31,831-node model.
3. **Method change: bespoke EnKF → PESTPP-DA.** The repo's `main.py`/`Transient_Run.py`/`generator.py` EnKF (15 members, pilot-point kriging, hand-tuned damping `damp_h=0.35`/`damp_K=0.05`) is replaced by PESTPP-DA (ensemble smoother, 24 members, `noptmax=1`). The repo scripts were not executed.
4. **Gauge set 14 → 13 registered** (Ne-507 has no 2017 observation; see §3).
5. **Tool-driven file rewiring** (`modflowsim.tdis/.ims`, `flow_k.dat`, `flow_strt.dat`, `OPEN/CLOSE` k and strt, `obs6` in `flow.nam`) — performed by the MCP writers, not by hand. The original `sim.tdis`/`sim.ims` are no longer referenced by `mfsim.nam`.

---

## 10. Artefacts

Session folder `…\6d-enkf-disu-rerun8\`:
- `run-log.md` (this file)
- `artifacts\obs_neckartal.csv` — long obs table fed to `import_obs_from_csv`
- `artifacts\heads_map_final_cycle.png` — final-cycle head map
- `artifacts\compare_final_cycle.png` — observed-vs-simulated scatter

Model workspace (`…\MODFLOW 6\sim\`): `neckartal_r8.pst`, `neckartal_r8.par_data.csv`, `neckartal_r8.obs_data.csv`, `neckartal_r8.tplfile_data.csv`, `neckartal_r8.insfile_data.csv`, `neckartal_r8_da_obs_cycle_tbl.csv`, `neckartal_r8_da_par_cycle_tbl.csv`, `neckartal_r8.global.phi.actual.csv`, `neckartal_r8.phi.*.csv`, `neckartal_r8.5.1.par.csv`, `neckartal_r8_da_residuals.csv`, `neckartal_r8.log`, `flow_head.obs.csv`.

## 11. Bottom line

The MCP toolchain was sufficient end-to-end on a real 31,831-node DISU model with real gauges: adopt in place → TDIS collapse → obs import with node-id mapping → DA setup → background PESTPP-DA run → summarise → plots, with no raw flopy/pyemu workaround. The DA itself is only partially informative: cycle 0 performs a real prior→posterior update (per-obs phi 21.95 → 6.44; ensemble 13-site RMSE 3.80 → 2.55 m), but the single uniform K immediately saturates at its upper bound, collapsing the ensemble, so cycles 1–5 produce no update and the headline phi decline is mostly the falling observation count.
