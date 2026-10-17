# Changelog

All notable changes to groundwater-mcp. The format follows
[Keep a Changelog](https://keepachangelog.com/). Nothing has been tagged or
published yet; everything below is on `main` and will ship as the first
release.

## [Unreleased]

### Added

- **Core MODFLOW 6 workflow (92 tools, 2 prompts, 3 resource templates):**
  environment preflight, offline docs search, parameterisation from rasters,
  shapefiles and CSVs, model building (DIS/DISV/DISU, NPF, IC, STO, CSUB,
  boundary packages, OC), running with job control, post-processing and
  export (heads, budgets, drawdown, water balance, GeoTIFF/shapefile/CSV).
- **Calibration with PEST++:** `setup_calibration` (uniform, zoned and
  multiplier K), GLM/IES/DA runners, summaries, uncertainty,
  parameter-sensitivity screening, and sequential ensemble data assimilation
  (`setup_da_control`, `run_pestpp_da`, `summarise_da`).
- **`import_boundary_from_shapefile`:** CHD from lines/polygons and WEL from
  points, reprojected into the grid CRS, inactive cells reported.
- **MODPATH 7:** `run_modpath` (forward/backward tracking on a completed flow
  run) and `plot_modpath_pathlines`, verified against the plug-flow velocity.
- **`add_mvr_package`:** water mover between package features, verified with a
  real well-to-stream run.
- **`add_advanced_package`:** SFR, MAW, LAK and UZF (feature-based packages;
  `add_boundary_package("SFR")` never worked), each verified with a real run.
- **GWT solute transport:** `add_gwt_model` and `add_gwt_adv/dsp/mst/ssm/cnc/src_package`,
  an FMI-coupled derived simulation like GWE; `read_concentration` and
  `plot_concentration_map` now serve both GWT and the legacy MT3D-USGS model.
- **`run_pestpp_sen`:** Morris (mu*, sigma, per-observation-group) and Sobol
  (first-order and total indices) global sensitivity, run on a copy of the
  control file.
- **`run_pestpp_sweep`:** Latin-hypercube or explicit-CSV parameter sweeps via
  pestpp-swp, with per-run phi and simulated observations.
- **`run_pestpp_opt`:** constrained optimisation (decision parameters, objective,
  observation constraints) via pestpp-opt.
- **`start_task`:** runs heavy tools (check_model, raster assignment, DA setup, ...) as
  background jobs, one per model at a time.
- **Pilot-point K calibration:** `setup_calibration(scope="pilot_points")`
  places pilot points on a lattice or at given coordinates, interpolates
  log10 K multipliers to every cell by ordinary kriging, and writes the
  variogram's prior covariance as the PST `parcov` so pestpp-ies draws a
  spatially correlated prior. A synthetic two-zone test recovers the
  west/east K contrast (23.5 / 2.1 m/d against a 20 / 2 truth).
- **Transient head time-series calibration:** on a model with more than one
  time step, `setup_calibration` / `setup_pest_control(obs_source="model")`
  (uniform, zoned and pilot-point scopes) turn every dated head record into
  its own observation, matched to the nearest time step (calendar dates via
  `start_date_time`, numbers as elapsed model time; `obs_time_tolerance`,
  default one median step). Unmatched records are reported in
  `time_series`. `compare_to_observed` and the sensitivity screen use the
  same series. A synthetic pumping test recovers K and Ss with pestpp-glm
  (7.996 / 1.017e-3 against 8 / 1e-3). Previously every site was collapsed
  to the mean of its records and compared with the first time step.
- **One MF6/PEST++ process per workspace:** runs and calibrations claim the
  workspace and a second start returns `WORKSPACE_BUSY` (a retried call after
  a client timeout used to start a second pestpp). The process PID goes in a
  workspace lock file, so an orphan from an earlier server session is
  detected; `release_workspace_lock` terminates it. Running jobs are
  terminated on server shutdown, and children are spawned with stdin detached
  from the MCP stdio pipe. The intermittent background-calibration stall
  itself is not root-caused; this prevents the collision and orphan cases.
- **`apply_calibration_result`:** writes the calibrated parameters of a GLM/IES
  run (including zone multipliers) back into the model, so the calibrated
  field can be run, plotted and exported.
- **Declarative specs and provenance:** `apply_model_spec`,
  `export_model_spec`, `export_reproducible_script`, `describe_model`,
  `export_model_report`, `clone_model`, `compare_scenarios`.
- **Diagnostics:** `diagnose_convergence`, `validate_model`,
  `diagnose_water_balance`, `model_status` with `next_steps`.
- **Subsidence:** `add_csub_package`, `read_compaction`, `plot_subsidence`,
  `import_subsidence_observations` and derived-observation calibration.
- **Multi-model simulations (v0.3.0 scope):** GWE heat transport
  (`add_gwe_model` and packages, `read_temperature`, temperature plots), PRT
  particle tracking (`add_prt_model` and packages, `read_pathlines`,
  `plot_pathlines`), and read-only MT3D-USGS post-processing
  (`adopt_mt3d_usgs_model`, `read_concentration`, `plot_concentration_map`).
- Closed-book validation of the Tier-1 real-model targets: Brabant, Zenodo
  21381071, Aare Valley, GMS `mf6_pest_obs_ss`, Freyberg, Neversink, 1D
  subsidence (CSUB) and Neckartal EnKF (DISU). See `tasks.md` and
  `research/holdout-registry.md`.

- **Worked example:** `examples/catchment_walkthrough.py` and
  `docs/examples/catchment-walkthrough.md`, smoke-tested in the suite.
- **Second worked example:** `examples/capture_zone.py` (well capture zone by MODPATH vs the analytical width), `docs/examples/capture-zone.md`.
- **Packaging:** PyPI metadata, a tag-triggered trusted-publishing workflow, CI
  that installs the MODFLOW 6 / PEST++ binaries, `CONTRIBUTING.md`, issue
  templates.

### Changed

- `adopt_model` reads `LENGTH_UNITS`/`TIME_UNITS` from the model files
  instead of defaulting to METERS/DAYS; a contradicting argument is an error.
  Models built by the MCP now write `LENGTH_UNITS` into their grid package.
- `summarise_model` labels undeclared K/recharge units in the model's own
  units and reports `model_rate`.
- `clone_model` copies the whole workspace tree and is writable by default,
  even for a read-only adopted source.

### Fixed — silent wrong answers now fail loudly

- `import_grid_from_shapefile` rejects a `layer_surfaces` list that is not
  `nlay + 1` long; it used to ignore it and build flat default layers.
- `import_river_from_shapefile` takes a `layer` and skips reaches on inactive
  cells (reported as `reaches_inactive_skipped`) instead of writing every reach
  to layer 0.
- `read_heads` honours `output_file`; `compare_to_observed` writes the residual
  table to an `output_file` ending in `.csv` instead of failing.
- CI's Python matrix now actually selects the interpreter (`UV_PYTHON`) and
  includes 3.13.
- **PEST++ on Linux/macOS:** every calibration failed there. Two causes:
  - the default forward command was pyEMU's `model.bat` placeholder, because
    the MF6 default was only set on Windows;
  - pestpp drops the leading `/` of an absolute command path before running it.

  Commands now use the MF6 binary on every platform, with workspace-relative
  paths on POSIX, including caller-supplied `model_command`s.
- Raster sampling failed with rasterio < 1.5 (the newest available on
  Python 3.11), which has no `CRS.equals`.

- `import_obs_from_csv` rejects sites more than about a cell outside the grid
  (`allow_outside=True` snaps them) instead of snapping every far-away site to
  an edge cell; a stale registry entry no longer shadows a newly created model
  of the same name; `mcp` is capped below 2.x so a fresh install imports.

- `import_obs_from_csv` no longer maps sites to cells in row order when no
  coordinates or cell ids are given (`allow_sequential=True` opts in); it also
  gained `append=True` to register a multi-layer set one layer per call.
- `setup_pest_control` no longer writes instruction tokens or template tokens
  that have no `obs_data`/`par_data` entry with placeholder values
  (`unlisted_obs="zero_weight"` keeps extra observations at weight 0).
- `setup_calibration`/`setup_da_control` refuse to replace a spatially varying
  K (or K33) field with one value unless `allow_flatten: true` is set.
- `assign_k_from_zones` never writes NaN: active cells outside every polygon
  are an error unless `unmatched="keep"` or `"nearest"`.
- `compute_water_balance`/`diagnose_water_balance` report missing STO
  `SAVE_FLOWS` as `storage_flows_missing` instead of an imbalance.
- Earlier gate work: transposed x/y in the `stage_raster` sampler, the river
  importer CRS check, layer-bound validation, adopted-model overwrite
  protection, GLM phi parsing from `.iobj`, and MF6 stdio detachment in the PEST++
  forward wrapper.
