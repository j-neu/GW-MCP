# Discovery session log — USGS ModelMuse tutorials

- Date: 2026-08-15
- Playbook: `research/discovery/playbooks/usgs-modelmuse-tutorials.md`
- Target source: USGS ModelMuse tutorial pages
- Client: **playwright MCP browser NOT available** (registered but needs a Kilo client restart) — this session used the playbook fallback path (`webfetch` + `websearch` on the same target sites). **Browser verification of the listed URLs is PENDING** per playbook; re-verify the help pages render and the download links resolve in the browser session.

## BROWSER VERIFICATION — COMPLETE (2026-08-15, playwright MCP after Kilo restart)

All URLs below re-verified in the browser (page loads + link targets confirmed):

- `Help/examples.html` — loads ("Examples/Tutorials"); links: PHAST/MODFLOW/SUTRA/PEST Examples; examples installed at `C:\Users\Public\Documents\ModelMuse Examples\examples` per the page.
- `Help/modflow_examples.html` — loads; confirms all MODFLOW 6 example links:
  `modflow_6_example.html`, `modflow-6-unsaturated-flow-wit.html`,
  `modflow-6-transfer-of-solute-a.html`, `modflow-6-transfer-of-solutes-.html` (LAK/SFR/CNC), plus Subsidence and ATES pages not yet catalogued.
- **`pest_examples.htm` → 404** ("Object not found!"). Correct URL is
  `pest_examples.html` — catalog row fixed.
- Downloads page `water.usgs.gov/water-resources/software/ModelMuse/` — loads;
  Current Version **5.4.0.0**; direct zip:
  `https://water.usgs.gov/water-resources/software/ModelMuse/ModelMuse64_5_4.zip`
  (78 MB, 64-bit); installer `ModelMuseSetup64_5_4.exe` (68 MB). Catalog's
  download URL stands; direct zip URL added to the MODFLOW 6 Example row.

## URL movement / fallback notes

- `https://water.usgs.gov/ogw/modelmuse/tutorials.html` → **404 Not Found** (old tutorials index is gone).
- `https://water.usgs.gov/nrp/gwsoftware/ModelMuse/` → **403 Forbidden** (bot-guarded directory).
- `https://www.usgs.gov/software/modelmuse` and `.../modelmuse-graphical-user-interface-groundwater-models` → **404**; the current USGS software page is `https://www.usgs.gov/software/modelmuse-a-graphical-user-interface-groundwater-models` (websearch-verified, last updated 2025-06-24).
- Current tutorials location: the **ModelMuse Help "Examples/Tutorials" section** at `https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/examples.html` → `modflow_examples.html` (HTML step-by-step tutorials, not PDFs). Example project files (`.gpt`, `.gpb`, shapefiles) ship inside the ModelMuse distribution zip/installer (`C:\Users\Public\Documents\ModelMuse Examples\examples`).
- ModelMuse Downloads (distribution zip incl. examples): `https://water.usgs.gov/water-resources/software/ModelMuse/` (current release v5.4.0.0; 64-bit zip ~71–78 MB, installer ~65–68 MB).
- Video tutorials (Flash-era, partially converted): `https://www.usgs.gov/mission-areas/water-resources/modelmuse-tutorial-videos-0` and `https://water.usgs.gov/nrp/gwsoftware/ModelMuse/ModelMuseVideos.html`.

## Topic coverage found (MODFLOW Examples list)

Example Model, Simple Model, Rocky Mountain Arsenal (RMA), Water Supply Problem, Cross Sectional Model, **MODFLOW 6 Example** (CHD, RCH, MAW, MVR, SFR, UZF; includes DISV quadtree run step), MT3D-USGS Contaminant Treatment System, MT3D-USGS Stream and Lake Transport, **MODFLOW 6 Subsidence Example**, **MODFLOW 6 Unsaturated Flow with Solute Transport**, **MODFLOW 6 Transfer of Solute Among Multiaquifer Wells**, **MODFLOW 6 Aquifer Thermal Energy Storage**, **MODFLOW 6 Transfer of Solutes Between Streams and Lakes (LAK/SFR/CNC)**, plus PEST Examples (MODFLOW 6 / MODFLOW-2005 / SUTRA, RMA-based, head+flow observations, parameters).

## Grid-type notes (matrix gaps)

- **DISV**: supported in ModelMuse as quadtree-refined DISV only (`Help/discretization_with_vertices_d.html`; max refinement level 6); covered inside the MODFLOW 6 Example, no standalone DISV tutorial.
- **DISU**: NOT supported by ModelMuse — no DISU tutorials exist for this source (gap; DISU stays an Aquaveo/USG-source row).
- **SWT**: not covered; variable-density problems are done via GWT hydraulic-head formulation (no SWT-package tutorial found).
- **GNC**: not covered (MODFLOW 6 handles the USG ghost-node concept internally; no GNC tutorial).
- ModelMuse supports UCODE (MODFLOW-2005/NWT) and PEST (MODFLOW 6/SUTRA) parameter estimation; the PEST Examples cover MODFLOW 6. PEST++ is not used in these tutorials.

## Catalog rows (for append under `USGS ModelMuse tutorials` in `research/discovery/catalog.md`)

| name | source | url | type | capabilities showcased | toolchain | input format | data formats | license | accessibility | download url | size | calibration-ready | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MODFLOW 6 Example | USGS ModelMuse Help (Examples/Tutorials) | https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/modflow_6_example.html | HTML step-by-step tutorial + ModelMuse project (installed with distribution) | DIS, DISV, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD, RCH), MAW, UZF, MVR, output, water-balance, plots | ModelMuse 5.4 + MODFLOW 6, ZONEBUDGET, MODPATH | ModelMuse .gpt project; exports MODFLOW 6 text input | .gpt, shapefiles, MF6 text input (nam/dis/npf/...) | USGS public domain — verify | Direct download, no registration | https://water.usgs.gov/water-resources/software/ModelMuse/ (distribution zip incl. examples) | per-tutorial not published; distribution ~71–78 MB | n | Activates CHD, RCH, MAW, MVR, SFR, UZF packages; BICGSTAB solver; includes step "Running Model with DISV" (quadtree-refined DISV, max level 6) and ZONEBUDGET+MODPATH runs. |
| MODFLOW 6 Transfer of Solute Among Multiaquifer Wells | USGS ModelMuse Help (Examples/Tutorials) | https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/modflow-6-transfer-of-solute-a.html | HTML step-by-step tutorial + ModelMuse project | DIS, TDIS/IMS, NPF, IC, OC, MAW, MVR, GWT, GWF-GWT | ModelMuse 5.4 + MODFLOW 6 (GWF+GWT) | ModelMuse .gpt project; exports MF6 text input | .gpt, MF6 text input | USGS public domain — verify | Direct download, no registration | https://water.usgs.gov/water-resources/software/ModelMuse/ (distribution zip) | per-tutorial not published | n | GWT solute-transport model coupled to GWF via multi-aquifer wells (MAW) with water-mover (MVR) transfers. |
| MODFLOW 6 Unsaturated Flow with Solute Transport | USGS ModelMuse Help (Examples/Tutorials) | https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/modflow-6-unsaturated-flow-wit.html | HTML step-by-step tutorial + ModelMuse project | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (RCH/EVT via UZF), UZF, GWT, GWF-GWT | ModelMuse 5.4 + MODFLOW 6 (GWF+UZF+GWT) | ModelMuse .gpt project; exports MF6 text input | .gpt, MF6 text input | USGS public domain — verify | Direct download, no registration | https://water.usgs.gov/water-resources/software/ModelMuse/ (distribution zip) | per-tutorial not published | n | Unsaturated-zone flow (UZF6) with solute transport through the unsaturated and saturated zones (UZT/GWT); irrigation + ET scenario. |
| MODFLOW 6 Transfer of Solutes Between Streams and Lakes (LAK/SFR/CNC) | USGS ModelMuse Help (Examples/Tutorials) | https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/modflow-6-transfer-of-solutes-.html | HTML step-by-step tutorial + ModelMuse project | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (SFR), LAK, GWT, GWF-GWT | ModelMuse 5.4 + MODFLOW 6 (GWF+GWT) | ModelMuse .gpt project; exports MF6 text input | .gpt, shapefiles (data/LakSfrCnc), MF6 text input | USGS public domain — verify | Direct download, no registration | https://water.usgs.gov/water-resources/software/ModelMuse/ (distribution zip) | per-tutorial not published | n | LAK + SFR + CNC packages; stream/lake exchange of solutes; flow and transport run as two simulations (ModelMonitor runs twice); grid built from shapefiles. |
| PEST Examples (MODFLOW 6 / MODFLOW-2005 / SUTRA) | USGS ModelMuse Help (Examples/Tutorials) | https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/pest_examples.htm | HTML step-by-step tutorial + 3–4 ModelMuse projects per model version | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (specified-head lake+stream, WEL), OBS, output, plots | ModelMuse 5.4 + PEST (classic; NOT PEST++) with MODFLOW 6 / MODFLOW-2005 / SUTRA | ModelMuse .gpt project (start/true/calibrated variants); exports model input | .gpt, model input files, PEST control/obs files | USGS public domain — verify | Direct download, no registration | https://water.usgs.gov/water-resources/software/ModelMuse/ (distribution zip) | per-tutorial not published | y (within-tutorial: calibrated "true" vs parameter-estimated variants; tutorial is not a real-world dataset) | RMA-based exercise: head + flow observations, parameter estimation for data sets and boundary conditions, visualization of calibrated model. PEST classic, so pestpp-*/ucode tags intentionally not used. |

## Matrix gaps for this source

- **DISU**: no ModelMuse tutorial (ModelMuse does not support DISU grids).
- **SWT**: none (variable density only via GWT hydraulic-head formulation).
- **GNC**: none.
- **pestpp-\***: none (PEST classic and UCODE only).
- **LAK (GWF flow-only)**: covered implicitly in the LAK/SFR/CNC GWT example.

## Browser-verification candidates (later session)

- All `water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/*` tutorial pages (webfetch rendered them, but bot-guard 403 on the directory suggests re-verifying).
- `https://water.usgs.gov/water-resources/software/ModelMuse/` download page (zip URLs per platform).
- ModelMuse Tutorial Videos page (`modelmuse-tutorial-videos-0`) if video rows are wanted.
- No files downloaded; no repo files edited (session log only).
