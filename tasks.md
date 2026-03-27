# groundwater-mcp — Implementation Tasks

Ordered build plan. Each phase produces a working, testable increment.

---

## Phase 0 — Project scaffold

- [ ] Initialise repo with `uv init` and `pyproject.toml`
- [ ] Add dependencies: `mcp`, `flopy`, `pyemu`, `matplotlib`, `whoosh`, `sentence-transformers`, `pytest`
- [ ] Create package structure: `src/groundwater_mcp/tools/`, `src/groundwater_mcp/utils/`
- [ ] Write `server.py` entrypoint: initialise MCP app, import and register all tool modules
- [ ] Write `utils/workspace.py`: functions to create, resolve, and list model workspaces
- [ ] Add `pyproject.toml` entry point: `groundwater-mcp = "groundwater_mcp.server:main"`
- [ ] Write `README.md` with install and quickstart instructions
- [ ] Set up `pytest` with a `conftest.py` fixture that creates a temp workspace
- [ ] Add GitHub Actions CI: lint (`ruff`), type-check (`mypy`), test on Python 3.11+
- [ ] Choose and add MIT licence

---

## Phase 1 — Model builder (`tools/builder.py`)

Core dependency — everything else requires a model to exist first.

- [ ] Implement `create_model`: initialise `flopy.mf6.MFSimulation` + `MFModel`, persist to workspace registry
- [ ] Implement `set_simulation`: add TDIS and IMS packages with sensible defaults
- [ ] Implement `add_dis_package`: wrap `ModflowGwfdis`, validate nlay/nrow/ncol vs botm shape
- [ ] Implement `add_disv_package`: wrap `ModflowGwfdisv`, validate vertices and cell2d
- [ ] Implement `add_npf_package`: wrap `ModflowGwfnpf`
- [ ] Implement `add_ic_package`: wrap `ModflowGwfic`
- [ ] Implement `add_boundary_package`: dispatch to correct FloPy class by package name; validate stress period data shape
- [ ] Implement `add_oc_package`: wrap `ModflowGwfoc`
- [ ] Implement `summarise_model`: introspect simulation and model objects, return structured dict
- [ ] Implement `list_model_files`: walk workspace directory, return names + sizes
- [ ] Write unit tests for each tool using a minimal 3-layer 10×10 model fixture
- [ ] Test round-trip: create model → write files → verify `.nam` file exists on disk

---

## Phase 2 — Runner (`tools/runner.py`)

Requires Phase 1.

- [ ] Implement `check_model`: call `flopy.utils.check.MFSimulationCheck`, return structured warnings/errors
- [ ] Implement `run_simulation`: call `simulation.run_simulation()`, parse return code, capture timing
- [ ] Implement `get_run_log`: read `.lst` file tail, extract convergence table if present
- [ ] Write helper to detect MODFLOW 6 binary path (check `$PATH`, common install locations, `get-modflow` cache)
- [ ] Add `BINARY_NOT_FOUND` error with install instructions if binary missing
- [ ] Write integration test: build minimal model → run → assert success and `.hds` file exists
- [ ] Test `CONVERGENCE_FAILED` path: create deliberately ill-conditioned model

---

## Phase 3 — Post-processing (`tools/postprocess.py`)

Requires Phase 2.

- [ ] Implement `read_heads`: open `.hds` with `flopy.utils.HeadFile`, extract array for given kstpkper + layer
- [ ] Implement `read_budget`: open `.cbb` with `flopy.utils.CellBudgetFile`, filter by text label
- [ ] Implement `compute_drawdown`: diff two `read_heads` calls, return array + stats
- [ ] Implement `compute_water_balance`: aggregate budget by boundary type, compute net
- [ ] Implement `utils/plotting.py`: shared figure setup (DPI, tight layout, temp file management)
- [ ] Implement `plot_heads_map`: use `flopy.plot.PlotMapView`, contour heads, save PNG
- [ ] Implement `plot_cross_section`: use `flopy.plot.PlotCrossSection`, save PNG
- [ ] Write unit tests using pre-computed binary output fixtures (checked into `tests/fixtures/`)
- [ ] Test plot tools: assert PNG output exists and is non-zero bytes

---

## Phase 4 — Docs module (`tools/docs.py`)

Independent of Phases 1–3; can be built in parallel.

- [ ] Write `scripts/build_index.py`:
  - Clone / download MODFLOW 6 docs, FloPy docs, PEST++ docs, pyEMU docs from GitHub
  - Strip HTML/notebooks to plain text
  - Build Whoosh full-text index
  - Build sentence-transformers embedding index (model: `all-MiniLM-L6-v2`)
  - Save both indexes to `~/.groundwater-mcp/index/`
- [ ] Add `build_index` as a `pyproject.toml` post-install script
- [ ] Implement `search_docs`: route to text, semantic, or hybrid search based on `method` param
- [ ] Implement `search_tutorials`: filter index to notebook files, respect `complexity` metadata
- [ ] Implement `get_doc_file`: read from index source files, paginate at 30 KB
- [ ] Implement acronym expansion table (WEL, RIV, CHD, DRN, MAW, SFR, etc.)
- [ ] Write unit tests with a minimal index fixture (10 documents)
- [ ] Test semantic search: assert conceptually related queries surface correct documents

---

## Phase 5 — Calibration (`tools/calibration.py`)

Requires Phase 2. PEST++ binaries must be installed separately.

- [ ] Implement `setup_pest_control`: use `pyemu.helpers.PstFrom` or manual `Pst` construction; write `.pst` file to workspace
- [ ] Implement `run_pestpp_glm`: run `pestpp-glm` via subprocess, stream output, parse final phi
- [ ] Implement `run_pestpp_ies`: run `pestpp-ies`, parse ensemble phi summary
- [ ] Implement `summarise_calibration`: read `*.rei` residuals and `*.par` parameter files via pyEMU; compute RMSE, bias, R²
- [ ] Implement `run_ies_uncertainty`: read posterior ensemble, extract forecast columns, compute percentiles
- [ ] Add PEST++ binary detection (similar to MODFLOW 6 binary detection in Phase 2)
- [ ] Write integration tests using a small synthetic calibration problem (2-parameter, 5-observation)
- [ ] Test `summarise_calibration` output schema matches documented format

---

## Phase 6 — Polish and release

- [ ] Write full `README.md` with:
  - Install instructions (pip + `get-modflow` + `get-pestpp`)
  - Claude Desktop configuration snippet
  - 3 worked examples (simple steady-state, transient pumping test, PEST++ calibration)
- [ ] Add `CONTRIBUTING.md`
- [ ] Add `CHANGELOG.md`
- [ ] Set up issue templates on GitHub (bug report, feature request)
- [ ] Publish to PyPI: `uv build && uv publish`
- [ ] Submit to MCP server registry / Anthropic directory
- [ ] Post to MODFLOW forum and FloPy GitHub discussions

---

## Future / stretch goals

- [ ] MODFLOW-2005 and MODFLOW-NWT support (via FloPy legacy API)
- [ ] MT3D-USGS solute transport post-processing
- [ ] MODPATH particle tracking tools
- [ ] QGIS / GeoPandas spatial preprocessing tools (clip rasters, interpolate to grid)
- [ ] Cloud execution backend (submit MODFLOW jobs to AWS/GCP)
- [ ] PEST++ sensitivity analysis tools (`pestpp-sen`)
- [ ] Web-based model visualiser (optional companion app)
