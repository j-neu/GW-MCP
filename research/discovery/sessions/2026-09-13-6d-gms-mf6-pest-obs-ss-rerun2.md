# 6d session — GMS `mf6_pest_obs_ss`, rerun-2 — clean set-and-forget run (target PASSED)

- **Date**: 2026-09-13
- **Client / model**: Agent Manager worktree session (`6d-gms-pest-obs-ss-rerun2`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run
  from `main` live worktree at `888b870` (OC period-record restore + OBS name sanitisation)
- **Worktree branch**: `6d-gms-pest-obs-ss-rerun2`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
- **Prompt**: 6d playbook Target-4 prompt verbatim (no rerun note). Full transcript in the run-log.
- **Run-log**: `2026-09-13-6d-gms-mf6-pest-obs-ss-rerun2-runlog.md`; artifacts alongside.

## Outcome vs criteria

All seven criteria PASS; **0 user reprompts, 0 MCP-only violations**; both fixes exercised.

- **check_environment**: PASS.
- **Adopt**: PASS — session copy of the shipped DISV set adopted with `units=FEET,
  allow_modify=true`; no grid rebuild. One in-session self-correction (the first adopt
  defaulted to `units=METERS`; the agent unregistered and re-adopted as FEET) — no user
  intervention.
- **Check**: PASS — `check_model` clean; `model_status` runnable, no missing packages.
- **Run**: PASS — normal termination, 0.198 s.
- **Postprocess**: PASS — `read_heads` 304.8–316.64 ft; `compute_water_balance` closes
  (RCHA +5811.635, RIV −5434.209358, CHD −249.958, WEL −130; discrepancy −0.0436 %,
  `balanced=true`); head map. Base RIV discharge **−5434.209358 exactly matches the shipped
  reference**.
- **Calibrate**: PASS — 10 head bores imported from `model.b2map` via `import_obs_from_csv`
  (nearest DISV cells); base fit RMSE 10.296 vs reference 10.275. `setup_calibration`
  (npf:k, scope all, 1 parameter) → `run_pestpp_glm` → `summarise_calibration`:
  φ 1060.06 → 208.04 → 116.83 → 116.50 (converged, iteration 4); K 2.4 → **0.552 ft/d**;
  head RMSE **10.296 → 3.413**, bias −0.471, MAE 2.326, R² 0.868, no bounds hit. Calibrated
  `run_simulation` reproduces the PEST result exactly.
- **Reprompts**: 0 user reprompts (one in-session self-correction, above).
  **MCP-only violations**: 0.

## Fix confirmation (from rerun-1)

- **(a) OC period records**: the shipped `OPEN/CLOSE` period file was restored on adopt; the
  base and calibrated runs wrote `.hds`/`.cbc` with **no OC re-add** — `restore_oc_period_records`
  confirmed (`saverecord {0: [HEAD FIRST, BUDGET FIRST]}`).
- **(b) OBS name sanitisation**: the shipped `POINT_#1…10` names registered **without
  corruption** (sanitised consistently in the OBS file, meta and instruction file) — no
  rename step needed.
- **(c) `obs_type` validation**: `obs_type="FLOW"` now fails fast with the documented gap
  message instead of writing an MF6-invalid record and replacing the head observations.

## Deviations from the source model

- Adopted a **session copy** of the shipped runnable set with `allow_modify=true` (base
  reference untouched); same input set, no rebuild.
- Observation representation: heads mapped to the nearest single DISV cell vs the shipped
  4-node `model.n2b` interpolation; PEST weight 1.0 vs `model.bwt`/`model.fwt`.
- Flow metric evaluated with `compute_water_balance` (as the MCP directs), not as an OBS.
- `setup_calibration` used instead of the prompt's `setup_pest_control` (which requires
  pre-existing template/instruction files that the MCP-only rule forbids hand-writing);
  `setup_calibration` is the supported generator and subsumes it.
- Units: model-native FEET/DAYS constants used unchanged; `summarise_model` labels K/recharge
  as `m/d` (metadata display only — no conversion applied).

## Limitations / findings (→ v0.2.0 backlog)

- **Compound total-RIV FLOW observation not representable** by any OBS6 continuous type;
  now rejected loudly. Calibration is consequently head-only, and the flow residual degrades
  under head-only calibration (+790.21 → +891.43).
- **`setup_calibration` supports only `npf:k`** — `rch:recharge` (and river conductance) are
  refused; only hydraulic conductivity is calibratable through the automatic path.
- **`run_pestpp_glm` client timeout** — completed server-side; use `start_calibration` +
  `get_job_status` for long jobs (already a v0.2.0 item).
- **Adopt units default** to METERS regardless of the shipped `LENGTH_UNITS` — caused the one
  self-correction; auto-detect from the MF6 NAM/DIS file.
- `summarise_model` units label hardcoded `m/d` for a FEET model (display).
- Multi-node obs interpolation and observation weights not importable.

## Gate position

**GREEN.** rerun-1 (criteria-green, with two server defects found and fixed at `888b870`) +
rerun-2 (clean set-and-forget, both fixes exercised) form **≥2 consecutive green runs** under
the playbook definition (0 user reprompts, full criteria met, last run set-and-forget).
Marked **PASSED 2026-09-13**; strict-reading caveat noted in `holdout-registry.md` / `tasks.md`.
