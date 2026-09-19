# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-9 — GREEN (2nd of 2 fresh greens)

- **Date**: 2026-09-17
- **Client**: Agent Manager closed-book session `ses_f4fc3d170ffeBnJgzGYNfEKnwR` (branch
  `6d-enkf-disu-rerun9`, request `am-1789663117343-iil3t2`)
- **Code**: `34d95b9`
- **Holdout**: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` — verified pristine (60 files) at
  dispatch; adopted **in place**, no copy
- **Prompt**: playbook Target 8, step 6 prescribing `scope="all"`, step 2 requiring a fresh name
  (`neckartal_r9`)
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun9/run-log.md` (329 lines)
- **Outcome**: **GREEN** — second of the two fresh consecutive greens; Target 8 is now ready for the
  owner's PASS call.

## What the agent chose (differs from rerun-8, both valid)

It reproduced the source repo's own assimilation loop: **30 DA cycles of 1 day** (`2017-01-30 →
2017-02-28`, mirroring `main.py`'s `for i in range(30)`), 13 gauges / 36 records, `num_reals=20`,
`noptmax=1`, `use_simulated_states=True`, uniform log K (`scope="all"`, initial 10.18, bounds
1.018–101.8). rerun-8 used 6 cycles × 24 reals — the playbook leaves the cycle schedule to the agent,
so the two greens are not carbon copies.

## Tool-call sequence

`check_environment` (ready; mf6 6.7.0) → `adopt_model(neckartal_r9, sim dir, allow_modify, METERS,
DAYS)` → `check_model` (0 errors, 0 warnings) → `summarise_model` / `model_status` →
`set_simulation(nper=1, perlen=[1.0], nstp=[1], ims_complexity=complex)` → `run_simulation`
(1.44 s) → `import_obs_from_csv(cellid_col="Cell_ID")` (13 sites / 36 records) → `run_simulation`
baseline (RMSE 4.954, bias −4.770, R² −1.844) → `setup_da_control` (30 cycles, 13 state params) →
`run_simulation` (rewired check, 1.34 s) → `start_calibration(method="da")` job `d6b50f735128` →
`get_job_status` ×4 → `summarise_da` → `read_simulated_observations` → `compare_to_observed` →
`plot_heads_map` → run log.

## DA result

- Job `d6b50f735128`: **`succeeded`, `converged=true`, 1,551.28 s (25.85 min)**, 30 cycles × 20
  realisations, **0 failed realisations every cycle**.
- Cycle-0 ensemble: prior φ **331.462** (std 23.34) → post-update **274.199** (std 2.68) — a real
  update (−17.3 %, ensemble collapse 23.3 → 2.7).
- Informative cycles only on 0/7/14/17/21/28 (13/9/3/6/2/3 gauges); the other 24 cycles carry no
  observations (φ 0).
- Posterior K: 99.658 m/d (std 4.93, max 101.202) → **pinned at the 10 × initial upper bound**; the
  bulk of realisations sit at the bound, so the estimate is bound-limited (the shipped K spans
  0.864–86,400 m/d).
- Fit: baseline RMSE **4.954** → post-DA `compare_to_observed` **4.620 m**, bias −4.563, R² −1.473 —
  a modest ~7 % improvement, consistent with one uniform K against a spatially systematic bias and a
  site-mean "truth" mixing six dates.
- Honest caveats (agent-documented): φ is not comparable across cycles (unweighted sum over a varying
  gauge count; per-observation φ is flat 15.8–21.4 m²/obs ≈ 4.0–4.6 m RMSE); `summarise_da`'s
  final-cycle residual table is degenerate because cycle 29 has no observations; the job's
  `final_phi_mean 23.83 / std 61.16` is an all-cycle mean, not a final-cycle statistic.

## Compliance (gate-relevant)

- **MCP-only: 0 violations.** No flopy/pyemu/PEST class called directly; no MODFLOW/PEST file
  hand-edited; repo EnKF scripts not run; model not copied. Only ordinary Python was (a) melting
  `Pegel.csv`/`Pegel_Cell_ID.csv` into the observation CSV fed to `import_obs_from_csv` and (b)
  **read-only** inspection of generated artefacts for reporting/verification. The agent states no gap
  forced a workaround.
- **0 human reprompts** — ran unattended to completion. One self-correction: `setup_da_control`
  returned `MCP error -32001` (client timeout; the 31,831-token K template takes ~85 s server-side)
  and the agent verified the completed artefacts instead of re-calling or hand-editing.
- Adopted in place, grid not rebuilt, files not renamed, TDIS re-expressed via `set_simulation`.

## Findings / backlog

1. **`setup_da_control` client timeout on large grids (recurrence)** — confirmed again for
   `scope="all"` (~31,831-token template, server completes ~85 s). Extends the rerun-8 item and the
   rerun-4/5 "no async/job mode for setup" item.
2. **`summarise_da` residual/posterior blocks are final-cycle only** — when the final cycle carries no
   observations the residual table is degenerate (`measured 0`, `weight 0`, `n 0`) and
   `final_phi_mean` can be the all-cycle mean; per-cycle residuals exist on disk
   (`<case>.<cycle>.base.rei`) but no MCP tool exposes them. Consider a per-cycle residual/phi API and
   an explicit `final_cycle`/`informative_cycles` field.
3. **K bound-limited again** (99.7 vs bound 101.8) — the known `scope="all"` limitation; structural fix
   is the deferred `multiplier` scope (helper-wrapper launch defect, tasks.md rerun-7 block).
4. Positive: a 30-cycle background sequential DA ran to completion with zero failed realisations and
   no wrapper, and the whole chain stayed MCP-only.

## Chain status

**rerun-8 GREEN + rerun-9 GREEN = 2 fresh consecutive closed-book greens on code `34d95b9`**, both
with 0 human reprompts and 0 MCP-only violations, both set-and-forget (ran unattended). Target 8's
release-gate PASS call is the owner's. E: was reset from pristine after the run (verified 60 files,
0 differing). The older rerun-4/rerun-5 pair (on `228595c`) remains as prior evidence.
