# Zoned NPF K multiplier calibration — design

- **Date:** 2026-09-11
- **Status:** approved (pending user review of this document)
- **Author:** agent (brainstorming session)
- **Scope:** new `scope: "zones"` for `setup_calibration`, plus the follow-on
  neversink closed-book rerun.

## Problem

`setup_calibration` (7e-A2) can only parameterise `npf:k` as an
absolute, whole-array replacement: supported scopes are `all`, `layer`, and
`cells`, and `_normalise_parameterisation` **requires every cell to be claimed
exactly once**. There is no multiplier mode and no partial coverage.

Real regional models ship **zoned** K fields. The neversink_workflow model
(`selected/neversink_workflow/neversink_mf6/`, USGS) has per-layer external K
arrays whose positive values are a small set of zone values, e.g. `k1.dat`
contains 7 distinct positive values (0.050292 … 60.96 m/d). The high-K
valley-fill conductors are numerically load-bearing for the SFR/Newton solve,
so **any** uniform-per-layer replacement K makes perturbed forward runs
non-convergent (persistent mass-balance residual at cell L1 249,182; GLM never
completed a clean iteration — see
`research/discovery/sessions/2026-09-08-6d-neversink-rerun1.md`). The 6d
neversink target is therefore NOT green: 4 of 8 Tier-1 targets passed.

The same gap was recorded independently against mf6brabant rerun-4 ("no
zoned/multiplier parameterisation for spatially-distributed K").

## Goal

Let an agent calibrate a zoned K field through the MCP chain with a small
number of adjustable parameters that **preserve the base spatial pattern**,
so that a perturbed forward run stays numerically well-posed.

## Non-goals

- Zoned multipliers on recharge (`rcha:recharge`) or any target other than
  `npf:k`. The neversink findings note the rejected `rcha:recharge` target;
  that stays on the backlog.
- Zone maps supplied as rasters/shapefiles. Zones are auto-derived from the
  existing K array only.
- A general multiplier framework over `k33`, STO, EVTA, etc.
- Changing the existing `all` / `layer` / `cells` scopes.

## Approach

Extend `setup_calibration` with `scope: "zones"`. Auto-derive zones from equal
base-K values per layer; expose one dimensionless multiplier parameter per
zone; apply `k = base_k × multiplier[zone]` in the forward run via the
generated Python wrapper. True multiplier semantics are required because PEST
templates substitute values literally, so something must compute the product;
the wrapper already exists for neversink's space-containing workspace path.

## 1. API / schema

A zone spec keeps the existing `target: "npf:k"` and adds `scope: "zones"`
with a required `layer`:

```json
{
  "kL1": {
    "target": "npf:k",
    "scope": "zones",
    "layer": 1,
    "initial": 1.0,
    "lower_factor": 0.1,
    "upper_factor": 10.0,
    "partrans": "log",
    "max_zones": 50
  }
}
```

- The outer dict key is the parameter-name **prefix**; zone parameters are
  named `<prefix>_z<index>` with `index` starting at 1 (`kL1_z1` … `kL1_z8`).
  The full name is validated against PEST's 12-character cap.
- `initial` is a dimensionless multiplier, default `1.0`; must be > 0.
- `lower_factor` / `upper_factor` (defaults `0.1` / `10.0`) bound the
  multiplier as `initial × factor`; `partrans` defaults to `"log"`.
- `max_zones` (default 50) caps the number of distinct zones for that layer.
- **Several `zones` specs may coexist in one call** (one per layer). They
  share one zone map and one multiplier file.
- **Mixing a `zones` spec with `all` / `layer` / `cells` in the same call is
  rejected** with `INVALID_INPUT`. The two template mechanisms (direct K-array
  tokenisation vs. multiplier-file tokenisation + wrapper) do not combine.
- Zones are ordered by `(layer ascending, base K ascending)`, so parameter
  names and the multiplier-file line order are deterministic and reproducible
  across specs in the same call.
- `initial` should normally be `1.0` (the base field). A non-1.0 value scales
  the whole zone at the initial point; the result carries a `warning` when
  `initial != 1.0` so the caller is not surprised that the initial state is
  not the shipped field.

### Result additions

`setup_calibration` returns the existing fields plus a `zones` block:

```json
{
  "zones": [
    {"name": "kL1_z1", "layer": 1, "base_k": 0.050292, "n_cells": 9393,
     "initial": 1.0, "lower_bound": 0.1, "upper_bound": 10.0}
  ]
}
```

and, when the multiplier mechanism is active, `template_file` points at the
multiplier template and `forward_wrapper` is non-null.

## 2. Zone derivation

For each `zones` spec:

1. Read the model's current NPF `k` array (base field), shaped by the grid
   type (2-D per layer for DIS; 1-D per layer for DISV).
2. Select the spec's layer; validate `0 <= layer < nlay`
   (`INVALID_INPUT` otherwise).
3. Group cells by base K value, where two finite positive values are treated as
   equal when they agree after rounding to 6 significant figures. Rounding (not
   exact-bit equality) keeps grouping stable against float representation while
   distinguishing the shipped zone values (0.050292, 0.16764, …). Only cells
   with finite `k > 0` are zoned. Non-positive / non-finite cells (inactive) are
   fixed.
4. If the layer has no positive-K cell → `INVALID_INPUT`.
5. If the number of distinct positive values exceeds `max_zones` →
   `INVALID_INPUT` naming the count and the cap, and pointing at a coarser
   input (the tool will not silently emit thousands of parameters).
6. Sort the distinct values ascending; zone `i` (1-based) is the i-th value;
   every cell with that value belongs to zone `i`.

**Partial coverage is allowed.** Cells in other layers, and non-positive
cells, are written at their base value and carry no parameter. This is the
behaviour the current tool refuses.

## 3. Files and forward mechanism

When any `zones` spec is present, `setup_calibration` writes these workspace
files:

| File | Purpose |
|---|---|
| `<gwf>_k_base.dat` | the base K field, all cells, written once |
| `<gwf>_k_zone.dat` | full-grid integer zone map; `0` = fixed, else zone index |
| `<gwf>_k_mult.dat.tpl` | PEST template: exactly one wide token per zone |
| `<gwf>_k_mult.dat` | target of the template; one multiplier value per line |
| `<gwf>_k.dat` | the runtime NPF `k` external file (NPF stays `OPEN/CLOSE`) |

Zone order in `<gwf>_k_zone.dat` matches the template line order and the
returned `zones` list — `(layer ascending, base K ascending)` across every
`zones` spec in the call, with zone indices `1..N` contiguous and global.

`setup_calibration` reuses `_impl_rewire_npf_k_external` to put NPF `k` behind
`OPEN/CLOSE <gwf>_k.dat`, then snapshots the array to `<gwf>_k_base.dat`.
Because `<gwf>_k.dat` is read by MODFLOW directly, `setup_calibration` also
writes it once with the base field so a plain `run_simulation` (without a
wrapper forward run) still runs the unperturbed model.

### Forward wrapper

The forward wrapper is **forced** whenever `zones` is used (not only when the
path contains spaces). It:

1. reads `<gwf>_k_base.dat` and `<gwf>_k_zone.dat`;
2. reads `<gwf>_k_mult.dat` (one multiplier per line, zone order);
3. computes `k = base` for zone `0`, `k = base × mult[zone]` otherwise;
4. writes `<gwf>_k.dat`;
5. runs MODFLOW 6 in the workspace and returns its exit code.

At `initial = 1.0` every multiplier is `1.0`, so the written `k` equals the
base field exactly (bit-for-bit) and the model is unchanged at the initial
point. The existing wrapper remains for the spaces-only case when no `zones`
spec is present.

`check_parameter_sensitivity` needs one targeted change: it runs MODFLOW
directly (`_impl_run_simulation`), which reads `<gwf>_k.dat` and ignores the
multiplier file, so a zone perturbation would register as zero sensitivity.
The screen detects the multiplier file by **filename matching**
(`_maybe_apply_zone_multipliers`: a template target named `<gwf>_k_mult.dat`)
and, after each `_tpl_substitute`, re-applies `k = base × mult[zone]` to
`<gwf>_k.dat` before the direct run. No sidecar file is written or read.
`run_pestpp_glm`, `run_pestpp_ies`, and `summarise_calibration` need no
changes: pestpp invokes the wrapper, which already applies the multipliers.

## 4. Errors and limits

All new failures return the standard envelope with `code: "INVALID_INPUT"`:

- a `zones` spec mixed with an `all` / `layer` / `cells` spec in one call;
- `scope="zones"` without `layer`, or `layer` outside `[0, nlay)`;
- no positive-K cells in the spec's layer;
- more distinct positive values than `max_zones`;
- a generated zone parameter name longer than 12 characters;
- `initial <= 0` or non-finite.

## 5. Testing

Test-driven, matching the project's existing calibration tests. New tests
cover:

- **Zone derivation:** grouping by equal value; inactive (`k <= 0`) excluded;
  deterministic ascending order; one spec per layer independent; `max_zones`
  cap fires; DIS and DISV grids.
- **Multiplier template:** exactly one wide token per zone; tokens map to the
  zone parameter names; token width ≥ 15.
- **Wrapper multiplication:** `base × mult` produced correctly per zone;
  `mult = 1` reproduces the base array bit-for-bit; fixed (zone 0) cells
  unchanged; wrapper writes `<gwf>_k.dat` before running MF6.
- **Partial coverage:** a layer without a spec, and inactive cells, keep their
  base values after `setup_calibration`.
- **Sensitivity screen:** `check_parameter_sensitivity` on a zoned
  parameterisation applies the multiplier to `<gwf>_k.dat` before each direct
  run, so a perturbed zone reports non-zero sensitivity and the unperturbed
  base run reproduces the base field.
- **End-to-end synthetic model:** build/adopt a small model with a zoned K
  field and registered observations → `setup_calibration(scope="zones")` →
  forward run converges → parameter count is the zone count, not the cell
  count → one GLM or IES iteration improves phi.
- **Regression:** existing `all` / `layer` / `cells` behave as before; a
  non-`zones` call still uses the direct K-array template and does not force
  the wrapper when the path is space-free.
- **Error cases:** each §4 case.

`ruff` and `mypy` clean on touched files; full pytest suite green.

## 6. Docs and validation

In the same commit(s) as the code:

- `tools.md`: document `scope: "zones"`, the multiplier semantics, the files,
  the partial-coverage behaviour, and the `zones` result block.
- `README.md`: no tool-count change (66) — note the extended calibration
  capability in the tool table/module description.
- `architecture.md`: record the capability under the calibration module and
  the 7e/7f deviation notes.
- `research/capability-matrix.md`: calibration / zoned-K row update.
- `tasks.md`: mark the neversink zoned-parameterisation gap addressed; keep
  the target's validation status open until the reruns pass.

### Neversink replay

After the code, tests, and docs land, dispatch the closed-book Agent Manager
rerun(s) (owner: the agent, per the approval):

1. `6d-neversink-rerun2` — Target-6 prompt, calibrating through
   `setup_calibration(scope="zones")`.
2. `6d-neversink-rerun3` — set-and-forget confirmation.

The target is PASSED when ≥ 2 consecutive closed-book reruns are green
(0 reprompts, 0 MCP-only violations, calibration improves phi through the MCP
chain). Session logs go to `research/discovery/sessions/`; update
`research/holdout-registry.md` and `tasks.md` with the outcome. If a rerun
exposes a defect, fix it, add a regression test, and repeat before the
confirmation rerun.

## Risks

- **Wrapper reliability.** Background calibration and wrapper hangs have been
  observed on this Windows host (zenodo rerun-4, mf6brabant rerun-3). Neversink
  already requires a wrapper because its workspace path contains spaces, so
  this adds no new dependency there; the synchronous `run_pestpp_glm` /
  `run_pestpp_ies` path is the reliable fallback if `start_calibration` stalls.
- **Zone-value noise.** A layer whose K is a near-continuous field would
  exceed `max_zones`; the cap fails loudly rather than emitting a huge
  parameter set. Rounding for grouping must be defined and tested.
- **Template/param name collisions.** `<prefix>_z<index>` names must be unique
  within the `.pst` and ≤ 12 characters; validated up front.
