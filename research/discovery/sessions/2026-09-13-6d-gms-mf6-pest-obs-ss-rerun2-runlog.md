# Run log — Phase 6d target 4: GMS MODFLOW 6 PEST observations (closed-book validation)

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun2`
Data zip: `D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
Constraint: all build/adopt/run/postprocess/calibrate actions on the MF6 model were done
through `groundwater-mcp` tools. Raw Python was used only to *read* the shipped solved
reference / PEST interface (model.b2map, model.bwt, model.fsamp) and to extract a
tool-input CSV. No flopy/pyemu MODFLOW or PEST classes were called; no MODFLOW/PEST file
was hand-edited.

## 1. Environment (`check_environment`)

- ready = true; Python 3.12.11 at `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8, whoosh 2.7.4
- mf6: `C:\Users\jakob\.local\bin\mf6.exe`
- pestpp-glm / ies / sen / opt / da all present
- missing packages = [], missing binaries = []

## 2. Data extraction and model inventory

Extracted to `data\mf6_pest_obs_ss`. The shipped runnable MODFLOW 6 set is
`data\...\sample\pest_obs_ss_models\MODFLOW 6\pest_obs_ss\`.

Model specification (read from the tutorial files, which are the spec):

- Grid: **DISV**, nlay=1, ncpl=3306, nvert=3796 (`GWF_Model.disv`; TOP/BOTM/CELL2D/VERTICES via `GWF_Model_input\`).
- Time: 1 steady stress period, `perlen=1 d`, `nstp=1` (`pest_obs_ss.tdis`).
- Solver: IMS SIMPLE, outer dvclose 0.01 / max 500, Cooley under-relaxation (`pest_obs_ss.ims`).
- Packages: DISV, OC, RCH (READASARRAYS), RIV, WEL, CHD, NPF, IC.
- Units: `LENGTH_UNITS FEET`, `TIME_UNITS DAYS`.
- NPF: `ICELLTYPE -1` (convertible), `K CONSTANT 2.4` (ft/d), SAVE_FLOWS, AMT-HMK, DEWATERED, PERCHED.
- RCH: uniform `7.62e-05` (ft/d).
- CHD: 41 cells at 304.8 ft (two cell groups). WEL: 3 wells (nodes 2200 q=-15, 1374 q=-30, 536 q=-85 ft^3/d).
- RIV: 451 reaches (stage, cond, rbot + AUX IFACE/CONDFACT/CELLGRP).

## 3. Adoption

Copied the shipped runnable set to `run\pestobs_ss` (so the shipped reference inputs/outputs
stay pristine) and adopted the copy — this is the same `sample/…_models/MODFLOW 6/` output
the task points at.

- `adopt_model(name="pestobs_ss", workspace=run\pestobs_ss, units="FEET", time_units="DAYS", allow_modify=true)`
- Result: `adopted=true`, `model_names=["gwf_model"]`, `allow_modify=true`.
- One reprompt: first adopt defaulted to `units=METERS`; the source DISV declares FEET, so
  the model was unregistered (`delete_model`, remove_files=false) and re-adopted as FEET.
- `allow_modify=true` was required because the task needs an OBS package and a PEST
  calibration rewiring NPF K (both are save_sim-backed builder changes).

## 4. Pre-run checks

- `model_status`: runnable=true, missing_required=[], missing_recommended=[].
- `check_model`: `check_passed=true`, **no errors or warnings** (RIV/WEL/CHD indices, NaN, inactive-cell, NPF K range checks all passed).

## 5. Base run and postprocessing

- `run_simulation`: success=true, convergence="converged", elapsed 0.198 s, "Normal termination of simulation".
- `get_run_log` (tail): confirms `Normal termination of simulation`.
- `read_heads` (layer 0): min 304.8, max 316.6358, mean 309.9685, n_active 3306.
- `compute_water_balance` (base):

  | term | value (ft^3/d) |
  |---|---|
  | inflow RCHA | +5811.635216 |
  | outflow WEL | -130.0 |
  | outflow RIV | **-5434.209358** |
  | outflow CHD | -249.957995 |
  | net | -2.532137 |

- `diagnose_water_balance`: discrepancy -0.0436 %, `balanced=true`, dominant_inflow RCHA (~50 %), not boundary-dominated.
- `plot_heads_map` → `run\heads_map_base.png`.

**Reference check:** the shipped simulated RIV discharge (`model.samp` / `model.fsamp.out`)
is **-5434.209358**, an exact match to the MCP base run. The adopted model reproduces the
published solution to the printed precision.

## 6. Observations from the shipped PEST interface

The shipped interface stores the bores in `GWF_Model_pest\model.b2map` (JSON: `geometry =
[x, y, observed]`), weights in `model.bwt` / `model.fwt`, and the compound river-discharge
observation in `model.fsamp` (FLOW = -4644.0). `model.pobs` is empty (0 bytes).

- 10 head observations (`model.b2map` POINT_ entries), values: 310.62, 304.8, 316.53,
  334.67, 308.61, 327.05, 327.66, 316.99, 329.18, 316.38 ft at their bore (x,y).
- 1 flow observation: total RIV discharge, observed **-4644.0** ft^3/d (weight 0.009333).
- Extracted `run\obs_points.csv` (site,date,value,x,y,weight) with `run\make_obs_csv.py`.
- `import_obs_from_csv(obs_type=HEAD, x_col=x, y_col=y, layer=0)` → 10 sites registered,
  mapped to nearest DISV cells: #1→[0,761], #2→[0,624], #3→[0,1167], #4→[0,1449],
  #5→[0,1626], #6→[0,2350], #7→[0,2127], #8→[0,2427], #9→[0,3152], #10→[0,3026].

### Flow observation — MCP capability gap (reported)

`import_obs_from_csv(obs_type="FLOW")` is refused:

> Unsupported obs_type 'FLOW'. MODFLOW 6 OBS continuous types supported here are
> ['CONCENTRATION','DEPTH','DRAWDOWN','HEAD','TEMPERATURE']. Compound flux observations
> (e.g. total river discharge over a cell group) are not representable by an OBS6 continuous
> type — evaluate them with compute_water_balance instead of registering them as observations.

The shipped observation is exactly such a compound flux (aggregate over 6 RIV cell groups,
`model.b2b`). The MCP therefore cannot register it as a PEST observation. This is a genuine
missing capability; it was **not** worked around with raw pyemu. Per the MCP's own suggestion
the flow metric was evaluated with `compute_water_balance` (Section 5/8). The calibration is
consequently head-only.

## 7. Base observation fit vs shipped reference

Re-ran with the OBS package; `run_simulation` returned `observation_fit` and
`compare_to_observed` produced the residual table and scatter (`run\obs_scatter_base.png`).

| statistic | MCP base run (10 head obs, cell-mapped) | shipped reference (`pest_obs_stats.txt`, n2b-interpolated, weighted) |
|---|---|---|
| mean residual / bias | 7.743138 | 7.707681 |
| mean abs residual | 7.989456 | 7.951675 |
| RMSE | 10.295904 | 10.274824 |
| R^2 | -0.19756 | — |

Agreement is within ~0.02–0.04. Residuals agree cell-by-cell in sign and magnitude, e.g.
POINT_4 +21.036 (vs +21.036 in the reference table), POINT_9 +13.979, POINT_7 +13.014,
POINT_6 +12.981. The small differences are explained by (a) the MCP OBS samples the nearest
single cell while the shipped interface interpolates each bore from up to 4 nodes
(`model.n2b`), and (b) the shipped stats are weighted with `model.bwt`/`model.fwt` while the
MCP importer carries no weight column.

Flow: base RIV discharge -5434.209358 (exact reference), observed -4644.0 → residual
+790.209358, identical to the reference `Flow: Mean residual: 790.209358`.

## 8. Calibration through the MCP chain

Chain used: **`setup_calibration` → `run_pestpp_glm` → `summarise_calibration`**.

Decision: the task names `setup_pest_control`, but that tool requires template/instruction
files to already exist and hand-writing them is prohibited. The MCP's `setup_calibration`
is the supported zero-hand-written-file entry point that generates them (it wrote
`gwf_model_k.dat.tpl`, `gwf_model_head.obs.csv.ins`, the forward wrapper and the `.pst`);
it subsumes `setup_pest_control`.

Parameterisation limits found:
- `setup_calibration` accepts **only `npf:k`** as a target (`rch:recharge` was refused:
  `Unsupported parameterisation target 'rch:recharge'. Supported: ['npf:k']`). So recharge and
  river conductance — plausible GMS calibration targets — are not adjustable through this
  automatic path. Only hydraulic conductivity was calibrated.

Setup (`obs_source="model"`, noptmax 20):

- K, scope `all`, initial 2.4, bounds 0.24–24, partrans log → 1 adjustable parameter, 10 obs.
- The MCP rewired `GWF_Model.npf` K to `OPEN/CLOSE 'gwf_model_k.dat'` and templated the whole
  array with token `hk_all`.
- `.pst`: `run\pestobs_ss\pestobs_ss.pst`.

GLM run:

- `run_pestpp_glm` hit the client timeout, but the server-side `pestpp-glm` process completed.
  Progress read from `pestobs_ss.iobj` and final results via `summarise_calibration`
  (use `start_calibration` + `get_job_status` for long jobs in future).
- phi: 1060.06 → 208.037 → 116.826 → 116.504 → 116.504 (converged at iteration 4).

| quantity | value |
|---|---|
| adjustable parameters | 1 (`hk_all`) |
| initial K | 2.4 ft/d |
| calibrated K | **0.552074** ft/d (bounded 0.24–24, no bound hit) |
| final phi (unweighted SSR) | 116.504 |
| calibrated head RMSE | 3.413275 |
| calibrated bias | -0.471250 |
| calibrated MAE | 2.326371 |
| calibrated R^2 | 0.868383 |
| verdict | improved=true, parameters_at_bounds=[] |

Post-calibration `run_simulation` reproduced the PEST result exactly (RMSE 3.413275), and
`read_heads`: min 302.772, max 332.479, mean 315.182.
`plot_heads_map` → `run\heads_map_calibrated.png`.

## 9. Reference comparison summary

| metric | shipped reference | MCP base | MCP calibrated |
|---|---|---|---|
| head mean residual | 7.707681 | 7.743138 | -0.471250 |
| head MAE | 7.951675 | 7.989456 | 2.326371 |
| head RMSE | 10.274824 | 10.295904 | **3.413275** |
| flow (RIV discharge) | -5434.209358 | -5434.209358 | -5535.432122 |
| flow residual (obs - sim, obs=-4644.0) | +790.209358 | +790.209358 | +891.432122 |
| weighted combined RMSE | 11.134540 | n/a (unweighted) | n/a (unweighted) |

The MCP base run reproduces the shipped solved reference (heads to ~0.02 RMSE and flow
exactly). Head-observation calibration cut the unweighted head RMSE from 10.30 to 3.41, but
because the flow observation could not be registered, the river-discharge fit degraded
(residual +790 → +891) — the calibration optimised only the 10 heads.

## 10. Deviations from the source model

1. Adopted a session **copy** of the shipped runnable set (`run\pestobs_ss`) with
   `allow_modify=true`, rather than the shipped directory in place, to keep the shipped
   reference untouched. Same input set, no rebuild of the grid.
2. **Units metadata:** `summarise_model` labels K and recharge as `m/d` even though the model
   is FEET/DAYS. No conversion was applied — the on-disk constants (K=2.4, RCH=7.62e-05,
   stages ~304.8) are model-native ft/d and were used unchanged.
3. **Observation representation:** head obs mapped to the nearest single DISV cell vs the
   shipped 4-node interpolation (`model.n2b`).
4. **Weights:** the MCP importer has no weight field, so PEST used weight=1; the reference
   weighted with `model.bwt`/`model.fwt`. Reference `Sum of squared residual` 1239.78 is
   weighted and is not directly comparable to our unweighted phi 1060.06.
5. **Flow observation not registered** — compound-flux OBS6 type unsupported (Section 6).
6. **Calibration scope:** only `npf:k` adjustable via `setup_calibration`; recharge and river
   conductance not available. Calibration is therefore head-only and K-only.
7. **Flow metric** evaluated via `compute_water_balance` (as the MCP directs) instead of as a
   PEST observation.

## 11. Tool-call sequence

1. `check_environment`
2. `adopt_model` (METERS, default) → `delete_model` (unregister) → `adopt_model` (FEET, allow_modify)
3. `summarise_model`, `check_model`, `model_status`
4. `run_simulation` → `get_run_log`
5. `read_heads`, `compute_water_balance`, `diagnose_water_balance`, `plot_heads_map`
6. `import_obs_from_csv` (HEAD, 10 sites) → `run_simulation` → `compare_to_observed`
7. `import_obs_from_csv` (FLOW) → INVALID_INPUT (documented gap)
8. `setup_calibration` (`rch:recharge`) → INVALID_INPUT; `setup_calibration` (`npf:k`, all)
9. `run_pestpp_glm` (client timeout; completed server-side)
10. `summarise_calibration`
11. `run_simulation`, `compute_water_balance`, `read_heads`, `plot_heads_map` (calibrated)

## 12. Artifacts

- Model workspace: `run\pestobs_ss\` (adopted, calibrated)
- Obs input: `run\obs_points.csv`; extractor `run\make_obs_csv.py`
- Maps: `run\heads_map_base.png`, `run\heads_map_calibrated.png`
- Obs scatter: `run\obs_scatter_base.png`
- PEST interface: `run\pestobs_ss\pestobs_ss.pst`, `gwf_model_k.dat.tpl`, `gwf_model_head.obs.csv.ins`
- Residuals: `run\pestobs_ss\pestobs_ss_obs_residuals.csv`, `run\pestobs_ss\pestobs_ss_residuals.csv`
