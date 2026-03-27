# groundwater-mcp

> An open-source Python MCP server for AI-assisted groundwater modelling with MODFLOW 6, FloPy, PEST++, and pyEMU.

No waitlist. No paywall. No closed components. Runs entirely on your machine.

---

## What it does

groundwater-mcp connects any MCP-compatible AI assistant (Claude, Cursor, etc.) to a full groundwater modelling stack. You can ask your AI to build a model, run it, inspect results, and calibrate parameters — all through natural language, with the actual computation happening locally via FloPy and MODFLOW 6.

```
"Build a 3-layer 20×20 model with a pumping well in the centre,
 run it for 365 days, and plot the head distribution in layer 1."
```

---

## Tools (26 total)

| Module | Tools |
|---|---|
| **docs** | `search_docs`, `search_tutorials`, `get_doc_file` |
| **model builder** | `create_model`, `set_simulation`, `add_dis_package`, `add_disv_package`, `add_npf_package`, `add_ic_package`, `add_boundary_package`, `add_oc_package`, `summarise_model`, `list_model_files` |
| **runner** | `check_model`, `run_simulation`, `get_run_log` |
| **post-processing** | `read_heads`, `read_budget`, `compute_drawdown`, `compute_water_balance`, `plot_heads_map`, `plot_cross_section` |
| **calibration** | `setup_pest_control`, `run_pestpp_glm`, `run_pestpp_ies`, `summarise_calibration`, `run_ies_uncertainty` |

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
- MODFLOW 6 binary (via `get-modflow`)
- pyemu (for calibration tools)
- PEST++ binaries (for calibration tools)

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
