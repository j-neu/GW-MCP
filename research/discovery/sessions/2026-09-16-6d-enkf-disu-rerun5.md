# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-5 (regional model validation)

- **Date**: 2026-09-16
- **Client**: Agent Manager closed-book session (groundwater-mcp server on this host)
- **Models**: `neckartal_da` — attempt 1, adopted in place at the shipped
  `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim` (single GWF `flow`); `neckartal_da2`
  — attempt 2, the repo's pristine sibling copy `…\MODFLOW 6\ensemble\m0\`
- **Worktree / branch**: `.kilo/worktrees/6d-enkf-disu-rerun5`
- **Code**: `228595c` (same code for rerun-4 and rerun-5)
- **Holdout**: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (relocated from `D:` — see playbook)
- **Playbook**: `research/discovery/playbooks/6d-regional-model-validation.md`, **Target 8**
  (sequential EnKF-style data assimilation on a real DISU model)
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun5/run-log.md`
- **Type**: closed-book validation rerun. Rerun-5 is the clean converged rerun after attempt 1
  aborted; the run log reports **no user reprompt**.

## Prompt used

The verbatim playbook Target 8 prompt (playbook §"Prompt (paste verbatim into the Agent Manager
session)"). Summarised:

- Closed-book: do NOT read the groundwater-mcp repo source/tests/plans/prior session logs; the
  target repo's own data and scripts **are** the model specification. Data root
  `GW-MCP-holdout\selected\MF6_EnKF_DISU\`.
- Nine steps: (1) `check_environment` first; (2) `adopt_model` the shipped `sim` (name ≤ 16 chars,
  `allow_modify=true`, declared units); (3) `check_model` clean; (4) re-express the 6×1-day TDIS as
  **NPER=1/NSTP=1** per cycle with `set_simulation` (no hand-edited TDIS) and define DA cycles
  explicitly; (5) register the gauges via `import_obs_from_csv(cellid_col="Cell_ID")` after
  ordinary-Python reshaping of `Pegel.csv` + `Pegel_Cell_ID.csv`; (6) `setup_da_control` with a
  log `npf:k` parameterisation, `cycles`, `obs_cycles`, `par_cycles` perlen, `num_reals`,
  `noptmax=1`, `use_simulated_states=True`; (7) `start_calibration(model, pst, method="da")` →
  poll `get_job_status` → `summarise_da`; (8) `plot_heads_map` + final-cycle `compare_to_observed` /
  `read_simulated_observations`; (9) write `run-log.md`.
- **MCP-only constraint**: every adopt/build/run/post-process/assimilate action on the MF6 model
  through a groundwater-mcp tool; no raw flopy/pyemu MODFLOW or PEST classes, no hand-edited
  MODFLOW/PEST files, and the repo's EnKF scripts (`main.py`/`Transient_Run.py`/`generator.py`)
  deliberately not run. Ordinary Python only to reshape the gauge CSVs into the observation table
  fed *into* `import_obs_from_csv`. If a tool cannot do something, stop and report the gap rather
  than work around it.

## Tool-call sequence (run log §1–§8, §11)

| # | call | outcome |
|---|---|---|
| 1 | `check_environment` | `ready: true`, `missing` none; flopy 3.10.0 / pyemu 1.4.0; mf6 + pestpp-glm/ies/da/sen/opt present |
| 2 | `adopt_model(neckartal_da, …\sim, allow_modify=true, METERS, DAYS)` | `adopted: true`, `model_names: ["flow"]`; no grid rebuild, no renames |
| 3 | `check_model` | `check_passed: true`, 0 errors, 0 warnings |
| 4 | `summarise_model` | DISU **31,831 nodes / 31,522 active**; 6 stress periods; m/d |
| 5 | `set_simulation(1, [1.0], [1], "moderate")` | shipped NPER=6 reduced to **NPER=1/NSTP=1**; `sim.tdis` not hand-edited |
| 6 | `import_obs_from_csv(cellid_col="Cell_ID")` | **13 sites / 78 records**; `site_cellid_map` 0-based node → 1-based OBS id |
| 7 | `run_simulation` | converged, 1.32 s; baseline `observation_fit`: n=13, **RMSE 4.966 m, bias −4.791 m, MAE 4.791 m, R² −1.802** |
| 8 | `setup_da_control` (attempt 1, uniform K bounds 0.1–10) | **client timeout (−32001)**; artefacts verified with `list_model_files`; 1 adjustable K + 13 state + 1 fixed `perlen`; 40 reals, 6 cycles |
| 9 | `start_calibration(method="da")` → `get_job_status` | job **`0b3ba25a1547`**; `succeeded` but `converged: false`; 3 cycles; final φ mean **277.176**, sd 35.054; stdout "all remaining realizations failed"; `mfsim.lst` convergence failure |
| 10 | read-only inspection (`flow_k.dat.tpl`, `flow_k.dat`, `flow_k_pristine.npy`, `mfsim.lst`) | diagnosed **uniform-K collapse**: 31,831 identical tokens; written K uniform **0.1408 m/d** (posterior mean 0.1999, min 0.107) vs pristine 0.864–86,400 m/d / 10,413 unique |
| 11 | `adopt_model(neckartal_da2, …\MODFLOW 6\ensemble\m0\)` | pristine sibling copy adopted for a clean start (FloPy 3.3.6, NPER 6, shipped `k`/`strt` arrays) |
| 12 | `check_model` | clean |
| 13 | `set_simulation(1, [1.0], [1])` | NPER=1/NSTP=1 |
| 14 | `import_obs_from_csv` (13 sites / 78 records) | registered |
| 15 | `setup_da_control` (attempt 2: `lower_factor 0.2`, `upper_factor 5.0`, `state_head_bound=5`) | returned in-band: `n_observations 13`, 1 adjustable, **13 state params**, 6 cycles, `state_bounds` ±5 m |
| 16 | `start_calibration(method="da")` → `get_job_status` | job **`6fff3ca1f55f`**; `succeeded`, **`converged: true`**, 6 cycles, 112 model runs, **1,492 s (24.87 min)** |
| 17 | `summarise_da` | per-cycle φ; final φ mean **69.695**, sd **1.315**; `k_glob` **mean 0.2000, std 2.8e-17, min = max = 0.200** (pinned at the lower bound, 100 % of reals); residuals **RMSE 2.363 m, bias −2.223 m, R² 0.370** |
| 18 | `plot_heads_map` | PNG produced; DISU footprint renders but the colour scale is dominated by the inactive sentinel |
| 19 | `compare_to_observed` / `read_simulated_observations` | **RMSE 2.321 m, bias −2.166 m, MAE 2.166 m, R² 0.388**, n=13; 13 simulated heads |

## Reprompts

**0 human reprompts** — the run was driven from the single verbatim playbook prompt. Internal
recovery actions (run log §11), not reprompts:

1. `setup_da_control` client timeout → verified server-side artefacts with `list_model_files` (no
   re-issue).
2. DA abort at cycle 2 → read `mfsim.lst` + templates, diagnosed the uniform-K collapse, re-ran
   with tightened K bounds.
3. Contaminated live snapshot → discovered `ensemble\m0\`, confirmed it is a byte-identical
   pristine copy of the shipped inputs, adopted it as `neckartal_da2` for a clean start.
4. `numpy.loadtxt` failed on the free-form external array files → switched to whitespace
   tokenisation (read-only data inspection).

## Outcome vs pre-registered criteria (Target 8)

| Criterion | Result | Evidence |
|---|---|---|
| `check_environment` first | **PASS** | run log §1: `ready: true`, `missing` none |
| Adopt shipped sim; grid/packages match the source set | **PASS** | run log §2/§3: DISU **31,831 nodes / NJA 198,261 / 31,522 active**, vertices + CELL2D; packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO; `check_model` 0 errors / 0 warnings |
| Single-step re-expression (NPER=1/NSTP=1) documented | **PASS** | run log §4: `set_simulation(1, [1.0], [1])` wrote `sim.tdis` to NPER 1; six DA cycles re-expressed via the cycle table; no hand editing |
| DA setup: DA-ready v2 `.pst`, `noptmax ≥ 1`, `da_num_reals N`, `da_use_simulated_states True`, a `head_state` param per gauge cell, populated cycle tables | **PASS** | run log §6: both attempts produced a v2 `.pst` (`pestmode estimation`, `noptmax 1`, `da_num_reals 40`, `da_use_simulated_states True`); attempt 2: 1 adjustable K + **13 state** params + 1 fixed `perlen`, 6 cycles, obs/par/weight cycle tables |
| Run: N-realisation ensemble over the requested cycles; per-cycle carry-forward observable | **PASS** (attempt 1 aborted; attempt 2 converged) | run log §6/§7: attempt 1 `converged: false` at cycle 2; attempt 2 `converged: true`, **6 cycles × 40 reals**, 112 model runs, 1,492 s; per-cycle prior→post φ table shows the carry-forward |
| Summarise: per-cycle post-update φ, final-cycle φ mean/std, posterior stats, residuals, no error | **PASS** | run log §7: per-cycle φ table; final φ mean **69.695**, sd **1.315**; posterior `k_glob` + 13 head-state values; residuals RMSE 2.363 m |
| Fit: gauges assimilated; prior→post-update φ reported; uncalibrated baseline documented | **PASS** | run log §5/§8: baseline single-step RMSE **4.966 m** (R² −1.802) → post-DA final cycle **2.363 m** (R² **+0.370**); `compare_to_observed` RMSE 2.321 m, R² 0.388; baseline documented as uncalibrated (shipped heads ~4–5 m high) |
| `plot_heads_map` + final-cycle `compare_to_observed` / `read_simulated_observations` | **PASS** (colour-scale caveat) | run log §8: DISU footprint renders correctly but the colour scale is dominated by the MF6 inactive sentinel (not quantitatively readable); `compare_to_observed` + `read_simulated_observations` produced the fit tables |
| Reprompts ≤ 1 | **PASS** | 0 human reprompts (the 4 recovery actions are tool/transport recoveries) |
| Closed-book and MCP-only | **PASS** | run log preamble + §10/§11: 0 MCP-only violations; repo EnKF scripts read, never executed; the recovery used `adopt_model` on the repo's pristine sibling copy (an MCP tool), not a hand-edit or raw flopy call |
| PASS bar: ≥ 2 consecutive green reruns, last set-and-forget with 0 reprompts / 0 MCP-only violations | **PARTIAL** | rerun-5 is a converged green run (with rerun-4 the ≥2 count is met), but `k_glob` is pinned at its lower bound and the ensemble still collapses after cycle 1, and the run needed the pristine-sibling-copy recovery; the strict "no workarounds / set-and-forget" PASS call is left to the owner |

## Deviations from the source model (run log §9)

1. **6-period → single-step DA cycles.** Shipped `NPER 6 × 1 day` reduced via `set_simulation` to
   `NPER 1, NSTP 1, perlen 1.0 day`; re-expressed as six 1-day DA cycles driven by the parameter
   cycle table. Total simulated time (6 days) matches the source model.
2. **Observation time collapsed.** Six 2017 survey dates spanning 2017-01-30 → 2017-08-29 (real
   gaps up to 118 days) mapped onto six consecutive 1-day cycles; real inter-survey travel time is
   not represented.
3. **Forcing is static.** The shipped boundary packages carry a single period, so all six cycles
   share the same RCH/RIV/WEL/CHD; the repo's dynamic forcing from `RCHunterjesingen.csv` /
   `2017.csv` was not reproduced (no MCP DA channel for it).
4. **Method change: PEST++-DA replaces the bespoke EnKF.** The repo's damped stochastic Kalman EnKF
   over pilot-point-kriged log-K was not run; sequential assimilation used **pestpp-da v5.2.16**
   (`noptmax 1`, `da_use_simulated_states True`).
5. **K parameterisation is uniform, not spatial.** MCP `scope="all"` on `npf:k` tokenises all 31,831
   cells with a single parameter, replacing the 10,413-value heterogeneous K field by one uniform
   value — a material simplification inherent to the "all" scope.
6. **Two model registrations.** `neckartal_da` (shipped `sim\`, attempt 1, aborted) and
   `neckartal_da2` (pristine `ensemble\m0\`, attempt 2, completed).
7. **State bounds** set to ±5 m (`state_head_bound`); tool-derived defaults were ±~5–9.5 m per site.
8. **Observation weight = 1.0** for all sites (σ ≡ 1 m), so φ is a plain sum of squared head
   residuals in m²; the absolute φ scale is arbitrary and the baseline is uncalibrated.

## MCP findings (run log §10 → v0.2.0 backlog)

| # | finding | impact |
|---|---|---|
| 1 | `setup_da_control` has **no async/job mode** and exceeded the client timeout on attempt 1; the call is successful server-side but reports a client error | setup completion must be confirmed by inspecting files; the async pattern added for the DA *run* does not cover setup |
| 2 | **No tool to unwind/reset a parameterisation.** After attempt 1 the live model's snapshot became the new "pristine" base, so a same-workspace re-setup inherits the assimilated state | worked around by adopting the repo's pristine sibling copy (an MCP call), not by hand-editing files |
| 3 | `scope="all"` K is a **uniform replacement, not a multiplier** on the existing field (31,831 identical tokens; written K uniform ≈0.14 m/d at the failure) | the likely cause of the bound-pinning/ensemble collapse; worth knowing before using it on a heterogeneous model |
| 4 | `plot_heads_map` **colour scale** is unusable on this DISU grid because inactive sentinel values dominate it | the vertex-carrying footprint renders correctly but the map is not quantitatively readable |
| 5 | `clone_model` fails on this DISU model (FloPy `ihc` error) | the clone-into-a-fresh-workspace isolation the DA findings call for is not available; recovery used the repo's pristine sibling copy instead |

All other steps (adopt, check, `set_simulation`, `import_obs_from_csv`, `run_simulation`,
`setup_da_control`, `start_calibration`/`get_job_status`, `summarise_da`, `compare_to_observed`,
`read_simulated_observations`) worked end-to-end through the MCP alone.

## MCP-only violations

**0.** No flopy/pyemu MODFLOW or PEST class was called, no MODFLOW/PEST file was hand-edited, and
the repo's EnKF scripts were not executed. Ordinary Python was used only for the allowed gauge data
prep and read-only diagnostic inspection.

## Time

The run log records the successful DA wall time, not the session total: attempt 2 **1,492 s
(24.87 min)** for 6 cycles × 40 reals (112 model runs). Attempt 1 ran 3 cycles before aborting.
Total closed-book session time is not recorded in the run log.
