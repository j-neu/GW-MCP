# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-2 (regional model validation)

- **Date**: 2026-09-15
- **Client**: Agent Manager closed-book session (groundwater-mcp server on this host)
- **Model**: `neckartal` — adopted, workspace = the shipped
  `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim` (single GWF `flow`)
- **Worktree / branch**: `.kilo/worktrees/6d-enkf-disu-rerun2` (branch `6d-enkf-disu-rerun2`;
  Agent Manager base `08103b5` — the stale-base regression already in the backlog, harmless here
  because the MCP server runs from `main`)
- **Playbook**: `research/discovery/playbooks/6d-regional-model-validation.md`, **Target 8**
  (sequential EnKF-style data assimilation on a real DISU model)
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun2/run-log.md` (384 lines; criteria evidence,
  deviations §9, tool gaps §10, tool-call sequence §11, evidence index §12)
- **Type**: closed-book validation rerun. Rerun-1 (2026-09-14) was blocked by the DISU capability
  gap in `setup_da_control`'s IC state parameterisation, fixed 2026-09-14
  (`8fb4742`/`f5d7a4f`; see `sessions/2026-09-14-6d-enkf-disu-rerun1.md`). Rerun-2 is the first
  **green** run.

## Prompt used

The verbatim playbook Target 8 prompt (playbook §"Target 8", "Prompt (paste verbatim into the
Agent Manager session)"; ~80 lines). Summarised:

- Closed-book: do NOT read the groundwater-mcp repo source/tests/plans/prior session logs; the
  target repo's own data and scripts **are** the model specification. Data root
  `GW-MCP-holdout\selected\MF6_EnKF_DISU\`.
- Nine success criteria: (1) `check_environment` first; (2) `adopt_model` the shipped `sim`
  (name ≤ 16 chars, `allow_modify=true`, declared units); (3) `check_model` clean; (4) re-express
  the 6×1-day TDIS as **NPER=1/NSTP=1** per cycle with `set_simulation` (no hand-edited TDIS) and
  define DA cycles explicitly; (5) register the gauges via `import_obs_from_csv(cellid_col="Cell_ID")`
  after ordinary-Python reshaping of `Pegel.csv` + `Pegel_Cell_ID.csv`; (6) `setup_da_control` with a
  log `npf:k` parameterisation, `cycles`, `obs_cycles`, `par_cycles` perlen, `num_reals`,
  `noptmax=1`, `use_simulated_states=True`; (7) `run_pestpp_da` → `summarise_da` (per-cycle phi,
  final phi mean/std, posterior stats, residuals); (8) `plot_heads_map` + final-cycle
  `compare_to_observed` / `read_simulated_observations`; (9) write `run-log.md`.
- **MCP-only constraint**: every adopt/build/run/post-process/assimilate action on the MF6 model
  through a groundwater-mcp tool; no raw flopy/pyemu MODFLOW or PEST classes, no hand-edited
  MODFLOW/PEST files, and the repo's EnKF scripts (`main.py`/`Transient_Run.py`/`generator.py`)
  deliberately not run. Ordinary Python only to reshape the gauge CSVs into the observation table
  fed *into* `import_obs_from_csv`, and to read/print diagnostics. If a tool cannot do something,
  stop and report the gap rather than work around it.

## Tool-call sequence (run log §11; timestamps from the model's `.gwmcp_history.jsonl`, local time)

| # | call | outcome |
|---|---|---|
| 1 | `check_environment` | `ready: true`; flopy 3.10.0 / pyemu 1.4.0; `mf6.exe` + `pestpp-da/glm/ies` located; docs index built |
| 2 | `adopt_model(neckartal, sim\, METERS, DAYS, allow_modify=true)` 17:35 | adopted `flow`; no grid rebuild, no renames |
| 3 | `check_model` | `check_passed: true`, 0 warnings, 0 errors |
| 4 | `set_simulation(nper=1, perlen=[1.0], nstp=[1], ims_complexity="complex")` → `flush_model` | non-destructive TDIS reduction: wrote `modflowsim.tdis`/`.ims`, repointed `mfsim.nam`, shipped `sim.tdis` preserved |
| 5 | `summarise_model`, `model_status` | verified reduced TDIS in memory; DISU `{nnodes 31831, nja 198261, n_active 31522}` |
| 6 | `start_run` → `get_job_status` | converged 1.58 s |
| 7 | `import_obs_from_csv(cellid_col="Cell_ID")` 17:37 | 13 sites / 30 records (scalar DISU node → 1-based OBS id) |
| 8 | `run_simulation` 17:38; second `run_simulation` 17:41 after the K rewire | baseline gauge fit RMSE 4.949 m; uniform-K rewire 5.147 m |
| 9 | `setup_da_control(...)` (tool-default prior) 17:40 | **exceeded the MCP client timeout**, completed on disk; v2 `.pst`, 1 adjustable + 13 `head_state` + 1 fixed = 15 rows, `da_num_reals 30` |
| 10 | `run_pestpp_da(...)` → polled | **client timeout**; completed on disk (`neckartal.global.phi.actual.csv` growing) |
| 11 | `summarise_da` | run 1: final φ mean 19.7651, std 1.23404 |
| 12 | `compare_to_observed`, `read_simulated_observations`, `plot_heads_map` | run 1 postprocess (RMSE 3.239, R² −0.214; DISU head map produced) |
| 13 | `setup_da_control(..., prior_std=2)` 17:57 | head prior sane (std 1.4–2.2 m) but log-K draws 0.0006–50,027 — outside the 1.018–101.8 bounds → **rejected after inspection** |
| 14 | `setup_da_control(..., prior_ensemble=<explicit>)` 17:59 | run 2 configured: K log-uniform [3,30], head `strt + N(0,2 m)` clipped ±6 m, seed 20260915 |
| 15 | `run_pestpp_da(...)` → polled 18:14 | **client timeout**; completed on disk (30 reals × 5 cycles) |
| 16 | `summarise_da` 18:15 | run 2: final φ mean **19.5135**, std **3.10e-05**; posterior head states 1–8 m below shipped `strt` |
| 17 | `compare_to_observed`, `read_simulated_observations`, `plot_heads_map` 18:15 | final gauge fit **RMSE 2.555 m / R² +0.244**; final-cycle head map archived |

## Reprompts

**0 human reprompts** — the run was driven from the single verbatim playbook prompt (the run log
reports no human reprompt; §11 "Reprompts/retries").

Not counted as reprompts (they are tool/transport retries, not human intervention): **three MCP
client timeouts** — `setup_da_control` (step 9) and both `run_pestpp_da` calls (steps 10, 15) —
which returned `−32001` while running correctly server-side. The agent recovered each by polling
`run.info` / `neckartal.global.phi.actual.csv` / the process table on disk, then re-called the
next MCP tool. Step 13's configuration was discarded after inspection (documented), and step 12
needed no rework. All model work still went through MCP tools (run log §10 item 1).

## Outcome vs pre-registered criteria (Target 8)

| Criterion | Result | Evidence |
|---|---|---|
| `check_environment` first | **PASS** | run log §1: `ready: true`, `missing.packages: []`, `missing.binaries: []` |
| Adopt shipped sim; grid/packages match the source set | **PASS** | run log §2: DISU `{nnodes 31831, nja 198261, n_active 31522}`, packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO |
| Single-step re-expression (NPER=1/NSTP=1) documented | **PASS** | run log §4: MCP wrote `modflowsim.tdis` (`NPER 1`) + `modflowsim.ims` and repointed `mfsim.nam`; shipped `sim.tdis` untouched; deviation recorded |
| DA setup: DA-ready v2 `.pst`, `noptmax ≥ 1`, `da_num_reals N`, `da_use_simulated_states True`, a `head_state` param per gauge cell, populated cycle tables | **PASS** | run log §6: `pcf version=2`, `noptmax 1`, `da_num_reals 30`, `da_use_simulated_states True`; 13 `head_state` params; obs/param cycle tables populated (`perlen,1,7,7,7,7`) |
| Run: `run_pestpp_da` over the requested cycles with per-cycle state carry-forward observable | **PASS** (transport caveat) | run log §7: 5 cycles × 30 reals in both runs; run 1 φ 159.4→67.7→19.80→16.10→19.77 (carry-forward visible); run 2 prior→post per cycle 339.2→300.2, 110.0→64.1, 19.44→19.44, 15.79→15.79, 19.51→19.51. Both `run_pestpp_da` calls exceeded the MCP client timeout and were recovered by disk-side polling (§10 item 1) |
| Summarise: per-cycle post-update φ, final-cycle φ mean/std, posterior stats, residuals, no error | **PASS** | run log §7: final φ mean 19.5135, std 3.10e-05; posterior parameter table (n=29); `neckartal_da_residuals.csv` |
| Fit: observed gauges assimilated; prior→post φ reported | **PASS** | run log §7/§8: final-cycle 3 active gauges RMSE 2.5504 m (bias −2.5146, R² −2.45); `compare_to_observed` over all 13 sites RMSE **4.949 → 2.555 m**, bias −4.765 → −2.377, R² **−1.835 → +0.244**. φ scale documented as arbitrary (PEST++ default weight 1.0, baseline not calibrated) |
| Reprompts ≤ 1 | **PASS** | 0 human reprompts; 3 tool/transport timeouts (see above) |
| Closed-book and MCP-only | **PASS** | 0 MCP-only violations; repo EnKF scripts not run; only data-prep Python |
| PASS bar: ≥ 2 consecutive green reruns, last set-and-forget with 0 reprompts / 0 MCP-only violations | **PARTIAL** | rerun-2 is the first green run after rerun-1's capability block → **1 of 2 consecutive**. 0 reprompts / 0 violations recorded; the run log does not record permission prompts, so the set-and-forget property is not established for rerun-2 |

Two findings reported rather than dressed up (run log §7): **`K` is not identifiable from this
data** (drives to its upper bound 101.800 in both runs — heads are nearly insensitive to K over a
single 1-day step) and **the ensemble collapses** (std → 0 by cycle 2, so cycles 3–5 cannot update
further). Reproducibility evidence: the two independent runs converged to posterior head states
agreeing to ≈0.01 m and the same per-cycle φ.

## Deviations from the source model (run log §9)

1. **6 × 1-day → 5 single-step cycles (1, 7, 7, 7, 7 days)** — required by sequential PEST++-DA;
   cycle ends chosen to match the 5 weekly gauge Mondays the repo's EnKF assimilates; written by
   the MCP (`modflowsim.tdis`), no hand editing.
2. **PEST++-DA instead of the bespoke EnKF** — method change (ensemble-smoother/IES-style update
   with cycle tables and `da_use_simulated_states`, not the repo's damped covariance-inflation
   pilot-point EnKF). Results are **not numerically comparable** to the published EnKF; this run
   validates the MCP chain.
3. **`scope="all"` → uniform K (10.18 m/d)** — the shipped heterogeneous field (0.864–86,400 m/d,
   10,413 unique) is replaced by one value; measured effect cycle-0 RMSE 4.95 → 5.15 m. Pristine
   field archived by the tool as `flow_k_pristine.npy`; `zones` infeasible (10,413 zones).
4. **Static boundary forcing** — the shipped RCH/RIV/WEL/CHD/OC carry only PERIOD 1, so NPER=1
   loses no forcing; the repo's per-step forcing from `csv data\2017.csv` is not re-expressed.
5. **State carry-over is partial** — only the 13 observed cells' `strt` carries between cycles;
   the other 31,818 nodes restart from the shipped `strt`. The DISU head field is never written
   back wholesale as the next IC.
6. **IMS options narrowed** — the `complex` preset drops `NO_PTC all` / `OUTER_DVCLOSE 0.1`;
   no convergence impact observed (1.2–1.6 s per run).
7. **Post-processing state** — the on-disk model after a DA run holds the last evaluated
   realisation (final cycle), not the posterior mean; no MCP tool pushes posterior estimates back.
8. **Observation weighting** is PEST++ default (1.0, no measurement-error calibration), so φ is a
   relative prior→post diagnostic, not a goodness-of-fit statistic.

## MCP findings (run log §10 → v0.2.0 backlog)

| # | finding | impact |
|---|---|---|
| 1 | `setup_da_control` and both `run_pestpp_da` calls **exceeded the MCP client timeout** (−32001) while continuing correctly server-side; `get_job_status` covers only `start_run`/`start_calibration`, so DA has no job id or progress API | had to poll `run.info` / `*.global.phi.actual.csv` / the process table on disk; no workaround outside the MCP |
| 2 | state parameters are generated with ±1e6 bounds (the `relative` change limit), so the **default prior ensemble is unphysical** and cycle 0 is wasted | worked around with the documented `prior_ensemble` tool option; fix = seed state params from `strt` with a head-scale std, or clip the prior to physical bounds |
| 3 | `prior_std=2` is applied per-parameter-space: sensible for linear head states but produced log-K draws 0.0006–50,027 (**outside** the parameter's own 1.018–101.8 bounds) | draws are not clipped to `parlbnd`/`parubnd`; `prior_ensemble` is the reliable path for mixed linear/log sets |
| 4 | no tool writes posterior parameters (or the posterior-mean head field) back into the model, and none sets the model IC from the previous cycle's full head output | post-processing reflects one ensemble member; state carry-over limited to observed cells (deviation 5) |
| 5 | `scope="all"` for `npf:k` **silently collapses a heterogeneous K field to uniform** (no error/warning; inferable only from 31,831 identical tokens in `flow_k.dat`) | needs a `scope="multiplier"`/`"factor"` option that preserves the field pattern |

**Verdict (run log §10):** the MCP toolchain was **sufficient** for this target end-to-end
(adopt → check → TDIS re-expression → obs import → DA setup → DA run → summary → map/scatter),
with no raw flopy/pyemu model call and no hand-edited MODFLOW/PEST file.

## MCP-only violations

**0.** No flopy/pyemu MODFLOW or PEST class was called, no MODFLOW/PEST file was hand-edited, and
the repo's EnKF scripts were not executed. Ordinary Python was used only for the allowed gauge
data prep (`scratch\prep_obs.py`) and to read/print diagnostics.

## Time

≈ **42 minutes** (derived, not recorded in the run log): the model's `.gwmcp_history.jsonl` spans
`adopt_model` at 15:35:14Z to `plot_heads_map` at 16:15:22Z (~40 min of model-tool activity) and
`run-log.md` was written at 16:16Z; `check_environment` plus reading the repo specification ran
before the first logged model call.
