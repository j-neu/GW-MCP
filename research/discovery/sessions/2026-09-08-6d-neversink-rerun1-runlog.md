# Run Log — Phase 6d target 6 (neversink_workflow) — RERUN-1 (import_obs_from_csv defect-fix)

Date: 2026-09-08. Mode: closed-book MCP validation. All model build/adopt/run/postprocess/calibrate actions went through `groundwater-mcp` tools only. Python was used solely for (a) reading shipped reference artifacts/listings/CSVs, and (b) preparing observation CSV tables. No flopy/pyemu MODFLOW or PEST modelling calls, and no hand-editing of MODFLOW or PEST files.

Dataset: `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\` (DOI-USGS/neversink_workflow). Runnable model: `neversink_mf6\` (shipped mfsim.nam + package files + solved listings). This run re-validates after an MCP defect fix: `import_obs_from_csv` no longer fails on a model that ships a continuous OBS6 package.

---

## 1. Environment (criterion 1)

`check_environment`: OK. Python 3.12.11, flopy 3.10.0, pyemu 1.4.0, geopandas/rasterio present; MODFLOW 6 executable located (`~/.local/bin/mf6.exe`); PEST++ (pestpp-glm/ies) located.

## 2. Model facts established from shipped files (reference specification)

- Single-GWF steady-state MODFLOW 6 model `neversink`: DIS 4 layers × 680 rows × 619 cols @ 50 m (EPSG:5070 Conus Albers; XORIGIN 1,742,950, YORIGIN 2,258,285), 1,683,680 user cells.
- **Solution-node count = 300,236** (idomain = +1 only). The run brief's "843k active" does not match the shipped idomain arrays; the shipped listing itself reports `NUMBER OF NODES IN SOLUTION: 300,236`. Layer-active counts (idomain>0): L1 85,051; L2 13,787; L3 11,700; L4 189,698. Layers 1–2 also contain idomain=−1 cells (72,323 / 74,729) which MF6 excludes from the solution.
- Packages: DIS, IC, NPF (icelltype=1, k external per-layer k0–k3.dat, k33 external per-layer k330–333.dat), RCHA (irch.dat + rch_000.dat), OC, WEL_0, CHD_0, SFR_0 (with SFR downstream-flow obs on reaches 6700/11127), and an OBS6 continuous head package (`neversink.obs`, FILEOUT `neversink.head.obs`) at 857 (site, layer, cell) records across 448 wells (USGS site 414525074360601 + 447 NY-DEC wells in Orange/Sullivan/Ulster counties).
- Reference hydrology (shipped `mfsim.lst`): normal termination; reference run time ~45 s (2021 hardware). No binary `.hds/.cbb` shipped.
- Observation CSVs in `processed_data\`: `NY_DEC_GW_sites.csv` (449 site rows incl. `obsnme`, `gw_elev_m`, x/y in EPSG:5070), `NWIS_GW_DV_data.csv` (1 USGS summary record: mean GW elevation 357.18 m), streamgage statistics files.

## 3. Adoption (criterion 2)

`adopt_model` name = `neversink` (≤16 chars), workspace = `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6`, `allow_modify=True` (needed for obs registration and calibration artifacts). No grid rebuild, no file renames; the shipped files ARE the model. Adoption is read-only by default, so modification was explicitly enabled for this calibration workflow; check/run/postprocess are allowed on read-only adoptions, but import_obs_from_csv + calibration need writes.

## 4. Model check (criterion 3)

`check_model`: 0 errors; warnings = 105 "boundary condition in inactive cell" (88 CHD + 17 WEL). These warnings ship with the reference model (same cells are active/inactive in the solved reference); they do not prevent normal termination. Documented, not introduced by this run.

## 5. Simulation run (criterion 4)

- `run_simulation`: converged / **normal termination**, elapsed ~27–30 s. Re-run later (post-calibration state) also normal (23.8 s). Listing warnings are only MF6 deprecations (UNIT_CONVERSION in sfr, OUTER_HCLOSE→DVCLOSE etc.) — same set as the shipped reference listing.
- `get_run_log`: normal termination confirmed.

## 6. Post-processing (criterion 5)

- `read_heads` L0 (kstpkper 0,0): min 88.1 / max 631.2 / mean 361.5 m. L3 (index 3): min 85.7 / max 723.6 / mean 355.8 m. Layer arrays also written to `neversink_heads_l0_k0_0.npy` / `_l3_`.
- `compute_water_balance` (0,0): IN 523,363.25 m³/d (RCHA 489,968; CHD 10,607; SFR 22,788); OUT −523,363.34 m³/d (SFR −500,318; CHD −13,164; WEL −9,881); **net −0.082 m³/d** → closes (<0.0001 % discrepancy). SFR is the dominant outflow and RCHA the dominant inflow, as expected for this recharge-fed stream-drained watershed model.
- `plot_heads_map` L0 → PNG saved to `neversink_layer0_heads.png` (viewable in GIS; image not renderable inline by this session model).

## 7. Observation set for calibration (criterion 6, documented decision)

The shipped solved model's head obs define 857 (site, layer, cell) targets at 448 wells. Field *head* values are only partially staged: `NY_DEC_GW_sites.csv` contains a derived `gw_elev_m` per DEC well, but diagnostics show those values sit ~24 m below the solved heads on average (measured-depth column includes non-water-level entries, e.g. 1000 ft), while the reference model's simulated water table is near land surface in its shallow active cells — i.e., the DEC field values are not a consistent direct head target for this steady-state model. The single clean staged field value is the USGS site 414525074360601 mean GW elevation 357.18 m (matching its shipped obs cell within ~1.5 m at L1 / 2.7 m at L4).

**Decision (documented):** primary targets = reference-derived pseudo-observations at all shipped (site, layer=4, cell) obs cells (values = shipped solved heads from `neversink.head.obs`), i.e., calibrating back toward the native-parameter reference solution; plus the genuine USGS/NWIS field water-level value as one independent target. This follows the run instruction's "reference-derived pseudo-observations from the shipped solved listings" path, with the field value included where real data exist.

Toolchain constraint discovered during registration: `import_obs_from_csv` **replaces** the model's OBS6 continuous package with the imported set (one layer per call; successive calls overwrite, they do not merge). A multi-layer obs set is therefore not registerable in one model; all sites were registered in **layer 4** (every one of the 448 wells has a shipped obs there — deepest, most complete coverage). Obs names made unique per (site, layer) as `<SITE>_L4` (≤20 chars). Layer-4 import = 448 targets + 1 USGS field target (`USGS414525074360601F`) → **449 registered HEAD targets** at layer 4.

Verification: site→cell mapping lands exactly on the shipped obs cells (0-based), e.g. `SV700_L4`→cell [3,480,259] = shipped `sv700 HEAD 4 481 260`; `414525074360601_L4`→[3,210,173].

The shipped SFR streamflow obs (2 gages) were retained in the SFR package but are not PEST targets: the import/obs-CSV machinery (obs_source="model") reads the GWF head obs CSV; SFR reach `downstream-flow` obs are a separate mechanism. This is documented as a deviation/limitation; the SFR obs values are reported in post-calibration runs via the model's own `neversink.sfr.obs.output.csv`.

Reference fit at the 449 registered targets (run with shipped/zoned K): RMSE 0.129 m, bias −0.006 m, R² 0.999998 — the 448 pseudo-obs reproduce to ~1e-8 (bit-identical re-run of the shipped solution) and the single field USGS target shows residual −2.74 m (simulated 359.92 vs field 357.18 m). This is the **reference comparison baseline**.

## 8. Calibration (criterion 6 — result and capability findings)

Parameterisation design constraint discovered: `setup_calibration` supports only `target: "npf:k"` (confirmed: target `rcha:recharge` rejected, supported = `['npf:k']`), and it rewires NPF k to one consolidated external array (`neversink_k.dat`, 1,683,680 lines) whose **every cell must carry a parameter token** (whole-scope tokenisation; leaving cells at their zoned values is refused). A `layer`-scoped parameter therefore replaces a layer's k field by a **single uniform value** during PEST runs. There is no multiplier/zonation-preserving option.

Attempts (all via MCP chain; setup_calibration → start_calibration/run_pestpp_glm → summarise_calibration intended):
1. 4 layer-K params, initials = layer geometric means (0.654 / 0.597 / 20.63 / 0.1676 m/d). Forward runs under PEST did not converge; listing showed persistent solver residual at the same SFR-coupled cell (1,249,182), outer iterations climbing past 90.
2. 4 layer-K params, initials = dominant per-layer values (0.1676 / 0.0503 / 22.86 / 0.1676). Base forward run: premature termination ("Simulation convergence failure occurred 1 time(s)").
3. Diagnostics: the reference k field is strongly zoned *within* shallow layers (L0: 61,118 cells at 0.1676 m/d till + high-K valley-fill up to 60.96 m/d; L1 similar). The failing cell (layer 1, row 249, col 182) has reference L0 above it = 45.72 m/d (valley-fill conduit). Replacing the intra-layer conductors with any uniform value removes the conduit that keeps the SFR-connected Newton solve balanced → persistent mass-balance residual (~10³ m³/d) at that cell, so no uniform-per-layer configuration converges reliably.
4. 4 layer-K params, initials = arithmetic means (8.97 / 12.25 / 21.67 / 0.1676). Base run DOES converge (23.8 s), but Jacobian perturbation runs (PEST perturbs the shallow-layer uniform k) intermittently stall for minutes with the same residual signature → GLM ground extremely slowly (a 4-parameter Jacobian did not complete in ~25 min on the earlier attempt).
5. Final bounded attempt (noptmax=1, arithmetic-mean initials): PEST++-GLM base + Jacobian runs in progress at time of writing; some perturbation runs converge in ~24 s, others stall (see §9 for outcome).

Root-cause summary (documented capability gap): the MCP calibration parameterisation supports only whole-scope uniform tokenisation of `npf:k`. For this particular model, the shallow-layer K field is zoned with hydraulic conductors that are numerically load-bearing (SFR/Newton coupling); no uniform-per-layer representation is stable, so a K calibration of the full model through the MCP chain is not achievable. What the chain needs to calibrate this model class is a multiplicative/zoned parameterisation (e.g., zone-factor or template that preserves the base field pattern). No workaround was attempted outside the MCP tools (as required).

## 9. Outcome of the final calibration attempt

Bounded final attempt: 4 layer-K parameters, initials = layer arithmetic means (8.97 / 12.25 / 21.67 / 0.1676 m/d), noptmax=1, engine PEST++-GLM. Observed behaviour:

- Base (initial-parameter) forward run converges normally (~24 s). Observation fit at the base set: **RMSE 15.15 m**, bias +7.85 m, R² 0.976 (449 targets). Residuals are not random: the largest are the Ulster County (U-prefix) wells in layer 4 (up to ~80 m) — a single uniform deep K cannot reproduce the zoned reference heads that generated the pseudo-observations.
- GLM Jacobian + parameter-upgrade trial runs: some converge in ~24 s, but any trial that moves the shallow-layer uniform K away from the arithmetic-mean base (e.g., the GLM upgrade search moved k_ly2 toward its 216.7 m/d upper bound and k_ly0 toward its 0.897 lower bound; see `neversink.upg.csv` trial table) produces forward runs that do not converge — the persistent solver residual appears at the same SFR-coupled cell (layer 1, row 249, col 182) whose reference overlying K (L0 = 45.72 m/d valley-fill) was removed by uniformisation.
- After 31 min the run had not completed a single clean GLM iteration (no phi row in `.iobj`), so it was cancelled (no phi improvement available to report). GLM did emit a linearised parameter-uncertainty summary (`neversink.0.par.usum.csv`, log10 units): k_ly0 stdev 0.046, k_ly1 0.19, k_ly2 0.14, **k_ly3 0.0027** — the deep uniform layer-4 K is the only parameter that is well identified by layer-4 head targets; the shallow-layer parameters are poorly constrained and destabilising to perturb.

**Calibration verdict:** through the MCP calibration chain, no full K calibration of this model completes, for a documented structural reason: the chain parameterises `npf:k` only by whole-scope uniform replacement (target `rcha:recharge` and partial-cell coverage are rejected; supported target set = `["npf:k"]`), and the Neversink shallow-layer K field is strongly zoned with numerically load-bearing valley-fill conductors. Under a uniform-per-layer K the SFR/Newton solve stalls at a persistent mass-balance residual (~10³ m³/d at cell (1,249,182)) for every initial-value strategy tried (mode, geometric mean, arithmetic mean) once parameters are perturbed. A multiplier- or zonation-preserving parameterisation would be required to calibrate this model class; that capability is missing from the toolchain. Per the run's MCP-only rule, no flopy/pyemu workaround was attempted.

**Reference comparison:** the strongest validation result is the reference reproduction itself. With the shipped (zoned) K configuration and the registered 449-target obs set, the MCP-run model converges normally and matches the shipped solved listing to ~1e-8: observation fit RMSE **0.129 m**, R² 0.999998; the single genuine field target (USGS 414525074360601, mean NWIS GW elevation 357.18 m) shows residual −2.74 m (simulated L4 head 359.92 m). Water balance closes to −0.08 m³/d on ~523,363 m³/d throughput. In contrast, the uniform-K calibration base run degrades fit to RMSE 15.2 m (water balance still closes, net −0.56 m³/d), consistent with the structural simplification, and GLM could not improve on it because its parameter moves make forward runs non-convergent.

## 10 (final). End-state of the workspace

The model remains registered as `neversink` and runnable. As a result of the calibration chain the on-disk NPF now references a consolidated external array `neversink_k.dat` (currently the uniform arithmetic-mean K values; runnable and convergent) instead of the original per-layer OPEN/CLOSE `k0.dat…k3.dat`; the pristine array files `k0–k3.dat`, `k330–333.dat`, `top.dat`, `botm_*.dat`, `idomain_*.dat`, `rch_000.dat` are unchanged on disk. The shipped model can be restored to its exact original layout by re-staging the pristine input set (only control files and the obs file differ; array content files are intact). Registered observation artifacts: `neversink.obs` (449 HEAD obs), `neversink_obs_summary.csv`, and, for calibration, `neversink.pst`, `neversink_k.dat.tpl`, `neversink_head.obs.csv.ins`, plus PEST++ outputs (`neversink.upg.csv`, `neversink.0.par.usum.csv`, logs) from the attempts described above.

## 11. Summary against success criteria

1. `check_environment` ✓ (stack reported above).
2. `adopt_model` ✓ — model `neversink` adopted from the shipped `neversink_mf6` workspace; runnable through MCP tools.
3. `check_model` ✓ — 0 errors; 105 shipped warnings (BCs in inactive cells) documented.
4. `run_simulation` ✓ — converged / normal termination (~24–30 s); listing confirms.
5. Postprocess ✓ — `read_heads`, `compute_water_balance` (closes to −0.08 m³/d on the reference run), `plot_heads_map` (PNG saved).
6. Calibration — obs set registered and documented (449 targets: 448 layer-4 reference-derived pseudo-observations at the model's own shipped obs cells + 1 genuine USGS/NWIS field water level); reference reproduced to RMSE 0.129 m. Full PEST calibration does not complete through the MCP chain for the documented parameterisation limitation above; attempts, evidence, and partial PEST++ artifacts are recorded here.
7. `run-log.md` ✓ — this file.

## 12. Provenance notes (appendix)

- Observed registration: `neversink.obs` now holds the 449 continuous HEAD obs (FILEOUT `neversink_head.obs.csv`); summary at `neversink_obs_summary.csv`. Shipped obs `neversink.head.obs` (reference output) is overwritten by model runs; shipped `neversink.obs` content is replaced (deviation, documented above).
- `setup_calibration` produced `neversink.pst`, `neversink_k.dat.tpl`, `neversink_k.dat`, `neversink_head.obs.csv.ins` and a Python forward wrapper (temp dir). NPF now reads consolidated `neversink_k.dat` rather than the original per-layer OPEN/CLOSE k0–k3.dat (deviation introduced by the calibration chain; the pristine k0–k3.dat array files remain untouched on disk).
- All number-of-cells/runtime statements above are consistent with the shipped reference listings and our re-runs.
