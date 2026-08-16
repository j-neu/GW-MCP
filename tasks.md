# groundwater-mcp — Path to Launch

**End goal:** A usable, publicly accessible MCP server that GW professionals and AI tools can reliably use to create, calibrate, and visualize groundwater flow models.

**Status:** Core implementation 100% complete. Testing: Layers 1–2 complete (233 passing incl. holdout replay), Layer 3 (manual E2E) complete via Mode B closed-book sessions (dry-run + rerun-2/3/4, 0 reprompts each; rerun-4 = set-and-forget run, zero permission prompts, best calibration fit); Mode A holdout replay green. Release 0% complete.

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
**561 LOC (builder.py) + 706 LOC (parameterise.py)**

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
**538 LOC (postprocess.py)**

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
**431 LOC (docs.py)**

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
**847 LOC (calibration.py)**

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

## COMPLETE — Phase 6 (End-to-End Testing with Real Data)

**Goal:** Three layers of testing using real ModelMuse tutorial data (DEM, catchment zones, boundary conditions, observations).
**Status:** All layers exercised and green. Layer 1 = pytest integration, Layer 2 = MCP protocol + Mode A holdout replay, Layer 3 = Mode B manual closed-book sessions (dry-run 1 + rerun-2/3/4, 0 reprompts each). Rerun-4 (2026-08-16) closed out the post-fix verification: fixed MCP calibration chain used end-to-end, best fit to date, zero permission prompts (set-and-forget run).

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
- [x] Tool listing: assert all 39 tools present, have descriptions + inputSchema
- [x] Response format: TextContent, valid JSON, no error key on success
- [x] Error paths: MODEL_NOT_FOUND for run/read before create
- [x] Multi-step workflow: create → grid → DEM → run → read_heads via MCP layer
- [x] import_river_from_shapefile via MCP layer (Tutorial 05 river.shp)

### Holdout replay (Mode A, dry-run COMPLETE ✅ — official run at v0.1.0 freeze)
- [x] `tests/test_holdout_replay.py` — 7 tests, all passing (build → check → run →
      postprocess for test051_uzfp2 + test020_NevilleTonkinTransient; GAP tools not
      exposed; clean failure envelope for unsupported boundaries; sealed DISU project
      has no tool path). Found & fixed pre-existing bugs: noptmax routed into pestpp
      `++` section, `compute_water_balance` summing plain-array FLOW-JA-FACE,
      `test_calibration.py` fixture missing k33. Full suite: 232 passed.
      Details: `research/discovery/sessions/2026-08-15-modeA-dryrun.md`.

### Layer 3 — Manual E2E (Mode B COMPLETE ✅ via closed-book Kilo sessions)
Mode B replaces the Claude Desktop walkthrough: a human-graded natural-language
session against a held-out tutorial (`modeB/tutorial05`) with no source/PDF/
reference-model access. Sessions logged in `research/discovery/sessions/`:
- [x] Dry-run 1 (`2026-08-15-modeB-tutorial05.md`): journey completed, 0 reprompts,
      build/run/postprocess pass, calibration partial (MCP chain bugs found).
- [x] Rerun-2 (`2026-08-15-modeB-tutorial05-rerun2.md`): closed-book, 0 reprompts,
      full journey incl. calibration (K 10 → 8.1 m/d, phi 1190, RMSE 6.4 m) — but
      only by bypassing the broken MCP calibration chain (pyemu-built PST + direct
      pestpp). ~45 of 65 min spent fighting tool bugs.
- [x] Fixes from rerun-2 applied 2026-08-16 (see `Mode B rerun-2 fixes` under 7d):
      obs alignment, model command, SAVE_FLOWS, overwrite warning, docs autobuild,
      `view_image`, water-balance per-record split, Windows calibration-chain test.
- [x] Rerun-3 (`2026-08-16-modeB-tutorial05-rerun3.md`): closed-book, 0 reprompts,
      MCP calibration chain used as-is and passed (K → 0.51 m/d, phi 1168.5,
      RMSE 6.35 m). Time lost to permission prompts (workspace outside session
      folder) + wrong-environment checks.
- [x] Set-and-forget fixes applied 2026-08-16: `check_environment` preflight tool
      (38th tool), `.groundwater-mcp\**` permission allow-list, `create_model`
      workspace guidance, holdout `activeZone.shp` sidecar staging fix, runbook
      preflight section + prompt line.
- [x] Rerun-4 (`2026-08-16-modeB-tutorial05-rerun4.md`): closed-book, 0 reprompts,
      ~29 min, **zero permission prompts** — the hands-free run. Build/run/
      postprocess pass; calibration via the fixed MCP chain
      (`setup_pest_control → run_pestpp_glm → summarise_calibration`) → K=36.28
      m/d, phi 803.6, RMSE 5.26 m, bias +0.49 m — best fit across all reruns.
      Agent had to discover PEST++ mechanics (template token width, derinclb,
      local-minimum trap) — backlog items below.
- [ ] Remaining Layer-3 follow-ups: none blocking — post-fix verification complete
      via rerun-4. Optional: Claude Desktop / other client walkthrough (Mode B is
      the recorded protocol).

### Concrete next steps for Phase 6:
1. ✅ Write `tests/test_tutorial_05.py` — 26 tests, all passing
2. ✅ Copy Tutorial 05 fixture files to `tests/fixtures/tutorial_05/`
3. ✅ Implement MCP protocol test harness + full workflow replay — 24 tests, all passing
4. ✅ Mode A holdout replay harness + dry-run — 7 tests, all passing (official run at freeze)
5. ✅ Mode B manual Layer-3 sessions (dry-run 1 + closed-book rerun-2/3/4) — 0 reprompts each
6. ✅ Re-run Mode B tutorial 05 against the fixed calibration chain (post-fix verification) — rerun-4 (2026-08-16), best fit (K=36.28, RMSE 5.26 m), zero permission prompts

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
- [ ] Add `CHANGELOG.md` (0.1.0: initial release with 39 tools across 7 modules)
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

**v0.2.0 build order (from capability matrix + discovery catalog, 2026-08-15):**
Ordered by user priority (DISU first) then demonstrated demand = capability
frequency in the catalog. Each item validates against the corresponding
held-out example (promoted to dev/test data AFTER the v0.1.0 release).
Refs point at `research/discovery/catalog.md` rows.
- [ ] DISU (fully unstructured grid) support — `add_disu_package`; refs: test009_3lay-disu, ex-gwf-radial
- [ ] MAW / UZF / LAK packages — extend boundary dispatch or new tools; refs: test020, test051_uzfp2, test045_lake1ss, ex-gwf-sagehen, mf6-training
- [ ] GNC (ghost-node) + MVR (water mover); refs: test006_gwf3_gnc, test001g_MVR, ex-gwf-lak-p02
- [ ] GWT (transport) + GWF-GWT coupling — new model types; refs: ex-gwt-keating, ex-gwt-mt3dms-p01, test201_gwtbuy-henryCHD
- [x] STO (storage) exposure — `add_sto_package` *(done 2026-08-16, pulled forward into the v0.1.0 gate)*
- [ ] pestpp-sen sensitivity analysis (+ pareto/sweep modes); refs: usgs/pestpp mf6_freyberg, neversink_workflow
- [ ] OBS package tool — `add_obs_package` to complete the partial OBS row; refs: test005_advgw_tidal, ex-gwf-radial
- [ ] Note: SWT has no MF6 SWT6 package — variable density is the GWT hydraulic-head formulation (henry/saltlake/BUY); no SWT-specific tool planned unless demand emerges (verify `MODFLOW-USGS/swtv4` first)
- [ ] GWE (energy transport) + PRT (particle tracking) + CSUB — catalogued as extra scope (not matrix rows)

**Other v0.2.0 candidates (pre-existing):**
- [ ] MT3D-USGS solute transport post-processing (read transport output, plot plumes)
- [ ] MODPATH particle tracking tools (backward/forward tracking, pathlines)
- [ ] MODFLOW-2005 + MODFLOW-NWT support (legacy compatibility)
- [ ] Cloud execution backend (submit jobs to AWS/GCP Compute, stream results)
- [ ] Web-based model visualiser (optional companion app for 3D inspection)

**Validation backlog (Mode B rerun-4, 2026-08-16; see research/discovery/sessions/2026-08-16-modeB-tutorial05-rerun4.md):**
- [ ] PEST++ template token width: `@k@` (3-char token) truncates every substituted value to `1.0` (pestpp formats to fixed token width, `model_interface.cpp::cast_to_fixed_len_string`) → zero Jacobian that looks like "calibration doesn't work". Document in `setup_pest_control` / tools.md: template params must use wide fixed-width tokens (`@          k          @`).
- [ ] `derinclb` default of 0.0 gives a zero relative derivative increment → zero Jacobian. Set a sensible nonzero default when building the parameter group in `setup_pest_control`.
- [ ] GLM local-minimum trap: from K=1 the single-start gradient method converged to K=0.074 (phi 1932) while the global basin is K≈35 (phi 803); empirical phi sweep needed. Consider recommending pestpp-ies or multiple GLM starts when a run stalls.
- [x] MODFLOW 6 model-name length limit (16 chars): `tutorial05_catchment` failed at run time, not at `create_model`. Validate name length in `create_model` and fail early with a clear error. *(done 2026-08-16)*
- [ ] `plot_heads_map` writes the PNG to the process CWD (`data/`) instead of the model workspace; make `output_file` default to the workspace.
- [ ] `check_environment` reports ucode_2014 missing on this machine (unused — note only).

**Validation backlog (Mode B dry-run 1, 2026-08-15; see research/discovery/sessions/2026-08-15-modeB-tutorial05.md):**
- [x] fix `setup_pest_control` model command: `model_command_line` in pestpp_options is silently dropped by pyemu 1.4.0 (attribute is `model_command`, a list) → PST written with default `model.bat` which doesn't exist → every PEST++ forward run fails *(fixed 2026-08-16)*
- [x] write relative tpl/ins paths into the PST (absolute paths with spaces are rejected by pestpp-glm "wrong number of tokens") *(fixed 2026-08-16)*
- [ ] make `run_pestpp_glm` resilient to the 60 s MCP client timeout (async/streaming or documented direct-invocation fallback) *(Tier 2 deferred — see below)*
- [ ] write `phi.actual.csv` (or return phi progress) when GLM aborts at parameter bounds — currently `summarise_calibration` gets empty progress
- [ ] CHD/WEL shapefile importers (cell mapping currently needs server-internal helpers); document `stress_period_data` record format in tool descriptions
- [x] document `import_river_from_shapefile` polygon handling (stage 0, conductance = overlap perimeter — acts as a strong drain) *(fixed 2026-08-16: documented defaults + added `stage_raster`/`stage_offset` options)*

**Mode B rerun-2 fixes (applied 2026-08-16; see `.kilo/plans/2026-08-15-modeB-lessons-and-mcp-fixes.md`):**
- [x] `setup_pest_control` obs-to-instruction alignment: obs_data keys must match instruction-file tokens; raise instead of silently dropping (was n_observations=0)
- [x] `add_boundary_package` writes SAVE FLOWS by default (`save_flows` option) so CHD/WEL/GHB/RIV fluxes appear in `compute_water_balance`
- [x] re-adding a package of the same type returns a warning instead of silently overwriting
- [x] `search_docs` auto-builds the docs index on first call (background) instead of returning INDEX_NOT_BUILT with no help
- [x] `compute_water_balance` splits positive/negative flows per budget record (CHD now reports inflow+outflow separately)
- [x] `view_image` tool (37th tool) so `plot_heads_map` output can be visually verified by the agent
- [x] `check_environment` tool (38th tool) so a session can verify the server's own Python/packages/executables in one call instead of probing with shell commands
- [x] `import_river_from_shapefile` stage-from-DEM option (`stage_raster` + `stage_offset`)
- [x] documented 0-based cellid + stress-period semantics in `add_boundary_package` description
- [x] integration test `test_integration_full_calibration_chain_windows` (paths with spaces, Windows cmd quirks)

### ✅ Phase 6c — Transient support + expanded validation gate (v0.1.0, 2026-08-16)

Gating step added after the Phase 6 review (transient build-from-scratch was
silently running as steady state — no STO tool, no warning). See
`.kilo/plans/2026-08-16-transient-support-and-validation-gate.md`.

- [x] `add_sto_package` tool (39th tool): iconvert/ss/sy + 0-based steady/transient period control; sy required when convertible cells exist
- [x] transient-without-STO guard: `check_model` + `run_simulation` return a loud warning when a multi-time-step model has no STO (steady-state multi-period models still run)
- [x] `summarise_model` reports `storage` (STO steady/transient periods)
- [x] `create_model` rejects names > 16 chars (MODFLOW 6 MODELNAME cap) with a clear error
- [x] transient integration tests (`tests/test_integration_transient.py`): heads evolve across time steps, water balance includes STO terms, guard warns, PEST++ calibration chain on a transient model
- [x] holdout Mode A replay now replays STO for test051/test020; STO removed from the GAP list
- [x] holdout Round-2 selections: test005_advgw_tidal (25-period multi-BC + OBS + time series; TS-driven BCs not replayable at v0.1.0 → synthetic CHD, documented deviation) and mf6_freyberg (usgs/pestpp TM7C26) adopted + full MCP calibration chain (setup_pest_control → run_pestpp_glm → summarise_calibration, 6 welflx params + 10 head obs)
- [x] `read_budget`/`compute_water_balance` accept `.cbc` budget files (freyberg writes `.cbc`, not `.cbb`)
- [x] 39-tool suite green; tools.md / README / architecture / capability-matrix / holdout-registry updated

**Tier 2 deferred (v0.2.0 design items from the rerun-2 plan, not yet started):**
- [ ] async `run_pestpp_glm`/`run_pestpp_ies` with a status/poll tool (client-side 60 s MCP timeout currently aborts long runs even though the run completes server-side)

**Companion tool (separate repo, planned dependency):**
- [ ] `geodata-mcp`: CRS reprojection, DEM hydrological conditioning, borehole kriging, climate data processing, land use ET zones
  - Fills the gap between "raw GIS data" and "processed inputs ready for groundwater-mcp"
  - Interface: standard files (GeoTIFF, GeoPackage/Shapefile, CSV)
  - Reduces data prep friction for new users

---

## Success Criteria (Definition of "Done")

**Minimum viable product (v0.1.0):**
- [x] All 39 tools implemented and unit-tested
- [x] Tutorial 04 integration test passing (grid → dem → npf/ic/oc → run → read_heads)
- [x] Tutorial 05 integration test passing (river → obs → chd → run → water_balance → plot)
- [x] MCP protocol test passing (tool listing, error handling, round-trip message flow)
- [x] Mode A holdout replay green (dry-run; official run at the freeze)
- [x] Mode B manual Layer-3 sessions completed (dry-run 1 + closed-book rerun-2/3/4, 0 reprompts each)
- [x] Mode B tutorial 05 re-run against the fixed calibration chain (post-fix verification) — rerun-4 (2026-08-16): clean `setup_pest_control → run_pestpp_glm → summarise_calibration`, K=36.28 m/d, RMSE 5.26 m; set-and-forget run (zero permission prompts, ~29 min)
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
| **0–5** | Core implementation (39 tools, unit tests) | ~40 days actual | ✅ Complete |
| **6a** | Tutorial 05 integration test + MCP protocol test + Mode A holdout replay | 4–5 days | ✅ Complete |
| **6b** | Mode B manual Layer-3 sessions (dry-run + closed-book rerun-2/3/4) + rerun-2/rerun-4 fixes + `check_environment` | 1–2 days | ✅ Complete (rerun-4 = post-fix verification, zero permission prompts) |
| **6c** | Transient support (STO) + expanded validation gate (test005 + freyberg holdout rounds) | 1–2 days | ✅ Complete (2026-08-16; `add_sto_package`, guard, 39 tools, all green) |
| **7a** | Documentation (README expansion, guides, examples) | 2–3 days | ⏳ To do |
| **7b** | CI/CD setup (GitHub Actions, PyPI publish) | 1–2 days | ⏳ To do |
| **7c** | Public release (tagging, registry submission, outreach) | 1 day | ⏳ To do |

**Critical path to launch:** 7a → 7c (7–10 days of focused work)

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
