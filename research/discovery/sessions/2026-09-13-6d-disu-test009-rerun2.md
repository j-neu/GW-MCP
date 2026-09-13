# 6d session — DISU capability row (`test009_3lay-disu`), rerun-2 — criteria-green (1 of 2)

- **Date**: 2026-09-13
- **Client / model**: Agent Manager worktree session (`6d-disu-test009-rerun2`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run
  from `main` live worktree at `9fb5977` (1-based DISU obs fix)
- **Worktree branch**: `6d-disu-test009-rerun2`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\`
- **Prompt**: 6d playbook Target 7 prompt verbatim. **Run-log**: `2026-09-13-6d-disu-test009-rerun2-runlog.md`.

## Outcome vs criteria — all 8 PASS; 0 user reprompts, 0 MCP-only violations

- **Environment**: PASS — full stack, `ready: true`.
- **Copy + adopt**: PASS — 11 files copied verbatim, `adopt_model(units=METERS, allow_modify=true)`,
  grid/GNC not rebuilt.
- **check_model**: PASS — clean.
- **run_simulation**: PASS — `start_run`/`get_job_status`; converged, normal termination (0.11 s).
- **Postprocess**: PASS — `read_heads` 228 nodes min 0 / max 1 / mean 0.5; balance closes
  (net −1.5e-8); `summarise_model` grid `{DISU, nlay 1, nnodes 228, ncells 228, nja 1372}`;
  `model_status` runnable; `validate_model` clean.
- **Builder + obs + calibration**: PASS — a fresh 3-node DISU model built with
  `add_disu_package`, run (converged); sequential obs import maps to **1-based** nodes
  (`{n1:1, n2:2, n3:3}`); `observation_fit rmse 0`; `setup_calibration` generated a complete
  PEST interface and `run_pestpp_glm` → `summarise_calibration` completed (φ 0; perfect
  synthetic fit — synthetic obs equal the forward solution).
- **x/y-dependent tools**: PASS (as designed) — `plot_heads_map` and coordinate obs return
  `INVALID_INPUT` with the clear no-geometry message; no head map produced.
- **Self-corrections (no user reprompt)**: DISU `ihc` convention and scalar CHD node cellid.

## Gate position

First clean green run after the `9fb5977` obs fix (rerun-1 failed criterion 6). Needs one more
consecutive green → rerun-3.
