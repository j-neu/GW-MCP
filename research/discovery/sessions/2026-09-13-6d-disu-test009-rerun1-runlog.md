# Phase 6d DISU validation — run log

Session: `6d-disu-test009-rerun1`
Date: 2026-09-13
Model source: `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\` (MODFLOW 6 test009, 3 layers with a nested grid in layer 2)
Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-disu-test009-rerun1\session-6d\`

All model builds/adopts/runs/postprocessing/calibration went through groundwater-mcp
tool calls. Python was used only to read model input files (the specification) and
MCP-written outputs. No MODFLOW files were hand-edited.

---

## 1) check_environment — stack

- Python 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`), Windows 10.
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8, whoosh 2.7.4.
- Binaries: `mf6.exe`, `pestpp-glm.exe`, `pestpp-ies.exe`, `pestpp-sen.exe`, `pestpp-opt.exe`, `pestpp-da.exe` (all under `C:\Users\jakob\.local\bin`).
- Docs index built. Workspace root `C:\Users\jakob\.groundwater-mcp\workspaces`.
- `ready: true`, nothing missing.

## 2) Copy + adopt

- Copied all 11 source files into `session-6d\test009_3lay-disu\` (verbatim; no edits).
- `adopt_model(name="disu_test009", workspace=<copy>, units="METERS", time_units="DAYS", allow_modify=true)`.
  → `adopted: true`, `model_names: ["gwf_1"]`, `next_steps: []`. Grid NOT rebuilt.

### Source model specification (from the files)
- `mfsim.nam`: one GWF model `GWF_1`; empty OPTIONS → default length units METERS. `flow.tdis`: `TIME_UNITS DAYS`, NPER 1, perlen 1.0, nstp 1 (steady).
- `flow.nam`: DISU6, IC6, CHD6, NPF6, **GNC6**, OC6.
- `flow.disu`: NODES 228, NJA 1372. TOP = 0 (nodes 1–76), -10 (77–152), -20 (153–228); BOT = -10/-20/-30. AREA 10000 m², but 2500 m² for the nested layer-2 cells (nodes 28–35, 42–49, 101–108, 115–122 = the 8×8 nested grid reflected in each of layers 2/3). IAC/JA/IHC/CL12/HWVA/ANGLDEGX supplied.
- `flow.gnc`: NUMGNC 48, NUMALPHAJ 2 — ghost-node corrections coupling the nested (coarser/finer) layer-2 interfaces (the `0.125` alpha / `0.125` … entries). This is the feature that makes test009 a genuine DISU+GNC problem.
- `flow.npf`: ICELLTYPE 0, K = K33 = 1 (SAVE_FLOWS, PRINT_FLOWS).
- `flow.ic`: STRT = 1.0. `flow.chd`: 24 north nodes at 1.0, 24 south nodes at 0.0 (48 total).
- `flow.oc`: head/budget files `flow.hds`/`flow.cbc`, save all.

## 3) check_model — adopted model

`check_passed: true`, `errors: []`, `warnings: []`.
FloPy summary: "No errors or warnings encountered." Checks passed include CHD index/nan/inactive-cell checks and NPF K range checks. Clean, no documentation caveat needed.

## 4) run_simulation — adopted model

`success: true`, `convergence: "converged"`, `elapsed_s: 0.33`.
`get_run_log` tail confirms: solver summary shows **2 outer iterations**, max change `7.34E-10` on the second, "Normal termination of simulation." mfsim.lst is 274 lines.

## 5) Postprocessing (adopted DISU model)

- `read_heads(layer=0)`: shape `[1, 228]`, `n_active: 228`, **min 0.0, max 1.0, mean 0.5000000000292736**. (DISU has no layer structure; layer 0 returns all 228 nodes. Values interpolate linearly between the 1.0 north CHD and 0.0 south CHD.)
- `compute_water_balance`: inflow `{CHD: 34.285714275882754}`, outflow `{CHD: -34.28571429093572}`, `net_balance: -1.5052968649342802e-8` → closes (≈0, only CHD boundaries).
- `summarise_model` — grid block **verbatim**:
  `{"type": "DISU", "nlay": 1, "nnodes": 228, "ncells": 228, "nja": 1372}`
  (Note: `nlay` is reported as 1 because a DISU grid carries no layer structure — the source model is conceptually 3 layers. `nnodes`/`ncells`/`nja` are correct.)
  Packages: `["DISU","IC","CHD-1","NPF","GNC","OC"]`; `boundary_types: ["CHD"]`; `storage: null` (steady).
- `model_status`: `runnable: true`, `missing_required: []`, `missing_recommended: []`, `next_steps: []`, `warnings: []`.
- `validate_model`: `clean: true`, `findings: []`.

## 6) New small DISU model via the builder path (`disu_small`)

Built entirely with MCP calls in `session-6d\disu_builder\`:
`create_model` → `set_simulation(nper=1, perlen=[1], nstp=[1])` →
`add_disu_package(nodes=3, nja=7, top=[0,0,0], bot=[-10,-10,-10], iac=[2,3,2], ja=[0,1,1,0,2,2,1])` →
`add_npf_package(icelltype=0, k=1)` → `add_ic_package(strt=0.5)` →
`add_boundary_package(CHD, ...)` → `add_oc_package` → `flush_model`.

### Deviation/reprompt 1 — DISU CHD cellid format
First attempt used `[layer, node]` records: `{"0": [[[0,0],1],[[0,2],0]]}`.
The written `disu_small.chd` contained `1 1` and `1 0` — both records collapsed onto
node 0, and the run failed:
`ERROR REPORT: 1. Cell is already a constant head ((1))`.
**Decision:** on a DISU grid the boundary `cellid` is a bare **node index**, not
`(layer, node)`. Re-issued with `{"0": [[0,1],[2,0]]}`, which wrote `1 1` / `3 0`
(0→1-based conversion correct). Re-`check_model`: pass. Re-run: `success: true`,
`convergence: "converged"`, normal termination.

`check_model` on the bare DISU grid passes (no MF6 errors) but FloPy raises two
**warnings**:
- "cell2d information missing. Functionality of the UnstructuredGrid will be limited."
- "vertices information missing. Functionality of the UnstructuredGrid will be limited."
(Expected: a vertex-less DISU grid has no x/y geometry.)

### Observations + calibration (`import_obs_from_csv`, `setup_calibration`)
- `obs_seq.csv` has only `site,value` (no x/y). `import_obs_from_csv` → `site_count: 3`,
  `site_cellid_map: {"N1":0,"N2":1,"N3":2}` — sequential node mapping works on DISU.
- **ERROR (tool defect).** The written `disu_small.obs` is 0-based:
  ```
  N1  HEAD  0
  N2  HEAD  1
  N3  HEAD  2
  ```
  MODFLOW 6 requires 1-based node numbers. Re-running the model now fails:
  `ERROR REPORT: 1. Node number in list (0) is outside of the grid. Cell number
  cannot be determined in line '0'. ... Error occurred while reading file
  'disu_small.obs'`.
  (Contrast: `add_boundary_package` for CHD wrote correct 1-based node ids. The
  off-by-one is specific to the DISU observation writer.)
- Per the MCP-only constraint the `.obs` file was **not** hand-corrected.
- `setup_calibration(parameterisation={"k":{"target":"npf:k","scope":"all","initial":1.0}},
  obs_source="model")` **succeeded**: generated `disu_small.pst` (3 observations, 1
  adjustable parameter `k`, initial 1, bounds 0.1–10, `partrans=log`), template
  `disu_small_k.dat.tpl`, instruction file `disu_small_head.obs.csv.ins`, and a
  space-free Python forward wrapper.
- `run_pestpp_glm`: client-side **timeout** (-32001); the `.rec` file shows the real
  outcome — `OPTIMISATION ITERATION NUMBER: 1 ... Model calls so far: 0 ... Error:
  Base parameter run failed. Can not compute the Jacobian`. The base forward run
  fails for the same `.obs` reason; `disu_small_head.obs.csv` contains only the
  header `time,N1,N2,N3`, so no simulated observations exist.

## 7) Spatial tools on a DISU grid with no vertices

Tested on the adopted `disu_test009` (DISU, no vertices):
- `plot_heads_map(layer=0)`:
  `{"error": true, "code": "INVALID_INPUT", "message": "plot_heads_map requires
  cell x/y geometry, which this discretisation does not carry (a DISU grid defined
  without vertices). Use read_heads or compute_water_balance instead."}`
  → **No head map is produced.**
- `import_obs_from_csv(..., x_col="x", y_col="y")`:
  `{"error": true, "code": "INVALID_INPUT", "message": "This grid has no cell-centroid
  x/y coordinates (a DISU grid defined without vertices/geometry). Coordinate-based
  operations are unavailable — use sequential node/cell mapping instead."}`
  → Coordinate-based observation mapping is unavailable; sequential mapping is the
  documented alternative (and does work — see §6).

## 8) Summary of results per criterion

| # | Criterion | Result |
|---|-----------|--------|
| 1 | check_environment | ready:true, full stack reported |
| 2 | copy + adopt_model | adopted, `disu_test009`, METERS/DAYS, allow_modify, grid not rebuilt |
| 3 | check_model | clean (no errors/warnings) |
| 4 | run_simulation | converged, normal termination (2 outer iters, max Δ 7.3e-10) |
| 5 | postprocess | read_heads min 0/max 1/mean 0.5; water balance closes (net -1.5e-8); summarise_model grid `{DISU, nlay 1, nnodes 228, nja 1372}`; model_status runnable; validate_model clean |
| 6 | new DISU builder model + obs + calibration | grid/NPF/IC/CHD/OC build & run OK (after cellid-format fix); sequential obs import OK; **OBS writer emits 0-based node ids → MF6 run fails**; setup_calibration OK; run_pestpp_glm fails at base run ("Can not compute the Jacobian") |
| 7 | x/y-dependent ops on vertex-less DISU | both `plot_heads_map` and coordinate `import_obs_from_csv` return `INVALID_INPUT`; no head map produced |
| 8 | run-log.md | this file |

## Deviations from the source model
- Adopted model: **none** — files copied verbatim, grid not rebuilt, GNC retained.
- Builder model: CHD cellids had to be scalar node indices, not `(layer, node)`.
- The DISU `.obs` 0-based-node defect was **not** worked around (constraint forbids
  editing MODFLOW files); it is reported as a capability gap.

## Capability gaps identified
1. **`import_obs_from_csv` on DISU writes 0-based node ids** in the `.obs` file. MF6
   needs 1-based node numbers, so any DISU model with registered observations cannot
   run (and therefore cannot be calibrated). This blocks the whole
   obs → setup_calibration → run_pestpp_glm chain on DISU grids.
2. **DISU grids without vertices carry no cell x/y**, which correctly disables
   `plot_heads_map` and coordinate-based `import_obs_from_csv` (reported explicitly as
   `INVALID_INPUT`). Sequential node mapping is the supported alternative.
