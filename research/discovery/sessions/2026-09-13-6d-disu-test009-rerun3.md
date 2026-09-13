# 6d session — DISU capability row (`test009_3lay-disu`), rerun-3 — clean second green (row PASSED)

- **Date**: 2026-09-13
- **Client / model**: Agent Manager worktree session (`6d-disu-test009-rerun3`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run
  from `main` live worktree at `9fb5977`
- **Worktree branch**: `6d-disu-test009-rerun3`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\`
- **Prompt**: 6d playbook Target 7 prompt verbatim. **Run-log**: `2026-09-13-6d-disu-test009-rerun3-runlog.md`.

## Outcome vs criteria — all 8 PASS; 0 user reprompts, 0 MCP-only violations

- **Environment**: PASS — stack ready.
- **Copy + adopt**: PASS — files copied verbatim; adopted as `r3t009disu` (unique name to avoid
  a stale registration — see friction 5).
- **check_model**: PASS — clean.
- **run_simulation**: PASS — converged, normal termination (0.034 s).
- **Postprocess**: PASS — `read_heads` 228 nodes min 0 / max 1 / mean 0.5 (layer>0 rejected with
  a clear range error, since DISU is flattened to nlay 1); balance closes (net −1.5e-8);
  `summarise_model` grid `{DISU, nlay 1, nnodes 228, ncells 228, nja 1372}`; `model_status`
  runnable; `validate_model` clean; GNC detected and carried.
- **Builder + obs + calibration**: PASS — fresh 3-node DISU built with `add_disu_package`, run
  (converged, heads [1.0, 0.5, 0.0]); sequential obs → `site_cellid_map {n1:1,n2:2,n3:3}`;
  `setup_calibration` generated pst/template/instruction/forward wrapper with
  `n_observations 3`, `n_adjustable_parameters 1`; the verification run wrote
  `r3disu3line_head.obs.csv` (`time,N1,N2,N3 / 1.0,1.0,0.5,0.0`) and
  `read_simulated_observations` returned `{n1:1.0, n2:0.5, n3:0.0}`. (`run_simulation` hit a
  client timeout but `get_run_log` / outputs confirmed normal termination — known v0.2.0 item.)
- **x/y-dependent tools**: PASS (as designed) — `plot_heads_map` and coordinate obs return
  `INVALID_INPUT` with actionable messages; no map produced.
- **Self-corrections (no user reprompt)**: scalar DISU CHD node cellid; unique model name.

## Friction / follow-ups (not gate-blocking)

1. **`add_boundary_package` on DISU silently truncates a multi-element cellid.** A `(layer,node)`
   id is reduced to its first element, so two records can collapse onto node 1 and abort with
   "Cell is already a constant head". The tool should reject a non-scalar cellid on a DISU grid
   with a clear message instead of silently producing a wrong file.
2. **Cross-worktree model-name ambiguity.** Each explicit workspace root has its own registry, so
   the same model name in two Agent Manager worktrees is legal but `resolve_workspace` returns
   the first known root, not necessarily the one just adopted. `adopt_model` should warn when the
   name already resolves to a different workspace root, and the rerun prompts should require
   session-unique model names.
3. **Client timeout on instant runs** (`run_simulation`/`run_pestpp_glm`) — already a v0.2.0 item;
   `get_run_log`/`get_job_status` are the documented fallback.
4. **DISU is flattened to nlay 1**, so per-layer tools (`read_heads` layer>0) reject the physical
   layers 1/2. Inherent to FloPy's `UnstructuredGrid`; documented.

## Gate position

**GREEN.** rerun-2 + rerun-3 are two consecutive criteria-green runs (0 user reprompts, 0 MCP-only
violations), both on the fixed `9fb5977`. **DISU capability row PASSED 2026-09-13** on
`test009_3lay-disu`; the gate's other named refs (`ex-gwf-radial`, GMS Quadtree) remain optional
future reruns.
