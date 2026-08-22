# 7f-G session — declarative spec, provenance ledger, scenarios

- Date: 2026-08-17
- Scope: tasks.md § 7f Tier G (G1.1-G1.4, G2.1-G2.3, G3.1-G3.2), promoted into
  the v0.1.0 gate by owner decision 2026-08-17d.
- Method: TDD — schema validation first, then apply/export, ledger,
  describe/report, clone/compare.

## Deliverables

| Task | Implementation | Tests |
|---|---|---|
| G1.1 | `utils/spec.py::validate_spec` — declarative spec schema (grid/time required; DIS/DISV; dimensional checks) with distinct error messages; schema + worked example published in tools.md | `test_validate_spec_{accepts_valid,rejects_unknown_key,rejects_missing_required_key,rejects_dimensional_mismatch}` |
| G1.2 | `utils/spec.py::apply_spec` — applies via the granular builder impls and returns a structured diff of package files (added/replaced/unchanged/removed) from header-normalised content hashes before/after | `test_apply_spec_to_empty_model_reports_added`, `test_apply_spec_to_granular_built_model_reports_unchanged` |
| G1.3 | Idempotence: second apply → zero-change diff + identical header-normalised file set; spec build == granular build content | `test_apply_spec_twice_is_idempotent`, `test_spec_build_matches_granular_build` |
| G1.4 | `utils/spec.py::export_spec` — emits the spec (grid arrays, npf/ic/sto, boundaries from `stress_period_data.get_data()`, oc, time) | `test_export_apply_roundtrip_reproduces_heads` (run heads within 1e-6 after export→apply→run) |
| G2.1 | `utils/ledger.py` + central wrapper in `server.py` around every `@mcp.tool()` — each call appends `{ts, tool, args, change}` to `<ws>/.gwmcp_history.jsonl`; failures record their error code | `test_ledger_records_every_tool_call_in_order` (6-call build → 6 lines; failing call → `failed: INVALID_INPUT`) |
| G2.2 | Parameterise tools record array provenance in `.gwmcp_meta.json`; `describe_model` reports data_sources, unverified_defaults, has_run, results_stale, ledger_entries | `test_describe_model_reports_sources_defaults_and_staleness`, `test_describe_model_reports_stale_after_external_edit` |
| G2.3 | `export_model_report` → `<model>_report.md` (description, provenance table, obs fit, water balance, plots, ledger) | `test_export_model_report_contains_sources` |
| G3.1 | `clone_model` — copies input files (no binary outputs) to a new registered workspace; `cloned_from` recorded; internal GWF name kept (tools fall back to the first model) | `test_clone_model_copies_and_isolates` |
| G3.2 | `compare_scenarios` — head-difference stats + max-abs cell, per-boundary budget deltas (inflow AND outflow keys), obs-fit deltas; response < 8 KB | `test_compare_scenarios_well_rate_difference` (max diff at well cell; WEL outflow delta == 400 for −500→−900) |

## Verification

- New tests: 15 (`tests/test_spec_scenarios.py`). Full suite green (302 + 15 =
  317 passed).
- Ruff clean on all touched files; mypy clean (the pre-existing `read_budget`
  dict-item mypy error remains, 7e-B territory).

## Notes / decisions

- The diff is package-file based (header-normalised content hashes) rather
  than array-diff based; a changed array shows as `replaced`. This is
  simpler, robust, and sufficient for the apply/verify loop.
- "Byte-identical" for G1.3 is header-normalised: flopy embeds a generation
  timestamp in every file's first line.
- The provenance ledger is written by a wrapper around the MCP tool
  registration (server.py `_register`), so it covers every tool including
  failures, but impl-level calls in tests bypass it — `describe_model` detects
  `has_run` from `.hds` presence, not the ledger.
- `export_model_spec` emits full arrays as nested lists (payload-scale caveat
  is 7e-A1's concern).
- Clone keeps the source's internal GWF name; `cloned_from` is recorded so the
  provenance chain is not lost.

## Next

Tier H (units, convergence auto-fix, sensitivity screen, calibration verdict)
is the next gate item per the updated critical path in tasks.md.
