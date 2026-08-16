# v0.1.0 Gate — Transient support (STO) + expanded validation

Source: design review session 2026-08-16 (pushback on Phase 6 validation scope).
Decision: make transient support + expanded validation a **gating step for v0.1.0**.

**Status: IMPLEMENTED 2026-08-16** — `add_sto_package` (39th tool), guard,
name-length validation, transient + calibration integration tests, holdout STO
replay, test005 + freyberg holdout rounds, docs/matrix/registry updated. Full
suite green (see `2026-08-16-transient-support-and-validation-gate-plan.md`).

## Problem

The v0.1.0 tool set has no STO package, so a build-from-scratch *transient*
model is impossible — and worse, it fails **silently**: a model configured with
`set_simulation(nper>1 or nstp>1)` and no STO runs as steady state per step
(MF6: "If the STO Package is excluded ... the model represents steady-state
conditions"), with `check_model` clean and `run_simulation` reporting success.
Verified empirically 2026-08-16 (probe model, 9 time steps, 0.027 s, no
warning). All 233 existing tests are steady-state, so none could catch it.
The README's flagship claim ("Build a 3-layer transient model ... run it for
2 years") is not achievable with current tools.

## Scope (approved)

1. **`add_sto_package` tool** (39th tool, builder.py) — storage + steady/transient
   period control.
2. **Loud-warning guard** — `check_model` + `run_simulation` warn prominently
   when a transient-looking model has no STO. (User chose warning, not hard
   error: multi-period steady-state models are valid MF6.)
3. **Model-name length guard** — `create_model` rejects names > 16 chars
   (pre-registered backlog item; found in holdout replay).
4. **Docs/matrix sync** — tool counts 38→39, STO row gap→covered, registry rows.
5. **Tests (TDD)** — builder/runner/protocol/holdout-replay updates + new
   `test_integration_transient.py`.
6. **Holdout expansion (full round)** — `test005_advgw_tidal` + pestpp
   `mf6_freyberg/template` downloaded into `GW-MCP-holdout/selected/`; replay
   rows added.

## Design detail

### add_sto_package

```
add_sto_package(model, iconvert, ss, sy=None, steady_state=None, save_flows=True)
```
- `iconvert` int|list (0 confined, 1 convertible), `ss` float|list (specific
  storage), `sy` float|list|None (specific yield; REQUIRED if any cell has
  iconvert>0), `steady_state` list[int]|None (0-based SP indices marked steady;
  default `[0]` → first period steady, rest transient; nper=1 stays steady),
  `save_flows` bool = True.
- Wraps `mf6.ModflowGwfsto`. Validates: sy presence when convertible cells
  exist; positive ss; steady_state indices within nper (when TDIS present).
- Replaces a previous STO package with a warning (pattern: `add_boundary_package`).
- Returns `{model, package: "STO", steady_state_periods, transient_periods,
  save_flows}`.
- NOTE: verify flopy 3.10.0 `ModflowGwfsto` period-index convention
  (0-based vs 1-based for `steady_state`/`transient`) during implementation and
  normalise so MCP stays 0-based.

### Transient-without-STO guard

- Shared helper in builder.py: `_transient_like_without_sto(sim, gwf) -> tuple[bool, str]`.
  Transient-looking = TDIS has `nper > 1` or any `nstp_i > 1`, AND `gwf` has no
  `sto` package.
- `check_model` (runner.py): append structured warning to the warnings list.
- `run_simulation` (runner.py): add `"warning"` key to the result envelope,
  write to stderr, and prepend to `listing_summary`.
- `summarise_model`: report `storage` — STO present + resolved steady/transient
  periods, or a note when missing (agents can self-verify).

### Model name guard

`create_model`: reject names with `len(name) > 16` — `INVALID_INPUT` error with
clear message (MF6 MODELNAME cap), before workspace creation.

### Tests

- `test_builder.py`: STO defaults / custom periods / sy-required / overwrite
  warning / steady-state period resolution / transient-like helper.
- `test_runner.py`: check_model + run_simulation warn without STO; silent with
  STO; summarise_model reports storage.
- `test_mcp_protocol.py`: 39 tools; add_sto_package present; error paths.
- `test_holdout_replay.py`: drop `add_sto_package` from `_GAP_TOOLS`; extend
  `_load_project` to parse STO; replay STO for test051/test020; add
  test005_advgw_tidal + freyberg replay rows.
- New `tests/test_integration_transient.py` (skipped without MF6 binary):
  - transient model via MCP → run → heads evolve across time steps;
  - water balance includes STO storage term;
  - full calibration chain on a small transient model.

### Holdout expansion

- `test005_advgw_tidal`: shallow clone of MODFLOW-ORG/modflow6-testmodels @
  `96a6d4fe015967972b051d311d34679224bc6d75`, `mf6/test005_advgw_tidal` →
  `GW-MCP-holdout/selected/test005_advgw_tidal/`.
- `mf6_freyberg`: sparse checkout of usgs/pestpp @
  `5d49814962531a0f0400cf75d0f9442c0504c714`, path `benchmarks/mf6_freyberg/template`
  → `GW-MCP-holdout/selected/mf6_freyberg/`.
- Registry rows appended to research/holdout-registry.md with commit pins,
  capability tags, and validation status.
- Freyberg calibration replay is slow (PEST++ minutes) — env-gated / marked
  slow, not part of the default fast suite.

## Success criteria (gate)

- [ ] Transient model built, run, and post-processed end-to-end via MCP tools
      with real storage physics (heads evolve; STO term in water balance).
- [ ] Transient-without-STO model surfaces a loud warning at check_model and
      run_simulation.
- [ ] test005_advgw_tidal and freyberg replay rows green (slow suite).
- [ ] Calibration chain works on a transient model.
- [ ] Full pytest suite green; tool count = 39.
- [ ] Docs/matrix/registry updated to match.
