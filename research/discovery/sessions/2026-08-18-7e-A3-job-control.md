# 7e-A3 session — job control (background runs + live progress)

- Date: 2026-08-18
- Scope: tasks.md § 7e Tier A3 (A3.1-A3.4), promoted into the v0.1.0 gate by
  owner decision 2026-08-17d.
- Method: TDD.

## Deliverables

| Task | Implementation | Tests |
|---|---|---|
| A3.1 | `utils/jobs.py` registry: `submit` runs `target(job)` in a daemon thread, holds the subprocess handle, transitions `running` → `succeeded`/`failed`/`cancelled` under a lock (a cancel is never overwritten by a late success). Four new tools: `start_run` (MF6, background, returns `job_id` immediately), `start_calibration` (pestpp-glm/ies, same), `get_job_status`, `cancel_job`. MF6 worker replicates flopy's `run_model` classification ("normal termination" in stdout) and produces a `run_simulation`-shaped result (success, convergence, elapsed_s, listing_summary, observation_fit, STO warning). A `_run_process` seam makes the subprocess injectable for tests. | `test_submit_returns_immediately_and_polls_to_succeeded`, `test_submit_failed_target_reports_error`, `test_cancel_job_terminates_running_process`, `test_start_run_returns_job_id_immediately_for_slow_model` (fake 6 s run, start < 1 s), `test_start_run_cancel_terminates_process`, unknown-job KeyError tests, real-MF6 `test_start_run_real_model_polls_to_succeeded` (.hds exists), MCP envelopes `JOB_NOT_FOUND` / `MODEL_NOT_FOUND` |
| A3.2 | `_parse_mf6_lst_progress` reads the TDIS block (nper from `N STRESS PERIOD(S) IN SIMULATION`, per-period `nstp` from the `STRESS PERIOD LENGTH TIME STEPS MULTIPLIER` table) and the `Solving:  Stress period: N  Time step: M` markers; `percent_complete` = share of completed time steps, monotonically non-decreasing. | `test_parse_mf6_lst_progress_{complete_run,partial_run,incremental_is_monotonic,empty}` against a synthetic 2-period (2+3 step) fixture shaped from real mfsim.lst output (verified against the zenodo-0205 and brabant worktree listing files) |
| A3.3 | `_pestpp_progress` branches on the engine: GLM reads `<case>.iobj` (via the existing `_read_glm_phi`); IES reads `<case>.phi.actual.csv` via the new `_read_ies_phi` (reports the ensemble-`mean` column; averages numeric columns when no mean exists). | `test_pestpp_progress_glm_from_iobj` (real `mf6brabant.iobj` shape: iteration 1, phi 0.00895693), `test_pestpp_progress_ies_from_phi_csv` (real zenodo `0205.phi.actual.csv` shape: iteration 3, mean 0.432304), no-mean fallback, missing-file → `{}`; `test_start_calibration_background_progress_and_result` polls live progress while the job runs and checks the final result |
| Docs | tools.md (runner + calibration tables, "Job control (7e-A3)" section, error codes), README.md (tool table 49→53, safety-guarantee bullet), capability-matrix.md (tool-count history, meta-tool list), tasks.md (A3.1-3 ticked, A3.4 remains [human], audit-block and Tier-2-deferred items closed, critical path updated) | protocol count 49 → 53 |

## Verification

- New tests: 23 (17 in `tests/test_job_control.py` + 6 MCP-layer in
  `test_mcp_protocol.py`). Full suite green (390 passed; 381 non-holdout +
  9 holdout replay).
- Ruff clean on all touched files; mypy clean on `jobs.py`, `runner.py`,
  `calibration.py`. Pre-existing ruff (parameterise/spatial/plotting +
  F841s, 7e-B items) and mypy (parameterise.py:591, index_builder.py:170)
  errors are untouched backlog, verified as pre-existing.

## Notes / decisions

- **Slow-run criterion without a slow model.** The "< 1 s return for a run
  taking > 5 s" and cancellation criteria are exercised through the
  `_run_process` seam with a fake process stand-in (`_FakeProc`: a Popen whose
  stdout streams "normal termination" after a configurable delay and whose
  `kill()` interrupts promptly) — the registry, threading, polling, status
  transitions and the parsers are all real code. A real-MF6 integration test
  covers the happy path end-to-end.
- **Success classification mirrors flopy.** `start_run`'s worker sets success
  when "normal termination" appears in stdout, exactly like
  `flopy.mbase.run_model` (verified against the installed flopy 3.10 source),
  so background and foreground results agree.
- **`start_run` deliberately has no `auto_fix`** (unlike `run_simulation`):
  the auto-fix ladder restarts the process, which would complicate the
  cancellation handle for no A3.1 requirement. `run_simulation(auto_fix=True)`
  remains the interactive path.
- **Job kind + progress are per-job**, so `get_job_status` is engine-agnostic
  and a single poll tool serves both MF6 and PEST++ jobs.
- A3.4 (a >30-minute PESTPP-IES calibration run entirely through the job
  tools) is the [human] 6d-replay item that closes deviation 8 from the
  zenodo run-1 session log.

## Next

7e-B correctness bugs (B2: `summarise_calibration` success-on-failure; B3:
narrow the calibration hot-path excepts; B4.1/B4.2 list_models/delete_model
+ registry scoping; then B5-B18) per the updated critical path in tasks.md.
