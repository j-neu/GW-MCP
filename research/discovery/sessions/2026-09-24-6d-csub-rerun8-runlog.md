# Run log — Phase 6d target 9 (1DSubsidenceModeling-MF6CSUB, H201), closed-book rerun-8

Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-target9-csub-rerun8`
Working subfolder: `...\csub-h201-rerun8\`
Target data (read-only, untouched): `D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB`

## 1. Environment (`check_environment`)

| item | value |
|---|---|
| python | 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy / pyemu | 3.10.0 / 1.4.0 |
| geopandas / rasterio / numpy / scipy / matplotlib | 1.1.3 / 1.5.0 / 2.4.4 / 1.17.1 / 3.10.8 |
| mf6 | `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-glm / ies / sen / opt / da | present |
| ready | true (missing packages: [], missing binaries: []) |
| docs index | built (`C:\Users\jakob\.groundwater-mcp\index`) |

## 2. Data preparation (allowed: produces inputs, not the model)

1. Copied `H201\` and `dependencies\` (13.2 MB, 717 files) from the holdout into
   `...\csub-h201-rerun8\`. The holdout tree was not modified; no code ran inside it.
2. Ran the repo's own `prep_data.py` **inside the copy** (cwd = `...\csub-h201-rerun8\H201`,
   `PYTHONPATH` = session working dir). It produced
   `H201\processed_data\H201.model_property_data.csv` and `H201.ts_data.csv`
   (daily-interpolated groundwater levels) — these are the repo's own preprocessing outputs.
   Key values: top 53.8 ft; botm [-77.2, -1117.2]; Upper 131 ft / Middle 1040 ft;
   thick_frac_0 [7.4450, 22.9241]; rnb_0 [5.9100, 24.0358]; cdelay [nodelay, delay];
   ssv_cc [5e-5, 5e-4]; sse_cr [2.5e-7, 2.5e-6]; theta 0.35; ib_kv 5e-5; pcs0=0 (record).
3. Wrote `prep_inputs.py` (plain pandas only) that replicates `model_functions.initialize_model`'s
   forcing construction: it resamples the processed levels to yearly (year-end) means, emits the
   TDIS (`perlen`, `nstp`), the per-period GHB heads, and `start_date_time`. Outputs `timeseries.json`
   (14 KB) and `props.json`. Result: `start_date_time = 1903-12-31`, 122 historical yearly periods
   + 36 predictive periods to 2060 = **158 periods**, 1 time step each, lay-0 head flat at 46.3 ft
   until the 1960s then declining (min ~ -4.4 ft), lay-1 declining to ~ -43.1 ft near 2012.

No flopy/pyemu MODFLOW or PEST classes were used anywhere; no MODFLOW/PEST file was hand-edited.

## 3. Model build (MCP tool calls only)

Model name `h201csub` (8 chars), workspace `...\csub-h201-rerun8\model_ws`, units **FEET / DAYS**.

| # | tool call | notes |
|---|---|---|
| 1 | `create_model(h201csub, FEET, DAYS, workspace)` | |
| 2 | `set_simulation(nper=158, perlen, nstp=[1]*158, start_date_time=1903-12-31, newton=true, ims_complexity=simple, linear_acceleration=bicgstab, outer_maximum=300, under_relaxation=simple)` | total time 57346 d |
| 3 | `add_dis_package(2,1,1, delr=delc=1, top=53.8, botm=[-77.2,-1117.2])` | first attempt with `idomain=[[1]]` was rejected (PACKAGE_ERROR, invalid idomain format); retried without idomain — all cells active, same as repo (repo sets no idomain) |
| 4 | `add_npf_package(icelltype=[1,1], k=[10,10], k33=[0.01,0.01], k_units=ft/d)` | feet units, values as-is |
| 5 | `add_ic_package(strt=53.8)` | = max processed head, as repo |
| 6 | `add_sto_package(iconvert=[0,0], ss=[0,0], sy=[0,0], steady_state=[0])` | period 0 steady, rest transient; ss=0 as repo |
| 7 | `add_boundary_package(GHB, 158-period head series, cond=50000)` | **2 records per period** (layers 0 and 1), accepted for all 158 periods |
| 8 | `add_csub_package(...)` | see below |
| 9 | `add_oc_package()` | head `h201csub.hds`, budget `h201csub.cbb` |
| 10 | `check_model()` | `check_passed: true`, 0 errors, 2 warnings (sto specific storage < 1e-6 — the deliberate ss=0) |
| 11 | `run_simulation()` | client returned `MCP error -32001` (client timeout only); listing shows **"Normal termination of simulation", elapsed 0.169 s** |

CSUB call detail:
- `packagedata` (11-field, 0-based): `[0,[0,0,0],nodelay,0,7.44503670,5.90997758,5e-5,2.5e-7,0.35,5e-5,0]`,
  `[1,[1,0,0],delay,0,22.92409836,24.03584173,5e-4,2.5e-6,0.35,5e-5,0]` (one composite interbed per layer;
  2 interbeds, 1 delay interbed).
- `ndelaycells=19`, `head_based=false`, `initial_preconsolidation_head=true`,
  `specified_initial_interbed_state=false`, `update_material_properties=false`,
  `sgm=[1.7,1.7]`, `sgs=[1.7,1.7]` (repo passes `sgm` for `sgs`), `cg_theta=[0.3,0.3]`,
  `cg_ske_cr=[2.5e-7,2.5e-6]`; beta/gammaw left at the FEET defaults (2.227e-8 / 62.48, the repo values).
- `filerecords`: zdisplacement `h201csub.displacement.hds`, package_convergence `h201csub.conv.log`,
  strainib `h201csub.strainib.csv`.
- Observations: 4 cell types (compaction/preconstress/elastic-/inelastic-compaction × 2 layers),
  `interbed-compaction-pct` for interbeds 0 and 1, and `delay-preconstress`/`delay-head` for the
  delay interbed at delay-cells 0/9/18 (16 records) → `obs_output_csv = h201csub.csub.obs.csv`.

### Deviations from the source `model_functions.py` build
- **idomain**: omitted (all active). The repo also sets no idomain, so no behavioural difference.
- **IMS under-relaxation**: repo uses numeric `relaxation_factor=0.97`; the MCP parameter takes an
  IMS keyword, so `under_relaxation="simple"` was used. Solver is otherwise matched
  (simple, outer_max 300, bicgstab) and the model converges.
- **GHB/forcing reconstruction**: done in plain pandas replicating `initialize_model`
  (year-end mean resampling, predictive extension to 2060 reused last head) rather than by
  running the repo's builder. Values are derived from the repo's own `prep_data` outputs.
- Everything else (layering, K, storage, interbed parameters, CSUB options, observation layout)
  follows `model_functions.py` / the `__main__` H201 example.

## 4. Post-processing (MCP tools)

- `read_compaction`: 158 output times; per-layer compaction and the derived cumulative
  **subsidence** series. Interbed strains: no-delay interbed (layer 1) total compaction
  0.0118 ft (0.159 %), delay interbed (layer 2) total compaction 20.229 ft (3.67 %).
  **Uncalibrated prior subsidence ≈ 20.26 ft** and flat after ~2012 (predictive period freezes head).
- `plot_subsidence(observed_csv=H201_sub_data.csv)` → PNG
  (`...\model_ws\gwmcp_qsrilfxn.png`); `has_observed: true`, `observed_axis: "model-time"`
  (observed series plotted on the model time axis and visually aligned).
- Comparison vs the site's own `sub_data.csv` (max measured subsidence 3.05 ft, 2023):
  the **prior strongly over-predicts** (~20 ft vs ~3 ft) — this is the expected pre-calibration
  state and is what the calibration corrects.

## 5. Calibration (MCP chain)

- `import_subsidence_observations(H201_sub_data.csv, time_col="Date", value_col="Subsidence_ft")`
  → `n_observations = 208`, sim source `h201csub.csub.obs.csv`, `sum_cols=["compaction"]`,
  match `nearest`.
- `setup_calibration(obs_source="derived", noptmax=5, parameterisation=...)`:
  - `ssv`: `csub:packagedata` columns `[ssv_cc, sse_cr]`, layers `[0,1]` (4 params)
  - `cg0`, `cg1`: `csub:cg_ske_cr` layer 0 / layer 1
  - → **6 adjustable parameters**, 208 observations, all **208 matched** (`skipped_dates: []`,
    `max_match_days 182`). PST `h201csub.pst`, derived target `h201csub_subsidence.csv`.
- `run_pestpp_ies(num_reals=12, num_workers=1)` — synchronous call returned `MCP error -32001`
  (client timeout) while the ensemble kept running server-side (as expected on this host).
  Monitored `h201csub.phi.actual.csv`; run completed to iteration 5 (232 forward runs).
- `summarise_calibration`:

  phi progress (ensemble mean): 575811 → 3814.6 → 39.85 → 15.23 → 14.25 → **14.03**
  (base-parameter phi: ~4.5e4 at iter 0 → **14.02** at iter 5). `verdict.improved = true`.

  Parameter estimates vs priors (log-transformed):

  | param | prior | posterior | bounds |
  |---|---|---|---|
  | cg0 (cg_ske_cr L1) | 2.5e-7 | 1.715e-7 | 2.5e-8 – 2.5e-6 |
  | cg1 (cg_ske_cr L2) | 2.5e-6 | 1.002e-6 | 2.5e-7 – 2.5e-5 |
  | ssv_sse_cr_1 (L1) | 2.5e-7 | 9.84e-7 | 1.25e-8 – 5e-6 |
  | ssv_sse_cr_2 (L2) | 2.5e-6 | 2.95e-6 | 1.25e-7 – 5e-5 |
  | ssv_ssv_cc_1 (L1) | 5e-5 | 1.155e-4 | 2.5e-6 – 1e-3 |
  | ssv_ssv_cc_2 (L2) | 5e-4 | **6.14e-5** | 2.5e-5 – 1e-2 |

  Residual statistics (208 obs): **RMSE 0.2596 ft, bias +0.0064 ft, R² 0.7904**; max |residual|
  ~0.81 ft (earliest survey) and typically 0.1–0.5 ft through the series. The dominant lever is the
  clay-layer 2 inelastic specific storage `ssv_cc`, reduced ~8× from 5e-4 to 6.1e-5, bringing total
  subsidence from ~20 ft to ~2.7 ft against ~3 ft observed. `verdict.parameters_at_bounds` lists
  `ssv_ssv_cc_2` (posterior near the lower end of its range) — worth noting as the parameter the
  data is pushing hardest. `identifiable` / `fit_within_measurement_error` are null (no
  measurement error supplied).

## 6. Coordination / process log

- reprompts: **0**; permission prompts: **0**.
- MCP-visible errors handled: (a) one DIS `idomain` PACKAGE_ERROR → retried without idomain;
  (b) two `-32001` client timeouts (`run_simulation`, `run_pestpp_ies`) — both were client-side only;
  server-side work completed (verified via listing file and phi CSV), no cancellation was issued.
- MCP-only constraint honoured: every build/run/post-process/calibration action went through
  groundwater-mcp tools. Only `prep_data.py` (the repo's data preparation) and a pandas-only
  forcing/TDIS derivation ran as ordinary Python.

## 7. Result

The MCP toolchain built, ran (normal termination), post-processed and IES-calibrated the H201
1D CSUB model end-to-end with no raw flopy/pyemu MODFLOW or PEST calls: prior total subsidence
~20.3 ft → calibrated RMSE 0.26 ft (R² 0.79) vs the site's 208 measured subsidence points.
