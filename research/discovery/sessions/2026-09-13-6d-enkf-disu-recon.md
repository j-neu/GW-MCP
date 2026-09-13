# 6d reconnaissance — `MF6_EnKF_DISU` (Neckartal DE): data staged; EnKF capability gap identified

- **Date**: 2026-09-13
- **Source**: `https://github.com/JanGei/MF6_EnKF_DISU` (clone @ `main`, 2026-09-13; 271.6 MB)
- **Staged**: `D:\Claude Projects\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (whole repo minus `.git`)
- **Type**: reconnaissance (not a closed-book validation run)

## What the repo ships

1. **A complete runnable MF6 DISU model** at
   `NeckartalModel1718/NeckartalCalib_try_models/MODFLOW 6/sim/`:
   `flow.nam` = DISU / NPF / IC / CHD / OC / RCH / RIV / WEL / STO, external arrays in
   `flow_input/`, solved outputs `flow_output/flow.hds` + `.cbc`, and a PEST-style obs
   interface in `flow_pest/` (`model.bsamp`, `model.n2b`, `model.bwt`, `mf6mod2obs*`).
   **31,831 nodes / NJA 198,261 / 31,522 active**, 6-period transient, `TIME_UNITS days`,
   **vertices + CELL2D present** (so x/y geometry exists).
2. **Gauge data**: `csv data/Pegel.csv` (gauge water levels), `Pegel_Cell_ID.csv`
   (gauge → model cell map), `2017.csv` (pumping), `RCHunterjesingen.csv` (recharge),
   `PV_pseudoPP9_2.csv` (pilot points).
3. **A bespoke EnKF implementation** (`main.py`, `Transient_Run.py`, `Objectify.py`,
   `generator.py`, `functions.py`): load the DISU sim, generate **15 ensemble K fields**
   by kriging at pilot points (`kriggle`/`covmod`), run MF6 per member, and assimilate
   gauge heads (**EnKF**) at `t_enkf=300`.
4. A 27 MB GMS project (`NeckartalCalib_try.gpr`) + `_data/Components/` (the same model
   as GMS-generated components).

## MCP probe of the shipped model (all via the server at `8c8dc5e`)

| Step | Result |
|---|---|
| adopt (copy → `adopt_model`) | ✅ model `flow`; grid_type unstructured; **x/y centroids available (31,831)** |
| model_status / summarise_model | ✅ runnable; grid `{DISU, nnodes 31831, nja 198261, n_active 31522}`; packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO |
| check_model | ✅ clean |
| run_simulation | ✅ **converged**, normal termination, 5.7 s (6 periods) |
| read_heads | ✅ min 305.16 / max 343.07 / mean 325.56 m |
| compute_water_balance | ✅ closes (STO/RCH/RIV/WEL/CHD) |
| validate_model / export_model_spec | ✅ clean / spec exports (incl. STO transient) |
| plot_heads_map | ❌ `ValueError: x and y arrays must have a length of at least 3` |

`plot_heads_map` root cause: FloPy derives this DISU `modelgrid` as **`nlay=31831`,
`ncpl=[1,…]`**, so `get_xcellcenters_for_layer(0)` returns a single point and
`PlotMapView.contour_array` cannot triangulate. (Contrast `test009_3lay-disu`, whose
`modelgrid` is `nlay=1, ncpl=[228]`.) Our `_model_nlay` returns 1 for DISU, so the
layer guard passes but the flopy layer helper disagrees. Fix: a DISU plot path that
triangulates directly from `modelgrid.xcellcenters/ycellcenters` + the head array
instead of `contour_array`.

## Capability gap

The 6d Tier-1 criterion is **EnKF data assimilation**. The MCP has only GLM and IES
(`run_pestpp_glm`, `run_pestpp_ies`, `run_ies_uncertainty`) — there is **no ensemble
generator and no DA/EnKF tool**. The repo's EnKF is bespoke Python over the DISU model;
under the MCP-only constraint an agent cannot run it (raw flopy), and no MCP tool
expresses "generate an ensemble prior → run the ensemble transient → sequentially
assimilate observations → update". So the target needs a new data-assimilation capability.

## Proposed plan

1. **Plot fix (small):** DISU `plot_heads_map` via direct triangulation; TDD with a
   vertex-carrying DISU fixture (extend `add_disu_package` to accept `vertices`/`cell2d`).
2. **Observation substrate (small/medium):** register the Pegel gauge obs (gauge-cell map →
   coordinate or node ids) and evaluate fit via `compare_to_observed`.
3. **DA capability (large — design first):** decide the DA method the MCP should expose.
   Options: (a) `pestpp-da`-backed EnKF (binary present), (b) an MCP ensemble-run +
   ensemble-Kalman/ensemble-smoother update over DISU pilot-point parameters, or (c) map the
   workflow onto `run_pestpp_ies` (an ensemble smoother — closest existing tool, but not a
   sequential EnKF). Requires ensemble-generation (pilot-point/kriging or prior-cov sampling),
   ensemble orchestration, and DA summarisation.
4. **Closed-book reruns:** after the capability lands, two consecutive green runs.
