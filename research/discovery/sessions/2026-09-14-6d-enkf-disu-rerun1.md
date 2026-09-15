# 6d target-8 rerun-1 — `MF6_EnKF_DISU` (Neckartal DE): DISU DA gap closed

- **Date**: 2026-09-14 (fix landed 2026-09-15, Task 7)
- **Run log**: `.kilo/worktrees/6d-enkf-disu-rerun1/run-log.md`
- **Task brief**: `.superpowers/sdd/2026-09-13-da-ready-pst-orchestrator/task-7-brief.md`
- **Type**: capability fix (no closed-book rerun in this session)

## What the run log established

The first closed-book rerun of the Tier-1 target `MF6_EnKF_DISU` (a **DISU** model,
31,831 nodes) completed steps 1–5 (adopt, `check_model`, TDIS re-expression to
`NPER=1`/`NSTP=1`, registration of 13 Neckartal gauges) and the step-8 postprocess, but
**steps 6–7 were blocked** by a hard toolchain gap:

```
setup_da_control IC state parameterisation supports DIS and DISV grids only;
this model has neither.
```

`setup_da_control` forces `use_simulated_states=True`, whose state-augmented IC
parameterisation accepted DIS/DISV only; `use_simulated_states=False` is rejected by
design (pestpp-da v5.2.16 needs final-to-initial state linkages the tool does not emit).
The two branches were mutually exclusive, so **no input made `setup_da_control` succeed
on a DISU model** and `run_pestpp_da` / `summarise_da` could not be exercised on the
target.

The run log's **secondary finding** was that the failure was **non-transactional**:
`_impl_setup_da_control` called `_restore_or_snapshot_k_base` / `_impl_rewire_npf_k_external`
*before* the DIS/DISV grid check, so the failed call left the Neckartal model with
uniform `K=1` in `flow_k.dat` and a rewritten single-period `flow.sto` — the calibrated
heterogeneous K field was lost on disk.

## Root cause

`_da_cell_flat_index` (`src/groundwater_mcp/tools/calibration.py`) mapped a site's stored
cell id to the flat index of the external IC array for DIS and DISV, then raised for
anything else. DISU stores each site's cell id as a scalar **1-based node**
(`import_obs_from_csv` does `site_to_cellid[site] = node + 1`;
`_cellid_as_json` keeps ints as ints), so the flat index is `int(cellid) - 1` on an
`nnodes`-node grid. The two neighbouring rewires
(`_impl_rewire_npf_k_external`, `_impl_rewire_ic_strt_external`) were already
grid-agnostic — only the index mapping and the ordering were wrong.

## Fix (Task 7)

1. **DISU branch in `_da_cell_flat_index`**: accepts a bare int or a 1-element
   list/tuple, returns `node - 1`, and validates `0 <= flat < disu.nnodes` (so a
   1-based `0` and an out-of-range node both raise). The final error now names
   DIS/DISV/DISU.
2. **Validation before mutation in `_impl_setup_da_control`**: the grid-support check,
   the state-cell mapping / out-of-bounds check, and the pure `par_cycles` / forcing /
   parameter-name checks now all run **before** `_restore_or_snapshot_k_base` and the
   K/IC rewires. A rejected setup leaves NPF `k` and IC `strt` untouched — the run log's
   secondary finding cannot recur.
3. **Tests** (`tests/test_da_control.py`): a 5-node 1-D DISU fixture; `_da_cell_flat_index`
   maps node `5` → flat `4` and rejects out-of-bounds; `setup_da_control` produces a v2
   PST with one `head_state` parameter per site on DISU; an out-of-bounds DISU site
   raises **and** leaves no `*_k.dat` / `*_strt.dat` rewire. A DISU variant of the
   MCP-only end-to-end `pestpp-da` run was added to `tests/test_da_end_to_end.py`.
4. **Docs**: `tools.md`'s DA grid-support note now reads DIS/DISV/DISU with the DISU
   1-based-node convention and the validate-before-write guarantee.

## Evidence

- RED (before the fix): the three new tests failed with the run log's exact message
  `setup_da_control IC state parameterisation supports DIS and DISV grids only; this
  model has neither.`
- GREEN (after the fix): `tests/test_da_control.py` 28 passed (3 new DISU tests included);
  `tests/test_da_end_to_end.py -k disu` passed a real `pestpp-da` run on a DISU grid
  (>= 2 cycles, 5-member ensemble, finite phi, `summarise_da` reports the two cycles).

## Status of the Tier-1 target

The capability gap that blocked `MF6_EnKF_DISU` steps 6–7 is **closed**. A closed-book
rerun of the Neckartal model (re-adopting from the pristine staged copy, since the failed
run-1 setup left its workspace with uniform K) can now exercise
`setup_da_control → run_pestpp_da → summarise_da` on the real DISU grid. DISU has no
layer dimension — `disu.nodes.data` is the global node count and the 1-based *global*
node is what `import_obs_from_csv` stores regardless of any `layer` argument — so the
mapping is not limited to single-layer grids and the rerun is not deferred on that basis.
