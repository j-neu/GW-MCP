# groundwater-mcp

> An open-source Python MCP server for AI-assisted groundwater modelling with MODFLOW 6, FloPy, PEST++, pyEMU, and UCODE.

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

## Tools (36 total)

| Module | Tools |
|---|---|
| **docs** | `search_docs`, `search_tutorials`, `get_doc_file` |
| **parameterise** | `import_grid_from_shapefile`, `assign_top_from_raster`, `assign_k_from_zones`, `import_river_from_shapefile`, `import_obs_from_csv` |
| **model builder** | `create_model`, `set_simulation`, `add_dis_package`, `add_disv_package`, `add_npf_package`, `add_ic_package`, `add_boundary_package`, `add_oc_package`, `summarise_model`, `list_model_files` |
| **runner** | `check_model`, `run_simulation`, `get_run_log` |
| **post-processing** | `read_heads`, `read_budget`, `compute_drawdown`, `compute_water_balance`, `plot_heads_map`, `plot_cross_section` |
| **calibration (PEST++)** | `setup_pest_control`, `run_pestpp_glm`, `run_pestpp_ies`, `summarise_calibration`, `run_ies_uncertainty` |
| **calibration (UCODE)** | `setup_ucode_control`, `run_ucode`, `summarise_ucode_calibration`, `run_ucode_uncertainty` |

See [TOOLS.md](TOOLS.md) for full input/output documentation.

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
- UCODE_2014 binary (for UCODE calibration tools; download from https://geology.mines.edu/igwmc/ucode/)

---

## Project files

| File | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, module responsibilities, file structure, tech stack |
| [TOOLS.md](TOOLS.md) | Full tool reference: inputs, outputs, error codes |
| [TASKS.md](TASKS.md) | Phased implementation plan with checkboxes |

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
