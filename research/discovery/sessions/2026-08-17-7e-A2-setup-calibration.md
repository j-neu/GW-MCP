# 7e-A2 session — automated calibration setup (`setup_calibration`)

- Date: 2026-08-17
- Scope: tasks.md § 7e Tier A2 (A2.1–A2.6), promoted into the v0.1.0 gate by
  owner decision 2026-08-17d. Also closes the 7e-B1.1/B1.2 phi-branching bug
  (a dependency of the A2.5/A2.6 criteria).
- Method: TDD. The headline 7e finding was that `setup_pest_control` is a
  `.pst` *writer*, not a calibration *setup* tool — it required hand-authored
  `.tpl`, `.ins`, and a forward wrapper. `setup_calibration` now emits the
  whole interface in one call with zero hand-written files.

## Deliverables

| Task | Implementation | Tests |
|---|---|---|
| A2.1 | `_impl_rewire_npf_k_external(model, filename)`: NPF `k` → `OPEN/CLOSE <file>` via `npf.k.set_data({"filename": ..., "data": arr})` (in-place; flopy writes the external file), flushed so the written `.npf` shows the directive | `test_rewire_npf_k_external_preserves_heads` (heads identical to pre-rewire within 1e-9), `..._requires_npf` |
| A2.2 | `_normalise_parameterisation` + `_impl_generate_tpl`: one wide token (≥15-char field) per array cell in the external file's layer-major order; scopes `all` / `layer` / `cells` must partition the array exactly (overlap and gap are hard errors); PEST 12-char param-name cap; `_tpl_substitute` round-trips | `test_generate_tpl_uniform_wide_tokens_round_trip` (25 tokens, parse == `["k"]`, 12345.678 round-trips), `..._zones_partition_array` (left/right zone values land on the right cells), `..._layer_scope`, `..._rejects_{overlapping_cells,unassigned_cells,invalid_spec}` |
| A2.3 | `_impl_generate_ins_from_obs_csv`: reads the MF6 OBS CSV header, emits the canonical header-skipping pif (`l1` skip + `l1 ~,~ !name! ...`), 20-char obsnme truncation with collision error; `_build_model_obs_interface` (7f-F1.5) refactored to use it | `test_generate_ins_from_obs_csv_header` (parse_ins_file == columns minus `time`; values read back), `..._missing_file`, `..._truncates_long_names` |
| A2.4 | `_generate_forward_wrapper` + `_needs_forward_wrapper`: a `.py` wrapper (never `.bat`/`.cmd`) at a space-free path — in the workspace when the workspace path is space-free, else in a space-free system dir — that runs MF6 in the model workspace; command = quoted `sys.executable` + wrapper (the pattern `test_integration_full_calibration_chain_windows` proves works) | `test_generate_forward_wrapper_space_free_and_runs` (workspace *with spaces*; wrapper path space-free, executing it produces `.hds`), `..._space_free_workspace_inline`, `..._requires_mf6` |
| A2.5 | `_impl_setup_pest_control` safe defaults: `rectify_pgroups()` then `derinclb = 0.01` on every group (write-time group expansion re-adds new groups with pyemu's 0.0 default — a zero relative derivative increment zeros the Jacobian); defaulted bounds become base/10–base×10 (was the blanket 0.01–100 that stressed the Newton solve in zenodo run 1) | `test_setup_pest_control_safe_defaults` (k: 0.5–50 from initial 5.0; `derinclb > 0`), `test_setup_calibration_parameterisation_safe_defaults_in_pst`, `test_setup_calibration_glm_produces_nonzero_jacobian` (2-zone run: `.iobj` total_phi descends, `.jco` written) |
| A2.6 | `_impl_setup_calibration` orchestrates A2.1–A2.5, applies the template with initial values so the on-disk array matches the PST initial state, returns the full interface; `setup_calibration` MCP tool registered (49th tool) with `INVALID_INPUT` / `MODEL_NOT_FOUND` / `BINARY_NOT_FOUND` envelopes | `test_setup_calibration_e2e_reduces_phi` (single call → run_pestpp_glm → summarise_calibration: phi descends, verdict improved, 5 obs, 1 param, zero hand-written files), MCP-layer tests in `test_mcp_protocol.py` |
| B1.1/B1.2 (dependency) | `_read_iobj_phi` + `_read_glm_phi`: GLM phi comes from `<case>.iobj` (`iteration,model_runs_completed,total_phi,...`), not the IES-only `.phi.actual.csv`; used by `_impl_run_pestpp_glm` and `_impl_summarise_calibration` | `test_read_iobj_phi_parses_real_glm_output`, `test_read_glm_phi_prefers_iobj_over_phi_csv`, `test_read_glm_phi_falls_back_to_phi_csv`, `test_run_pestpp_glm_reads_iobj`, `test_summarise_calibration_reads_iobj` (the fabricated `.phi.actual.csv` GLM fixtures replaced) |

## Verification

- New tests: 23 (`tests/test_setup_calibration.py` 18, `test_calibration.py`
  +5, `test_mcp_protocol.py` +2). Full suite green (344 + 23 = 367 passed).
- Ruff clean and mypy clean on all touched files (calibration.py,
  test_setup_calibration.py, test_calibration.py, test_mcp_protocol.py). The
  pre-existing ruff/mypy debt in parameterise.py / utils / other tests
  (7e-B) is untouched.
- Real-binary integration: the GLM runs use the actual pestpp-glm + MF6
  binaries on this machine; the `.iobj` fixture is shaped like real captured
  GLM output.
- A CHD-only steady confined model has a K-independent head solution, so the
  integration models include recharge to make K identifiable (same finding as
  the 7f-H sensitivity session).

## Notes / decisions

- **B1.1/B1.2 were pulled into A2**, not left for Tier B: the A2.5 criterion
  ("a 2-parameter GLM run produces a non-zero Jacobian") and the A2.6
  criterion ("run_pestpp_glm + summarise_calibration reduces phi") both
  require GLM phi progress to be visible, and the old reader (`.phi.actual.csv`
  for GLM) always returned empty. The fabricated GLM fixtures in
  `test_calibration.py` were replaced with inline `.iobj` fixtures; capturing
  the real `mf6brabant.iobj` into `tests/fixtures/` (B1.3) remains for the
  next 6d brabant rerun.
- **Template layout is one token per line** (valid MF6 free-format external
  array), not the row-blocked layout flopy writes. Free-format parsing makes
  the two interchangeable; the sensitivity screen already relied on this.
- **`derinclb` must be set after `rectify_pgroups()`.** `Pst.write()` calls
  `rectify_pgroups()`, which re-adds any parameter group named in the
  parameter data with `pargp_defaults` (derinclb = 0.0). Setting the column
  before write is silently overwritten for new groups (e.g. the `gwmcp`
  group `setup_calibration` assigns).
- **Wrapper only when needed.** `setup_calibration` uses the direct MF6
  command when both the workspace and the MF6 binary path are space-free (the
  common case, no advisory warning); the Python wrapper kicks in when either
  has spaces. The A2.4 pytest forces the wrapper path (workspace with spaces)
  and verifies it executes.
- The `[human]` verification items (closed-book 6d rerun completing
  calibration with zero hand-written files; tutorial_05-specific e2e) are
  6d-replay items.

## Next

Tier A3 (job control — `start_run` / `get_job_status` / `cancel_job`, MF6 and
PEST++ progress parsing) is the remaining Tier A gate item; then 7e-B (B2+)
and 7e-C, per the critical path in tasks.md.
