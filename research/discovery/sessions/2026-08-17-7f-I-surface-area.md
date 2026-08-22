# 7f-I session — reduce surface area

- Date: 2026-08-17
- Scope: tasks.md § 7f Tier I (I1-I5), promoted into the v0.1.0 gate by owner
  decision 2026-08-17d.
- Method: TDD.

## Deliverables

| Task | Implementation | Tests |
|---|---|---|
| I1 | `plot_heads_map`/`plot_cross_section` return `[Image(path), result]` — FastMCP emits ImageContent + TextContent (both tools forced `structured_output=False` so the JSON contract is unchanged); `view_image` tool + impl deleted (also removes the unconfined-path primitive); ledger summarises list results via the trailing dict | `test_plot_heads_map_returns_image_content` (MCP layer: ImageContent + text path), `test_view_image_no_longer_registered` |
| I2 | `sentence-transformers` moved to `[project.optional-dependencies] semantic`; `_semantic_available()` guard; `method="semantic"` → `SEMANTIC_SEARCH_UNAVAILABLE`, `method="auto"` falls back to Whoosh text | `test_semantic_search_unavailable_returns_envelope` |
| I3 | `describe_package` — the DFN files the plan expected are NOT vendored in flopy 3.10, so the spec is derived from flopy's package classes (throwaway 2×2 simulation): description, blocks (required/optional), and `stress_period_data` record fields | `test_describe_package_riv` (cellid/stage/cond/rbot), `test_describe_package_unknown_raises` |
| I4 | `add_disv_package(gridprops_file=...)`; inline `cell2d` over 50,000 → `PayloadTooLargeError` → `PAYLOAD_TOO_LARGE` envelope naming the alternatives | `test_disv_inline_payload_rejected_when_oversized`, `test_disv_gridprops_file_accepted` |
| I5 | `export_reproducible_script` — `run.py` with the exported spec embedded as a Python literal (pprint) and pure-flopy constructors | `test_export_reproducible_script_rebuilds_heads` (runs in a clean workspace, heads within 1e-6) |

## Verification

- New tests: 7 (`tests/test_surface_area.py`) + 1 rewritten image test in
  test_postprocess. Full suite green (335 + 8 = 343 → 338 after the net tool
  change). Tool count: 48 (46 + describe_package + export_reproducible_script).
- Ruff clean on touched files; mypy clean (only the pre-existing `read_budget`
  dict-item error remains, 7e-B).
- `test_holdout_replay._parse` now picks the first text content block (plot
  tools emit an image block first).

## Notes / decisions

- **Deviation from the plan's mechanism for I3:** the DFN files
  (`mf6ivar/dfn/*.dfn`) are not present in flopy 3.10 (verified by walking the
  installed package). `describe_package` therefore derives the authoritative
  package spec from flopy's own package classes (live introspection of blocks
  and `stress_period_data.dtype`) — same outcome (RIV → cellid/stage/cond/rbot),
  no vendored data files.
- **I1 deviation:** images are returned as FastMCP `ImageContent` plus the
  JSON result (matching the plan's test), and the plot tools' dict contract is
  preserved for impl-level callers.
- The generated `run.py` embeds the spec with `pprint.pformat` (JSON `true`
  would not parse as Python) and sets an explicit OC `saverecord` so the
  rebuilt model writes heads.

## Next

7e-A (array payloads, calibration setup automation, job control) is the next
gate item per the updated critical path in tasks.md — Tier A blocks the 6d
Tier-1 gate on regional models.
