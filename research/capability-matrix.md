# Capability Matrix — MODFLOW 6 + PEST coverage in groundwater-mcp

Row schema:
`capability (package/process/mode) | MCP status today (covered | partial | gap | legacy-out-of-scope) | covering tool(s) | catalog example refs | notes`

Status verified against `tools.md` + tool module source on 2026-08-15
(`src/groundwater_mcp/tools/`, 37 tools across 6 modules; `check_environment`
added 2026-08-16 → 38 tools across 7 modules; `add_sto_package` added
2026-08-16 → 39 tools; `adopt_model` added 2026-08-17 → 40 tools; the 4 UCODE
stub tools removed 2026-08-17 — UCODE is no longer part of the project's
calibration scope — → 36 tools; `flush_model` added 2026-08-17 (7f-E1.2) →
37 tools; `read_simulated_observations` + `compare_to_observed` added
2026-08-17 (7f-F1.2/1.3) → 39 tools; `apply_model_spec`/`export_model_spec`/
`describe_model`/`export_model_report`/`clone_model`/`compare_scenarios`
added 2026-08-17 (7f-G) → 45 tools; `check_parameter_sensitivity` +
`calibrate` added 2026-08-17 (7f-H3.1/H4.1) → 47 tools; `describe_package` +
`export_reproducible_script` added 2026-08-17 (7f-I3/I5), `view_image` removed
(7f-I1 — plot tools return the PNG natively) → 48 tools; `setup_calibration`
added 2026-08-17 (7e-A2 — automated calibration setup) → 49 tools).
**7e-A3 (2026-08-17/18): job control.** `start_run`, `get_job_status` and
`cancel_job` (runner) plus `start_calibration` (calibration) run long jobs in
a background thread and return a `job_id` immediately; `get_job_status`
reports live progress parsed from the `.lst` (MF6 stress period / time step /
percent complete) or `.iobj` / `.phi.actual.csv` (PEST++ iteration + phi);
`cancel_job` terminates the process. → 53 tools. No capability-coverage rows
changed.
**7e-B (2026-08-18): correctness bugs.** `set_model_crs` (CRS on hand-built
grids), `list_models` + `delete_model`, `add_dis_package(idomain)` (→
`summarise_model.grid.n_active`), RCHA/EVTA array-based recharge/ET packages,
`add_boundary_package(pname=...)` for multiple packages of one type;
`assign_top_from_raster` honours `method` (zonal mean/min/max + bilinear),
fails `CRS_UNKNOWN` without a grid CRS, and has an explicit `fill`/coverage
policy; per-root registry scoping; NaN/Inf sanitisation; OC-filerecord output
selection; missing `.rei` fails loudly in `summarise_calibration`. → 56 tools.
No capability-coverage rows changed.
**7e-C1 (2026-08-22): `diagnose_convergence`.** Classifies why a run failed to
converge — `closure_too_tight` (IMS outer/inner dvclose unresolvable at
double precision), `disconnected_active_domain` (idomain splits the DIS
active domain into >1 face-connected region), `newton_needed`/`dry_cells`
(convertible cells at/below their bottom elevation, Newton off vs. already
on), `k_contrast` (NPF k spans >4 orders of magnitude) — inferred from the
model configuration rather than parsed from `.lst` prose, since MF6's log
rarely states a root cause explicitly. Replaces the 20-line raw `.lst` tail
an agent previously had to interpret unaided. → 57 tools. No
capability-coverage rows changed (workflow/meta tool, not capability-specific).
C2–C8 (validate_model, diagnose_water_balance, export tools, MCP
prompts/resources, next_steps hints) remain.
**7e-C2 (2026-08-22): `validate_model`.** Physical-plausibility findings —
`head_below_bottom`, `head_above_top` (convertible cells only), `k_contrast`
(NPF K > 6 orders of magnitude), `disconnected_active_cells` (idomain, DIS
grids), `boundary_in_inactive_cell` (list-based boundary packages on
idomain<=0 cells, per-package counts) — each collapsed into one finding with
a `count` instead of one entry per cell; the real trigger was 569,796
individual FloPy-checker warnings on the zenodo-21381071 regional model. Uses
simulated heads when available, else initial conditions. → 58 tools. No
capability-coverage rows changed. C3–C8 remain.
**7e-C3 (2026-08-22): `diagnose_water_balance`.** Wraps
`compute_water_balance` with a verdict: `percent_discrepancy` (MODFLOW's own
`100*(IN-OUT)/((IN+OUT)/2)` statistic), `balanced` (within `tolerance_pct`,
default 1%), `dominant_inflow_term`/`dominant_outflow_term`, and
`dominant_term`/`dominant_term_share`/`boundary_dominated` (one boundary type
carrying more than `dominance_threshold`, default 50%, of all flow — e.g. a
CHD boundary absorbing everything). → 59 tools. No capability-coverage rows
changed. C4 ticked as bookkeeping (already shipped as `compare_to_observed`,
7f-F1.3).
**7e-C5 (2026-08-22): GIS/table export tools.** `export_heads_to_raster`
(georeferenced GeoTIFF, delegating the affine transform/rotation/CRS to
flopy's own `export_array`), `export_boundaries_to_shapefile` (one feature
per list-based boundary stress-period cell, package record fields as
attributes), `export_water_balance_csv` (`compute_water_balance`'s own
numbers as a CSV with a TOTAL row) — the "no path from a finished model back
to GIS" gap the 2026-08-17 audit named. All three require a structured DIS
grid with a CRS set (`CRS_UNKNOWN` otherwise). → 62 tools. No
capability-coverage rows changed.
**7e-C6/C7/C8 (2026-08-22): prompts, resources, next_steps.** `model_status`
(63rd tool) reports ordered build-order status — `runnable`,
`missing_required`/`missing_recommended`, `next_steps` — and the same
`next_steps` list is auto-attached to every builder/parameterise tool's
result (a server-level wrapper, not per-tool code), so ordering gaps
(`add_sto_package` needs TDIS, `assign_k_from_zones` needs NPF,
`import_grid_from_shapefile`'s `set_simulation` prerequisite) surface
proactively instead of only as the next call's error (C8). Two MCP prompts,
`build_model_from_data` and `calibrate_model`, encode the same build/
calibrate ordering as renderable guidance text (C6). Three MCP resource
templates, `gwmcp://models/{model}/{lst,pst,files}`, expose the listing
file, PEST control file, and workspace file listing as readable URIs instead
of round-tripping through a tool call (C7) — these register as templates
(`mcp.list_resource_templates()`), not static resources, since models are
created at runtime. → 68 tools, +2 prompts, +3 resource templates. No
capability-coverage rows changed. All of 7e Tier C is now done except the
`[human]` closed-book verification on C1/C6/C8 (needs a live agent session).
**7e-A2 (2026-08-17): automated calibration setup.** `setup_calibration`
emits the whole PEST interface with zero hand-written files: rewires NPF `k`
to an external `OPEN/CLOSE` array, generates a wide-token template (≥15 chars)
over `all`/`layer`/`cells` scopes, generates the instruction file from the
model's OBS CSV header, writes a Python forward wrapper at a space-free path
when the default MF6 command would be unsafe on Windows, and assembles the
`.pst` with safe numeric defaults (`derinclb > 0` on every group — fixes the
zero-Jacobian bug — and default bounds base/10–base×10). GLM phi/iterations
now come from `<case>.iobj` (7e-B1.1/1.2), not the IES-only `.phi.actual.csv`,
so `run_pestpp_glm`/`summarise_calibration` no longer report empty progress.
No capability-coverage rows changed.

**Zoned K multipliers (2026-09-11):** `setup_calibration` gained
`scope="zones"` — zones auto-derived from equal positive per-layer `npf:k`
values become dimensionless multiplier parameters applied by a generated
forward wrapper (`k = base_k × multiplier[zone]`). Calibration of zoned-field
regional models no longer requires uniform per-layer K replacement. No
capability-coverage rows changed.
**7f-I (2026-08-17): surface-area cuts.** `plot_heads_map`/`plot_cross_section`
return the PNG natively (ImageContent) and `view_image` is removed;
`sentence-transformers` moved to the optional `semantic` extra with a Whoosh
fallback; `describe_package` exposes the package spec from flopy
introspection (the DFN files are not vendored in flopy 3.10, so the
spec is derived from the package classes instead — deviation from the plan's
mechanism, same outcome); `add_disv_package` rejects oversized inline
payloads (`gridprops_file` alternative); `export_reproducible_script` emits a
pure-flopy rebuild script. No capability-coverage rows changed.
**7f-H (2026-08-17): expertise as behaviour.** Dimensional arguments carry
units (`k_units`, `rate_units` — converted on entry and reported by
`summarise_model.units`); river conductance is derived from bed properties,
never guessed; `run_simulation(auto_fix=True)` escalates solver settings and
reports exactly what changed; `check_parameter_sensitivity` is a cheap n+1
forward-run screen and `setup_pest_control` warns on insensitive parameters;
`calibrate` chooses GLM vs IES; `summarise_calibration` returns a verdict
(improved, parameters_at_bounds, identifiable, fit_within_measurement_error).
No capability-coverage rows changed.
**7f-G (2026-08-17): declarative spec, provenance, scenarios.** A model spec
dict (grid/time/properties/storage/boundaries/output-control) validates with
distinct errors, applies onto any prior state with a structured diff, and is
idempotent; `export_model_spec` emits the spec for adopted models. Every tool
call appends to the provenance ledger (`.gwmcp_history.jsonl`); parameterise
tools record array data sources; `describe_model` reports sources, unverified
defaults, run status and staleness; `export_model_report` produces a Markdown
report. `clone_model`/`compare_scenarios` enable scenario work without
destroying the base model. No capability-coverage rows changed.
**7f-F (2026-08-17): the observation loop is closed.** `import_obs_from_csv`
persists observation targets as model state (`.gwmcp_meta.json` `observations`);
`summarise_model` reports the target count; `read_simulated_observations` and
`compare_to_observed` (RMSE/bias/R²/MAE + residuals + scatter, no PEST setup)
read the model's obs CSV back; `run_simulation` reports `observation_fit`; and
`setup_pest_control(obs_source="model")` builds the obs interface from the
registered targets. OBS row moves **partial → covered**.
**7f-D hardening (2026-08-17e, v0.1.0 gate):** `import_river_from_shapefile`
now samples `stage_raster` at true cell centroids and fails loudly on
insufficient coverage (`STAGE_RASTER_NO_COVERAGE`, `coverage_tolerance`),
reprojects into the model grid's CRS and errors `CRS_UNKNOWN` when the grid
has no CRS; post-processing tools validate `layer` against `nlay`
(`INVALID_INPUT`); `adopt_model` is read-only by default (`allow_modify`)
and the model cache reloads on external file edits (`reloaded_from_disk`).
No capability-coverage rows changed.
`add_boundary_package` dispatch list verified at
`builder.py:_BOUNDARY_PKG_CLASSES` (CHD, WEL, RIV, DRN, RCH, EVT, GHB, SFR).
"catalog example refs" are filled from discovery round 1
(`discovery/catalog.md`); a gap row with zero refs is a red flag.
**DISV obs/calibration/reporting fix (2026-09-12):** the obs/calibration layer
was silently structured-only because FloPy's `gwf.get_package("dis")`
prefix-matches the DISV package (`"disv"` → `"dis"`), so `import_obs_from_csv`
(coords), `setup_calibration`, `summarise_model`, `describe_model`, and
`export_model_spec` dereferenced the missing `nrow`/`ncol` on `ModflowGwfdisv`.
`utils/grid.py` now type-gates the resolvers (`get_dis`/`get_disv`/`get_grid`)
across all 22 call sites, coordinate obs map to `(layer, node)` on DISV, and
`_find_output_file`/`_find_budget_file` resolve OC-declared subdirectory paths
and the GMS `.hed`/`.ccf` extensions. DISV obs/calibration row (formerly an
implicit gap) is now covered; `tests/test_disv_support.py`.
**Adopt/rewrite + OBS robustness fix (2026-09-13, GMS rerun):** FloPy leaves a
GWF OC package's `saverecord`/`printrecord` empty when the period block is an
external `OPEN/CLOSE` file (GMS), so the first rewrite dropped it and the run
wrote no heads/budget — `model_store.restore_oc_period_records` now re-reads
the OC period file on adopt/load/clone. `import_obs_from_csv` also sanitises
site names to MF6-safe tokens (`#` is a comment marker; `POINT_#1` aborted the
base run) and rejects unsupported `obs_type` values (e.g. `FLOW`) loudly.
`tests/test_oc_obs_robustness.py`.

## GWF — flow (discretisation + stress packages)

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| DIS (rectangular grid) | covered | `add_dis_package` | test005_advgw_tidal, ex-gwf-hani, mf6-training | `idomain` support (7e-B9) |
| DISV (layered vertex grid) | covered | `add_disv_package` | test006_gwf3_disv, ex-gwf-u1disv, mf6Voronoi, Modflow-API-Ag-Package | obs import (coords → `(layer, node)`), `summarise_model`, `export_model_spec`, and non-zoned/zoned `setup_calibration` all work on DISV (fix 2026-09-12) |
| DISU (fully unstructured) | covered | `add_disu_package` | test009_3lay-disu, test006_gwf3_gnc, ex-gwf-radial, MF6_EnKF_DISU, GMS Quadtree | Connectivity-based build (NODES/NJA, IAC/JA 0-based); `get_disu`/`grid_size`, `model_status`/`summarise_model`, obs scalar 1-based node ids and DISU `setup_calibration`; **rerun-validated on test009_3lay-disu 2026-09-13** (2 consecutive green). No x/y without vertices → `plot_heads_map`/coordinate obs fail clearly |
| TDIS / IMS (time + solver) | covered | `set_simulation` | all testmodels/examples (mfsim.nam) | nper, perlen, nstp, tsmult, ims_complexity |
| STO (storage) | covered | `add_sto_package` | test003_gwfs_tr, test020_NevilleTonkinTransient, ex-gwf-advtidal | v0.1.0 gate (2026-08-16): iconvert/ss/sy + steady/transient periods |
| NPF (properties) | covered | `add_npf_package` | all testmodels/examples | |
| IC (initial conditions) | covered | `add_ic_package` | all testmodels/examples | |
| OC (output control) | covered | `add_oc_package` | all testmodels/examples | head/budget filerecords + saverecord |
| CHD / WEL / RIV / DRN / RCH / EVT / GHB / SFR | covered | `add_boundary_package` | test005_advgw_tidal, test051_uzfp2, ex-gwf-advtidal, mf6-training | SFR via dispatch; RIV/DRN/GHB also via `import_river_from_shapefile` |
| RCHA / EVTA (array-based recharge/ET) | covered | `add_boundary_package` | mf6brabant (RP1.tif recharge), test051_uzfp2 | Full-grid array per stress period (7e-B8) |
| MAW (multi-aquifer well) | **gap** | — | test020_NevilleTonkinTransient, test001g_MVR, ex-gwf-maw-p01, ex-gwt-mt3dsupp82, mf6-training, ModelMuse MAW-solute tutorial | Not in supported boundary list |
| UZF (unsaturated zone flow) | **gap** | — | test051_uzfp2, ex-gwf-sagehen, ex-gwt-uzt-2d, ex-gwf-drn-p01, mf6-training, Modflow-API-Ag-Package | Not in supported boundary list |
| LAK (lakes) | **gap** | — | test045_lake1ss, ex-gwf-lak-p02, ex-gwf-sfr-p01b, modflow-setup (Pleasant Lake), mf6-training | Not in supported boundary list |
| GNC (ghost-node correction) | **gap** | — | test006_gwf3_gnc, test009_3lay-disu, test006_gwf3_disv, flopy lgr_gnc_example.py | Not exposed; thin coverage — red flag |
| MVR (water mover) | **gap** | — | test001g_MVR, test051_uzfp2_mvr, ex-gwf-lak-p02, ex-gwf-sagehen, ex-gwt-mt3dsupp82, mf6-training | Not exposed |

## GWT / SWT — transport

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| GWT (solute transport) | **gap** | — | ex-gwt-mt3dms-p01, ex-gwt-prudic2004t2, ex-gwt-keating, test201_gwtbuy-henryCHD, PROMISCES PFOA (Zenodo), mf6-training | No GWT model support at all |
| SWT (saltwater) | **gap** | — | no MF6 SWT6 package exists (round-1 finding); nearest: test201/205_gwtbuy (BUY), ex-gwt-henry, ex-gwt-saltlake; verify `MODFLOW-USGS/swtv4` next round | Variable density in MF6 = GWT hydraulic-head formulation (Langevin et al. 2020) or standalone swtv4; SWT6 not an MF6 package |
| GWF-GWT coupling | **gap** | — | test201/205_gwtbuy, ex-gwt-prudic2004t2, ex-gwt-keating, ex-gwt-uzt-2d, elder-mf6, mf6rtm | Requires both models + exch |

## Observations

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| OBS (observations) | covered | `import_obs_from_csv`, `read_simulated_observations`, `compare_to_observed` | test005_advgw_tidal, test020_NevilleTonkinTransient, ex-gwf-radial, ex-gwf-advtidal, ex-gwt-keating, usgs/pestpp mf6_freyberg, neversink_workflow | Writes OBS file from CSV, persists targets to model state, reads the obs CSV back, and calibrates from registered targets (`obs_source="model"`) |

## Output / post-processing

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| .hds / .cbb readers | covered | `read_heads`, `read_budget` | | |
| Plots | covered | `plot_heads_map`, `plot_cross_section` | | FloPy PlotMapView / PlotCrossSection |
| Water balance | covered | `compute_water_balance` | | Budget aggregation by boundary type |
| Drawdown | covered | `compute_drawdown` | | |

## Calibration / uncertainty

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| PEST++ GLM / IES | covered | `setup_calibration`, `run_pestpp_glm`, `run_pestpp_ies` | | `setup_calibration` emits the whole interface (external-array rewire, wide-token template, ins from the OBS CSV, Windows-safe forward wrapper, safe `.pst` defaults); GLM phi from `.iobj`; `summarise_calibration` auto-detects the engine and summarises IES runs too (2026-08-29) — phi from the `.phi.actual.csv` mean column, parameter estimates from the final ensemble `par.csv` (mean + spread), residuals from `.rei` or the obs ensemble |
| PEST++ PPU (prediction uncertainty) | covered | `run_ies_uncertainty` | | Ensemble percentiles |
| PEST++ SEN (sensitivities) | **gap** | — | usgs/pestpp benchmarks/mf6_freyberg (freyberg6_run_sen.pst), neversink_workflow | |
| PEST++ Pareto / SWP (sweep) | **gap** | — | usgs/pestpp benchmarks/mf6_freyberg (freyberg6_sweep.pst, run_opt.pst) | |

## Workflow / meta tools (not capability-specific)

`create_model`, `summarise_model`, `list_model_files`, `flush_model`,
`list_models`, `delete_model`, `set_model_crs`, `check_model`,
`run_simulation`, `get_run_log`, `diagnose_convergence`, `validate_model`, `diagnose_water_balance`,
`export_heads_to_raster`, `export_boundaries_to_shapefile`, `export_water_balance_csv`, `model_status`, `start_run`,
`get_job_status`, `cancel_job`, `start_calibration`, `setup_calibration`,
`setup_pest_control`, `summarise_calibration`, `import_grid_from_shapefile`,
`assign_top_from_raster`, `assign_k_from_zones`,
`import_river_from_shapefile`, `search_docs`, `search_tutorials`,
`get_doc_file`.

Correctness hardening (7e-B): the registry is scoped per workspace root with
idempotent re-registration (B4.2); `assign_top_from_raster` honours `method`
(zonal mean/min/max + bilinear), requires a grid CRS (`CRS_UNKNOWN`) and has
an explicit `fill`/coverage policy (B5/B11.2/B11.3); `summarise_calibration`
fails loudly when the run died before writing residuals (B2); tool results
are sanitised of NaN/Inf (B12); head/budget readers prefer the OC filerecord
(B13); `_array_stats` masks both `±1e30` sentinels (B14).

Build-loop cost (7f-E1.2): builder calls defer their disk writes; the write
happens at `flush_model` or implicitly at `check_model` / `run_simulation` /
`list_model_files` and the calibration handoff. Observation loop (7f-F):
targets registered by `import_obs_from_csv` are read back by
`read_simulated_observations` / `compare_to_observed` and consumed by
`run_simulation.observation_fit` and `setup_pest_control(obs_source="model")`.
Spec/provenance/scenarios (7f-G): `apply_model_spec`/`export_model_spec`
(declarative spec), the per-call provenance ledger + `describe_model`/
`export_model_report`, and `clone_model`/`compare_scenarios`.
No capability-coverage rows changed except OBS (partial → covered).

## Legacy — out of scope (v0.1.0/v0.2.0; appear here for completeness only)

| Capability | Status | Notes |
|---|---|---|
| MODFLOW-2005 / NWT / USG | legacy-out-of-scope | v0.2.0+ candidate |
| SEAWAT | legacy-out-of-scope | — |
| MT3D-MS / MT3D-USGS | legacy-out-of-scope | v0.2.0 candidate (tasks.md 7d) |
| MODPATH | legacy-out-of-scope | v0.2.0 candidate (tasks.md 7d) |

## Coverage summary

- covered: 16 rows · partial: 0 · gap: 10 (MAW, UZF, LAK, GNC, MVR,
  GWT, SWT, GWF-GWT coupling, pestpp-sen, pestpp-pareto/swp) · legacy-out-of-scope: 4
  (UCODE SVD estimation and UCODE linear/MCMC uncertainty rows removed
  2026-08-17 — UCODE is no longer part of the project's calibration scope)
- Round-1 red flags (see `discovery/catalog.md` "Round-1 red flags"): SWT has
  no MF6 SWT6 package (variable density via GWT hydraulic-head formulation);
  GNC coverage is thin (2 testmodels + 1 flopy notebook). Every GAP row now has
  ≥1 catalog example ref.
