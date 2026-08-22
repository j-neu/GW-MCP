# 7f-H session — expertise as behaviour

- Date: 2026-08-17
- Scope: tasks.md § 7f Tier H (H1.1-H1.3, H2.1-H2.2, H3.1-H3.2, H4.1-H4.2),
  promoted into the v0.1.0 gate by owner decision 2026-08-17d.
- Method: TDD. Each validation gotcha that used to be prose in a tool
  description is now behaviour the tool performs.

## Deliverables

| Task | Implementation | Tests |
|---|---|---|
| H1.1 | `k_units` on `add_npf_package` (m/d, m/s, m/yr, cm/s, ft/d, ft/s → model length/time), `rate_units` on `add_boundary_package` for RCH/EVT (m/d, m/yr, mm/d, mm/yr → m/d); declared units recorded in `.gwmcp_meta.json` | `test_npf_k_units_conversion` (1e-5 m/s → 0.864), `test_rch_rate_units_conversion` (300 mm/yr → 8.219e-4), `test_unknown_{k,rate}_units_rejected` |
| H1.2 | `import_river_from_shapefile(bed_k, bed_thickness, channel_width)` — `cond = bed_k·width·length/thickness`; the reach-length-as-conductance default is removed and the call fails loudly without a conductance source | `test_river_conductance_derived_from_bed_properties`, `test_river_without_conductance_source_errors` (impl ValueError + MCP INVALID_INPUT envelope) |
| H1.3 | `summarise_model.units = {length, time, k, recharge}` from declared units | `test_npf_k_units_recorded_in_meta` |
| H2.1/2.2 | `run_simulation(auto_fix=True)`: `_IMS_RUNGS` escalation ladder (moderate 100 → complex 1000 → complex 2000 + relaxation → complex 2000 + relaxation 0.97 + BCGS); mutations staged via save_sim+flush (deferred-write aware); adopted read-only models not auto-fixed in place; `auto_fix_applied` reports from/to | `test_auto_fix_recovers_iteration_starved_model` (outer_maximum=1 model: fails without, converges in rung 1 with), `test_auto_fix_lists_every_rung_on_persistent_failure` |
| H3.1 | `check_parameter_sensitivity(model, parameters, template_files, delta)`: base run + one perturbed run per parameter (template substitution writes the model-input file, restored after); sensitivity = mean relative change of the obs CSV; results persisted in meta | `test_sensitivity_runs_exactly_n_plus_1_forward_runs`, `test_sensitivity_reports_sensitive_parameter_at_interior` (OPEN/CLOSE hk.dat + recharge), `test_sensitivity_flags_insensitive_parameter_at_chd_cell` |
| H3.2 | `setup_pest_control` warns naming insensitive parameters from the persisted sensitivity screen | `test_setup_pest_control_warns_on_insensitive_parameter` |
| H4.1 | `calibrate(model, par_data, template_files, ...)`: builds the obs interface from registered targets, chooses GLM vs IES (`_choose_method`: >50 params → IES), runs the engine, reports method + rationale | `test_choose_method_selects_glm_for_small_problem`, `test_choose_method_selects_ies_for_many_parameters` |
| H4.2 | `summarise_calibration` returns a `verdict`: improved (vs stored prior phi), parameters_at_bounds, identifiable (from sensitivity), fit_within_measurement_error (new `measurement_error` arg) | `test_summarise_calibration_verdict`, `test_summarise_calibration_verdict_names_parameter_at_bound`, `test_summarise_calibration_fit_within_measurement_error` |

## Verification

- New tests: 18 (`tests/test_hydro_expertise.py`). Full suite green (317 + 18
  = 335 passed).
- Ruff clean on all touched files (pre-existing parameterise.py debt remains,
  7e-B). Mypy clean (fixed the dict value-type widening the `observation_fit`
  assignment caused in runner.py by annotating `result: dict`).
- The `_tpl_substitute` helper emits a plain model-input file (template header
  and markers stripped) — the output file must be readable by MODFLOW, not by
  PEST.
- Sensitivity at an interior cell required recharge: a CHD-only steady confined
  model's head solution is linear in K, so heads are K-independent there.

## Notes / decisions

- `calibrate`'s job-control half (7e-A3) and the safe-numeric-defaults half
  (7e-A2.5: nonzero derinclb, tighter bounds) are deferred to 7e-A as the plan
  itself specifies (H4.1 says "run through the job control from 7e-A3").
- The `[human]` verification items (closed-book recovery of a non-converging
  model; sensitivity on the tutorial_05 fixture with real river conductance)
  are 6d-replay items.

## Next

Tier I (surface-area cuts) is the next gate item per the updated critical path
in tasks.md.
