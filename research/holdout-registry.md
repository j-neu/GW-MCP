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
| Tutorials Modelmuse 01–05 | USGS ModelMuse tutorials (local copy, was repo-tracked) | USGS public domain (verify) | `initial-local/Tutorials Modelmuse/` | DIS, SFR/CHD/WEL, OBS (tutorials 04/05) | Mode B rerun-4 (2026-08-16): closed-book, 0 reprompts, ~29 min, zero permission prompts (set-and-forget run). Build/run/postprocess pass; calibration via the fixed MCP chain (`setup_pest_control → run_pestpp_glm → summarise_calibration`) → K=36.28 m/d, phi 803.6, RMSE 5.26 m — best fit across all reruns. Required PEST++ mechanics the agent had to discover (template token width, derinclb, local-minimum trap) — see backlog. See `sessions/2026-08-16-modeB-tutorial05-rerun4.md`; prior: rerun-2 (workaround), rerun-3 (MCP chain, pre-UX-fixes) | 02/05 hold data; 01/03 PDF-only; 04 = source of `tests/fixtures/tutorial_04` (fixtures self-contained) |
| GMS Tutorials (MODFLOW / MODFLOW-USG / MODFLOW6) | Aquaveo GMS tutorials (local copy, was repo-tracked) | Aquaveo ToS (verify) | `initial-local/GMS Tutorials/` | DIS, DISV, DISU, MAW, UZF (per tutorial zips) | pending v0.1.0 freeze | MODFLOW-USG zips = natural legacy-content pool; PDFs + zips |
| Getting started (GMS exercises, PS1A/PS1B, Exercise8) | Aquaveo GMS getting-started (local copy, was repo-tracked) | Aquaveo ToS (verify) | `initial-local/Getting started/` | DIS, calibration exercises | pending v0.1.0 freeze | `.gpt` GMS project files + data/solution folders |

---
### Round-1 selections (downloaded 2026-08-15, discovery round 1)

Capability-stratified per plan Phase B step 10: ≥1 DISU/unstructured, ≥1
SFR/MAW/UZF, ≥1 GWT, ≥1 with calibration observations, ≥1 flopy-script-driven.
All pinned by commit for reproducibility (clone-on-demand re-fetchable).
Validation: Mode A dry-run executed 2026-08-15 (7 replay tests green); the
**official Mode A replay runs at the v0.1.0 freeze** (Phase C step 12).

| Name | Source | License | Local path | Capabilities | Validation status | Notes |
|---|---|---|---|---|---|---|
| test009_3lay-disu | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test009_3lay-disu/` | DISU, GNC, CHD | pending v0.1.0 freeze | 3-layer unstructured grid; DISU stratum. 11 files. |
| test051_uzfp2 | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test051_uzfp2/` | UZF, SFR, STO, WEL, GHB, OBS | Mode A dry-run PASS (2026-08-15; structure only — partial stress replay) | UZF doc problem 2; OBS6 in nam (calibration stratum); 15 files; contains mf2005/mfnwt legacy variants. |
| test020_NevilleTonkinTransient | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test020_NevilleTonkinTransient/` | MAW, STO, OBS | Mode A dry-run PASS (2026-08-15; closure asserted — CHD-only synthetic) | Multi-aquifer well (Neville & Tonkin 2004); MAW+OBS6 (calibration stratum); 14 files. |
| test201_gwtbuy-henryCHD | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test201_gwtbuy-henryCHD/` | GWT, GWF-GWT, BUY | pending v0.1.0 freeze | Transport stratum — GAP capability: must fail CLEANLY at v0.1.0 (known-limitation gate, `PACKAGE_MISSING`-style code). 22 files. |
| ex-gwt-keating | MODFLOW-ORG/modflow6-examples @ `ff478a63` | no LICENSE file (USGS-origin; flopy CC0-1.0) | `selected/ex-gwt-keating/` | GWT, GWF-GWT, OBS (flopy-script-driven) | pending v0.1.0 freeze | flopy-script stratum + calibration obs (keating_obs1/2.csv); transport — GAP capability: must fail cleanly. |
| modflow6-examples archive | MODFLOW-ORG/modflow6-examples @ `ff478a63` | no LICENSE file (USGS-origin) | `pools/modflow6-examples/` (33.2 MB, 330 files) | curated pool: all GWF/GWT showcase scripts (MAW/UZF/LAK/MVR/STO/DISU/GWT/GWF-GWT/OBS) | pending v0.1.0 freeze | Archive decision from size check (33.17 MB ≤ 50 MB threshold); flopy scripts generate MF6 input at runtime; inputs-only release archive available at modflow6-examples releases page if needed. |

---
### Round-2 selections (downloaded 2026-08-16, v0.1.0 validation-gate round)

Adds the harder in-scope validation targets the Phase 6 review asked for
(transient + multi-BC + real calibration benchmark). STO moved from GAP to
covered on 2026-08-16 (`add_sto_package`, v0.1.0 gate) — see
`.kilo/plans/2026-08-16-transient-support-and-validation-gate.md`.

| Name | Source | License | Local path | Capabilities | Validation status | Notes |
|---|---|---|---|---|---|---|
| test005_advgw_tidal | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test005_advgw_tidal/` | STO, WEL, RIV, RCH (x3), GHB, EVT, OBS, time series | Mode A replay PASS (2026-08-16): DIS+STO+NPF+IC+OC replayed, synthetic CHD (WEL/RIV/GHB/EVT are TS6-driven → not replayable at v0.1.0, documented deviation), 25 transient periods, converges | 31 files; multi-BC + OBS + time-series stress; OBS package not replayed (GAP) |
| mf6_freyberg | usgs/pestpp @ `5d49814` | USGS public domain (TM7C26 report example) | `selected/mf6_freyberg/` | DIS, STO, SFR, RCH, WEL, GHB, OBS, PEST++ control files | Full MCP calibration chain PASS (2026-08-16): adopted → run_simulation converges → setup_pest_control → run_pestpp_glm → summarise_calibration (6 welflx params, 10 head obs, noptmax=3) | 102 files; benchmark from White et al (2020) PEST++ report; calibration is a subset of the shipped parameterisation (documented deviation) |

<!-- Round 1 holdout selections appended above (Phase B step 10): 3–5 capability-stratified projects,
     each with source URL, license, commit hash (git sources), local path, capabilities -->
