# groundwater-mcp — Tool Reference

74 tools across 7 modules, plus 2 MCP prompts and 3 MCP resource templates. All tools are registered with the MCP server and callable by any compatible AI client.

---

## environment

Preflight check for a hands-free session. Reports the server's own runtime stack so the agent verifies the environment instead of probing with shell commands.

| Tool | Inputs | Returns |
|---|---|---|
| `check_environment` | *(none)* | Python version/executable, installed packages with versions (flopy, pyemu, geopandas, rasterio, ...), MODFLOW 6 / PEST++ binary paths, docs index state, default workspace root, `ready` flag + missing items |

## docs

Search and retrieve documentation from MODFLOW 6, FloPy, PEST++, and pyEMU. Index is built locally at install time from public GitHub repositories.

| Tool | Inputs | Returns |
|---|---|---|
| `search_docs` | `query: str`, `repos: list[str] \| None`, `method: "text" \| "semantic" \| "auto"`, `limit: int = 10` | List of matching doc snippets with source paths and relevance scores |
| `search_tutorials` | `query: str`, `complexity: "beginner" \| "intermediate" \| "advanced" \| None`, `limit: int = 5` | List of matching notebooks/examples with descriptions and paths |
| `get_doc_file` | `path: str`, `page: int = 1` | Full file content (paginated at 30 KB) |
| `describe_package` | `name: str` | The MODFLOW 6 package specification — each block's dataset (keyword) names and, for boundary packages, the `stress_period_data` record fields; CSUB is included and returns its interbed `packagedata` fields (7f-I3) |

Semantic search requires the optional `semantic` extra
(`pip install groundwater-mcp[semantic]`). Without it, `method="semantic"`
returns `SEMANTIC_SEARCH_UNAVAILABLE` and `method="auto"` falls back to
full-text (7f-I2).

---

## parameterise

Translate processed spatial data (rasters, shapefiles, CSVs) into MODFLOW 6 model inputs. These tools accept standard GIS file formats and produce the arrays and stress period data consumed by the model builder. They expect *already-processed* data — reprojection, resampling, and interpolation from raw sources is handled upstream by a companion tool or manually.

| Tool | Inputs | Returns |
|---|---|---|
| `import_grid_from_shapefile` | `model: str`, `shapefile: str`, `nlay: int`, `layer_surfaces: list[str]`, `method: "disv" \| "dis" = "disv"`, `target_crs: str \| None` | Grid summary: cell count, layer count, CRS, bounding box |
| `assign_top_from_raster` | `model: str`, `raster: str`, `layer: int = 0`, `method: "mean" \| "min" \| "max" \| "nearest" \| "bilinear" = "nearest"`, `fill: "error" \| "median" \| "nearest" = "error"`, `coverage_tolerance: float = 0.1` | Array statistics (min, max, mean), `cells_assigned`, `cells_no_coverage`, optional `warning` |
| `assign_k_from_zones` | `model: str`, `shapefile: str`, `k_field: str`, `layer: int \| list[int]`, `k33_field: str \| None`, `icelltype_field: str \| None` | Zone summary: zone count, cell count per zone, K range |
| `assign_k_from_raster` | `model: str`, `raster: str \| list[str]`, `layer: int \| list[int] = 0`, `k33_raster: str \| list[str] \| None`, `method: "mean" \| "min" \| "max" \| "nearest" \| "bilinear" = "nearest"`, `fill: "error" \| "median" \| "nearest" = "error"`, `coverage_tolerance: float = 0.1` | Per-layer assignments, `cells_assigned`, `cells_no_coverage`, `k_range`, optional `warning` |
| `assign_ic_from_raster` | `model: str`, `raster: str \| list[str]`, `layer: int \| list[int] = 0`, `method: "mean" \| "min" \| "max" \| "nearest" \| "bilinear" = "nearest"`, `fill: "error" \| "median" \| "nearest" = "error"`, `coverage_tolerance: float = 0.1` | Per-layer assignments, `cells_assigned`, `cells_no_coverage`, `head_range`, optional `warning` |
| `assign_array_from_raster` | `model: str`, `target: str` (`NPF.k` / `NPF.k33` / `IC.strt` / `STO.ss` / `STO.sy` / `RCHA.recharge` / `EVTA.surface` / `EVTA.rate` / `EVTA.depth`), `raster: str \| list[str]`, `layer: int \| list[int] = 0`, `stress_period: int = 0`, `method`, `fill`, `coverage_tolerance`, `rate_units: str \| None` | Per-layer or per-period assignment counts, written `value_range`, optional `warning` / `value_warnings`, `rate_units` when converted |
| `import_river_from_shapefile` | `model: str`, `shapefile: str`, `package: "RIV" \| "DRN" \| "GHB"`, `stage_field: str \| None`, `cond_field: str \| None`, `depth_field: str \| None`, `stage_raster: str \| None`, `stage_offset: float = 1.0`, `coverage_tolerance: float = 0.1`, `stress_periods: list[int] \| None`, `bed_k: float \| None`, `bed_thickness: float \| None`, `channel_width: float \| None` | Stress period data summary: reach count, stage source, per-reach coverage count, package written |

**Conductance is derived, not guessed (7f-H1.2):** pass a `cond_field`
attribute, or `bed_k` + `bed_thickness` + `channel_width` and the tool computes
`cond = bed_k * channel_width * reach_length / bed_thickness` per reach. With
no conductance source the call fails loudly — the old
reach-length-as-conductance default was dimensionally wrong (L vs L²/T).

NOTE: with no stage attribute/raster, river stage defaults to 0.0 m and the river acts as a deep drain. Pass `stage_raster` (a ground-surface elevation GeoTIFF) to derive stage as raster value minus `stage_offset`, or provide a `stage_field` attribute. RIV records are `[cellid, stage, cond, rbot]`; DRN/GHB records are `[cellid, elev, cond]`.

**stage_raster coverage (7f-D1):** stage is sampled at each reach cell's true centroid. If more than `coverage_tolerance` (default 10%) of reaches fall outside the raster extent the call fails with `STAGE_RASTER_NO_COVERAGE` naming the uncovered count — stages are never silently guessed. On success the result reports `reaches_no_raster_coverage` (0 when fully covered).

**CRS safety (7f-D2):** the river is reprojected into the model grid's CRS when they differ. If the grid has no CRS but the shapefile declares one, the call fails with `CRS_UNKNOWN` (coordinates are never compared in an assumed coordinate space). A disjoint but same-CRS shapefile returns `NO_INTERSECTION` with the grid and shapefile bounding boxes in the message.

**`assign_top_from_raster` method is honoured, not ignored (7e-B5):** `method="mean"/"min"/"max"` are per-cell zonal aggregations (regular DIS grids with uniform `delr`/`delc`; non-uniform grids error `INVALID_INPUT` — use `nearest`/`bilinear`). `"nearest"` and `"bilinear"` sample at the cell centroids.

**`assign_top_from_raster` CRS + coverage (7e-B11.2):** a model grid without a CRS sampled against a raster that declares one returns `CRS_UNKNOWN` (set one first with `set_model_crs` or `import_grid_from_shapefile(target_crs=...)`). A raster that covers none of the grid cells errors `INVALID_INPUT` naming the mismatch.

**No-data fill is explicit (7e-B11.3):** `fill` controls cells without raster coverage. Default `"error"` fails when more than `coverage_tolerance` (default 0.1) of cells are uncovered and otherwise median-fills with a `warning` field; `"median"` always median-fills; `"nearest"` fills from the nearest covered cell. `cells_no_coverage` is always reported.

**`layer_surfaces` on the DISV branch (7e-B6):** rejected with `INVALID_INPUT` — build flat layers and assign surfaces afterwards with `assign_top_from_raster`.
| `import_obs_from_csv` | `model: str`, `csv_file: str`, `obs_type: str` (HEAD/DRAWDOWN/DEPTH/CONCENTRATION/TEMPERATURE), `site_col: str`, `date_col: str`, `value_col: str`, `x_col: str \| None`, `y_col: str \| None`, `layer: int = 0`, `cellid_col: str \| None = None` | Observation summary: site count, record count, date range, written observation file path |
| `import_subsidence_observations` | `model: str`, `observed_csv: str`, `time_col: str = "datetime"`, `value_col: str = "Subsidence_ft"`, `sim_source: dict \| None`, `name: str = "subsidence"`, `match: str = "nearest"`, `tolerance_days: float \| None`, `date_map: dict \| None` | Registered derived target: observation count, resolved time/value columns, `sim_source` (`csv`/`sum_cols`/`time_col`), `match`/`tolerance_days`/`date_map` |

`import_obs_from_csv` persists the observation targets as model state
(7f-F1.1): the site → cellid map, observed values and dates are stored in
`.gwmcp_meta.json` under `observations`, so `summarise_model` reports the
registered target count and the observation loop
(`read_simulated_observations`, `compare_to_observed`, and
`setup_pest_control(obs_source="model")`) can consume them.

**Large grids:** the site→cell spatial join over a ~2M-cell regional grid
with thousands of sites can exceed the client's 60 s call timeout. The server
completes the import anyway (the call is not transactional with the timeout),
so after a `-32001 Request timed out` just verify `summarise_model`/the
obs summary CSV, then continue — the client may need its MCP connection
re-established before further calls (2026-08-30 rerun-5 finding).

### Notes

- `import_grid_from_shapefile` uses `flopy.utils.GridGen` (DISV) or derives a regular DIS grid from the polygon bounding box.
- `assign_top_from_raster` uses `rasterio` to sample the raster at cell centroids and writes the result to the model's top or botm arrays.
- `assign_k_from_zones` intersects cell centroids with zone polygons via `geopandas`; cells outside all zones retain their existing K.
- `assign_k_from_raster` / `assign_ic_from_raster` sample a GeoTIFF at cell centroids (`nearest`/`bilinear`) or aggregate per cell (`mean`/`min`/`max`, regular DIS grids only) and write the K/k33 (NPF) or starting-head (IC) arrays per layer — the raster-based route for per-cell K fields (e.g. TX/CL GeoTIFF layers, or a fine K raster against a coarse model grid). Raster values must already be in the model's K units. Coverage/fill semantics match `assign_top_from_raster`; the K variant refuses non-positive/non-finite K in active cells. `raster` accepts one path reused across layers or a list of paths (one per layer); a mismatched list is refused, never silently remapped.
- `assign_array_from_raster` is the catch-all for any other model array driven by a raster: an enumerated target table names the (package, array) pair — `NPF.k`/`NPF.k33`, `IC.strt`, `STO.ss`/`STO.sy` (per layer) and `RCHA.recharge`, `EVTA.surface`/`EVTA.rate`/`EVTA.depth` (per stress period, on the layer-0 footprint = topmost active cell per column, the MF6 default). Rate targets (`RCHA.recharge`, `EVTA.rate`) accept `rate_units` (e.g. `mm/yr`) and convert to m/d, recording the declared units. Odd values (negative ET rates, non-positive ET depth) are reported in `value_warnings`, never written silently. RCHA/EVTA packages are created on first use; NPF/IC/STO need their builder call first. This completes the file-based ingestion path — an agent names a file, never a payload of cell values.
- `import_river_from_shapefile` intersects the river network with the model grid and snaps reaches to cell faces.
- `import_obs_from_csv` matches observation sites to model cells by an explicit `cellid_col` cell-id column if provided (0-based node on DISU → written 1-based; `layer,row,col`/`layer,node` on DIS/DISV), otherwise by (x, y) coordinate if provided, otherwise sequentially. The explicit column is required where coordinates are ambiguous (DISU/DISV layers stack in x/y).
- `import_subsidence_observations` registers a **derived** time-series target under `derived_observations` in `.gwmcp_meta.json` — a measured subsidence CSV plus the recipe (`sim_source`) for the simulated series, which the calibration forward wrapper materialises as `<gwf>_subsidence.csv` before PEST++ reads it (`setup_calibration(obs_source="derived")`). `time_col` falls back to the first CSV column when the header does not name it (an unnamed date index works); `dates` are stored as ISO `YYYY-MM-DD` sorted ascending with non-finite values dropped. `match` picks how observed dates bind to simulated times — `"nearest"` (default) snaps each observed date to the closest simulated time, so a dated survey that never lands on a stress-period end still calibrates; `"exact"` keeps only coincident dates. `tolerance_days` caps the snap (None = one median output interval, 0 for a single simulated time) and `date_map` (observed → simulated) overrides the automatic match per date; `setup_calibration` reports the matched/skipped counts and the largest snap distance. It writes no MODFLOW 6 observation package because a derived series has no native MF6 observation type.

---

## model builder

Create and configure MODFLOW 6 GWF models using FloPy. All tools operate on a named workspace directory.

| Tool | Inputs | Returns |
|---|---|---|
| `create_model` | `name: str`, `workspace: str`, `units: str = "METERS"`, `time_units: str = "DAYS"` | Confirmation with workspace path |
| `adopt_model` | `name: str`, `workspace: str`, `units: str = "METERS"`, `time_units: str = "DAYS"`, `allow_modify: bool = False` | Confirmation with workspace path + adopted model names + read-only status |
| `set_simulation` | `model: str`, `nper: int`, `perlen: list[float]`, `nstp: list[int]`, `ims_complexity: "simple" \| "moderate" \| "complex"` | Confirmation |
| `set_model_crs` | `model: str`, `crs: str`, `xorigin: float \| None`, `yorigin: float \| None`, `angrot: float \| None` | Confirmation with the set CRS/offsets (7e-B11.1) |

Grids built with `add_dis_package`/`add_disv_package` have no CRS until
`set_model_crs` is called — every spatial tool needs the grid to carry a CRS
to compare coordinates, and without one they fail `CRS_UNKNOWN` rather than
guess (7e-B11.2).

**CRS persistence (2026-08-22):** the grid CRS is persisted to
`.gwmcp_meta.json` (by both `set_model_crs` and — since modeB rerun-6 —
`import_grid_from_shapefile`, including `xorigin`/`yorigin`) and re-applied to
the modelgrid on every load from disk. flopy does not store the CRS in MF6
input files, so without this a staleness reload (7f-D4.1) or a new process
would drop the CRS and the georeferenced exporters would fail CRS_UNKNOWN.
| `add_dis_package` | `model: str`, `nlay: int`, `nrow: int`, `ncol: int`, `delr: float \| list`, `delc: float \| list`, `top: float \| list`, `botm: list`, `idomain: int \| list \| None = None` | Grid summary (dimensions, cell count) |

`idomain` (7e-B9) marks active/inactive cells: `1` active, `0`/`-1` inactive. A 2-D array `(nrow, ncol)` is broadcast across layers; a 3-D array is `(nlay, nrow, ncol)`. `summarise_model` reports the active cell count as `grid.n_active` when `idomain` is present.
| `add_disv_package` | `model: str`, `nlay: int`, `vertices: list`, `cell2d: list`, `top: list`, `botm: list`, `gridprops_file: str \| None = None` | Grid summary |

Inline `vertices`/`cell2d` payloads are rejected beyond 50,000 cells
(`PAYLOAD_TOO_LARGE`, 7f-I4) — pass `gridprops_file` (a JSON file with
`vertices`/`cell2d`/`top`/`botm`) or use `import_grid_from_shapefile`
(`method='disv'`) for real Voronoi grids.
| `add_disu_package` | `model: str`, `nodes: int`, `nja: int`, `top: list`, `bot: list`, `area: list \| None = None`, `iac: list \| None = None`, `ja: list \| None = None`, `ihc: list \| None = None`, `cl12: list \| None = None`, `hwva: list \| None = None`, `angldegx: list \| None = None`, `idomain: list \| None = None`, `vertices: list \| None = None`, `cell2d: list \| None = None`, `nvert: int \| None = None`, `gridprops_file: str \| None = None` | Grid summary |

Fully unstructured (DISU) grids are defined by explicit node connectivity: `nodes`/`nja` plus `iac` (connections per node) and `ja` (connected node ids, 0-based; each node's first connection must be itself). `top`/`bot` are per-node; `area` defaults to 1.0 and `ihc`/`cl12`/`hwva` default to single-layer/unit placeholders so a connectivity-only model still runs. Optional `vertices`/`cell2d` add cell x/y geometry (needed for coordinate observations and plan-view plots). Pass `gridprops_file` (JSON) for large grids. Obs cell ids are scalar 1-based node numbers; adopter models keep working via `adopt_model`.
| `add_npf_package` | `model: str`, `icelltype: int \| list`, `k: float \| list`, `k33: float \| list \| None`, `save_flows: bool = True`, `k_units: str = "m/d"` | Confirmation |
| `add_ic_package` | `model: str`, `strt: float \| list` | Confirmation |
| `add_sto_package` | `model: str`, `iconvert: int \| list`, `ss: float \| list`, `sy: float \| list \| None`, `steady_state: list[int] \| None`, `save_flows: bool = True` | Package summary with resolved steady/transient periods |
| `add_csub_package` | `model: str`, `packagedata: list \| dict`, `ninterbeds: int \| None`, `sgm`/`sgs`/`cg_theta`/`cg_ske_cr: float \| list \| None`, `head_based: bool`, `initial_preconsolidation_head: bool`, `specified_initial_interbed_state: bool`, `update_material_properties: bool`, `ndelaycells: int \| None`, `beta`/`gammaw: float \| None`, `interbeddata: list \| None`, `stress_period_data: dict \| None`, `observations: dict \| None`, `filerecords: dict \| None`, `print_input: bool`, `save_flows: bool`, `pname: str \| None` | CSUB package summary (interbed count, delay count, layers, filerecords, obs CSV) |
| `add_boundary_package` | `model: str`, `package: str`, `stress_period_data: dict`, `kwargs: dict`, `save_flows: bool = True`, `rate_units: str \| None = None`, `pname: str \| None = None` | Package summary with cell count per stress period |

**Units (7f-H1.1):** `add_npf_package` accepts `k_units` (default "m/d";
accepted m/d, m/s, m/yr, cm/s, ft/d, ft/s) and converts `k`/`k33` into the
model's own length unit per its `time_units` on entry (so `k_units="ft/d", k=10`
stays 10 in a FEET model, while `k_units="m/d", k=10` becomes 32.808 ft/d);
`add_boundary_package` accepts `rate_units` (m/d, m/yr, mm/d, mm/yr) for
RCH/EVT/RCHA/EVTA rates, converting them into the model's length unit per its
time unit. Declared units are recorded in `.gwmcp_meta.json` and reported by
`summarise_model.units` (`{length, time, k, recharge}`). `add_csub_package`'s
`gammaw`/`beta` default to the model's unit system (METERS 9806.65 / 4.6512e-10;
FEET 62.48 / 2.227e-8) rather than FloPy's SI defaults.

**Multi-model simulations (v0.3.0, 2026-09-25):** one simulation can hold several models
(`gwf`, `gwe`, `prt`) addressed by an optional `component: str = "gwf"` argument. The shared
builder tools `set_model_crs`, `add_dis_package`, `add_disv_package`, `add_disu_package`,
`add_ic_package` and `add_oc_package` (plus `get_run_log`) accept it; the default reproduces the
single-GWF behaviour exactly. `summarise_model` reports a `components` block (per component: MF6
model name, package list, grid type) and `model_status` a `components` list. `add_oc_package`
supports only `component="gwf"` today — a coupled component's OC is added by that component's spec.
The user-facing tools for creating `gwe`/`prt` models (`add_gwe_model`, `add_prt_model`) arrive with
the GWE and PRT specs; the underlying `add_component_model` mirrors the GWF grid and registers the
`GWF6-GWE6`/`GWF6-PRT6` exchange.

**GWE heat transport (v0.3.0, 2026-09-25):** `add_gwe_model` creates a derived
heat simulation in `<workspace>/gwe/` coupled to a flow run through the Flow
Model Interface (FMI). Build its packages with `add_gwe_adv_package` /
`add_gwe_cnd_package` / `add_gwe_est_package` / `add_gwe_ssm_package` /
`add_gwe_esl_package`, add its grid and initial temperature with the shared
tools using `component="gwe"`, and its output control with
`add_oc_package(component="gwe")` (temperature_filerecord). `run_simulation`
runs the flow model first and the heat model second. Post-process with
`read_temperature`, `plot_temperature_map` and `plot_temperature_timeseries`.
The flow model is made FMI-ready automatically (`save_flows`,
`save_specific_discharge`, `save_saturation` on NPF); a GWE model requires an
SSM package whenever the flow model has boundary packages.

`stress_period_data` maps a **0-based** stress-period index to records with **0-based** cell indices (layer, row, col for DIS; layer, node for DISV); indices are converted to 1-based when written to the package file. `save_flows` (default on) writes the SAVE FLOWS option so the package's fluxes appear in the budget file for `compute_water_balance`.

**RCHA/EVTA — array-based recharge/ET (7e-B8):** `add_boundary_package(package="RCHA"|"EVTA", ...)` accepts a full-grid array per stress period instead of cell records (`{"0": <nrow×ncol array>}` for DIS layer 0, or `<ncpl>` for DISV). `rate_units` is converted on entry exactly as for RCH/EVT. The budget term is `RCH`.

**pname — several packages of one type (7e-B10):** re-adding a package with an explicit `pname` replaces only that package, so two CHD sets can coexist (`pname="chd_high"` + `pname="chd_low"`, e.g. tutorial-05). Without a `pname` every package of the type is replaced first (as before). The replacement warning names the pname.

`adopt_model` registers an **existing** MODFLOW 6 simulation on disk (a directory containing a runnable `mfsim.nam` + package files) without creating a stub or rewriting files — so `check_model`, `run_simulation`, `summarise_model`, and the calibration chain operate on the real model. The GWF model name inside the files need NOT match `name` (tools fall back to the first model in the simulation). Use it to bring a real published/regional model into the MCP toolchain instead of `create_model` + manual file copying.

**Adopted models are read-only by default (7f-D4.2):** every `save_sim`-backed builder call (`add_*`, `set_simulation`, `assign_*`, `import_*`) on an adopted model is refused with `error=True, code="MODEL_ADOPTED_READONLY"` so a real published model cannot be silently rewritten by a stray call. Pass `allow_modify=True` to opt out. Non-mutating tools (`check_model`, `run_simulation`, `summarise_model`, `read_heads`, plotting) always work.

**Cache staleness (7f-D4.1):** the in-process cache records the mtimes of `mfsim.nam` and the package files at load/save time. If any tracked file changes on disk outside the MCP, the next `get_sim` reloads from disk and the calling tool reports `reloaded_from_disk: true` (currently surfaced by `summarise_model`).

**Registry scoping (7e-B4.2):** the model registry is scoped per workspace root. Models created with an explicit `workspace` register in a `.<root>/.gwmcp_registry.json` next to that workspace; models created without one register under the default root. Re-registering the same name+path is idempotent; the same name under different roots is legal; the same name twice in one root with different paths errors.

`add_sto_package` defines aquifer storage (required for transient simulations). `steady_state` lists the **0-based** stress-period indices that are steady-state; all other periods run transient. Default `[0]` → first period steady, rest transient; `[]` → all periods transient. `sy` (specific yield) is required when any cell is convertible (`iconvert > 0`). **Without an STO package, a multi-time-step model runs as steady state** — `check_model` and `run_simulation` return a warning when they detect that configuration.

`add_csub_package` defines the CSUB (subsidence) package. `packagedata` is a list of 11-field interbed records (`[icsubno, cellid, cdelay, pcs0, thick_frac, rnb, ssv_cc, sse_cr, theta, kv, h0]`, all indices 0-based and contiguous from `icsubno=0`), `{"filename": ...}` to reference a pre-externalised file that **must already exist** (then `ninterbeds` is required), or `{"filename": ..., "data": [...]}` to externalise the records to that file (flopy writes it immediately at construction; `ninterbeds` defaults to `len(data)`). `packagedata_filename` is recorded in the result/meta only when the referenced file exists on disk. `sgm`/`sgs`/`cg_theta`/`cg_ske_cr` accept a scalar or one value per layer. `ndelaycells` is **required** when any interbed has `cdelay="delay"` — it is never defaulted silently. `observations` maps a CSV name to `[(name, obs_type, index), ...]`: cell types (`compaction`, `preconstress`, `elastic-compaction`, `inelastic-compaction`; the `-cell` suffix is optional) take a cellid, interbed types (`interbed-compaction-pct`, `delay-preconstress`, `delay-head`) take a 0-based interbed number, or for the delay types a 0-based `(interbed, delay-cell)` pair (`delay-preconstress`/`delay-head` index 0 → interbed 1, delay cell 1); the registered output CSV (`obs_output_csv`/`obs_names`) is persisted in `.gwmcp_meta.json` under the `csub` block for post-processing. `filerecords` accepts `zdisplacement`, `package_convergence`, `strainib`, `compaction`. Re-adding replaces the existing CSUB package(s) unless distinct `pname` values are used.
| `add_oc_package` | `model: str`, `head_filerecord: str \| None`, `budget_filerecord: str \| None`, `saverecord: list`, `printrecord: list \| None` | Confirmation |
| `summarise_model` | `model: str` | Structured summary: packages, grid dimensions (+ `n_active` when idomain present), stress periods, boundary types, storage (STO steady/transient periods), registered `observations` count, `components` (per-component model name/packages/grid type), `reloaded_from_disk` flag |
| `model_status` | `model: str` | `{ runnable: bool, missing_required: list[str], missing_recommended: list[str], next_steps: list[str], warnings: list[str], components: list[str] }` — ordered build-order status (7e-C8) |
| `list_model_files` | `model: str` | File list with sizes and types; flushes staged changes first and reports `flushed` |
| `flush_model` | `model: str` | `{ written: bool }` — forces the pending deferred write so the on-disk input set matches the in-memory state |
| `list_models` | *(none)* | `{ models: {name: workspace_path} }` — every registered model (7e-B4.1) |
| `delete_model` | `model: str`, `remove_files: bool = False` | `{ model, removed: true, remove_files }` — unregisters a model; `remove_files` also deletes its workspace directory (7e-B4.1) |

### Deferred writes (7f-E1.2)

Builder and parameterisation calls (`add_*`, `set_simulation`, `assign_*`,
`import_*`, `create_model`) mutate the in-memory model and **defer the disk
write**: their results report `written: false`. The write happens at the next
flush point — `flush_model`, `check_model`, `run_simulation`,
`list_model_files`, or the calibration handoff (`setup_pest_control`,
`run_pestpp_glm`, `run_pestpp_ies`) — which report `flushed: true` when a
write occurred. This removes the quadratic write volume of a regional build
(every call no longer re-serialises every array). `flush_model` is a no-op
(`written: false`) for clean models and for adopted read-only models.

### model_status and next_steps (7e-C8)

Ordering constraints (`add_sto_package` needs `set_simulation` first;
`assign_k_from_zones`/`assign_k_from_raster` need `add_npf_package` first;
`assign_ic_from_raster` needs `add_ic_package` first; `import_grid_from_shapefile`
documents a `set_simulation` prerequisite) used to surface only as the *next*
call's error. `model_status(model)` reports the whole build order up front —
`runnable` is `True` once the grid (DIS/DISV), simulation (TDIS+IMS), NPF, IC,
OC, and — when TDIS looks transient — STO all exist; `missing_required`/
`missing_recommended` name the gaps (a boundary condition package is
recommended, not required: MF6 runs without one, it just won't do anything);
`next_steps` gives the exact next tool call for each gap, in build order.

Every **builder and parameterise** tool's result also carries the same
`next_steps` list (computed from the model's state after the call), so the
gap is visible immediately rather than only via `model_status` or the next
call's error. It's omitted from error responses and any result with no
`model` key. This does not apply to runner/postprocess/calibration/docs
tools — only the tools that build the model.

### Supported boundary packages for `add_boundary_package`

`CHD` (constant head), `WEL` (well), `RIV` (river), `DRN` (drain), `RCH` (recharge, list-based), `RCHA` (recharge, array-based), `EVT` (evapotranspiration, list-based), `EVTA` (evapotranspiration, array-based), `GHB` (general head boundary), `SFR` (streamflow routing)

---

## runner

Execute MODFLOW 6 and retrieve run results.

| Tool | Inputs | Returns |
|---|---|---|
| `check_model` | `model: str` | List of warnings and errors from FloPy model checker; flushes staged changes first (`flushed`) |
| `run_simulation` | `model: str`, `silent: bool = False`, `auto_fix: bool = False` | `{ success: bool, elapsed_s: float, convergence: str, listing_summary: str, flushed: bool, observation_fit: dict \| null, auto_fix_applied: list \| null }` |
| `diagnose_convergence` | `model: str` | `{ converged: bool, failure_class: str, recommendations: list[str], evidence: dict, progress: dict }` |
| `validate_model` | `model: str` | `{ findings: list[dict], clean: bool, flushed: bool }` — physical-plausibility findings, aggregated with a count per defect type |

`auto_fix=True` (7f-H2) retries a non-converged run through a bounded
escalation ladder of solver settings (IMS complexity moderate→complex, more
outer iterations, relaxation factor, linear acceleration) and reports the
exact changes in `auto_fix_applied: [{rung, changes: [{setting, from, to}]}]`;
the model files reflect the final successful configuration. Adopted read-only
models cannot be auto-fixed in place (clone them first).
| `start_run` | `model: str` | `{ model, job_id, kind: "mf6", status: "running" }` — starts MODFLOW 6 in a background thread and returns a job id immediately (7e-A3) |
| `get_job_status` | `job_id: str` | `{ job_id, model, kind, status, elapsed_s, progress \| null, result \| null, error \| null }` |
| `cancel_job` | `job_id: str` | `{ job_id, status: "cancelled" }` (or the job's terminal status if already finished) |
| `get_run_log` | `model: str`, `tail: int = 100`, `component: str = "gwf"` | Last N lines of the MODFLOW listing file (.lst); a non-gwf component prefers its own `<model>.lst`, else mfsim.lst |

### diagnose_convergence (7e-C1)

MF6's own listing file rarely states *why* a run failed to converge — it just
stops short of "Normal termination". `diagnose_convergence` reads the `.lst`
to confirm non-convergence, then inspects the model configuration itself
(deterministic and inspectable even when the iteration tables are not) for
the root cause, checked in this order:

1. **`closure_too_tight`** — IMS `outer_dvclose`/`inner_dvclose` set tighter
   than `1e-9`, unresolvable at double precision for realistic head scales.
2. **`disconnected_active_domain`** — the DIS grid's `idomain` splits the
   active domain into more than one face-connected region (DISV/DISU grids
   are not checked here).
3. **`newton_needed`** / **`dry_cells`** — convertible cells (`icelltype !=
   0`) start at or below their bottom elevation; `newton_needed` when the
   Newton-Raphson formulation is off (the classic fix), `dry_cells` when it's
   already on and cells are still critically dry.
4. **`k_contrast`** — NPF `k`/`k33` spans more than 4 orders of magnitude
   across active cells.
5. **`unclassified`** — none of the above; recommends `get_run_log` /
   `run_simulation(auto_fix=True)`.

`converged: true, failure_class: "converged"` is returned when the listing
file shows normal termination. Each result includes `recommendations`
(actionable text), `evidence` (the specific values that triggered the
classification), and `progress` (the same stress-period/time-step progress
`get_job_status` reports).

### validate_model (7e-C2)

Physical-plausibility checks the FloPy checker doesn't aggregate — each
defect type collapses into **one finding with a count**, not one entry per
cell. On a real regional model (zenodo-21381071), boundary cells sitting on
inactive cells alone produced 569,796 individual FloPy-checker warnings; here
that becomes a single `boundary_in_inactive_cell` finding.

| Finding type | Severity | Trigger |
|---|---|---|
| `disconnected_active_cells` | error | idomain splits the DIS active domain into more than one face-connected region |
| `k_contrast` | warning | NPF `k`/`k33` spans more than 6 orders of magnitude across active cells |
| `head_below_bottom` | error | a cell's head (simulated if the model has run, else IC `strt`) is below its own bottom elevation — physically impossible regardless of `icelltype` |
| `head_above_top` | warning | a convertible (`icelltype != 0`) cell's head is above the layer top |
| `boundary_in_inactive_cell` | warning | a list-based boundary package (CHD/WEL/RIV/DRN/RCH/EVT/GHB — not RCHA/EVTA/SFR) has a stress-period cell on an idomain<=0 cell; aggregated per package in `by_package` |

Returns `{ model, findings: list[dict], clean: bool, flushed: bool }` —
`clean=True` and `findings=[]` when none of the checks fire. Each finding has
`type`, `severity`, `message`, `count`, and type-specific detail fields
(`k_ratio`/`k_min`/`k_max`, `heads_source`, `by_package`). DISV/DISU grids
skip `disconnected_active_cells` (idomain connectivity assumes a DIS row/col
grid); the head checks work on DISV too since `top`/`botm`/`strt` shapes
generalise.

### Job control (7e-A3)

Long-running work — MODFLOW 6 runs and PEST++ calibration — executes in a
background worker thread so the MCP call returns a `job_id` immediately
instead of blocking until the client timeout (the zenodo run 1 needed a
94-minute blocking call and was bypassed for exactly this reason). Status
transitions: `running` → `succeeded` | `failed` | `cancelled`.

- `start_run(model)` starts the MF6 simulation. While the job runs,
  `get_job_status` reports live progress parsed from the `.lst` listing file:
  stress period / time step counts, `percent_complete` (monotonically
  non-decreasing), and `terminated`. When finished, the job's `result` has the
  same shape as `run_simulation` (success, convergence, elapsed_s,
  listing_summary, observation_fit).
- `start_calibration(model, pst_file, method, num_reals, num_workers)` (calibration
  module) starts pestpp-glm (`method="glm"`, default), pestpp-ies (`method="ies"`) or
  pestpp-da (`method="da"`) the same way. While running, progress reports
  `engine`, `iteration` and `latest_phi` parsed from `<case>.iobj` (GLM) or
  `<case>.phi.actual.csv` (IES), or the per-cycle post-update `cycle` /
  `latest_phi` / `n_cycles` from `<case>.global.phi.actual.csv` (DA). The
  finished result matches `run_pestpp_glm` / `run_pestpp_ies` / `run_pestpp_da`
  (for DA, `num_reals` maps to `da_num_reals`; when `num_reals` is omitted the
  PST's own `ies_num_reals` / `da_num_reals` is preserved, so a
  `setup_da_control` PST is not silently resized). `num_workers` is accepted for
  parity with `run_pestpp_*` but is **advisory** — PEST++ has no local
  worker-count option, so it is echoed back rather than applied (parallel
  forward runs need PANTHER agents or an external run manager).
- `cancel_job(job_id)` terminates the underlying process **and its entire
  process tree** (`taskkill /T /F` on Windows, `killpg` on POSIX) — the
  PEST++ forward chain spawns `mf6.exe` grandchildren that would otherwise
  survive as orphans, spinning and file-locking the workspace — and reports
  `"cancelled"`. An unknown `job_id` returns the `JOB_NOT_FOUND` envelope.
  Jobs are spawned in their own process group/session so the tree is killable.
  A calibration job's cancellation then restores the externalised inputs
  (`<gwf>_k.dat`, `<gwf>_k33.dat`, `<gwf>.csub_<keyword>.dat` and
  `<gwf>.csub_packagedata.dat`) from their base snapshots, so a killed forward
  run cannot leave the model unloadable (`Unable to open file
  ...csub_cg_theta.dat`, 6d Target 9 rerun-1).

---

## post-processing

Read binary output files and compute derived quantities.

| Tool | Inputs | Returns |
|---|---|---|
| `read_heads` | `model: str`, `kstpkper: tuple[int,int] \| None`, `layer: int = 0`, `include_values: bool = False`, `max_cells: int = 10000`, `row_slice: list[int] \| None`, `col_slice: list[int] \| None`, `decimate: int \| None` | Statistics + `output_file` (`.npy`) — values only under `include_values` within `max_cells`, else `PAYLOAD_TOO_LARGE` (7e-A1) |

`read_heads` no longer returns the full array by default (a regional layer was
~38 MB of JSON). Default returns min/max/mean/`n_active` plus `output_file`, a
`<model>_heads_l<layer>_k<kstpkper>.npy` in the workspace you can load
directly. `include_values=True` returns raw values when the cell count is
within `max_cells`; `row_slice`/`col_slice` (`[start, stop]`) and `decimate`
subset the array first.

Layer indices are validated against the model's `nlay` (7f-D3): `layer < 0` or `layer >= nlay` returns `error=True, code="INVALID_INPUT"` naming the valid range instead of silently returning the bottom layer or a raw `IndexError`. Applies to `read_heads`, `compute_drawdown`, and `plot_heads_map` (`plot_cross_section` takes no layer argument).

**Output-file selection (7e-B13):** `read_heads`, `read_budget`, `compute_drawdown`, `compute_water_balance` and the plot tools read the head/budget file the OC package declares (`head_filerecord`/`budget_filerecord`) when it exists on disk. With several undeclared `.hds`/`.cbb` files a `warning` field names the candidates.
| `read_budget` | `model: str`, `text: str \| None`, `kstpkper: tuple[int,int] \| None`, `max_records: int = 1000` | Per-record-type aggregates + `record_count`; `records` capped at `max_records` with the full table to CSV on overflow (7e-A1) |
| `compute_drawdown` | `model: str`, `kstpkper_initial: tuple`, `kstpkper_final: tuple`, `layer: int = 0`, `include_values: bool = False`, `max_cells: int = 10000` | Statistics + `output_file` (`.npy`); values under `include_values` within `max_cells` (7e-A1) |
| `compute_water_balance` | `model: str`, `kstpkper: tuple \| None` | Inflow/outflow table by boundary type, net balance |
| `diagnose_water_balance` | `model: str`, `kstpkper: tuple \| None`, `tolerance_pct: float = 1.0`, `dominance_threshold: float = 0.5` | `{ percent_discrepancy, balanced, dominant_inflow_term, dominant_outflow_term, dominant_term, dominant_term_share, boundary_dominated, ... }` |
| `read_simulated_observations` | `model: str` | Per-site simulated values from the model's obs CSV at the final output time (7f-F1.2) |
| `compare_to_observed` | `model: str`, `output_file: str \| None` | RMSE, bias, R², MAE, per-site residual table (CSV) and a scatter plot — no PEST setup needed (7f-F1.3) |
| `read_compaction` | `model: str`, `max_rows: int = 500` | Per-layer compaction + derived cumulative `subsidence` (sum of the layer compaction columns), `interbed_strain` from `<gwf>.strainib.csv`; full table written to `<model>_compaction.csv` |
| `plot_subsidence` | `model: str`, `observed_csv: str \| None`, `output_file: str \| None` | The PNG returned natively (ImageContent) + `{ model, output_file, n_times, has_observed, observed_csv, observed_axis }` — cumulative subsidence vs model time, with an optional observed overlay placed on the same axis (`observed_axis` = `"model-time"`/`"row-index"`) |
| `plot_heads_map` | `model: str`, `layer: int = 0`, `kstpkper: tuple \| None`, `contour_intervals: int = 10`, `output_file: str \| None` | The PNG returned natively (ImageContent) + the saved file path |
| `plot_cross_section` | `model: str`, `line: dict`, `kstpkper: tuple \| None`, `output_file: str \| None` | The PNG returned natively (ImageContent) + the saved file path |

`plot_heads_map` / `plot_cross_section` / `plot_subsidence` return the PNG natively
as an MCP image content block together with the saved file path (7f-I1) — the
separate `view_image` round-trip has been removed.

### GIS/table export tools (7e-C5)

| Tool | Inputs | Returns |
|---|---|---|
| `export_heads_to_raster` | `model: str`, `layer: int = 0`, `kstpkper: tuple \| None`, `output_file: str \| None` | `{ output_file, layer, kstpkper, crs }` — a georeferenced GeoTIFF |
| `export_boundaries_to_shapefile` | `model: str`, `output_file: str \| None` | `{ output_file, feature_count, packages, crs }` — one feature per (package, stress period, cell) |
| `export_water_balance_csv` | `model: str`, `kstpkper: tuple \| None`, `output_file: str \| None` | `{ output_file, row_count }` — one row per boundary type + a TOTAL row |

The deliverable for a working hydrogeologist is a GeoTIFF and a table, not a
base64 PNG or a raw MCP response — there was previously no path from a
finished model back to GIS. All three require a **structured DIS grid**
(DISV/DISU are not supported) with a **CRS set** (`set_model_crs`); a missing
CRS fails `CRS_UNKNOWN` rather than writing an unreferenced file.

`export_heads_to_raster` delegates the actual georeferencing (affine
transform, rotation, CRS) to flopy's own `export_array` — MF6's
inactive/dry sentinel values (`abs(head) >= 1e20`) become the GeoTIFF's
nodata. `export_boundaries_to_shapefile` covers list-based boundary packages
(CHD/WEL/RIV/DRN/RCH/EVT/GHB) with each record's own fields (head, rate,
stage, cond, ...) as attributes; RCHA/EVTA (array-based, apply everywhere)
and SFR (reach-indexed, no `cellid`) are not included, and a model with no
list-based boundaries fails `INVALID_INPUT`. `export_water_balance_csv`
writes `compute_water_balance`'s own inflow/outflow/net numbers to a CSV —
no new computation, just a table instead of a dict.

A relative `output_file` resolves against the model's workspace directory
(not the server process's working directory) for all three.

### diagnose_water_balance (7e-C3)

Answers "is this water balance actually OK?" instead of leaving the modeller
to eyeball `compute_water_balance`'s inflow/outflow table. `percent_discrepancy`
is the same statistic MODFLOW itself reports (`100 * (IN - OUT) / ((IN +
OUT) / 2)`); `balanced` is `abs(percent_discrepancy) < tolerance_pct` (default
1%). `dominant_inflow_term`/`dominant_outflow_term` name the single largest
boundary-type contributor on each side; `dominant_term`/`dominant_term_share`/
`boundary_dominated` look across both sides together and flag when one
boundary type carries more than `dominance_threshold` (default 50%) of all
flow through the model — a common sign the balance is only closing because
that boundary (often CHD) is absorbing everything. Zero flow everywhere is
reported as trivially `balanced=True`, `percent_discrepancy=0.0`, not a
division-by-zero error.

### Closed observation loop (7f-F)

Observations enter the model via `import_obs_from_csv` and are now read back:
- `read_simulated_observations` returns the values the model actually produced
  at the registered sites (from `<model>_<type>.obs.csv`, at the final output
  time).
- `compare_to_observed` answers "how good is this model?" in one call: RMSE,
  bias, R², MAE, a per-site residual table (capped at 500 rows; full table to
  `<model>_obs_residuals.csv`) and an observed-vs-simulated scatter plot — with
  **no PEST setup at all**.
- `run_simulation` reports `observation_fit` (n, rmse, bias, worst 5 sites)
  on every run when targets are registered (`null` otherwise).

Each site's observed value is the mean of its registered records; the simulated
value is the obs-CSV value at the final output time — steady-state appropriate.
For transient models this compares mean observations against the final-state
simulation (documented limitation).

**Obs-name matching is case-insensitive (2026-08-22):** MODFLOW uppercases
observation names in the continuous obs CSV (`W1..W29`), while
`import_obs_from_csv` registers the caller's case. `read_simulated_observations`,
`compare_to_observed` and `run_simulation.observation_fit` match the registered
site names against the obs-CSV columns case-insensitively (exact match
preferred), so a lowercase-imported CSV works without re-importing.

### CSUB subsidence (`read_compaction`, `plot_subsidence`)

`read_compaction` turns MF6's CSUB observation output into per-layer compaction
and a derived cumulative subsidence series. It reads `<gwf>.csub.obs.csv`
(declared as `meta["csub"]["obs_output_csv"]`, else found by glob), matches the
layer `compaction` columns case-insensitively — MF6 upper-cases registered
observation names, e.g. `COMPACTION.01` — and sums them per time into
`subsidence`. The `ELASTIC-COMPACTION`, `INELASTIC-COMPACTION`, `PRECONSTRESS`
and `INTERBED-COMPACTION-PCT` columns are deliberately excluded from the sum.
`interbed_strain` is read from `<gwf>.strainib.csv` when present. `max_rows`
(default 500) caps the inline `times`/`compaction`/`subsidence` lists; the full
table is always written to `<model>_compaction.csv`. With no CSUB obs CSV the
tool returns `OUTPUT_FILE_MISSING`, and a CSV without any layer compaction
columns returns `INVALID_INPUT`.

`plot_subsidence` consumes that series and plots cumulative subsidence against
time, returning the PNG natively. Pass `observed_csv` (a two-column
`time,subsidence` CSV) to overlay a measured series: the value column is
`Subsidence_ft` case-insensitively when present, else the first numeric
non-time column, and the time column is `time`/`datetime`/`date` (else the first
column, which catches an unnamed date index). The observed series is placed on
the **model time axis** — a numeric time column is elapsed model time, and
calendar dates are converted to elapsed time via the model's `start_date_time`
and `time_units` — so the overlay lines up with the simulated curve instead of
collapsing to `x = 0..N-1`; the result reports `observed_axis`
(`"model-time"` or `"row-index"`). A missing
observed file returns `OUTPUT_FILE_MISSING`; when no numeric value column can
be identified it returns `INVALID_INPUT`. `read_compaction`'s error envelope is
propagated unchanged.

---

## calibration

Set up and run PEST++ parameter estimation via pyEMU.

| Tool | Inputs | Returns |
|---|---|---|
| `setup_calibration` | `model: str`, `parameterisation: dict`, `obs_source: str = "model"`, `noptmax: int = 10` | The generated PEST interface: `.pst`, template, instruction file, external array, forward wrapper, parameter table |
| `setup_da_control` | `model: str`, `parameterisation: dict`, `cycles: list[int]`, `obs_cycles: dict`, `obs_weights: dict \| None = None`, `par_cycles: dict \| None = None`, `num_reals: int = 50`, `noptmax: int = 1`, `use_simulated_states: bool = True`, `da_options: dict \| None = None`, `prior_ensemble: dict \| None = None`, `prior_std: float \| None = None`, `state_head_bound: float \| None = None` | The generated DA-ready v2 PEST interface: `.pst`, K template/target, IC template, cycle tables, state-parameter count, `state_bounds` (per-site bound used), model command, prior ensemble file and `prior_ensemble_n_clipped` when a prior is requested |
| `setup_pest_control` | `model: str`, `obs_data: dict`, `par_data: dict`, `template_files: list`, `instruction_files: list`, `pestpp_options: dict \| None`, `obs_source: "explicit" \| "model" = "explicit"` | Path to generated `.pst` control file |
| `start_calibration` | `model: str`, `pst_file: str`, `method: "glm" \| "ies" \| "da" = "glm"`, `num_reals: int \| None = None`, `num_workers: int = 1` | `{ model, job_id, kind, pst_file, status: "running", num_workers, parallelism }` — starts PEST++ in a background thread with live phi progress (7e-A3). For `method="da"`, progress is the per-cycle post-update phi from `<case>.global.phi.actual.csv` and `num_reals` maps to `da_num_reals`; when `num_reals` is omitted the PST's own option is preserved for IES/DA. `num_workers` is advisory (echoed, not applied — PEST++ has no local worker-count option) |

### Automated calibration setup — `setup_calibration` (7e-A2)

`setup_calibration` emits the **whole** PEST interface in one call with zero
hand-written files. `parameterisation` maps a parameter name (≤ 12 chars, PEST
cap) to a spec dict:

```json
{
  "k": {"target": "npf:k", "scope": "all", "initial": 5.0}
}
```

- `target`: the model array/property to parameterise. Supported: `"npf:k"`
  (default), `"npf:k33"`, and the CSUB targets `"csub:packagedata"`,
  `"csub:cg_theta"` and `"csub:cg_ske_cr"`. A CSUB target on a model with no
  CSUB package returns `INVALID_INPUT` (`"No CSUB package found; run
  add_csub_package before parameterising csub:…"`); see the CSUB calibration note
  below.
- `scope`: `"all"` (whole array), `"layer"` (with `"layer": N`), `"cells"`
  (with `"cells": [[layer, row, col], ...]` on DIS — `[[layer, node], ...]`
  on DISV or `[[node], ...]` / a scalar node on DISU; these `cells` node ids are
  **0-based**, unlike observation cell ids which are 1-based on DISU), or
  `"zones"` (with `"layer": N`). Scopes must partition the array
  exactly for all/layer/cells; `zones` is the multiplier mode below.
  `setup_da_control` additionally accepts `"multiplier"` (see the DA section):
  a **single** dimensionless factor over the whole existing K array. It cannot
  be combined with `all`/`layer`/`cells`, and is deliberately not accepted by
  `setup_calibration` (its `"all"` scope is an absolute replacement, not a
  multiplier).
- `initial` (required, > 0) sets the base value; `lower_factor` /
  `upper_factor` (defaults `0.1`/`10.0`) set the bounds as
  `initial × factor`; `partrans` defaults to `"log"`.

**Zoned multipliers (scope="zones"):** zones are auto-derived from groups of
equal positive `npf:k` values within the spec's layer (values equal to 6
significant figures group together; inactive/zero cells stay fixed). Each zone
becomes a dimensionless multiplier parameter `<prefix>_z<index>` (names ordered
by layer then base K ascending, ≤12 chars). `initial` defaults to `1.0` (base
field), bounds default 0.1–10. One spec per layer; `zones` specs cannot be
mixed with `all`/`layer`/`cells`. `max_zones` (default 50) fails loudly when a
layer has more distinct values than the cap. The call writes
`<gwf>_k_base.dat`, `<gwf>_k_zone.dat`, `<gwf>_k_mult.dat.tpl` and forces a
forward wrapper that computes `k = base_k × multiplier[zone]` before each
MODFLOW 6 run — so the base spatial pattern is preserved and only the zone
magnitudes are calibrated. `check_parameter_sensitivity` re-applies the
multipliers before its direct runs. The result adds a `zones` block (name,
layer, base_k, n_cells, bounds) and `grid`.

**Single-factor K multiplier (scope="multiplier", `setup_da_control` only):**
one dimensionless parameter multiplies the **whole existing** `npf:k` array
(`k = base_k × factor`), so the base spatial pattern is preserved and the K
template holds **one** token regardless of grid size (the 31,522-token
per-cell template is why `setup_da_control` was reported to exceed the client
timeout on a heterogeneous DISU model, and the uniform replacement of
`scope="all"` collapsed K and aborted a `pestpp-da` run). Reuses the zoned
machinery with a single all-cells zone (zone id 1): it writes
`<gwf>_k_base.dat`, `<gwf>_k_zone.dat` (all ones), `<gwf>_k_mult.dat.tpl`
(one token), rewires NPF `k` to `<gwf>_k.dat`, and **always** emits the
forward wrapper that computes `k = base_k × factor` before each run. `initial`
defaults to `1.0` (the shipped base field), `lower_factor`/`upper_factor`
default to 0.1/10.0, and `partrans` defaults to `"log"`. Exactly one parameter
is allowed; it cannot be mixed with `all`/`layer`/`cells`.

```json
{"k_mult": {"target": "npf:k", "scope": "multiplier", "initial": 1.0,
            "lower_factor": 0.2, "upper_factor": 5.0, "partrans": "log"}}
```

Measured on synthetic large models (32,000 cells / 32,000 DISU nodes): the K
template goes from 32,000 tokens (593.8 kB) to **1** token (~20 B), and the
array-parameterisation + template + substitution phase from 92 ms to 3 ms.
Whole-setup wall time is ~0.6 s (DIS) / ~1.3 s (DISU) for both scopes on those
fixtures — the flopy flush dominates and is common to both; the real
31,831-node holdout's documented whole-setup ≈22–24 s (Task 9) is likewise
flush-dominated, so the multiplier scope stays comfortably inside the ~90 s
client timeout.

The call then: (1) rewires NPF `k` to an external `OPEN/CLOSE <file>` array
(so a template can target it — the model runs identically afterwards); (2)
generates a template with wide fixed-width tokens (≥ 15 chars — the `@k@`
truncation bug is structurally impossible); (3) generates the instruction
file from the model's OBS CSV header (`obs_source="model"`, reading the
targets registered by `import_obs_from_csv`); (4) writes a Python forward-run
wrapper at a space-free path when the default MF6 command would be unsafe on
Windows (the **MF6 binary path** contains spaces — see the Windows model
command note below); and (5) assembles
the `.pst` with safe numeric defaults — `derinclb > 0` on every parameter
group (a zero `derinclb` produces a zero Jacobian) and default bounds
base/10–base×10.

Run the calibration afterwards with `run_pestpp_glm` / `run_pestpp_ies` (or
`calibrate`), then `summarise_calibration`.

**GLM phi progress (7e-B1):** pestpp-glm writes its objective-function
history to `<case>.iobj` — not the `.phi.actual.csv` that pestpp-ies writes.
`run_pestpp_glm` and `summarise_calibration` now branch on the engine, so GLM
runs report real `iterations` / `phi_progress` (the old reader always returned
empty for GLM).

`obs_source="model"` (7f-F1.5) builds the observation interface from the
targets registered by `import_obs_from_csv`: an instruction file is generated
that reads the model's obs CSV (first output row — the single row for the
steady-state models this targets) and each site's observed value is the mean
of its registered records. With `obs_source="model"` you still supply
`par_data` and `template_files` but may omit `instruction_files` and
`obs_data`.

**CSUB calibration (v0.3.0, 2026-09-19):** `setup_calibration` parameterises
CSUB through a target resolver alongside `npf:k` / `npf:k33`:
`csub:packagedata` (scope `"columns"`, optionally restricted by `layers`
(0-based layer list) / `interbeds` (0-based interbed list) — the interbed table is
externalised and a wide-token template is written over the selected numeric
columns; bounds default to value × 0.05 / × 20,
with `partrans` `none` for `rnb`/`thick_frac` and `log` where positive-only),
`csub:cg_theta` and `csub:cg_ske_cr` (scope `"layer"`, per-layer external arrays,
one template per layer). Multi-target specs (e.g. `csub:packagedata` +
`csub:cg_ske_cr` + `npf:k33`) assemble into one `.pst` with `derinclb > 0` on
every group. The observation interface for CSUB is `obs_source="derived"`:
`import_subsidence_observations` registers a measured subsidence CSV with the
recipe for the simulated series, and the calibration forward wrapper materialises
`<gwf>_subsidence.csv` before PEST++ reads it (CSUB compaction has no native MF6
observation time series the head-OBS reader can consume). A CSUB target on a
model with no CSUB package returns `INVALID_INPUT` (`"No CSUB package found; run
add_csub_package before parameterising csub:…"`) — not `PACKAGE_MISSING`, which
belongs to the parameterise tools.

`obs_data` keys must match the instruction-file tokens exactly (case-insensitive); unmatched names raise an error rather than being silently dropped. Special `pestpp_options` keys: `model_command_line` (str) / `model_command` (str\|list) sets the forward-model command (Windows default: the located MF6 binary); `output_files` (list, parallel to `instruction_files`) sets explicit model output filenames; `input_files` (list, parallel to `template_files`) sets explicit model input filenames (override the `.tpl`-stripped target — e.g. `hk.dat.tpl` → `hk.dat`, matching what the NPF `OPEN/CLOSE` reads); `noptmax` is native PEST control data.

**Instruction files:** classic PEST tokens (`!name!`) or pyemu pif/jif. For pif, the header must be `pif @` and each line uses fixed-width reader syntax — e.g. `l1 !dum! !o0001!` (skip the first token, read `o0001`). The `[l1]…@o0001@` PEST style is **not** accepted by pyemu's pif parser.

**Canonical pif example** (matches what pyemu's own instruction writer emits — see `pyemu/utils/pst_from.py:_write_observation_instruction`). For an output file with one observation value per line, prepended with a dummy column, the instruction file is:

```
pif ~
l1 !dum! !o0001!
l1 !dum! !o0002!
```

Each `l1` reads one line of the model output; `!dum!` reads-and-discards a token (skips the dummy column), `w` reads-and-discards a word, `!name!` reads the value into observation `name`. The header marker (`~` or `@`) is arbitrary. Keep one instruction line per line of the model output file. **CSV output files:** use `!dum!` (not `w`) to discard skipped columns — pestpp rejects `w` on comma-delimited lines ("EOL encountered while executing whitespace instruction"), e.g. `l1 !dum! !name! !dum! !name! …` for a header + comma-separated values row.

**Templates:** must start with `ptf`/`jtf`. Parameter tokens must be **wide fixed-width** (`@          k          @`) — narrow tokens truncate substituted values to `1.0` and zero out the Jacobian.

**Windows model command:** must be a direct executable or a space-free Python wrapper. pestpp cannot run `.bat`/`.cmd` wrappers (it hangs normalising `cmd /c`) nor executables whose path contains spaces; `setup_pest_control` warns when it detects either.

**A space in the *workspace* path does not need a wrapper (Task 9):** pestpp runs the model command with the model workspace as its working directory, so the workspace path never enters the command line. `setup_calibration` / `setup_da_control` therefore emit the direct `mf6.exe` command whenever the MF6 binary path itself is space-free, even when the workspace path contains spaces (e.g. `...\MODFLOW 6\sim`) — proven end-to-end for both `start_calibration(method="da")` and `run_pestpp_da`, and it removes two process launches (the venv launcher plus the interpreter) per realisation. A wrapper is generated when the MF6 **binary** path contains a space, and **always** for the K-multiplier paths (`scope="zones"` and the DA-only `scope="multiplier"`) which must compute `k = base × mult` before each run. Every wrapper is **stdlib-only** (no `numpy`) and its command uses a space-free interpreter, so the command line itself never contains a space — including when the workspace contains a space and the wrapper therefore lives in the temp directory. Because both wrapper flavours are stdlib-only, the space-free *base* interpreter (which has no site-packages) can run them; this is what fixed 6d rerun-6, where a `numpy`-importing multiplier wrapper forced this venv's space-containing `python.exe` (`D:\Claude Projects\...\.venv\Scripts\python.exe`) into the command and deadlocked `pestpp-da` at 100 % CPU before `mf6.exe` ever started (4/4 attempts).
| `run_pestpp_glm` | `model: str`, `pst_file: str`, `num_workers: int = 1` | `{ converged: bool, final_phi: float, iterations: int }` |
| `run_pestpp_ies` | `model: str`, `pst_file: str`, `num_reals: int = 50`, `num_workers: int = 1` | `{ final_phi_mean: float, final_phi_std: float, iterations: int }` |
| `run_pestpp_da` | `model: str`, `pst_file: str`, `num_reals: int \| None = None`, `num_workers: int = 1`, `da_options: dict \| None = None`, `noptmax: int \| None = None` | `{ converged: bool, final_phi_mean: float, final_phi_std: float, cycles: int, num_reals: int, noptmax: int }` |

`run_pestpp_da` runs the PESTPP-DA binary against a **DA-ready `.pst`** — build one with `setup_da_control` (its cycle tables and `da_*` options are exactly what the binary expects). `num_reals` is the DA **ensemble size**, written to the `da_num_reals` `++` option; when omitted the PST's own `da_num_reals` is preserved (a `setup_da_control(num_reals=N)` PST stays at N). The PEST control `noptmax` is the number of update **iterations per assimilation cycle**, not the ensemble size — the optional `noptmax` overrides it and, when omitted, the PST's own value is preserved. Pass cycle options such as `{"da_observation_cycle_table": "obs_cycle_tbl.csv", "da_parameter_cycle_table": "par_cycle_tbl.csv"}` (or a `.pst` that already carries `da_*` options). PEST++-DA recognises `da_observation_cycle_table`, `da_parameter_cycle_table`, `da_weight_cycle_table`, `da_parameter_ensemble`, `da_hotstart_cycle`, `da_stop_cycle`, `da_use_simulated_states` and `da_noptmax_schedule`; there is **no** `da_cycle` / `da_obs_cycle_table` / `da_ensemble`, and an unrecognised `++` arg is a fatal parse error.

`num_workers` on `run_pestpp_glm` / `run_pestpp_ies` / `run_pestpp_da` / `start_calibration` is **advisory**: PEST++ 5.x has no local worker-count option (parallel forward runs require a PANTHER manager/agent or an external run manager), so a value > 1 neither parallelises the run nor is written to the PST — it is echoed in the result (`num_workers`, `parallelism`) so callers are not misled. Ensemble size (`num_reals`) is what actually sets the IES/DA workload.

**Forward-wrapper MF6 stdio (2026-09-20, commit `f1e7015`):** the generated wrapper runs MF6 with `stdin`/`stdout`/`stderr = subprocess.DEVNULL`. PEST++ launches the model command with FIFO pipes and does not continuously drain them, while MF6 writes its console listing to stdout — for the 158-period 6d H201 model that listing is ~657 KB against a 64 KB Windows pipe buffer, so inheriting those pipes deadlocked the forward run at `mf6_start` once the buffer filled. MF6 already writes its full listing to `<gwf>.lst`, so the console streams are discarded. This removed a deterministic deadlock (reproduced by running the wrapper with an undrained stdout pipe: hung at 25 s before, completes in <1 s after).

**Known caveat (open, context-dependent):** a PEST++ calibration can still stall *under some conditions*. It has only been observed while a **background** `start_calibration` job runs inside the MCP server and the client polls it — two attempts launched ~2 forward runs then idled (~35–100 s launch gaps, once ~16 min idle) while the **synchronous** `run_pestpp_ies` on the identical `.pst`, in the same MCP tree, completed 389 forward runs in 2.73 min (0.42 s/run). It is **not reproducible in isolation**: the same `start_calibration` background job run from a plain script completes 364 runs in 90 s (0.25 s/run) with live progress, and the wrapper executes `mf6` in ~0.2 s in every case. So the background job runner and the forward wrapper are individually sound; the trigger is not yet root-caused (the earlier "VS Code process tree / job object" theory and a plain "background runner is broken" theory are both contradicted by evidence). Reliable path today: the synchronous runner (`run_pestpp_ies` / `run_pestpp_glm`), which may exceed the MCP client timeout (`-32001`) but completes server-side. See `tasks.md` 6d Target 9 rerun-6/rerun-7 findings.

| `summarise_calibration` | `model: str`, `pst_file: str`, `measurement_error: float \| None = None`, `max_residuals: int = 500` | Phi progress table, parameter estimates vs priors, residual statistics (RMSE, bias, R²; `residuals` capped at `max_residuals`, full table to CSV), an `engine` field, and a `verdict` |
| `summarise_da` | `model: str`, `pst_file: str`, `max_residuals: int = 500` | Per-cycle phi table (post-update ensemble mean from `<case>.global.phi.actual.csv`), final-cycle phi mean/std, posterior parameter statistics (`mean`/`std`/`min`/`max` from the **current run's** final `<case>.global.<cycle>.pe.csv`, excluding the `base` row), and residuals from that run's per-cycle base `.rei` (`residuals` capped at `max_residuals`, full table to CSV) |
| `run_ies_uncertainty` | `model: str`, `pst_file: str`, `forecast_names: list[str]` | Forecast ensemble statistics: mean, std, 5th/95th percentiles |
| `check_parameter_sensitivity` | `model: str`, `parameters: dict[str, float]`, `template_files: list[str]`, `delta: float = 0.1` | Per-parameter sensitivity (mean relative change of the simulated observations) over n+1 forward runs (7f-H3.1) |
| `calibrate` | `model: str`, `par_data: dict`, `template_files: list[str]`, `time_budget_minutes: float = 30.0`, `noptmax: int = 10`, `num_reals: int = 50` | Chosen method + rationale + the run result (7f-H4.1) |

**Sequential-DA semantics on the installed `pestpp-da` v5.2.16:** `noptmax` is iterations per cycle and **`0` performs no update** (base values only, one realisation) — use `noptmax >= 1` for an ensemble-Kalman update (`setup_da_control` defaults to `1`). `da_num_reals` overrides `ies_num_reals`. `da_weight_cycle_table` is accepted but **ignored** in this build, so observation weights must be non-zero in `obs_data.csv`. A DA run needs one MODFLOW 6 stress period / one time step per cycle (`NPER=1`, `NSTP=1`).

### DA-ready control file — `setup_da_control`

`setup_da_control` emits the whole DA interface in one call (7f-DA):

- rewires NPF `k` to an external `OPEN/CLOSE` array and generates the K template (reusing the `setup_calibration` machinery). With `scope="multiplier"` the K template is the **one-token** `<gwf>_k_mult.dat.tpl` over an all-cells zone and the forward wrapper computes `k = base_k × factor` each run, so the base K pattern is preserved (see the single-factor K multiplier note above);
- rewires the IC `strt` array and generates a **state-augmented IC template** — one state parameter per registered observation cell, sharing the observation name so `da_use_simulated_states True` carries each cycle's simulated heads into the next cycle's IC;
- generates the MF6-OBS-CSV instruction file (the canonical `l1 ~,~ !name! …` pif reads the first data row, which is the end-of-cycle value because there is one time step per cycle);
- writes the observation cycle table (`obs_cycles`), a weight cycle table when `obs_weights` is given (v5.2.16 ignores it — the authoritative weights are the non-zero values in `obs_data.csv`), and, when `par_cycles` supplies fixed forcing values, a populated parameter cycle table (a `perlen` entry templates the TDIS stress-period length). A `par_cycles` key that names an adjustable parameter is a hard `INVALID_INPUT` error (the cycle table would override the calibrated value every cycle);
- assembles a **version-2** `.pst` whose external parameter/observation/model-IO sections carry a `cycle` column, with `da_num_reals`, `da_observation_cycle_table`, `da_parameter_cycle_table` and `da_use_simulated_states`;
- when `prior_ensemble` (a mapping of parameter name to a list of realisations) or `prior_std` (draw `num_reals` realisations around each parameter's value with that standard deviation — log10 space for `partrans='log'`) is supplied, writes `<model>_da_prior.csv` (rows = realisations, columns = parameters) and sets `da_parameter_ensemble`; the ensemble row count becomes `da_num_reals`. Every drawn **or supplied** realisation is clipped into its parameter's `parlbnd`/`parubnd` interval (in the parameter's own value/transform space), so a large `prior_std` cannot emit out-of-bounds values and an explicit out-of-bounds `prior_ensemble` entry is clamped rather than silently passed to pestpp-da. With neither, `pestpp-da` draws the prior internally from the parameter bounds.

**Physical state bounds (7f-DA.3):** the `head_state` parameters (the state augmentation) get `parlbnd = strt - bound` / `parubnd = strt + bound`, where `bound = max(observed spread, abs(strt - mean(observed values)), 5 m)` — wide enough to cover both the observed range and the head shift the evidence demands, and never the `relative` change limit (about +/-1e6 m) that made the default bounds-derived prior physically meaningless (cycle-0 phi ~1e9 in the 6d rerun-2). A site with fewer than two registered values gets the 10 m default. `state_head_bound` (a positive float) overrides the derived bound for every state parameter, and the per-site bound actually used is reported in the result's `state_bounds` map. When a prior is written, `prior_ensemble_n_clipped` reports how many drawn/supplied realisations were clamped. `setup_da_control` also performs a **single** full-model flush after staging both the NPF-K and IC-`strt` rewires (previously each helper flushed the whole model): on a 31,831-node DISU grid the rewire phase drops from ~42.3 s to ~21.2 s (measured, rewire phase only — not whole-setup wall time) with byte-identical on-disk inputs.

**Setup runtime on a large DISU grid (Task 9 measurement):** a whole `setup_da_control` call on the 31,831-node DISU model (K template 605 kB / 31,522 tokens, 13 state parameters, 6 cycles) takes **~22–24 s** wall on the reference machine — inside the ~90 s MCP client timeout, so the result object is no longer lost. Profiling attributes **94 %** of that to the single required `sim.write_simulation()` inside `flush_model` (55.5 s of 58.8 s under `cProfile`; ~20 s unprofiled): FloPy recomputes each package's size definitions by re-reading every external array file, and this model ships **~2.4 M lines** of DISU external arrays (`JA`/`IAC`/`HWVA`/`CL12`/`ANGLDEGX`/`VERTICES`/`CELL2D`) that FloPy tokenises one line at a time with `shlex` (2.33 M `shlex.split` calls). The flush cannot be deferred (the K/IC template substitution must run *after* FloPy writes, or FloPy overwrites the substituted arrays) and cannot be narrowed to the changed packages without changing `flush_model`'s dirty-flag semantics for every builder tool — so it is left as is, with a ~5× speedup available from a selective (NPF/IC/TDIS-only) write if this path ever needs it.

`cycles` are DA cycle indices; `obs_cycles` maps a registered site name to `{cycle: observed value}` (a missing cycle is a blank/off cycle). The state-augmented IC parameterisation supports **DIS, DISV and DISU** grids: on DIS/DISV a site's stored cell id is `(layer, row, col)` / `(layer, node)`, on DISU it is a scalar **1-based node** number (`import_obs_from_csv` stores `node + 1`; the flat IC index is `node - 1` on a `nnodes`-node grid). A site outside the grid is an `INVALID_INPUT` error, raised **before** any model write (NPF `k` / IC `strt` are rewired only once all grid, state-cell and cycle inputs validate). The model must have `NPER=1`/`NSTP=1` — `setup_da_control` returns a clear `INVALID_INPUT` error otherwise. `use_simulated_states=True` is the only supported value: pestpp-da v5.2.16 requires final-to-initial state linkages the tool does not emit, so `use_simulated_states=False` is rejected with `INVALID_INPUT`. Run the assimilation with `run_pestpp_da`, then `summarise_da`.

**Reading DA outputs — `summarise_da`:** pestpp-da v5.2.16 writes a per-cycle phi file `<case>.global.phi.actual.csv` (`cycle,iteration,mean,standard_deviation,min,max,<reals...>`, two rows per cycle — iteration 0 = prior, ≥1 = post-update), a final-cycle parameter ensemble `<case>.global.<cycle>.pe.csv` (`real_name` column plus one column per parameter, with a `base` row alongside the realisations), and per-cycle base residual files `<case>.<cycle>.<iter>.base.rei`. `summarise_da` reports the **post-update** ensemble-mean phi for each cycle (never the cycle-0 prior), the final cycle's phi mean/std, posterior parameter statistics (the `base` row excluded — it is not an ensemble member), and residuals from that cycle's highest-iteration `.rei` (whose observed values are that cycle's cycle-table values).

**`summarise_da` is run-isolated:** the current run's cycle set is taken from its own (overwritten) per-cycle phi file, and the posterior ensemble and residuals are read from **that run's final cycle** — not from the highest cycle number present in the workspace. A second DA run with fewer cycles in a reused workspace therefore reports its own posterior and residuals rather than the earlier run's higher-cycle leftovers (the 6d rerun-4 finding F2: a 6-cycle control reporting run-1's `k=10.0` and its 2018-12-20 residuals). `summarise_calibration` does **not** summarise DA runs; use `summarise_da`. A workspace with **no** run outputs at all (no `<case>.global.phi.actual.csv` and no per-cycle `<case>.global.<cycle>.pe.csv`) fails loudly with `OUTPUT_FILE_MISSING` rather than returning an empty success — a partial no-update run that wrote the cycle phi is still summarised.

`summarise_calibration` returns a **verdict** (7f-H4.2): `improved` (phi
reduction versus the previous run — the prior phi is stored per model),
`parameters_at_bounds`, `identifiable` (from the last
`check_parameter_sensitivity` run), and `fit_within_measurement_error`
(`rmse <= measurement_error`).

**Missing residuals fail loudly (7e-B2):** a PEST++ run that dies before
writing residuals (no `<case>.res` / `.rei` / `.base.rei`) returns the
`OUTPUT_FILE_MISSING` envelope naming the missing file — never a
successful-looking result with `rmse: None, n_observations: 0`. A corrupt
`.par`/phi CSV surfaces an error instead of empty progress (7e-B3).

**pestpp-ies summarise (2026-08-29):** `summarise_calibration` works for both
engines, auto-detected from the run artifacts (`engine` in the result):
`glm` from `<case>.par`/`.iobj`, `ies` from `<case>.*.par.csv`/`.obs.csv`
(no `.par` present). For an IES run: phi comes from `<case>.phi.actual.csv`'s
ensemble-mean column (never a sum of the mean/std/min/max/realisation
columns); parameter estimates come from the final ensemble
`<case>.<N>.par.csv` with `estimated_value` = the ensemble mean plus
`ensemble_mean/std/min/max` and `n_realizations`; residuals come from
`<case>.rei` when present, otherwise from the final observation ensemble
`<case>.<N>.obs.csv` compared against the PST observed values (modelled =
ensemble mean per site). Only a run with neither residuals nor an ensemble
file fails `OUTPUT_FILE_MISSING`.

---

## spec — declarative models, provenance, scenarios (7f-G)

| Tool | Inputs | Returns |
|---|---|---|
| `apply_model_spec` | `model: str`, `spec: dict` | Structured diff of what changed (packages added/replaced/unchanged) |
| `export_model_spec` | `model: str` | The declarative spec for the model, ready to inspect/diff/rebuild |
| `export_reproducible_script` | `model: str` | Path to a standalone `run.py` that rebuilds the model in pure flopy — no MCP dependency (7f-I5) |
| `describe_model` | `model: str` | What the model is, where every number came from, and what is unverified |
| `export_model_report` | `model: str` | Path to a Markdown report (description, provenance table, water balance, obs fit, plots, tool-call history) |
| `clone_model` | `source: str`, `name: str`, `workspace: str = ""` | Copy the model to a new workspace (binary outputs not copied) |
| `compare_scenarios` | `model_a: str`, `model_b: str` | Head-difference statistics (incl. the max-difference cell), per-boundary budget deltas, observation-fit deltas — not arrays |

### Model spec schema (G1)

A spec is one JSON-serialisable dict describing the whole model:

```json
{
  "name": "tut05",
  "units": "METERS",
  "time_units": "DAYS",
  "grid": {
    "type": "DIS", "nlay": 1, "nrow": 66, "ncol": 64,
    "delr": 500.0, "delc": 500.0, "top": 50.0, "botm": [40.0, 30.0],
    "crs": "EPSG:32718"
  },
  "time": {"nper": 1, "perlen": [1.0], "nstp": [1], "ims_complexity": "moderate"},
  "properties": {"npf": {"icelltype": 1, "k": 10.0, "k33": 1.0, "save_flows": true}},
  "initial_conditions": {"strt": 45.0},
  "storage": {"iconvert": 1, "ss": 1e-5, "sy": 0.2, "steady_state": [0]},
  "boundaries": {
    "WEL": {"0": [[[0, 5, 5], -500.0]]},
    "CHD": {"0": [[[0, r, 0], 70.0] for r in range(64)]}
  },
  "output_control": {"head_file": "tut05.hds", "budget_file": "tut05.cbb",
                     "saverecord": [["HEAD", "ALL"], ["BUDGET", "ALL"]]}
}
```

`grid` and `time` are required. Validation rejects unknown keys, missing
required keys, and dimensional mismatches (e.g. `len(botm) != nlay`) with
distinct messages. `apply_model_spec` reconciles the spec onto a model in any
prior state (build-from-scratch or diff-against-existing) and is idempotent;
`export_model_spec` emits the spec for an existing or adopted model so a real
model can be inspected, diffed and rebuilt.

### Provenance (G2)

Every MCP tool call appends a line to `<workspace>/.gwmcp_history.jsonl`
(timestamp, tool, argument digest, one-line change description; failures
record their error code). Parameterisation tools record data-source provenance
per array in `.gwmcp_meta.json` (`provenance`). `describe_model` combines both:
data-source provenance, `unverified_defaults` (uniform/default-valued arrays
never sourced from data), `has_run`, `results_stale` (an input file newer than
the latest `.hds`), and the ledger entry count. `export_model_report` turns
all of it into a Markdown report fit for a memo.

### Scenarios (G3)

`clone_model` copies a model (excluding binary outputs) to a new registered
workspace; `compare_scenarios(a, b)` returns differences — head-difference
min/max/mean/percentiles and the max-difference cell, per-boundary budget
deltas, and observation-fit deltas — small responses, never arrays.

---

## MCP prompts (7e-C6)

Two prompts encode the tool-call ordering an agent otherwise infers from
tool descriptions and trial and error (`mcp.list_prompts()`):

| Prompt | Arguments | Returns |
|---|---|---|
| `build_model_from_data` | `model: str`, `has_grid_shapefile: bool = True`, `has_dem: bool = True`, `has_zone_shapefile: bool = True`, `has_boundary_data: bool = True`, `has_observations: bool = True`, `transient: bool = False` | A numbered build-order guide (check_environment → create_model → set_simulation → grid → CRS → NPF → IC → [STO] → boundaries → [obs] → OC → check_model → run → validate/diagnose → export), skipping steps whose input isn't available |
| `calibrate_model` | `model: str`, `use_ensemble: bool = False` | A numbered calibration guide (confirm run + registered obs → `setup_calibration` → optional sensitivity screen → GLM or IES → `summarise_calibration` → [uncertainty]) |

Both are plain text, not tool calls — a client renders them as a starting
message for the agent, encoding the same ordering `model_status`/`next_steps`
(7e-C8) enforce at runtime.

## MCP resources (7e-C7)

Three resource templates expose per-model files as readable URIs instead of
requiring a tool call whose whole job is returning a giant string
(`mcp.list_resource_templates()`; read with `mcp.read_resource(uri)`):

| URI template | Mime type | Content |
|---|---|---|
| `gwmcp://models/{model}/lst` | `text/plain` | The full MODFLOW listing (`.lst`) file |
| `gwmcp://models/{model}/pst` | `text/plain` | The PEST++ control (`.pst`) file |
| `gwmcp://models/{model}/files` | `application/json` | The workspace file listing (same shape as `list_model_files`) |

These register as resource *templates* (`{model}` is a variable path
segment) since models are created at runtime — they appear in
`mcp.list_resource_templates()`, not the static `mcp.list_resources()`.
Reading a URI for a model with no `.lst`/`.pst` yet, or an unknown model
name, raises — FastMCP wraps the underlying error in its own `ValueError`
rather than passing the original exception type through.

---

## Error handling

All tools return a consistent error envelope on failure:

```json
{
  "error": true,
  "code": "MODEL_NOT_FOUND",
  "message": "No model named 'my_model' found in workspace /path/to/ws",
  "suggestion": "Run create_model first, or check the workspace path."
}
```

Common error codes: `MODEL_NOT_FOUND`, `PACKAGE_MISSING`, `BINARY_NOT_FOUND`, `CONVERGENCE_FAILED`, `OUTPUT_FILE_MISSING`, `PEST_ERROR`, `CRS_UNKNOWN`, `MODEL_ADOPTED_READONLY`, `PAYLOAD_TOO_LARGE`, `JOB_NOT_FOUND`, `START_RUN_FAILED`, `JOB_STATUS_FAILED`, `JOB_CANCEL_FAILED`, `DIAGNOSIS_FAILED`, `VALIDATION_FAILED`, `MODEL_STATUS_FAILED`, `EXPORT_FAILED`.
