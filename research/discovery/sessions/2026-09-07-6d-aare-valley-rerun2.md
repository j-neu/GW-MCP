# 6d session — aare-valley (Zenodo 8047723), rerun-2 — set-and-forget confirmation

- **Date**: 2026-09-07
- **Client / model**: Agent Manager worktree session (`6d-aare-valley-rerun2`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1,
  MF6 6.7.0, PEST++) — server run from committed `main` `110cf13`
- **Worktree branch**: `6d-aare-valley-rerun2` (created from stale base
  `08103b5` by the Agent Manager base-default bug; session unaffected — server
  code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\aare-valley\exportPaper\`
  (Zenodo 8047723, Neven & Renard 2023 WRR, CC BY 4.0) — published
  `HydrologicalModel/` dir restored to pristine (19 shipped files) before this
  run
- **Prompt**: the 6d playbook Target-3 prompt, verbatim (run-2 = confirmation
  run; no prompt changes)
- **Source run-log**: `research/discovery/sessions/2026-09-07-6d-aare-valley-rerun2-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — flopy 3.10.0 / pyemu 1.4.0 / MF6 6.7.0 /
  PEST++; `ready: true`, `missing: {}`.
- **Adopt**: PASS — `aar_2d` adopted read-only at `HydrologicalModel/`
  (mfsim.nam + package files ARE the model; no rebuild, no renames). Shipped
  reference outputs copied to the session's `run-artifacts/` before any run so
  the published "Normal termination" evidence is preserved.
- **Check**: PASS — `check_model` 0 errors; 311 shipped "BC in inactive cell"
  warnings (153 Aar RIV / 115 Gurbe RIV / 42 lake CHD / 1 zero-rate wel)
  documented as the published spec.
- **Run**: PASS — `run_simulation` normal termination, 0.22 s; re-run solve
  **bit-equivalent** to the shipped reference (identical 4 outer / 32 total
  iterations); verified via `get_run_log`.
- **Postprocess**: PASS — `read_heads` 501.278–516.000 m (mean 510.504 m);
  `compute_water_balance` net −0.0019 m³/s → closes (−0.14 %); `plot_heads_map`
  PNG written (not visually inspectable — documented).
- **Calibrate**: PASS — 34 pseudo-obs (from the reference run's `head_obs.csv`,
  identical to the shipped hds at the Obs cells; 2-decimal CSV rounding is the
  documented fit floor) → clone `aar2d_cal` (re-adopted `allow_modify=True`) →
  `import_obs_from_csv` with explicit x/y (all 34 sites map 1:1 to the OBS6
  cells) → `setup_calibration(k)` bootstrap → literal
  `setup_pest_control` → `run_pestpp_glm` → `summarise_calibration`. GLM
  converged (RELPARSTP/NRELPAR, NOPT=4, 10 runs / 0 failed, ~0.45 min),
  φ 3.564e-4 → 3.295e-4, **k = 0.030113 m/s** (recovers the reference 0.03 to
  0.4 %), RMSE 0.00311 m, bias −0.00031 m, R² 0.999999, no parameter at bounds.
- **Posterior comparison**: PASS — published ArchPy posterior (510 realizations,
  log10 K m/s on the 25 m / 202×205 raster) read in its native pickle format.
  Key improvement over run-1: comparison made on a common **transmissivity
  basis** — the MF6 layer is 1 m thick, so its calibrated K is numerically T
  (0.030 m²/s); posterior columns collapsed to T = Σ(10^logK·2 m) give median
  ≈ 0.028 m²/s (log10 −1.56). Calibrated T sits at ≈ p50–p65 of the posterior
  column-T distribution — consistent with the published posterior. Per-cell K
  mismatch (calibrated log10 −1.52 vs posterior gravel ~−3.4/clay ~−7.1) is
  structural (2-D homogeneous depth-integrated T model vs 3-D bimodal
  gravel/clay facies model), documented.
- **Reprompts**: 0 — start-to-finish without operator input (set-and-forget).
- **MCP-only violations**: 0 — Python limited to reading the published ArchPy
  posterior pickles (reference reading) and dataset inspection.
- **Closed-book**: respected per the run-log.

## Deviations from a mechanical transcription (documented in the run-log)

1. Calibration on a clone (`aar2d_cal`), re-adopted `allow_modify=True`
   (clone_model inherits read-only) — published input set never modified.
2. `setup_calibration` used to bootstrap the PEST interface (.tpl/.ins/.pst)
   because no MCP tool writes a bare template/instruction file; the literal
   `setup_pest_control` chain was then run on that interface with explicit obs
   data and gave an identical result to the automated .pst.
3. Pseudo-observed heads derived from the reference run's `head_obs.csv` (=
   shipped hds at Obs cells), 2-decimal precision documented as the fit floor.
4. `import_obs_from_csv` without explicit `x_col`/`y_col` silently maps sites
   in sequential order to the wrong cells — explicit columns required and used.
5. Heads-map PNG not visually QA'd (no image input in this model context).

## Status in the rerun-improvement loop

**PASSED 2026-09-07 (owner tick).** Run-1 (2026-09-07) and rerun-2 (2026-09-07)
are ≥2 consecutive green closed-book full-journey runs; rerun-2 ran
set-and-forget (0 reprompts, 0 permission prompts). Target 3 (aare-valley) of
the 6d Tier-1 gate is complete. See
`research/discovery/sessions/2026-09-07-6d-aare-valley.md` + `-runlog.md` for
run-1 and the registry Round-3 row.

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- **`import_obs_from_csv` silently falls back to sequential site→cell mapping
  when `x_col`/`y_col` are omitted** — a first call without the columns mapped
  all 34 sites to cells [0,i,0] (wrong); passing the columns produced the
  correct mapping. A silent wrong-cell registration is a data-corruption
  footgun: require the columns or error when a coordinate column is absent.
- No MCP tool writes a bare template/instruction file — `setup_calibration` is
  the only .tpl/.ins bootstrap (positive: both the automated and the
  `setup_pest_control`-explicit .pst give identical GLM results).
- `clone_model` read-only inheritance + re-adopt `allow_modify=True` dance
  recurred (already filed from run-1).
- Positive: posterior comparison strengthened — the 1 m layer thickness makes
  the MF6 "K" numerically a transmissivity; comparing calibrated T against the
  posterior column-T distribution resolves run-1's apparent per-cell K gap.

## Time

~20 min wall-clock, dispatched 16:06 UTC and run-log complete by 18:24 local;
no operator interaction during the run.
