# 7f-D session — silent-corruption fixes (stage_raster, river CRS, layer bounds, cache/adopt)

- Date: 2026-08-17 (2026-08-17e)
- Scope: tasks.md § 7f Tier D (D1.1–D1.3, D2.1–D2.2, D3.1, D4.1–D4.2), promoted
  into the v0.1.0 gate by owner decision 2026-08-17d. All items done in one
  pass before any 6d rerun.
- Method: TDD — regression tests written first (RED), then minimal fixes (GREEN).

## Deliverables

| Task | Fix | Tests |
|---|---|---|
| D1.1 | `import_river_from_shapefile` stage_raster sampler now uses `mg.xyzcellcenters[0]` (x) / `[1]` (y) instead of the transposed (y, x) | `test_stage_raster_uses_true_centroids` (non-square grid, ramp raster varying only in x, per-reach stage == centroid-x − offset), `test_sample_transposed_coordinates_differ` |
| D1.2 | `STAGE_RASTER_NO_COVERAGE` error when > `coverage_tolerance` (default 0.1) of reaches sample to NaN; `reaches_no_raster_coverage` in success result; out-of-bounds raster sampling hardened to NaN (rasterio returns 0.0 when no nodata — a plausible-looking wrong value) | partial-coverage error, single-uncovered success, custom-tolerance, `test_sample_out_of_bounds_returns_nan` |
| D1.3 | Transient-run stage_raster nodata backlog line split + ticked; rerun-3 weakness #1 annotated (fixed by D1.2 + D2.2) | [review] — annotations in tasks.md + tools.md NOTE updated |
| D2.1 | `intersect_lines_with_dis_grid` tags the grid GeoDataFrame with `modelgrid.crs`, not the shapefile's CRS → reprojection branch reachable; dead `xyzv` removed | `test_river_reprojected_matches_native` (EPSG:4326 river vs EPSG:32718 grid == pre-projected reach set) |
| D2.2 | `CRSError` (grid no CRS + shapefile has CRS) → `CRS_UNKNOWN` envelope; `NO_INTERSECTION` message includes grid + shapefile bboxes | `test_river_import_unknown_model_crs_errors`, `test_river_import_no_intersection_reports_bboxes` |
| D3.1 | `_validate_layer` in `read_heads` / `compute_drawdown` / `plot_heads_map` → `INVALID_INPUT` naming valid range (`plot_cross_section` has no layer argument) | impl-level raises (3-layer fixture) + MCP-envelope tests |
| D4.1 | model_store records input-file mtimes at load/save; `get_sim` reloads from disk when any tracked file is newer; `summarise_model` reports `reloaded_from_disk` | `test_cache_reloads_on_external_edit` (edit `.ic` on disk → reload + strt reflected) |
| D4.2 | `adopt_model` read-only by default (`allow_modify=False`); `save_sim` raises `ModelReadOnlyError` → `MODEL_ADOPTED_READONLY` in every mutating tool envelope; files left byte-identical; non-mutating tools unaffected | `test_adopt_model_readonly_*` (impl + MCP envelope) |

## Verification

- New tests: 20. Full suite: **286 passed** (was 266), 0 failures.
- Ruff: no new violations in touched files (pre-existing lint debt in untouched
  code remains — `assign_k_from_zones`/`import_obs_from_csv`/`read_budget`
  E501/mypy items are 7e-B territory).
- Mypy: no new errors in touched files (2 pre-existing in untouched code).

## Notes / decisions

- `test_parameterise.py::dis_model` fixture now sets `modelgrid.crs = EPSG:32755`
  so the D2.2 CRS guard does not trip the existing river/obs/assign tests
  (grids built via `add_dis_package` carry no CRS by design; grids built via
  `import_grid_from_shapefile` do).
- The D4.1 flag is consumed (read+cleared) by `summarise_model`; other tools
  benefit from the reload itself even though they do not surface the flag.
- When `save_sim` refuses an adopted read-only model it also evicts the
  in-memory copy so the next access reloads the authoritative disk state.

## Next

Tier E (build-loop write cost) is the next gate item per the updated critical
path in tasks.md.
