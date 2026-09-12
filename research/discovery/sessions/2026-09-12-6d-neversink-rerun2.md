# 6d session — neversink_workflow (DOI-USGS watershed model), rerun-2 — zoned/multiplier calibration
# (criteria met; load-bearing tool defect found and fixed)

- **Date**: 2026-09-11 → 2026-09-12
- **Client / model**: Agent Manager worktree session (`6d-neversink-rerun2`) via the
  groundwater-mcp stack (flopy 3.10.0, pyemu 1.4.0, MF6 6.7.0, PEST++ 5.2.16) —
  server run from `main` live worktree (zoned NPF K multiplier capability merged
  2026-09-11, commit `35648da`)
- **Worktree branch**: `6d-neversink-rerun2`
- **Data**: `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\`
  (DOI-USGS/neversink_workflow; `neversink_mf6/` + `processed_data/`) — adopted
  `allow_modify=True` in place (calibration needs writes), so the holdout model
  dir was modified during the run.
- **Prompt**: 6d playbook Target-6 prompt verbatim + a rerun-2 note that the
  rerun-1 calibration gap was closed and `setup_calibration` now supports
  zoned/multiplier NPF K parameterisation (discoverable via the tool
  description). Full prompt transcript in the run-log.

## Outcome vs criteria

- **check_environment**: PASS — stack reported; ready, no missing packages/binaries.
- **Adopt**: PASS — `neversink` adopted from the shipped `neversink_mf6`
  (DIS 4×680×619 @ 50 m, 1,683,680 cells, **300,236 active** — the brief's
  "843k active" does not match the shipped `idomain_*.dat`), `allow_modify=True`.
- **Check**: PASS — `check_model` 0 errors; 105 shipped BC-in-inactive-cell
  warnings documented (benign).
- **Run**: PASS — `start_run` normal termination ~30 s; water balance closes
  (−0.082 m³/d on ~523,363 m³/d; percent discrepancy −1.57e-5 %).
- **Postprocess**: PASS — `read_heads` L0 88.1…631.2 (mean 361.5 m);
  `compute_water_balance` closes; `diagnose_water_balance` balanced;
  `plot_heads_map` PNG. Baseline reproduces the shipped solved listing to
  **max 3.06e-4 m** on 858 head observations and **identically** on the 2 SFR
  flow observations.
- **Calibrate**: **PASS (first time for this target)** — the MCP calibration
  chain completed end-to-end: `setup_calibration(scope="zones")` (9 layer-1
  zones + 1 layer-4 zone, dimensionless multipliers) → `run_pestpp_glm`
  (`num_workers=1`) → `summarise_calibration` (+ `compare_to_observed`).
  φ 542,101 → 266,953 → **245,338** (−54.7 %); PEST RMSE ≈ 27 m vs 337 derived
  field observations (baseline ≈ 40 m), R² 0.920. The shipped K pattern is
  retained (per-zone multipliers).
- **Reprompts**: 0.
- **MCP-only violations**: none identified. All model build/run/postprocess/
  calibrate actions went through MCP tools; the only Python was CSV/raster
  data-prep (`prep_obs.py`, `prep_obs2.py`, `inspect_rasters.py`, `verify_k.py`)
  and reading the shipped reference.

## Deviations from the source model

- Active-cell count differs from the brief (300,236 vs "843k") — reported, not changed.
- `import_obs_from_csv` registered 337 layer-1 field observations (NY-DEC/NWIS
  `gw_elev_m`), replacing the shipped 857-target OBS6 for calibration; the
  shipped reference was preserved by copy.
- Calibration rewired NPF `k` to an external non-zoned file and changed the
  shipped K by per-zone multipliers; layer-4's single zone is a no-op flatten.
- 10-parameter subset (L1 zones + L4) chosen for host tractability.
- `kl1_z2` sits at its ×10 upper bound (not widened).
- `check_parameter_sensitivity` / `run_pestpp_glm` foreground calls exceed the
  ~2-min client timeout and complete server-side.

## MCP findings (→ v0.2.0 backlog)

1. **`setup_calibration` was not re-runnable and silently corrupted NPF K
   (FIXED 2026-09-12).** Repeated mixed-scope calls rewired NPF `k` to the same
   external file; a layer-scope setup wrote its absolute `initial` into it, and
   a later zones setup then saw a single uniform zone. The shipped
   `neversink.npf` reference was overwritten with no pristine copy. The run
   recovered MCP-only via `set_model_crs` + `assign_k_from_raster`, but ~24
   zone-boundary cells differ from pristine.
   - **Fix**: `1bac781` snapshots the pristine NPF `k` once to
     `<gwf>_k_pristine.npy` and restores it before every setup; `733cd74` adds
     `model_store.clear_k_base_snapshot`, called by every tool that writes NPF
     `k` (`assign_k_from_raster`, `assign_k_from_zones`, `add_npf_package`), so
     an external K change is honoured instead of reverted. Regression tests:
     `test_setup_calibration_repeatable_preserves_base_k`,
     `test_setup_calibration_re_snapshots_after_k_change`,
     `test_assign_k_from_raster_clears_setup_k_snapshot`.
2. **Forward-wrapper launch stall.** The generated PEST wrapper intermittently
   never spawned `mf6.exe` (frozen `run.info`), coinciding with a runaway
   process, AV activity, and the host suspending overnight (~10.4 h). Serial
   `num_workers=1` after wake proceeded. The wrapper does not surface a launch
   failure — backlog: fail fast / log.
3. `assign_k_from_raster` and foreground `run_pestpp_glm` exceed the client
   timeout but complete server-side — a background entry point is preferable.
4. Default x10 multiplier bound too tight for the dominant zone (`kl1_z2` at bound).

## Gate position

**Criteria met but NOT counted as a clean green.** All six criteria passed and
the calibration chain completed through the MCP tools for the first time, but
the run hit a load-bearing `setup_calibration` defect (finding 1) and had to
recover via another tool. Per the rerun-improvement loop the defect was fixed
(commit `1bac781`/`733cd74`) and rerun-3 is the set-and-forget confirmation on
the fixed code. The target remains NOT PASSED until two consecutive clean
reruns; rerun-2 is green-with-defect #1.

**Holdout state:** `neversink_mf6/` was modified in place and is not pristine;
it must be re-mirrored from upstream before rerun-3 (rerun-1 precedent: fresh
sparse upstream clone → robocopy /MIR). The MCP server must also be restarted to
load the fix commits before rerun-3.
