# 6d session — mf6_freyberg (usgs/pestpp PEST++ benchmark), rerun-2 — set-and-forget confirmation

- **Date**: 2026-09-07
- **Client / model**: Agent Manager worktree session (`6d-mf6-freyberg-rerun2`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run from committed `main`
  `6dc0503`
- **Worktree branch**: `6d-mf6-freyberg-rerun2` (created from stale base
  `08103b5`; session unaffected — server code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\mf6_freyberg\`
  (usgs/pestpp @ `5d49814`, TM7C26 White et al. 2020; Round-2 holdout) — pristine
  (restored to the exact 102 shipped files before this run); adopted read-only,
  calibration on a byte-identical scratch copy
- **Prompt**: the 6d playbook Target-5 prompt, verbatim (run-2 = confirmation
  run)
- **Source run-log**: `research/discovery/sessions/2026-09-07-6d-mf6-freyberg-rerun2-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — stack reported, `ready: true`.
- **Adopt**: PASS — `freyberg6` adopted read-only in place (grid not rebuilt,
  files not renamed). Calibration ran on a byte-identical scratch copy so the
  shipped reference is never mutated.
- **Check**: PASS — `check_model` 0 errors/warnings; `model_status` runnable.
- **Run**: PASS — all 25 transient stress periods converged / normal termination
  (~0.3–0.4 s); regenerated `heads.csv` matches the shipped reference output
  (one client-side timeout on a run_simulation recovered via the listing, which
  shows normal termination).
- **Postprocess**: PASS — `read_heads` layer-0 means 34.34 m (SP1) → 34.35 m
  (SP25) across all 25 snapshots; `compute_water_balance` closes on period 1
  (net −7.1 m³, 0.26 %); later-period net equals the storage change, absent from
  the `.cbb` because the shipped STO omits `SAVE_FLOWS` (documented);
  `plot_heads_map` L0/SP25 PNG.
- **Calibrate**: PASS — documented subset: 25 monthly RCH params (shipped
  `freyberg6.rch.tpl` bounds/initials) against the shipped SFR stream-obs
  series (`sfr.csv.ins`, 75 tokens; weights as shipped, i.e. the benchmark's 12
  weighted gage-1 monthly flows). Chain: `setup_pest_control` (obs_source=
  "explicit") → `start_calibration(method="ies", num_reals=10)` → job converged
  after 3 iterations, 94 forward runs / 0 failed → best mean φ **417 → 10.3 →
  7.27** on the 12 weighted gage obs (base-run weighted φ 306.03 → calibrated
  ≈ 5.8, ~98 % reduction); `summarise_calibration` residual CSV written
  (unweighted RMSE ≈ 100 m³/d, R² 0.973 on the 12 gage obs); post-calibration
  model still runs clean.
- **Reference comparison**: PASS — documented subset result: the shipped base is
  exactly truth × 1.05 RCH for all 25 months; the IES posterior-mean moved
  toward truth on most months but 12 streamflow obs cannot identify 25 monthly
  recharge values and the omitted K/K33/STO truth perturbations also drive gage
  flow (RMSLE-to-truth 0.218 vs base 0.049) — expected for the deliberately
  under-determined subset, documented as a subset result not a benchmark-grade
  estimate.
- **Reprompts**: 0 — no operator prompts; set-and-forget run.
- **MCP-only violations**: 0 — Python limited to reference-data reads and obs
  payload prep.
- **Closed-book**: respected per the run-log.

## Deviations from a mechanical transcription (documented in the run-log)

1. Calibration on a byte-identical scratch copy (`freyberg6cal`, allow_modify),
   never on the shipped dir.
2. RCH-only documented subset (K/K33/SS/SY cell-wise + WEL templates excluded as
   poorly identified / infeasible: full GLM Jacobian ≈ 8176 runs/iteration).
3. IES engine used (GLM's 1:1 Jacobian base solve failed engine-side; IES on the
   identical pst ran 94 models / 0 failures).
4. One GLM attempt (175 params, all 725 tokens) discarded — its objective was
   corrupted by the 689 dummy observations `setup_pest_control` auto-creates for
   unsupplied instruction tokens; the clean 25-param/75-obs pst was used for the
   recorded calibration.
5. `freyberg6.obs.csv` (a stale 2026-08-16 artifact never opened by mf6) not
   used as a target; authoritative outputs are `heads.csv`/`sfr.csv`/`.lst`.

## Status in the rerun-improvement loop

**PASSED 2026-09-07 (owner tick).** Run-1 (2026-09-07) and rerun-2 (2026-09-07)
are ≥2 consecutive green closed-book full-journey runs; rerun-2 ran
set-and-forget. Target 5 (mf6_freyberg) of the 6d Tier-1 gate is complete. See
`research/discovery/sessions/2026-09-07-6d-mf6-freyberg.md` + `-runlog.md` for
run-1 and the registry Round-2 row.

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- `setup_pest_control` auto-created dummy observations (obsval 1e10, weight 1)
  for unsupplied instruction tokens recurred and corrupted one GLM attempt
  (φ 6.9e22) — a weighted-subset or file-reference option is needed for large
  instruction files (e.g. `heads.csv.ins`, 650 tokens).
- `obs_source="model"` targets single-output-time model obs CSVs ("first output
  row", per-site means) and cannot represent the shipped monthly transient head
  series — explicit path is the transient route.
- GLM Jacobian base solve fails for the small single-group pst here; IES is the
  reliable engine (recurrence of the run-1 finding).
- `summarise_calibration`'s verdict/phi sections are GLM-oriented and return
  empty fields after an IES run (recurrence).
- `compute_water_balance` treats the net transient budget as a discrepancy when
  STO lacks `SAVE_FLOWS` (recurrence).
- Positive: IES calibration on the shipped obs series converged cleanly and cut
  weighted φ by ~98 %; adopt/run/postprocess on the transient DIS+SFR model
  reproduced the shipped reference output.

## Time

~25 min wall-clock; no operator interaction.
