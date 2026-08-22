# Playbook — Aquaveo GMS tutorials (playwright browser)

**Source:** Aquaveo GMS tutorials index. **URLs verified 2026-08-15:**
- `www.aquaveo.com/gms-tutorials` is **gone (404)**; current index:
  `https://www.aquaveo.com/software/gms-learning-tutorials` (GMS 10.9 set).
- PDF + project-zip pairs are hosted on
  `https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/` (direct download,
  no registration; older mirrors `-10.1`, `-10.4`, `lightstone.co.jp/...`).
- Footer: "Copyright © Aquaveo, LLC. All rights reserved." — tutorials are
  **NOT public domain**; record "Aquaveo tutorial ToS — verify".
- Coverage map: MODFLOW 6 (Grid/Conceptual/SFR/EVT/GWE/Transport/PEST Obs
  SS+Transient), MODFLOW-USG (UGrid/Quadtree/Calibration/GNC/CLN — the
  authoritative **DISU** source), SEAWAT, SWI2, MT3D-USGS, MODPATH.

**Client:** the playwright MCP browser only.

## Procedure

1. **Navigate** to the tutorials index; snapshot and list the tutorial grid
   (topic × version columns).
2. **Targets for round 1** (these cover gap/legacy rows):
   - MODFLOW 6 tutorials (DIS, DISV, boundary packages, observations)
   - MODFLOW-USG tutorials (DISU unstructured grids — the GMS DISU set is a
     natural legacy-content pool already mirrored in the local holdout
     `GMS Tutorials/MODFLOW-USG/*.zip`; catalog the online pages anyway as the
     authoritative source with URLs)
   - Transport (MT3D-USGS) and Saltwater tutorial pages if present
   - MODPATH particle tracking (v0.2.0 row)
3. **Fill 3–5 catalog rows** with: title, URL, format (PDF + zip of a GMS
   `.gpr/.gpt` project), size, capability tags, and license/ToS note (Aquaveo
   tutorial terms — record "Aquaveo tutorial ToS — verify" unless the page
   states otherwise; Aquaveo material is NOT public domain).
4. **Bot protection:** snapshot-and-retry once; if still blocked, record the
   URL in the session log for manual fill and move on.
5. **Catalog:** append rows under the `Aquaveo GMS tutorials` section of
   `research/discovery/catalog.md`; `accessibility` as observed (direct zip /
   registration).
6. **Session log:** `research/discovery/sessions/YYYY-MM-DD-aquaveo-gms.md`.

## Rules

- Metadata only. Capability tags match matrix row names.
- **GMS zips are MCP-usable despite the `.gpr/.gpt` project files (corrected
  2026-08-16):** the tutorial zips ship the *generated MF6 text input sets*
  (`sample/…_models/MODFLOW 6/` — `.nam/.dis/.disv/.npf/.chd/.wel/.drn/.riv/
  .ghb/.rch` + `_input/` + `_output/`) AND the GIS source data (shapefiles,
  GeoTIFFs) used to build each model. No GMS importer is needed — record
  `input format: MF6 text input (generated) + GMS project + GIS source data`,
  and set `calibration-ready: y` where a PEST obs interface ships (e.g.
  `mf6_pest_obs_ss`: `model.pobs`, `mf6mod2obs`, `obs.out`,
  `pest_obs_stats.txt`). Verify inside the zip (tar listing), not from the PDF
  alone.
