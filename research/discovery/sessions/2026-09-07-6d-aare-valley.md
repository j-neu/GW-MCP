# 6d session — aare-valley (Zenodo 8047723), run-1

- **Date**: 2026-09-07
- **Client / model**: Agent Manager worktree session (`6d-aare-valley`,
  kilo/deepseek/deepseek-v4-flash-0731) via groundwater-mcp stack (flopy 3.10.0,
  pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1,
  MF6 6.7.0, PEST++) — server run from committed `main` `e1dbb58`
- **Worktree branch**: `6d-aare-valley` (created from stale base `08103b5` by
  the Agent Manager base-default bug; session unaffected — server code = `main`)
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\aare-valley\exportPaper\`
  (Zenodo 8047723, Neven & Renard 2023 WRR, CC BY 4.0; staged 2026-09-07)
- **Prompt**: the 6d playbook Target-3 prompt, verbatim — refreshed 2026-09-07
  to the D: data path, corrected `exportPaper/` archive layout
  (`HydrologicalModel/`, `ArchPyPrior/`, `ArchPyPosterior/`), and the
  `adopt_model` instruction
- **Source run-log**: `research/discovery/sessions/2026-09-07-6d-aare-valley-runlog.md`

## Outcome vs criteria

- **check_environment**: PASS — flopy 3.10.0 / pyemu 1.4.0 / MF6 6.7.0 /
  PEST++; `ready: true`.
- **Adopt**: PASS — model identified under `HydrologicalModel/` (single GWF
  `aar_2d`, 1 layer × 205 rows × 202 cols @ 25 m, steady state, TIME_UNITS
  seconds) and adopted read-only via `adopt_model`; no rebuild, no renames,
  solved reference outputs in the folder untouched. 16,081 active cells.
- **Check**: PASS — `check_model` 0 errors; 311 shipped "BC in inactive cell"
  warnings (153 Aar.riv / 115 Gurbe.riv / 42 lake.chd / 1 wel) documented as the
  published spec.
- **Run**: PASS — clone `aar_cal` ran to **normal termination**, 0.92 s wall
  (0.34 s MF6); heads **bit-identical** to the shipped reference (min/max/mean
  match to all shown digits) → deterministic reproduction of the published
  solution; verified via `get_run_log`.
- **Postprocess**: PASS — `read_heads` 501.278–516.000 m (mean 510.504 m);
  `compute_water_balance` net −0.0019 m³/s → closes (≈ −0.14 % of mean
  throughput; RIV net-losing, lake CHD main inflow, well −0.283 m³/s);
  `plot_heads_map` PNG produced (not visually inspectable in a text-only
  session — documented).
- **Calibrate**: PASS — chain via `import_obs_from_csv` (34 pseudo-obs derived
  from the shipped reference `aar_2d.hds` at the exact OBS6 cells; values not
  shipped) → `setup_calibration` (1 uniform log-K, NPF rewired to external
  array, bounds [0.003, 0.3]) → `run_pestpp_glm` **converged** (PHIREDSTP, 4
  iters, 10 runs / 0 failed, ~19 s, φ 1.49e-14) → `summarise_calibration`
  (RMSE 2.1e-8 m, R² 1.0) → `check_parameter_sensitivity` (k sensitivity
  ≈ 1.5e-5). Estimate k = 0.0300000002 m/s. The closed-loop self-calibration
  (pseudo-obs from the uniform-0.03 reference) recovers the "truth" K —
  expected and documented; heads are boundary-dominated so uniform K is weakly
  identified.
- **Posterior comparison**: PASS — published ArchPy posterior read in its
  native format (510 realizations of log10 K on the same 25 m / 202×205
  raster): domain geometric-mean K 1.0e-6 m/s (log10 −5.99), gravel ~1e-3 /
  clay ~3e-7 m/s end-members (16.2 % gravel volume). Calibrated MF6 uniform
  0.03 m/s sits ~4.5 orders above the posterior central K — structural
  differences documented (MF6 = single confined-layer effective 2-D forward
  model that generated the synthetic heads vs ArchPy = 3-D bimodal
  clay/gravel stochastic geology; CRS difference prevents cell-wise overlay;
  comparison is statistical).
- **Reprompts**: 0.
- **MCP-only violations**: 0 — Python limited to building the pseudo-obs CSV
  from an MCP-exported reference-head `.npy` and reading the published ArchPy
  pickles (reference reading, not model work).
- **Closed-book**: respected per the run-log.

## Deviations from a mechanical transcription (documented in the run-log)

1. Published model never mutated in place: adopted read-only, ran/calibrated on
   a clone; the only file added to the published folder is the MCP
   reference-head export `aar_2d_heads_l0_k0_0.npy` (shipped inputs untouched).
2. `clone_model` registers read-only models; calibration needs writes (obs
   registration, NPF rewire), so the clone was re-adopted with
   `allow_modify=True` (MCP's own suggested remedy).
3. Observed head VALUES are not shipped → pseudo-obs from the shipped reference
   `aar_2d.hds` (extracted via MCP `read_heads` before any run) at the OBS6
   cells, values agreeing with the model's own `head_obs.csv`.
4. Heads-map PNG could not be visually QA'd (no image input support in this
   model context).
5. Posterior comparison via dataset-native pickles (ArchPy is py3.11-only and
   not installable in the py3.12 env) — plain-python reference reading.

## Status in the rerun-improvement loop

**Run-1 GREEN (2026-09-07)** — full closed-book journey through the MCP
chain: adopt → check → run (bit-identical to the published reference) →
postprocess → GLM calibration → posterior comparison. **NOT PASSED yet** — the
release-gate policy requires ≥2 consecutive green closed-book reruns; rerun-2
is the set-and-forget confirmation run.

## MCP findings (→ v0.2.0 backlog, filed in tasks.md)

- `clone_model` yields a **read-only** registry entry; making the clone
  writable for calibration requires the delete → re-adopt(`allow_modify=True`)
  dance. A `clone_model(allow_modify=…)` option (or writable clones by default)
  would remove the dance.
- `read_heads` wrote its `.npy` export under the model workspace with an
  auto-generated name, ignoring the requested absolute `output_file` path.
- `plot_heads_map` returns a PNG with no in-session visual QA possible.
- Positive: automated `setup_calibration` (obs_source="model" against an
  adopted model's own OBS6 fileout) worked end-to-end — replacement OBS6
  naming matched the generated instruction file.
- Positive: two RIV6 packages in an adopted model presented no problem
  (adopt-model path registers them as-is, unlike the single-boundary-package
  limitation on the create path).

## Time

~30 min wall-clock from dispatch to the completed run-log.
