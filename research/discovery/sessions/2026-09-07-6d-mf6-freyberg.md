# 6d session — mf6_freyberg (usgs/pestpp PEST++ benchmark), run-1

- **Date**: 2026-09-07
- **Client / model**: Agent Manager worktree session (`6d-mf6-freyberg`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run from committed `main`
  `171e270`
- **Worktree branch**: `6d-mf6-freyberg` (created from stale base `08103b5`;
  session unaffected — server code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\mf6_freyberg\`
  (usgs/pestpp @ `5d49814`, TM7C26 White et al. 2020; Round-2 holdout) — pristine,
  never mutated
- **Prompt**: the 6d playbook Target-5 prompt (added 2026-09-07, verbatim)
- **Source run-log**: `research/discovery/sessions/2026-09-07-6d-mf6-freyberg-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — stack reported, nothing missing.
- **Adopt**: PASS — `freyberg6` adopted read-only in place (grid not rebuilt,
  files not renamed). Forward run + calibration ran on a writable clone/copy
  (`freyberg6b`), never on the shipped dir.
- **Check**: PASS — `check_model` 0 errors / 0 warnings; `validate_model` clean.
- **Run**: PASS — all 25 transient stress periods converged / normal termination
  (0.36 s); the clone's `heads.csv` reproduces the shipped forward reference to
  ≤ 1e-6 m (max |Δ| 8.1e-7, median 4.0e-8).
- **Postprocess**: PASS — `read_heads` SP1/SP25 plausible (33.7–35.1 m);
  `compute_water_balance` closes on steady SP1 (net −7.12 m³/d, 0.26 %);
  transient-period budget caveat documented (shipped STO lacks `SAVE_FLOWS`, so
  storage fluxes are invisible to the CBB — the unaccounted +1791.5 m³/d is the
  storage term); `plot_heads_map` ×3 PNGs (SP1/SP25 L0, SP25 L2).
- **Calibrate**: PASS — documented subset (25 monthly `rch_0…rch_24` params
  from the shipped parameterisation; 75 SFR stream obs `gage_1`/`headwater`/
  `tailwater` × 25 months from `truth.obs_data.csv`, shipped `sfr.csv.ins`).
  Chain: `setup_pest_control` (obs_source="explicit") →
  `run_pestpp_ies` (25 reals, 6 iterations, 310 forward runs, 0 failed, ~91 s;
  GLM's Jacobian phase is broken in this env — documented, IES allowed by the
  prompt) → results from the IES ensemble outputs. φ 74186 → 24314; RMSE on the
  75 stream obs 149.8 → 18.0 m³/d (native → calibrated); head RMSE improves
  0.121 → 0.035 m (posterior-mean recharge vs shipped truth head series).
  Reference comparison: posterior median recharge drifts from truth in parameter
  space (ln-RMSE 0.049 → 0.137) — expected for the deliberately mis-specified
  recharge-only subset (truth differs also in K/k33/STO/WEL), documented as an
  identifiability finding, not a tool failure.
- **Reprompts**: none reported / no operator prompts; run completed to idle
  unassisted.
- **MCP-only violations**: 0 — Python limited to reading shipped reference CSVs
  and preparing observation inputs.
- **Closed-book**: respected per the run-log.

## Deviations from a mechanical transcription (documented in the run-log)

1. Calibration on a writable copy of the shipped inputs (clone inherits
   read-only) — shipped dir untouched.
2. Calibration completed with **pestpp-ies** instead of GLM — the shipped
   benchmark carries a `run_pestpp_ies` variant and the prompt permits IES;
   pestpp-glm's Jacobian phase fails in this environment (see findings).
3. Recharge-only documented parameter subset (full 8175-param array calibration
   intractable in the time budget; head fit still evaluated post-hoc).
4. Results read from IES ensemble CSVs because `summarise_calibration` cannot
   parse IES `.rei` output (see findings).

## Status in the rerun-improvement loop

**Run-1 GREEN (2026-09-07)** — full closed-book journey through the MCP chain:
adopt → check → run (reference reproduced to ≤1e-6 m) → postprocess →
IES calibration → reference/truth comparison. **NOT PASSED yet** — needs a
consecutive green rerun-2 (set-and-forget confirmation).

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- **`import_obs_from_csv` fails on any model that already carries an OBS6
  package** (`OBS_IMPORT_FAILED: 'list' object has no attribute 'lower'`); no
  tool removes an existing OBS package, so the obs_source="model" path is
  unusable on obs-bearing adopted benchmarks — obs_source="explicit" is the
  only route.
- **`setup_pest_control` silently auto-creates observations for instruction
  tokens not supplied explicitly** (obsval 1e10, weight 1) → corrupts phi
  (φ ≈ 6.5e22) unless every instruction token is passed. Footgun: should error
  or default to a documented behaviour.
- **`run_pestpp_glm` Jacobian phase fails under this Windows/pestpp-glm 5.2.16
  setup** — with the quoted command path every derivative run fails (0 model
  calls); with an unquoted path the base noptmax=0 run works but noptmax>0 GLM
  still reports "failed to compute parameter derivative for all parameters" and
  truncates the template target file to 0 bytes. IES (forward-run-only) is the
  working calibration path.
- **`summarise_calibration` cannot parse PEST++-IES `.rei` output**
  ("observations were not found in <case>.rei") — IES results had to be read
  from `<case>.5.par.csv`/`<case>.5.obs.csv`/`<case>.phi.*.csv`.
- **`compute_water_balance` cannot close transient budgets when the model's STO
  package lacks `SAVE_FLOWS`** (storage fluxes absent from the binary budget
  file) — the tool should detect the missing option and report storage as an
  unobserved term rather than a budget failure.
- Positive: adoption/run/postprocess on a transient DIS model with SFR works
  end-to-end; IES calibration with an explicit shipped instruction file
  converged and improved the fit vs the shipped truth series.

## Time

~30 min wall-clock; no operator interaction.
