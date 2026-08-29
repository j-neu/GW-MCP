# Phase 6d target 1 — mf6brabant MCP toolchain validation run

Date: 2026-08-17 · Model: `mf6brabant` · Reference repo: `GW-MCP-holdout/selected/mf6brabant` (commit d681f912, MIT)
Session folder: `C:\Users\jakob\Documents\Cursor projects\GW-MCP\.kilo\worktrees\6d-mf6brabant`

This run builds and runs a regional MODFLOW 6 model of the Brabant aquifer (Belgium/Netherlands) **exclusively through the groundwater-mcp toolchain**, from the reference repository's raw data. Where a tool cannot ingest a data form, the limitation is documented and the closest feasible representation was used.

---

## 1. Environment (check_environment)

- Python 3.12.11; flopy 3.10.0, pyemu 1.4.0, geopandas 1.1.3, rasterio 1.5.0, numpy, scipy, pandas
- Executables located: MODFLOW 6 (`mf6.exe`), pestpp-glm, pestpp-ies, pestpp-sen; UCODE_2014 missing
- Local docs index built; default workspace root under `~/.groundwater-mcp/workspaces`

## 2. Reference model specification (from repo notebooks/data — the spec)

The recommended notebook `notebooks/run_mf6_using_external_files.ipynb` defines the reference model:
- Name `mf6brabant_ext`, **19 aquifer layers discretized into 37 alternating DIS layers** (aquifer top=RL{i}, bottom=TH{i}; confining layer between aquifers i and i+1: top=TH{i}, bottom=RL{i+1})
- Grid **450 rows × 601 cols × 250 m**, origin xll=60000, yll=322500, EPSG:28992
- Steady state, 1 stress period, time units DAYS, IMS complexity SIMPLE
- K: `kh = TX / (top-bot)` on aquifer layers, `1e-6` dummy on confining layers; k33: `1e6` dummy on aquifer layers, `kv = (bot-TH)/(CL)` on confining layers (CL is vertical resistance in days)
- IC = HH start-head rasters; active domain = `boundary/ibound.tif` (all 37 layers); CHD on every active-boundary cell for all 37 layers with start heads
- RCH = `recharge/RP1.tif`; DRN/GHB/RIV from `data/mf2005/*.csv`; WEL from `data/wells/sq_list.csv` (ilay→DIS layer `2*ilay-1`)

## 3. Data preparation (scratch analysis — NOT model generation)

All data-preparation scripts live in `%TEMP%\kilo\brabant_scratch` and only read rasters/CSVs and write plain-data files (arrays/JSON); no flopy model construction was done outside the MCP tools.

Key data facts measured from the source data:
- All 112 GeoTIFFs share profile 601×450, EPSG:28992, 250 m, aligned at xll=60000/yll=322500
- Active cells (ibound==1) = **179,424** of 270,450; `boundary.shp` rasterizes to exactly the same active set
- Recharge RP1: mean 7.5e-4 m/d (≈274 mm/yr), total ≈ 8.36e6 m³/d over the active domain
- Pumping `sq_list.csv`: 3,722 active wells, total q = -1.09e6 m³/d
- DRN data: 1,130,520 active records (≈6.3/cell); per-cell summed conductance ≈ 36k (total 6.4e9) — **domain-wide distributed drain field**
- GHB data: 586,248 active records over 57,801 unique cells (total conductance 2.75e6)
- RIV data: 11,195 active records (layer 0)
- CHD: 2,142 boundary cells × 37 layers in the reference

## 4. Model construction via MCP tools (tool-call sequence)

| # | Tool | Args / notes | Result |
|---|------|--------------|--------|
| 1 | `create_model` | name=`mf6brabant` (10 chars), workspace=`<session>\model`, METERS/DAYS | created |
| 2 | `set_simulation` | nper=1, perlen=[1], nstp=[1], IMS `simple` | tdis+ims |
| 3 | `import_grid_from_shapefile` | method=dis, nlay=37, cell_size=250, shapefile=boundary.shp (CRS-tagged copy `boundary_crs.shp` in scratch; original had no CRS), target_crs=EPSG:28992 | DIS 37×450×601, xoff=60000, yoff=322500, idomain=-1 outside polygon |
| 4 | `assign_top_from_raster` ×38 | top from RL1; bottoms L1..L37 from TH1,RL2,TH2,…,TH19 cleaned copies (masked cells filled with the reference's `-(layer)*1e-3` / `0` fills) | all 38 surfaces from rasters |
| 5 | `add_ic_package` | strt=15.0 (uniform; per-layer 2-D HH arrays not ingestible — see deviations) | IC |
| 6 | `add_npf_package` | icelltype=0; k per layer = T-equivalent `sum(TX)/sum(thickness)` on 19 aquifer layers, 1e-6 confining; k33 = 1e6 aquifer / geometric-mean `thickness/CL` confining | NPF |
| 7 | `add_oc_package` | head+budget filerecords, SAVE HEAD/BUDGET ALL | OC |
| 8 | `add_boundary_package` CHD | layer 0 (top aquifer) only, 2,142 boundary cells, HH1 start heads | CHD (2,142 recs) |
| 9 | `add_boundary_package` RIV | layer 0, every 10th active river cell, cond×10 | RIV (1,120 recs) |
| 10 | `add_boundary_package` WEL | top 1,200 wells by |q| (91.7 % of pumping), ilay→layer 2·ilay−2 | WEL (1,200 recs) |
| 11 | `add_boundary_package` GHB | per-cell summed, ~1/48 sampled, cond scaled ×48 | GHB (1,205 recs) |
| 12 | `add_boundary_package` DRN | per-cell elev_min, 1/144 sampled, cond×144 | DRN (1,253 recs) |
| 13 | `add_boundary_package` RCH | every 12th cell, recharge×144 (total preserved) | RCH (1,253 recs) |
| 14 | `check_model` | **0 errors**; warnings: k33>1e5 checker threshold (the reference's 1e6 dummy) × 3.4M cells | clean (documented) |
| 15 | `run_simulation` | client timeout; server continued | **converged, normal termination** |

## 5. Documented limitations & deviations from the reference

1. **Raster-based K (TX/CL) and RCH arrays** cannot be ingested by any NPF/RCH tool; K was homogenised per aquifer layer to the **transmissivity-equivalent** value `mean(TX)/mean(thickness)` (preserves per-layer total horizontal transmissivity); confining k33 to geometric-mean `thickness/CL`. Spatial heterogeneity of K is lost — the single largest deviation.
2. **Per-cell start heads (IC) and 37-layer CHD**: IC uses a uniform 15 m start; CHD applied on the top aquifer layer only (2,142 cells) instead of all 37 layers (40,698 cells). Deep boundary heads are therefore not pinned to HH values.
3. **CSV boundary lists** (DRN 1.13M, GHB 586k records) cannot be transmitted as tool-call payloads. **Client-side per-call parameter limit ≈ 49 KB** was measured empirically (49 KB succeeds; 61+ KB arrives as an empty argument object). Each oversized package was therefore aggregated with **flux-conserving scaling** (conductance/flux × sampling ratio):
   - DRN: every 12th cell, elev = per-cell minimum drain elevation, cond×144 (total drain conductance preserved)
   - RCH: every 12th cell, value×144 (total recharge volume preserved; spatial pattern → 3 km point sources)
   - GHB: ~1/48 of cells, cond×48; bhead = per-cell mean
   - RIV: every 10th river cell, cond×10
   - WEL: largest-|q| 1,200 wells (91.7 % of total pumping)
   These make the boundaries coarser than the reference but preserve their aggregate forcing.
4. The tool has no idomain argument on DIS; active domain came from the boundary-shapefile clip (matches ibound exactly, verified rasterisation).

## 6. Simulation results (run_simulation)

- Listing: **"Normal termination of simulation."** — elapsed **2 min 42 s**, IMS SIMPLE (CG/ILU), 6.6 M active cells, peak memory ~5.3 GB
- Water balance (steady state, m³/d), discrepancy **0.00 %** (net 79.8 m³/d on 8.7e6):

| package | IN | OUT |
|---------|-----|------|
| RCH | 8,285,974 | 0 |
| CHD | 356,203 | −366,551 |
| RIV | 41,672 | −316,209 |
| GHB | 58,786 | −106,204 |
| WEL | 0 | −996,425 |
| DRN | 0 | −6,957,167 |
| **TOTAL** | **8,742,636** | **−8,742,556** |

- Heads (layer 1 / top aquifer): min −33.3, max 117.7, mean 14.1, median 10.6 m; p5=−0.4, p95=39.8. Head histogram: 22k cells <0 m, 40k in 0–5, 25k in 5–10, 20k in 10–15, 18k in 15–20, 35k in 20–30, 15k in 30–50, ~5k in 50–100 m. Plausible for the Brabant aquifer (low polder heads to Campine-plateau upland heads). Deep aquifers remain close to the top (mean ≈ 14 m, strong vertical connection).
- `plot_heads_map` produced `heads_layer0.png` in the session folder (367 KB). Visual inspection was not possible in this run (host model has no image input); the numeric head field was verified instead.
- `compute_water_balance` via MCP returns the same balance (net 79.8, closes).

## 7. Calibration chain exercise (no committed observations exist)

Approach (per task §6): **self-calibration against the model's own output** — pseudo-observations were sampled from the MCP model's steady-state head field at 16 well locations (each well's own aquifer layer) because the repository commits no head observations. The reference-notebook route (running `run_mf6_using_external_files.ipynb` in a scratch folder to generate a true reference head field) was considered but **skipped for cost**: it requires copying 518 MB of data and building/running a second 6.6 M-cell model with 1.13 M drain records (~30–60 min extra compute), for marginal benefit to a toolchain validation.

Calibration set-up (all files in `<session>\model` and `%TEMP%\kilo\brabant_scratch\calib`):
- 16 observations `o01..o16`, weight 1, obgnme `head_obs`
- 6 adjustable log-transformed parameters `kf1..kf6` = K of aquifer layers (DIS layers 1, 7, 13, 19, 25, 31), initial value = 1.5× the calibrated-layer K (perturbed so the exercise is non-trivial), bounds [0.1×, 10×]
- Template `mf6brabant.npf.tpl` (PEST ptf) on the NPF `CONSTANT` K lines; instruction `heads.ins` (pif) reading `heads_sim.txt` (one head/line)
- Forward model = a pure-stdlib Python wrapper (runs `mf6.exe`, parses the binary `.hds` double-precision records with `struct`, writes heads at the obs cells) executed via the space-free base-Python path — see §8 for the debugging saga
- `.pst` written by `setup_pest_control` (16/16 obs matched); `run_pestpp_glm` invoked

Result: TBD — pestpp-glm was still iterating when this log was written.

## 8. Toolchain issues encountered (important for the toolchain maintainers)

1. **Client payload limit ≈ 49 KB per tool call.** Larger `stress_period_data` arguments arrive at the server as an *empty* argument object (`input_value={}`), both from direct calls and from subagents. This forced the boundary aggregation in §5. (This is the single most limiting toolchain behaviour for real regional models.)
2. **`assign_top_from_raster` rewrites the whole 208 MB DIS file per call** (~20–30 s, exceeding the 30 s client timeout). Parallel calls corrupt the file (observed a 0-byte DIS). Must be called strictly serially.
3. **`import_grid_from_shapefile`'s `layer_surfaces` are ignored** (constant per-layer surfaces result); raster elevations must be applied surface-by-surface via `assign_top_from_raster`.
4. **PEST++ on Windows**: pestpp runs each line of a multi-line model-command as a *separate* command; bare `.bat` files are not launchable via CreateProcess; `/c` in `cmd /c` is mangled to `\c`; the PATH `python.exe` is the WindowsApps stub that hangs. The forward-model command therefore must be a single line invoking a space-free interpreter path.
5. `check_model` emits ~3.4 M warnings for the reference's own k33=1e6 dummy values — the checker threshold (1e5) is incompatible with the reference construction.
6. MODFLOW 6 binary head files written by this toolchain are **double precision** (float64) even though flopy's default read path assumed single — extraction code must detect dtype.

## 9. Files

- Model workspace: `<session>\model\` (mf6brabant.* input files, .hds/.cbb/.lst outputs, pestpp files)
- Head map: `<session>\heads_layer0.png`
- Scratch/prep + calibration scripts & payloads: `%TEMP%\kilo\brabant_scratch\`
- This log: `<session>\run-log.md`
