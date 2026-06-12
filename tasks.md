# groundwater-mcp — Path to Launch

**End goal:** A usable, publicly accessible MCP server that GW professionals and AI tools can reliably use to create, calibrate, and visualize groundwater flow models.

**Status:** Core implementation 100% complete. Testing 70% complete. Release 0% complete.

---

## COMPLETED — Phase 0 through 5 (Core Build)

### ✅ Phase 0 — Project scaffold
All foundational infrastructure in place:
- Repo structure: `src/groundwater_mcp/` with 6 tool modules, `utils/`, `scripts/`, `tests/`
- Entry point: `groundwater-mcp serve` (MCP stdio) + `groundwater-mcp build-index` (CLI)
- `pyproject.toml`: Python 3.11+, uv build system, dev tools (pytest, ruff, mypy)
- CI: GitHub Actions set up for lint + type-check (not yet running tests)
- Dependencies: All critical packages specified and lockfile generated

**Deliverables:** 3 code files (pyproject.toml, server.py, index_builder.py) + CI config

---

### ✅ Phase 1 — Model builder + parameterisation
**535 LOC (builder.py) + 671 LOC (parameterise.py)**

**Model builder (builder.py):**
- `create_model`: initialises MFSimulation + MFModel, persists to workspace registry
- `set_simulation`: adds TDIS + IMS packages with sensible complexity defaults
- `add_dis_package`: wraps ModflowGwfdis, validates grid dimensions
- `add_disv_package`: wraps ModflowGwfdisv, validates vertices/cell2d
- `add_npf_package`, `add_ic_package`, `add_oc_package`: property and output control
- `add_boundary_package`: dispatch by package name (CHD, WEL, RIV, DRN, RCH, EVT, GHB, SFR)
- `summarise_model`, `list_model_files`: introspection + metadata

**Parameterisation (parameterise.py):**
- `import_grid_from_shapefile`: builds DISV grid from catchment polygon (GridGen) or bounding-box DIS
- `assign_top_from_raster`: samples GeoTIFF at cell centroids via rasterio
- `assign_k_from_zones`: spatial join cell centroids to zone polygons (geopandas)
- `import_river_from_shapefile`: intersects river polyline with grid, computes reach lengths
- `import_obs_from_csv`: parses dates, maps observation sites to cells, writes OBS file

**Tests:** Unit tests + round-trip fixture (create → write → verify on disk)

**Status:** 100% feature-complete, all tools tested with synthetic fixtures

---

### ✅ Phase 2 — Runner
**262 LOC (runner.py)**

- `check_model`: calls FloPy model checker, returns structured warnings/errors
- `run_simulation`: invokes MODFLOW 6 binary via FloPy, captures timing + convergence
- `get_run_log`: reads .lst file, extracts convergence table
- MODFLOW 6 binary detection: checks $PATH, common install locations, `get-modflow` cache
- Error handling: `BINARY_NOT_FOUND` with install instructions

**Tests:** Integration tests (build → run → verify .hds exists), convergence failure paths

**Status:** 100% feature-complete, binary detection robust

---

### ✅ Phase 3 — Post-processing
**467 LOC (postprocess.py)**

- `read_heads`: opens .hds file, extracts array for given kstpkper + layer
- `read_budget`: opens .cbb file, filters by text label
- `compute_drawdown`: diff two head snapshots, return array + stats
- `compute_water_balance`: aggregate budget by boundary type, compute net
- `plot_heads_map`: FloPy PlotMapView, contour heads, save PNG
- `plot_cross_section`: FloPy PlotCrossSection, save PNG
- `utils/plotting.py`: shared figure setup (DPI, tight layout, temp file management)

**Tests:** Unit tests with pre-computed binary fixtures, PNG output validation

**Status:** 100% feature-complete, all post-processing tools tested

---

### ✅ Phase 4 — Docs module
**387 LOC (docs.py)**

- `search_docs`: text/semantic/hybrid search (Whoosh + sentence-transformers)
- `search_tutorials`: filter index to notebook files, respect `complexity` metadata
- `get_doc_file`: read from index source files, paginate at 30 KB
- `build_index` subcommand: clones MODFLOW 6, FloPy, PEST++, pyEMU docs from GitHub at install time
- Acronym expansion table (WEL, RIV, CHD, DRN, MAW, SFR, etc.)
- Full offline capability — no external API required

**Tests:** Unit tests with minimal index fixture (10 documents), semantic search validation

**Status:** 100% feature-complete, offline search fully working

---

### ✅ Phase 5 — Calibration (PEST++ + UCODE)
**697 LOC (calibration.py)**

**PEST++ (via pyEMU):**
- `setup_pest_control`: build .pst control file via PstFrom or manual Pst
- `run_pestpp_glm`: linear regression calibration, parse final phi
- `run_pestpp_ies`: iterative ensemble smoother, parse ensemble phi
- `summarise_calibration`: read .rei + .par files, compute RMSE/bias/R²
- `run_ies_uncertainty`: extract forecast ensemble, compute percentiles
- PEST++ binary detection

**UCODE_2014 (via pyEMU):**
- `setup_ucode_control`: build UCODE main input file (.#ucode)
- `run_ucode`: SVD-based parameter estimation
- `summarise_ucode_calibration`: SSR progress, parameter confidence intervals, sensitivity matrix
- `run_ucode_uncertainty`: linear + MCMC uncertainty bounds

**Tests:** Integration tests with small synthetic 2-parameter / 5-observation problem

**Status:** 100% feature-complete, dual-engine calibration framework validated

---

## IN PROGRESS — Phase 6 (End-to-End Testing with Real Data)

**Goal:** Three layers of testing using real ModelMuse tutorial data (DEM, catchment zones, boundary conditions, observations).

### Data inventory
- **Tutorial 04** (spatial parameterisation): `activeZone.shp` (catchment), `dem_clipped.tif` (DEM, EPSG:32718)
- **Tutorial 05** (boundary conditions): `river.shp`, `wells.shp`, `chd_high.shp`, `chd_lower.shp` (all UTM 18S)
- Status: Fixtures copied to `tests/fixtures/tutorial_04/` + `05/` (copies on disk, CI independent)

### Layer 1 — Pytest integration tests (COMPLETE ✅)
✅ Tutorial 04 pipeline (`test_tutorial_04.py`):
- [x] `import_grid_from_shapefile` with activeZone.shp → assert cell count > 0
- [x] `assign_top_from_raster` with DEM → assert plausible elevation range
- [x] `create_model` + `set_simulation` + add NPF/IC/OC/CHD packages
- [x] `run_simulation` → assert success + .hds exists (skip if mf6 not installed)
- [x] `read_heads` → assert array shape matches grid

✅ Tutorial 05 pipeline (`test_tutorial_05.py`) — **26 tests, all passing**:
- [x] `import_river_from_shapefile` with river.shp → assert reach count > 0
- [x] `import_obs_from_csv` with synthetic wells CSV → assert site count = 29
- [x] `add_boundary_package` CHD from chd_high.shp + chd_lower.shp (spatial join)
- [x] `add_boundary_package` WEL from wells.shp (point → nearest cell)
- [x] `run_simulation` → assert convergence
- [x] `read_heads`, `compute_water_balance`, `plot_heads_map` → assert outputs valid

### Layer 2 — MCP protocol tests (COMPLETE ✅)
In-process FastMCP API tests (mcp.list_tools / mcp.call_tool):
- [x] `tests/test_mcp_protocol.py` — 24 tests, all passing
- [x] Tool listing: assert all 36 tools present, have descriptions + inputSchema
- [x] Response format: TextContent, valid JSON, no error key on success
- [x] Error paths: MODEL_NOT_FOUND for run/read before create
- [x] Multi-step workflow: create → grid → DEM → run → read_heads via MCP layer
- [x] import_river_from_shapefile via MCP layer (Tutorial 05 river.shp)

### Layer 3 — Manual Claude Desktop E2E (NOT STARTED)
Highest-fidelity test of actual user experience:
- [ ] Connect Claude Desktop to local server (config + run)
- [ ] Tutorial 04 using only natural-language prompts → assert correct tool sequence
- [ ] Tutorial 05 end-to-end → assert heads map PNG produced + plausible
- [ ] PEST++ calibration walkthrough with Tutorial 05 wells as observations
- [ ] Document any tool calls requiring reprompting → feed back into descriptions

### Concrete next steps for Phase 6:
1. Write `tests/test_tutorial_05.py` (copy template from tutorial_04, adapt for 05 data) — **1–2 hours**
2. Copy Tutorial 05 fixture files to `tests/fixtures/tutorial_05/` — **0.5 hours**
3. Implement MCP protocol test harness + full workflow replay — **3–4 hours**
4. Manual Claude Desktop walkthrough (best after #3 is passing) — **2–3 hours per run**

---

## TODO — Phase 7 (Polish, Release, Dissemination)

### 7a — Documentation & Examples
**Goal:** Users can install, configure, and run a worked example in 10 minutes.

Detailed yet clear:
- [ ] Expand README.md with:
  - Installation checklist: pip install → get-modflow → get-pestpp → build-index (copy steps from docs.py/runner.py code)
  - Claude Desktop config snippet + screenshot of configured state
  - Quick-start: Tutorial 04 worked example (5 steps: create → grid → dem → npf/ic/oc → run)
  - Worked example: Tutorial 05 with boundary conditions + water balance output
  - Worked example: PEST++ calibration walkthrough (setup_pest_control → run_pestpp_glm → summarise_calibration)
  - Expected output screenshots (heads map contours, water balance table, calibration phi plot)
  - Troubleshooting: common errors (binary not found, CRS mismatch, convergence failure)

- [ ] Add `CONTRIBUTING.md` (fork, test, PR, code style: ruff format + mypy strict)
- [ ] Add `CHANGELOG.md` (0.1.0: initial release with 36 tools across 6 modules)
- [ ] Add GitHub issue templates: bug report (tool name, error code, reproducible example), feature request (problem, desired behavior, use case)

### 7b — CI/CD & Packaging
**Goal:** Automated testing on each push; one-click publish to PyPI.

- [ ] GitHub Actions: Run pytest on Python 3.11, 3.12, 3.13 (create empty mf6 stub if binary not available)
- [ ] GitHub Actions: Run ruff lint + mypy type-check on every PR
- [ ] GitHub Actions: Build + publish to PyPI on tagged release (`uv publish --token $PYPI_TOKEN`)
- [ ] PyPI metadata: package description, keywords (MODFLOW, MCP, groundwater, calibration, PEST++, UCODE), classifier tags (Topic :: Scientific/Engineering, Environment :: Console)

### 7c — Public Release
**Goal:** Software is discoverable, trustworthy, and easy to use.

Broad audience:
- [ ] Tag repo as v0.1.0 → trigger PyPI publish via GitHub Actions
- [ ] Update README.md with shield badges: `[PyPI version](link)`, `[license](link)`, `[CI status](link)`
- [ ] Register with MCP server registry / Anthropic directory (link from anthropic.com or MCP hub)
- [ ] Post to MODFLOW forum (USGS MODFLOW mail list): "New open-source MCP for MODFLOW 6 + PEST++ / UCODE"
- [ ] Post to FloPy GitHub discussions: "MCP server for AI-assisted MODFLOW 6 workflows"
- [ ] Optional: Tweet from @j-neu account linking to repo + PyPI

### 7d — Beyond v0.1.0 (Post-Launch Roadmap)

**Immediate feedback loop (weeks 1–4 after launch):**
- [ ] Monitor GitHub issues: triage, respond, fix critical bugs within 48 hours
- [ ] Log user feedback: common workflows, usability friction, missing features
- [ ] Update tool descriptions based on real usage patterns

**v0.2.0 improvements (if demand warrants):**
- [ ] MT3D-USGS solute transport post-processing (read transport output, plot plumes)
- [ ] MODPATH particle tracking tools (backward/forward tracking, pathlines)
- [ ] MODFLOW-2005 + MODFLOW-NWT support (legacy compatibility)
- [ ] PEST++ sensitivity analysis tools (pestpp-sen)
- [ ] Cloud execution backend (submit jobs to AWS/GCP Compute, stream results)
- [ ] Web-based model visualiser (optional companion app for 3D inspection)

**Companion tool (separate repo, planned dependency):**
- [ ] `geodata-mcp`: CRS reprojection, DEM hydrological conditioning, borehole kriging, climate data processing, land use ET zones
  - Fills the gap between "raw GIS data" and "processed inputs ready for groundwater-mcp"
  - Interface: standard files (GeoTIFF, GeoPackage/Shapefile, CSV)
  - Reduces data prep friction for new users

---

## Success Criteria (Definition of "Done")

**Minimum viable product (v0.1.0):**
- [x] All 36 tools implemented and unit-tested
- [x] Tutorial 04 integration test passing (grid → dem → npf/ic/oc → run → read_heads)
- [ ] Tutorial 05 integration test passing (river → obs → chd → run → water_balance → plot)
- [ ] MCP protocol test passing (tool listing, error handling, round-trip message flow)
- [ ] Manual Claude Desktop walkthrough completed (both tutorials + calibration)
- [ ] README + CONTRIBUTING + CHANGELOG documentation in place
- [ ] PyPI package published and installable
- [ ] MCP registry + MODFLOW/FloPy community notified

**User-facing success metrics (after launch):**
- GW professionals can build a calibrated model from spatial data in one session (< 2 hours)
- Queries to MODFLOW forum / FloPy discussions reference this tool
- GitHub repo gets 50+ stars within 3 months
- At least one peer-reviewed GW publication cites or uses this tool

---

## Implementation Timeline Estimate

| Phase | Scope | Effort | Status |
|---|---|---|---|
| **0–5** | Core implementation (36 tools, unit tests) | ~40 days actual | ✅ Complete |
| **6a** | Tutorial 05 integration test + MCP protocol test | 4–5 days | ⏳ In progress |
| **6b** | Manual Claude Desktop walkthrough | 1 day (after 6a) | ⏳ Blocked on 6a |
| **7a** | Documentation (README expansion, guides, examples) | 2–3 days | ⏳ To do |
| **7b** | CI/CD setup (GitHub Actions, PyPI publish) | 1–2 days | ⏳ To do |
| **7c** | Public release (tagging, registry submission, outreach) | 1 day | ⏳ To do |

**Critical path to launch:** 6a → 6b → 7a → 7c (8–10 days of focused work)

---

## Notes for Developers

### Architecture decisions (frozen for v0.1.0)
- **MODFLOW 6 only:** No legacy (2005, NWT) support yet. v0.2.0 candidate.
- **Local execution only:** No cloud backend in v0.1.0. Cloud job submission is v0.2.0 candidate.
- **Dual calibration engines:** PEST++ (primary) + UCODE (secondary). Both mature, community-trusted.
- **Offline docs:** Full MODFLOW/FloPy/PEST++ search indexed at install time. No external API calls.

### Testing philosophy
- **Layer 1 (unit):** Fast, isolated, synthetic fixtures. Runs in CI.
- **Layer 2 (integration):** Real spatial data (ModelMuse tutorials). Skipped if MODFLOW 6 binary not present. Runs in CI (stub binary fallback possible).
- **Layer 3 (manual):** Human-validated UX. Run before each release.

### Code quality guardrails
- ruff lint + mypy type-check enforced on every PR
- All tool input/output must match schema in tools.md (no surprise keys)
- Error return format: `{"error": true, "code": "ENUM", "message": "...", "suggestion": "..."}`
- No external API calls. All I/O via local filesystem or subprocesses.

### Community engagement (ongoing)
- Respond to issues within 48 hours
- Accept PRs for bug fixes + documentation
- Link to `geodata-mcp` once ready (companion tool for spatial preprocessing)
