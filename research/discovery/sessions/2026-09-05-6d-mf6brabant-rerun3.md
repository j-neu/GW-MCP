# 6d session — mf6brabant (Brabant NL regional aquifer), rerun-3

- **Date**: 2026-09-05
- **Client / model**: Agent Manager worktree session (`6d-mf6brabant-rerun3`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, MF6 6.7.0, PEST++ present) — server run from current `main`
  (3f395fa) in a rebuilt D: venv
- **Worktree branch**: `6d-mf6brabant-rerun3` (created from stale base
  `08103b5` by the Agent Manager base-default bug — see findings; session itself
  unaffected, server code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\mf6brabant/` (commit
  `d681f912`, MIT) — flopy-script-only MF6 repo; model reproduced via MCP tools
  from the data
- **Prompt used**: the 6d playbook Target-1 prompt, verbatim except the DATA
  path corrected to the D: holdout root (the playbook still names the old C:
  path)
- **Source run-log**: `research/discovery/sessions/2026-09-05-6d-mf6brabant-rerun3-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — flopy/pyemu/geopandas/rasterio + MODFLOW 6 +
  PEST++ located; docs index present.
- **Build**: PASS (coarse but fully regional) — 37-layer DIS 45×61 @ ~2.5 km
  from `boundary.shp` (EPSG:28992; the shipped shapefile has no `.prj`, so a
  CRS-qualified copy was written first), 38 raster surface assignments
  (`assign_top_from_raster`, resampled reference RL/TH GeoTIFFs), per-cell
  upscaled K via 37× `assign_k_from_zones` (transmissivity-weighted kh,
  resistance-weighted kv), IC (per-layer HH means), OC, CHD ring on the 19
  aquifer layers (3,971 rec), DRN (3,757), GHB (1,737), RIV (323), WEL (970)
  via external list files, RCHA (45×61 array file). `check_model` clean apart
  from the intentional reference k33=1e6 dummy warning.
- **Run**: PASS — `start_run`/`get_job_status`: `succeeded`, converged,
  `Normal termination of simulation`, returncode 0, elapsed ~1.6 s (mfsim.lst
  confirmed).
- **Postprocess**: PASS — heads −2.5…78 m across layers (layer-1 mean 15.2 m),
  plausible for the Brabant lowlands and closely following the terrain
  (corr ≈ 0.98); `compute_water_balance` closes (net −5.7 m³/d on 1.4e8 ≈
  −4.2e-6 %); `diagnose_water_balance` balanced (CHD rim gross recirculation
  ≈ 94 % of gross flow documented as a representation feature); heads map +
  cross-section PNGs written.
- **Calibrate**: PASS (chain exercised) — no committed observations, so
  synthetic HEAD observations (120 sites) were sampled from a clone's OWN
  simulated heads; the calibration model was deliberately started from a
  misfitting uniform-per-layer K (0.5× geometric mean) and run through
  `setup_calibration` (5 adjustable aquifer-K params) → `run_pestpp_ies`
  (num_reals=6, synchronous) → `summarise_calibration`: phi 78.2→15.11,
  RMSE 0.35 m, bias −0.055 m, R² 0.995, verdict fit_within_measurement_error.
  Background `start_calibration` (GLM and IES) stalled on this host — see
  findings.
- **Reprompts**: 0 (operator issued no mid-run prompts; session ran to
  completion).
- **MCP-only violations**: 0 per the run-log (Python limited to data
  transforms + the documented clone-obs self-fit approach).
- **Closed-book**: respected per the run-log — only the target repo's own
  data/scripts read.

## Status in the rerun-improvement loop

Rerun-2 (2026-08-23, 500 m) and rerun-3 (2026-09-05, 2.5 km) are both green
full-journey closed-book runs — but rerun-3 built at a **coarser** resolution
than rerun-2 rather than advancing toward the reference grid. **Not PASSED**:
the release-gate criterion requires the 250 m-resolution build (450×601×37)
converged, which no rerun has achieved. Rerun-3 documents why: full-resolution
ingestion is blocked by inline-payload limits for 3-D DIS/NPF/IC arrays and by
the absence of raster→K / raster→IC tools and a file-based (OPEN/CLOSE) array
path. Closing the target needs tool work first (or an owner re-scope of the
pass criterion).

## Deviations from the source model (documented in the run-log §3)

1. **Grid resolution**: 250 m reference → ~2.5 km coarse regional grid
   (45×61×37; extent/origin/CRS unchanged; active pattern rasterised from the
   reference polygon).
2. **idomain** outside the polygon = −1 (`import_grid_from_shapefile`) instead
   of 0 — hydraulically identical.
3. **CHD ring** on the 19 aquifer layers only (not confining layers; their
   horizontal K is 1e-6, rim immaterial there).
4. **DRN/GHB/RIV** aggregated per (coarse cell, layer) with cond-weighted
   elevations and summed conductance; inert records dropped.
5. **K** upscaled from the 250 m rasters per layer (heterogeneity preserved at
   coarse scale via `assign_k_from_zones` polygon files).
6. **IC** per-layer scalar means; steady-state only.
7. **RCH** as RCHA areal-mean array (RP1 already m/d).
8. **Calibration** used clone-sampled pseudo-observations (no committed obs).

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- Background `start_calibration` (GLM + IES) stalls on this Windows host under
  the job runner (forward wrapper never spawns mf6); synchronous
  `run_pestpp_ies` works.
- Full-reference-resolution ingestion blocked (3-D arrays + missing raster→K /
  raster→IC and file-based array paths) — the standing blocker for the 250 m
  pass criterion.
- `assign_k_from_zones` replaces the target layer slice and writes NaN for
  unmatched cells instead of preserving existing values.
- Agent Manager worktree base regression recurs (`08103b5`, 26 commits behind
  main) — known extension bug, hygiene otherwise clean (agent committed
  nothing).

## Time

~5.5 h wall-clock (session busy 11:00–16:41 UTC+2); ~200+ MCP tool calls per
the run-log's build/calibration sequences.
