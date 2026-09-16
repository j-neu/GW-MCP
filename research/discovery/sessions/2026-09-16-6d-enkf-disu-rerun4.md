# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-4 (regional model validation)

- **Date**: 2026-09-16
- **Client**: Agent Manager closed-book session (groundwater-mcp server on this host)
- **Model**: `neckartal_da` — adopted in place at the shipped
  `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim` (single GWF `flow`)
- **Worktree / branch**: `.kilo/worktrees/6d-enkf-disu-rerun4` (session folder `session6d-t8`)
- **Code**: `228595c` (same code for rerun-4 and rerun-5)
- **Holdout**: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (relocated from `D:` — see playbook)
- **Playbook**: `research/discovery/playbooks/6d-regional-model-validation.md`, **Target 8**
  (sequential EnKF-style data assimilation on a real DISU model)
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun4/session6d-t8/run-log.md`
- **Type**: closed-book validation rerun. Rerun-2 (2026-09-15) was the first green run; rerun-4 is
  the next green run in the sequence. The run log reports **no user reprompt**.

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

## Tool-call sequence (run log §3)

| # | call | outcome |
|---|---|---|
| 1 | `check_environment` | stack verified, `ready=true` (flopy 3.10.0 / pyemu 1.4.0; mf6 + pestpp-da/glm/ies present) |
| 2 | `adopt_model(neckartal_da, …\sim, allow_modify=true, METERS, DAYS)` | adopted in place; `model_names=["flow"]` |
| 3 | `check_model` | clean — 0 errors, 0 warnings |
| 4 | `model_status` / `summarise_model` | runnable; grid + 6×1-day periods + boundary types confirmed |
| 5 | `run_simulation(auto_fix=true)` | as-shipped converged, 5.19 s, 6 steps |
| 6 | `read_heads` ×2 | `kstpkper` = (step, period); mean head 327.07 → 325.56 m over 6 days |
| 7 | `validate_model` | clean, no findings |
| 8 | `set_simulation(1,[62],[1])` + `run_simulation` | worst-case 62-day cycle converges (1.49 s); mean 324.18 m; no drying |
| 9 | `diagnose_water_balance` | balanced, discrepancy 0.007 %, `dominant_term=RIV` (63 %) |
| 10 | `import_obs_from_csv(cellid_col="Cell_ID")` | first pass with all 14 gauges → mapping verified |
| 11 | `set_simulation(27, perlen=gaps, nstp=[1]*27, complex)` + `run_simulation` | open-loop baseline over the identical cycle sequence, converged 17.4 s |
| 12 | `compare_to_observed` / `read_simulated_observations` | baseline per-site table (below) |
| 13 | `describe_model` | provenance: `OBS_0` from the prep CSV, 14 sites, no unverified defaults |
| 14 | `set_simulation(1,[29],[1], complex)` | DA base discretisation (NPER 1 / NSTP 1) |
| 15 | `import_obs_from_csv` (13 gauges) | re-registered for the DA (see R1) |
| 16 | `setup_da_control(...)` | accepted: 1 adjustable + 13 state params, 13 obs, 27 cycles |
| 17 | `start_calibration(method="da")` | job `bd078b8de763`, returns immediately |
| 18 | `get_job_status` ×6 | live per-cycle phi (1047 → 159 → … → 244) |
| 19 | `summarise_da` | per-cycle phi, posterior params, residuals |
| 20 | `compare_to_observed` / `read_simulated_observations` | final-cycle gauge fit (time = 28 d) |
| 21 | `plot_heads_map` | vertex-carrying DISU plot rendered |
| 22 | `setup_da_control` (control) + `start_calibration(method="da")` | job `8a90d1b63746`, 6 cycles |
| 23 | `get_job_status` / `summarise_da` | control results (see finding F2) |

## Reprompts

**0 human reprompts** — the run was driven from the single verbatim playbook prompt. The run log's
"Reprompts / tool friction" entries are tool/transport friction, not user intervention:

- **R1 — `setup_da_control` rejected the 14-gauge observation set.** `INVALID_INPUT: obs_cycles is
  missing registered site(s) ['Ne-507']; every registered site needs a per-cycle observed-value
  mapping.` Ne-507's record starts 2019-01-15, after the model period, so it can never be in
  `obs_cycles`. Re-`import_obs_from_csv` with the 13 in-window gauges fixed it. Ne-507's node
  mapping was already verified in the 14-gauge pass (10692 → 10693 = Cell_ID + 1), so criterion 5
  is met even though Ne-507 is not assimilated.
- **R2 — `run_simulation` returned `MCP error -32001: Request timed out`** on the 1-period base
  case although the run itself finished (listing shows normal termination, 1.644 s, obs CSV
  refreshed). A client-side reporting timeout, not a run failure; re-checked with `get_run_log`.
- **F2 — `summarise_da` is not run-isolated in a reused workspace** (found at step 23; see MCP
  findings).

## Outcome vs pre-registered criteria (Target 8)

| Criterion | Result | Evidence |
|---|---|---|
| `check_environment` first | **PASS** | run log §1: `ready=true`, missing packages/binaries none |
| Adopt shipped sim; grid/packages match the source set | **PASS** | run log §2: DISU **31,831 nodes / NJA 198,261 / 31,522 active**, NVERT 11,430, vertices + CELL2D; packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO |
| Single-step re-expression (NPER=1/NSTP=1) documented | **PASS** | run log §5 item 1: DA base is `set_simulation(model, 1, [perlen], [1])`; 27 cycles declared explicitly; **no TDIS file hand-edited** |
| DA setup: DA-ready v2 `.pst`, `noptmax ≥ 1`, `da_num_reals N`, `da_use_simulated_states True`, a `head_state` param per gauge cell, populated cycle tables | **PASS** | run log §3 step 16: 1 adjustable + **13 state** parameters, 13 obs, **27 cycles**; §4: `use_simulated_states=True`, `noptmax=1`, `num_reals=20` |
| Run: N-realisation ensemble over the requested cycles; per-cycle carry-forward observable | **PASS** | run log §6: `converged: true`, **20 reals**, **27 cycles**, 56.27 min (72 model runs per cycle group) |
| Summarise: per-cycle post-update φ, final-cycle φ mean/std, posterior stats, residuals, no error | **PASS** (caveat F2) | run log §6: per-cycle φ list + final-cycle φ mean **243.778**, sd **4.77e-8**; §7 control posteriors read from `neckartal_da.5.1.par.csv` because `summarise_da` returned run-1 leftovers in the reused workspace |
| Fit: gauges assimilated; prior→post-update φ reported; uncalibrated baseline documented | **PASS** (as reported, not dressed up) | run log §6: cycle-0 prior φ **1047.48** → post **212.77** (−79.7 %); final-cycle gauge fit **RMSE 4.330 m, bias −4.190 m, R² −1.028** — **worse** than the 0.673 m (13-gauge) open-loop baseline |
| `plot_heads_map` + final-cycle `compare_to_observed` / `read_simulated_observations` | **PASS** | run log §8: DISU map rendered (heads 291.77–342.54 m); per-site residuals listed; gauge→node mapping verified for all 14 gauges |
| Reprompts ≤ 1 | **PASS** | 0 human reprompts (R1/R2/F2 above are tool findings, not reprompts) |
| Closed-book and MCP-only | **PASS** | run log preamble: 0 MCP-only violations; repo EnKF scripts read, never executed |
| PASS bar: ≥ 2 consecutive green reruns, last set-and-forget with 0 reprompts / 0 MCP-only violations | **PARTIAL** | rerun-4 is a completed green run of the chain (with rerun-2 the ≥2 count is met), but the single global-K parameter pinned at its upper bound and the ensemble collapsed, so the DA degraded the final fit vs the open-loop baseline; the strict "no workarounds / set-and-forget" PASS call is left to the owner |

## Deviations from the source model (run log §5)

1. **6 × 1-day periods → 27 single-step cycles.** Sequential PEST++-DA needs NPER=1 / NSTP=1 per
   cycle (the canonical OBS-CSV instruction file reads the first data row). Applied with
   `set_simulation(model, 1, [perlen], [1])`; **no TDIS file was hand-edited**. Windows
   **2017-01-30 → 2018-12-20**; cycles = every `Pegel.csv` date at which ≥ 8 gauges report a valid
   value (the repo's own `>7` test); `perlen(k) = date(k) − date(k−1)` with `date(−1) = 2017-01-01`;
   total 718 days, perlen 7–62 d.
2. **Bespoke EnKF → PEST++-DA.** The repo implements its own EnKF with `damp_K = 0.05`,
   `damp_h = 0.35`, `eps = 0.01 m²`; the MCP path exposes no damping/inflation knob (`noptmax`,
   `num_reals`, `obs_weights`, `prior_std`, parameter bounds are the levers). This is the direct
   cause of the ensemble collapse in run log §6/§7.
3. **Constant forcing retained.** The shipped `sim\` model has period-1-only RCH/WEL; the brief
   scoped the work to re-expressing the shipped run, so the shipped forcing was kept. Consequence:
   no seasonal signal, so the model cannot track the gauges' seasonal cycle.
4. **IMS complexity pinned to `complex`** to match the shipped `sim.ims` (the tool default is
   `moderate`).
5. **OBS package added** (`flow.obs` + `flow_head.obs.csv`) and the `sim\` directory mutated;
   `sim.tdis` / `sim.ims` rewritten, PEST interface files added, `flow_output\` overwritten. No
   grid rebuild, no file renames, `disu`/`npf`/`ic` array files untouched.
6. **IC = the shipped `flow.ic_STRT_1.txt`** (the initial state of `Transient_Run.py`, 2017-01-01);
   the repo's EnKF instead overwrote IC with `Final_h_field.mat`.
7. **Ne-507 not assimilated** (record begins 2019-01-15, outside the model period).

## MCP findings (run log §9 → v0.2.0 backlog)

| # | finding | impact |
|---|---|---|
| 1 | `setup_da_control` requires `obs_cycles` to cover **every** registered site, so a gauge with no data inside the simulation window cannot be left out of the DA — it must be un-registered | Ne-507 (record starts 2019-01-15) had to be dropped from registration; the run log reports it, not worked around |
| 2 | `summarise_da` is **not run-isolated**: in a reused workspace with fewer cycles than a previous run it reported the **previous** run's posterior ensemble and residuals (it reported `k = 10.0`, outside the control run's 0.5–2.0 bounds, and residuals against the earlier gauges) while the per-cycle φ list was correct | mitigation: one workspace per DA run (e.g. `clone_model`), or cross-check the reported final cycle against `neckartal_da.global.<cycle>.pe.csv`; run-1's summary was checked and is consistent with `neckartal_da.26.1.par.csv` |
| 3 | `scope="all"` on `npf:k` **replaces the heterogeneous K field with one uniform value** (the K multiplier was initialised at 1.0 and pinned at 10.0 after the first update in run 1; the 6-cycle control with 0.5–2.0 bounds pinned at 2.0) | root cause of the ensemble collapse; the MCP exposes no damping/inflation, and no `scope="multiplier"` that preserves the base pattern |
| 4 | `plot_heads_map` on this DISU grid produces a map but its colour scale is not quantitatively readable in rerun-5 (run log for that rerun) | post-processing caveat; see rerun-5 session |

Not a tool defect but reported: the run's modelling outcome is that the sequential DA ends-to-end
and delivers a real, large first-cycle misfit reduction (φ 1047 → 213, −80 %; control 251 → 146 →
36), but the 20-member ensemble **collapses at the first update** because the single global K
multiplier is driven to its bound; under the shipped constant forcing the state then drifts away
from the seasonally varying gauges, and the final-cycle fit (RMSE 4.330 m) is **worse** than the
0.673 m open-loop baseline. This is a configuration/identifiability finding, not an MCP capability
failure.

## MCP-only violations

**0.** No flopy/pyemu MODFLOW or PEST class was called, no MODFLOW/PEST file was hand-edited, and
the repo's EnKF scripts were not executed. Ordinary Python was used only for the allowed gauge data
prep (`prep_gauge_analysis.py`, `prep_build_obs.py`) and to read/print diagnostics.

## Time

The run log records the DA wall times, not the session total: DA run 1 **56.27 min** (27 cycles ×
20 reals), the 6-cycle control **14.87 min**. Total closed-book session time is not recorded in the
run log.
