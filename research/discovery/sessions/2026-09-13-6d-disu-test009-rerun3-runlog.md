# Phase 6d capability row — DISU (fully unstructured grid)

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-disu-test009-rerun3`
Source data: `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\`
Constraint: MCP-only for all model build/adopt/run/post-process/calibrate actions.
Flopy/pyemu classes were not called directly; model files were only copied/read.

## 1. Environment (`check_environment`)

- Python 3.12.11 at `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4,
  scipy 1.17.1, matplotlib 3.10.8, whoosh 2.7.4
- Binaries: mf6, pestpp-glm/ies/sen/opt/da all present
  (`C:\Users\jakob\.local\bin\...`)
- `ready: true`, `missing: {}`, docs index built, workspace root
  `C:\Users\jakob\.groundwater-mcp\workspaces`.

Stack is sufficient for MODFLOW 6 DISU build/run/post-process/calibration.

## 2. Copy + adopt

Source files copied verbatim into the session sub-folder `test009_3lay-disu\`
(mfsim.nam, flow.nam, flow.disu, flow.ic, flow.npf, flow.chd, flow.gnc,
flow.oc, flow.tdis, flow.ims, readme.txt). No file was edited.

Model declaration read from the input files:
- DISU, NODES 228, NJA 1372 (3 layers: layer tops 0 / -10 / -20 m).
- TDIS: `TIME_UNITS DAYS`; 1 stress period, 1 step, perlen 1.0 d.
- No LENGTHUNITS option anywhere -> length units default to METERS.
- Packages: DISU, IC, CHD-1, NPF, GNC, OC.

`adopt_model(name="test009disu", workspace=...rerun3\test009_3lay-disu,
units="METERS", time_units="DAYS", allow_modify=true)` -> OK,
`model_names: ["gwf_1"]`.

**Decision / gotcha:** the first adopt reused the model name `test009disu`,
which a previous session had already registered against the sibling
`...rerun2\test009_3lay-disu`. `list_models` confirmed
`test009disu -> ...rerun2\...` while `read_heads`/`summarise_model` reported
the rerun2 workspace. To guarantee the rerun3 copy was the one under test the
adopted model was re-registered under the unique name **`r3t009disu`**
(workspace ...rerun3\test009_3lay-disu). All reported results below are for
`r3t009disu`.

## 3. check_model — clean

`check_model(r3t009disu)`:
- `check_passed: true`, `errors: []`, `warnings: []`
- "No errors or warnings encountered." Passed checks include chd BC indices
  valid / no NaN / BC not in inactive cells, npf K range checks.
- `flush` is a no-op for adopted read-only-source models.

## 4. run_simulation — converged / normal termination

`run_simulation(r3t009disu)` -> `success: true`, `elapsed_s: 0.06`,
`convergence: "converged"`, listing ends:
`"Run end date and time ... Elapsed run time: 0.034 Seconds /
Normal termination of simulation."`
(No client timeout occurred on the adopted-model run; see §6 for the one
timeout that did occur.)

## 5. Post-processing on the adopted DISU model

- **read_heads(layer=0)**: shape `[1, 228]`, `n_active: 228`,
  min 0, max 1, mean 0.50000000003. `layer=1` and `layer=2` were refused:
  `INVALID_INPUT: layer 1 out of range: model has nlay=1 (valid: 0..0)`.
  Reason: DISU carries no layer dimension — all 228 nodes are exposed as one
  flattened layer (nnodes == ncells == 228). Reported.
- **compute_water_balance**: inflow `{"CHD": 34.2857142759}`,
  outflow `{"CHD": -34.2857142909}`, `net_balance: -1.505e-08`
  (relative discrepancy ~4.4e-10). Closes.
- **summarise_model** grid block verbatim:
  `{"type":"DISU","nlay":1,"nnodes":228,"ncells":228,"nja":1372}`
  packages `["DISU","IC","CHD-1","NPF","GNC","OC"]`, 1 stress period
  `{"perlen":1,"nstp":1,"tsmult":1}`, boundary_types `["CHD"]`, units
  `{length: METERS, time: DAYS, k: m/d, recharge: m/d}`.
- **model_status**: `runnable: true`, `missing_required: []`,
  `missing_recommended: []`, `warnings: []`.
- **validate_model**: `clean: true`, `findings: []`.

The GNC (ghost-node correction) package is correctly detected and carried.

## 6. Second, brand-new DISU model (builder path)

Model `r3disu3line`, workspace `...rerun3\disu3line`.

Sequence:
1. `create_model(r3disu3line, METERS/DAYS)`.
2. `set_simulation(nper=1, perlen=[1], nstp=[1])`.
3. `add_disu_package(nodes=3, nja=7, top=[0,0,0], bot=[-1,-1,-1],
   iac=[2,3,2], ja=[0,1,1,0,2,2,1])` — 3-node line, 0-based JA.
4. `add_npf_package(icelltype=0, k=1.0)`.
5. `add_ic_package(strt=0.5)`.
6. `add_oc_package(head=flow.hds, budget=flow.cbc,
   saverecord=[["HEAD","ALL"],["BUDGET","ALL"]])`.
7. CHD boundary — **gotcha / reprompt:**
   - First tried `[[0,0],1.0],[[0,2],0.0]` (i.e. `(layer,node)`). It was
     accepted, but the generated `r3disu3line.chd` wrote both records as
     cell `1`; the run then failed with
     `ERROR REPORT: 1. Cell is already a constant head ((1)).`
   - Root cause: on DISU the CHD cell id is a **single node index**; passing
     a 2-element id made the tool use only the first element (node 1 for both
     records). Re-added as `[[0],1.0],[[2],0.0]` -> file correctly has
     `1 ...` and `3 ...`, i.e. nodes 1 and 3.
   - Note: an edit + re-read of the `.chd` showed the old text until
     `flush_model` was called — builder changes are staged in memory.
8. `flush_model` -> written.
9. `check_model` -> `check_passed: true`, `errors: []`; warnings limited to
   the expected `cell2d information missing` / `vertices information missing`
   (the hand-built DISU has no geometry). Later re-check after the CHD fix
   returned zero warnings.
10. `run_simulation` -> `success: true`, `convergence: "converged"`,
    normal termination; heads `[1.0, 0.5, 0.0]` (shape `[1,3]`).

### Observations and calibration

- Wrote `obs_noxy.csv` (`site,date,value`; no x/y).
- `import_obs_from_csv(obs_noxy.csv)` (no `x_col`/`y_col`) -> **works via
  sequential mapping**: `site_cellid_map {n1:1, n2:2, n3:3}`,
  `site_count: 3`. Wrote `r3disu3line.obs` (OBS6 in the nam, FILEOUT
  `r3disu3line_head.obs.csv`) and an obs summary CSV.
- `setup_calibration(parameterisation={"k":{"target":"npf:k","scope":"all",
  "initial":1.0}}, obs_source="model")` -> **success**:
  - `pst_file r3disu3line.pst`, `n_observations: 3`,
    `n_adjustable_parameters: 1`
  - parameter `k`: scope all, initial 1, bounds 0.1–10, partrans log
  - template `r3disu3line_k.dat.tpl`, target `r3disu3line_k.dat`
    (NPF k rewired to `OPEN/CLOSE 'r3disu3line_k.dat' FACTOR 1.0`)
  - instruction file `r3disu3line_head.obs.csv.ins`
  - forward wrapper `%TEMP%\gwmcp_run_r3disu3line.py`; model_command uses the
    space-free wrapper (Windows-safe).
- Verification run after the k rewire: `run_simulation` returned a **client
  timeout** (`MCP error -32001: Request timed out`). Per the criteria this was
  checked with `get_run_log`, which showed
  `Normal termination of simulation`, and
  `r3disu3line_head.obs.csv` was produced with
  `time,N1,N2,N3 / 1.0,1.0,0.5,0.0`. `read_simulated_observations` returned
  `{n1:1.0, n2:0.5, n3:0.0}`. So the timeout was a client-side artifact, not a
  model failure. No errors in the calibration setup itself; the calibration
  was not executed (not required) but the interface is complete and runnable.

## 7. Operations that need cell x/y on a vertex-less DISU

Tested on both adopted `r3t009disu` and built `r3disu3line` (neither DISU file
contains VERTICES/CELL2D):

- `plot_heads_map` -> **no map produced**; returned
  `INVALID_INPUT: "plot_heads_map requires cell x/y geometry, which this
  discretisation does not carry (a DISU grid defined without vertices). Use
  read_heads or compute_water_balance instead."` (same for both models).
- `import_obs_from_csv` with `x_col`/`y_col` ->
  `INVALID_INPUT: "This grid has no cell-centroid x/y coordinates (a DISU
  grid defined without vertices/geometry). Coordinate-based operations are
  unavailable — use sequential node/cell mapping instead."`

Behaviour is a hard, explicit refusal with an actionable message; the tool
does not silently guess coordinates and does not fall back to raw flopy.

## 8. Deviations from the source model

- No deviation in the adopted model: files were copied byte-for-byte and
  adopted from disk (grid, GNC, CHD etc. untouched).
- The only naming deviation: adopted as `r3t009disu` instead of
  `test009disu` to avoid the stale rerun2 registration (see §2).
- The second model `r3disu3line` is new work, not a modification of the
  published model.

## 9. Summary of criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | check_environment | PASS — stack ready, all packages/binaries present |
| 2 | copy + adopt_model, no rebuild | PASS (adopted as `r3t009disu`; name-collision documented) |
| 3 | check_model clean | PASS — no errors/warnings |
| 4 | run_simulation converges | PASS — normal termination, 0.034 s |
| 5 | postprocess + model_status + validate_model | PASS — heads 0–1 (mean 0.5), CHD balance closes (net -1.5e-8), grid `nlay 1 / nnodes 228 / nja 1372`, runnable, clean |
| 6 | new DISU build + obs + setup_calibration | PASS — converged 3-node DISU; sequential obs mapping works; pst + template + instruction generated |
| 7 | x/y-dependent ops on vertex-less DISU | PASS (as designed) — clear INVALID_INPUT, no head map produced |
| 8 | run-log.md | this file |

### Notable tool behaviours / friction

1. DISU is flattened to `nlay=1`; per-layer tools (`read_heads` layer>0) fail
   with a clear range error even though the physical model is 3 layers.
2. `add_boundary_package` on DISU needs a single-element node cell id
   (`[node]`); a `[layer,node]` id is silently truncated to its first element
   and produced a duplicate-constant-head run failure.
3. Builder edits are staged in memory; `flush_model` is required before the
   on-disk file reflects a re-add.
4. `run_simulation` can hit the client timeout on an otherwise instant run;
   `get_run_log` confirms termination and outputs are written.
5. A model name reused across sessions resolves to the older registration;
   use a unique name (or delete the stale registration).
