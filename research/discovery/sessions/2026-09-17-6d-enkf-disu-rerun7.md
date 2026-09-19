# 6d session — `MF6_EnKF_DISU` (Neckartal DE) rerun-7 (regional model validation)

- **Date**: 2026-09-17
- **Client**: Agent Manager closed-book session `ses_f50258602ffeNnzmBZtw2aDQZ1` (groundwater-mcp
  server restarted 2026-09-17 14:51Z, loading `34d95b9`)
- **Model**: `neckartal_r7` — adopted in place at the shipped
  `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim`
- **Worktree / branch**: `.kilo/worktrees/6d-enkf-disu-rerun7`, branch `6d-enkf-disu-rerun7`
- **Code**: `34d95b9` (space-free, stdlib-only multiplier forward wrapper — the rerun-6 fix)
- **Holdout**: `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\` (verified byte-identical to pristine at
  dispatch, 60 files)
- **Type**: closed-book validation rerun. **Outcome: NOT GREEN** — blocked in step 7 by a second,
  distinct toolchain defect (background DA + Python wrapper), not the rerun-6 space defect.

## The rerun-6 space fix IS confirmed live (this part of rerun-7 succeeded)

The generated `neckartal_r7.pst` model command was:

```
C:\Users\jakob\AppData\Roaming\uv\python\cpython-3.12.11-windows-x86_64-none\python.exe C:\Users\jakob\AppData\Local\Temp\gwmcp_run_neckartal_r7.py
```

No spaces; the wrapper is referenced by an absolute space-free temp path (the workspace
`...\MODFLOW 6\sim` contains a space, so the wrapper necessarily lives in tempdir). Steps 1–6
completed: adopt → `check_model` clean → `set_simulation(NPER=1)` → 13 gauges → open-loop
`compare_to_observed` RMSE 2.18 (n=13) → `setup_da_control` with `scope="multiplier"` accepted
(`da_num_reals 30`, 6 cycles, one-token K template, 1 K + 13 state parameters).

## Step 7 defect: pestpp-da deadlocks launching the Python model command

Observed on the E: holdout run and reproduced in a second workspace on C:

| run | process | evidence |
|---|---|---|
| E: holdout (31,831 nodes) | pestpp-da → wrapper | progressed only to `run.info: da_cycle:0 realization:3` in ~14 min (3 realisations), each wrapper invocation stalling for minutes; the run was abandoned and the workspace left dirty |
| C: temp retry `%TEMP%\kilo\neck_da7_ws\sim` (agent's own controlled experiment) | pestpp-da 21852 (parent = MCP server pid 26500) → wrapper 23872 | hard block: `run.info` stuck at `realization:0` for >8 min; wrapper alive at **0.02 s CPU, 1 thread, WaitReason Executive, 9 reads / 31 KB, 0 writes**; `mf6.exe` never started; pestpp-da spinning at 100 % CPU (464 s CPU) |

### The wrapper, interpreter and launch flags are all exonerated

- **Manual run of the exact wrapper** (base interpreter, cwd = workspace, normal stdio):
  exit 0 in **1.92 s**, `flow_k.dat` rewritten (422,989 B), `mf6` "Normal termination" in 1.767 s.
- **Probe with the exact `_run_process` spawn flags** (PIPE stdout, STDOUT stderr, text=True,
  CREATE_NEW_PROCESS_GROUP, cwd = workspace) from a normal Python parent — both with the pipe
  **never drained** and **drained by a thread**: exit 0, `k.dat` rewritten, **3.5 s** each. So an
  undrained pipe (backpressure) is *not* the mechanism.
- **The committed regression test**
  `tests/test_da_end_to_end.py::test_mcp_only_sequential_da_run_multiplier_space_workspace` — a real
  pestpp-da run with the multiplier wrapper in a space-containing workspace — **passes in ~13 s**,
  re-confirmed after the rerun-7 failure.

The only remaining variable is that **pestpp-da is spawned by the MCP server** (`calibration.py
_run_process` → background DA job) rather than by pytest/shell. Direct `mf6.exe` model commands
work fine in that same context (rerun-4/rerun-5, 27 cycles); a Python-wrapper model command does
not. There is no space anywhere on the command line and the wrapper's own code never runs.

## Impact

The `scope="multiplier"` (and `scope="zones"`) K parameterisation **always** requires the Python
wrapper, so background `start_calibration(method="da")` cannot currently execute it on this host.
The rerun-6 space fix was necessary but not sufficient: the multiplier scope is still unusable for
the closed-book gate runs.

## Housekeeping

- The frozen temp DA tree (pestpp-da 21852 + wrapper 23872) was terminated — an orphaned
  100 %-CPU pestpp-da file-locking a workspace is exactly the failure mode recorded in the rerun-6
  finding, and it would sabotage a later run.
- The E: holdout is **dirty** (rerun-7 DA artifacts + a truncated/rewritten `flow_k.dat`); it must be
  reset from `E:\GW-MCP-holdout\_pristine\MF6_EnKF_DISU_sim` before any further rerun.
- rerun-6-space fix commit `34d95b9` remains valid and is not implicated in this defect.

## Controller investigation — what was ruled out

| candidate | test | result |
|---|---|---|
| space in command | read the generated PST | fixed (space-free base python + temp path) — not the cause |
| numpy / wrapper logic | ran the wrapper standalone (base interpreter, cwd = workspace) | exit 0 in 1.92 s, `k.dat` 422,989 B, mf6 normal termination 1.77 s |
| interpreter health | `python -c "import subprocess,sys"` | 0.06 s |
| pipe backpressure | spawned the wrapper with the exact `_run_process` flags, PIPE never drained **and** drained by a thread | exit 0, 3.5 s both ways |
| `CREATE_NEW_PROCESS_GROUP` | tiny multiplier-scope DA (16 cells, 5 reals, 2 cycles, space-containing ws) run with the `_run_process` config (flag + merged stderr) vs the sync config (no flag, separate pipes) in two fresh workspaces | **both completed, exit 0, 4 phi rows, ~10 s each** — flag benign |
| disk/AV write latency | pure-Python `'%.10g\n'` write+read of a 413 KB K array on E: and on C: | 0.02 s write / 0.01 s read on both |
| E: storage health | `Get-Volume`/`Get-PhysicalDisk` | E: = Crucial BX500 SSD, NTFS, Healthy/OK (D: is the failing exFAT HDD, unrelated) |
| background worker drains stdout | read `_impl_start_calibration` | yes (`for line in proc.stdout`) |
| sync path | re-ran the committed multiplier-space-workspace regression test | converged in 13 s |

**Conclusion:** the stall is **scale-dependent** (large DISU model) and reproducible only in the
closed-book holdout runs; the small-scale multiplier DA works under every spawn configuration
tested. The deep cause is still unidentified — it is not the space, numpy, the wrapper logic, the
pipe, the process-group flag, the disk or the interpreter. Meanwhile the previously-filed
background-wrapper stall findings (zenodo rerun-4, mf6brabant rerun-3, neversink rerun-3) are the
same class and all involve large models plus a Python-wrapper model command.

## The agent's own run log (`.kilo/worktrees/6d-enkf-disu-rerun7/run-log.md`)

Written just before the session was stopped; 219 lines. It confirms and adds:

- ~~The run was abandoned~~ **Corrected:** the agent explicitly **cancelled** the E: DA job (`ffa6d3f4e33d`)
  with `cancel_job` after ~13 min stuck at cycle 0 / realization 3 — that is what killed the E:
  `pestpp-da` at ~17:12, not a crash. Its second job (`7eed1ea0a965`, temp workspace) ended after
  **504.38 s** with `status: succeeded` but `converged: false`, `cycles: 0`, `final_phi_mean: null`;
  in fact the controller terminated that frozen tree at ~15:26Z, which is what ended the 504 s window.
- Baseline on the E: workspace, cycle-0 forcing (29 d, converged 1.86 s): RMSE **2.176 m**, bias
  −2.121 m, R² 0.462 — a usable, non-arbitrary phi scale. Pristine shipped 6×1-day model: RMSE
  3.870 m, R² −0.702 (not like-for-like).
- Setup details: 15 parameters (13 `head_state` + log `k_mult` 0.1–10 + fixed `perlen`), one-token
  `flow_k_mult.dat.tpl`, state-augmented `flow_strt.dat.tpl`, `modflowsim.tdis.tpl`, `.ins` pif,
  `da_num_reals 30`, `use_simulated_states True`. Cycle perlen `[29,56,10,74,45,26]` d (240 d),
  cycle ends = the six 2017 gauge dates; `Ne-507` dropped (no data before 2019-01-15). **0 MCP-only
  violations** — it used no raw flopy/pyemu/PEST classes, hand-edited no MODFLOW/PEST file, never ran
  `pestpp-da` itself, and never ran the repo's EnKF scripts.
- New defect detail: `clone_model` failed because it **does not copy external OPEN/CLOSE arrays**
  (`flow_input\flow.disu_IHC_1.txt`, …), so the clone is unloadable — the "`ihc` error" was the symptom.
  Filed in the rerun-7 tasks.md block.
- Reported capability gap (its §8.1): `multiplier`/`zones` scopes need the wrapper, and under
  pestpp-da the wrapper stalls ~30–215 s per run before starting MF6 and does not exit after its mf6
  child finishes, so no realisation is ever recorded.

**Evidence-contamination caveat (disclosure).** While diagnosing rerun-7 the controller ran
read-only-ish probes *in the agent's temp workspace* `%TEMP%\kilo\neck_da7_ws\sim` (wrapper run
standalone at 17:19:51; two pipe-config probes at ~17:20:14): those wrote `flow_k.dat` (422,989 B),
ran `mf6` (`mfsim.lst` 17:20:16, `flow_head.obs.csv` 17:20:15) and updated `run.info`-adjacent state.
The agent's run log therefore attributes an mf6 run "finally launched at 17:20:16" to its own stalled
wrapper, and its "wrapper still alive 4+ min after its MF6 child had terminated" reading is not
reliable — those artifacts are the controller's probes. The frozen-wrapper state itself
(0.0156–0.02 s CPU, no k.dat write, no mf6 child, one Executive-wait thread) was observed
independently before and after the probes and is unaffected; the E: workspace was never touched by
the probes.

## Options for the owner

1. **Gate with `scope="all"`** (no wrapper): the already-demonstrated-green configuration
   (rerun-4/rerun-5) on the current code — fastest route to the 6d pass, at the cost of the uniform-K
   collapse the multiplier scope was introduced to avoid.
2. **Fix the background-DA launch** before spending rerun-8: examine why a Python child of
   MCP-spawned pestpp-da blocks at interpreter startup (candidates: stdio/handle inheritance —
   try `stdin=DEVNULL` / `CREATE_NO_WINDOW` / job output to a file instead of a PIPE — or bypass the
   Python wrapper entirely for the model command).
