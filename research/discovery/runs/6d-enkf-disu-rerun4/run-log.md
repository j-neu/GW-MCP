# Phase 6d target 8 — closed-book MCP validation on a real DISU model

**Target:** `MF6_EnKF_DISU` (github.com/JanGei/MF6_EnKF_DISU), Neckartal DE
**Data:** `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\`
**Runnable model:** `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim\`
**Session:** 2026-09-16, worktree `6d-enkf-disu-rerun4`
**Constraint honoured:** every adopt / build / run / post-process / assimilate action on the MF6
model went through a `groundwater-mcp` tool call. Ordinary Python was used only to reshape
`Pegel.csv` + `Pegel_Cell_ID.csv` into the observation table fed to `import_obs_from_csv`.
No flopy/pyemu/raw-MF6 call and no hand-edited MODFLOW or PEST file. The repo's own EnKF
scripts (`main.py`, `Transient_Run.py`, `generator.py`) were **read** as model specification
but never executed.

**Licence check (requested):** no `LICENSE`/`COPYING`/`NOTICE` file exists anywhere in the
repository (recursive search returned nothing), so reuse terms are unspecified.

---

## 1. Stack (`check_environment`)

| item | value |
|---|---|
| Python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio | 1.1.3 / 1.5.0 |
| numpy / scipy / matplotlib | 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp | glm, ies, sen, opt, **da** all present |
| docs index | built (`C:\Users\jakob\.groundwater-mcp\index`) |
| workspace root | `C:\Users\jakob\.groundwater-mcp\workspaces` |
| `ready` | **true**, missing packages/binaries: none |

## 2. Shipped model as found

* `mfsim.nam` → one GWF model `flow` (`flow.nam`), `sim.tdis`, `sim.ims`.
* DISU: **31,831 nodes**, NJA **198,261**, **31,522 active**, NVERT 11,430, vertices + CELL2D
  present; `LENGTH_UNITS meters`.
* Packages: DISU / NPF / IC / CHD / OC / RCH / RIV / WEL / STO; all arrays external in `flow_input\`.
* `sim.tdis`: `TIME_UNITS days`, **NPER 6 × 1.0-day step**.
* Forcing is **period-1 only** (CHD 6 records @ 305.16 m; RCH 10,182 / RIV 686 / WEL 610
  records) — MF6 reuses period 1 for all periods, so the shipped forcing is **constant in time**.
* STO: `iconvert 1`, `ss 1e-4`, `sy 0.01`, all 6 periods TRANSIENT.
* Shipped listing: normal termination, 6.9 s elapsed; `mfsim.lst` shows the full 6-step run.

## 3. Tool-call sequence

| # | tool | purpose / outcome |
|---|---|---|
| 1 | `check_environment` | stack verified, `ready=true` |
| 2 | `adopt_model(name="neckartal_da", workspace=…\sim, allow_modify=true, METERS, DAYS)` | adopted in place; `model_names=["flow"]` |
| 3 | `check_model` | **clean** — 0 errors, 0 warnings |
| 4 | `model_status` / `summarise_model` | runnable; grid + 6×1-day periods + boundary types confirmed |
| 5 | `run_simulation` (auto_fix=true) | as-shipped **converged, 5.19 s**, 6 steps |
| 6 | `read_heads` ×2 | `kstpkper` is **(step, period)**; mean head 327.07 → 325.56 m over 6 days |
| 7 | `validate_model` | **clean**, no findings |
| 8 | `set_simulation(1,[62],[1])` + `run_simulation` | worst-case 62-day cycle **converges** (1.49 s); mean 324.18 m; no drying |
| 9 | `diagnose_water_balance` | balanced, discrepancy 0.007 %, `dominant_term=RIV` (63 %) |
| 10 | `import_obs_from_csv(cellid_col="Cell_ID")` | first pass with **all 14 gauges** → mapping verified |
| 11 | `set_simulation(27, perlen=gaps, nstp=[1]*27, complex)` + `run_simulation` | **open-loop baseline** over the identical cycle sequence, converged 17.4 s |
| 12 | `compare_to_observed` / `read_simulated_observations` | baseline per-site table (below) |
| 13 | `describe_model` | provenance: `OBS_0` from the prep CSV, 14 sites, no unverified defaults |
| 14 | `set_simulation(1,[29],[1], complex)` | DA base discretisation (NPER 1 / NSTP 1) |
| 15 | `import_obs_from_csv` (13 gauges) | re-registered for the DA (see reprompt R1) |
| 16 | `setup_da_control(...)` | **accepted**: 1 adjustable + 13 state params, 13 obs, 27 cycles |
| 17 | `start_calibration(method="da")` | job `bd078b8de763`, returns immediately |
| 18 | `get_job_status` ×6 | live per-cycle phi (1047 → 159 → … → 244) |
| 19 | `summarise_da` | per-cycle phi, posterior params, residuals |
| 20 | `compare_to_observed` / `read_simulated_observations` | final-cycle gauge fit (time = 28 d) |
| 21 | `plot_heads_map` | vertex-carrying DISU plot rendered |
| 22 | `setup_da_control` (control) + `start_calibration(method="da")` | job `8a90d1b63746`, 6 cycles |
| 23 | `get_job_status` / `summarise_da` | control results (see finding F2) |

### Reprompts / tool friction

* **R1 — `setup_da_control` rejected my observation set.**
  `INVALID_INPUT: obs_cycles is missing registered site(s) ['Ne-507']; every registered site
  needs a per-cycle observed-value mapping.`  Ne-507's record starts **2019-01-15**, after the
  model period, so it can never be in `obs_cycles`. I re-ran `import_obs_from_csv` with the 13
  in-window gauges; `setup_da_control` then succeeded. Ne-507's node mapping was already
  verified in the 14-gauge pass (`Ne-507 → 10693` = Cell_ID 10692 + 1), so criterion 5 is met
  even though Ne-507 is not assimilated.
* **R2 — `run_simulation` returned `MCP error -32001: Request timed out`** on the 1-period base
  case, although the run itself finished (listing shows normal termination, 1.644 s, and the
  obs CSV was refreshed to a single row). A client-side reporting timeout, not a run failure;
  re-checked with `get_run_log`. For the long jobs I used `start_calibration` + polling as the
  brief required.
* **F2 — `summarise_da` is not run-isolated in a reused workspace** (found at step 23). After a
  second DA run with **fewer** cycles in the same directory, `summarise_da` still returned the
  **first** run's parameter ensemble and residuals (it reported `k = 10.0`, which is outside the
  control run's 0.5–2.0 bounds, and residuals measured against the 2018-12-20 gauges although
  the control ends at 2017-08-03). The per-cycle phi list *was* correct. Verified against
  on-disk cycle files: the control's true posterior is `k = 2.0` with the states listed in §7.
  Mitigation: one workspace per DA run (e.g. `clone_model`), or verify the reported final cycle
  against `neckartal_da.global.<cycle>.pe.csv`. Run-1's summary was checked and is consistent
  with its `neckartal_da.26.1.par.csv`.

## 4. Decisions

* **Cycle definition (cycle-table-driven).** Cycles = every `Pegel.csv` date inside the model
  period at which **≥ 8 gauges** report a valid value — the same `>7` test the repo's own EnKF
  used. Window **2017-01-30 → 2018-12-20**; 2017-01-30 is the assimilation start date hard-coded
  in the repo's `main.py`. **27 cycles**; `perlen(k) = date(k) − date(k−1)` with
  `date(−1) = 2017-01-01` (the date `Transient_Run.py` starts its 365-day spin-up from the
  shipped IC). Total window 718 days, perlen 7–62 d. This keeps every assimilation cycle
  informative, which is what the per-cycle phi evidence needs.
* **Observation registration.** One record per site at the final cycle date (2018-12-20), so
  `compare_to_observed`'s "mean of registered records" is exactly the final-cycle gauge value.
  The per-cycle values for the DA come from the same prep table via `obs_cycles`.
* **Observed vs simulated datum.** Gauge values are m a.s.l. and simulated heads are metres, so
  they compare directly — no datum offset applied.
* **Parameterisation.** `npf:k`, scope `all`, log-transformed, initial 1.0 (a dimensionless
  multiplier over the shipped K field), bounds 0.1–10 in run 1.
* `use_simulated_states=True` (required by pestpp-da v5.2.16), `noptmax=1` (v5.2.16: 0 = no
  update), `num_reals=20` (the repo used 15).

## 5. Deviations from the source model (and why)

1. **6 × 1-day periods → 27 single-step cycles.** Sequential PEST++-DA needs NPER=1 / NSTP=1 per
   cycle (the canonical OBS-CSV instruction file reads the first data row, which is the
   end-of-cycle value only with one time step). Applied with
   `set_simulation(model, 1, [perlen], [1])`; **no TDIS file was hand-edited**. Heads carry
   between cycles by the tool's state-parameter mechanism — which is the EnKF's own design
   (the repo re-set `ic.strt` from the previous step's heads and re-ran one step per step).
2. **Bespoke EnKF → PEST++-DA.** The repo implements its own EnKF with explicit dampening
   (`damp_K = 0.05`, `damp_h = 0.35`) and a measurement-error variance `eps = 0.01 m²`. The
   MCP path exposes no damping/inflation knob (`noptmax`, `num_reals`, `obs_weights`,
   `prior_std`, parameter bounds are the available levers). This is the direct cause of the
   ensemble collapse in §6/§7.
3. **Constant forcing retained.** The repo drove time-varying recharge (`RCHunterjesingen.csv`)
   and pumping (`2017.csv`) through `set_transient_forcing`. The shipped `sim\` model has
   period-1-only RCH/WEL, and the brief scoped the work to re-expressing the shipped run, so I
   kept the shipped forcing. Consequence: no seasonal signal, so the model cannot track the
   gauges' seasonal cycle in 2017–2018 — a structural limitation of this re-expression, not of
   the DA machinery.
4. **IMS complexity pinned to `complex`** to match the shipped `sim.ims` (the tool default is
   `moderate`).
5. **OBS package added** (`flow.obs` + `flow_head.obs.csv`) and the `sim\` directory mutated:
   `sim.tdis` / `sim.ims` rewritten, PEST interface files added, `flow_output\` overwritten.
   No grid rebuild, no file renames, `disu`/`npf`/`ic` array files untouched.
6. **IC = the shipped `flow.ic_STRT_1.txt`** (the initial state of `Transient_Run.py`, i.e.
   2017-01-01). The repo's EnKF instead overwrote IC with `Final_h_field.mat`.
7. **Ne-507 not assimilated** (record begins 2019-01-15, outside the model period).

## 6. Convergence and phi evidence

| run | setup | result |
|---|---|---|
| shipped model | 6 × 1 d | converged, 5.19 s |
| 62-day single step | NPER 1 / NSTP 1 | converged, 1.49 s, no dry cells |
| open-loop baseline | 27 cycles, no assimilation | converged, 17.4 s |

**Open-loop (no assimilation) baseline**, compared at day 718 (= 2018-12-20 obs) —
`compare_to_observed`, 14 registered gauges: **RMSE 1.393 m, MAE 0.892 m, bias −0.081 m,
R² 0.862**. Largest residuals: Ne-507 +4.62 (the out-of-period gauge), Ne-503 +1.07,
Ne-604 −1.05. Restricted to the **13 assimilated gauges** the tool's own residual table gives
RMSE ≈ **0.673 m**, bias ≈ **−0.442 m** (derived from the returned residuals). The shipped model
is a calibration model, so the prior is already close and the phi scale is *not* arbitrary.

**Run 1 (defaults, 27 cycles, 20 reals, `noptmax=1`, weight 1.0, K bounds 0.1–10)**
— `converged: true`, 56.27 min, 72 model runs per cycle group as reported by pestpp-da.

* cycle 0: **prior phi 1047.48 (sd 643.94) → posterior phi 212.77 (sd 0.357)**, a **−79.7 %**
  reduction (RMSE 9.0 m → 4.0 m).
* per-cycle phi (post-update):
  `212.77, 158.99, 184.95, 268.54, 118.09, 226.14, 204.36, 222.93, 241.62, 250.95, 198.45,
  226.37, 50.08, 93.27, 104.43, 166.56, 186.33, 187.58, 201.41, 180.19, 236.81, 256.84,
  260.12, 261.97, 232.25, 236.40, 243.78` (best cycle 12 at 50.08).
* **final-cycle phi mean 243.778, sd 4.77e-8** — a degenerate posterior.
* **Collapse mechanism (from the par-ensemble files):** the K multiplier's 20-realisations prior
  was 0.171–1.380+ (log-uniform over 0.1–10). After the **first** update **every** realisation sat
  at the **upper bound 10.0** (`k mean = 10, std = 0`), so all realisations became the same model:
  state spread went 643.94 → 0.357 → 0.003 → ~1e-7, the Kalman gain went to zero and cycles 2–26
  were inert. The `head_state` group finished with `n at ubnd 40` (15.4 %).
* final-cycle fit (`compare_to_observed`, 13 gauges): **RMSE 4.330 m, bias −4.190 m,
  R² −1.028** — i.e. **worse than the 0.673 m open-loop baseline**. The cycle-0 update (a global
  K pushed to its bound) changed the model's dynamics, and with zero spread the DA could not
  recover.

## 7. Control experiment (isolating the mechanism)

6 cycles (0–5), 20 reals, same parameterisation but **K bounds 0.5–2.0** and a finite head
measurement error **weight 0.5 (σ = 2 m)** — a more realistic weight than 1 m for head data.
`converged: true`, 14.87 min.

* cycle 0: prior phi **250.82 (sd 56.79)** → post **146.44 (sd 0.556)**.
* cycle 1: prior/post **36.40 (sd 0.0105)** — the best cycle (RMSE ≈ 3.35 m).
* per-cycle phi: `146.44, 36.40, 169.75, 110.17, 35.68, 148.70`; final-cycle phi mean 148.70.
* **K again pinned to its (new) upper bound:** prior 0.588–1.968 → posterior **all 20 = 2.0**,
  then frozen for every remaining cycle. State values of two realisations even hit the ±10 m
  `head_state` bounds at cycle 0.
* The control's true posterior (read from `neckartal_da.5.1.par.csv`, because `summarise_da`
  returned run-1 leftovers — finding F2): `k = 2.0` (std 0), states
  Ne-401 339.520, Ne-402 335.440, Ne-403 333.360, Ne-503 351.578, Ne-504 351.581,
  Ne-505 334.802, Ne-506 334.707, Ne-604 326.840, Ne-801 334.657, Ne-802 330.225,
  Ne-803 330.152, Ne-805 334.185, Ne-806 334.213 (m).
* Interpretation: a tighter K bound and a more realistic observation weight **halve the cycle-0
  misfit and reach a 3.3 m fit**, but they do **not** prevent the runaway of the single global K
  parameter to its bound, and therefore do not prevent collapse. The undamped, un-inflated
  ensemble update with one strongly-correlated global-K parameter is the root cause; the repo's
  own EnKF suppressed exactly this with `damp_K = 0.05`.

## 8. Post-processing (step 8)

* `plot_heads_map(layer=0, kstpkper=(0,0))` → `gwmcp_qgt6lwbh.png`. The vertex-carrying DISU
  grid renders correctly: the Neckartal valley outline with heads **291.77 – 342.54 m**,
  high in the SW, low in the NE. Also `flow.hds` is a single time step (the final DA cycle).
* `compare_to_observed` / `read_simulated_observations` on the final cycle (obs CSV `time = 28` d):
  per-site residuals listed in §6; every residual is negative (model too high) and spatially
  coherent, which also confirms the gauge→node mapping is physically sensible.
* Gauge→node mapping verification (criterion 5): `import_obs_from_csv` returned
  `site_cellid_map` = **Cell_ID + 1** for all 14 gauges
  (14119→14120 … 12064→12065, Ne-507 10692→10693), and the four independent check runs
  (shipped, 62-day, baseline, DA) all produced heads with the correct spatial pattern and within
  ~5 m of the gauges at the right locations.

## 9. Answer to "is the MCP toolchain sufficient?"

**Yes for the mechanics — nothing required a raw flopy/pyemu/MF6 call.**
`adopt_model` adopted the real 31,831-node DISU model unmodified; `check_model`/`validate_model`
were clean; `set_simulation` re-expressed the 6-period TDIS as single-step DA cycles without
touching the files; `import_obs_from_csv` mapped the 14 gauges by scalar DISU node id onto the
1-based OBS ids; `setup_da_control` generated the whole PEST++-DA interface (K template + IC
state template + instruction file + obs/par/weight cycle tables + `.pst`) in one call;
`start_calibration`/`get_job_status` ran the 56-minute assimilation as a background job; and
`summarise_da` / `compare_to_observed` / `read_simulated_observations` / `plot_heads_map`
delivered the post-processing.

**Gaps found (both reported, neither worked around):**

1. `setup_da_control` requires `obs_cycles` to cover *every* registered site, so a gauge with no
   data inside the simulation window cannot simply be left out of the DA — it must be
   un-registered. Ne-507 (record starts 2019-01-15) had to be dropped from registration.
2. `summarise_da` is not run-isolated: in a reused workspace it reports the previous run's
   posterior and residuals if that run had more cycles. The per-cycle phi list is reliable; the
   parameter/residual blocks must be cross-checked against `neckartal_da.global.<cycle>.pe.csv`.

**Modelling outcome (reported as found, not dressed up):** the sequential DA runs end-to-end and
delivers a real, large first-cycle misfit reduction (phi 1047 → 213, i.e. −80 %; control
251 → 146 → 36), but on this model the 20-member ensemble **collapses at the first update**
because the single global K multiplier is driven to its bound, after which the assimilation is
inert and, under the shipped constant forcing, the state drifts away from the seasonally varying
gauges. The final-cycle fit (RMSE 4.33 m) is therefore **worse** than the no-assimilation
open-loop baseline (RMSE 0.67 m for the same 13 gauges). This is a configuration/identifiability
finding, not an MCP capability failure — but the MCP does not currently expose the damping or
covariance inflation that would have prevented it.

**Recommended next steps:** run DA in a cloned workspace per protocol (avoiding finding F2);
parameterise K by zone/prior rather than as one global multiplier (the `zones` scope path in
`setup_calibration`/`setup_da_control` exists); or use PESTPP-IES/GLM for the parameter
estimation and reserve PESTPP-DA for state estimation with a tighter, damped update; and, for a
fully faithful DA, restore the repo's time-varying RCH/WEL forcing so the model can track the
seasonal signal.

## 10. Artefacts

* Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun4\session6d-t8\`
  * `prep_gauge_analysis.py`, `prep_build_obs.py` — data prep (ordinary Python)
  * `obs_register.csv` (14 gauges, mapping verification), `obs_register_da13.csv` (13 gauges, DA)
  * `obs_long_all_dates.csv`, `da_cycles.json` — the cycle design and per-cycle gauge values
  * `run1_default\` — run-1 `.pst`, obs/par/weight cycle tables, per-cycle par ensembles,
    `global.phi.actual.csv`, residuals CSV, obs fit plot, heads map, templates
  * `run2_control\` — the same for the 6-cycle control
* Model workspace (`…\MODFLOW 6\sim\`): `neckartal_da.pst`, `flow_k.dat.tpl`,
  `flow_strt.dat.tpl`, `neckartal_da_*.csv` cycle/ensemble tables, `flow.obs`,
  `flow_head.obs.csv`, `gwmcp_qgt6lwbh.png`, `neckartal_da_obs_fit.png`.
