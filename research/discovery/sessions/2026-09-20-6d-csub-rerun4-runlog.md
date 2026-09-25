# Closed-book MCP validation run log — Phase 6d target 9 (H201, MODFLOW 6 CSUB)

Session: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-target9-csub-rerun4` (rerun-4, closed-book)
Site: `H201` of `1DSubsidenceModeling-MF6CSUB` (repo `__main__` example), copied read-only from
`D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB\H201`.
Model: `h201csub`, workspace `.\model_ws`.

## 1. Environment (check_environment)

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| numpy / scipy / pandas | 2.4.4 / 1.17.1 / (pandas present) |
| geopandas / rasterio / matplotlib | 1.1.3 / 1.5.0 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-ies / glm / sen / opt / da | present |
| ready / missing | true / none |

Stack reported ready, no missing packages or binaries.

## 2. Data preparation (allowed: transforms source CSVs; not the model)

Copied `H201\` and the repo `dependencies\` into this session folder. Holdout tree untouched.

`H201\prep_data.py` was executed **in the copy** (run from `H201\` with the session root on
`PYTHONPATH` so the `dependencies` namespace package resolves):

```
PYTHONPATH=<session>\  python  H201\prep_data.py     # __main__: prep_data(True)
```

Outputs (data prep only): `H201\processed_data\H201.model_property_data.csv`,
`H201\processed_data\H201.ts_data.csv`, `processed_gwlevels.pdf`.

Processed property table (authoritative values used to build the model):

| property | layer 0 (Upper) | layer 1 (Middle) |
|---|---|---|
| cdelay | nodelay | delay |
| k / k33 | 10.0 / 0.01 ft/d | 10.0 / 0.01 ft/d |
| ssv_cc | 5e-5 | 5e-4 |
| sse_cr | 2.5e-7 | 2.5e-6 |
| theta | 0.35 | 0.35 |
| kv (ib_kv) | 5e-5 | 5e-5 |
| cg_theta | 0.3 | 0.3 |
| cg_ske_cr | 2.5e-7 | 2.5e-6 |
| sgm | 1.7 | 1.7 |
| thick_frac_0 | 7.4450367 | 22.924098 |
| rnb_0 | 5.9099778 | 24.035842 |
| tot_thick | 131 | 1040 |
| botm | -77.2 | -1117.2 |
| top | 53.8 | 53.8 |

`prep_mcp_inputs.py` (ordinary Python, data prep only) reproduced
`model_functions.initialize_model`'s TDIS + GHB construction from those outputs and wrote
`model_inputs.json` / `ghb_lines.txt` / `tdis_lines.txt`:

* `start_date_time = 1903-12-31` (= min(sub_data date, obs date) − 1 day)
* `nper = 158` = 113 historic periods (1903-12-31 + yearly 1904-12-31 … 2024-12-31) + 45 predictive
  yearly periods to 2060-12-31 (repo default `freq='Y'`, `wl_sample='mean'`)
* `perlen`/`nstp` = 1 day for the first period, then 365/366 d, `nstp = 1` throughout
* GHB: conductance 50 000, head per layer = yearly-mean resampled `interpolated` series;
  2 GHB warning rows (1903-12-31 absent from the yearly index → previous head reused, exactly as
  the repo's `last_dict` fallback). No head-below-bottom warnings.
* `strt = 53.8` = max interpolated groundwater level

## 3. Model build — MCP tool calls only

Exact call sequence (all `groundwater-mcp`):

1. `create_model(name="h201csub", workspace="<session>\model_ws", units="FEET", time_units="DAYS")`
2. `set_simulation(nper=158, perlen=[…158…], nstp=[…1…], start_date_time="1903-12-31",
   newton=true, ims_complexity="simple", outer_maximum=300, linear_acceleration="bicgstab")`
3. `add_dis_package(nlay=2, nrow=1, ncol=1, delr=1, delc=1, top=53.8, botm=[-77.2, -1117.2])`
4. `add_npf_package(icelltype=1, k=[10,10], k33=[0.01,0.01], k_units="ft/d")`
5. `add_ic_package(strt=53.8)`
6. `add_sto_package(iconvert=0, ss=0, sy=0, steady_state=[0])`
7. `add_boundary_package(package="GHB", stress_period_data={158 periods × 2 layers}, save_flows=true)`
8. `add_csub_package(packagedata=[…2 × 11-field…], ndelaycells=19, sgm=1.7, sgs=1.7,
   cg_theta=[0.3,0.3], cg_ske_cr=[2.5e-7,2.5e-6], head_based=false,
   initial_preconsolidation_head=true, specified_initial_interbed_state=true,
   update_material_properties=false, observations={…16 records…},
   filerecords={"zdisplacement": "...", "strainib": "..."})`
9. `add_oc_package(head_filerecord="h201csub.hds", budget_filerecord="h201csub.cbc",
   saverecord=[HEAD ALL, BUDGET ALL], printrecord=[BUDGET ALL])`
10. `check_model` → `check_passed: true` (only 2 `ss < 1e-6` STO warnings, expected from `ss=0`)
11. `start_run` → `get_job_status`

CSUB packagedata written (0-based icsubno/cellid), matching the repo `sub6` loop:

```
[0, [0,0,0], nodelay, 0.0, 7.4450367,  5.9099778,  5e-5, 2.5e-7, 0.35, 5e-5, 0.0]
[1, [1,0,0], delay,   0.0, 22.924098, 24.035842,  5e-4, 2.5e-6, 0.35, 5e-5, 0.0]
```

Verified in `model_ws\h201csub.csub`: `GAMMAW 62.48`, `BETA 2.227e-08`,
`INITIAL_PRECONSOLIDATION_HEAD`, `SPECIFIED_INITIAL_INTERBED_STATE`, `NDELAYCELLS 19`
(no `HEAD_BASED` → head_based false). These are the benchmark values and were taken from the
MCP's FEET-unit defaults (not passed explicitly).

### Deviations from `model_functions.py` (all documented, none functional)

1. **IMS inner controls not exposed.** The repo sets `complexity="simple"` plus
   `inner_maximum=200`, `outer_dvclose=1e-3`, `inner_dvclose=1e-3`, `relaxation_factor=0.97`,
   `linear_acceleration="bicgstab"`, `outer_maximum=300`. `set_simulation` exposes only
   `ims_complexity`, `outer_maximum`, `linear_acceleration` (and `newton`). I used
   `SIMPLE` + `outer_maximum=300` + `bicgstab`; the inner/dvclose/relaxation values come from the
   MCP's SIMPLE preset. The 2-cell model converges regardless.
2. **`sgs` quirk preserved.** `model_functions` passes `sgs=prop_df.loc["sgm"]`, i.e. 1.7, even
   though `prep_data` writes `sgs=2.0`. I used `sgm = sgs = 1.7` to reproduce the benchmark.
3. **OC extras.** The repo also writes `budget.csv` and prints `BUDGET ALL`; the MCP OC writes
   head + budget with `HEAD/BUDGET = ALL`. Immaterial to results.
4. **`clean_model` not needed.** The repo post-edits the CSUB obs OPEN/CLOSE name; the MCP writes
   the CSUB observations natively, so no fix-up was required.
5. **`package_convergence` filerecord not passed** (repo writes `model.conv.log`); `zdisplacement`
   and `strainib` were requested and written.
6. **Output frequency = repo default `freq='Y'`.** The repo's *published* `SimulatedSubsidence_H201.csv`
   is monthly and already calibrated, so it was **not** used as a base-case reference.

## 4. Run convergence evidence

`start_run` → `succeeded`, `convergence: "converged"`, returncode 0, 158/158 stress periods,
"Normal termination of simulation", elapsed ≈ 0.13–0.23 s. Final state re-verified after the
cancelled calibrations: `check_model` still `check_passed: true`, final `start_run` converged.

## 5. Post-processing (MCP)

* `read_compaction` → per-layer compaction and cumulative subsidence over 158 times, plus
  `interbed_strain`:
  * interbed 1 (no-delay, layer 1): final thickness 7.445 ft, total compaction 7.4e-4 ft (0.0099 %)
  * interbed 2 (delay, layer 2): final thickness 551.0 ft, total compaction **8.335 ft** (1.51 %)
* `plot_subsidence(observed_csv=H201\source_data\H201_sub_data.csv)` → PNG
  `subsidence_H201.png` (returned natively), `has_observed: true`.

Base (prior) model vs the site's own `sub_data.csv` (reporting arithmetic on the MCP compaction
output + source CSV):

* base total subsidence at 2024-12-31 = **8.45 ft** vs observed **2.91 ft**
* RMSE over all 208 observation dates = **3.88 ft**; bias = +2.85 ft
* the misfit is dominated by a late inelastic spike: layer-2 compaction jumps 2.56 → 8.50 ft
  around 2016, when the Middle-aquifer GHB head falls to ≈ −43 ft, far below the interbed
  `PCS0 = 0.0`, driving large inelastic compaction. The repo's calibrated benchmark suppresses
  this by lowering the interbed `KV` (calibrated layer-2 KV ≈ 1.18e-7 vs prior 5e-5), i.e. the
  misfit is exactly what the included `kv` parameter is meant to absorb. The base model is a
  plausible uncalibrated prior, not a build error.

## 6. Derived observation + calibration interface (MCP)

`import_subsidence_observations(observed_csv=H201\source_data\H201_sub_data.csv,
name="subsidence", value_col="Subsidence_ft")` → `n_observations = 208`, sim source
`h201csub.csub.obs.csv`, `sum_cols=["compaction"]`, `time_col="time"`.

`setup_calibration(obs_source="derived", noptmax=5, parameterisation=…)` →
`h201csub.pst`, 3 templates, 1 instruction file, forward wrapper
`C:\Users\jakob\AppData\Local\Temp\gwmcp_run_h201csub.py`, **8 adjustable parameters**:

| name | target | initial | bounds | transform |
|---|---|---|---|---|
| sub_ssv_cc_1 / _2 | csub:packagedata ssv_cc, ib 1/2 | 5e-5 / 5e-4 | ×0.05–×20 | log |
| sub_sse_cr_1 / _2 | csub:packagedata sse_cr | 2.5e-7 / 2.5e-6 | ×0.05–×20 | log |
| sub_kv_1 / _2 | csub:packagedata kv | 5e-5 / 5e-5 | ×0.05–×20 | log |
| cg | csub:cg_theta layer 2 | 0.3 | 0.03–3 | log |
| k33 | npf:k33 all | 0.01 | 0.001–0.1 | log |

Derived-target matching: `n_observations = 208`, **`n_matched = 17`** — only observation dates that
coincide with the yearly output times are usable (1904-01-01 and 2005-01-01 … 2024-01-01); the
other 191 monthly/InSAR/GPS dates are skipped. This is a direct consequence of the repo's default
yearly discretisation and is reported honestly rather than worked around.

Verified the generated wrapper is correct: it runs `mf6.exe`, then sums only CSV columns that
`startswith("compaction")` and exclude `elastic` (i.e. `COMPACTION.01/02` only — no double count
of `ELASTIC-/INELASTIC-COMPACTION` or `INTERBED-COMPACTION-PCT`), then writes the 17 matched dates.

## 7. Calibration execution — BLOCKED (environment/process-launch wedge)

Three attempts, all wedged while launching the PEST++ forward-run child:

| # | method | job id | outcome | evidence |
|---|---|---|---|---|
| 1 | IES (50 reals) | `d65d157622a2` | 2 forward runs OK, then wedge | wrapper `python.exe` pid 19204: **0.03 s CPU**, started 21:40:10, **no mf6 child**, never wrote a trace line; pestpp-ies CPU climbing (140 s) while idle |
| 2 | IES (50 reals) | `85b321c5ac6f` | wedge on first child | wrapper pid 44316 stuck (0.02 s CPU, no mf6), trace frozen at 8 lines |
| 3 | GLM | `256f47d7952b` | 2 forward runs OK, then wedge at `mf6_start` | wrapper 0.03 s CPU, **no `mf6.exe` process anywhere**, trace frozen at 11 lines for >45 s; pestpp-glm CPU climbing (114 s) |

Diagnostics confirming it is **not** the model or the interface:

* `mf6.exe` runs standalone repeatedly through the MCP: `start_run` → converged, returncode 0,
  normal termination (0.13–0.23 s) — checked before and after each cancel.
* The first two forward runs of each attempt completed with `mf6_done rc=0`; the wedge is on a
  *subsequent* child, in Windows process creation/`subprocess.run([MF6])`, before mf6 starts.
* `check_model` passes and the model reloads/runs after every cancel (cancel restores the
  externalised inputs).

All three jobs were cancelled with `cancel_job`; no leftover `pestpp-*`, wrapper `python.exe`, or
`mf6.exe` processes remain, and the model workspace was left runnable (final `start_run` green).

**Verdict for criterion 5:** the calibration *chain* is fully exercised and verified —
`import_subsidence_observations` → `setup_calibration(obs_source="derived", csub:packagedata +
csub:cg_theta + npf:k33)` → `start_calibration` — and the parameter estimates/phi could not be
produced because PEST++'s forward-run child processes wedge in process launch on this host. This is
an environment/process-launch blocker, reported per the run protocol rather than worked around with
raw flopy/pyemu.

## 8. MCP-only compliance

* Every model action (create, TDIS/IMS, DIS, NPF, IC, STO, GHB, CSUB, OC, check, run,
  read_compaction, plot_subsidence, import_subsidence_observations, setup_calibration,
  start_calibration/cancel_job, check_model) was a `groundwater-mcp` tool call.
* No flopy/pyemu MODFLOW or PEST class was used directly; no MODFLOW/PEST file was hand-edited by
  editor or shell.
* Ordinary Python was used only for data preparation (`prep_data.py`, `prep_mcp_inputs.py`,
  `emit_lines.py`) and read-only reporting arithmetic (`calc_prior_fit.py`) on the MCP-produced
  compaction CSV plus the source CSVs.
* The repo's `model_functions.py` / `workflow.py` / `ies_functions.py` were read as the model
  specification but never executed.

## 9. Artefacts

* `model_ws\` — `h201csub` MF6 input set + outputs (`h201csub.hds`, `.cbc`, `.csub.obs.csv`,
  `h201csub_compaction.csv`, `.strainib.csv`, `.displacement.hds`), calibration interface
  (`h201csub.pst`, 3 `.tpl`, 1 `.ins`)
* `H201\processed_data\` — prep_data.py outputs
* `subsidence_H201.png` — simulated vs observed subsidence
* `model_inputs.json`, `ghb_lines.txt`, `tdis_lines.txt` — prepared MCP inputs
* `prep_mcp_inputs.py`, `emit_lines.py`, `dump_ib.py`, `calc_prior_fit.py` — helper scripts
* `h201csub.csub_packagedata.dat`, `h201csub.csub_cg_theta.dat`, `h201csub_k33.dat` — externalised
  calibration inputs (restored; model runs)

## 10. Reprompts / permission prompts

None. No clarifying questions were needed; no permission prompts were raised; no MCP-only
violations.
