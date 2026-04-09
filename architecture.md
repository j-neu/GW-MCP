# groundwater-mcp — Architecture

An open-source Python MCP server for AI-assisted groundwater modelling with MODFLOW 6, FloPy, PEST++, pyEMU, and UCODE.

---

## Overview

The server exposes 36 tools across 6 modules, running locally over stdio transport. All computation happens on the user's machine — no external API calls, no waitlist, no paywall.

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
                   rasterio /         (heads, plots) PEST++ /
                   FloPy + MF6                       UCODE
                          │               │              │
                          └───────────────┴──────────────┘
                                          │
                            local filesystem workspace
                          (model files · output · plots)
```

---

## Module responsibilities

### docs
Builds a local full-text + semantic search index from the public MODFLOW 6, FloPy, and PEST++ GitHub repositories at install time. Works fully offline. No external API required.

### parameterise
Translates processed spatial data — rasters, shapefiles, and CSVs — into MODFLOW 6 model inputs. Covers the gap between real-world data and a runnable model: building a grid from a catchment shapefile, assigning layer elevations from a DEM, distributing hydraulic conductivity from geological zone polygons, generating river/drain stress period data from a river network, and importing borehole or gauging station observations for calibration. Uses `geopandas` and `rasterio`; expects data that is already in the correct CRS and resolution — raw spatial processing is handled upstream.

### model builder
Wraps FloPy's MODFLOW 6 GWF API to create and configure models programmatically — grids, packages, boundary conditions, and output control. Manages a per-session workspace directory.

### runner
Invokes the MODFLOW 6 binary via FloPy's `run_model()`, streams stdout/stderr, and returns structured convergence status. Also runs FloPy's pre-run model checker.

### post-processing
Reads binary output files (`.hds`, `.cbb`) via `flopy.utils`, computes derived quantities (drawdown, water balance), and generates plan-view and cross-section plots as PNG files.

### calibration
Uses pyEMU to set up and run PEST++ (PESTPP-IES and PESTPP-GLM) for parameter estimation and uncertainty analysis. Also supports UCODE_2014 for model-agnostic calibration via SVD-based parameter estimation, sensitivity analysis, and MCMC/linear uncertainty quantification. Both backends are invoked as subprocesses with file-based I/O. Returns phi/SSR progress, residual statistics, and predictive uncertainty bounds.

---

## File structure

```
groundwater-mcp/
├── src/
│   └── groundwater_mcp/
│       ├── server.py           ← MCP entrypoint, tool registration
│       ├── tools/
│       │   ├── docs.py         ← search_docs, search_tutorials, get_doc_file
│       │   ├── parameterise.py ← import_grid_from_shapefile, assign_top_from_raster, assign_k_from_zones, import_river_from_shapefile, import_obs_from_csv
│       │   ├── builder.py      ← create_model, add_*_package, summarise_model
│       │   ├── runner.py       ← run_simulation, check_model, get_run_log
│       │   ├── postprocess.py  ← read_heads, read_budget, plot_*, compute_*
│       │   └── calibration.py  ← setup_pest_control, run_pestpp_*, setup_ucode_control, run_ucode_*, summarise_*
│       └── utils/
│           ├── workspace.py    ← model directory management
│           ├── plotting.py     ← shared matplotlib helpers
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
| Calibration | `pyemu`, PEST++ binaries, UCODE_2014 binary |
| Plotting | `matplotlib`, `flopy.plot` |
| Docs index | `whoosh` (full-text) + `sentence-transformers` (semantic) |
| Testing | `pytest` |
| Packaging | `uv` / `pyproject.toml` |

---

## Testing strategy

Three layers, each catching different failure modes:

| Layer | What it tests | When to run |
|---|---|---|
| **Pytest integration tests** (`tests/test_tutorial_*.py`) | Tool logic with real spatial data from `Tutorials Modelmuse/04` and `05` | Every commit (CI) |
| **MCP protocol tests** (`tests/test_mcp_protocol.py`) | JSON-RPC message handling, tool registration, error envelope schema | Every commit (CI) |
| **Manual Claude Desktop walkthrough** | Natural-language usability, tool description quality, full user journey | Before each release |

The tutorial datasets used are:

- **Tutorial 04:** `activeZone.shp` (catchment boundary), `ASTGTM2_S14W077_dem_WGS84_18S_cut_grd` (DEM), zone shapefiles — exercises the full parameterisation pipeline
- **Tutorial 05:** `chd_high.shp`, `chd_lower.shp`, `river.shp`, `wells.shp` — exercises boundary conditions, runner, and post-processing

See `TASKS.md` Phase 6 for the full test checklist.

---

## Design principles

- **Local-first.** All computation runs on the user's machine. No data leaves the environment.
- **Open source.** MIT licensed. All source code public, no closed components.
- **Composable.** Each module is independently testable and importable outside the MCP context.
- **MODFLOW 6 only (v1).** Supporting the modern standard first; legacy versions can be added later.
- **Fail loudly.** Tool errors return structured error objects with actionable messages, not silent failures.
- **Clear scope boundary.** This MCP covers model parameterisation from processed data through to calibrated results. Raw spatial preprocessing (CRS reprojection, DEM hydrological conditioning, borehole kriging, climate data processing) belongs in a companion `geodata-mcp`. The handoff format is standard files: GeoTIFF, GeoPackage/Shapefile, CSV.
