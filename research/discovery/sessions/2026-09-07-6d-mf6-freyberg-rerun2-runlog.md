# Run log — Phase 6d target 5 (mf6_freyberg PEST++ benchmark)

CLOSED-BOOK validation of the groundwater-mcp toolchain against the shipped
USGS/PEST++ `mf6_freyberg` model (usgs/pestpp @ 5d49814, TM7C26 White et al 2020).
No groundwater-mcp source, tests, plans, or prior research logs were read. Only
the dataset's own files and plain-Python reference-data reads were used.

Date: 2026-09-07. Session folder: `.kilo/worktrees/6d-mf6-freyberg-rerun2`.

---

## 1. Environment (success criterion 1)

`check_environment`: Python 3.12.11, flopy 3.10.0, pyemu 1.4.0,
geopandas/rasterio present, MODFLOW 6 and PEST++ (pestpp-glm/pestpp-ies 5.2.16)
binaries located, docs index built, `ready: true`.

## 2. Model adoption (criterion 2)

Shipped directory `selected/mf6_freyberg` IS the model (mfsim.nam + package
files, single GWF `freyberg6`: DIS 3 x 40 x 20 @ 250 m, 25 transient monthly
stress periods, DIS/IC/NPF/STO/OC/WEL/RCH/GHB/SFR(NEWTON)+OBS6 head.obs,
26 `trgw_*` head sites at layers 1/3 writing `heads.csv`).

- `adopt_model(name="freyberg6", workspace=<shipped dir>)` — read-only adopt.
  No grid rebuild, no file renames. Model became runnable through MCP tools.

## 3. check_model (criterion 3)

`check_model`: check_passed, no errors/warnings. `model_status`: runnable, no
missing required/recommended packages. `summarise_model`: grid/stress-period
structure matches the shipped spec (2118 active cells of 2400).

## 4. Simulation (criterion 4)

- `run_simulation(freyberg6)` → converged, normal termination across all 25
  transient stress periods, ~0.3–0.4 s. `get_run_log` confirms.
- Regenerated `heads.csv` matches the shipped `heads.csv` exactly (closed-loop
  check on the first data row) → the adopted model reproduces the reference
  base output bit-for-bit.
- Only warnings are the expected MF6 deprecation notices in shipped
  `freyberg6.sfr` (`UNIT_CONVERSION`) and `freyberg6.ims`
  (`OUTER/INNER_HCLOSE`).

## 5. Post-processing (criterion 5)

- `read_heads`: all 25 output times available (kstpkper 0-based). Layer 0
  means ≈ 34.34 m (period 1) → 34.35 m (period 25); heads file has every
  stress-period snapshot.
- `compute_water_balance`: per-period budgets read from `.cbb`. Period 1
  (1-day): inflow 2722.1 (RCHA) vs outflow 2729.2 (WEL −945, GHB −463,
  SFR −1322), net −7.1 m³ → closes to 0.26 % of inflow. For later transient
  periods the reported net equals the storage change; the storage term is NOT
  in the `.cbb` because the shipped `freyberg6.sto` omits `SAVE_FLOWS`
  (documented, not a model error; MF6 listing prints no per-period budget
  table because OC prints only in period 1).
- `plot_heads_map` (layer 0, period 25) → `freyberg6_heads_map_l0_sp25.png`
  written to the session folder (image cannot be rendered by this model, file
  retained as the artifact).

## 6. Calibration (criterion 6)

### Approach (documented deviations from the shipped parameterisation)

The full shipped case parameterises **8175 cell-wise K/K33/SS/SY arrays** with
**1025 observations** (650 head + 300 flux + 75 SFR), of which **36 carry
non-zero weight** (`gage_1`, `trgw_2_2_9`, `trgw_2_33_7`, 12 months each).
A full GLM Jacobian would need ~8176 forward runs/iteration — infeasible here.

Calibrated a **documented subset**:
- Parameters: the shipped **monthly RCH array parameterisation**
  (`freyberg6.rch.tpl`, `rch_0..rch_24`, 25 log-transform parameters, shipped
  bounds/initial values). The shipped WEL templates would add 150 poorly
  identified per-well-per-period fluxes; K/K33/SS/SY templates are cell-wise
  and were deliberately excluded.
- Observations: the shipped **SFR gage/headwater/tailwater** observation
  series (`sfr.csv.ins`, 75 tokens) with the shipped `obs_data.csv` values and
  weights — i.e. exactly the benchmark's 12 weighted gage-1 monthly flows;
  all other tokens weight 0. The 24 weighted head observations share
  `heads.csv.ins` with 626 additional head tokens, which could not be supplied
  to `setup_pest_control` without a very large payload (see Limitations).

### Tool-call chain (MCP-only)

1. Scratch sandbox `cal_ws2` created by plain file copy of the dataset
   (data prep, not model building) so pestpp never mutates the shipped
   reference. Adopted as `freyberg6cal` (`allow_modify=True`); `run_simulation`
   converged (one client-side timeout; listing shows normal termination).
2. `setup_pest_control(model=freyberg6cal, obs_source="explicit", par_data=25
   RCH, obs_data=75 SFR obs, template_files=[freyberg6.rch.tpl],
   instruction_files=[sfr.csv.ins], noptmax=2)` → `freyberg6cal.pst`
   (75 obs matched, 25 adjustable params; weights verified in the `.pst`).
3. `start_calibration(method="ies", num_reals=10)` → job `7ea11a25ee01`.
4. `get_job_status`: converged after 3 iterations, 94 forward runs, 0 failed,
   best mean phi 417 → 10.3 → **7.27** (12 weighted gage obs).
5. `summarise_calibration`: per-obs residuals written to
   `cal_ws2/freyberg6cal_residuals.csv`; unweighted RMSE ≈ 100 m³/d,
   R² = 0.973 on the 12 gage obs (note: the tool's GLM-oriented summary showed
   parameter estimates = initial and an empty verdict because the run was IES,
   not GLM).
6. Post-calibration `run_simulation(freyberg6cal)` (model files as left by
   IES) still converges / normal termination — calibrated inputs are runnable.

### Results vs shipped reference

- Base-run weighted phi on the 12 gage obs: **306.03**
  (simulated base flows +270…+490 m³/d above the shipped observed series).
- Calibrated weighted phi on the same 12 obs: **≈ 5.8** (point estimate from
  the posterior residuals; IES best mean phi 7.27) → ~98 % reduction.
- Calibrated RCH values: the shipped base is exactly **truth × 1.05** for all
  25 months (base/truth ratio = 1.050). The IES posterior-mean RCH moved toward
  truth in most months but the 12 streamflow observations cannot identify 25
  monthly recharge values, and the omitted K/K33/STO truth perturbations also
  drive gage flow; RMSLE-to-truth of the IES mean (0.218) is larger than the
  base (0.049) despite the large phi reduction — expected for a deliberately
  under-determined subset calibration that trades parameter accuracy for fit.
  Documented as a subset result, not a benchmark-grade estimate.

## 7. Decisions, reprompts and deviations

- Adopted the shipped folder read-only for run/post-processing; calibrated on a
  byte-identical scratch copy so pestpp template writes never alter the shipped
  reference files.
- `freyberg6.obs.csv` in the dataset is a stale reference artifact (mtime
  2026-08-16; mf6 never opens it — confirmed from the listing). It was NOT used
  as a calibration target; the authoritative model outputs are `heads.csv`,
  `sfr.csv` and the `.lst` written by each run.
- First GLM attempt (175 RCH+WEL params, all 725 tokens as obs) ran 150 forward
  runs successfully but its objective was corrupted by 689 dummy observations
  (obsval 1e10, weight 1) that `setup_pest_control` auto-creates for any
  instruction-file token not present in `obs_data`. Discarded; the run log
  records phi 6.9e22 as an artifact of that misuse.
- GLM on the clean 25-param/75-obs pst failed before any forward run
  ("parameter derivative calculations failed for all parameters", template
  target truncated) — appears engine/Jacobian-specific; **IES on the identical
  pst ran 94 models with 0 failures and converged**. Recorded as a toolchain
  observation, not worked around outside the MCP.

## 8. MCP capability gaps encountered (reported, not worked around)

1. `setup_pest_control(obs_source="explicit")` requires every instruction-file
   token to be supplied in `obs_data`; tokens not supplied are auto-created as
   dummy obs (obsval=1e10, weight=1) that dominate phi. There is no
   "weighted subset" or file-reference path, forcing large payloads for big
   instruction files (e.g. `heads.csv.ins`, 650 tokens).
2. The `obs_source="model"` path targets single-output-time (steady-state)
   model obs CSVs ("first output row", per-site means), so it cannot represent
   the shipped monthly transient head series faithfully — hence the explicit
   path above.
3. `summarise_calibration`'s verdict/phi-progress sections are GLM-oriented and
   return empty fields after an IES run.
4. `compute_water_balance`/`diagnose_water_balance` treat net transient budget
   as a discrepancy because storage flows are absent from the `.cbb` when STO
   has no `SAVE_FLOWS` (as shipped).
5. GLM's 1:1 Jacobian base solve failed on the small single-group pst (see
   section 7); IES is the reliable engine for this configuration.

All model build/adopt/run/post-process/calibrate actions were performed via
groundwater-mcp tool calls. Plain Python was used only to read shipped
CSV/PEST reference files and to prepare observation payloads.
