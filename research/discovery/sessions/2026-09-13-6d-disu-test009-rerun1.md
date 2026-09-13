# 6d session — DISU capability row (`test009_3lay-disu`), rerun-1 — criteria-green except one server defect found

- **Date**: 2026-09-13
- **Client / model**: Agent Manager worktree session (`6d-disu-test009-rerun1`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run
  from `main` live worktree at `839ebb7` (DISU grid support)
- **Worktree branch**: `6d-disu-test009-rerun1`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\`
  (MODFLOW 6 test009: 3 layers, 228 nodes, nested grid in layer 2, GNC)
- **Prompt**: 6d playbook Target 7 prompt verbatim. Full transcript in the run-log.
- **Run-log**: `2026-09-13-6d-disu-test009-rerun1-runlog.md`.

## Outcome vs criteria

- **check_environment**: PASS.
- **Copy + adopt**: PASS — files copied verbatim, `adopt_model(units=METERS,
  allow_modify=true)`; GNC retained; grid not rebuilt.
- **check_model**: PASS — clean.
- **run_simulation**: PASS — converged, normal termination, 2 outer iterations.
- **Postprocess**: PASS — `read_heads` shape [1, 228], min 0.0 / max 1.0 / mean 0.5;
  balance closes (net −1.5e-8); `summarise_model` grid
  `{DISU, nlay 1, nnodes 228, ncells 228, nja 1372}`; `model_status` runnable;
  `validate_model` clean.
- **Builder path** (`add_disu_package`): PASS — a fresh 3-node DISU model built through the
  MCP and run (converged). One in-session self-correction: boundary cell ids on DISU are bare
  **node** indices (not `(layer, node)`) — confirmed the tool converts 0-based → 1-based.
- **x/y-dependent tools**: PASS (documented) — `plot_heads_map` and coordinate-mode
  `import_obs_from_csv` both return `INVALID_INPUT` with the clear "no cell x/y geometry"
  message; no head map is produced.
- **Reprompts**: 0. **MCP-only violations**: 0.

## Server defect exposed (fixed after this run)

**DISU observation files were written 0-based.** `import_obs_from_csv` (sequential mode) put
0-based node ids in the `.obs` file. Unlike the boundary packages, FloPy does not add 1 to a
*scalar* DISU cellid, so MF6 read
`Node number in list (0) is outside of the grid ... Error occurred while reading file
'disu_small.obs'`. The base run therefore failed and the PEST chain reported
`Base parameter run failed. Can not compute the Jacobian`. The agent did **not** hand-edit the
file (MCP-only constraint) and reported it as a capability gap.

Fixed at commit `f6bf…`: the sequential DISU obs mapping stores the 1-based node number
(so `site_cellid_map`/meta report 1-based ids on DISU), with regression tests for the
on-disk 1-based ids + a running model and for a DISU `setup_calibration` base run.

## Gate position

Criteria 1–5, 7 and 8 are green on the shipped DISU model; criterion 6 (obs → calibration)
was blocked by the defect above. Not yet a green run for the gate; re-run after the fix.
