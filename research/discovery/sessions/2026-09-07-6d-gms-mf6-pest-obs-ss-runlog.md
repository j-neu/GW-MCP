# Validation Run Log — Phase 6d target 4 (GMS MODFLOW 6 PEST Observations, steady state)

- Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss`
- Run date: 2026-09-07 (closed-book; no MCP repo source, tests, .kilo plans, or prior session logs read)
- Data: `D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
  (Aquaveo GMS 10.9 tutorial `mf6_pest_obs_ss`)
- Working copy / artifacts: `phase6d\` under the session folder (`extract\` + outputs + helper scripts)

---

## 1. Environment stack (`check_environment`)

| Component | Value |
|---|---|
| Python | 3.12.11 (venv `D:\Claude Projects\GW-MCP\.venv`) |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / ies / sen / opt / da | all present |
| Docs index | built |
| Workspace root | `C:\Users\jakob\.groundwater-mcp\workspaces` |
| `ready` | `true` (nothing missing) |

## 2. Data layout (zip, verified by listing before use)

- `sample\pest_obs_ss_MODFLOW-quadtree_mf6\` — shipped runnable MF6 input set (**the adopted model**):
  `mfsim.nam`, `pest_obs_ss.{nam,disv,ic,ims,npf,oc,rch,tdis,riv,chd,wel}` + GMS extras (`gsf/vtu/xmc/mfn.log`).
  1-layer DISV grid: NLAY 1, NCPL 3306, NVERT 3796; LENGTH_UNITS **FEET**, TIME_UNITS **DAYS**;
  NPF K = 2.4 (CONSTANT, confined icelltype −1); RCH = 7.62e-05; RIV 451 reaches; WEL 3 cells;
  CHD 42 records in the shipped file; OC → `pest_obs_ss.hed`/`pest_obs_ss.ccf`.
- `sample\pest_obs_ss_MODFLOW-quadtree\` — MODFLOW-USG (DISU) variant — **out of scope** (not used).
- `sample\pest_obs_ss_models\MODFLOW 6\pest_obs_ss\` — **solved reference artifacts**:
  - `GWF_Model_output\GWF_Model.hds/.cbc`, `pest_obs_stats.txt`
  - `GWF_Model_pest\` obs interface: `model.n2b` (10 bores, 4-cell interpolation each),
    `model.blisting`, `model.bsamp` (observed heads), `model.bsamp.out` (reference simulated heads),
    `model.b2b` (RIV CELLGRP 1–6 → compound `FLOW`), `model.fsamp` (observed FLOW −4644),
    `model.fsamp.out`/`model.samp` (reference simulated FLOW −5434.209358), `obs.out`
    (mf6mod2obs/mf6bud2smp console transcript), plus mf6bud2smp/mf6mod2obs `*.in`.
  - Reference model parameters are identical to the shipped base model (K=2.4, RCH=7.62e-05,
    same grid), so `pest_obs_stats.txt` describes the **uncalibrated base run** residuals.
  - No PEST `.pst` / `.tpl` / `.ins` files are shipped anywhere in the zip.

## 3. Decisions and deviations from the source model

1. **Adoption.** `adopt_model(name="pest_obs_ss", workspace=<mf6 folder>, units="FEET",
   time_units="DAYS", allow_modify=True)`. `allow_modify=True` was required because calibration
   (and any builder call) is refused on read-only adopted models and this run explicitly exercises
   the calibration chain on the adopted model. Registered model name `pest_obs_ss`
   (internal model name in files: `gwf_model`).
2. **Deviation A (correctness fix, CHD duplicate).** The shipped `pest_obs_ss.chd` lists cell
   **(1,32) twice**: head 78.11037 (CELLGRP 1) and head 226.6896 (CELLGRP 2). MF6 aborts with
   `ERROR: Cell is already a constant head ((1,32))`. The shipped solved reference
   (`GWF_Model.chd` + `GWF_Model_input\GWF_Model.chd_1.txt`) uses **41 single records, all
   head 304.8 ft** (cell 32 appears once). Fix made through MCP only: re-added the CHD package via
   `add_boundary_package(package="CHD", stress_period_data={0: 41 × [[0,node],304.8]})` then
   `flush_model`. Auxiliary SHEADFACT/EHEADFACT/CELLGRP columns (GMS transient-interpolation only,
   not used in this steady run) were dropped, as they were in the reference.
3. **Deviation B (output naming).** GMS OC writes head/budget to `pest_obs_ss.hed`/`.ccf`;
   the MCP postprocess tools only discover `.hds` and `.cbb`/`.cbc` (`OUTPUT_FILE_MISSING`).
   Re-added the OC package via `add_oc_package(head_filerecord="pest_obs_ss.hds",
   budget_filerecord="pest_obs_ss.cbc", saverecord=HEAD/BUDGET FIRST, printrecord=BUDGET FIRST)`
   and flushed. Physics unchanged (single steady stress period, 1 timestep).
4. **Deviation C (format re-serialisation).** Because the model was adopted with `allow_modify`
   and a flush occurred, the whole input set was re-written on disk by flopy in canonical layout
   (all package files regenerated; original orphaned `pest_obs_ss.chd` (duplicate version),
   `pest_obs_ss.oc`, `pest_obs_ss.hed`, `pest_obs_ss.ccf` remain in the folder but are not
   referenced by `mfsim.nam`/`pest_obs_ss.nam`). All parameter values are unchanged.
5. **Postprocessing of binary outputs** is performed with the MCP tools only; a single
   `read_heads` output `.npy` plus plotting output are consumed by ordinary Python only for the
   reference comparison (reading the solved reference + MCP output, as permitted).

## 4. Tool-call sequence

| # | Tool | Result |
|---|---|---|
| 1 | `check_environment` | stack ready (see §1) |
| 2 | shell `Expand-Archive` | zip extracted to `phase6d\extract\mf6_pest_obs_ss\` |
| 3 | `adopt_model(name=pest_obs_ss, ..., allow_modify=True)` | adopted; model `gwf_model` |
| 4 | `check_model` | **clean** — no errors/warnings (riv/wel/chd/NPF checks pass) |
| 5 | `model_status` | runnable=true, nothing missing |
| 6 | `summarise_model` | **FAILS on DISV**: `'ModflowGwfdisv' object has no attribute 'nrow'` (tool gap) |
| 7 | `run_simulation` | **FAILS**: duplicate CHD cell (1,32) — see Deviation A |
| 8 | `add_boundary_package(package=CHD, 41 records @304.8)` + `flush_model` | CHD replaced |
| 9 | `check_model` (again) | clean |
| 10 | `run_simulation` | **converged / Normal termination**, 0.21–0.27 s |
| 11 | `read_heads` | **FAILS**: no `.hds` (outputs are `.hed`) — see Deviation B |
| 12 | `compute_water_balance` | **FAILS**: no `.cbb/.cbc` (outputs are `.ccf`) — see Deviation B |
| 13 | `add_oc_package(..., .hds/.cbc)` + `flush_model` | OC re-pointed |
| 14 | `run_simulation` | **converged / Normal termination** (final) |
| 15 | `read_heads` | ok: layer 0, 3306/3306 active; min 304.8, max 316.636, mean 309.969 |
| 16 | `compute_water_balance` | closes (see §6) |
| 17 | `plot_heads_map` | PNG written (`phase6d\pest_obs_ss_heads_map.png`); could not be rendered inline (no image input in this session model) |
| 18 | `list_model_files`, reads of shipped reference files | reference inventory + interface understood |
| 19 | obs CSV preparation (python, reading shipped `model.n2b/.bsamp/.fsamp` + model `.disv`) | `phase6d\heads_obs.csv`, `phase6d\flow_obs.csv` |
| 20 | `import_obs_from_csv(obs_type=HEAD, x_col/y_col)` | **FAILS on DISV**: `OBS_IMPORT_FAILED: 'ModflowGwfdisv' object has no attribute 'ncol'` |
| 21 | fresh pristine probe copy: `adopt_model(name=pest_probe)` + `import_obs_from_csv` (no coordinates) | sequential mode works on DISV but maps row k → node k (cells 1…10), i.e. cannot target the shipped obs cells; probe model deleted |
| 22 | `clone_model(pest_obs_ss → pest_ss_cal)` + `import_obs_from_csv` (coords) | same `ncol` failure (reproducible) |
| 23 | `setup_calibration(obs_source="model", parameterisation k)` on clone | **FAILS on DISV**: `PEST_ERROR: 'ModflowGwfdisv' object has no attribute 'nrow'`; clone deleted |
| 24 | — | **STOPPED** per MCP-only constraint (see §8) |

No permission reprompts occurred during the run.

## 5. Model state (final, on disk in the adopted workspace)

`mfsim.nam` → `pest_obs_ss.tdis`, 1 GWF (`gwf_model`) → `pest_obs_ss.nam` listing
`chd6 gwf_model.chd`, `disv6 pest_obs_ss.disv`, `rch6/riv6/wel6/npf6/ic6 pest_obs_ss.*`,
`oc6 gwf_model.oc`. OC saves HEAD+BUDGET FIRST to `pest_obs_ss.hds`/`.cbc`.
CHD: 41 boundary cells @ 304.8 ft (matches solved reference). NPF K=2.4, RCH=7.62e-05 unchanged.

## 6. Convergence evidence and post-processing (MCP tools)

- Final `run_simulation`: `success=true`, `convergence="converged"`, elapsed 0.21 s,
  `Normal termination of simulation.` Only warnings are IMS deprecation notices
  (OUTER_HCLOSE/INNER_HCLOSE renamed to *_DVCLOSE, informational). Solver: IMS simple/moderate
  defaults, CG linear acceleration; single stress period of 1 day, 1 timestep.
- `read_heads` (kstpkper [0,0], layer 0): n_active 3306, min 304.8, max 316.636, mean 309.969 ft.
- `compute_water_balance` (ft³/d):

  | term | value |
  |---|---|
  | IN RCHA | +5811.635 |
  | OUT WEL | −130.000 |
  | OUT RIV | −5434.207 |
  | OUT CHD | −249.961 |
  | net | −2.533 |

  Percent discrepancy ≈ 100·|net|/(mean of in/out magnitudes) ≈ **0.04 %** → closes.
- `plot_heads_map` produced `phase6d\pest_obs_ss_heads_map.png` (246 KB).

## 7. Reference comparison (rerun vs shipped solved reference)

Using the shipped `model.n2b` interpolation weights and the `read_heads` array:

| site | obs head | ref sim | our sim | resid(ref) | resid(our) |
|---|---|---|---|---|---|
| POINT_#1 | 310.62 | 307.372 | 307.372 | 3.25 | 3.25 |
| POINT_#2 | 304.80 | 306.020 | 306.020 | −1.22 | −1.22 |
| POINT_#3 | 316.53 | 309.985 | 309.985 | 6.55 | 6.55 |
| POINT_#4 | 334.67 | 313.634 | 313.634 | 21.04 | 21.04 |
| POINT_#5 | 308.61 | 308.189 | 308.188 | 0.42 | 0.42 |
| POINT_#6 | 327.05 | 314.123 | 314.123 | 12.93 | 12.93 |
| POINT_#7 | 327.66 | 314.645 | 314.645 | 13.02 | 13.02 |
| POINT_#8 | 316.99 | 312.771 | 312.771 | 4.22 | 4.22 |
| POINT_#9 | 329.18 | 315.201 | 315.202 | 13.98 | 13.98 |
| POINT_#10 | 316.38 | 313.473 | 313.474 | 2.91 | 2.91 |

- Head statistics: **mean residual 7.7077, mean abs 7.9517, RMSE 10.2748** for both the reference
  sim and our sim (differences ≤ 0.0007 ft), matching the shipped `pest_obs_stats.txt`
  exactly (7.707681 / 7.951675 / 10.274824). → our rerun reproduces the shipped solved reference.
- Flow: reference simulated compound FLOW −5434.209 vs our RIV outflow −5434.207 (Δ ≈ 0.003 ft³/d,
  < 1e-6 relative).
- The shipped obs.out transcript confirms the reference simulated obs were produced by
  mf6mod2obs/mf6bud2smp on the same base parameter run.

## 8. Calibration — STOPPED, capability gap (MCP-only constraint)

Success criterion 6 (calibrate through the MCP chain `setup_pest_control` → `run_pestpp_glm` →
`summarise_calibration` against the shipped PEST interface) **cannot be satisfied for this model
through the groundwater-mcp tools**, and per the run instructions I did not work around the gap
with raw flopy/pyemu or hand-written PEST files.

Evidence collected:
1. The shipped observation set is 10 head bores at **scattered DISV cells** (nodes e.g. 685/761,
   2127/2128, 3124/3153 …, with 4-cell interpolation weights) plus 1 **compound flow observation**
   (sum of RIV leakage over CELLGRP groups 1–6, observed −4644 ft³/d, simulated −5434 ft³/d).
2. `import_obs_from_csv` **coordinate mapping is DIS-only**: on this DISV model every coordinate
   call throws `OBS_IMPORT_FAILED: 'ModflowGwfdisv' object has no attribute 'ncol'`
   (reproduced on the base model and on a fresh clone). The model grid carries no CRS and the DISV
   grid type is inherently unsupported in this path.
3. Sequential registration (no coordinates) works on DISV but assigns rows to cells **1…10 by node
   order** (`site_cellid_map`: [0,0,0]…[0,9,0]) — those are constant-head boundary cells, not the
   shipped observation locations, so it cannot represent the shipped interface and would make the
   calibration meaningless (and non-comparable to `pest_obs_stats.txt`).
4. `setup_calibration(obs_source="model")` (the only MCP generator of PEST template/instruction/.pst
   files) throws `PEST_ERROR: 'ModflowGwfdisv' object has no attribute 'nrow'` on this DISV model.
5. `setup_pest_control` (manual) requires pre-existing `template_files`/`instruction_files`; none are
   shipped in the zip and no MCP tool can generate them for a DISV grid. Hand-writing PEST files is
   prohibited by the run rules.
6. `summarise_model` likewise fails on DISV (`nrow`), indicating the obs/calibration/reporting layer
   of the server assumes structured (DIS) grids only.

**Missing capability (exact):** observation registration, calibration setup, and model summary in the
groundwater-mcp server assume a structured DIS grid and dereference `nrow`/`ncol` on the grid object.
Unstructured **DISV** grids (GMS quadtree exports, like this tutorial model) are unsupported by
`import_obs_from_csv` (coordinate mode), `setup_calibration`, and `summarise_model`, so an
observation-driven PEST calibration cannot be set up or run for this model. A multi-cell / budget-type
flow observation (the GMS `FLOW` compound over 6 RIV CELLGRPs) is also not representable by the obs
import interface even on a DIS grid.

Consequently `setup_pest_control`, `run_pestpp_glm` and `summarise_calibration` were **not reached**;
no calibration results exist to compare against the shipped reference. The shipped
`pest_obs_stats.txt` itself is the statistics of the *uncalibrated* base run, which we reproduced
exactly (§7).

## 9. Files produced in the session folder

- `phase6d\extract\` — extracted tutorial; adopted/rewritten MF6 workspace inside
  `...\pest_obs_ss_MODFLOW-quadtree_mf6\` (model `pest_obs_ss`)
- `phase6d\pest_obs_ss_heads_map.png` — heads map (MCP `plot_heads_map`)
- `phase6d\pest_obs_ss_heads_l0_k0_0.npy` — layer-0 head array (MCP `read_heads`),
  also in the model workspace
- `phase6d\heads_obs.csv`, `phase6d\flow_obs.csv` — observations transcribed from the shipped
  PEST interface (`model.n2b` + `model.bsamp` + `model.fsamp`) for attempted import
- `phase6d\prepare_obs_csv.py`, `phase6d\compare_reference.py` — data-prep / reference-comparison scripts
- `run-log.md` — this log

## 10. Success-criteria assessment

1. ✅ `check_environment` run; stack reported (§1).
2. ✅ Zip extracted; model adopted via `adopt_model` into an MCP workspace without rebuilding the grid;
   reference artifacts preserved in place and compared (§7).
3. ✅ `check_model` clean (after the CHD fix).
4. ✅ `run_simulation` converged / normal termination (verified via listing log too).
5. ✅ Post-processing: `read_heads`, `compute_water_balance` (closes, ~0.04 %), `plot_heads_map`.
6. ❌ Calibration chain blocked by a documented tool capability gap (DISV obs/calibration support);
   stopped per the MCP-only rule rather than working around with raw flopy/pyemu.
7. ✅ This `run-log.md` written.
