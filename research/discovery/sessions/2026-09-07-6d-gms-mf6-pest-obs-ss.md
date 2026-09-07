# 6d session — GMS `mf6_pest_obs_ss` (Aquaveo tutorial), run-1

- **Date**: 2026-09-07
- **Client / model**: Agent Manager worktree session (`6d-gms-pest-obs-ss`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, MF6 6.7.0, PEST++) — server run from committed `main` `777681e`
- **Worktree branch**: `6d-gms-pest-obs-ss` (created from stale base `08103b5`;
  session unaffected — server code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
  (Aquaveo GMS 10.9 tutorial; local validation use). Zip not modified — the
  agent extracted into its own session folder and adopted/ran there.
- **Prompt**: the 6d playbook Target-4 prompt variant with the verified MF6
  folder path (`sample/pest_obs_ss_MODFLOW-quadtree_mf6/`) inlined
- **Source run-log**: `research/discovery/sessions/2026-09-07-6d-gms-mf6-pest-obs-ss-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — stack reported, `ready: true`.
- **Adopt**: PASS — `pest_obs_ss` adopted via `adopt_model` (allow_modify=True)
  at the shipped runnable MF6 folder; 1-layer DISV grid (NCPL 3306), FEET/DAYS,
  K=2.4, RCH 7.62e-5; grid not rebuilt. Shipped solved reference (`model.n2b`,
  `pest_obs_stats.txt`, `model.bsamp.out`/`fsamp.out`, `obs.out`) found under
  `sample/pest_obs_ss_models/MODFLOW 6/pest_obs_ss/GWF_Model_{output,pest}/`
  and compared against (§7).
- **Check**: PASS — `check_model` clean after the CHD fix (below); 0
  errors/warnings.
- **Run**: PASS — after removing a shipped duplicate-CHD-cell defect,
  `run_simulation` converged / normal termination (0.21 s).
- **Postprocess**: PASS — `read_heads` (3306/3306 active; 304.8–316.636 ft),
  `compute_water_balance` closes (−2.53 ft³/d ≈ 0.04 % of throughput),
  `plot_heads_map` PNG.
- **Reference reproduction**: PASS — rerun heads/RIV-flow are **identical to
  the shipped solved reference** (head RMSE 10.2748, mean |res| 7.95 vs
  `pest_obs_stats.txt` 10.274824/7.951675; RIV outflow −5434.207 vs reference
  −5434.209). The shipped `pest_obs_stats.txt` is the *uncalibrated base-run*
  statistics, which our rerun reproduces exactly.
- **Calibrate**: ❌ **BLOCKED — tool capability gap (see findings).** The
  calibration chain was not reached; the agent stopped per the MCP-only rule
  rather than working around with raw flopy/pyemu or hand-written PEST files.
- **Reprompts**: 0 (no permission prompts).
- **MCP-only violations**: 0 — Python limited to obs-CSV prep from shipped
  interface files and reference comparison.
- **Closed-book**: respected per the run-log.

## Deviations from a mechanical transcription (documented in the run-log)

1. **Shipped CHD defect fixed via MCP**: `pest_obs_ss.chd` lists cell (1,32)
   twice (heads 78.11 and 226.69) → MF6 aborts. The shipped solved reference
   uses 41 single records all at 304.8 ft. Re-added CHD through
   `add_boundary_package` (41 records @ 304.8) + flush. Auxiliary
   SHEADFACT/EHEADFACT/CELLGRP columns (GMS transient interpolation, unused in
   steady state) dropped as in the reference.
2. **OC re-pointed to `.hds`/`.cbc`**: GMS writes `pest_obs_ss.hed`/`.ccf`,
   which the MCP postprocess tools cannot read (`OUTPUT_FILE_MISSING`);
   `add_oc_package` re-pointed output to `.hds`/`.cbc`. Physics unchanged.
3. Re-serialisation of the input set on flush (canonical flopy layout); all
   parameter values unchanged.
4. Obs registration / calibration attempted on DISV — see findings.

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- **DISV grids are unsupported by the obs/calibration/reporting layer.**
  `import_obs_from_csv` coordinate mode throws
  `OBS_IMPORT_FAILED: 'ModflowGwfdisv' object has no attribute 'ncol'`;
  `setup_calibration(obs_source="model")` throws
  `PEST_ERROR: ... no attribute 'nrow'`; `summarise_model` throws the same. All
  three dereference structured-DIS `nrow`/`ncol` on the grid object. Sequential
  (no-coordinate) registration "works" on DISV but maps sites to nodes 1..10 in
  order — meaningless for this model. The GMS quadtree MF6 model cannot be
  calibrated through the MCP chain until DISV cell-centroid obs mapping +
  DISV-aware calibration/summary exist (or the obs interface learns the
  model.n2b cellid/interpolation form directly).
- **Compound multi-cell flow observations not representable**: the shipped
  interface includes one flow obs (sum of RIV leakage over CELLGRP 1–6,
  observed −4644, simulated −5434) — the obs-import interface has no budget/
  multi-cell aggregate form even on a DIS grid.
- No PEST `.pst`/`.tpl`/`.ins` is shipped anywhere in the zip (the tutorial's
  PEST side is a GMS GUI workflow) — obs values live in `model.bsamp`/`fsamp`
  (bore/flow sampling files), interpolation weights in `model.n2b`.
- Positive: adoption + run + postprocess on the DISV model work; the MCP run
  reproduces the shipped solved reference bit-for-bit at the observation sites.

## Status in the rerun-improvement loop

**Run-1 (2026-09-07): build/run/postprocess PASS + exact reference
reproduction; calibration BLOCKED by the DISV obs/calibration tool gap. NOT
green** — criterion 6 unmet. The clean stop validates the error envelope but
does not pass the target. A rerun is only meaningful after the gap is closed
(DISV obs registration/calibration) or the target is re-scoped to a
structured-grid GMS MF6 model. Registry Round rows + tasks.md 6d target updated
2026-09-07; no checkbox tick.

## Time

~25 min wall-clock; 0 reprompts; no operator interaction.
