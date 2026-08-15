# Discovery session log — Aquaveo GMS tutorials

- Date: 2026-08-15
- Playbook: `research/discovery/playbooks/aquaveo-gms-tutorials.md`
- Target source: Aquaveo GMS tutorials index
- Client: **playwright MCP browser NOT available** (registered but needs a Kilo client restart) — this session used the playbook fallback path (`webfetch` + `websearch`). **Browser verification of the listed URLs is PENDING** per playbook; re-verify page rendering and S3 links in the browser session.

## URL movement / fallback notes

- `https://www.aquaveo.com/gms-tutorials` → **404 Not Found** (old URL moved).
- Current index: `https://www.aquaveo.com/software/gms-learning-tutorials` (GMS 10.9 tutorial set; fetched OK).
- All PDF + project-zip pairs are hosted on `https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/` (direct download, no registration). Older-version mirrors exist (`gmstutorials-10.1.aquaveo.com`, `-10.4`; `lightstone.co.jp/aquaveo/files/...` for 10.2).
- Page footer: "Copyright © Aquaveo, LLC. All rights reserved." — tutorials are **NOT public domain**; license recorded as "Aquaveo tutorial ToS — verify".
- No bot challenge encountered via webfetch (unlike some Aquaveo pages); the store front-end emitted a cookie/JS banner but the tutorial grid rendered in full.

## Topic coverage found (GMS 10.9, partial — targets only)

- **MODFLOW 6**: Conceptual Model Approach, Grid Approach, EVT Package, GWE, GWE–Borehole Heat Exchangers, SFR Package, Transient, Transport Grid, Transport Uncoupled, MDT 3D / Discrete Fracture / Equivalent Porous / Sand Tank, **PEST Observations Steady State**, **PEST Observations Transient**, ZONEBUDGET.
- **MODFLOW-USG**: UGrid Creation, Converting from MODFLOW 2005, **Quadtree**, Complex Stratigraphy, Regional to Local, **Calibration**, **GNC Packages**, **CLN Process**, Shapefile to CLN, CLN Observation Wells; Transport: Grid Approach, PFAS, TVM, MDT Matrix Diffusion/3D.
- **Saltwater/transport**: SEAWAT (Hele-Shaw Experiment, Conceptual Model Approach, Concentration and Temperature Effects, Thermal Effects, Viscosity and Pressure Effects, **Goswami/Clement Experiment**), SWI Package (Two-Aquifer System), MT3DMS, **MT3D-USGS Keating**, MODPATH, mod-PATH3DU.
- Legacy MODFLOW packages: DRT, ETS, GAGE, LAK, MNW1/MNW2, Recharge, SFR2, STR, SUB, UZF, SWI; Calibration/PEST set (Model Calibration, Automated Parameter Estimation, Pilot Points, SVD/SVD-Assist/Parallel PEST, Transient Calibration, MODFLOW-USG-PEST); Stochastic set (Parameter Randomization, Indicator, Stochastic Inverse, PEST Null-Space Monte Carlo I/II).

## Grid-type notes (matrix gaps)

- **DISU**: GMS's MODFLOW-USG set is the authoritative DISU source (UGrid Creation → Quadtree/Complex/Regional-to-Local/Calibration/GNC/CLN); quadtree + Voronoi + VTK unstructured grids. Online PDF/zips mirror the local holdout `GMS Tutorials/MODFLOW-USG/*.zip` pool.
- **SWT**: no MODFLOW 6 SWT tutorial; saltwater is via SEAWAT (variable-density) and SWI2 tutorials (tagged SWT with explicit note).
- **GNC**: MODFLOW-USG GNC Packages tutorial exists (`MODFLOW-USG-GncPackage.pdf` + `GncPackage.zip`).
- **pestpp-\***: GMS uses classic PEST (SVD, SVD-Assist, Parallel PEST, NSMC tutorials); PEST++/pestpp tags not used for these rows.

## Catalog rows (for append under `Aquaveo GMS tutorials` in `research/discovery/catalog.md`)

| name | source | url | type | capabilities showcased | toolchain | input format | data formats | license | accessibility | download url | size | calibration-ready | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MODFLOW 6 Grid Approach | Aquaveo GMS 10.9 tutorials | https://www.aquaveo.com/software/gms-learning-tutorials | PDF tutorial + GMS project zip | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR, output | GMS 10.9 + MODFLOW 6 | GMS project (.gpr/.gpt) + generated MF6 text input | PDF, .gpr/.gpt, MF6 text input | Aquaveo tutorial ToS — verify (NOT public domain) | Direct download (S3), no registration | https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/MODFLOW6-GridApproach.pdf + mf6_grid.zip | not shown | n | Grid-approach (structured DIS) MF6 workflow; zip contains GMS project — not directly consumable by MCP (no GMS importer); flag n unless a flopy/MF6-input companion exists. |
| MODFLOW 6 SFR Package | Aquaveo GMS 10.9 tutorials | https://www.aquaveo.com/software/gms-learning-tutorials | PDF tutorial + GMS project zip | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (SFR) | GMS 10.9 + MODFLOW 6 | GMS project (.gpr/.gpt) + generated MF6 text input | PDF, .gpr/.gpt, MF6 text input | Aquaveo tutorial ToS — verify (NOT public domain) | Direct download (S3), no registration | https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/MODFLOW6-SFR.pdf + mf6_sfr.zip | not shown | n | MF6 streamflow-routing package setup in GMS; GMS-project input only. |
| MODFLOW 6 PEST Observations, Steady State | Aquaveo GMS 10.9 tutorials | https://www.aquaveo.com/software/gms-learning-tutorials | PDF tutorial + GMS project zip | DIS, TDIS/IMS, NPF, IC, OC, OBS, output, plots | GMS 10.9 + MODFLOW 6 + PEST (classic) | GMS project (.gpr/.gpt) + generated MF6 text input + PEST obs files | PDF, .gpr/.gpt, MF6 text input, PEST files | Aquaveo tutorial ToS — verify (NOT public domain) | Direct download (S3), no registration | https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/MODFLOW6_PEST_Obs_SS.pdf + mf6_pest_obs_ss.zip | not shown | n | GMS observation/PEST workflow for MF6; companion transient tutorial (MODFLOW6_PEST_Obs_Trans.pdf + mf6_pest_obs_transient.zip). Classic PEST, not pestpp — pestpp-* tags intentionally not used. |
| MODFLOW-USG - Quadtree | Aquaveo GMS 10.9 tutorials | https://www.aquaveo.com/software/gms-learning-tutorials | PDF tutorial + GMS project zip | DISU, TDIS/IMS, NPF, IC, OC, output | GMS 10.9 + MODFLOW-USG | GMS project (.gpr/.gpt) | PDF, .gpr/.gpt, MODFLOW-USG text input | Aquaveo tutorial ToS — verify (NOT public domain) | Direct download (S3), no registration | https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/MODFLOW-USG-Quadtree.pdf + Quadtree.zip | not shown | n | DISU quadtree unstructured grid construction; authoritative online mirror of the local holdout `GMS Tutorials/MODFLOW-USG/Quadtree.zip`. |
| MODFLOW-USG - Calibration | Aquaveo GMS 10.9 tutorials | https://www.aquaveo.com/software/gms-learning-tutorials | PDF tutorial + GMS project zip | DISU, TDIS/IMS, NPF, IC, OC, OBS, output, plots | GMS 10.9 + MODFLOW-USG + PEST utilities | GMS project (.gpr/.gpt) | PDF, .gpr/.gpt, MODFLOW-USG text input, PEST obs data | Aquaveo tutorial ToS — verify (NOT public domain) | Direct download (S3), no registration | https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/MODFLOW-USG-Calibration.pdf + Calibration.zip | not shown | n | MODFLOW-USG has no native obs process — GMS generates PEST observation data post-processing; demonstrated on quadtree and Voronoi UGrids (starts from a MODFLOW 2000 model). GMS-project input only. |

## Rows deferred / candidates for browser verification (saltwater, transport, extra)

- **SEAWAT Goswami/Clement Experiment** (`SEAWAT-GoswamiClementExperiment.pdf` + `saltwater.zip`) — variable-density saltwater intrusion benchmark (tag SWT with "SEAWAT, not MF6 SWT" note; GMS-project input).
- **SEAWAT Conceptual Model Approach** (`SEAWAT-ConceptualModelApproach.pdf` + `coastal.zip`); **SWI Package Two-Aquifer** (`MODFLOW-SWI-TwoAquiferSystem.pdf` + `swi2ex03.zip`).
- **MODFLOW 6 Transport Grid / Transport Uncoupled** (`mf6_transport_p09.zip`, `mf6_transport_uncoupled.zip`) — MF6 GWT rows (GWT, GWF-GWT tags).
- **MT3D-USGS Keating** (`keating.zip`); **MODPATH** (`modpath.zip`), **mod-PATH3DU** (`VoronoiModel.zip`, `Transient.zip`).
- **MODFLOW-USG GNC Packages** (`MODFLOW-USG-GncPackage.pdf` + `GncPackage.zip`) — GNC tag row.
- **MODFLOW-USG CLN Process / CLN Observation Wells** (`ClnProcess.zip`, `ClnObservations.zip`).

## Notes

- Zip contents not inspected (metadata only per playbook rule); `calibration-ready: n` for all GMS rows because input is GMS-project-only and no flopy/MF6-input companion was verified.
- No files downloaded; no repo files edited (session log only).
