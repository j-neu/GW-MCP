# 6d session — mf6brabant (Brabant NL regional aquifer), rerun-2

- **Date**: 2026-08-23
- **Client / model**: Agent Manager worktree session (`6d-mf6brabant-rerun2`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack
  (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PESTPP-GLM/IES present)
- **Worktree branch**: `6d-mf6brabant-rerun2`
- **Data**: `GW-MCP-holdout/selected/mf6brabant/` (commit `d681f912`, MIT) —
  flopy-script-only MF6 repo; model reproduced via MCP tools from the data
- **Prompt used**: the 6d playbook Target-1 prompt, verbatim (closed-book +
  MCP-only constraints)
- **Source run-log**: `research/discovery/sessions/2026-08-23-6d-mf6brabant-rerun2-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — flopy 3.10.0 / pyemu 1.4.0 / MF6 6.7.0 /
  geopandas 1.1.3 / rasterio 1.5.0; docs index built.
- **Build**: PASS (500 m tractable model) — 37-layer DIS 225×301 @ 500 m from
  `boundary.shp` (EPSG:28992), 38 raster surface assignments (RL/TH GeoTIFFs),
  NPF (uniform per-layer K/K33 — see deviations), IC (per-layer HH means), OC,
  RIV/DRN/GHB via `import_river_from_shapefile`, RCH (block-lumped),
  WEL (1,775), CHD (3,800 on 19 aquifer layers). A full-resolution 250 m build
  (37×450×601, 6.6M cells) was also constructed but could not be solved.
- **Run**: PASS (500 m) — `start_run`/`get_job_status`: `succeeded`,
  converged, `Normal termination of simulation`, returncode 0, elapsed 55.0 s.
- **Postprocess**: PASS — `compute_water_balance` closes (net −155.7 m³/d on
  1.335e8 m³/d ≈ 0.0001 % discrepancy); `read_heads` layer 0: −46…87 m, mean
  13.8 m (hydrologically plausible for the Brabant lowlands); `plot_heads_map`
  + `plot_cross_section` PNGs.
- **Calibrate**: PASS (chain exercised) — no committed observations, so the
  model's own converged heads at 29 well cells were used as pseudo-observations
  (documented self-fit). `import_obs_from_csv` (29 HEAD) →
  `setup_calibration` (k_scale, npf:k all, initial 1.0, bounds 0.5–2.0) →
  `run_pestpp_glm` (phi 13,809 → 2,449, −82 %; hit upper bound) →
  `summarise_calibration` (improved=true; k_scale=2.0 at bound; RMSE 9.2 m,
  bias 5.5 m, R² 0.36). Chain works end-to-end; fit limited by the single
  global K parameter.
- **Reprompts**: 0.
- **MCP-only violations**: 0 (plain Python limited to data transforms + the
  documented scratch/self-fit exception).
- **Closed-book**: respected — only the target repo's own data/notebooks read.

## Status in the rerun-improvement loop

Run 1 (2026-08-17) was cancelled before completion; **this is effectively the
first green full-journey run** (build → run → postprocess → calibration chain,
all via MCP tools). **Not PASSED yet** — the release gate requires ≥2
consecutive green closed-book reruns (last = set-and-forget) with the
250 m-resolution build converged. Next rerun: fix the findings below, then
re-run.

## Deviations from the source model (documented in the run-log §7)

1. **Grid resolution**: 250 m → 500 m (extent/origin unchanged) — the 6.6M-cell
   250 m model could not be solved under the toolchain-available solver
   settings (see findings).
2. **K field**: uniform per-layer K/K33 (layer means) instead of per-cell zonal
   K — the `assign_k_from_zones` strict `within` join wrote NaN for 31 % of
   cells at 500 m, and extreme thin-layer TX-derived kh up to ~1e5 m/d made the
   full-resolution model non-convergent.
3. **DRN/GHB**: all reaches placed in layer 0 (reference uses 6 layers) —
   `import_river_from_shapefile` cannot assign deeper layers; reaches filtered
   to interior active cells.
4. **CHD**: 19 aquifer layers at ~2 km ring spacing (reference: all 37 layers
   at 250 m).
5. **RCH**: block-lumped 4 km cells (total recharge conserved exactly) instead
   of the full array — RCHA needs an inline full-grid array, infeasible at
   model size.
6. **IC**: per-layer mean start heads (no file-based IC tool); irrelevant for
   steady state.
7. **Calibration** used model-generated pseudo-observations (no committed obs).

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- **`set_simulation(ims_complexity=…)` does not persist to the on-disk
  `mfsim.ims` for adopted models** — the solver could not be strengthened for
  the adopted 250 m model; `clone_model` + `set_simulation` did persist.
- **`assign_k_from_zones` writes NaN for cells the strict `within` join does
  not match** (31 % at 500 m; centroids falling on raster row boundaries) →
  MF6 `forrtl: error (65) floating invalid`. Needs an explicit unmatched-cell
  policy (error / fill / nearest) like `assign_top_from_raster`.
- **`import_river_from_shapefile` cannot assign reaches to layers > 0** and
  places some edge segments in inactive cells.
- **`export_model_spec` / `check_model` on very large models (~10M-cell
  arrays) crash the machine** — memory exhaustion during full-array
  serialisation; twice.
- **RCHA requires an inline full-grid array per stress period** — no file-based
  form, infeasible at regional scale.

## Time

Not recorded precisely; ~200 MCP tool calls across the session.
