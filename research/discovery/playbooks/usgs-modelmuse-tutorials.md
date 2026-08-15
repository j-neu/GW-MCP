# Playbook — USGS ModelMuse tutorials (playwright browser)

**Source:** USGS ModelMuse help/tutorial pages. **URLs verified 2026-08-15:**
- The old tutorials index `water.usgs.gov/ogw/modelmuse/tutorials.html` is
  **gone (404)**; `www.usgs.gov/software/modelmuse*` moved to
  `https://www.usgs.gov/software/modelmuse-a-graphical-user-interface-groundwater-models`.
- Current tutorials live in the ModelMuse Help "Examples/Tutorials" section:
  `https://water.usgs.gov/nrp/gwsoftware/ModelMuse/Help/examples.html` →
  `modflow_examples.html` (HTML step-by-step tutorials; project files ship in
  the ModelMuse distribution zip).
- Downloads: `https://water.usgs.gov/water-resources/software/ModelMuse/`
  (distribution zip incl. examples, ~71–78 MB, v5.4.0.0 at scan time).
- Known coverage: MODFLOW 6 Example (CHD/RCH/MAW/MVR/SFR/UZF + DISV quadtree),
  MAW solute transfer (GWT), UZF+solute transport, LAK/SFR/CNC transport,
  Subsidence, ATES, PEST Examples (classic PEST, not PEST++). ModelMuse does
  NOT support DISU, SWT, or GNC — those stay gaps for this source.

**Client:** the playwright MCP browser only (`browser_navigate`,
`browser_snapshot`, `browser_extract_content`, `browser_click`, and
`browser_type` as needed). Browser tools appear after the Kilo client restart.

## Procedure

1. **Navigate** to the tutorials index; `browser_snapshot` and locate the
   tutorial list. USGS pages are JS-light but occasionally bot-guarded:
   - If the page fails or shows a challenge → snapshot again after 3–5 s
     (`browser_navigate` once more), then retry.
   - If still blocked → record the URL in the session log as
     "bot-protected, manual fill" and continue with other sources. Do NOT fail
     the whole round.
2. **Extract the tutorial table**: title, topic (grid type, packages,
   transport/saltwater), format (PDF, .mmp ModelMuse project, .zip data).
   ModelMuse tutorials of interest: DISV grids, SFR/RIV/WEL boundaries, MAW,
   UZF, LAK, GWT transport, saltwater (SWT).
3. **Fill 3–5 catalog rows** (target the gap rows: DISU rarely appears in
   ModelMuse tutorials — note that; MAW/UZF/LAK and GWT/SWT do). For each row
   capture: exact download URL, format (`.mmp`/`.zip`/PDF), size if shown,
   license/terms note (USGS tutorials are generally public-domain; record
   "USGS public domain — verify" unless the page says otherwise), and
   capability tags.
4. **Catalog:** append rows under the `USGS ModelMuse tutorials` section of
   `research/discovery/catalog.md`; `accessibility: direct zip` or
   `registration` as observed.
5. **Session log:** `research/discovery/sessions/YYYY-MM-DD-usgs-modelmuse.md`
   including blocked pages + fallback notes.

## Rules

- Do not download during discovery (metadata only) — downloads happen only for
  holdout selection (B10).
- Capability tags must match matrix row names.
