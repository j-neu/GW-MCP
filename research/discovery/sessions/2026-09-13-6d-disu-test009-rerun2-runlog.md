# Phase 6d capability validation — DISU (fully unstructured grid)

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-disu-test009-rerun2`
Date: 2026-09-13
Source model: `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu` (MODFLOW 6 test009, 3-layer DISU with a nested grid in layer 2)
Constraint: every build/adopt/run/post-process/calibrate action went through a groundwater-mcp tool. No raw flopy/pyemu MODFLOW classes were called and no MODFLOW input file was hand-edited.

---

## 1. Environment (check_environment)

```
python        3.12.11  (D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe)
flopy         3.10.0
pyemu         1.4.0
geopandas     1.1.3
rasterio      1.5.0
numpy         2.4.4
scipy         1.17.1
matplotlib    3.10.8
mf6           C:\Users\jakob\.local\bin\mf6.exe
pestpp-glm    C:\Users\jakob\.local\bin\pestpp-glm.exe
pestpp-ies    C:\Users\jakob\.local\bin\pestpp-ies.exe
docs_index_built: true
workspace_root:   C:\Users\jakob\.groundwater-mcp\workspaces
missing: {}
ready: true
```
Stack ready, no missing packages or binaries.

## 2. Model spec read from the model's own files (allowed — the specification)

- `mfsim.nam`: one GWF6 model `flow.nam`, model name `GWF_1`.
- `flow.nam`: DISU6, IC6, CHD6, NPF6, **GNC6**, OC6 (ghost-node corrections present).
- `flow.tdis`: `TIME_UNITS DAYS`, NPER 1, perlen 1.0, nstp 1, tsmult 1.0.
- No `LENGTH_UNITS` declared → MF6 default **METERS**.
- `flow.disu`: NODES 228, NJA 1372; top = 0 (nodes 1–76) / -10 (77–152) / -20 (153–228); area 10000 (2500 nested); IAC/JA/IHC/CL12/HWVA/ANGLDEGX provided; **no vertices/cell2d**.
- `flow.npf`: ICELLTYPE CONSTANT 0, K CONSTANT 1.0, K33 CONSTANT 1.0.
- `flow.ic`: STRT CONSTANT 1.0.
- `flow.chd`: 48 nodes; north ring head 1.0, south ring head 0.0. **DISU CHD records use a single node index** (`1 1.0`, `2 1.0`, …, not layer,node).
- `flow.gnc`: 48 ghost-node corrections, NUMALPHAJ 2.
- `flow.ims`: outer_dvclose 1e-8 / inner_dvclose 1e-8 / bicgstab.
- `flow.oc`: SAVE/PRINT HEAD+BUDGET ALL.

## 3. Adoption (criterion 2)

Copied the 11 source files verbatim into `.\test009_3lay-disu\` (no grid rebuild, no edits), then:

```
adopt_model(name="test009disu", workspace="...\test009_3lay-disu",
            units="METERS", time_units="DAYS", allow_modify=true)
→ adopted: true, model_names: ["gwf_1"]
```
Model name `test009disu` is 11 chars (≤16). Length units are the MF6 default METERS; time units are the DAYS the model declares.

## 4. check_model (criterion 3)

```
check_model("test009disu") → check_passed: true, errors: [], warnings: []
  chd-1: BC indices valid / no NaNs / BCs in active cells
  npf:   K values within checker thresholds
```
Clean, no documented exceptions needed.

## 5. run_simulation + convergence (criterion 4)

Ran in the background (`start_run`) to avoid a client timeout; `get_job_status` returned:
```
status: succeeded, convergence: "converged", returncode: 0, elapsed_s: 0.11
listing: "Normal termination of simulation."
```
`get_run_log` tail confirms: `2 CALLS TO NUMERICAL SOLUTION IN TIME STEP 1 STRESS PERIOD 1`, `13 TOTAL ITERATIONS`, elapsed 0.053 s, **Normal termination**.

## 6. Post-processing on the adopted model (criterion 5)

**read_heads** (layer 0, kstpkper 0,0):
```
shape [1,228], n_active 228, min 0, max 1, mean 0.5000000000292736
```
Linear north(1.0)→south(0.0) gradient, symmetric as expected.

**compute_water_balance**:
```
inflow  CHD  34.285714275882754
outflow CHD -34.285714290935720
net_balance  -1.5052968649342802e-08     → closes
```

**summarise_model — grid block verbatim**:
```json
"grid": {"type": "DISU", "nlay": 1, "nnodes": 228, "ncells": 228, "nja": 1372}
```
(packages: DISU, IC, CHD-1, NPF, GNC, OC; units length METERS / time DAYS / k m/d.)
Note: the summariser reports the DISU grid as **nlay 1** with 228 nodes — DISU is a single node-index space, so the 3-layer structure is not surfaced as an `nlay` of 3.

**model_status**:
```
runnable: true, missing_required: [], missing_recommended: [], next_steps: [], warnings: []
```

**validate_model**:
```
clean: true, findings: []
```

## 7. New DISU builder path (criterion 6)

Built a brand-new 3-node line model `disu3line` (workspace `.\disu3line`) purely through MCP builder calls:

```
create_model("disu3line", METERS, DAYS)
set_simulation(nper=1, perlen=[1], nstp=[1])
add_disu_package(nodes=3, nja=7, top=[0,0,0], bot=[-10,-10,-10],
                 iac=[2,3,2], ja=[0,1,1,0,2,2,1],
                 area=[1,1,1], idomain=[1,1,1],
                 cl12=[0,1,0,1,1,0,1], hwva=[1,1,1,1,1,1,1], ihc=<see below>)
add_npf_package(icelltype=0, k=1)
add_ic_package(strt=0.5)
add_oc_package()
add_boundary_package("CHD", {"0": [[[0],1.0],[[2],0.0]]})
flush_model()
```

### Retries / reprompts during this step (all self-diagnosed; no user reprompt)

1. **Node-numbering failure.** First `add_disu_package` used `ihc=[0,…]` (all zero). `run_simulation` failed:
   `"Top elevation (0.0) for cell 2 is above bottom elevation (-10.0) for cell 1. Based on node numbering rules cell 2 must be below cell 1."`
   Cause: in DISU, `IHC` distinguishes connection orientation, and `IHC=0` made MF6 treat the three connections as a **vertical stack**, triggering the node-numbering rule. In the reference `flow.disu`, same-layer connections carry `ihc=1` and cross-layer connections carry `ihc=0`. Fix: re-added DISU with `ihc=[0,1,0,1,1,0,1]` (self-connections 0, in-line connections 1). Node-numbering check then passed.

2. **Duplicate CHD cell.** Second run failed:
   `"Cell is already a constant head ((1))."` Reading the generated `disu3line.chd` showed two records both resolving to node 1. Cause: for DISU the boundary `cellid` is a **single node index**, but I passed two-element cellids `[0,0]` / `[0,2]` (DIS-style layer,row,col). The tool collapsed both to node 1. Fix: re-added CHD with single-element cellids `{"0": [[[0],1.0],[[2],0.0]]}`, which wrote node 1 (head 1.0) and node 3 (head 0.0). Note: this is a DISU-specific cellid convention; the tool documentation describes `(layer,node)` for DISV and does not spell out the single-node form for DISU.

### Final builder results
```
check_model("disu3line") → check_passed: true, errors: []
  warnings: ["cell2d information missing…", "vertices information missing…"]   (expected for a vertexless DISU)
model_status → runnable: true, nothing missing
run_simulation → success: true, convergence: "converged", Normal termination
read_heads → shape [1,3], min 0, max 1, mean 0.5
```

### Observations (CSV without x/y)
`obs_seq.csv` = `site,value,date` rows n1=1.0, n2=0.5, n3=0.0 (no x/y columns). `import_obs_from_csv` reported:
```
site_count 3, site_cellid_map {"n1":1,"n2":2,"n3":3}
```
Sequential node mapping works on DISU. A re-run then produced `observation_fit: {n:3, rmse:0, bias:0, mae:0, r2:1}` (observed values were set equal to the converged heads).

### Calibration setup (obs_source="model")
```
setup_calibration(disu3line,
    parameterisation={"k": {"target":"npf:k","scope":"all","initial":1.0}},
    obs_source="model")
→ pst_file        .\disu3line.pst
   template_file   .\disu3line_k.dat.tpl
   target_file     .\disu3line_k.dat
   instruction     .\disu3line_head.obs.csv.ins
   forward_wrapper C:\Users\jakob\AppData\Local\Temp\gwmcp_run_disu3line.py
   n_observations 3, n_adjustable_parameters 1
   parameter k: initial 1.0, bounds 0.1–10, partrans log
```
No errors — the zero-hand-written-file calibration interface built fine on DISU.

### Calibration run
`run_pestpp_glm` returned an MCP **client timeout**, but the run had actually completed (`.rec`, `.iobj`, `run.info`, `.jcb`, `.par.usum.csv` all written). `summarise_calibration`:
```
phi_progress: iter 0 phi 0 → iter 1 phi 0
k: initial 1.0 → estimated 1.0 (not at bounds)
residuals: n1/n2/n3 all 0; rmse 0, bias 0, r² 1
verdict: improved true, final_phi 0
```
(The perfect fit is expected — the synthetic observations equal the forward solution; the point is that the GLM path executes end-to-end on DISU.)

## 8. x/y-dependent operations on a vertexless DISU (criterion 7)

**plot_heads_map** on both `disu3line` and `test009disu`:
```
error: INVALID_INPUT
message: "plot_heads_map requires cell x/y geometry, which this discretisation does not carry
          (a DISU grid defined without vertices). Use read_heads or compute_water_balance instead."
```
**No head map is produced.** The tool fails fast and redirects the caller.

**Coordinate-based import_obs_from_csv** (`x_col`/`y_col` supplied) on `disu3line`:
```
error: INVALID_INPUT
message: "This grid has no cell-centroid x/y coordinates (a DISU grid defined without
          vertices/geometry). Coordinate-based operations are unavailable — use sequential
          node/cell mapping instead."
```
Sequential mapping is the supported alternative and works (section 7).

## 9. Deviations from the source model

- **Adopted model `test009disu`:** zero deviations — files were copied byte-for-byte, adopted as-is, not modified (grid not rebuilt), and run with the model's own DISU/GNC/CHD data.
- **New model `disu3line`:** synthetic and unrelated to the source geometry. It is a *horizontal* 3-node line, so its in-line connections are marked `ihc=1` (the vertical-stack interpretation with `ihc=0` was rejected by MF6's node-numbering rule). `cl12/hwva/area` were supplied because a vertexless DISU still needs connection geometry for conductance.

## 10. Capability verdict

| Capability | DISU result |
|---|---|
| check_environment | ready |
| adopt_model (no rebuild, allow_modify) | works; internal name `gwf_1` adopted under `test009disu` |
| check_model | passes clean (adopted); passes with expected cell2d/vertices warnings (built) |
| run_simulation | converges, Normal termination (both models) |
| read_heads / compute_water_balance | work; balance closes to ~1.5e-8 |
| summarise_model / model_status / validate_model | all work; DISU grid shown as nlay 1 / 228 nodes / nja 1372 |
| add_disu_package builder path | works (after correct `ihc`; see §7) |
| import_obs_from_csv sequential | works (node-index mapping) |
| import_obs_from_csv coordinate-based | unavailable — clean INVALID_INPUT |
| setup_calibration + PEST++-GLM | works on DISU; client timeout on sync GLM call but run completes |
| plot_heads_map | unavailable — clean INVALID_INPUT, no map produced |

The MCP toolchain is sufficient for the DISU capability row. The only gaps are the two inherently geometry-dependent operations (head-map plotting and coordinate-based observation mapping) on a DISU grid that carries no vertices; both fail explicitly rather than silently, and both offer the supported workaround (`read_heads` / sequential node mapping).
