# groundwater-mcp

> An open-source Python MCP server for AI-assisted groundwater modelling with MODFLOW 6, FloPy, PEST++, and pyEMU.

No waitlist. No paywall. No closed components. Runs entirely on your machine.

---

## What it does

groundwater-mcp connects any MCP-compatible AI assistant (Claude, Cursor, etc.) to a full groundwater modelling stack. You can ask your AI to build a model from real-world data, run it, inspect results, and calibrate parameters — all through natural language, with the actual computation happening locally via FloPy and MODFLOW 6.

```
"I have a DEM raster, a shapefile of geological zones with K values,
 borehole water level CSVs, and a river centreline shapefile.
 Build a 3-layer transient model of the catchment, run it for 2 years,
 calibrate against the observed heads, and plot the water balance."
```

### Scope

groundwater-mcp covers the *modelling* side of a groundwater workflow: parameterising a model from processed spatial data, running simulations, post-processing results, and calibrating parameters.

Upstream data preparation — clipping DEMs, kriging borehole logs, processing climate data — is intentionally out of scope. That work belongs in a companion `geodata-mcp` (planned). The interface between the two is simple: groundwater-mcp accepts standard file formats (GeoTIFF, GeoPackage/Shapefile, CSV) as inputs to its parameterisation tools.

---

## Tools (110 total, plus 2 MCP prompts and 3 MCP resource templates)

| Module | Tools |
|---|---|
| **environment** | `check_environment` |
| **docs** | `search_docs`, `search_tutorials`, `get_doc_file`, `describe_package` |
| **parameterise** | `import_grid_from_shapefile`, `import_boundary_from_shapefile`, `assign_top_from_raster`, `assign_k_from_zones`, `assign_k_from_raster`, `assign_ic_from_raster`, `assign_array_from_raster`, `import_river_from_shapefile`, `import_obs_from_csv`, `import_subsidence_observations` |
| **model builder** | `create_model`, `adopt_model`, `set_simulation`, `set_model_crs`, `add_dis_package`, `add_disv_package`, `add_disu_package`, `add_npf_package`, `add_ic_package`, `add_sto_package`, `add_csub_package`, `add_boundary_package`, `add_advanced_package`, `add_mvr_package`, `add_oc_package`, `flush_model`, `summarise_model`, `model_status`, `list_model_files`, `list_models`, `delete_model` |
| **runner** | `check_model`, `run_simulation`, `get_run_log`, `diagnose_convergence`, `validate_model`, `start_run`, `start_task`, `get_job_status`, `cancel_job`, `release_workspace_lock` |
| **post-processing** | `read_heads`, `read_budget`, `compute_drawdown`, `compute_water_balance`, `diagnose_water_balance`, `export_heads_to_raster`, `export_boundaries_to_shapefile`, `export_water_balance_csv`, `read_simulated_observations`, `compare_to_observed`, `read_compaction`, `plot_subsidence`, `plot_heads_map`, `plot_cross_section` |
| **calibration (PEST++)** | `setup_calibration`, `setup_da_control`, `setup_pest_control`, `start_calibration`, `run_pestpp_glm`, `run_pestpp_ies`, `run_pestpp_da`, `run_pestpp_sen`, `run_pestpp_sweep`, `run_pestpp_opt`, `apply_calibration_result`, `summarise_calibration`, `summarise_da`, `run_ies_uncertainty`, `check_parameter_sensitivity`, `calibrate` |
| **multi-model transport and tracking** | `add_gwe_model`, `add_gwe_adv_package`, `add_gwe_cnd_package`, `add_gwe_est_package`, `add_gwe_ssm_package`, `add_gwe_esl_package`, `read_temperature`, `plot_temperature_map`, `plot_temperature_timeseries`, `add_gwt_model`, `add_gwt_adv_package`, `add_gwt_dsp_package`, `add_gwt_mst_package`, `add_gwt_ssm_package`, `add_gwt_cnc_package`, `add_gwt_src_package`, `add_prt_model`, `add_prt_mip_package`, `add_prt_prp_package`, `add_prt_oc_package`, `read_pathlines`, `plot_pathlines`, `run_modpath`, `plot_modpath_pathlines`, `adopt_mt3d_usgs_model`, `read_concentration`, `plot_concentration_map` |
| **spec / provenance** | `apply_model_spec`, `export_model_spec`, `export_reproducible_script`, `describe_model`, `export_model_report`, `clone_model`, `compare_scenarios` |

`setup_calibration` supports **zoned NPF K multipliers** (`scope="zones"`): zones auto-derived from groups of equal positive per-layer `npf:k` values become dimensionless multiplier parameters applied by a generated forward wrapper (`k = base_k × multiplier[zone]`), preserving the base K pattern while calibrating only zone magnitudes. `setup_da_control` builds a DA-ready PEST++ **version-2** control file (cycle tables + `da_*` options, IC state parameterisation) for sequential ensemble data assimilation with `run_pestpp_da`; `summarise_da` reads pestpp-da's per-cycle outputs back (per-cycle phi, posterior parameter statistics, per-cycle residuals). These capabilities add no extra tools beyond `setup_da_control` and `summarise_da`, and the total above reflects the current registration.

**CSUB (subsidence)** is covered end-to-end: `add_csub_package` builds the MODFLOW 6 CSUB package (delay and no-delay interbeds, `cg_theta`/`cg_ske_cr`, compaction observation records, filerecords), `read_compaction` and `plot_subsidence` post-process the CSUB observation output into per-layer compaction and cumulative subsidence (with an optional observed overlay), and `import_subsidence_observations` registers a measured subsidence series as a **derived** time-series target. `setup_calibration(obs_source="derived")` then calibrates `csub:packagedata` (plus `csub:cg_theta`, `csub:cg_ske_cr` and `npf:k33`) targets through `run_pestpp_ies` → `summarise_calibration`.

**v0.3.0 multi-model foundation** (2026-09-25) is in place: a single simulation can hold several models (`gwf`/`gwe`/`prt`) addressed by an optional `component` argument on the model-scoped tools, with the GWF grid mirrored into a component and its exchange registered. It ships no new tool — it is the base the **GWE** and **PRT** capability specs (with **MT3D-USGS** and **MODPATH** post-processing) build on to complete the v0.3.0 gate.

**GWE heat transport** (2026-09-25) is built: `add_gwe_model` creates a heat simulation coupled to a completed flow run through MF6's Flow Model Interface, with `add_gwe_adv/cnd/est/ssm/esl_package` for the physics, `read_temperature` and `plot_temperature_*` for post-processing, and `run_simulation` running flow then heat. The ex-gwe-radial closed-book validation is the remaining v0.3.0 gate for GWE.

**GWT solute transport** (2026-10-15) is built: `add_gwt_model` creates a solute-transport simulation coupled to a completed flow run through the same Flow Model Interface as GWE, with `add_gwt_adv/dsp/mst/ssm/cnc/src_package` for the physics (advection, dispersion, sorption/decay, boundary and mass sources), `read_concentration` / `plot_concentration_map` for post-processing (shared with the legacy MT3D-USGS tools), and `run_simulation` running flow then transport. It is one-way (no density coupling) and covers CNC/SRC sources only; the `ex-gwt-keating` closed-book gate has not been run.

**MODPATH 7 particle tracking** (2026-10-15) is built: `run_modpath` tracks particles forward (where water goes) or backward (capture zones) from chosen cells or whole layers of a completed MODFLOW 6 run, returning end-point status counts, travel-time statistics and per-particle start/end/travel time, and `plot_modpath_pathlines` draws the pathlines. It reads the flow run's own head/budget/grid files and needs the `mp7` binary (`get-modflow` installs it); zones, weak-sink/source options and stop times are not exposed.

**PRT particle tracking** (2026-09-27) is built: `add_prt_model` adds a MODFLOW 6 PRT model as a **same-simulation** component (the GWF grid is mirrored and a `GWF6-PRT6` exchange registered), with `add_prt_mip/prp/oc_package` for the physics, release schedule and track output, and `read_pathlines` / `plot_pathlines` for post-processing. The `ex-prt-mp7-p01` closed-book validation is the remaining v0.3.0 gate for PRT.

**MT3D-USGS legacy post-processing** (2026-10-03) is built: `adopt_mt3d_usgs_model` registers an existing MODFLOW-2005 + MT3D-USGS model directory (the grid is read from the flow model's DIS), and `read_concentration` / `plot_concentration_map` read the binary `.UCN` concentration output and render a plan-view plume. This is **read + plot only** — the MCP does not author MT3D-USGS input or run the legacy binary. The closed-book **GMS "MT3D-USGS Keating"** validation is the remaining v0.3.0 gate for MT3D-USGS.

See [tools.md](tools.md) for full input/output documentation.

### Safety guarantees

- **Long jobs never block the client (7e-A3).** `start_run` and
  `start_calibration` execute in a background thread and return a `job_id`
  immediately; `get_job_status` reports live progress (stress period / time
  step / percent complete for MF6; iteration + phi for PEST++), and
  `cancel_job` terminates the process — a >30-minute calibration no longer
  trips the client timeout or forces a shell workaround.
- **Builder writes are deferred.** Model-building calls mutate the in-memory model and report `written: false`; the disk write happens once at `flush_model` (or automatically at `check_model`/`run_simulation`/`list_model_files` and the calibration handoff). A regional build no longer re-serialises every array on every call.
- **Adopted models are read-only by default.** `adopt_model` registers an existing on-disk MODFLOW 6 simulation without rewriting it; any mutating builder call on it returns `MODEL_ADOPTED_READONLY` unless `allow_modify=True` was passed.
- **External edits are never lost.** The model cache detects package-file changes on disk and reloads from disk instead of serving (and later overwriting with) a stale in-memory copy.
- **Spatial data is never compared in an assumed coordinate space.** A river importer call fails with `CRS_UNKNOWN` when the grid has no CRS but the data declares one; `stage_raster` sampling fails loudly (`STAGE_RASTER_NO_COVERAGE`) when the raster does not cover the reaches.
- **Post-processing validates indices.** Layer arguments are checked against the model's `nlay`, returning `INVALID_INPUT` instead of a silent wrong layer or a raw `IndexError`.
- **Build ordering surfaces proactively, not just as the next error (7e-C8).** Every builder/parameterise tool's result carries a `next_steps` list — the missing prerequisites for the model to be runnable, in build order — and `model_status(model)` reports the same thing on demand. Two MCP prompts (`build_model_from_data`, `calibrate_model`) and three MCP resources (`.lst`/`.pst`/file listing as readable URIs) round out the same "don't make the agent infer the ordering" goal.

---

## Try it

The fastest way to see the whole chain work is the runnable worked example, which
builds a model from a shapefile and DEM, calibrates it with PEST++ and runs the
calibrated model (about ten seconds, results in
[docs/examples/catchment-walkthrough.md](docs/examples/catchment-walkthrough.md)):

```bash
uv run python examples/catchment_walkthrough.py
```

---

## Install

The package is not on PyPI yet; install it from a clone:

```bash
# 1. Clone and install (uv recommended; `pip install -e .` also works)
git clone https://github.com/j-neu/GW-MCP.git
cd GW-MCP
uv sync

# 2. Download the MODFLOW 6 binary
uv run get-modflow :

# 3. Download the PEST++ binaries (for calibration)
uv run get-pestpp :

# 4. Build the local docs search index
uv run groundwater-mcp build-index
```

### Claude Desktop configuration

Add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`,
Linux: `~/.config/Claude/`), pointing `--directory` at your clone:

```json
{
  "mcpServers": {
    "groundwater": {
      "command": "uv",
      "args": ["--directory", "/path/to/GW-MCP", "run", "groundwater-mcp", "serve"]
    }
  }
}
```

---

## Requirements

- Python 3.11+
- flopy ≥ 3.7
- geopandas, rasterio (for parameterisation tools)
- MODFLOW 6 binary (via `get-modflow`)
- pyemu (for PEST++ calibration tools)
- PEST++ binaries (for PEST++ calibration tools)

---

## Project files

| File | Contents |
|---|---|
| [architecture.md](architecture.md) | System design, module responsibilities, file structure, tech stack |
| [docs/examples/catchment-walkthrough.md](docs/examples/catchment-walkthrough.md) | Worked example: build, calibrate and re-run a catchment model (runnable script in `examples/`) |
| [docs/examples/capture-zone.md](docs/examples/capture-zone.md) | Worked example: capture zone of a pumping well with MODPATH, checked against the analytical width |
| [tools.md](tools.md) | Full tool reference: inputs, outputs, error codes |
| [tasks.md](tasks.md) | Phased implementation plan with checkboxes |
| [research/capability-matrix.md](research/capability-matrix.md) | MODFLOW 6 + PEST capability coverage vs. MCP tools |
| [research/discovery/catalog.md](research/discovery/catalog.md) | Catalogue of open-source models/tutorials, capability-tagged |
| [research/holdout-registry.md](research/holdout-registry.md) | Sealed validation pool — the data itself lives in the sibling `GW-MCP-holdout/` folder, outside this repo |

---

## Licence

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

Built on the shoulders of the open groundwater modelling community:
[USGS MODFLOW](https://www.usgs.gov/mission-areas/water-resources/science/modflow-and-related-programs) ·
[FloPy](https://github.com/modflowpy/flopy) ·
[PEST++](https://github.com/usgs/pestpp) ·
[pyEMU](https://github.com/pypest/pyemu)
