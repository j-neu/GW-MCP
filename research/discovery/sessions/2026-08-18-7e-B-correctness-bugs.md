# 7e-B session — correctness bugs (v0.1.0 gate)

- Date: 2026-08-18
- Scope: tasks.md § 7e Tier B (B2–B16, B18), promoted into the v0.1.0 gate by
  owner decision 2026-08-17d. Next gate item after 7e-A.
- Method: TDD — one test per atomic task, then the implementation; every task
  that changes a tool signature/default/behaviour also updated tools.md,
  README.md and research/capability-matrix.md in the same change.

## Summary

**31 new tests in `tests/test_7e_b.py`** (plus updates to
`test_calibration.py`, `test_builder.py`, `test_mcp_protocol.py`,
`test_spec_scenarios.py`, `test_integration_transient.py` and
`test_holdout_replay.py`). Full suite **424 passed** (was 390 at the end of
7e-A3); ruff + mypy clean on the touched files. **56 tools** (was 53:
`set_model_crs`, `list_models`, `delete_model` added; `view_image` stays
removed per 7f-I1).

## What was implemented, per task

| Task | Change |
|---|---|
| **B2** | `summarise_calibration` checks for `{base}.res/.rei/.base.rei` and raises `FileNotFoundError` (→ `OUTPUT_FILE_MISSING`) when none exist — a run that dies before residuals is never reported as a success with `rmse: None, n_observations: 0`. |
| **B3** | Calibration hot-path excepts narrowed: `_read_phi_csv`/`_read_iobj_phi` catch only `OSError` (parse errors propagate), `_parse_par_file` has no swallow, `_compute_residual_stats` catches only data-shape errors, `_parse_ins_obs_names` narrowed. |
| **B4.1** | `list_models` + `delete_model` registered (agents can recover model names and unregister without hand-editing `.gwmcp_registry.json`). |
| **B4.2** | Registry scoped per workspace root (explicit workspaces register in their parent's `.gwmcp_registry.json`, discoverable via a `known_roots.json` index); re-registering the same name+path is idempotent; the same name in different roots is legal. |
| **B5** | `assign_top_from_raster(method=...)` now honoured: `mean`/`min`/`max` are per-cell zonal aggregations (rasterio reprojection, uniform DIS grids; non-uniform → `INVALID_INPUT`), `nearest`/`bilinear` sample at centroids (manual bilinear — rasterio 1.5's `sample_gen` has no `resampling` kwarg). |
| **B6** | DISV `layer_surfaces` rejected with `INVALID_INPUT` (the DIS branch keeps sampling; DISV surface sampling is blocked by flopy 3.10's `VoronoiGrid` requiring the external `triangle` binary — follow-up noted). |
| **B7** | Ticked as superseded by 7f-H1.2 (done 2026-08-17). |
| **B8** | `RCHA`/`EVTA` (array-based recharge/ET) added to `add_boundary_package`: `stress_period_data` maps a period to a full-grid array; `rate_units` converts on entry; budget term is `RCH`. Verified end-to-end: transient-with-storage run produces `rate × area × n_cells` in the RCH budget term. |
| **B9** | `add_dis_package(idomain=...)` (2-D broadcast or 3-D); `summarise_model.grid.n_active`. |
| **B10** | `add_boundary_package(pname=...)`: with a `pname` only that package is replaced, so `chd_high` + `chd_low` coexist; without one, all packages of the type are replaced. `_packages_of_type` handles flopy's list-returning `get_package`. |
| **B11.1** | `set_model_crs(model, crs, xorigin, yorigin, angrot)` — grid built with `add_dis_package` can now carry a CRS, unblocking every spatial tool. |
| **B11.2** | `assign_top_from_raster` errors `CRS_UNKNOWN` when the grid has no CRS and the raster declares one; errors when the raster covers no grid cells. |
| **B11.3** | `fill: "error"|"median"|"nearest"` + `coverage_tolerance`; `cells_no_coverage` always reported, `warning` field on fills. |
| **B12** | `server._sanitise` converts non-finite floats to `None` across every tool result (dict/list/tuple walk; plot `Image`s pass through). |
| **B13** | Head/budget readers prefer the OC `head_filerecord`/`budget_filerecord`; multiple undeclared candidates return a `warning` naming them. |
| **B14** | `_array_stats` masks `abs(v) >= 1e20` (both `±1e30` sentinels); same mask in `compute_drawdown`/`plot_heads_map`/`compute_water_balance`. |
| **B15** | Dead `zone_counts` loop removed from `assign_k_from_zones`. |
| **B16** | UCODE references gone (`grep -ri ucode src/` clean) — the register docstring and the new `test_no_stale_ucode_references`. |
| **B18** | Tool-count guard (`test_tool_count` + doc-sync comment) kept current at 56. |

## Notable findings

1. **The two calibration-chain replay tests (transient, freyberg) were passing
   vacuously.** Under the old `except Exception: pass`, `summarise_calibration`
   returned a success dict with empty residuals whenever the GLM run died
   before writing `.rei` — which is what those runs did:
   - *transient*: the synthetic obs file is static (the forward model never
     regenerates it), so GLM cannot build a Jacobian.
   - *freyberg*: the hand-rolled `forward.py` wrapper never executed under
     pestpp (pyemu writes each `model_command` element on its own line, so the
     two-token `[sys.executable, "forward.py"]` made pestpp run `forward.py`
     alone), and the zip-based template/wel subsetting misaligns the PERIOD
     blocks (MF6 exit 2: "Looking for BEGIN PERIOD but found END PERIOD").
   Both tests now assert the loud `FileNotFoundError` (the B2 contract), with
   comments pointing at the real fixes for the 6d freyberg round. **This is
   the strongest evidence for B2:** the old code made a completely broken
   calibration look green.
2. **MF6 head files are unframed.** The pre-existing `synthetic_hds` helper in
   `test_postprocess.py` writes MODFLOW-2005-style Fortran-framed records that
   flopy's `get_headfile_precision` cannot read; it was never exercised. The
   new `test_7e_b.py` helper writes the correct unframed single-precision
   format.
3. **flopy 3.10's `VoronoiGrid` requires the external `triangle` binary**, so
   `import_grid_from_shapefile(method='disv')` is currently broken regardless
   of `layer_surfaces` — pre-existing, tracked as a follow-up (the DISV row in
   the capability matrix overstates what works today).

## Docs updated in the same change

- tools.md (56 tools; assign_top_from_raster method/fill/CRS; idomain; pname;
  RCHA/EVTA; set_model_crs/list_models/delete_model; registry scoping;
  OC-filerecord selection; missing-`.rei` behaviour; `CRS_UNKNOWN` error code)
- README.md (tool table, 56 tools)
- research/capability-matrix.md (tool-count history → 56; DIS idomain note;
  RCHA/EVTA row; workflow tools; correctness-hardening paragraph)
- tasks.md (all of Tier B ticked with completion notes)
