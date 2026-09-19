# Run log — Phase 6d target 8: MF6_EnKF_DISU (Neckartal DE), sequential DA

Session worktree: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-enkf-disu-rerun1`
Date: 2026-09-14
Model: `github.com/JanGei/MF6_EnKF_DISU` (cloned 2026-09-13). **No LICENSE file present** in the
repo (verified by directory listing) — licence status unresolved; treated as a read-only
third-party dataset for validation only.

## Result up front

Steps 1–5 completed. **Step 6/7 (sequential PEST++-DA) is BLOCKED by a hard MCP capability gap:
`setup_da_control` cannot produce a DA-ready PST for a DISU grid.** No workaround was attempted
(no raw flopy/pyemu, no hand-edited MODFLOW/PEST files). Details in "Capability gap" below.

---

## 1. Environment (`check_environment`)

```
python 3.12.11
flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8
mf6, pestpp-glm, pestpp-ies, pestpp-sen, pestpp-opt, pestpp-da  -> all present
docs_index_built=true ; workspace_root=C:\Users\jakob\.groundwater-mcp\workspaces
ready=true, missing={}
```

## 2. Adopt (`adopt_model`)

```
name=neckartal  (9 chars, <= 16)
workspace=D:\...\MF6_EnKF_DISU\NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim
units=METERS  time_units=DAYS  allow_modify=true
-> adopted:true, model_names=["flow"]
```

`summarise_model` confirmed the shipped geometry: **DISU, 31,831 nodes, NJA 198,261, 31,522 active**,
packages DISU/NPF/IC/CHD/WEL/RIV/RCH/STO, 6 stress periods. The grid was **not** rebuilt; the
external arrays in `flow_input\` (TOP/BOT/AREA/IDOMAIN/IAC/JA/IHC/CL12/HWVA/ANGLDEGX/VERTICES/CELL2D,
K/K33/ICELLTYPE, STRT, CHD/RIV/RCH/WEL) were preserved and still referenced by OPEN/CLOSE.

## 3. check_model

Clean, twice — once immediately after adopt and again after collapsing TDIS:

```
check_passed=true, warnings=[], errors=[]
"No errors or warnings encountered." (NPF/CHD/RCH/RIV/WEL/STO checks all passed)
model_status: runnable=true, missing_required=[], missing_recommended=[]
```

## 4. Re-expression as single-step cycles (`set_simulation`)

Shipped TDIS is NPER=6 × 1 day. Collapsed to the DA requirement (NPER=1, NSTP=1):

```
set_simulation(neckartal, nper=1, perlen=[1], nstp=[1], ims_complexity="complex")
-> nper=1, total_time=1, written:false
```

Notes / deviations observed:
- The MCP regenerated the simulation: it wrote a **new** `mfsim.nam` referencing `modflowsim.tdis`
  (NPER 1) and `modflowsim.ims` (COMPLEX), leaving the original `sim.tdis`/`sim.ims` orphaned on
  disk. This is the tool's own write mechanism (triggered by `set_simulation`), not a hand edit.
- The original `sim.ims` options `NO_PTC all` and `OUTER_DVCLOSE 0.1` were replaced by the tool's
  `COMPLEXITY complex` IMS. **Deviation from the source model.**
- `flow.sto` initially kept 6 period blocks against NPER=1; MF6 still ran period 1 and converged.
  (Later, the failed `setup_da_control` rewrote `flow.sto` to a single TRANSIENT period.)
- The DA cycle length is driven per cycle by `par_cycles["perlen"]`, so the base `perlen=[1]` is a
  placeholder.

## 5. Register gauges

Data prep (ordinary Python, allowed): reshaped the wide `csv data\Pegel.csv` (Date + 14 gauge
columns, `-9999` = missing, dates `DD.MM.YYYY`) and joined `csv data\Pegel_Cell_ID.csv`
(Name → scalar DISU `Cell_ID`). Produced `obs_gauges.csv` with columns `site,date,value,Cell_ID`.

Cycle design — cycles chosen on 2017 gauge dates that align with the shipped IC and the repo's
EnKF start date (2017-01-30). Every chosen date has **13 of the 14** gauges valid:

| cycle | date       | perlen (d) | gauges |
|-------|------------|-----------:|-------:|
| 0     | 2017-01-30 | 1          | 13     |
| 1     | 2017-03-27 | 56         | 13     |
| 2     | 2017-04-06 | 10         | 13     |
| 3     | 2017-06-19 | 74         | 13     |
| 4     | 2017-08-03 | 45         | 13     |
| 5     | 2017-08-29 | 26         | 13     |

perlen = actual day gaps between gauge dates (cycle 0 is a 1-day prior step).

**Deviation:** gauge `Ne-507` is excluded. It has only 16 valid records in the whole 2003–2019
table, all in 2019, so it has no value at any chosen cycle; **no date has all 14 gauges valid**
(max = 13). Fabricating a value was not acceptable, so only the 13 co-observed gauges were
registered. All 14 Name→node mappings were nonetheless inspected and are physically plausible
(Table below).

`import_obs_from_csv(model, csv_file=obs_gauges.csv, obs_type=HEAD, cellid_col="Cell_ID",
site_col="site", date_col="date", value_col="value")`:

```
site_count=13, total_records=78
site_cellid_map (1-based OBS ids; input Cell_ID is 0-based, tool added +1):
  Ne-401 14119->14120  Ne-402 13835->13836  Ne-403 15081->15082  Ne-503 21856->21857
  Ne-504 11201->11202  Ne-505 13261->13262  Ne-506 23969->23970  Ne-604 16316->16317
  Ne-801 11418->11419  Ne-802 11904->11905  Ne-803 22575->22576  Ne-805 22737->22738
  Ne-806 12064->12065
```

Written `flow.obs` = 13 non-time-series HEAD observations (one per site), added to `flow.nam` as
`OBS6`. Not time-series: the obs are evaluated every time step, so with NPER=1/NSTP=1 the model's
`flow_head.obs.csv` has a single (end-of-cycle) row — exactly the canonical DA instruction-file
contract.

### Verification run (baseline, uncalibrated)

`run_simulation` → **converged**, elapsed 1.56 s (single 1-day period).

`read_simulated_observations` / `compare_to_observed` (observed = mean of each site's 6 registered
records, simulated = model value), n=13:

```
RMSE 4.97 m   bias -4.79 m   MAE 4.79 m   R2 -1.80
worst: Ne-504 -7.94, Ne-503 -6.57, Ne-401 -5.57, Ne-506 -5.27, Ne-402 -5.00 (m)
```

The model is uniformly **~2.5–8 m too high** vs the 2017 gauge values. This is the uncalibrated
baseline (the shipped IC comes from the repo's own prior EnKF head field; the K field is a raw
calibration field). **The phi scale for any DA here is therefore arbitrary/uncalibrated** — there
is no expectation of a small residual, only of *relative* improvement.

## 6–7. setup_da_control / run_pestpp_da — BLOCKED (capability gap)

Intended call:

```
setup_da_control(
  model="neckartal",
  parameterisation={"k": {"target":"npf:k","scope":"all","initial":1,"partrans":"log"}},
  cycles=[0,1,2,3,4,5],
  obs_cycles={ <13 sites> -> {cycle: gauge value} },   # values from step 5
  par_cycles={"perlen": {0:1, 1:56, 2:10, 3:74, 4:45, 5:26}},
  num_reals=15, noptmax=1, use_simulated_states=True)
```

Attempt 1 → **client timeout (-32001)** after ~2 min. The server had partially written:
`flow.npf` rewired `k` from `flow_input/flow.npf_K_1.txt` to a new `flow_k.dat`;
`flow_k.dat.tpl` (single parameter token `~ k ~` on all 31,831 lines);
`flow_k_pristine.npy` (original heterogeneous K, 0.864–86400 m/d).
No `.pst`, no cycle tables, no wrapper were produced.

Attempt 2 → immediate, definitive error:

```
{"error":true,"code":"INVALID_INPUT",
 "message":"setup_da_control IC state parameterisation supports DIS and DISV grids only;
            this model has neither."}
```

Attempt 3 (`use_simulated_states=False`) → rejected by design:

```
{"error":true,"code":"INVALID_INPUT",
 "message":"use_simulated_states=False is not supported: pestpp-da v5.2.16 requires
            final-to-initial state linkages that setup_da_control does not emit ... Only
            use_simulated_states=True is supported."}
```

### The gap

`setup_da_control` forces `use_simulated_states=True` (it writes a state-augmented IC `strt`
template, one state parameter per observed cell), and that IC state parameterisation only accepts
**DIS or DISV** grids. This target is **DISU** (`nlay=1`, scalar node ids). The two branches are
mutually exclusive, so there is **no input that makes `setup_da_control` succeed on a DISU model**:

- `use_simulated_states=True`  → DISU not supported (IC state parameterisation).
- `use_simulated_states=False` → rejected unconditionally.

Consequently no DA-ready PST (cycle column + `da_*` options + state params) can be produced, so
`run_pestpp_da` and `summarise_da` cannot be exercised on this model. **Step 7 was not run.**

This is exactly the "IR in a DISU data assimilation workflow" target of the validation: a real
DISU model with real gauges, where the MCP sequential-DA path is expected to work but does not.

### Secondary finding — the failed setup is non-transactional

The failed `setup_da_control` left the workspace inconsistent rather than rolling back:
- `flow.npf` now points at `flow_k.dat` (currently all `1.0`) → the model would run with **uniform
  K = 1 m/d**, destroying the calibrated heterogeneous field.
- `flow.sto` was rewritten from 6 periods to 1 period.
- `flow_k.dat.tpl`, `flow_k_pristine.npy` left behind; no PST.
Restoring the original K through MCP alone is not possible: `add_npf_package` requires the 31,831
values inline (no file-path/OPEN-CLOSE input), and hand-editing the package file is forbidden.
The pristine values survive in `flow_k_pristine.npy` / `flow_input\flow.npf_K_1.txt`. The baseline
`flow.hds` (correct K) was not overwritten and was used for postprocessing.

## 8. Postprocess

- `plot_heads_map(neckartal)` → `gwmcp_gx4sfbg6.png`; DISU vertex/CELL2D grid renders correctly
  (plan view of the Neckar valley), heads 305.16–345.24 m, 31,522 active.
- `read_heads` → layer 0, kstpkper (0,0): n_active 31,522, min 305.16, max 345.24, mean 327.07.
- `read_simulated_observations` + `compare_to_observed` already captured in step 5.
- A "final-cycle" comparison is not meaningful because no DA cycles were run.

## 9. Method / deviation summary

| Aspect | Source model | This run |
|---|---|---|
| Run driver | bespoke EnKF (`main.py`/`Transient_Run.py`, raw flopy) | MCP toolchain only (never executed repo EnKF) |
| TDIS | NPER 6 × 1 day | NPER 1 × 1 step, perlen driven per cycle |
| IMS | `COMPLEXITY complex`, `NO_PTC all`, `OUTER_DVCLOSE 0.1` | tool-rewritten `COMPLEXITY complex` only |
| DA method | bespoke EnKF, 15 members, damped K/h, daily steps from 2017-01-30 | PEST++-DA intended; **blocked** |
| Assimilation window | 2017-01-30 + 30 daily steps | 6 gauge dates (2017), perlen = inter-observation gaps |
| Gauges | 14 (assimilated only when >7 valid) | 13 (Ne-507 excluded — no overlap) |
| Files | shipped `sim\` | MCP regenerated `modflowsim.tdis`/`.ims`, rewired NPF, added OBS6 |

## 10. Stop point

Per the MCP-only constraint, work stopped at the `setup_da_control` DISU limitation rather than
bypassing it with raw flopy/pyemu or hand-written PEST files. Steps 1–5 and 8 (env, adopt,
check_model, TDIS re-expression, gauge registration + verification, postprocess plot/obs fit) are
complete; steps 6–7 (DA setup/run) are not achievable with the current toolchain on a DISU grid.
