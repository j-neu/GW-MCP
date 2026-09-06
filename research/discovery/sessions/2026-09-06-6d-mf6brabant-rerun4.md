# 6d session — mf6brabant (Brabant NL regional aquifer), rerun-4 — FULL RESOLUTION

- **Date**: 2026-09-06
- **Client / model**: Agent Manager worktree session (`6d-mf6brabant-rerun4`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, MF6 6.7.0, PEST++) — server run
  from committed `main` `7faabab` (raster→array tools shipped)
- **Worktree branch**: `6d-mf6brabant-rerun4` (created from stale base
  `08103b5` by the Agent Manager base-default bug; session unaffected — server
  code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\mf6brabant/` (commit
  `d681f912`, MIT)
- **Prompt**: rerun-4 variant of the 6d Target-1 prompt — full 250 m build is
  the primary goal; coarse grids explicitly not acceptable as the headline
  result; non-convergence at full res to be reported as the central finding
- **Source run-log**: `research/discovery/sessions/2026-09-06-6d-mf6brabant-rerun4-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — stack above; MF6 + PEST++ located.
- **Build — FULL 250 m (PRIMARY)**: PASS — 450×601×37 = 10,006,650 nodes
  (6.64M active) from `boundary.shp` at `cell_size=250` via
  `import_grid_from_shapefile`; 38× `assign_top_from_raster`; 37×
  `assign_k_from_raster` (per-layer K + k33 GeoTIFFs; active K 1e-6 … ~1.2e5);
  37× `assign_ic_from_raster` (HH field −22.4…111 m); RCH via
  `assign_array_from_raster` (RCHA.recharge, auto-created); CHD 79,180 / DRN
  835,135 / GHB 290,222 / RIV 11,195 / WEL 3,722 records via external list
  files (`stress_period_data={0: {"filename": …}}`). Every cell-valued input
  file-first — no inline payloads. MF6 prep-check clean after two documented
  data filters (see deviations).
- **Run — FULL 250 m**: PASS — reproduced twice + final obs run;
  `Normal termination of simulation`, job `f4d96f86b241` elapsed 259 s (final
  run 198 s), ~5.8 GB memory, `diagnose_convergence` = converged.
- **Postprocess**: PASS — L1 heads −23.4…110.1 m (mean 15.0 m, close to HH1,
  plausible); deepest-layer mean 14.0 m; `compute_water_balance` net −199 m³/d
  (−7.4e-5 %); CHD rim = 96.6 % of throughput (intrinsic to the source
  perimeter ring, not an error); heads map + obs-fit PNG written.
- **Calibrate**: chain exercised on a clone (`brabantcal`, noptmax=0) —
  import_obs_from_csv (21 well-site synthetic heads) → setup_calibration
  (37 whole-array npf:k params, 190 MB `.tpl`) → pestpp-glm 1/1 forward runs
  clean → initial phi 10.76, RMSE 0.716 m, bias −0.088 m, R² 0.993. Full
  optimisation documented as out of scope at this resolution (≥ 38 runs/iter ×
  ~8.5 min); toolchain lacks zoned K parameters.
- **Reprompts**: 0 (operator issued none; run to completion). Internal
  incidents: one server-connection loss mid-build (recovered by window reload,
  assignments re-run sequentially), repeated heavy-call client timeouts
  (completed server-side), one pestpp double-launch collision (killed, single
  relaunch clean).
- **MCP-only violations**: 0 per the run-log (Python limited to data
  transforms + external boundary file prep).
- **Closed-book**: respected per the run-log.

## Deviations from a mechanical transcription (documented in §4 of the run-log)

1. MF2005 inactive boundary records (cond ≤ 0: 295k DRN + 296k GHB rows)
   dropped — MODFLOW 6 aborts on them; the committed reference notebooks do
   not filter and would abort identically. Closest faithful representation.
2. 74 CHD records (0.09 % of the ring set) on geologically absent cell–layer
   pairs (RL/TH sentinels < −9990) excluded — these produced cancelling
   ±1.5e14 m³/d fluxes between stacked fixed-head layers.

No grid-resolution degradation anywhere.

## Status in the rerun-improvement loop

rerun-3 (2026-09-05, coarse 2.5 km) and rerun-4 (2026-09-06, full 250 m) are
consecutive green closed-book full-journey runs, and rerun-4 delivers the
explicitly missing **250 m-resolution converged build**. On the stated
criterion ("≥2 consecutive green reruns incl. the 250 m-resolution build") the
target is met — **PASSED 2026-09-06 (owner tick)**. Target 1 (mf6brabant) of
the 6d Tier-1 gate is complete; a rerun-5 would only be needed to produce a
second consecutive full-resolution green.

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- No zoned/multiplier parameterisation for spatially-distributed K — real
  full-res calibration impractical through `setup_calibration`.
- `check_model` exceeds the client timeout on ~10M-node models (in-solve MF6
  prep-check is the effective gate).
- Parallel heavy parameterise calls dropped the server connection mid-run;
  heavy writes must be serialised at this scale.
- Heavy `flush_model`/`start_run`/`start_calibration` exceed the ~300 s client
  timeout but complete server-side; job-id-on-timeout would remove ambiguity.
- Timed-out `start_calibration` can double-spawn pestpp → collision; the job
  runner must guarantee a single pestpp instance.
- Positive: file-first ingestion at full resolution works; the earlier
  "250 m never converges" claim was a toolchain-state artifact, not a solver
  ceiling.

## Time

Session busy 10:10–18:54 local; ~8.5 h wall-clock including the multi-GB
flushes and the repeated full-res runs.
