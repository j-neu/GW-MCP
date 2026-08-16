# Capability Matrix — MODFLOW 6 + PEST coverage in groundwater-mcp

Row schema:
`capability (package/process/mode) | MCP status today (covered | partial | gap | legacy-out-of-scope) | covering tool(s) | catalog example refs | notes`

Status verified against `tools.md` + tool module source on 2026-08-15
(`src/groundwater_mcp/tools/`, 37 tools across 6 modules; `check_environment`
added 2026-08-16 → 38 tools across 7 modules; `add_sto_package` added
2026-08-16 → 39 tools). `add_boundary_package` dispatch list verified at
`builder.py:_BOUNDARY_PKG_CLASSES` (CHD, WEL, RIV, DRN, RCH, EVT, GHB, SFR).
"catalog example refs" are filled from discovery round 1
(`discovery/catalog.md`); a gap row with zero refs is a red flag.

## GWF — flow (discretisation + stress packages)

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| DIS (rectangular grid) | covered | `add_dis_package` | test005_advgw_tidal, ex-gwf-hani, mf6-training | |
| DISV (layered vertex grid) | covered | `add_disv_package` | test006_gwf3_disv, ex-gwf-u1disv, mf6Voronoi, Modflow-API-Ag-Package | |
| DISU (fully unstructured) | **gap** | — | test009_3lay-disu, test006_gwf3_gnc, ex-gwf-radial, MF6_EnKF_DISU, GMS Quadtree | User-flagged; first v0.2.0 item |
| TDIS / IMS (time + solver) | covered | `set_simulation` | all testmodels/examples (mfsim.nam) | nper, perlen, nstp, tsmult, ims_complexity |
| STO (storage) | covered | `add_sto_package` | test003_gwfs_tr, test020_NevilleTonkinTransient, ex-gwf-advtidal | v0.1.0 gate (2026-08-16): iconvert/ss/sy + steady/transient periods |
| NPF (properties) | covered | `add_npf_package` | all testmodels/examples | |
| IC (initial conditions) | covered | `add_ic_package` | all testmodels/examples | |
| OC (output control) | covered | `add_oc_package` | all testmodels/examples | head/budget filerecords + saverecord |
| CHD / WEL / RIV / DRN / RCH / EVT / GHB / SFR | covered | `add_boundary_package` | test005_advgw_tidal, test051_uzfp2, ex-gwf-advtidal, mf6-training | SFR via dispatch; RIV/DRN/GHB also via `import_river_from_shapefile` |
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
| OBS (observations) | partial | `import_obs_from_csv` | test005_advgw_tidal, test020_NevilleTonkinTransient, ex-gwf-radial, ex-gwf-advtidal, ex-gwt-keating, usgs/pestpp mf6_freyberg, neversink_workflow | Writes OBS file from CSV; no `add_obs_package` tool |

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
| PEST++ GLM / IES | covered | `run_pestpp_glm`, `run_pestpp_ies` | | pyEMU PstFrom/manual Pst |
| PEST++ PPU (prediction uncertainty) | covered | `run_ies_uncertainty` | | Ensemble percentiles |
| PEST++ SEN (sensitivities) | **gap** | — | usgs/pestpp benchmarks/mf6_freyberg (freyberg6_run_sen.pst), neversink_workflow | |
| PEST++ Pareto / SWP (sweep) | **gap** | — | usgs/pestpp benchmarks/mf6_freyberg (freyberg6_sweep.pst, run_opt.pst) | |
| UCODE SVD estimation | covered | `setup_ucode_control`, `run_ucode`, `summarise_ucode_calibration` | | |
| UCODE linear/MCMC uncertainty | covered | `run_ucode_uncertainty` | | |

## Workflow / meta tools (not capability-specific)

`create_model`, `summarise_model`, `list_model_files`, `check_model`,
`run_simulation`, `get_run_log`, `setup_pest_control`, `summarise_calibration`,
`import_grid_from_shapefile`, `assign_top_from_raster`, `assign_k_from_zones`,
`import_river_from_shapefile`, `search_docs`, `search_tutorials`, `get_doc_file`.

## Legacy — out of scope (v0.1.0/v0.2.0; appear here for completeness only)

| Capability | Status | Notes |
|---|---|---|
| MODFLOW-2005 / NWT / USG | legacy-out-of-scope | v0.2.0+ candidate |
| SEAWAT | legacy-out-of-scope | — |
| MT3D-MS / MT3D-USGS | legacy-out-of-scope | v0.2.0 candidate (tasks.md 7d) |
| MODPATH | legacy-out-of-scope | v0.2.0 candidate (tasks.md 7d) |

## Coverage summary

- covered: 15 rows · partial: 1 · gap: 11 (DISU, MAW, UZF, LAK, GNC, MVR,
  GWT, SWT, GWF-GWT coupling, pestpp-sen, pestpp-pareto/swp) · legacy-out-of-scope: 4
- Round-1 red flags (see `discovery/catalog.md` "Round-1 red flags"): SWT has
  no MF6 SWT6 package (variable density via GWT hydraulic-head formulation);
  GNC coverage is thin (2 testmodels + 1 flopy notebook). Every GAP row now has
  ≥1 catalog example ref.
