# groundwater-mcp — Implementation Tasks

Ordered build plan. Each phase produces a working, testable increment.

---

## Phase 0 — Project scaffold

- [x] Initialise repo with `uv init` and `pyproject.toml`
- [x] Add dependencies: `mcp`, `flopy`, `pyemu`, `geopandas`, `rasterio`, `scipy`, `matplotlib`, `whoosh`, `sentence-transformers`, `pytest`
- [x] Create package structure: `src/groundwater_mcp/tools/`, `src/groundwater_mcp/utils/`
- [x] Write `server.py` entrypoint: initialise MCP app, import and register all tool modules
- [x] Write `utils/workspace.py`: functions to create, resolve, and list model workspaces
- [x] Add `pyproject.toml` entry point: `groundwater-mcp = "groundwater_mcp.server:main"`
- [x] Write `README.md` with install and quickstart instructions
- [x] Set up `pytest` with a `conftest.py` fixture that creates a temp workspace
- [x] Add GitHub Actions CI: lint (`ruff`), type-check (`mypy`), test on Python 3.11+
- [x] Choose and add MIT licence

---

## Phase 1 — Model builder (`tools/builder.py`) and parameterisation (`tools/parameterise.py`)

Core dependency — everything else requires a model to exist first.

- [x] Implement `create_model`: initialise `flopy.mf6.MFSimulation` + `MFModel`, persist to workspace registry
- [x] Implement `set_simulation`: add TDIS and IMS packages with sensible defaults
- [x] Implement `add_dis_package`: wrap `ModflowGwfdis`, validate nlay/nrow/ncol vs botm shape
- [x] Implement `add_disv_package`: wrap `ModflowGwfdisv`, validate vertices and cell2d
- [x] Implement `add_npf_package`: wrap `ModflowGwfnpf`
- [x] Implement `add_ic_package`: wrap `ModflowGwfic`
- [x] Implement `add_boundary_package`: dispatch to correct FloPy class by package name; validate stress period data shape
- [x] Implement `add_oc_package`: wrap `ModflowGwfoc`
- [x] Implement `summarise_model`: introspect simulation and model objects, return structured dict
- [x] Implement `list_model_files`: walk workspace directory, return names + sizes
- [x] Write unit tests for each tool using a minimal 3-layer 10×10 model fixture
- [x] Test round-trip: create model → write files → verify `.nam` file exists on disk

### Parameterisation tools (`tools/parameterise.py`)

- [x] Write `utils/spatial.py`: shared helpers for raster sampling at cell centroids (`rasterio`), polygon-cell intersection (`geopandas`), and CRS validation
- [x] Implement `import_grid_from_shapefile`: use `flopy.utils.GridGen` to build a DISV grid from a catchment polygon shapefile; fall back to bounding-box DIS grid if `method="dis"`
- [x] Implement `assign_top_from_raster`: sample GeoTIFF at cell centroids using `rasterio`, write result to model top or botm arrays; validate CRS match against model grid
- [x] Implement `assign_k_from_zones`: spatial join of cell centroids to zone polygons via `geopandas`; write K (and optionally K33, icelltype) arrays; warn on cells outside all zones
- [x] Implement `import_river_from_shapefile`: intersect river/drain polyline shapefile with model grid; compute reach lengths; build stress period data for RIV, DRN, or SFR package; write via `add_boundary_package`
- [x] Implement `import_obs_from_csv`: read CSV, parse dates, map sites to model cells by (x, y) or site name lookup; write MODFLOW 6 OBS file; return structured observation list for use in calibration setup
- [x] Write unit tests using small synthetic fixtures: a 5-polygon zone shapefile, a 10×10 DEM GeoTIFF, and a 3-site head observation CSV

---

## Phase 2 — Runner (`tools/runner.py`)

Requires Phase 1.

- [x] Implement `check_model`: call `flopy.utils.check.MFSimulationCheck`, return structured warnings/errors
- [x] Implement `run_simulation`: call `simulation.run_simulation()`, parse return code, capture timing
- [x] Implement `get_run_log`: read `.lst` file tail, extract convergence table if present
- [x] Write helper to detect MODFLOW 6 binary path (check `$PATH`, common install locations, `get-modflow` cache)
- [x] Add `BINARY_NOT_FOUND` error with install instructions if binary missing
- [x] Write integration test: build minimal model → run → assert success and `.hds` file exists
- [x] Test `CONVERGENCE_FAILED` path: create deliberately ill-conditioned model

---

## Phase 3 — Post-processing (`tools/postprocess.py`)

Requires Phase 2.

- [x] Implement `read_heads`: open `.hds` with `flopy.utils.HeadFile`, extract array for given kstpkper + layer
- [x] Implement `read_budget`: open `.cbb` with `flopy.utils.CellBudgetFile`, filter by text label
- [x] Implement `compute_drawdown`: diff two `read_heads` calls, return array + stats
- [x] Implement `compute_water_balance`: aggregate budget by boundary type, compute net
- [x] Implement `utils/plotting.py`: shared figure setup (DPI, tight layout, temp file management)
- [x] Implement `plot_heads_map`: use `flopy.plot.PlotMapView`, contour heads, save PNG
- [x] Implement `plot_cross_section`: use `flopy.plot.PlotCrossSection`, save PNG
- [x] Write unit tests using pre-computed binary output fixtures (checked into `tests/fixtures/`)
- [x] Test plot tools: assert PNG output exists and is non-zero bytes

---

## Phase 4 — Docs module (`tools/docs.py`)

Independent of Phases 1–3; can be built in parallel.

- [x] Write `scripts/build_index.py`:
  - Clone / download MODFLOW 6 docs, FloPy docs, PEST++ docs, pyEMU docs from GitHub
  - Strip HTML/notebooks to plain text
  - Build Whoosh full-text index
  - Build sentence-transformers embedding index (model: `all-MiniLM-L6-v2`)
  - Save both indexes to `~/.groundwater-mcp/index/`
- [x] Add `build_index` as a `pyproject.toml` post-install script (implemented as `groundwater-mcp build-index` subcommand in `server.py`; core logic in `src/groundwater_mcp/index_builder.py`)
- [x] Implement `search_docs`: route to text, semantic, or hybrid search based on `method` param
- [x] Implement `search_tutorials`: filter index to notebook files, respect `complexity` metadata
- [x] Implement `get_doc_file`: read from index source files, paginate at 30 KB
- [x] Implement acronym expansion table (WEL, RIV, CHD, DRN, MAW, SFR, etc.)
- [x] Write unit tests with a minimal index fixture (10 documents)
- [x] Test semantic search: assert conceptually related queries surface correct documents

---

## Phase 5 — Calibration (`tools/calibration.py`)

Requires Phase 2. PEST++ binaries must be installed separately.

- [x] Implement `setup_pest_control`: use `pyemu.helpers.PstFrom` or manual `Pst` construction; write `.pst` file to workspace
- [x] Implement `run_pestpp_glm`: run `pestpp-glm` via subprocess, stream output, parse final phi
- [x] Implement `run_pestpp_ies`: run `pestpp-ies`, parse ensemble phi summary
- [x] Implement `summarise_calibration`: read `*.rei` residuals and `*.par` parameter files via pyEMU; compute RMSE, bias, R²
- [x] Implement `run_ies_uncertainty`: read posterior ensemble, extract forecast columns, compute percentiles
- [x] Add PEST++ binary detection (similar to MODFLOW 6 binary detection in Phase 2)
- [x] Write integration tests using a small synthetic calibration problem (2-parameter, 5-observation)
- [x] Test `summarise_calibration` output schema matches documented format


## Phase 6 — End-to-end testing (Modelmuse tutorials)

Three layers of testing using real spatial data from `Tutorials Modelmuse/04/` (DEM + catchment zones) and `Tutorials Modelmuse/05/` (CHD, river, wells shapefiles).

### Option 1 — Pytest integration tests

Calls tool functions directly in Python with tutorial data. Fast, repeatable, runs in CI without a live server.

**Tutorial 04 — spatial parameterisation pipeline:**
- [x] `import_grid_from_shapefile` with `activeZone.shp` → assert cell count > 0
- [x] `assign_top_from_raster` with `ASTGTM2_S14W077_dem_WGS84_18S_cut_grd` → assert min/max in plausible elevation range
- [x] `create_model` + `set_simulation` + `add_npf_package` + `add_ic_package` + `add_oc_package`
- [x] `run_simulation` → assert success and `.hds` file exists
- [x] `read_heads` → assert array shape matches grid, no dry cells

**Tutorial 05 — boundary condition pipeline:**
- [ ] `import_river_from_shapefile` with `river.shp` → assert reach count > 0
- [ ] `import_obs_from_csv` (or shapefile-based well import) with `wells.shp` → assert site count matches
- [ ] `add_boundary_package` CHD from `chd_high.shp` and `chd_lower.shp`
- [ ] `run_simulation` → assert convergence
- [ ] `read_heads`, `compute_water_balance`, `plot_heads_map` → assert PNG output non-empty

**Cross-cutting:**
- [x] Each step asserts its output is valid input to the next (no silent failures at boundaries)
- [x] All tests use a pytest `tmp_path` workspace fixture, not the tutorial data directory itself
- [x] Add fixture data copies to `tests/fixtures/tutorial_04/`
- [ ] Add fixture data copies to `tests/fixtures/tutorial_05/`

### Option 2 — MCP protocol tests

Sends real JSON-RPC messages to a live server instance via the `mcp` SDK test client. Tests the protocol layer and tool registration in addition to business logic.

- [ ] Add `tests/test_mcp_protocol.py` using `mcp.testing.TestClient` (or equivalent)
- [ ] Start server in-process using `mcp.server.stdio` test harness
- [ ] Replay the full tutorial 04 → 05 workflow as a sequence of `tools/call` requests
- [ ] Assert each response has no `error` key and matches the documented return schema (from `tools.md`)
- [ ] Test error paths: call `run_simulation` before `create_model` → assert `MODEL_NOT_FOUND` error envelope
- [ ] Test tool listing: assert all 36 tools appear in `tools/list` response

### Option 3 — Manual end-to-end via Claude Desktop

Highest-fidelity test of the actual user experience. Not automatable — run manually before each release.

- [ ] Connect Claude Desktop to local `groundwater-mcp` server (see `README.md` config)
- [ ] Walk through Tutorial 04 using only natural-language prompts; Claude should invoke the correct tool sequence unprompted
- [ ] Walk through Tutorial 05 end-to-end; assert heads map PNG is produced and looks plausible
- [ ] Walk through a PEST++ calibration run using Tutorial 05 wells as observations
- [ ] Document any tool calls that required reprompting or produced confusing output — feed back into tool descriptions

---

## Phase 7 — Polish and release

- [ ] Write full `README.md` with:
  - Install instructions (pip + `get-modflow` + `get-pestpp`)
  - Claude Desktop configuration snippet
  - Worked examples from the Tutorials Modelmuse folder (Tutorial 04 spatial pipeline, Tutorial 05 boundary conditions, PEST++ calibration)
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
- [ ] PEST++ sensitivity analysis tools (`pestpp-sen`)
- [ ] Cloud execution backend (submit MODFLOW jobs to AWS/GCP)
- [ ] Web-based model visualiser (optional companion app)
- [ ] `geodata-mcp` companion server (separate project): CRS reprojection, DEM hydrological conditioning, borehole kriging/IDW interpolation, climate data processing, land use ET zone derivation — produces the rasters/shapefiles/CSVs consumed by groundwater-mcp's parameterise module
