# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-6 (regional model validation)

- **Date**: 2026-09-16
- **Client**: Agent Manager closed-book session `ses_f54b735e3ffersgFL5uFyMrM7c` (groundwater-mcp
  server restarted 2026-09-16 17:34 local, loading code through `91d00f7`)
- **Model**: `neckartal_disu` — adopted in place at the shipped
  `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim` (single GWF `flow`, DISU 31,831
  nodes); `neckartal_base` — the same repo copy the agent preserved as `_sim_backup_shipped`
- **Worktree / branch**: `.kilo/worktrees/6d-enkf-disu-rerun6`, branch `6d-enkf-disu-rerun6`
- **Code**: `91d00f7` (Task 10 multiplier K scope + run-isolated `summarise_da`)
- **Holdout**: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (verified byte-identical to the pristine
  snapshot at dispatch, 60 files)
- **Playbook**: `research/discovery/playbooks/6d-regional-model-validation.md`, **Target 8**
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun6/run-log.md`
- **Type**: closed-book validation rerun. **Outcome: NOT GREEN** — steps 1–6 and 8 complete and
  verified; step 7 (the sequential DA execution) is blocked by a toolchain defect.

## Prompt used

The verbatim playbook Target 8 prompt, unmodified (step 6 already instructs the agent to prefer
`scope="multiplier"`). 0 user reprompts; 2 agent self-corrections (below).

## Tool-call sequence (from `run-log.md` §3 and the workspace's `.gwmcp_history.jsonl`)

1. `check_environment` — stack ready (flopy 3.10.0, pyemu 1.4.0, mf6, pestpp-glm/-ies/-sen/-opt/-da).
2. `adopt_model(neckartal_disu, <sim dir>, allow_modify=true, METERS, DAYS)` — adopted, GWF `flow`.
3. `check_model` — clean (no errors/warnings).
4. `model_status` — `runnable: true`.
5. `set_simulation(nper=1, perlen=[56], nstp=[1])` — single 56-day step (`modflowsim.tdis` written
   by the flush; the shipped `sim.tdis` is left orphaned on disk — noted, not a blocker).
6. `check_model` + `validate_model` — clean.
7. `start_run` / `run_simulation` — converged, 1.70 s.
8. `import_obs_from_csv(cellid_col="Cell_ID")` — 13 sites, 78 records (0-based DISU node ids
   converted to 1-based OBS ids correctly).
9. `run_simulation` + `compare_to_observed` — RMSE **1.0556 m**, bias −0.9811, R² **0.8671** (n=13):
   the gauge→node mapping is **verified** (wrong nodes would show tens of metres).
10. `setup_da_control` — **accepted `scope="multiplier"`** (this is the Task 10 code path): one
    adjustable `k_mult` (log), K template with ONE token (`flow_k_mult.dat.tpl`), 13 state
    parameters, 6 cycles, `par_cycles` perlen 56/28/14/12/15/36 d, `noptmax 1`, `da_num_reals 50`,
    `da_use_simulated_states True`, v2 `.pst`. The one-token template proves the multiplier scope
    is live (the reload took effect).
11. `start_calibration(method="da")` ×3 (50, 50, 4 reals) + `run_pestpp_da` (4 reals) — **all four
    deadlock** (section below); each cancelled/abandoned.
12. `flush_model` / `run_simulation` — `RUN_FAILED` on NPF `k`: the aborted DA left `flow_k.dat`
    truncated (122,995 of 412,638 bytes).
13. `adopt_model(neckartal_base, <pristine backup copy>)`, `set_simulation`, `import_obs_from_csv`,
    `run_simulation` — converged, reproduces the baseline exactly (RMSE 1.0555854, R² 0.8671324).
14. `plot_heads_map`, `compare_to_observed` (PNG + residual CSV), `read_simulated_observations` —
    step 8 delivered on the pristine baseline.

## Reprompts / corrections (agent self-corrections, **no user reprompt**)

1. `setup_da_control` `par_cycles` — `{"perlen": [56,28,...]}` (list) →
   `INVALID_INPUT: par_cycles['perlen'] must map a cycle index to a fixed value`; corrected to
   `{"perlen": {"0":56,...}}` → accepted. **Backlog (ergonomics):** the tool docstring/playbook
   should show the per-cycle mapping form.
2. `compare_to_observed` `output_file` — a `.csv` path →
   `COMPARE_FAILED: Format 'csv' is not supported`; corrected to `.png`. **Backlog (ergonomics):**
   accept/ignore non-PNG `output_file`, or say PNG-only in the docstring.

## Step 7 failure — `pestpp-da` deadlocks on the multiplier forward command

Identical signature on all four attempts (50, 50, 4 reals via `start_calibration`; 4 reals via the
synchronous `run_pestpp_da`, which hit the MCP client timeout):

- `pestpp-da.exe` burns 100 % of one core while "running initial ensemble";
- the spawned chain `pestpp-da → .venv\Scripts\python.exe (stub) → uv cpython python.exe` shows the
  interpreter at ~0.016 s CPU / 9 MB — frozen immediately after start, before it can import numpy;
- `mf6.exe` never starts (`flow_output\flow.hds` never updates); no error is emitted;
- the wrapper is left suspended mid-`np.savetxt`, truncating `flow_k.dat`;
- reducing the ensemble 50 → 4 changes nothing (zero realisations completed in >6 min).

**Root cause (controller-verified, not just the agent's hypothesis).** The PST's
`model_command` was

```
"D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe" C:\Users\jakob\AppData\Local\Temp\gwmcp_run_neckartal_disu.py
```

The interpreter is the venv `python.exe`, whose path contains a space (`Claude Projects`), and it is
also a two-level redirector stub. `_generate_forward_wrapper` hard-coded `sys.executable` for the
`multiply_k` wrapper **because that wrapper imported numpy**; the space-free interpreter it otherwise
prefers is the base interpreter
(`C:\Users\jakob\AppData\Roaming\uv\python\cpython-3.12.11-windows-x86_64-none\python.exe`), which
has no site-packages. The MCP's own `setup_pest_control` validation documents that pestpp on Windows
cannot launch an executable path containing spaces. The multiplier scope *always* requires a wrapper
(and `scope="all"` is infeasible here), so there was no tool-level route around it — the agent
correctly stopped rather than work around it, per the MCP-only rule.

**Fix (applied by the controller after the run, TDD):** the `multiply_k` wrapper is now stdlib-only
(the base×factor arithmetic is inlined without numpy), and both wrapper flavours use
`_space_free_interpreter() or sys.executable`, so the command never contains a space. Covered by:
`test_multiplier_forward_command_is_space_free_and_stdlib_only` (unit) and
`test_mcp_only_sequential_da_run_multiplier_space_workspace` (real `pestpp-da` run in a
space-containing workspace — the exact failing configuration, passes in ~12 s).

## Outcome vs criteria

| # | criterion | result |
|---|---|---|
| 1 | `check_environment` | ✅ |
| 2 | `adopt_model` in place | ✅ |
| 3 | `check_model` clean | ✅ |
| 4 | re-express as NPER=1/NSTP=1 DA cycles | ✅ (161 simulated days over 6 cycles) |
| 5 | register gauges + verify mapping | ✅ RMSE 1.06 m, R² 0.87 |
| 6 | `setup_da_control` with multiplier K | ✅ one token, 1 K param, 13 state params, 6 cycles |
| 7 | run the sequential DA | ❌ **BLOCKED** — `pestpp-da` deadlock (toolchain defect) |
| 8 | postprocess (`plot_heads_map`, `compare_to_observed`) | ✅ (on the preserved pristine baseline) |

## MCP findings (backlog)

1. **[BLOCKER, fixed]** multiplier/zones forward wrapper imported numpy, forcing the
   space-containing venv interpreter into `model_command` → `pestpp-da` deadlock. This is a
   regression introduced by the Task 10 multiplier scope (which always needs the wrapper); the
   `scope="zones"` path had the same latent defect.
2. `setup_da_control` `par_cycles["perlen"]` needs the per-cycle mapping form; the list form fails
   with an unhelpful-sounding message. Document the mapping.
3. `compare_to_observed(output_file=*.csv)` fails; document PNG-only (or accept CSV).
4. After an aborted DA run, the adopted model is left non-runnable (truncated external `flow_k.dat`)
   and there is no MCP route to repair it in place; recovery required re-adopting a preserved copy.
   Consider validating/rewriting the external K array on `run_simulation`, or documenting a
   re-run `setup_da_control`/re-rewire recovery.
5. `set_simulation` leaves the shipped `sim.tdis`/`sim.ims` orphaned when the flush re-renders the
   active set under a new stem; harmless but confusing.

## MCP-only violations

**0.** No flopy/pyemu/PEST class was called and no MODFLOW/PEST file was hand-edited; the repo's
EnKF scripts were never executed. Ordinary Python was used only to reshape the gauge CSVs into the
observation table (`prep_obs.py`, `obs_gauges_long.csv`).

## Time

~40 minutes (adopt 17:39 → last tool call 18:09 UTC), of which ~25 min were the four deadlocked DA
attempts.

## Chain status

rerun-4 + rerun-5 were the 2 consecutive green runs on `228595c`. rerun-6 is **red** (blocked), so
the consecutive-green chain restarts: rerun-7 and rerun-8 must both be green on the fixed code.
