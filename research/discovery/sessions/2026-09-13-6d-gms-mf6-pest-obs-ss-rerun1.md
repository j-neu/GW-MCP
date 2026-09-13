# 6d session — GMS `mf6_pest_obs_ss` (MODFLOW 6 DISV PEST-observations tutorial), rerun-1 — criteria-green, exposed two server defects

- **Date**: 2026-09-13
- **Client / model**: Agent Manager worktree session (`6d-gms-pest-obs-ss-rerun1`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) — server run
  from `main` live worktree at `8a1ea74` (DISV grid-package fix)
- **Worktree branch**: `6d-gms-pest-obs-ss-rerun1`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
  (Aquaveo GMS 10.9 tutorial; MF6 generated inputs + PEST interface only)
- **Prompt**: 6d playbook Target-4 prompt verbatim. Full transcript in the run-log.
- **Run-log**: `2026-09-13-6d-gms-mf6-pest-obs-ss-rerun1-runlog.md`; artifacts alongside.

## Outcome vs criteria

All seven criteria PASS; **0 user reprompts, 0 MCP-only violations**.

- **check_environment**: PASS — full stack present.
- **Adopt**: PASS — shipped `sample/pest_obs_ss_models/MODFLOW 6/pest_obs_ss/` DISV set
  (1 layer × 3306 cells) copied to the session folder and adopted; grid never rebuilt.
- **Check**: PASS — `check_model` clean, no warnings.
- **Run**: PASS — normal termination, 0.26 s.
- **Postprocess**: PASS — `read_heads` 304.80–316.64 ft; water balance closes
  (RCHA +5811.635, RIV −5434.209, CHD −249.958, WEL −130; discrepancy ≈0.044 %);
  head map. **Reproduces the shipped reference exactly**: 10 interpolated heads match
  `model.bsamp.out` to 5 dp, RIV flow = `model.fsamp.out` (−5434.209358), stats match
  `pest_obs_stats.txt` (mean 7.7077 / abs 7.9517 / RMSE 10.2748).
- **Calibrate**: PASS — `import_obs_from_csv` (10 head bores, dominant node) →
  `setup_calibration(obs_source="model", npf:k, scope=all)` → `start_calibration`/GLM →
  `summarise_calibration`. φ 1060.1 → 208.0; K 2.4 → 0.427 ft/d; head RMSE **10.27 → 4.56**,
  R² 0.765; calibrated run reproduces the fit exactly, balance closes 0.007 %.
- **Reprompts**: 0. **MCP-only violations**: 0.

## Server defects exposed (fixed after this run)

1. **OC period block dropped on rewrite.** FloPy loads the Adopted GWF OC but leaves
   `saverecord`/`printrecord` empty when the period block is an external `OPEN/CLOSE` file
   (GMS: `BEGIN PERIOD 1 / OPEN/CLOSE GWF_Model_input/GWF_Model.oc_1.txt`). The first
   rewrite dropped the block, writing empty `.hds`/`.cbc`; the agent repaired it with
   `add_oc_package(..., HEAD/BUDGET FIRST)`.
2. **`#` in obs site names corrupts the OBS file.** `import_obs_from_csv` used the raw site
   string as the OBS name; MF6 reads `#` as a comment (`Observation type not found: #`) and
   the base run/Jacobian failed. The agent renamed `POINT_#1…10` → `pt01…10`.

Both were fixed on `main` at `888b870` (`restore_oc_period_records`, `_safe_obs_name`,
unsupported-`obs_type` rejection) with `tests/test_oc_obs_robustness.py`; see
`2026-09-13-6d-gms-mf6-pest-obs-ss-rerun2.md`.

## Documented gaps (not worked around; → v0.2.0 backlog)

- Compound total-RIV **FLOW observation not representable** — no OBS6 continuous type; the
  MCP now fails loudly and directs the caller to `compute_water_balance`. Calibration is
  head-only (observed flow −4644.0, base residual +790.21 = reference).
- GMS multi-node bore interpolation (`model.n2b`, ≤4 nodes) reduced to the dominant single
  cell; shipped PEST weights (`model.bwt`/`model.fwt`) not importable (weight 1.0).
- `run_pestpp_glm` client timeout → `start_calibration` background path; ~85 s/model
  evaluation made a full 10-iteration run impractical (stopped after iteration 1).

## Gate position

**Criteria-green (1 of the 2 consecutive greens).** 0 reprompts / 0 MCP-only violations,
all criteria met, but two reproducible server defects forced MCP-only repairs — not a clean
set-and-forget run. Fixed and re-verified in rerun-2.
