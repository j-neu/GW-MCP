# groundwater-mcp — Architecture

An open-source Python MCP server for AI-assisted groundwater modelling with MODFLOW 6, FloPy, PEST++, and pyEMU.

---

## Overview

The server exposes 74 tools across 7 modules, plus 2 MCP prompts and 3 MCP resource templates, running locally over stdio transport. All computation happens on the user's machine — no external API calls, no waitlist, no paywall.

```
  [geodata-mcp]          Claude / AI client
  (future companion)             │  MCP protocol (stdio)
         │                       ▼
         │  rasters/   ┌─────────────────────────────────────────────┐
         │  shapefiles/│         groundwater-mcp  (Python)           │
         └────────────▶│  tool dispatcher · workspace manager        │
                       │  error handling · logging                   │
                       └──┬──────┬──────┬──────┬──────┬─────────────┘
                          │      │      │      │      │
                        docs  param  builder runner  post  calib
                          │      │      │      │      │      │
                          └──────┴──────┴──────┴──────┴──────┘
                                          │
                          ┌───────────────┼──────────────┐
                          │               │              │
                   geopandas /        flopy.utils    pyEMU /
                   rasterio /         (heads, plots) PEST++
                   FloPy + MF6
                          │               │              │
                          └───────────────┴──────────────┘
                                          │
                            local filesystem workspace
                          (model files · output · plots)
```

---

## Module responsibilities

### environment
Preflight checks for a hands-free session. `check_environment` reports the server's own Python interpreter, the installed packages (flopy, pyemu, geopandas, rasterio) with versions, the paths to the MODFLOW 6 / PEST++ executables, the local docs index state, and the default workspace root — so an agent verifies the stack in one call instead of probing with shell commands (which commonly hit the wrong interpreter).

### docs
Builds a local full-text + semantic search index from the public MODFLOW 6, FloPy, and PEST++ GitHub repositories at install time. Works fully offline. No external API required.

### parameterise
Translates processed spatial data — rasters, shapefiles, and CSVs — into MODFLOW 6 model inputs. Covers the gap between real-world data and a runnable model: building a grid from a catchment shapefile, assigning layer elevations from a DEM, distributing hydraulic conductivity from geological zone polygons, generating river/drain stress period data from a river network, and importing borehole or gauging station observations for calibration. Uses `geopandas` and `rasterio`; expects data that is already in the correct CRS and resolution — raw spatial processing is handled upstream.

### model builder
Wraps FloPy's MODFLOW 6 GWF API to create and configure models programmatically — grids, packages, boundary conditions, and output control. Manages a per-session workspace directory.

### runner
Invokes the MODFLOW 6 binary via FloPy's `run_model()`, streams stdout/stderr, and returns structured convergence status. Also runs FloPy's pre-run model checker.

### post-processing
Reads binary output files (`.hds`, `.cbb`) via `flopy.utils`, computes derived quantities (drawdown, water balance, CSUB compaction/subsidence), and generates plan-view, cross-section and subsidence time-series plots as PNG files.

### calibration
Uses pyEMU to set up and run PEST++ (PESTPP-IES and PESTPP-GLM) for parameter estimation and uncertainty analysis. Invoked as a subprocess with file-based I/O. Returns phi progress, residual statistics, and predictive uncertainty bounds.

DA-ready control files (2026-09-14): `setup_da_control` emits the PEST++ **version-2** control file that `pestpp-da` v5.2.16 needs for sequential ensemble data assimilation. It reuses the `setup_calibration` NPF-`k` rewire/template path, rewires the IC `strt` array to an external array, and generates a state-augmented IC template with one state parameter per registered observation cell (sharing the observation name, so `da_use_simulated_states True` carries each cycle's simulated heads into the next cycle's IC). It writes the observation/parameter cycle tables, sets `da_num_reals`/`da_observation_cycle_table`/`da_parameter_cycle_table`/`da_use_simulated_states`, and requires `NPER=1`/`NSTP=1` so the canonical MF6-OBS-CSV instruction file reads the end-of-cycle value. `run_pestpp_da` executes it.

Zoned K multiplier calibration (2026-09-11): `setup_calibration(scope="zones")` auto-derives zones from groups of equal positive per-layer `npf:k` values and turns each zone into a dimensionless multiplier parameter (`<prefix>_z<index>`). It writes `<gwf>_k_base.dat`, `<gwf>_k_zone.dat` and `<gwf>_k_mult.dat.tpl` and forces a forward wrapper that computes `k = base_k × multiplier[zone]` before each MODFLOW 6 run, so the base spatial K pattern is preserved and only zone magnitudes are calibrated. This closes the neversink `setup_calibration` uniform-only (whole-scope per-layer replacement) parameterisation gap.

DISV support in the obs/calibration/reporting layer (2026-09-12): FloPy's `gwf.get_package("dis")` falls back to a partial package-type match, so on a DISV model it returns the `ModflowGwfdisv` package for `"dis"` too — every `if dis is not None` branch silently took the structured-DIS path and dereferenced the missing `nrow`/`ncol`. `utils/grid.py` (`get_dis`/`get_disv`/`get_grid`) now returns a package only when it is the requested grid type; all 22 call sites use it. `import_obs_from_csv` coordinate mode maps sites to `(layer, node)` on DISV, and `summarise_model`/`describe_model`/`export_model_spec`/non-zoned `setup_calibration` work on unstructured grids. Output discovery (`_find_output_file`/`_find_budget_file`) also resolves OC-declared paths relative to the workspace (subdirectories) and accepts the GMS `.hed`/`.ccf` extensions. This closes the GMS `mf6_pest_obs_ss` Tier-1 blocker.

DISU (fully unstructured) support (2026-09-13): `add_disu_package` builds a grid from explicit node connectivity (NODES/NJA + IAC/JA, with per-node TOP/BOT/AREA and optional IHC/CL12/HWVA/ANGLDEGX; JA is 0-based and IHC/CL12/HWVA default to single-layer/unit placeholders so a connectivity-only model runs). `utils/grid.py` gains `get_disu`/`grid_size`, and the grid resizing/recognition path (`model_status`, `summarise_model`, DISU-aware `setup_calibration` and `import_obs_from_csv` scalar node ids) is DISU-aware. DISU has no cell x/y when defined without vertices, so `plot_heads_map` and coordinate-mode obs import fail with a clear message while `read_heads`/`compute_water_balance` work. This unblocks the `MF6_EnKF_DISU` Tier-1 target.

CSUB subsidence support (v0.3.0, 2026-09-19): `add_csub_package` builds the MODFLOW 6 CSUB package — 11-field interbed `packagedata` with delay/no-delay `cdelay`, `ndelaycells`, `sgm`/`sgs`/`cg_theta`/`cg_ske_cr`, cell- and interbed-based observation records, and `zdisplacement`/`strainib`/compaction filerecords. `read_compaction` turns the CSUB observation output into per-layer compaction plus a derived cumulative subsidence series (and `interbed_strain` when the strain file is present); `plot_subsidence` renders that series as a PNG with an optional observed overlay. `import_subsidence_observations` registers a measured subsidence CSV as a **derived** time-series target (the recipe for the simulated series), and `setup_calibration` gains a target resolver (`csub:packagedata`, `csub:cg_theta`, `csub:cg_ske_cr`, `npf:k33`) plus `obs_source="derived"`, which builds the PEST++ instruction file from the derived series rather than the head-obs first row (the calibration forward wrapper materialises `<gwf>_subsidence.csv` for PEST++). This is the capability behind 6d playbook Target 9 (`1DSubsidenceModeling-MF6CSUB`). Validation status (2026-09-24): rerun-1 (2026-09-20) was green-with-gaps; reruns 2–6 built, ran and post-processed `H201` green MCP-only, and the calibration forward wrapper now detaches MF6's stdio from PEST++'s FIFO pipes (commit `f1e7015`, fixing the `<gwf>.lst`-sized pipe-buffer deadlock), but the calibration step has been intermittent: it completed on rerun-7 (2026-09-24) via the **synchronous** `run_pestpp_ies` (IES φ 1119.56 → 15.68, RMSE 0.315 ft, R² 0.925), while a **background** `start_calibration` job stalled under the MCP server with the client polling — a stall that is not reproducible in isolation (the same background job completes 364 runs in 90 s from a plain script). See `tasks.md` 6d Target 9 rerun-6/rerun-7 findings. **Rerun-8 (2026-09-24) then completed the loop green set-and-forget** (208/208 derived observations matched by nearest matching with no resampling, IES φ 575811 → 14.03, RMSE 0.2596 ft, R² 0.7904, 0 reprompts / 0 permission prompts / 0 MCP-only violations), so rerun-7 + rerun-8 are two consecutive green closed-book runs with the last set-and-forget and the **v0.3.0 gate condition is met (owner tick 2026-09-25)**.

---

Multi-model-per-simulation foundation (v0.3.0, 2026-09-25): a single MODFLOW 6 simulation can now hold several models of different types — a flow model (`gwf`), an energy-transport model (`gwe`) and a particle-tracking model (`prt`) — addressed by an optional `component` argument on the model-scoped tools. `utils/components.py` is a small registry mapping a component name to its FloPy model/grid/IC/OC classes and its exchange class; `model_store.get_model(name, component)` resolves the model through the component map persisted in `.gwmcp_meta.json` (auto-detected by model class on `adopt_model`), with `get_gwf` a thin delegate so every existing call is unchanged. The shared builder tools (`add_dis_package`/`add_disv_package`/`add_disu_package`/`add_ic_package`/`add_oc_package`/`set_model_crs`) and `get_run_log` take `component="gwf"`; the internal `add_component_model` creates a component with the source grid mirrored and the `GWF6-GWE6`/`GWF6-PRT6` exchange registered, and `summarise_model`/`model_status` report the components present. This is the internal foundation the GWE and PRT capability specs build on; it ships no user-facing tool.

GWE heat transport (v0.3.0, 2026-09-25): a registered model can own a **second, derived simulation**. `add_gwe_model` creates a `ModflowGwe` model in `<workspace>/gwe/` whose `ModflowGwefmi` package reads the flow run's head/budget files (MF6's flow-model interface), so heat transport runs *after* a completed flow run rather than as a same-simulation exchange. `model_store` caches component simulations beside the flow simulation (`get_component_sim`, `cache_component_sim`), `save_sim`/`flush_model` stage and write them, and the component map entry for such a component is a dict `{model, workspace}`. `run_simulation` runs the flow model first and the heat model second, reporting per-component success. The flow model is made FMI-ready automatically (model/package `save_flows` plus NPF `save_specific_discharge`/`save_saturation`), and the GWE heat solver uses BICGSTAB (asymmetric matrix). GWE packages: `adv`, `cnd`, `est`, `ssm` (required with flow boundaries), `esl`; grid/IC reuse the `component="gwe"` shared tools, and `add_oc_package(component="gwe")` writes the temperature file. Post-processing: `read_temperature`, `plot_temperature_map`, `plot_temperature_timeseries`.

---

## File structure

```
groundwater-mcp/
├── src/
│   └── groundwater_mcp/
│       ├── server.py           ← MCP entrypoint, tool registration
│       ├── tools/
│       │   ├── docs.py         ← search_docs, search_tutorials, get_doc_file
│       │   ├── parameterise.py ← import_grid_from_shapefile, assign_top_from_raster, assign_k_from_zones, assign_k_from_raster, assign_ic_from_raster, assign_array_from_raster, import_river_from_shapefile, import_obs_from_csv, import_subsidence_observations
│       │   ├── builder.py      ← create_model, adopt_model, add_*_package, summarise_model
│       │   ├── runner.py       ← run_simulation, check_model, get_run_log
│       │   ├── postprocess.py  ← read_heads, read_budget, read_compaction, plot_*, compute_*
│       │   ├── calibration.py  ← setup_pest_control, run_pestpp_*, summarise_*
│       │   └── environment.py  ← check_environment (preflight stack check)
│       └── utils/
│           ├── workspace.py    ← model directory management
│           ├── plotting.py     ← shared matplotlib helpers
│           ├── components.py   ← component registry for multi-model simulations
│           └── spatial.py      ← shared raster/vector helpers (rasterio, geopandas)
├── scripts/
│   └── build_index.py          ← indexes docs at install time
├── tests/
│   └── ...
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
├── TOOLS.md
└── TASKS.md
```

---

## Technology stack

| Component | Library / tool |
|---|---|
| MCP server | `mcp` (Anthropic Python SDK) |
| Groundwater modelling | `flopy` ≥ 3.7 |
| MODFLOW binary | MODFLOW 6 (downloaded separately via `get-modflow`) |
| Spatial parameterisation | `geopandas`, `rasterio`, `scipy` |
| Calibration | `pyemu`, PEST++ binaries |
| Plotting | `matplotlib`, `flopy.plot` |
| Docs index | `whoosh` (full-text) + `sentence-transformers` (semantic) |
| Testing | `pytest` |
| Packaging | `uv` / `pyproject.toml` |

---

## Testing strategy

Three layers, each catching different failure modes:

| Layer | What it tests | When to run |
|---|---|---|
| **Pytest integration tests** (`tests/test_tutorial_*.py`) | Tool logic with real spatial data from the sealed dev set `tests/fixtures/tutorial_04` and `tutorial_05` | Every commit (CI) |
| **MCP protocol tests** (`tests/test_mcp_protocol.py`) | JSON-RPC message handling, tool registration, error envelope schema | Every commit (CI) |
| **Holdout replay (Mode A)** (`tests/test_holdout_replay.py`) | Automated build→run→postprocess replay of sealed projects (test051, test020) + GAP clean-failure gates | Dry-run green; official run at the v0.1.0 freeze |
| **Mode B manual Layer-3** | Natural-language usability, tool-description quality, full user journey on a closed-book held-out tutorial | Complete (dry-run + rerun-2/3/4, 0 reprompts each; rerun-4 = set-and-forget, zero permission prompts; separate transient-run session) |
| **6d regional-model validation** | Closed-book rerun-improvement loop on real regional models (mf6brabant, zenodo-21381071, aare-valley, GMS pest_obs_ss, freyberg, neversink, CSUB, EnKF-DISU) | Run 1 green for zenodo-21381071 (2026-08-17); **all reruns held until the promoted 7e+7f v0.1.0 gate work is done** (owner decision 2026-08-17d) |
| **Manual Claude Desktop walkthrough** | Natural-language usability, tool description quality, full user journey | Before each release (optional — Mode B is the recorded protocol) |

The tutorial datasets used are:

- **Tutorial 04:** `activeZone.shp` (catchment boundary), `ASTGTM2_S14W077_dem_WGS84_18S_cut_grd` (DEM), zone shapefiles — exercises the full parameterisation pipeline
- **Tutorial 05:** `chd_high.shp`, `chd_lower.shp`, `river.shp`, `wells.shp` — exercises boundary conditions, runner, and post-processing

The original tutorial material (including further ModelMuse tutorials, GMS tutorials
and getting-started exercises) is sealed in the sibling holdout folder
`GW-MCP-holdout/` outside this repo; see `research/holdout-registry.md` for the
pre-registered validation protocol (Mode A replay via `GW_MCP_HOLDOUT` env var,
Mode B manual sessions). Holdout data never enters `tests/fixtures/`.

See `TASKS.md` Phase 6 for the full test checklist.

---

## Design principles

- **Local-first.** All computation runs on the user's machine. No data leaves the environment.
- **Open source.** MIT licensed. All source code public, no closed components.
- **Composable.** Each module is independently testable and importable outside the MCP context.
- **MODFLOW 6 only (v1).** Supporting the modern standard first; legacy versions can be added later.
- **Fail loudly.** Tool errors return structured error objects with actionable messages, not silent failures.
- **Clear scope boundary.** This MCP covers model parameterisation from processed data through to calibrated results. Raw spatial preprocessing (CRS reprojection, DEM hydrological conditioning, borehole kriging, climate data processing) belongs in a companion `geodata-mcp`. The handoff format is standard files: GeoTIFF, GeoPackage/Shapefile, CSV.

### Known deviations from these principles (audit 2026-08-17b)

Recorded here so the document describes the code as it is, not only as
intended. Each has atomic remediation tasks in `TASKS.md` § 7e.

**Fixed by the 7f-D gate work (2026-08-17e):** the "fail loudly" principle is
now enforced on the spatial/data layer. `stage_raster` sampling fails with
`STAGE_RASTER_NO_COVERAGE` instead of silently guessing stages (D1); the river
importer errors `CRS_UNKNOWN` rather than comparing coordinates in an assumed
space (D2); layer indices are validated against `nlay` (`INVALID_INPUT`) (D3);
adopted models are read-only by default so a stray builder call cannot rewrite
a real published model, and the cache reloads from disk when package files
change externally (D4).

Remaining deviations:

- **Composability is limited by response size, not by module boundaries.**
  Post-processing tools serialise whole grid arrays into the response
  (~38 MB for a 1600×1252 domain), so the modules compose in Python but not
  over MCP at regional scale (7e-A1). *(A1 done 2026-08-17: `read_heads`/
  `compute_drawdown` return stats + `.npy` by default, `read_budget` returns
  aggregates with a record cap, `summarise_calibration` caps residuals —
  the remaining A1.7 regional verification is a 6d-replay item.)*
- **No long-job story.** All execution is blocking `subprocess` with no
  timeout, polling, or cancellation, so runs exceeding the client timeout
  push callers out of the MCP entirely (7e-A3). *(fixed 2026-08-18 by 7e-A3:
  `start_run`/`start_calibration` run in a background thread and return a job
  id; `get_job_status` reports live progress; `cancel_job` terminates the
  process.)*
- **The tool layer is currently a 1:1 FloPy transcription.** It exposes the
  library rather than the expertise; diagnostic/validation/export tools that
  would justify the layer are catalogued as 7e Tier C. *(C1 done 2026-08-22:
  `diagnose_convergence` classifies a non-converged run — closure tolerance,
  idomain connectivity, Newton/dry-cell risk, K contrast — from the model
  configuration rather than 20 lines of raw `.lst` tail. C2 done 2026-08-22:
  `validate_model` aggregates physical-plausibility defects (heads above
  top/below bottom, K contrast, disconnected active cells, boundaries on
  inactive cells) into one finding per type instead of the 569,796 individual
  warnings a real regional model produced. C3 done 2026-08-22:
  `diagnose_water_balance` reports the same percent-discrepancy MODFLOW
  itself computes, a `balanced` verdict, and whether one boundary type is
  absorbing most of the flow — instead of the raw inflow/outflow table
  `compute_water_balance` already returned. C4 is superseded by the
  already-shipped `compare_to_observed` (ticked, bookkeeping only). C5 done
  2026-08-22: `export_heads_to_raster` (georeferenced GeoTIFF, delegating to
  flopy's own `export_array`), `export_boundaries_to_shapefile` (one feature
  per boundary stress-period cell), and `export_water_balance_csv` — the
  finished-model-back-to-GIS path this deviation named as missing. C6 done
  2026-08-22: two MCP prompts (`build_model_from_data`, `calibrate_model`)
  encode the ordering an agent otherwise infers by trial and error. C7 done
  2026-08-22: three MCP resource templates (`gwmcp://models/{model}/lst`
  /`pst`/`files`) expose per-model files as readable URIs. C8 done
  2026-08-22: `model_status` plus a `next_steps` list auto-attached to every
  builder/parameterise tool's result — the ordering constraints this
  deviation named (`add_sto_package` needs TDIS, `assign_k_from_zones` needs
  NPF, `import_grid_from_shapefile`'s undocumented `set_simulation`
  prerequisite) now surface proactively instead of only as the next call's
  error. All of 7e Tier C is done except the `[human]` closed-book
  verification criteria on C1/C6/C8, which need a live agent session to
  confirm — not yet run.)*

**Fixed by the 7e-B gate work (2026-08-18):** the "fail loudly" principle is
now enforced on the calibration path too. `summarise_calibration` returns
`OUTPUT_FILE_MISSING` when a run died before writing residuals instead of a
successful-looking empty result (B2), and the broad `except Exception`
swallows on the calibration hot path are narrowed to the specific
data-errors expected, so corrupt `.par`/phi files surface as errors (B3).
Tool results are additionally sanitised of NaN/Inf before JSON serialisation
(B12).
