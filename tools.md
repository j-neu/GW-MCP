# groundwater-mcp — Tool Reference

67 tools across 7 modules, plus 2 MCP prompts and 3 MCP resource templates. All tools are registered with the MCP server and callable by any compatible AI client.

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
| `describe_package` | `name: str` | The MODFLOW 6 package specification — blocks (required/optional) and, for boundary packages, the `stress_period_data` record fields (7f-I3) |

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
| `import_obs_from_csv` | `model: str`, `csv_file: str`, `obs_type: "HEAD" \| "FLOW"`, `site_col: str`, `date_col: str`, `value_col: str`, `x_col: str \| None`, `y_col: str \| None`, `layer: int = 0` | Observation summary: site count, record count, date range, written observation file path |

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
- `import_obs_from_csv` matches observation sites to model cells by (x, y) coordinate if provided; otherwise by site name mapped to a pre-existing cell mapping.

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
| `add_disu_package` | `model: str`, `nodes: int`, `nja: int`, `top: list`, `bot: list`, `area: list \| None = None`, `iac: list \| None = None`, `ja: list \| None = None`, `ihc: list \| None = None`, `cl12: list \| None = None`, `hwva: list \| None = None`, `angldegx: list \| None = None`, `idomain: list \| None = None`, `gridprops_file: str \| None = None` | Grid summary |

Fully unstructured (DISU) grids are defined by explicit node connectivity: `nodes`/`nja` plus `iac` (connections per node) and `ja` (connected node ids, 0-based; each node's first connection must be itself). `top`/`bot` are per-node; `area` defaults to 1.0 and `ihc`/`cl12`/`hwva` default to single-layer/unit placeholders so a connectivity-only model still runs. Pass `gridprops_file` (JSON) for large grids. Obs cell ids are scalar 0-based node numbers; adopter models keep working via `adopt_model`.
| `add_npf_package` | `model: str`, `icelltype: int \| list`, `k: float \| list`, `k33: float \| list \| None`, `save_flows: bool = True`, `k_units: str = "m/d"` | Confirmation |
| `add_ic_package` | `model: str`, `strt: float \| list` | Confirmation |
| `add_sto_package` | `model: str`, `iconvert: int \| list`, `ss: float \| list`, `sy: float \| list \| None`, `steady_state: list[int] \| None`, `save_flows: bool = True` | Package summary with resolved steady/transient periods |
| `add_boundary_package` | `model: str`, `package: str`, `stress_period_data: dict`, `kwargs: dict`, `save_flows: bool = True`, `rate_units: str \| None = None`, `pname: str \| None = None` | Package summary with cell count per stress period |

**Units (7f-H1.1):** `add_npf_package` accepts `k_units` (default "m/d";
accepted m/d, m/s, m/yr, cm/s, ft/d, ft/s) and converts `k`/`k33` into the
model's length/time convention on entry; `add_boundary_package` accepts
`rate_units` (m/d, m/yr, mm/d, mm/yr) for RCH/EVT rates, converting them into
m/d. Declared units are recorded in `.gwmcp_meta.json` and reported by
`summarise_model.units` (`{length, time, k, recharge}`).

`stress_period_data` maps a **0-based** stress-period index to records with **0-based** cell indices (layer, row, col for DIS; layer, node for DISV); indices are converted to 1-based when written to the package file. `save_flows` (default on) writes the SAVE FLOWS option so the package's fluxes appear in the budget file for `compute_water_balance`.

**RCHA/EVTA — array-based recharge/ET (7e-B8):** `add_boundary_package(package="RCHA"|"EVTA", ...)` accepts a full-grid array per stress period instead of cell records (`{"0": <nrow×ncol array>}` for DIS layer 0, or `<ncpl>` for DISV). `rate_units` is converted on entry exactly as for RCH/EVT. The budget term is `RCH`.

**pname — several packages of one type (7e-B10):** re-adding a package with an explicit `pname` replaces only that package, so two CHD sets can coexist (`pname="chd_high"` + `pname="chd_low"`, e.g. tutorial-05). Without a `pname` every package of the type is replaced first (as before). The replacement warning names the pname.

`adopt_model` registers an **existing** MODFLOW 6 simulation on disk (a directory containing a runnable `mfsim.nam` + package files) without creating a stub or rewriting files — so `check_model`, `run_simulation`, `summarise_model`, and the calibration chain operate on the real model. The GWF model name inside the files need NOT match `name` (tools fall back to the first model in the simulation). Use it to bring a real published/regional model into the MCP toolchain instead of `create_model` + manual file copying.

**Adopted models are read-only by default (7f-D4.2):** every `save_sim`-backed builder call (`add_*`, `set_simulation`, `assign_*`, `import_*`) on an adopted model is refused with `error=True, code="MODEL_ADOPTED_READONLY"` so a real published model cannot be silently rewritten by a stray call. Pass `allow_modify=True` to opt out. Non-mutating tools (`check_model`, `run_simulation`, `summarise_model`, `read_heads`, plotting) always work.

**Cache staleness (7f-D4.1):** the in-process cache records the mtimes of `mfsim.nam` and the package files at load/save time. If any tracked file changes on disk outside the MCP, the next `get_sim` reloads from disk and the calling tool reports `reloaded_from_disk: true` (currently surfaced by `summarise_model`).

**Registry scoping (7e-B4.2):** the model registry is scoped per workspace root. Models created with an explicit `workspace` register in a `.<root>/.gwmcp_registry.json` next to that workspace; models created without one register under the default root. Re-registering the same name+path is idempotent; the same name under different roots is legal; the same name twice in one root with different paths errors.

`add_sto_package` defines aquifer storage (required for transient simulations). `steady_state` lists the **0-based** stress-period indices that are steady-state; all other periods run transient. Default `[0]` → first period steady, rest transient; `[]` → all periods transient. `sy` (specific yield) is required when any cell is convertible (`iconvert > 0`). **Without an STO package, a multi-time-step model runs as steady state** — `check_model` and `run_simulation` return a warning when they detect that configuration.
| `add_oc_package` | `model: str`, `head_filerecord: str \| None`, `budget_filerecord: str \| None`, `saverecord: list`, `printrecord: list \| None` | Confirmation |
| `summarise_model` | `model: str` | Structured summary: packages, grid dimensions (+ `n_active` when idomain present), stress periods, boundary types, storage (STO steady/transient periods), registered `observations` count, `reloaded_from_disk` flag |
| `model_status` | `model: str` | `{ runnable: bool, missing_required: list[str], missing_recommended: list[str], next_steps: list[str], warnings: list[str] }` — ordered build-order status (7e-C8) |
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
| `get_run_log` | `model: str`, `tail: int = 100` | Last N lines of the MODFLOW listing file (.lst) |

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
- `start_calibration(model, pst_file, method, num_reals)` (calibration module)
  starts pestpp-glm (`method="glm"`, default) or pestpp-ies (`method="ies"`)
  the same way. While running, progress reports `engine`, `iteration` and
  `latest_phi` parsed from `<case>.iobj` (GLM) or `<case>.phi.actual.csv`
  (IES). The finished result matches `run_pestpp_glm` / `run_pestpp_ies`.
- `cancel_job(job_id)` terminates the underlying process **and its entire
  process tree** (`taskkill /T /F` on Windows, `killpg` on POSIX) — the
  PEST++ forward chain spawns `mf6.exe` grandchildren that would otherwise
  survive as orphans, spinning and file-locking the workspace — and reports
  `"cancelled"`. An unknown `job_id` returns the `JOB_NOT_FOUND` envelope.
  Jobs are spawned in their own process group/session so the tree is killable.

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
| `plot_heads_map` | `model: str`, `layer: int = 0`, `kstpkper: tuple \| None`, `contour_intervals: int = 10`, `output_file: str \| None` | The PNG returned natively (ImageContent) + the saved file path |
| `plot_cross_section` | `model: str`, `line: dict`, `kstpkper: tuple \| None`, `output_file: str \| None` | The PNG returned natively (ImageContent) + the saved file path |

`plot_heads_map` / `plot_cross_section` return the PNG natively as an MCP
image content block together with the saved file path (7f-I1) — the separate
`view_image` round-trip has been removed.

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

---

## calibration

Set up and run PEST++ parameter estimation via pyEMU.

| Tool | Inputs | Returns |
|---|---|---|
| `setup_calibration` | `model: str`, `parameterisation: dict`, `obs_source: str = "model"`, `noptmax: int = 10` | The generated PEST interface: `.pst`, template, instruction file, external array, forward wrapper, parameter table |
| `setup_pest_control` | `model: str`, `obs_data: dict`, `par_data: dict`, `template_files: list`, `instruction_files: list`, `pestpp_options: dict \| None`, `obs_source: "explicit" \| "model" = "explicit"` | Path to generated `.pst` control file |
| `start_calibration` | `model: str`, `pst_file: str`, `method: "glm" \| "ies" = "glm"`, `num_reals: int = 50` | `{ model, job_id, kind, pst_file, status: "running" }` — starts PEST++ in a background thread with live phi progress (7e-A3) |

### Automated calibration setup — `setup_calibration` (7e-A2)

`setup_calibration` emits the **whole** PEST interface in one call with zero
hand-written files. `parameterisation` maps a parameter name (≤ 12 chars, PEST
cap) to a spec dict:

```json
{
  "k": {"target": "npf:k", "scope": "all", "initial": 5.0}
}
```

- `target`: the model array to parameterise — currently `"npf:k"` only.
- `scope`: `"all"` (whole array), `"layer"` (with `"layer": N`), `"cells"`
  (with `"cells": [[layer, row, col], ...]` on DIS — `[[layer, node], ...]`
  on DISV), or `"zones"` (with `"layer": N`). Scopes must partition the array
  exactly for all/layer/cells; `zones` is the multiplier mode below.
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

The call then: (1) rewires NPF `k` to an external `OPEN/CLOSE <file>` array
(so a template can target it — the model runs identically afterwards); (2)
generates a template with wide fixed-width tokens (≥ 15 chars — the `@k@`
truncation bug is structurally impossible); (3) generates the instruction
file from the model's OBS CSV header (`obs_source="model"`, reading the
targets registered by `import_obs_from_csv`); (4) writes a Python forward-run
wrapper at a space-free path when the default MF6 command would be unsafe on
Windows (spaces in the workspace or the MF6 binary path); and (5) assembles
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
| `run_pestpp_glm` | `model: str`, `pst_file: str`, `num_workers: int = 1` | `{ converged: bool, final_phi: float, iterations: int }` |
| `run_pestpp_ies` | `model: str`, `pst_file: str`, `num_reals: int = 50`, `num_workers: int = 1` | `{ final_phi_mean: float, final_phi_std: float, iterations: int }` |
| `summarise_calibration` | `model: str`, `pst_file: str`, `measurement_error: float \| None = None`, `max_residuals: int = 500` | Phi progress table, parameter estimates vs priors, residual statistics (RMSE, bias, R²; `residuals` capped at `max_residuals`, full table to CSV), an `engine` field, and a `verdict` |
| `run_ies_uncertainty` | `model: str`, `pst_file: str`, `forecast_names: list[str]` | Forecast ensemble statistics: mean, std, 5th/95th percentiles |
| `check_parameter_sensitivity` | `model: str`, `parameters: dict[str, float]`, `template_files: list[str]`, `delta: float = 0.1` | Per-parameter sensitivity (mean relative change of the simulated observations) over n+1 forward runs (7f-H3.1) |
| `calibrate` | `model: str`, `par_data: dict`, `template_files: list[str]`, `time_budget_minutes: float = 30.0`, `noptmax: int = 10`, `num_reals: int = 50` | Chosen method + rationale + the run result (7f-H4.1) |

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
