# Closed-book validation run-log — Phase 6d target 8

**Target:** `MF6_EnKF_DISU` (github.com/JanGei/MF6_EnKF_DISU), Neckartal (DE) DISU model, cloned 2026-09-13.
**Session:** worktree `6d-enkf-disu-rerun5`. **Date:** 2026-09-16.
**Question:** are the groundwater-mcp tools sufficient, on their own, to adopt, re-express as
sequential DA, assimilate real gauge observations, and post-process a real DISU model?
**MCP-only constraint honoured:** every adopt/build/run/post-process/assimilate action on the MF6
model went through a `groundwater-mcp` tool. Ordinary Python was used only to reshape
`Pegel.csv` + `Pegel_Cell_ID.csv` into the observation table, which was then registered through
`import_obs_from_csv`. No flopy/pyemu MODFLOW/PEST class was called directly; no MODFLOW/PEST file
was hand-edited; the repo's own EnKF scripts (`main.py`, `Transient_Run.py`, `generator.py`) were
read (as model specification) but **not** executed.

---

## 0. Provenance / licence check

- Model files are FloPy **3.3.6**, written **2023-09-06**; runs under **MF6 6.7.0** (per listing).
- **No `LICENSE` file** anywhere in the cloned repo (verified by directory enumeration). Redistribution
  status is therefore **unverified** — flagged as a provenance/compliance risk for any downstream use.
- Runnable model: `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim\` — single GWF model
  `flow` (`mfsim.nam` + `flow.nam`), packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO.
- Grid: DISU **31,831 nodes / NJA 198,261 / 31,522 active**; VERTICES + CELL2D present.
- Units declared: `LENGTH_UNITS meters`, `TIME_UNITS days` → adopted as METERS / DAYS (k in m/d).
- Shipped TDIS: **NPER 6**, one 1.0-day step each (6 × 1-day transient).
- NPF: `icelltype` per cell, heterogeneous `k` (OPEN/CLOSE), `k33` via K33OVERK, `wetdry -1`.
- STO: transient all periods, `ss 1e-4`, `sy 0.01`, `iconvert 1`. `flow.nam` sets `NEWTON`.
- Gauge data: `csv data\Pegel.csv` (wide, 421 rows, 14 gauges, 2003-02-12 → 2019-04-29, `-9999` missing)
  and `csv data\Pegel_Cell_ID.csv` (Name → Cell_ID).
- **Cell_ID convention confirmed from the repo's own code** (`Objectify.py:92,103,191`): the value is used
  directly as a 0-based scalar DISU node index into numpy arrays, so it is a **0-based node id**.

## 1. Step 1 — environment

`check_environment`:

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio / numpy / scipy | 1.1.3 / 1.5.0 / 2.4.4 / 1.17.1 |
| matplotlib | 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / ies / da / sen / opt | present in `C:\Users\jakob\.local\bin\` |
| docs index | built (`C:\Users\jakob\.groundwater-mcp\index`) |
| `ready` | **true**, `missing` = none |

## 2. Model specification read from the target repo (not the MCP source)

- `sim.tdis`: NPER 6, each `perlen 1.0 / nstp 1 / tsmult 1.0`, `TIME_UNITS days`.
- `flow.disu`: 31,831 nodes, NJA 198,261, external arrays under `flow_input/`.
- `flow.npf`: `k` ← `flow_input/flow.npf_K_1.txt` (10,413 unique values, 0.864 → 86,400 m/d, mean 1,011 m/d).
- `flow.ic`: `strt` ← `flow_input/flow.ic_STRT_1.txt`.
- `flow.oc`: `HEAD FILEOUT flow_output/flow.hds`, `BUDGET FILEOUT flow_output/flow.cbc`.
- Boundary packages (`chd`/`rch`/`riv`/`wel`) all carry **only `BEGIN PERIOD 1`** → one forcing period.
- Shipped run (`mfsim.lst`) = normal termination, 6.9 s.
- IC vs gauges (computed from the shipped arrays): the shipped `strt` at the gauge nodes is **~3–6 m
  above** the observed 2017 levels (e.g. Ne-401 338.93 vs 332.95; Ne-503 345.30 vs 337.59) → an
  **uncalibrated baseline**, documented rather than forced.

## 3. Step 2 — adoption (shipped model)

`adopt_model(name="neckartal_da", workspace="…\MODFLOW 6\sim", allow_modify=true, units="METERS", time_units="DAYS")`
→ `adopted: true`, `model_names: ["flow"]`. No grid rebuild, no file renames.

`check_model` → `check_passed: true`, **zero errors and zero warnings** (NPF/CHD/RCH/RIV/WEL/STO checks
all passed). `summarise_model` confirmed DISU / 31,831 nodes / 31,522 active / 6 stress periods / m/d.

## 4. Step 4 — re-expression as single-step DA cycles

The canonical OBS-CSV instruction file reads only the first data row, which is the end-of-cycle value
only when a period has one time step. The shipped NPER=6 was therefore reduced **through the MCP**:

`set_simulation(model, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")` → NPER 1, total 1.0 day.

`sim.tdis` was **not** hand-edited; the tool rewrote the timing discretisation. Six DA cycles are then
re-expressed by the DA cycle tables as six 1-day stress periods with heads carried between cycles.

## 5. Step 5 — observation table (data prep) and registration

Cycles chosen = six 2017 survey dates on which **all 13 reporting gauges** have values (only Ne-507, with
16 lifetime records, is excluded): `2017-01-30, 2017-03-27, 2017-04-06, 2017-06-19, 2017-08-03, 2017-08-29`.

Python prep reshaped the wide table into `…\sim\da_obs_gauges.csv` with columns `site,date,value,Cell_ID`
(`-9999` → missing; values ≤ 5 m rejected), 13 sites × 6 cycles = **78 records**.

`import_obs_from_csv(model, csv_file, cellid_col="Cell_ID", site_col="site", date_col="date", value_col="value", obs_type="HEAD")`
→ `site_count: 13`, `total_records: 78`, and `site_cellid_map` converts each 0-based node to the 1-based
OBS id: 14119→14120, 13835→13836, 15081→15082, 21856→21857, 11201→11202, 13261→13262, 23969→23970,
16316→16317, 11418→11419, 11904→11905, 22575→22576, 22737→22738, 12064→12065 — i.e. **exactly the 14
nodes named in `Pegel_Cell_ID.csv`** (13 used).

Verification run on the re-expressed single-step model: **converged**, 1.32 s,
`observation_fit`: n=13, **RMSE 4.966 m, bias −4.791 m, MAE 4.791 m, R² −1.802** — i.e. the shipped
baseline is uncalibrated and heads sit ~4.8 m high. This is the documented baseline, not a fabricated fit.

## 6. Step 6 — DA setup

### Attempt 1 (model `neckartal_da`, shipped `sim\` workspace)

`setup_da_control(parameterisation={"k_glob": {target:"npf:k", scope:"all", partrans:"log", initial:1.0}},
cycles=[0..5], obs_cycles={13 sites × 6 cycles}, par_cycles={"perlen":{0..5:1.0}},
num_reals=40, noptmax=1, use_simulated_states=true)`.

> **Reprompt / deviation note:** this call returned `MCP error -32001: Request timed out` to the client.
> Completion was verified **read-only** with `list_model_files` — the `.pst`, templates, cycle tables and
> obs/par data were all present. There is no asynchronous/job mode for setup, so a timed-out setup must be
> confirmed by inspecting artefacts.

Generated artefacts: `neckartal_da.pst` (pcf v2, `pestmode estimation`, `noptmax 1`, `svdmode 1`,
`da_num_reals 40`, `da_use_simulated_states True`, obs/par/weight cycle tables, model command
`C:\Users\jakob\.local\bin\mf6.exe`), plus `flow_k.dat.tpl`, `flow_strt.dat.tpl`, `modflowsim.tdis.tpl`,
`flow_head.obs.csv.ins`. The interface was wired correctly: `mfsim.nam` → `modflowsim.tdis`/`modflowsim.ims`,
`flow.npf.k` → `OPEN/CLOSE flow_k.dat`, `flow.ic.strt` → `OPEN/CLOSE flow_strt.dat`.

Parameter set: **1 adjustable K parameter (`k_glob`, log, bounds 0.1–10) + 13 head-state parameters +
1 fixed `perlen`** (14 adjustable, 15 total).

### Attempt 1 result — aborted

`start_calibration(method="da")` → job **`0b3ba25a1547`** (background, polled with `get_job_status`).

| cycle | prior phi (it 0) | post-update phi (it 1) |
|---|---|---|
| 0 | 352.101 | **244.793** |
| 1 | 347.990 | 260.860 |
| 2 | 325.874 | — (aborted) |

`status: succeeded` but `converged: false`, `cycles: 3`, `final_phi_mean 277.176`, `std 35.054`.
Stdout: *“EnsembleMethod error: all remaining realizations failed”*; `mfsim.lst`: *“Solution 1 did not
converge for stress period 1 and time step 1 … Simulation convergence failure.”* `summarise_da` gave
RMSE 3.758 m, bias −3.576 m, R² −0.600.

**Diagnosis (read-only):** `flow_k.dat.tpl` contains **31,831 copies of a single `~ k_glob ~` token** and the
written `flow_k.dat` is **uniform** (0.1408 m/d at the failing run, posterior mean 0.1999, min 0.107). The
`scope="all"` K parameterisation therefore **replaces the entire heterogeneous K field with one uniform
value** rather than scaling the base pattern, and it collapsed to ≈0.1–0.14 m/d — a solver-hostile regime that
broke Newton in the cycle-2 update. (The pristine pattern was preserved in `flow_k_pristine.npy`: 10,413 unique
values, 0.864–86,400 m/d.)

### Attempt 2 (model `neckartal_da2`, pristine workspace) — clean start

The live-model snapshot problem: after attempt 1, a re-`setup_da_control` on the same workspace seeded the
state parameters from the **already-assimilated** IC (e.g. Ne-806 initial 333.56 vs shipped 334.46), so
attempt 2 would not have started from the shipped model. The MCP exposes **no tool to unwind a
parameterisation** back to the pristine input set. Mitigation: the repo contains a byte-identical pristine
copy of the shipped model at `…\MODFLOW 6\ensemble\m0\` (FloPy 3.3.6, NPER 6, `k` ← `flow_input\flow.npf_K_1.txt`,
`strt` ← `flow_input\flow.ic_STRT_1.txt`). It was adopted as **`neckartal_da2`** and used for the clean DA.

Sequence: `adopt_model(neckartal_da2)` → `check_model` (clean) → `set_simulation(1,[1.0],[1])` →
`import_obs_from_csv` (13 sites / 78 records) → `setup_da_control` with **tightened K bounds**
(`lower_factor 0.2`, `upper_factor 5.0`) and **`state_head_bound = 5 m`**, cycles [0..5], per-cycle obs and
perlen, `num_reals 40`, `noptmax 1`, `use_simulated_states true`.

Setup returned in-band: `n_observations 13`, `n_adjustable_parameters 1`, **`n_state_parameters 13`**,
`n_cycles 6`, `state_bounds` = ±5 m for all sites, `model_command` = `mf6.exe`.

## 7. Step 7 — assimilation results (model `neckartal_da2`)

`start_calibration(method="da")` → job **`6fff3ca1f55f`**; `get_job_status` → `succeeded`,
`converged: true`, **6 cycles, 112 model runs, 1,492 s (24.87 min)**.

Per-cycle phi (`neckartal_da2.global.phi.actual.csv`):

| cycle | prior (it 0) | post-update (it 1) | improvement |
|---|---|---|---|
| 0 | 91.487 | **41.105** | −55 % |
| 1 | 63.766 | **28.591** | −55 % |
| 2 | 40.308 | 35.224 | −13 % |
| 3 | 54.614 | 51.360 | −6 % |
| 4 | 68.014 | 65.653 | −3 % |
| 5 | 70.630 | 69.695 | −1 % |

**Final-cycle (5) phi: mean 69.695, std 1.315** (`summarise_da`).
Ensemble spread collapses over cycles (prior std 13.3 → 1.4); the best fitting cycle is cycle 1 (post 28.59),
after which the ensemble drifts upward — a documented ensemble-collapse/drift symptom, not a fabricated fit.

Posterior parameter statistics (`summarise_da`, n≈39 non-failed reals):
`k_glob` **mean 0.2000, std 2.8e-17, min = max = 0.200** → **pinned at the lower bound in 100 % of
realizations** (pestpp stdout: *“k: n at lbnd 40, 100 %”*) — i.e. the uniform K is driven as low as allowed,
consistent with the shipped heads being systematically too high. Head-state posteriors (m): Ne-401 334.64,
Ne-402 332.65, Ne-403 332.13, Ne-503 340.04, Ne-504 339.53, Ne-505 331.99, Ne-506 333.22, Ne-604 327.25,
Ne-801 332.22, Ne-802 329.51, Ne-803 330.32, Ne-805 332.41, Ne-806 331.25 (29 of 520 state values at their
lower bound).

Residuals at the final cycle (`summarise_da`): **RMSE 2.363 m, bias −2.223 m, R² 0.370**, n=13
(residual = observed − modelled, so ~2.2 m of remaining high bias).

## 8. Step 8 — post-processing

- `plot_heads_map(model=neckartal_da2)` → `gwmcp_s4f64f73.png`. The tool **does render the vertex-carrying
  DISU footprint** (the modelled valley outlines correctly), but the colour scale is dominated by MF6's
  inactive/dry sentinel so the map is **not quantitatively readable**. Caveat recorded.
- `compare_to_observed(model=neckartal_da2)` (final-cycle output vs per-site mean observed):
  **RMSE 2.321 m, bias −2.166 m, MAE 2.166 m, R² 0.388**, n=13. Worst sites: Ne-504 (−3.896),
  Ne-506 (−3.074), Ne-801 (−2.919); best Ne-604 (−0.859). Artefacts: `neckartal_da2_obs_residuals.csv`,
  `neckartal_da2_obs_fit.png`.
- `read_simulated_observations(model=neckartal_da2)` → 13 simulated heads, e.g. Ne-401 334.777, Ne-503 340.180,
  Ne-604 327.534.

**Fit improvement vs baseline (same 13 gauges):**

| metric | shipped IC single step | post-DA final cycle | Δ |
|---|---|---|---|
| RMSE (m) | 4.966 | **2.363** | −52 % |
| bias (m) | −4.791 | −2.223 | ~halved |
| R² | −1.802 | **0.370** | +2.17 |

## 9. Deviations from the source model (explicit)

1. **6-period → single-step DA cycles.** Shipped `NPER 6 × 1 day` was reduced via `set_simulation` to
   `NPER 1, NSTP 1, perlen 1.0 day`, and re-expressed as six 1-day DA cycles driven by the parameter cycle
   table (`perlen = 1.0` each). Total simulated time (6 days) matches the source model.
2. **Observation time collapsed.** The six 2017 survey dates span 2017-01-30 → 2017-08-29 (real gaps up to
   118 days) but are mapped onto six consecutive 1-day cycles. Real inter-survey travel time is not
   represented.
3. **Forcing is static.** The shipped boundary packages carry a single period, so all six cycles share the
   same RCH/RIV/WEL/CHD. The repo's own EnKF changed recharge and pumping daily from
   `RCHunterjesingen.csv` / `2017.csv`; that dynamic forcing was **not** reproduced (no MCP DA channel for it).
4. **Method change: PEST++-DA replaces the bespoke EnKF.** The repo's `main.py`/`Transient_Run.py` implement a
   custom damped stochastic Kalman EnKF (15–30 members) over pilot-point-kriged log-K; those scripts were
   **not run**. Instead, sequential assimilation was performed with **pestpp-da v5.2.16**
   (`noptmax 1`, `da_use_simulated_states True`) as instructed.
5. **K parameterisation is uniform, not spatial.** MCP `scope="all"` on `npf:k` tokenises all 31,831 cells with
   a single parameter, so the 10,413-value heterogeneous K field is replaced by one uniform value. The source
   model (and its EnKF) is spatially distributed; this is a material simplification inherent to the tool's
   "all" scope.
6. **Two model registrations.** `neckartal_da` (shipped `sim\`, attempt 1, aborted) and `neckartal_da2`
   (pristine `ensemble\m0\`, attempt 2, completed). Attempt 2's workspace is a byte-identical copy of the
   shipped inputs, not the primary `sim\` directory.
7. **State bounds** set to ±5 m (`state_head_bound`); the tool's derived defaults were ±~5–9.5 m per site.
8. Observation weight = 1.0 for all sites (σ ≡ 1 m), so phi is a plain sum of squared head residuals in m²;
   the absolute phi scale is arbitrary and the baseline is uncalibrated.

## 10. MCP capability observations (gaps found, none bypassed)

- **`setup_da_control` has no async mode** and exceeded the client timeout on attempt 1; the call is
  successful server-side but reports a client error. Setup completion must be confirmed by inspecting files.
- **No tool to unwind/reset a parameterisation.** After attempt 1 the live model's snapshot became the new
  "pristine" base, so a same-workspace re-setup inherits the assimilated state. Worked around by adopting the
  repo's pristine sibling copy (not by hand-editing files).
- **`scope="all"` K is a uniform replacement, not a multiplier** on the existing field — worth knowing before
  using it on a heterogeneous model.
- **`plot_heads_map` colour scale** is unusable on this DISU grid because inactive sentinel values dominate it.
- All other steps (adopt, check, set_simulation, import_obs_from_csv, run_simulation, setup_da_control,
  start_calibration/get_job_status, summarise_da, compare_to_observed, read_simulated_observations) worked
  end-to-end through the MCP alone.

## 11. Reprompts / recovery actions

No user reprompts (single closed-book prompt). Internal recovery actions:
1. `setup_da_control` client timeout → verified server-side artefacts with `list_model_files` (no re-issue).
2. DA abort at cycle 2 → read `mfsim.lst` + templates, diagnosed uniform-K collapse, re-ran with tightened K
   bounds.
3. Contaminated live snapshot → discovered `ensemble\m0\`, confirmed byte-identical to the shipped inputs,
   adopted it as `neckartal_da2` for a clean start.
4. `numpy.loadtxt` failed on the free-form external array files → switched to whitespace tokenisation
   (read-only data inspection).

## 12. Conclusion

The groundwater-mcp toolchain **is sufficient** to adopt this real DISU model, re-express a 6×1-day transient
as single-step sequential DA cycles, register 13 real gauges by scalar DISU node id, build and run a
pestpp-da assimilation, and post-process it — with the model never touched outside MCP tool calls. The
assimilation completed all six cycles and reduced gauge RMSE from **4.97 m to 2.36 m** (R² −1.80 → +0.37)
on an uncalibrated baseline. The result is deliberately qualified: the shipped heads are ~4–5 m high to begin
with, the K lever is a single uniform value pinned at its lower bound, the ensemble collapses after cycle 1, and
the later cycles drift upward — reported as measured rather than dressed up as a calibrated fit.
