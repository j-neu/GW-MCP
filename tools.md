# groundwater-mcp — Tool Reference

26 tools across 5 modules. All tools are registered with the MCP server and callable by any compatible AI client.

---

## docs

Search and retrieve documentation from MODFLOW 6, FloPy, PEST++, and pyEMU. Index is built locally at install time from public GitHub repositories.

| Tool | Inputs | Returns |
|---|---|---|
| `search_docs` | `query: str`, `repos: list[str] \| None`, `method: "text" \| "semantic" \| "auto"`, `limit: int = 10` | List of matching doc snippets with source paths and relevance scores |
| `search_tutorials` | `query: str`, `complexity: "beginner" \| "intermediate" \| "advanced" \| None`, `limit: int = 5` | List of matching notebooks/examples with descriptions and paths |
| `get_doc_file` | `path: str`, `page: int = 1` | Full file content (paginated at 30 KB) |

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
| `add_boundary_package` | `model: str`, `package: str`, `stress_period_data: dict`, `kwargs: dict` | Package summary with cell count per stress period |
| `add_oc_package` | `model: str`, `head_filerecord: str \| None`, `budget_filerecord: str \| None`, `saverecord: list`, `printrecord: list \| None` | Confirmation |
| `summarise_model` | `model: str` | Structured summary: packages, grid dimensions, stress periods, boundary types |
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

---

## calibration

Set up and run PEST++ parameter estimation via pyEMU.

| Tool | Inputs | Returns |
|---|---|---|
| `setup_pest_control` | `model: str`, `obs_data: dict`, `par_data: dict`, `template_files: list`, `instruction_files: list`, `pestpp_options: dict \| None` | Path to generated `.pst` control file |
| `run_pestpp_glm` | `model: str`, `pst_file: str`, `num_workers: int = 1` | `{ converged: bool, final_phi: float, iterations: int }` |
| `run_pestpp_ies` | `model: str`, `pst_file: str`, `num_reals: int = 50`, `num_workers: int = 1` | `{ final_phi_mean: float, final_phi_std: float, iterations: int }` |
| `summarise_calibration` | `model: str`, `pst_file: str` | Phi progress table, parameter estimates vs priors, residual statistics (RMSE, bias, R²) |
| `run_ies_uncertainty` | `model: str`, `pst_file: str`, `forecast_names: list[str]` | Forecast ensemble statistics: mean, std, 5th/95th percentiles |

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

Common error codes: `MODEL_NOT_FOUND`, `PACKAGE_MISSING`, `BINARY_NOT_FOUND`, `CONVERGENCE_FAILED`, `OUTPUT_FILE_MISSING`, `PEST_ERROR`.
