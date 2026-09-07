# Run log — Phase 6d target 6: neversink_workflow watershed model (MCP closed-book validation)

Date: 2026-09-07  Session folder: `D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink`
Model source: `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\`
Scope: validate the groundwater-mcp toolchain end-to-end on the adopted USGS neversink MF6 model
(DIS 4 × 680 × 619 @ 50 m, METERS, single steady period 1 d from 2011-01-01; DIS/IC/NPF/RCH/OC/WEL/CHD/SFR
+ OBS6 continuous head + SFR obs). MCP-only constraint respected: no flopy/pyemu MODFLOW/PEST calls and no
hand-editing of MODFLOW or PEST files.

## 1. Environment stack (check_environment)

- Python 3.12.11 (`D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`), Windows 10.
- flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8, whoosh 2.7.4.
- Binaries: `mf6.exe`, `pestpp-glm/-ies/-sen/-opt/-da.exe` under `C:\Users\jakob\.local\bin`.
- docs index built; workspace root `C:\Users\jakob\.groundwater-mcp\workspaces`; `ready: true`.

## 2. Tool-call sequence (chronological, model-touching calls only)

| # | Tool | Model | Result |
|---|------|-------|--------|
| 1 | check_environment | — | stack ready (above) |
| 2 | adopt_model | `neversink` | adopted read-only from shipped `neversink_mf6\` (mfsim.nam + packages) |
| 3 | check_model | neversink | check_passed=true, errors=[], 105 warnings (88 CHD + 17 WEL “BC in inactive cell”) — inherited from shipped inputs (documented, §5) |
| 4 | clone_model | `nvsink_base` | read-only clone at `work\nvsink_base` (clone of a read-only adoption is itself read-only) |
| 5 | clone_model | `nvsink_cal` | clone at `work\nvsink_cal`, re-registered via delete_model + adopt_model(allow_modify=True) for calibration work |
| 6 | start_run (job 5138e2053622) | nvsink_base | **succeeded, 33.4 s, converged, normal termination** (get_job_status / get_run_log / diagnose_convergence confirmed) |
| 7 | read_heads kstpkper [0,0] | nvsink_base | L1: 85,051 active, 88.1–631.2 m, mean 361.5 m |
| 8 | read_heads kstpkper [0,0] layer 3 | nvsink_base | L4: 189,698 active, 85.7–723.6 m, mean 355.8 m |
| 9 | compute_water_balance | nvsink_base | closes: in RCHA 489,968 / CHD 10,607 / SFR 22,788; out WEL −9,881 / CHD −13,164 / SFR −500,318 m³/d; net −0.082 m³/d |
| 10 | diagnose_water_balance | nvsink_base | percent_discrepancy −1.57e−5 % (tolerance 1 %), balanced=true; dominant inflow RCHA, dominant outflow SFR (share 49.98 %) |
| 11 | diagnose_convergence | nvsink_base | converged=true, failure_class=“converged” |
| 12 | plot_heads_map layer 0 / layer 3 | nvsink_base | PNGs written (see §7) — image preview not viewable by this model, files are the deliverables |
| 13 | export_water_balance_csv | nvsink_base | `nvsink_base_water_balance.csv` (5 rows) |
| 14 | export_model_report | nvsink_base | `nvsink_base_report.md` (obs-fit section empty — no obs targets registered) |
| 15 | set_model_crs EPSG:26918 | nvsink_cal | ok (grid carries XORIGIN 1,742,955 / YORIGIN 2,258,285 → NAD83/UTM 18N) |
| 16 | import_obs_from_csv (8 variants) | nvsink_cal & nvsink_base | **OBS_IMPORT_FAILED: `'list' object has no attribute 'lower'`** (§6) |
| 17 | setup_calibration (4-layer spec) | nvsink_cal | **INVALID_INPUT: obs_source='model' requires targets registered via import_obs_from_csv — none found** (§6) |
| 18 | export_model_spec | neversink / clones | SPEC_EXPORT_FAILED: `could not convert string to float: 'sv_193'` (obs-name handling) — corroborates §6 |

Data-prep / reference-reading Python (allowed) used only to: parse shipped `neversink.obs` + reference `neversink.head.obs`,
read shipped idomain/K arrays, join NY-DEC/NWIS observation tables, and write `work\neversink_head_observations.csv`.

## 3. Decisions and deviations from the source model

- **Never ran the adopted read-only model in place.** Running MF6 in the shipped directory would have overwritten the
  shipped solved listings / obs outputs (the reference). All runs/post-processing were done on the read-only clone
  `nvsink_base`; the shipped directory remains byte-identical (verified by `list_model_files`; nothing flushed for read-only models).
- **Adopted as-is; grid rebuilt / renamed nowhere.** The shipped `mfsim.nam` + package files are the model. Model name `neversink` (≤16 chars).
- **Active-cell count discrepancy with the brief.** The brief said ~1.7 M cells / ~843k active. The shipped `idomain_*.dat`
  arrays give **1,683,680 cells and 300,236 active** (L1 85,051; L2 13,787; L3 11,700; L4 189,698). All active cells have K>0.
  This is what adopt_model/run actually solve; reported numbers follow the shipped files, not the brief.
- **Parameterisation structure (would-have-been, not applied).** MCP `setup_calibration` parameterises whole NPF `k` arrays and
  refuses any un-assigned cell. The only clean low-order structure it exposes is **uniform K per layer** (4 log parameters),
  which is a documented structural simplification of the native spatially variable K fields (per-layer active geometric means:
  L1 0.654, L2 0.597, L3 20.63, L4 0.168 m/d). This is recorded as a deviation; it was never applied because the chain is
  blocked earlier (see §6).
- Scratch `probe`/`probe2` models created to isolate the obs-import bug hit a second server defect
  (create_model workspace routed to a non-existent `%TEMP%\tmp*\...` path / `.gwmcp_meta.json` mismatch) and were deleted. Noted only.

## 4. Reference comparison (native-parameter run vs shipped solved listings)

Shipped reference = solved `mfsim.lst`/`neversink.list` (52 outer iterations, ~45 s in 2021) + obs outputs. Our native clone run:

- Obs-CSV comparison (`neversink.head.obs`, 857 columns): regenerated values match the shipped reference solution to
  **max |Δ| = 3.06e−4 m, mean |Δ| = 5e−6 m** (identical header/order). 
- SFR gage obs (USGS 01436500 rno 6700; 01366650 rno 11127): **identical** (−0.10094E+06, −0.14714E+06 m³/d).
- Water balance matches the shipped listing budget (RCHA≈489,968 in; SFR≈500,318 out; WEL≈9,881 out) to <0.1 %.
- Conclusion: the shipped solved listings reproduce the native-parameter run, and the MCP-run model reproduces the listings.

## 5. check_model / run / post-processing evidence

- check_model: 0 errors. 105 warnings are native to the shipped inputs (88 CHD + 17 WEL boundary cells on inactive cells);
  the shipped solved run used the same configuration (documented, no action taken — consistent with “clean (or documented)”).
- Run: “Normal termination of simulation.” Elapsed 33.394 s (listing tail via get_run_log). diagnose_convergence: converged.
- Water balance: |discrepancy| = 1.6e−5 % → closes. Not boundary-dominated (SFR share 49.98 %).
- Outputs: `work\nvsink_base_heads_layer1.png`, `work\nvsink_base_heads_layer4.png` (head maps, layers 1 and 4),
  `work\nvsink_base_water_balance.csv`, `work\nvsink_base\nvsink_base_report.md`, head arrays `.npy` in `work\nvsink_base\`.
  *(Image preview unavailable to this model; PNGs written to disk are the deliverables.)*

## 6. Calibration — capability gap (STOPPED per instructions, no workaround)

Target observation set was derived and fully documented (§6a) but **could not be registered**, so the PEST chain
(setup_calibration/setup_pest_control → pestpp-glm/ies → summarise_calibration) **could not be run**.

Attempted, all failing identically:
- `import_obs_from_csv` on the modifiable clone `nvsink_cal` and on read-only `nvsink_base`; layer 0 and 3; with and without
  x/y coordinate columns; one site and many sites; with/without date column; default and explicit column names.
  **Error every time:** `OBS_IMPORT_FAILED — 'list' object has no attribute 'lower'`. It fails before the read-only gate
  (read-only clone returns the same error, not MODEL_ADOPTED_READONLY) and is independent of CSV contents.
  Root cause (from observable behaviour only): the adopted model ships with a continuous OBS6 package (857 HEAD records);
  every obs-related introspection of this package is broken (export_model_spec also dies on an obs name, `'sv_193'`).
  MCP tooling offers no other way to register observation targets (no import alternative, no obs-package removal tool).
- `setup_calibration` then refuses: `obs_source='model' requires observation targets registered via import_obs_from_csv.
  No 'observations' entry found in .gwmcp_meta.json for this model.`
- `setup_pest_control` (obs_source='explicit') requires pre-existing template + instruction files; under MCP-only rules the
  only generator of those files (setup_calibration) is gated on the same broken import step. No .pst can therefore be produced.

**Missing capability:** `import_obs_from_csv` (and, consequently, `compare_to_observed`, `read_simulated_observations`,
`setup_calibration`, the `calibrate` chain, and PEST template/instruction generation) is unusable on models adopted from
shipped MF6 input sets that already contain a continuous OBS6 package. The bug is internal to the MCP server and not
bypassable with legal inputs.

Per the task instructions I did **not** work around this with raw flopy/pyemu or hand-written PEST files, so **no calibrated
parameter estimates or calibrated-vs-reference head deltas are reported**. The chain remains unexercised beyond the setup gate.

### 6a. Documented observation set (prepared, ready to import)

Derived from field data in `processed_data\` for **all 448 sites** of the model's shipped obs network
(parsed from `neversink.obs`: 857 HEAD records, sites screened across layers 1–4):
- 447 sites joined to `NY_DEC_GW_sites.csv` by `obsnme` → observed head = `gw_elev_m` (land-surface elevation from DEM minus
  recorded depth to water, m NAVD88-equivalent; single static level per well-completion record).
- 1 site (`414525074360601`, USGS Sv-535 Woodbourne) joined to `NWIS_GW_DV_data.csv` + sites → `gw_elev_m` 357.182 m
  (2005–2020 mean of a continuous NWIS record).
- Output: `work\neversink_head_observations.csv` (site, value, x, y, source); values 59.3–655.2 m (mean 341.1 m).

Fit of the **native (reference) solution** to this field set (shipped obs output, positional record mapping):
- All 857 obs records: RMSE 38.9 m, bias (sim−obs) +23.4 m, median +15.6 m; 575/857 within ±25 m, 292 within ±10 m.
- Per-site (deepest record, n=448): RMSE 40.2 m, bias +24.4 m; per-site (shallowest record): RMSE 40.5 m, bias +24.7 m.
- The one continuous NWIS well fits well: sim−obs = +1.5 m (L1/L2) to +2.7 m (L4).
- Interpretation (documented for the log): the DEC column is a **static, drilling-era depth-to-water**; many upland/bedrock
  wells show water levels tens to hundreds of metres below the modelled regional steady-state water table, so the bulk DEC
  set is not a coherent target for this 2011 steady-state model (large positive bias, outliers). The NWIS well is coherent.
  A defensible calibration would therefore have needed either a physically filtered DEC subset or reference-derived
  pseudo-observations; both were moot once obs registration itself failed.

## 7. Session artefacts

- `work\neversink_head_observations.csv` — documented field observation set (448 sites).
- `work\nvsink_base\` — clone model dir: run outputs `.hds/.cbc/.lst`, `neversink.head.obs` (regenerated),
  `nvsink_base_heads_l0_k0_0.npy`, `nvsink_base_heads_l3_k0_0.npy`, `nvsink_base_report.md`.
- `work\nvsink_base_heads_layer1.png`, `work\nvsink_base_heads_layer4.png`, `work\nvsink_base_water_balance.csv`.
- `work\nvsink_cal\` — modifiable calibration clone (CRS EPSG:26918 set; no calibration artifacts generated).
- Registry / workspaces: adopted `neversink` (read-only, shipped dir untouched), `nvsink_base`, `nvsink_cal`.

## 8. Bottom line

Success criteria: (1) stack ✓, (2) adopt ✓, (3) check_model ✓ (documented inherited warnings), (4) run_simulation ✓
(converged, normal termination, matches shipped listings), (5) post-process ✓ (heads, closing budget, maps),
(6) calibration ✗ — **blocked by an MCP-server defect in `import_obs_from_csv` on models that ship with a continuous
OBS6 package**; reported per instructions instead of working around with raw pyemu/flopy. Reference comparison ✓ for the
native run; no calibrated run to compare.
