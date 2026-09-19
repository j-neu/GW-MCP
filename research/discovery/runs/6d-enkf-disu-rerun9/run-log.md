# Phase 6d target 8 — MF6_EnKF_DISU (Neckartal, DE), sequential PEST++-DA

**Model:** `neckartal_r9` — adopted, unmodified shipped MF6 DISU model `flow`
**Workspace:** `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim`
**Data:** github.com/JanGei/MF6_EnKF_DISU (cloned 2026-09-13)
**Constraint honoured:** all adopt/build/run/post-process/assimilate actions went through
groundwater-mcp tools. Ordinary Python was used only to reshape `Pegel.csv` +
`Pegel_Cell_ID.csv` into the observation CSV. The repo's bespoke EnKF
(`main.py` / `Transient_Run.py` / `generator.py`) was **not** executed. No flopy/pyemu
MODFLOW or PEST class was called directly; no MODFLOW/PEST file was hand-edited.

---

## 1. Licence check

`Get-ChildItem -Recurse -Include LICENSE*,COPYING*,*.md` over the repo root returns
**nothing**. There is no LICENSE, COPYING or README file in the cloned repository —
redistribution terms are therefore unstated. Flagged as an unresolved legal/IP finding.

## 2. Environment (`check_environment`)

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio / numpy / scipy / matplotlib | 1.1.3 / 1.5.0 / 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / ies / da / sen / opt | all present in `C:\Users\jakob\.local\bin\` |
| ready | true, nothing missing |

`mf6` reports VERSION 6.7.0 (02/05/2026); the shipped `.lst` was written by 6.4.2-class
output — no compatibility issue observed.

## 3. Adoption (`adopt_model`)

* name `neckartal_r9` (fresh; the registry held stale `neckartal*` entries), workspace = the
  shipped `sim` directory, `allow_modify=true`, units `METERS`, time units `DAYS`
  (matching `flow.disu LENGTH_UNITS meters` and `sim.tdis TIME_UNITS days`).
* Result: `adopted=true`, `model_names=["flow"]`, model name length 12 ≤ 16.
* **No** grid rebuild, **no** file renames.

Source model as shipped:

| property | value |
|---|---|
| grid | DISU, 31,831 nodes, NJA 198,261, 31,522 active (309 idomain 0) |
| packages | DISU, NPF, IC, CHD, OC, RCH, RIV, WEL, STO |
| IC strt | 305.16 … 345.5 m (1e30 sentinel on inactive nodes) |
| NPF K | 0.864 – 86,400 m/d, **10,413 unique** values |
| CHD | 6 nodes @ 305.16 m ("Baggersee Kfurt") |
| RIV / RCH / WEL | 686 reaches / 10,182 cells / 610 entries, single period |
| TDIS (shipped) | NPER 6 × 1.0 d, 1 step each, TIME_UNITS days |
| shipped run | normal termination, 6.902 s |

## 4. `check_model`

`check_passed=true`, **zero errors, zero warnings** (all NPF/CHD/RCH/RIV/WEL/STO checks
passed, incl. BC-in-inactive-cell and K-range checks). `model_status` → `runnable=true`.

## 5. Re-expression as sequential DA (`set_simulation`)

The shipped TDIS is NPER 6 (six 1-day periods). Sequential PEST++-DA needs exactly one
MF6 stress period with one time step per cycle, because the generated OBS-CSV instruction
file reads the first data row, which is the end-of-cycle value only with a single step.

```
set_simulation(neckartal_r9, nper=1, perlen=[1.0], nstp=[1], ims_complexity="complex")
```

→ `{"nper":1,"time_units":"DAYS","ims_complexity":"COMPLEX","total_time":1}`.
`ims_complexity="complex"` was passed deliberately to preserve the shipped `sim.ims`
(`COMPLEXITY complex`, `NO_PTC all`). The tdis file was **not** hand-edited.

The DA cycles are then supplied by the cycle table: **30 cycles of 1 day**, 2017-01-30 →
2017-02-28, reproducing the source repo's EnKF loop (`date = 2017-01-30`, `for i in
range(30)`, `date += timedelta(days=1)` in `main.py`). Heads and states carry between
cycles (`use_simulated_states=True`).

Verified after the reduction: `run_simulation` → converged, 1.44 s.

## 6. Gauge registration (`import_obs_from_csv`)

Data prep (ordinary Python, `prep_obs.py`): wide `Pegel.csv` melted to
`site,date,value,Cell_ID`; `-9999` treated as missing; only the six dates inside the
2017-01-30…2017-02-28 window retained.

```
import_obs_from_csv(model="neckartal_r9", csv_file=.../obs_gauges.csv,
                    cellid_col="Cell_ID", site_col="site",
                    date_col="date", value_col="value", obs_type="HEAD")
```

* 13 sites, 36 records. Scalar DISU node ids were converted 0-based → 1-based by the tool
  (`Ne-401`: 14119 → 14120, … `Ne-806`: 12064 → 12065) — exactly +1, no re-offsetting.
* **Ne-507 is not registered.** `Pegel.csv` contains only 16 Ne-507 records in the whole
  2003–2019 file, all in **2019**; it has no observation anywhere near the assimilation
  window. Registering it would have required fabricating a 2017 value. Its node
  mapping (0-based **10692**, idomain 1) is recorded here for completeness.
* Mapping verification: all 14 `Pegel_Cell_ID.csv` nodes are `idomain=1`; initial heads at
  them are 329.4–345.5 m vs gauge levels ≈326.7–337.6 m (same datum, plausible);
  and — strongest evidence — the generated IC template
  `flow_strt.dat.tpl` places its 13 state tokens on lines
  `11203, 11420, 11906, 12066, 13263, 13837, 14121, 15083, 16318, 21858, 22577, 22739,
  23971` = exactly the 0-based gauge nodes + 1.
* Available gauges per cycle: c0 (2017-01-30) 13, c7 9, c14 3, c17 6, c21 2, c28 3.

Sanity run after registration: converged, `observation_fit` n=13, **RMSE 4.954 m,
bias −4.770 m, R² −1.844**. The negative R² and ~4.8 m bias show the shipped model was
never calibrated against these 2017 gauges — the phi scale is arbitrary (documented, not
fitted away).

## 7. DA setup (`setup_da_control`)

```
setup_da_control(model="neckartal_r9",
                 parameterisation={"k": {"target":"npf:k","scope":"all","initial":10.18}},
                 cycles=[0..29],
                 obs_cycles={13 sites → {cycle: gauge value}},   # from step 6
                 par_cycles={"perlen": {0..29: 1.0}},            # cycle-driven TDIS
                 num_reals=20, noptmax=1, use_simulated_states=True)
```

**Reprompt / timeout:** this call returned `MCP error -32001: Request timed out` on the
client. The server work nevertheless completed (verified by timestamped artifacts at
18:44:55–18:45:17). This is a client-timeout reporting gap, not a failure — the tool
writes a per-cell (31,831-token) K template, which is slow. Nothing was retried and no
file was hand-edited to compensate.

Generated control file — **`neckartal_r9.pst`** (847 B):

```
pcf version=2 … pestmode estimation / noptmax 1 / svdmode 1
da_num_reals                20
da_observation_cycle_table  neckartal_r9_da_obs_cycle_tbl.csv
da_parameter_cycle_table    neckartal_r9_da_par_cycle_tbl.csv
da_use_simulated_states     True
```

**State-parameter count = 13** (one `head_state` parameter per registered observed cell,
named after its gauge, linked to the observation name so simulated heads carry forward).
Full adjustable list = **14** (13 states + 1 K); `perlen` is `fixed`.

| parameter | partrans | parval1 | bounds | group |
|---|---|---|---|---|
| `k` | **log** | 10.18 | 1.018 – 101.8 | k |
| `perlen` | fixed | 1.0 | 1e-08 – 1e6 | forcing |
| `Ne-401 … Ne-806` (13) | none | shipped strt at that node | ≈ strt ± 5 m | head_state |

Rewiring performed by the tool:
* `mfsim.nam` → `modflowsim.tdis` (NPER 1, 1 step); `modflowsim.tdis.tpl` templates `perlen`.
* `flow.npf` k → `OPEN/CLOSE 'flow_k.dat'`; `flow.ic` strt → `OPEN/CLOSE 'flow_strt.dat'`.
* `flow.nam` gains `obs6 flow.obs`; `flow_head.obs.csv.ins` reads the OBS CSV.
* Cycle tables: `obs_cycle_tbl` carries the 36 gauge values on cycles 0/7/14/17/21/28
  (blank elsewhere); `par_cycle_tbl` holds `perlen=1` for all 30 cycles.

Verified the rewired model still runs: converged, 1.34 s.

## 8. Assimilation (`start_calibration` → `get_job_status`)

```
start_calibration(model="neckartal_r9", pst_file="…/neckartal_r9.pst", method="da")
→ job_id d6b50f735128 (running)
```

Polling: 125 s → cycle 0, phi 274.199 · 433 s → cycle 7, phi 177.584 ·
1038 s → cycle 19 · **succeeded at 1551.28 s (25.85 min)**.
Result: `converged=true`, `cycles=30`, `num_reals=20`, `noptmax=1`.
Ensemble health from the PEST++ DA stdout: `20 of 20 complete, 0 failed` every cycle.
Two informational messages: `initial lambda estimation from phi failed, using 10,000`
(cycle 0) and `no non-zero-weighted observations in cycle 29, continuing`.

### Per-cycle phi (`summarise_da`, post-update ensemble mean)

| cycle | date | n obs | phi | phi / n |
|---|---|---|---|---|
| 0 | 2017-01-30 | 13 | **274.199** | 21.09 |
| 7 | 2017-02-06 | 9 | **177.577** | 19.73 |
| 14 | 2017-02-13 | 3 | **47.299** | 15.77 |
| 17 | 2017-02-16 | 6 | **128.175** | 21.36 |
| 21 | 2017-02-20 | 2 | **40.139** | 20.07 |
| 28 | 2017-02-27 | 3 | **47.439** | 15.81 |
| all others | — | 0 | 0 | — |

### Prior → post-update improvement (cycle 0)

From `neckartal_r9.global.phi.actual.csv`:

| cycle 0 | mean | std | min | max |
|---|---|---|---|---|
| prior (iteration 0) | **331.462** | 23.344 | 275.967 | 370.235 |
| post-update (iteration 1) | **274.199** | 2.677 | 272.345 | 283.906 |

Ensemble-mean phi falls **331.46 → 274.20 (−17.3 %)** and the ensemble collapses from
std 23.34 to 2.68 — the observations do inform the parameters at cycle 0, as expected.

**Honest caveat.** Per-cycle phi is *not* comparable across cycles: it is an unweighted
sum of squared residuals (obs weight = 1.0, so phi is in m²) over a varying number of
gauges. Normalised per observation the fit is essentially flat (15.8–21.4 m²/obs ≈ 4.0–4.6 m
RMSE) across all six informative cycles. The apparent 274 → 47 drop is mostly the
collapse in gauge count, **not** a progressive improvement. The absolute fit stays at a
≈ 4.5 m bias because the shipped model/IC were not calibrated to these gauges — the phi
scale is arbitrary, and that is reported rather than dressed up as a fit.

**Reported final-cycle numbers.** `summarise_da` returns `final_phi_mean = 0`,
`final_phi_std = 0`, because the last cycle (29, 2017-02-28) has no gauge data at all. The
job's `final_phi_mean 23.8276 / std 61.1593` is the mean/std of the per-cycle values over
all 30 cycles (714.827 / 30 = 23.8276), not a final-cycle statistic — both are quoted here
to avoid a misleading headline.

### Posterior parameter statistics (final cycle, 19 non-base realizations)

| parameter | mean | std | min | max |
|---|---|---|---|---|
| **k** (m/d) | **99.658** | 4.927 | 80.357 | **101.202** |
| perlen (d) | 1.0 | 0.0 | 1.0 | 1.0 |
| Ne-401 | 337.420 | 0.031 | 337.410 | 337.543 |
| Ne-402 | 336.013 | 0.013 | 336.009 | 336.064 |
| Ne-403 | 335.006 | 0.007 | 335.004 | 335.034 |
| Ne-503 | 341.632 | 0.086 | 341.605 | 341.973 |
| Ne-504 | 341.648 | 0.086 | 341.621 | 341.988 |
| Ne-505 | 335.823 | 0.009 | 335.820 | 335.859 |
| Ne-506 | 335.820 | 0.010 | 335.817 | 335.857 |
| Ne-604 | 329.374 | 0.038 | 329.226 | 329.386 |
| Ne-801 | 334.221 | 0.004 | 334.220 | 334.235 |
| Ne-802 | 332.640 | 0.005 | 332.619 | 332.642 |
| Ne-803 | 332.644 | 0.005 | 332.624 | 332.646 |
| Ne-805 | 334.644 | 0.003 | 334.643 | 334.654 |
| Ne-806 | 334.643 | 0.003 | 334.642 | 334.652 |

K moved from the prior 10.18 m/d to **99.66 m/d** with the bulk of realizations pinned at
101.2 = the parameter **upper bound** (10 × initial). The DA wants even higher uniform K,
so the estimate is bound-limited. The posterior state spread is ≤ 0.09 m.

### Residuals

`summarise_da`'s residual table (written to `neckartal_r9_da_residuals.csv`) is taken from
the **final cycle (29)**, which has no gauge data — hence every row shows
`measured = 0`, `weight = 0`, `residual = −simulated` (`rmse/bias/r² = null`,
`n_observations = 0`). Those 13 rows are the state-carrying values, **not** a usable
residual statistic. Real per-cycle residuals for cycles 0/7/14/17/21/28 exist in the
workspace (`neckartal_r9.<cycle>.base.rei`) but no MCP tool exposes them; they were not
mined with raw Python, to keep the MCP-only constraint intact.

## 9. Post-processing

* `read_simulated_observations` (final cycle, posterior base): Ne-401 337.410 …
  Ne-806 334.642 m.
* `compare_to_observed` (vs each site's registered mean): **n=13, RMSE 4.620 m,
  bias −4.563 m, MAE 4.563 m, R² −1.473.** Worst: Ne-506 −5.597, Ne-504 −5.471,
  Ne-402 −5.154 m. Residual plot `neckartal_r9_obs_fit.png`, table
  `neckartal_r9_obs_residuals.csv`.
* Versus the pre-DA baseline (RMSE 4.954, bias −4.770): the DA improves RMSE by ~7 %
  (4.95 → 4.62 m). Modest — consistent with a single uniform K against a spatially
  systematic bias, and with the site-mean "truth" mixing six different dates.
* `plot_heads_map` → `artifacts/heads_map_postDA.png`. The vertex-carrying DISU grid
  rendered correctly (no cell2d/Voronoi failure); head range 305.16 – 342.43 m on the
  post-DA (cycle-29 base) run, stored in `flow_output/flow.hds`.

## 10. Deviations from the source model

| # | shipped / repo | this run | reason |
|---|---|---|---|
| D1 | TDIS NPER 6 × 1 day | NPER 1 + DA cycle table (30 × 1 day) | sequential DA requires 1 period × 1 step per cycle; the OBS-CSV instruction file reads only the first data row |
| D2 | heterogeneous K, 0.864–86,400 m/d, 10,413 unique values | **one uniform K = 10.18 m/d** (log, bounds 1.018–101.8), posterior 99.66 m/d | `scope="all"` was mandated for this run; the pattern-preserving `multiplier` scope needs a helper script that stalls under the background DA job on this 31,831-node model. The shipped spatial K pattern is destroyed — recovered from `flow_k_pristine.npy` (31,831 × float64) |
| D3 | bespoke Python EnKF (`main.py`), 15 members, damp_h 0.35 / damp_K 0.05, ε 0.01 m² | **PEST++-DA**, 20 members, `noptmax=1` | method substitution; the repo EnKF is raw flopy and is excluded by the MCP-only constraint |
| D4 | assimilates on any date with > 7 reporting gauges | all 36 records on the 6 reporting dates used | more observations retained; no > 7 filter |
| D5 | 14 gauges in `Pegel_Cell_ID.csv` | 13 registered | Ne-507 has no record in 2017 (2019 only) |
| D6 | daily transient recharge `RCHunterjesingen.csv` and pumping `2017.csv` fed per step | shipped single-period constant RCH/WEL left untouched | re-forcing would be a model edit; no MCP tool was used for it, and the shipped model carries constant boundaries |
| D7 | IC overwritten by `Final_h_field.mat` in `main.py` | shipped `flow.ic_STRT_1.txt` used as IC | shipped IC is the adopted model's own IC; only the 13 state cells are then modified by DA |
| D8 | — | `flow_input\flow.npf_K_1.txt` was rewritten to uniform K by `setup_da_control` (side effect of the rewiring) | pristine pattern preserved in `flow_k_pristine.npy`; an earlier session also keeps `_sim_backup_shipped` |
| D9 | observation error covariance | obs weight 1.0 | phi is an unweighted sum of squared head residuals in m² — arbitrary scale, as anticipated |

## 11. Tool-call sequence

```
check_environment
adopt_model(neckartal_r9, sim/, METERS, DAYS, allow_modify=true)
check_model · summarise_model · model_status
set_simulation(nper=1, perlen=[1.0], nstp=[1], ims=complex)
run_simulation                       # baseline, converged 1.44 s
import_obs_from_csv(cellid_col="Cell_ID", 13 sites / 36 records)
run_simulation                       # baseline fit: RMSE 4.954, bias −4.770
setup_da_control(scope="all", cycles[0..29], obs_cycles, par_cycles{perlen}, num_reals=20, noptmax=1, use_simulated_states=True)
                                     # client timeout -32001; server artifacts verified complete
run_simulation                       # rewired model check, converged 1.34 s
start_calibration(method="da")       # job d6b50f735128
get_job_status × 4                   # progress → succeeded, 1551.28 s
summarise_da
read_simulated_observations
compare_to_observed
plot_heads_map                       # artifacts/heads_map_postDA.png
```

## 12. MCP-only compliance

No flopy/pyemu MODFLOW or PEST class was called; no MODFLOW/PEST input was hand-edited;
the repo EnKF scripts were not run; the model was not copied to another directory. The
only non-MCP Python was (a) melting `Pegel.csv`/`Pegel_Cell_ID.csv` into the observation
CSV that was fed to `import_obs_from_csv`, and (b) read-only inspection of generated
artifacts (input text arrays, `.pst`, cycle tables, `global.phi.actual.csv`, and the
`flow_k`/`flow_strt` arrays) to *report* and *verify* what the tools produced. No gap in
the toolchain forced a workaround; the one tooling weakness found is the
`setup_da_control` client timeout (reporting only, section 7).

## 13. Verdict

The toolchain is **sufficient** for this target end-to-end: adopt a shipped real DISU
model (31,831 nodes, 198,261 connections, vertex geometry) → clean check → re-express a
6-period transient as single-step DA cycles → register 13 real gauges on scalar DISU node
ids → build a PEST++-DA control file with 13 dynamic head states + 1 log-K → run 30
sequential cycles × 20 realizations (25.85 min, zero failures) → summarise, plot and score.

Assimilation is **demonstrated** (cycle-0 ensemble phi 331.46 → 274.20, −17.3 %, ensemble
std 23.3 → 2.7) but the **posterior fit is not calibrated**: RMSE only improves from
4.95 m to 4.62 m, bias stays ≈ −4.5 m, and the single uniform K is pinned at its upper
bound (101.2 m/d). That outcome is the expected consequence of the mandated uniform-K
collapse (D2), the uncalibrated shipped IC/gauges (arbitrary phi scale), and the constant
single-period boundary packages (D6) — reported rather than presented as a fit.

### Artifacts
* `artifacts/heads_map_postDA.png` — post-DA head map on the DISU grid
* `artifacts/obs_gauges.csv` — the 36-row long observation table
* `artifacts/da_cycles.json` — cycles / obs_cycles / perlen as passed to `setup_da_control`
* `prep_obs.py`, `run-log.md`
* in the model workspace: `neckartal_r9.pst`, `neckartal_r9.{obs,par,pargp}_data.csv`,
  `neckartal_r9_da_{obs,par}_cycle_tbl.csv`, `flow_k.dat.tpl`, `flow_strt.dat.tpl`,
  `modflowsim.tdis.tpl`, `flow_head.obs.csv.ins`, `neckartal_r9.global.phi.actual.csv`,
  `neckartal_r9.global.29.pe.csv`, `neckartal_r9_da_residuals.csv`,
  `neckartal_r9_obs_fit.png`, `flow_k_pristine.npy`
