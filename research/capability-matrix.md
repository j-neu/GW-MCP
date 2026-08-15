# Capability Matrix — MODFLOW 6 + PEST coverage in groundwater-mcp

Row schema:
`capability (package/process/mode) | MCP status today (covered | partial | gap | legacy-out-of-scope) | covering tool(s) | catalog example refs | notes`

Status verified against `tools.md` + tool module source on 2026-08-15
(`src/groundwater_mcp/tools/`, 36 tools across 6 modules). `add_boundary_package`
dispatch list verified at `builder.py:_BOUNDARY_PKG_CLASSES` (CHD, WEL, RIV, DRN,
RCH, EVT, GHB, SFR). "catalog example refs" are filled from discovery round 1
(`discovery/catalog.md`); a gap row with zero refs is a red flag.

## GWF — flow (discretisation + stress packages)

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| DIS (rectangular grid) | covered | `add_dis_package` | | |
| DISV (layered vertex grid) | covered | `add_disv_package` | | |
| DISU (fully unstructured) | **gap** | — | | User-flagged; first v0.2.0 item |
| TDIS / IMS (time + solver) | covered | `set_simulation` | | nper, perlen, nstp, tsmult, ims_complexity |
| STO (storage) | **gap** | — | | Not exposed as a tool |
| NPF (properties) | covered | `add_npf_package` | | |
| IC (initial conditions) | covered | `add_ic_package` | | |
| OC (output control) | covered | `add_oc_package` | | head/budget filerecords + saverecord |
| CHD / WEL / RIV / DRN / RCH / EVT / GHB / SFR | covered | `add_boundary_package` | | SFR via dispatch; RIV/DRN/GHB also via `import_river_from_shapefile` |
| MAW (multi-aquifer well) | **gap** | — | | Not in supported boundary list |
| UZF (unsaturated zone flow) | **gap** | — | | Not in supported boundary list |
| LAK (lakes) | **gap** | — | | Not in supported boundary list |
| GNC (ghost-node correction) | **gap** | — | | Not exposed |
| MVR (water mover) | **gap** | — | | Not exposed |

## GWT / SWT — transport

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| GWT (solute transport) | **gap** | — | | No GWT model support at all |
| SWT (saltwater) | **gap** | — | | No SWT model support at all |
| GWF-GWT coupling | **gap** | — | | Requires both models + exch |

## Observations

| Capability | Status today | Covering tool(s) | Catalog example refs | Notes |
|---|---|---|---|---|
| OBS (observations) | partial | `import_obs_from_csv` | | Writes OBS file from CSV; no `add_obs_package` tool |

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
| PEST++ SEN (sensitivities) | **gap** | — | | |
| PEST++ Pareto / SWP (sweep) | **gap** | — | | |
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

- covered: 14 rows · partial: 1 · gap: 12 (DISU, STO, MAW, UZF, LAK, GNC, MVR,
  GWT, SWT, GWF-GWT coupling, pestpp-sen, pestpp-pareto/swp) · legacy-out-of-scope: 4
