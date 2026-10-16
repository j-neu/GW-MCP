# Worked example: build, calibrate and re-run a catchment model

This walks through one complete modelling session using only the MCP tool
surface an AI client calls. The script is
[`examples/catchment_walkthrough.py`](../../examples/catchment_walkthrough.py);
it runs in about ten seconds and is exercised by the test suite
(`tests/test_examples.py`), so it cannot silently drift from the tools.

## What it demonstrates

A **twin experiment**, which is how a calibration workflow is normally
verified before it is trusted on field data:

1. A "true" model with K = 20 m/d is built from real spatial data (the
   Tutorial 04 catchment polygon and DEM in `tests/fixtures/tutorial_04`) and
   run. Six heads from it become the synthetic observations.
2. The same model is rebuilt with a deliberately wrong K = 5 m/d.
3. PEST++ (GLM) calibrates K against the observations.
4. The calibrated value is written back into the model and the model is run
   again, so the calibrated heads, budget and plot come from the calibrated
   model itself.

It is a synthetic test, not a published case study: it shows the tool chain
is wired correctly and recovers a known answer. The real-model validations are
listed in [`tasks.md`](../../tasks.md) and
[`research/holdout-registry.md`](../../research/holdout-registry.md).

## Run it

```bash
uv run get-modflow :      # once
uv run get-pestpp :       # once
uv run python examples/catchment_walkthrough.py
```

## The tool calls, in order

| Step | Tool | What it does here |
|---|---|---|
| 1 | `create_model`, `set_simulation` | steady-state model, metres/days |
| 2 | `import_grid_from_shapefile` | 7 × 7 grid at 500 m over the catchment polygon (CRS EPSG:32718 inherited) |
| 3 | `assign_top_from_raster` | cell tops from the DEM |
| 4 | `add_boundary_package` (CHD, WEL) | 60 m / 40 m constant heads, one pumping well |
| 5 | `add_npf_package`, `add_ic_package`, `add_oc_package` | conductivity, initial heads, output |
| 6 | `check_model`, `run_simulation` | pre-run checks, then MODFLOW 6 |
| 7 | `read_heads` | heads of the true model → synthetic observations |
| 8 | `import_obs_from_csv` | observations mapped to cells by their coordinates |
| 9 | `compare_to_observed` | misfit of the wrong-K model |
| 10 | `setup_calibration`, `run_pestpp_glm`, `summarise_calibration` | one call builds the whole PEST++ interface; GLM estimates K |
| 11 | `apply_calibration_result` | writes the estimate back into the model |
| 12 | `run_simulation`, `compare_to_observed`, `plot_heads_map`, `diagnose_water_balance` | calibrated model: fit, map, budget |

## Output

```
== grid from shapefile
   type: DIS    nrow: 7    ncol: 7    crs: EPSG:32718
== check_model            passed: True
== true model run         success: True   convergence: converged
== synthetic observations n: 6    head_range: 44.90 .. 51.49 m
== observations registered  sites: 6   mapping: coordinates
== before calibration (K = 5 m/d)   rmse: 1.4896   n: 6
== setup_calibration      parameters: 1   observations: 6
== pestpp-glm             converged: True   iterations: 9   final_phi: 1.93001e-19
== calibrated parameter   name: k   estimate: 20.00000000629021   truth: 20.0
== after calibration      rmse: 0.0   n: 6
== water balance          percent_discrepancy: 6e-06   balanced: True
```

K is recovered to nine significant figures and the head misfit falls from
1.49 m to zero. The water balance of the calibrated model closes to 6e-6 %.

## Things worth knowing when you adapt it

- **Observation coordinates must be in the grid's CRS.** Sites more than about
  a cell beyond the grid are rejected (`allow_outside=True` snaps them
  instead); an earlier version snapped them silently, which is how this example
  first came out with every site reading the same head.
- **A parameter that would flatten a varied field is refused.** The example
  sets `allow_flatten: true` because the starting K is uniform; on a spatially
  varying K use `scope="zones"` (see `tools.md`).
- **`apply_calibration_result` handles GLM and IES** (the IES ensemble mean);
  zoned setups are rebuilt as base × multiplier. pestpp-da runs are not
  supported, because their parameters are per cycle.
- **Calibration reads observations from the model's own OBS output**, so the
  observation set registered in step 8 is the target.
