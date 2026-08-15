# Playbook — HydroShare / Zenodo (playwright browser)

**Purpose:** find published, often calibration-ready MODFLOW 6 model datasets
with observation data — the best source for the "calibration observations"
stratum of the holdout selection. Also where GWT/SWT and unstructured models
get published by researchers.

**Client:** the playwright MCP browser for HydroShare; Zenodo search may work
via websearch/webfetch, but browser is the fallback for paginated results.

## Procedure

1. **HydroShare** (`https://www.hydroshare.org/search/?q=modflow`):
   - The search UI is a JS-only SPA — fallback: find resources via websearch
     and fetch resource pages directly
     (`https://www.hydroshare.org/resource/{id}/`), which render license,
     size, and sharing status server-side.
   - For each candidate resource: open it, extract title, description
     (packages/model type), resource type, license (shown on the resource
     page — often a CC license or "all rights reserved"; record exactly what
     is shown), files list (`.nam`/`.mfsim.nam`, observations CSV; file lists
     are JS-rendered — verify in the browser), and whether download is direct
     (resource → "Download all" zip).
   - Bot protection → snapshot-and-retry; fallback: record URL for manual fill.
2. **Zenodo** (`https://zenodo.org/search?q=modflow6`):
   - The HTML search is JS/bot-challenged — the public REST API works:
     `https://zenodo.org/api/records?q=modflow6` (returns license + file list
     + size + stable per-file download URLs). Use it for discovery; confirm
     the display-license text + checksums in the browser for selected rows.
   - Direct-download URLs are stable (record the file-level URLs).
3. **Capability-tag** against the matrix. Round-1 priority: calibration-ready
   rows with OBS data, GWT, SWT, DISU.
4. **Catalog:** append rows under the `HydroShare / Zenodo` section of
   `research/discovery/catalog.md`.
5. **Session log:** `research/discovery/sessions/YYYY-MM-DD-hydroshare-zenodo.md`.

## Rules

- Metadata only; downloads only for holdout selection (B10).
- License must be recorded verbatim from the resource page — redistribution
  restrictions decide whether a project is holdout-eligible (holdout is used
  locally only, but the registry records the license anyway).
