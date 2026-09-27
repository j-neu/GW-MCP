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

## Tools (89 total, plus 2 MCP prompts and 3 MCP resource templates)

| Module | Tools |
|---|---|
| **environment** | `check_environment` |
| **docs** | `search_docs`, `search_tutorials`, `get_doc_file`, `describe_package` |
| **parameterise** | `import_grid_from_shapefile`, `assign_top_from_raster`, `assign_k_from_zones`, `assign_k_from_raster`, `assign_ic_from_raster`, `assign_array_from_raster`, `import_river_from_shapefile`, `import_obs_from_csv`, `import_subsidence_observations` |
| **model builder** | `create_model`, `adopt_model`, `set_simulation`, `set_model_crs`, `add_dis_package`, `add_disv_package`, `add_disu_package`, `add_npf_package`, `add_ic_package`, `add_sto_package`, `add_csub_package`, `add_boundary_package`, `add_oc_package`, `flush_model`, `summarise_model`, `model_status`, `list_model_files`, `list_models`, `delete_model` |
| **runner** | `check_model`, `run_simulation`, `get_run_log`, `diagnose_convergence`, `validate_model`, `start_run`, `get_job_status`, `cancel_job` |
| **post-processing** | `read_heads`, `read_budget`, `compute_drawdown`, `compute_water_balance`, `diagnose_water_balance`, `export_heads_to_raster`, `export_boundaries_to_shapefile`, `export_water_balance_csv`, `read_simulated_observations`, `compare_to_observed`, `read_compaction`, `plot_subsidence`, `plot_heads_map`, `plot_cross_section` |
| **calibration (PEST++)** | `setup_calibration`, `setup_da_control`, `setup_pest_control`, `start_calibration`, `run_pestpp_glm`, `run_pestpp_ies`, `run_pestpp_da`, `summarise_calibration`, `summarise_da`, `run_ies_uncertainty`, `check_parameter_sensitivity`, `calibrate` |
| **spec / provenance** | `apply_model_spec`, `export_model_spec`, `export_reproducible_script`, `describe_model`, `export_model_report`, `clone_model`, `compare_scenarios` |

`setup_calibration` supports **zoned NPF K multipliers** (`scope="zones"`): zones auto-derived from groups of equal positive per-layer `npf:k` values become dimensionless multiplier parameters applied by a generated forward wrapper (`k = base_k × multiplier[zone]`), preserving the base K pattern while calibrating only zone magnitudes. `setup_da_control` builds a DA-ready PEST++ **version-2** control file (cycle tables + `da_*` options, IC state parameterisation) for sequential ensemble data assimilation with `run_pestpp_da`; `summarise_da` reads pestpp-da's per-cycle outputs back (per-cycle phi, posterior parameter statistics, per-cycle residuals). These capabilities add no extra tools beyond `setup_da_control` and `summarise_da`, and the total above reflects the current registration.

**CSUB (subsidence)** is covered end-to-end: `add_csub_package` builds the MODFLOW 6 CSUB package (delay and no-delay interbeds, `cg_theta`/`cg_ske_cr`, compaction observation records, filerecords), `read_compaction` and `plot_subsidence` post-process the CSUB observation output into per-layer compaction and cumulative subsidence (with an optional observed overlay), and `import_subsidence_observations` registers a measured subsidence series as a **derived** time-series target. `setup_calibration(obs_source="derived")` then calibrates `csub:packagedata` (plus `csub:cg_theta`, `csub:cg_ske_cr` and `npf:k33`) targets through `run_pestpp_ies` → `summarise_calibration`.

**v0.3.0 multi-model foundation** (2026-09-25) is in place: a single simulation can hold several models (`gwf`/`gwe`/`prt`) addressed by an optional `component` argument on the model-scoped tools, with the GWF grid mirrored into a component and its exchange registered. It ships no new tool — it is the base the **GWE** and **PRT** capability specs (with **MT3D-USGS** and **MODPATH** post-processing) build on to complete the v0.3.0 gate.

**GWE heat transport** (2026-09-25) is built: `add_gwe_model` creates a heat simulation coupled to a completed flow run through MF6's Flow Model Interface, with `add_gwe_adv/cnd/est/ssm/esl_package` for the physics, `read_temperature` and `plot_temperature_*` for post-processing, and `run_simulation` running flow then heat. The ex-gwe-radial closed-book validation is the remaining v0.3.0 gate for GWE.

**PRT particle tracking** (2026-09-27) is built: `add_prt_model` adds a MODFLOW 6 PRT model as a **same-simulation** component (the GWF grid is mirrored and a `GWF6-PRT6` exchange registered), with `add_prt_mip/prp/oc_package` for the physics, release schedule and track output, and `read_pathlines` / `plot_pathlines` for post-processing. The `ex-prt-mp7-p01` closed-book validation is the remaining v0.3.0 gate for PRT.

See [TOOLS.md](TOOLS.md) for full input/output documentation.

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

## Install

```bash
# 1. Install the package
pip install groundwater-mcp

# 2. Download MODFLOW 6 binary
get-modflow :

# 3. Download PEST++ binaries (for calibration)
get-pestpp :

# 4. Build the local docs search index
groundwater-mcp build-index
```

### Claude Desktop configuration

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "groundwater": {
      "command": "groundwater-mcp",
      "args": ["serve"]
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
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, module responsibilities, file structure, tech stack |
| [TOOLS.md](TOOLS.md) | Full tool reference: inputs, outputs, error codes |
| [TASKS.md](TASKS.md) | Phased implementation plan with checkboxes |
| [RESEARCH/capability-matrix.md](research/capability-matrix.md) | MODFLOW 6 + PEST capability coverage vs. MCP tools |
| [RESEARCH/discovery/catalog.md](research/discovery/catalog.md) | Catalogue of open-source models/tutorials, capability-tagged |
| [RESEARCH/holdout-registry.md](research/holdout-registry.md) | Sealed validation pool — the data itself lives in the sibling `GW-MCP-holdout/` folder, outside this repo |

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
