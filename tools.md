# groundwater-mcp — Tool Reference

39 tools across 7 modules. All tools are registered with the MCP server and callable by any compatible AI client.

---

## environment

Preflight check for a hands-free session. Reports the server's own runtime stack so the agent verifies the environment instead of probing with shell commands.

| Tool | Inputs | Returns |
|---|---|---|
| `check_environment` | *(none)* | Python version/executable, installed packages with versions (flopy, pyemu, geopandas, rasterio, ...), MODFLOW 6 / PEST++ / UCODE binary paths, docs index state, default workspace root, `ready` flag + missing items |

## docs

Search and retrieve documentation from MODFLOW 6, FloPy, PEST++, and pyEMU. Index is built locally at install time from public GitHub repositories.

| Tool | Inputs | Returns |
|---|---|---|
| `search_docs` | `query: str`, `repos: list[str] \| None`, `method: "text" \| "semantic" \| "auto"`, `limit: int = 10` | List of matching doc snippets with source paths and relevance scores |
| `search_tutorials` | `query: str`, `complexity: "beginner" \| "intermediate" \| "advanced" \| None`, `limit: int = 5` | List of matching notebooks/examples with descriptions and paths |
| `get_doc_file` | `path: str`, `page: int = 1` | Full file content (paginated at 30 KB) |

---

## parameterise

Translate processed spatial data (rasters, shapefiles, CSVs) into MODFLOW 6 model inputs. These tools accept standard GIS file formats and produce the arrays and stress period data consumed by the model builder. They expect *already-processed* data — reprojection, resampling, and interpolation from raw sources is handled upstream by a companion tool or manually.

| Tool | Inputs | Returns |
|---|---|---|
| `import_grid_from_shapefile` | `model: str`, `shapefile: str`, `nlay: int`, `layer_surfaces: list[str]`, `method: "disv" \| "dis" = "disv"`, `target_crs: str \| None` | Grid summary: cell count, layer count, CRS, bounding box |
| `assign_top_from_raster` | `model: str`, `raster: str`, `layer: int = 0`, `method: "mean" \| "min" \| "max" \| "bilinear" = "mean"` | Array statistics (min, max, mean) and count of cells assigned |
| `assign_k_from_zones` | `model: str`, `shapefile: str`, `k_field: str`, `layer: int \| list[int]`, `k33_field: str \| None`, `icelltype_field: str \| None` | Zone summary: zone count, cell count per zone, K range |
| `import_river_from_shapefile` | `model: str`, `shapefile: str`, `package: "RIV" \| "DRN" \| "GHB"`, `stage_field: str \| None`, `cond_field: str \| None`, `depth_field: str \| None`, `stage_raster: str \| None`, `stage_offset: float = 1.0`, `stress_periods: list[int] \| None` | Stress period data summary: reach count, intersected cells, package written |

NOTE: with no stage attribute/raster, river stage defaults to 0.0 m and the river acts as a deep drain. Pass `stage_raster` (a ground-surface elevation GeoTIFF) to derive stage as raster value minus `stage_offset`, or provide a `stage_field` attribute. RIV records are `[cellid, stage, cond, rbot]`; DRN/GHB records are `[cellid, elev, cond]`.
| `import_obs_from_csv` | `model: str`, `csv_file: str`, `obs_type: "HEAD" \| "FLOW"`, `site_col: str`, `date_col: str`, `value_col: str`, `x_col: str \| None`, `y_col: str \| None`, `layer: int = 0` | Observation summary: site count, record count, date range, written observation file path |

### Notes

- `import_grid_from_shapefile` uses `flopy.utils.GridGen` (DISV) or derives a regular DIS grid from the polygon bounding box.
- `assign_top_from_raster` uses `rasterio` to sample the raster at cell centroids and writes the result to the model's top or botm arrays.
- `assign_k_from_zones` intersects cell centroids with zone polygons via `geopandas`; cells outside all zones retain their existing K.
- `import_river_from_shapefile` intersects the river network with the model grid and snaps reaches to cell faces.
- `import_obs_from_csv` matches observation sites to model cells by (x, y) coordinate if provided; otherwise by site name mapped to a pre-existing cell mapping.

---

## model builder

Create and configure MODFLOW 6 GWF models using FloPy. All tools operate on a named workspace directory.

| Tool | Inputs | Returns |
|---|---|---|
| `create_model` | `name: str`, `workspace: str`, `units: str = "METERS"`, `time_units: str = "DAYS"` | Confirmation with workspace path |
| `set_simulation` | `model: str`, `nper: int`, `perlen: list[float]`, `nstp: list[int]`, `ims_complexity: "simple" \| "moderate" \| "complex"` | Confirmation |
| `add_dis_package` | `model: str`, `nlay: int`, `nrow: int`, `ncol: int`, `delr: float \| list`, `delc: float \| list`, `top: float \| list`, `botm: list` | Grid summary (dimensions, cell count) |
| `add_disv_package` | `model: str`, `nlay: int`, `vertices: list`, `cell2d: list`, `top: list`, `botm: list` | Grid summary |
| `add_npf_package` | `model: str`, `icelltype: int \| list`, `k: float \| list`, `k33: float \| list \| None`, `save_flows: bool = True` | Confirmation |
| `add_ic_package` | `model: str`, `strt: float \| list` | Confirmation |
| `add_sto_package` | `model: str`, `iconvert: int \| list`, `ss: float \| list`, `sy: float \| list \| None`, `steady_state: list[int] \| None`, `save_flows: bool = True` | Package summary with resolved steady/transient periods |
| `add_boundary_package` | `model: str`, `package: str`, `stress_period_data: dict`, `kwargs: dict`, `save_flows: bool = True` | Package summary with cell count per stress period |

`stress_period_data` maps a **0-based** stress-period index to records with **0-based** cell indices (layer, row, col for DIS; layer, node for DISV); indices are converted to 1-based when written to the package file. `save_flows` (default on) writes the SAVE FLOWS option so the package's fluxes appear in the budget file for `compute_water_balance`. Re-adding a package of the same type replaces the previous package and returns a warning.

`add_sto_package` defines aquifer storage (required for transient simulations). `steady_state` lists the **0-based** stress-period indices that are steady-state; all other periods run transient. Default `[0]` → first period steady, rest transient; `[]` → all periods transient. `sy` (specific yield) is required when any cell is convertible (`iconvert > 0`). **Without an STO package, a multi-time-step model runs as steady state** — `check_model` and `run_simulation` return a warning when they detect that configuration.
| `add_oc_package` | `model: str`, `head_filerecord: str \| None`, `budget_filerecord: str \| None`, `saverecord: list`, `printrecord: list \| None` | Confirmation |
| `summarise_model` | `model: str` | Structured summary: packages, grid dimensions, stress periods, boundary types, storage (STO steady/transient periods) |
| `list_model_files` | `model: str` | File list with sizes and types |

### Supported boundary packages for `add_boundary_package`

`CHD` (constant head), `WEL` (well), `RIV` (river), `DRN` (drain), `RCH` (recharge), `EVT` (evapotranspiration), `GHB` (general head boundary), `SFR` (streamflow routing)

---

## runner

Execute MODFLOW 6 and retrieve run results.

| Tool | Inputs | Returns |
|---|---|---|
| `check_model` | `model: str` | List of warnings and errors from FloPy model checker |
| `run_simulation` | `model: str`, `silent: bool = False` | `{ success: bool, elapsed_s: float, convergence: str, listing_summary: str }` |
| `get_run_log` | `model: str`, `tail: int = 100` | Last N lines of the MODFLOW listing file (.lst) |

---

## post-processing

Read binary output files and compute derived quantities.

| Tool | Inputs | Returns |
|---|---|---|
| `read_heads` | `model: str`, `kstpkper: tuple[int,int] \| None`, `layer: int = 0` | 2-D array of head values + statistics (min, max, mean) |
| `read_budget` | `model: str`, `text: str \| None`, `kstpkper: tuple[int,int] \| None` | Budget records as structured list |
| `compute_drawdown` | `model: str`, `kstpkper_initial: tuple`, `kstpkper_final: tuple`, `layer: int = 0` | 2-D drawdown array + statistics |
| `compute_water_balance` | `model: str`, `kstpkper: tuple \| None` | Inflow/outflow table by boundary type, net balance |
| `plot_heads_map` | `model: str`, `layer: int = 0`, `kstpkper: tuple \| None`, `contour_intervals: int = 10`, `output_file: str \| None` | Path to saved PNG file |
| `plot_cross_section` | `model: str`, `line: dict`, `kstpkper: tuple \| None`, `output_file: str \| None` | Path to saved PNG file |
| `view_image` | `model: str`, `filename: str`, `output_format: str = "png"` | Image file as base64 (mime type, size, data) for visual verification of plots |

---

## calibration

Set up and run PEST++ parameter estimation via pyEMU, or UCODE_2014 for model-agnostic calibration and uncertainty analysis.

### PEST++ tools

| Tool | Inputs | Returns |
|---|---|---|
| `setup_pest_control` | `model: str`, `obs_data: dict`, `par_data: dict`, `template_files: list`, `instruction_files: list`, `pestpp_options: dict \| None` | Path to generated `.pst` control file |

`obs_data` keys must match the instruction-file tokens exactly (case-insensitive); unmatched names raise an error rather than being silently dropped. Special `pestpp_options` keys: `model_command_line` (str) / `model_command` (str\|list) sets the forward-model command (Windows default: the located MF6 binary); `output_files` (list, parallel to `instruction_files`) sets explicit model output filenames; `noptmax` is native PEST control data.
| `run_pestpp_glm` | `model: str`, `pst_file: str`, `num_workers: int = 1` | `{ converged: bool, final_phi: float, iterations: int }` |
| `run_pestpp_ies` | `model: str`, `pst_file: str`, `num_reals: int = 50`, `num_workers: int = 1` | `{ final_phi_mean: float, final_phi_std: float, iterations: int }` |
| `summarise_calibration` | `model: str`, `pst_file: str` | Phi progress table, parameter estimates vs priors, residual statistics (RMSE, bias, R²) |
| `run_ies_uncertainty` | `model: str`, `pst_file: str`, `forecast_names: list[str]` | Forecast ensemble statistics: mean, std, 5th/95th percentiles |

### UCODE tools

| Tool | Inputs | Returns |
|---|---|---|
| `setup_ucode_control` | `model: str`, `obs_data: dict`, `par_data: dict`, `template_files: list`, `instruction_files: list`, `ucode_options: dict \| None` | Path to generated UCODE main input file (`.#ucode`) |
| `run_ucode` | `model: str`, `ucode_file: str` | `{ converged: bool, final_ssr: float, iterations: int, par_estimates: dict }` |
| `summarise_ucode_calibration` | `model: str`, `ucode_file: str` | SSR progress table, parameter estimates with confidence intervals, sensitivity matrix, residual statistics (RMSE, bias, R²) |
| `run_ucode_uncertainty` | `model: str`, `ucode_file: str`, `forecast_names: list[str]`, `method: "linear" \| "mcmc" = "linear"` | Forecast uncertainty bounds: mean, std, 5th/95th percentiles |

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

Common error codes: `MODEL_NOT_FOUND`, `PACKAGE_MISSING`, `BINARY_NOT_FOUND`, `CONVERGENCE_FAILED`, `OUTPUT_FILE_MISSING`, `PEST_ERROR`, `UCODE_ERROR`.
