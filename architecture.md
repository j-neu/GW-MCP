# groundwater-mcp — Architecture

An open-source Python MCP server for AI-assisted groundwater modelling with MODFLOW 6, FloPy, PEST++, and pyEMU.

---

## Overview

The server exposes 26 tools across 5 modules, running locally over stdio transport. All computation happens on the user's machine — no external API calls, no waitlist, no paywall.

```
Claude / AI client
        │  MCP protocol (stdio)
        ▼
┌─────────────────────────────────────────────┐
│         groundwater-mcp  (Python)           │
│  tool dispatcher · workspace manager        │
│  error handling · logging                   │
└──┬──────┬──────┬──────┬──────┬─────────────┘
   │      │      │      │      │
 docs  builder runner  post  calib
   │      │      │      │      │
   └──────┴──────┴──────┴──────┘
                 │
   ┌─────────────┼──────────────┐
   │             │              │
FloPy +      flopy.utils    pyEMU /
MODFLOW 6    (heads, plots)  PEST++
   │             │              │
   └─────────────┴──────────────┘
                 │
     local filesystem workspace
   (model files · output · plots)
```

---

## Module responsibilities

### docs
Builds a local full-text + semantic search index from the public MODFLOW 6, FloPy, and PEST++ GitHub repositories at install time. Works fully offline. No external API required.

### model builder
Wraps FloPy's MODFLOW 6 GWF API to create and configure models programmatically — grids, packages, boundary conditions, and output control. Manages a per-session workspace directory.

### runner
Invokes the MODFLOW 6 binary via FloPy's `run_model()`, streams stdout/stderr, and returns structured convergence status. Also runs FloPy's pre-run model checker.

### post-processing
Reads binary output files (`.hds`, `.cbb`) via `flopy.utils`, computes derived quantities (drawdown, water balance), and generates plan-view and cross-section plots as PNG files.

### calibration
Uses pyEMU to set up and run PEST++ (PESTPP-IES and PESTPP-GLM) for parameter estimation and uncertainty analysis. Returns phi progress, residual statistics, and ensemble-based predictive uncertainty bounds.

---

## File structure

```
groundwater-mcp/
├── src/
│   └── groundwater_mcp/
│       ├── server.py           ← MCP entrypoint, tool registration
│       ├── tools/
│       │   ├── docs.py         ← search_docs, search_tutorials, get_doc_file
│       │   ├── builder.py      ← create_model, add_*_package, summarise_model
│       │   ├── runner.py       ← run_simulation, check_model, get_run_log
│       │   ├── postprocess.py  ← read_heads, read_budget, plot_*, compute_*
│       │   └── calibration.py  ← setup_pest_control, run_pestpp_*, summarise_*
│       └── utils/
│           ├── workspace.py    ← model directory management
│           └── plotting.py     ← shared matplotlib helpers
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
| Calibration | `pyemu`, PEST++ binaries |
| Plotting | `matplotlib`, `flopy.plot` |
| Docs index | `whoosh` (full-text) + `sentence-transformers` (semantic) |
| Testing | `pytest` |
| Packaging | `uv` / `pyproject.toml` |

---

## Design principles

- **Local-first.** All computation runs on the user's machine. No data leaves the environment.
- **Open source.** MIT licensed. All source code public, no closed components.
- **Composable.** Each module is independently testable and importable outside the MCP context.
- **MODFLOW 6 only (v1).** Supporting the modern standard first; legacy versions can be added later.
- **Fail loudly.** Tool errors return structured error objects with actionable messages, not silent failures.
