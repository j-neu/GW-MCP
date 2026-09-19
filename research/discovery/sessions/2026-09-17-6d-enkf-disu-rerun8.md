# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-8 — GREEN

- **Date**: 2026-09-17
- **Client**: Agent Manager closed-book session `ses_f4fe25450ffeHhso1Km2i46XSB` (branch
  `6d-enkf-disu-rerun8`, request `am-1789661116415-r2izeg`)
- **Code**: `34d95b9` (space-free stdlib-only wrapper fix; not exercised this run — see scope note)
- **Holdout**: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` — verified byte-identical to pristine
  (60 files) at dispatch; adopted **in place**, no copy made
- **Prompt**: playbook Target 8, with step 6 prescribing `scope="all"` and step 2 requiring a fresh
  model name (`neckartal_r8`)
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun8/run-log.md` (193 lines)
- **Type**: closed-book validation rerun. **Outcome: GREEN** — the first of the two fresh
  consecutive greens needed on the current code (the second is rerun-9).

## Tool-call sequence

`check_environment` (ready) → `list_models` → `adopt_model(neckartal_r8, sim dir, allow_modify,
METERS, DAYS)` → `summarise_model` → `check_model` (clean) → `set_simulation(nper=1, perlen=[7],
nstp=[1], ims_complexity=complex)` → `check_model` (clean) → ordinary Python obs prep →
`import_obs_from_csv(cellid_col="Cell_ID")` (13 sites, 33 records) → `flush_model` →
`run_simulation` baseline (converged 3.20 s) → `setup_da_control` (scope `all`, 6 cycles,
`num_reals=24`, `noptmax=1`, `use_simulated_states=True`) → `start_calibration(method="da",
num_reals=24)` job `308becd89395` → `get_job_status` ×4 → `summarise_da` →
`read_simulated_observations` → `compare_to_observed` → `plot_heads_map` → `read_heads` →
`run-log.md`.

Generated `neckartal_r8.pst` (pcf v2): `mf6.exe` **direct** model command (no helper wrapper),
`da_num_reals 24`, cycle tables, 15 parameters (1 adjustable log `k` + 13 `head_state` + fixed
`perlen`; 14 adjustable).

## DA result

- Job `308becd89395`: `succeeded`, `converged=true`, **877 s** (14.62 min), **80 model runs**, 24
  realisations, 6 cycles, `pestpp-da` "analysis complete".
- Per-cycle phi (mean): cycle 0 prior **285.362** (std 98.93) → post-update **83.709** (std 0.0746);
  then 63.9691, 19.4395, 15.7904, 19.5135, 18.359.
- Gauge fit: pre-DA baseline RMSE **3.801 m** / R² −0.676 → post-DA `compare_to_observed` RMSE
  **2.553 m** / R² **+0.244** (n=13).
- Honest reading (documented by the agent, confirmed here): only cycle 0 performs a real update
  (per-observation phi 21.95 → 6.44). K immediately pins at its **upper bound (101.8 m/d, std 0)**
  and the ensemble collapses, so cycles 1–5 carry no update; the headline phi decline 83.7 → 18.4 is
  dominated by the observed-site count falling 13 → 3. Per-observation phi is flat (~6.1–7.9) after
  cycle 0. The phi scale is arbitrary (shipped state fits these 2017 gauges poorly); no calibrated
  fit is claimed.

## Compliance (gate-relevant)

- **MCP-only: 0 violations.** No flopy/pyemu/PEST class called directly, no MODFLOW/PEST file
  hand-edited, repo EnKF scripts not executed, model not copied. The agent explicitly states no gap
  would have forced a raw workaround.
- **0 human reprompts** (ran unattended to completion). Two **self-corrections**, both recorded:
  1. `compare_to_observed(output_file=*.csv)` → `COMPARE_FAILED: Format 'csv' is not supported`
     (the parameter takes an image path); re-issued with `.png`. Backlog ergonomics item.
  2. `setup_da_control` returned `MCP error -32001` (client timeout) after ~60 s while completing
     server-side at ~84 s; resolved by verifying the artefacts on disk instead of re-calling.
- Adopted in place, grid not rebuilt, files not renamed; TDIS re-expressed by `set_simulation`
  (not hand-edited).

## Findings / backlog

1. **`setup_da_control` client timeout on large grids even for scope `all`** — the uniform-K
   template spans the full 31,831-node grid (~544 KB `.tpl`), so the call exceeds the MCP client
   timeout while completing server-side. Extends the known "no async/job mode for setup" item
   (rerun-4/5): `all` scope can also time out, not just the pattern-preserving scopes.
2. **`compare_to_observed(output_file=…)` is image-only** — a `.csv` value fails with an
   unhelpful-sounding `Format 'csv' is not supported`; the residuals table is written separately.
   Repeats the Mode B rerun-7 finding.
3. **Default K bounds (±factor 10 around the initial value) are too narrow for this field** — the
   shipped K spans 5 orders of magnitude (0.864–86,400 m/d), so the single uniform K rails at the
   upper bound. The agent documented rather than widened them. This is the known `scope="all"`
   limitation (rerun-4/5) and the motivation for the `multiplier` scope, which is deferred pending
   the helper-wrapper launch defect (`tasks.md` rerun-7 block).
4. Positive: the whole chain — adopt in place on a 31.8k-node DISU model, TDIS collapse, obs import
   with node-id mapping, background DA, summarise, plots — ran MCP-only with no workaround.

## Chain status

rerun-8 = **green #1 of 2** on code `34d95b9`. E: was reset from pristine immediately after (verified
60 files, 0 differing) and **rerun-9 dispatched** (branch `6d-enkf-disu-rerun9`, request
`am-1789663117343-iil3t2`) with the same prompt. If rerun-9 is green, the owner can adjudicate PASS
for Target 8; the PASS call is the owner's.
