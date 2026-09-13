# Closed-book validation run — Phase 6d target 4
## GMS MODFLOW 6 PEST observations (`mf6_pest_obs_ss`)

Session worktree: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun1`
Source zip: `D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
(Aquaveo GMS 10.9 tutorial; MF6 input + PEST interface only; `.gpr`/`.gpt` not used.)

Constraint observed: **every** build/adopt/run/post-process/calibrate action on the MF6
model went through a `groundwater-mcp` tool. No flopy/pyemu MODFLOW or PEST classes were
called, and no MODFLOW/PEST file was hand-edited. Plain Python was used only to read the
tutorial's own model/PEST files and to prepare observation CSVs.

---

## 1. Environment (`check_environment`)

```
Python 3.12.11
flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0,
numpy, scipy, matplotlib
mf6        : C:\Users\jakob\.local\bin\mf6.exe
pestpp-glm : present
pestpp-ies / sen / opt / da : present
```
Stack ready; no tooling gaps at start.

## 2. Extraction

```
Expand-Archive mf6_pest_obs_ss.zip -> extract\mf6_pest_obs_ss\
```
Relevant tree:
- `sample\pest_obs_ss_models\MODFLOW 6\pest_obs_ss\` — shipped runnable MF6 model
  (`mfsim.nam`, `GWF_Model.nam`, DISV (3306 cells, 1 layer, FEET/DAYS), NPF (K=2.4),
  IC, OC, RCH, RIV (451 reaches), WEL, CHD; external arrays in `GWF_Model_input\`;
  outputs in `GWF_Model_output\`).
- `...\GWF_Model_pest\` — shipped GMS/PEST obs interface (`model.n2b`, `model.blisting`,
  `model.b2b`, `model.bsamp` = observed, `model.bsamp.out`/`model.fsamp.out` =
  reference simulated, `model.bwt`/`model.fwt` = weights, `obs.out`, `temp.rec`).
- `...\GWF_Model_output\pest_obs_stats.txt` — shipped reference residual statistics.

Observations in the shipped interface: **10 head bores** (node-to-bore interpolation in
`model.n2b`, up to 4 nodes/bores) + **1 flow observation** = total RIV discharge over
`CELLGRP 1..6` (all 451 reaches; `model.fsamp` = −4644.0 ft³/d).

## 3. Model adoption (`adopt_model`)

The shipped runnable model was copied to
`work\pest_obs_ss\` (so the shipped reference files stay intact) and adopted:

```
adopt_model(name="pest_obs_ss", workspace="…\work\pest_obs_ss",
            units="FEET", time_units="DAYS", allow_modify=True)
```

`allow_modify=True` was required because the MCP calibration chain (obs registration,
parameterisation) modifies the model. **No grid rebuild** was done — adoption loaded the
shipped DISV grid/arrays directly.

`model_status` confirmed runnable; `summarise_model` reported the DISV grid, 1 stress
period, and all packages.

## 4. check_model

`check_model` → `check_passed: true`, no errors, no warnings.

## 5. Simulation (`run_simulation`)

`run_simulation` → `success: true`, `convergence: converged`, listing summary
"Normal termination of simulation", elapsed 0.26 s.

**Reproduction of the shipped reference (adopted model, K = 2.4 ft/d):**

| | shipped reference | this run |
|---|---|---|
| sim. head @ POINT_#1..10 | `model.bsamp.out` | matched to 5 dp (all 10) |
| total RIV flow | `−5434.209358` (`model.fsamp.out`) | `−5434.209358` (exact) |
| head mean resid | 7.707681 | 7.707682 |
| head mean abs resid | 7.951675 | 7.951676 |
| head RMSE | 10.274824 | 10.274826 |
| flow resid (obs−sim) | 790.209358 | 790.209358 |

The adopted model reproduces the shipped solved model **exactly** — the derivation is
faithful. (`pest_obs_stats.txt` is the fit of the shipped model as-is; it is not a
post-calibration target.)

## 6. Post-processing

- `read_heads` (layer 0): min 304.80, max 316.64, mean 309.97 (adopted run).
- `compute_water_balance` (adopted run):
  inflow `RCHA 5811.635`; outflow `WEL −130`, `RIV −5434.209`, `CHD −249.958`;
  net −2.532 → discrepancy ≈ **0.044 %** (closes).
- `plot_heads_map` → PNG produced (adopted run).
- `diagnose_water_balance` (calibrated run): discrepancy **0.0073 %**, `balanced: true`.

## 7. Calibration through the MCP chain

### 7.1 Observation registration (`import_obs_from_csv`)

Each bore was reduced to its **dominant-weight node** from `model.n2b` (the MCP maps an
obs site to a single cell — it cannot express multi-node interpolation), using the same
observed values from `model.bsamp`:

| site | bore | node | dominant weight | obs (ft) |
|---|---|---|---|---|
| pt01 | POINT_#1 | 762 | 0.657 | 310.62 |
| pt02 | POINT_#2 | 625 | 0.742 | 304.80 |
| pt03 | POINT_#3 | 1168 | 0.676 | 316.53 |
| pt04 | POINT_#4 | 1450 | 0.9998 | 334.67 |
| pt05 | POINT_#5 | 1627 | 0.950 | 308.61 |
| pt06 | POINT_#6 | 2351 | 0.582 | 327.05 |
| pt07 | POINT_#7 | 2128 | 0.995 | 327.66 |
| pt08 | POINT_#8 | 2428 | 0.845 | 316.99 |
| pt09 | POINT_#9 | 3153 | 0.991 | 329.18 |
| pt10 | POINT_#10 | 3027 | 0.614 | 316.38 |

### 7.2 Calibration setup (`setup_calibration`)

```
setup_calibration(obs_source="model",
                  parameterisation={"hk_all":{"target":"npf:k","scope":"all","initial":2.4}},
                  noptmax=10)
```
generated `pest_obs_ss.pst`, `gwf_model_k.dat.tpl` (3306 wide tokens),
`gwf_model_head.obs.csv.ins`, and a forward wrapper; NPF `k` rewired to
`OPEN/CLOSE 'gwf_model_k.dat'`. 10 obs, 1 parameter `hk_all` (K, log, 2.4, bounds
0.24–24).

`setup_pest_control` was **not** usable: it requires pre-existing template/instruction
files, which cannot be authored by hand under the MCP-only constraint.
`setup_calibration` (the automated setup that generates them) was used instead.

### 7.3 Run (`start_calibration` → GLM)

`run_pestpp_glm` timed out the client and left the run incomplete. Re-issued through
`start_calibration` (background job), polled with `get_job_status`. GLM ran successfully
(model runs all "normal termination"); stopped with `cancel_job` after iteration 1
because ≈85 s/model-evaluation made a 10-iteration run impractical.

### 7.4 Summary (`summarise_calibration`)

```
engine glm
phi: iteration 0 = 1060.06 → iteration 1 = 208.037
hk_all: 2.4 → 0.426787 ft/d  (bounds 0.24–24, log)
RMSE 4.5611 | bias −3.0562 | MAE 3.6864 | R² 0.7650 | n = 10
verdict: improved = true, final_phi = 208.037
```
Calibrated state re-run through `run_simulation` reproduced the GLM fit exactly
(RMSE 4.5611, residuals identical to `.rei`), with water balance closing at 0.007 %.

## 8. Reference comparison

| metric (head, ft) | shipped reference (K=2.4) | MCP adopted run | MCP GLM calibrated (K=0.427) |
|---|---|---|---|
| mean residual | 7.7077 | 7.7077 | −3.0562 |
| mean abs residual | 7.9517 | 7.9517 | 3.6864 |
| RMSE | **10.2748** | 10.2748 | **4.5611** |
| R² | — | −0.198 | 0.765 |
| flow residual (obs−sim) | 790.209 | 790.209 | 900.365 (calibrated RIV = −5544.365) |

- The MCP pipeline **reproduces the shipped reference exactly** for the adopted model.
- Head-only GLM calibration **halved the head RMSE** (10.27 → 4.56, R² 0.77) by lowering
  K from 2.4 to 0.427 ft/d.
- The response is head-dominated (RCHA inflow ≈ RIV outflow, domain boundary-dominated),
  so a single uniform K mainly trades head bias against RIV discharge; excluding the
  flow observation from the calibration **worsened** the flow residual (790 → 900 ft³/d).

## 9. Deviations, reprompts and MCP capability gaps

1. **Flow observation not representable (capability gap).** The shipped interface's
   second observation is a compound total-RIV flow. `import_obs_from_csv` accepted
   `obs_type="FLOW"` and wrote `FLOW FLOW 1 762`; MF6 rejected it:
   `ERROR 1. Observation type not found: FLOW`. The call also **replaced** the 10 head
   observations (no mixed HEAD+FLOW registration). The flow obs therefore could not be
   included in the calibration; it was evaluated post-hoc from `compute_water_balance`.
   (MF6's OBS package does not support a `FLOW` continuous type; the MCP wrote it anyway.)
2. **`#` in site names corrupts the OBS file (bug).** The shipped names `POINT_#1..10`
   caused `setup_calibration` to rewrite `gwf_model.obs` as
   `point_  #  '1  head  1 762'`, so MF6 read `#` as the observation type and the base
   run failed ("Base parameter run failed. Can not compute the Jacobian"). Fixed by
   re-registering with `#`-free labels `pt01..pt10` (same cells/values).
3. **Interpolation vs single-cell mapping.** GMS observes interpolated bore heads over up
   to 4 nodes (`model.n2b`); the MCP maps each site to one nearest-centroid cell. Reduced
   to dominant node — small effect (e.g. pt04 weight 0.9998 → residual identical to
   reference; other sites differ by <0.2 ft in the simulated value).
4. **Weights not importable.** Shipped PEST weights (`model.bwt` ≈0.65–1.31, `model.fwt`
   ≈0.00933) are not settable via `import_obs_from_csv`; the MCP uses weight 1.0. MCP
   phi is therefore an unweighted head SSE, not the shipped weighted SSE (1 239.78).
5. **OC output control dropped on rewrite (bug).** The MCP's adopt/flush re-serialisation
   of `GWF_Model.oc` dropped the period `SAVERECORD` (`oc_1.txt`: `SAVE HEAD FIRST`,
   `SAVE BUDGET FIRST`), leaving `GWF_Model.hds`/`.cbc` empty. Re-added via
   `add_oc_package(saverecord=[["HEAD","FIRST"],["BUDGET","FIRST"]], …)`; post-processing
   then worked.
6. **`run_pestpp_glm` client timeout.** Synchronous GLM exceeded the client timeout;
   switched to `start_calibration` + `get_job_status`, and reported GLM iteration 1
   (best phi) after `cancel_job`.
7. **Calibration runtime.** ≈85 s per model evaluation (~1 min per MF6 run incl. PEST++
   overhead) despite MF6 itself running in 0.2 s. Only iteration 1 was completed.
8. `summarise_calibration` flagged `parameters_at_bounds: ["hk_all"]`, but K = 0.4268 is
   comfortably inside the 0.24–24 bounds; the flag appears spurious.
9. Model adopted with `allow_modify=True`; the MCP re-serialised the shipped inputs
   (physics preserved: K=2.4, RCH=7.62e-5, all boundary values/aux unchanged).

## 10. Artifacts produced

- `work\pest_obs_ss\` — adopted/modified model workspace (`pest_obs_ss`).
- `heads_obs.csv`, `heads_obs_clean.csv`, `flow_obs.csv` — observation inputs.
- `compare_reference.py` — reference reproduction check.
- `calibration_evidence\` — `.pst`, `.rei`, `.iobj`, `.rec`, `_residuals.csv`.
- Head-map PNGs (adopted and calibrated runs).
- `run-log.md` (this file).

## 11. Bottom line

The groundwater-mcp chain **adopts, runs, post-processes and calibrates the shipped GMS
MF6 model without any raw flopy/pyemu workaround**, and reproduces the shipped solved
reference exactly. The calibration chain works end-to-end (head obs → setup_calibration →
PEST++ GLM → summarise_calibration) and improves the head fit substantially.

However, the chain is **not sufficient to reproduce the shipped PEST interface faithfully**:
the compound RIV-flow observation cannot be registered (and a bogus `FLOW` obs is written
that MF6 rejects), observation mixing is impossible, `#` in site names breaks the OBS
file, and the OC period saverecord is dropped on model rewrite. These are concrete,
reproducible capability gaps in the MCP toolchain, documented above rather than worked
around.
