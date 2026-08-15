# Holdout Registry

Sealed validation pool for the v0.1.0 freeze. Data lives OUTSIDE the repo at
`C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\` (sibling folder).
The repo holds this registry only — no test code, no fixture copies, no index
entries reference holdout material.

## Seal rules

- No holdout data may enter `tests/fixtures/`, tool signatures, or tool
  descriptions before the v0.1.0 freeze.
- Validation failures become v0.2.0 backlog items; no v0.1.0 changes.
- Holdout replay tests (Mode A) reference the sibling folder via `GW_MCP_HOLDOUT`
  env var with a skip-if-absent guard.
- Holdout projects exercising GAP capabilities must fail *cleanly* with
  actionable errors at v0.1.0 (that is the expected outcome — it validates the
  error envelope, not the feature).

## Pre-registered validation criteria (per project)

- Build: `create_model` → packages → `check_model` no fatal errors
- Run: `run_simulation` succeeds and converges
- Outputs plausible: heads in expected range; water-balance closure within tolerance
- Post-processing: `read_heads`, `read_budget`, `plot_heads_map` valid
- Calibration (when data exists): `setup_pest_control` → `run_pestpp_glm` →
  `summarise_calibration` converges or fails with a documented, actionable error
- AI autonomy (Layer 3): log tool-call sequence + reprompt count; target ≤1 reprompt
- Known-limitation gate: GAP-capability projects fail cleanly with
  `PACKAGE_MISSING`-style error codes

## Registry rows

Schema: `name | source url | license | local path (inside holdout root) | capabilities | validation status | notes`

### initial-local (sealed 2026-08-15, from repo)

| Name | Source | License | Local path | Capabilities | Validation status | Notes |
|---|---|---|---|---|---|---|
| Tutorials Modelmuse 01–05 | USGS ModelMuse tutorials (local copy, was repo-tracked) | USGS public domain (verify) | `initial-local/Tutorials Modelmuse/` | DIS, SFR/CHD/WEL, OBS (tutorials 04/05) | pending v0.1.0 freeze | 02/05 hold data; 01/03 PDF-only; 04 = source of `tests/fixtures/tutorial_04` (fixtures self-contained) |
| GMS Tutorials (MODFLOW / MODFLOW-USG / MODFLOW6) | Aquaveo GMS tutorials (local copy, was repo-tracked) | Aquaveo ToS (verify) | `initial-local/GMS Tutorials/` | DIS, DISV, DISU, MAW, UZF (per tutorial zips) | pending v0.1.0 freeze | MODFLOW-USG zips = natural legacy-content pool; PDFs + zips |
| Getting started (GMS exercises, PS1A/PS1B, Exercise8) | Aquaveo GMS getting-started (local copy, was repo-tracked) | Aquaveo ToS (verify) | `initial-local/Getting started/` | DIS, calibration exercises | pending v0.1.0 freeze | `.gpt` GMS project files + data/solution folders |

---
### Round-1 selections (downloaded 2026-08-15, discovery round 1)

Capability-stratified per plan Phase B step 10: ≥1 DISU/unstructured, ≥1
SFR/MAW/UZF, ≥1 GWT, ≥1 with calibration observations, ≥1 flopy-script-driven.
All pinned by commit for reproducibility (clone-on-demand re-fetchable).
Validation status: `pending v0.1.0 freeze` for all.

| Name | Source | License | Local path | Capabilities | Validation status | Notes |
|---|---|---|---|---|---|---|
| test009_3lay-disu | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test009_3lay-disu/` | DISU, GNC, CHD | pending v0.1.0 freeze | 3-layer unstructured grid; DISU stratum. 11 files. |
| test051_uzfp2 | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test051_uzfp2/` | UZF, SFR, STO, WEL, GHB, OBS | pending v0.1.0 freeze | UZF doc problem 2; OBS6 in nam (calibration stratum); 15 files; contains mf2005/mfnwt legacy variants. |
| test020_NevilleTonkinTransient | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test020_NevilleTonkinTransient/` | MAW, STO, OBS | pending v0.1.0 freeze | Multi-aquifer well (Neville & Tonkin 2004); MAW+OBS6 (calibration stratum); 14 files. |
| test201_gwtbuy-henryCHD | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test201_gwtbuy-henryCHD/` | GWT, GWF-GWT, BUY | pending v0.1.0 freeze | Transport stratum — GAP capability: must fail CLEANLY at v0.1.0 (known-limitation gate, `PACKAGE_MISSING`-style code). 22 files. |
| ex-gwt-keating | MODFLOW-ORG/modflow6-examples @ `ff478a63` | no LICENSE file (USGS-origin; flopy CC0-1.0) | `selected/ex-gwt-keating/` | GWT, GWF-GWT, OBS (flopy-script-driven) | pending v0.1.0 freeze | flopy-script stratum + calibration obs (keating_obs1/2.csv); transport — GAP capability: must fail cleanly. |
| modflow6-examples archive | MODFLOW-ORG/modflow6-examples @ `ff478a63` | no LICENSE file (USGS-origin) | `pools/modflow6-examples/` (33.2 MB, 330 files) | curated pool: all GWF/GWT showcase scripts (MAW/UZF/LAK/MVR/STO/DISU/GWT/GWF-GWT/OBS) | pending v0.1.0 freeze | Archive decision from size check (33.17 MB ≤ 50 MB threshold); flopy scripts generate MF6 input at runtime; inputs-only release archive available at modflow6-examples releases page if needed. |

<!-- Round 1 holdout selections appended above (Phase B step 10): 3–5 capability-stratified projects,
     each with source URL, license, commit hash (git sources), local path, capabilities -->
