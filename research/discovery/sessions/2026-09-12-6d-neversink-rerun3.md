# 6d session — neversink_workflow (DOI-USGS watershed model), rerun-3 — clean set-and-forget run

- **Date**: 2026-09-12
- **Client / model**: Agent Manager worktree session (`6d-neversink-rerun3`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) —
  server run from `main` live worktree (zoned capability `35648da`; re-runnability
  fixes `1bac781` + `733cd74`)
- **Worktree branch**: `6d-neversink-rerun3`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\`
  (restored to the pristine shipped state before this run; `neversink` registration cleared)
- **Prompt**: 6d playbook Target-6 prompt verbatim + a rerun-3 note (both fixes
  landed, holdout pristine, clean set-and-forget expected). Full transcript in the run-log.

## Outcome vs criteria

All seven criteria PASS; **0 reprompts, 0 MCP-only violations**.

- **check_environment**: PASS — full stack present.
- **Adopt**: PASS — `neversink` adopted from the shipped `neversink_mf6`
  **read-only/pristine** (no rebuild, no renames).
- **Check**: PASS — 0 errors; 105 shipped BC-in-inactive-cell warnings documented.
- **Run**: PASS — `start_run` normal termination ≈28 s.
- **Postprocess**: PASS — `read_heads` L0 88.10…631.17 (mean 361.49 m);
  water balance closes (net −0.082 m³/d, discrepancy −1.6e-5 %); head map;
  `validate_model` reports only shipped-model conditions.
- **Calibrate**: PASS — base model left pristine; calibration on a **clone**
  (`clone_model` → `neversink_cal`, `allow_modify=True`). `import_obs_from_csv`
  registered 448 field observations (447 NY-DEC `gw_elev_m` + 1 NWIS; exact
  one-to-one match with the model's 448 unique OBS6 site names), layer 4.
  `setup_calibration(scope="zones")` → **20 dimensionless zone multipliers**
  across all four layers (9/7/3/1 zones; zone `base_k` exactly the shipped K
  values, so the pattern is preserved — **fix (a) confirmed**).
  `run_pestpp_glm` (synchronous) completed; φ native **725,261 → 327,897**
  (−54.8 %); RMSE **40.24 → 27.05 m**, bias +24.38 → −6.56 m, R² 0.914.
- **Reprompts**: 0. **MCP-only violations**: 0.

## Fix confirmation

- **(a) zoned/multiplier parameterisation**: works; 20 zone multipliers, shipped
  K values reported as `base_k`.
- **(b) re-runnability**: `setup_calibration` was called three times in-session
  (layer 1, then twice at layer 4) with **no K corruption** — zone `base_k`
  identical across calls.

## Deviations from the source model

- Outputs regenerated in place in `neversink_mf6\` by the base run (no input modified).
- Calibration uses a **clone** (`neversink_cal` in temp), not the shipped dir.
- Observation set registered at a single layer (4) — `import_obs_from_csv`
  replaces rather than merges per-layer OBS packages; layer 4 is the only layer
  active at all 448 wells (justified in the run-log; vertical gradient median
  1.09 m vs the 40 m native misfit).
- Clone NPF rewired to an external K array with per-zone multipliers; k33/IC/DIS/BC/SFR unchanged.
- `noptmax` capped at 5 on the clone to bound runtime.

## Limitations / findings (→ v0.2.0 backlog)

- **`start_calibration` (background GLM) hung twice**: the generated forward
  wrapper deadlocked before launching MF6 (no `mf6` child, stuck at the base
  run). The synchronous `run_pestpp_glm` ran the identical `.pst` to completion
  (client timed out, server-side completed). The background runner and the
  generated wrapper appear incompatible in this uv-venv environment. This is the
  one toolchain issue in an otherwise clean run; it is **not** an MCP-only
  violation (the synchronous tool is part of the documented chain).
- Two zone multipliers sit at the ×10 upper bound (`k_l0_z2`, `k_l1_z13`) —
  wider bounds for insensitive zones.
- `summarise_calibration.verdict improved=false` is a bookkeeping artefact
  (no prior in-session calibration to compare against); vs the native prior the
  fit improved 54.8 %.
- Observation quality: a subset of NY-DEC wells carry round sentinel depths
  (500/1000 ft); 11 wells with |native residual| > 100 m retained (not
  cherry-picked) and cap the achievable fit.
- Single-layer obs registration cannot reproduce the model's per-well screened
  layer mapping.

## Time

≈4 h (dispatched 11:18, run-log written 16:41).

## Gate position

**GREEN.** rerun-2 (criteria-met green, with the re-runnability defect found and
fixed) + rerun-3 (clean set-and-forget) form **≥2 consecutive green runs** under
the playbook's definition (0 reprompts, full criteria met, last run
set-and-forget). Marked **PASSED 2026-09-12**; owner tick and the strict-reading
caveat noted in `holdout-registry.md` / `tasks.md`.
