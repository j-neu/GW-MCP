# Capability-Coverage Discovery + Holdout Validation Plan (groundwater-mcp)

Status: **Phase A–B complete (2026-08-15).** Discovery round 1 executed: 62 catalog rows across 6 sources (see `research/discovery/sessions/2026-08-15-round1-orchestration.md`); browser-verification follow-ups done; holdout sealed (5 projects + modflow6-examples pool, see `research/holdout-registry.md`). Phase C (validation): Mode A dry-run green + Mode B rerun-2 completed pre-freeze; official Phase C runs at the v0.1.0 freeze.

## Goal (reframed)

Make groundwater-mcp able to manage **ALL of MODFLOW 6 and PEST capabilities**. The discovery effort is a capability-coverage map: systematically find open-source models and tutorials that showcase everything MODFLOW 6 can do (e.g., unstructured-grid DISU), tag them by capability, and use them to (a) expose coverage gaps in the MCP's 36 tools, (b) build a sealed holdout pool for independent validation at the v0.1.0 freeze.

## Baseline — capability audit of the MCP today (from tools.md / source)

| Capability area | Covered by MCP today | Status |
|---|---|---|
| DIS (rectangular grid) | `add_dis_package` | covered |
| DISV (layered vertex grid) | `add_disv_package` | covered |
| **DISU (fully unstructured)** | none | **GAP — user-flagged example** |
| TDIS / IMS | `set_simulation` (nper, perlen, nstp, ims_complexity) | covered |
| STO (storage) | not exposed | GAP |
| NPF / IC / OC | `add_npf_package`, `add_ic_package`, `add_oc_package` | covered |
| CHD/WEL/DRN/RCH/EVT/GHB/SFR | `add_boundary_package` | covered |
| **MAW / UZF / LAK** | not in supported boundary list | **GAP** |
| **GNC / MVR** | not exposed | **GAP** |
| Observations (OBS) | `import_obs_from_csv` writes OBS file; no `add_obs_package` | partial |
| **GWT (transport) / SWT (saltwater) / GWF-GWT coupling** | none | **GAP** |
| Output: .hds/.cbb readers, plots | `read_heads`, `read_budget`, `plot_*`, water balance | covered |
| PEST++ GLM / IES | `run_pestpp_glm`, `run_pestpp_ies` | covered |
| PEST++ uncertainty (PPU) | `run_ies_uncertainty` | covered |
| **PEST++ SEN (sensitivities) / Pareto / SWP (sweep)** | none | **GAP** |
| UCODE (SVD estimation, MCMC/linear uncertainty) | `setup_ucode_control` … `run_ucode_uncertainty` | covered |

This table becomes the "today" column of `research/capability-matrix.md`; the executor verifies each row against the source (tools.md / tool modules) before finalizing.

## Decisions (from user interview)

1. **Coverage scope**: MODFLOW 6 stack first — GWF (all packages incl. DISU/MAW/UZF/LAK/GNC/MVR), GWT, SWT, plus PEST++/pyEMU and UCODE modes. Legacy codes (MODFLOW-2005/NWT/USG, SEAWAT, MT3D-MS) appear in the matrix as out-of-scope rows only.
2. **Gap-fill timing**: v0.1.0 releases as-is (36 tools, frozen). The matrix/catalog drive a **v0.2.0 build order** (DISU first, then remaining gaps by demonstrated demand).
3. Discovery is a **repeatable playbook in the repo** (`research/discovery/`), re-runnable for v0.2.0 rounds.
4. **Catalog-first**: metadata only during discovery; downloads only for the holdout pool.
5. Holdout pool lives in a **sibling folder outside the repo** (`C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\`, confirm at execution). Repo holds a registry (names, URLs, licenses, status) only.
6. Untouched local material (**Tutorials Modelmuse/01,02,03,05, GMS Tutorials/, Getting started/** — 183 tracked files, never used in development) becomes the initial sealed holdout: move to holdout folder, `git rm` from repo.
7. Dev set remains Tutorials 04/05 fixtures in `tests/fixtures/` (unchanged).
8. Holdout sealing: no test code, no fixture copies, no tool-signature/description changes from holdout results before the v0.1.0 freeze. Failures become v0.2.0 backlog items.

## Repository artifacts (executor creates)

```
research/
├── README.md                  ← purpose, how to run a discovery round, links
├── capability-matrix.md       ← every MODFLOW 6 + PEST capability, MCP coverage status, example refs
├── discovery/
│   ├── catalog.md             ← catalog rows (schema below), one section per source
│   ├── playbooks/
│   │   ├── modflow6-test-problems.md   ← git-clone scan (canonical showcase of every package)
│   │   ├── modflow6-examples.md        ← git-clone scan of the curated example repo
│   │   ├── github-topic-searches.md    ← per-capability GitHub searches (DISU, UZF, MAW, GWT, SWT, pestpp)
│   │   ├── flopy-examples.md           ← git-clone scan of flopy examples dir
│   │   ├── usgs-modelmuse-tutorials.md ← playwright session
│   │   ├── aquaveo-gms-tutorials.md    ← playwright session
│   │   └── hydroshare-zenodo.md        ← playwright session
│   └── sessions/              ← dated session logs (small only)
└── holdout-registry.md        ← sealed projects: name, source URL, license, local path, validation status
```

Plus: remove the three tutorial dirs from git after moving; update README project-files table and stale tasks.md checkboxes.

## Schema — capability matrix rows

`capability (package/process/mode, e.g. DISU, MAW, GWT, pestpp-sen) | MCP status today (covered | partial | gap | legacy-out-of-scope) | covering tool(s) | catalog example refs | notes`

## Schema — catalog rows

`name | source | url | type (tutorial|example model|test problem|exercise) | capabilities showcased (list of packages/processes from matrix) | toolchain (MF6 GWF|GWT|SWT|PEST|UCODE|legacy) | input format (flopy script|MF6 input|ModelMuse .mmp|GMS project|NA) | data formats (GeoTIFF|SHP|CSV|zip|none) | license | accessibility (direct zip|git clone|registration|paywall) | download url | size | calibration-ready (y/n) | notes`

## Task list (ordered)

### Phase A — Setup (1–2 sessions)
1. Configure playwright MCP (`npx @playwright/mcp@latest`) for the host client (Kilo via `kilo.jsonc` `mcp` field and/or Cursor); verify `browser_navigate` / `browser_snapshot` / `browser_extract_content` work. Playbooks are client-agnostic.
2. Load superpowers skills: `using-superpowers` (process), `dispatching-parallel-agents` (parallel per-source rounds), `find-skills` (check for a web-scrape skill before hand-writing playbooks).
3. Create `research/` skeleton (artifacts above), capability-matrix.md with the verified baseline table, and the sibling holdout folder.
4. Move local material: copy (then `git rm`) the three tutorial dirs → holdout `initial-local/`; commit removal; run `pytest` (green, `tests/fixtures/` untouched).
5. Update stale docs: tasks.md success-criteria checkboxes + phase status; README project-files table; architecture.md testing-strategy note pointing at holdout-registry.

### Phase B — Discovery round 1 (catalog-first, capability-tagged)
6. Write the 7 playbooks. Git-clone playbooks (modflow6 test problems, modflow6-examples, flopy examples, GitHub topic searches) describe: clone target/branch, how to scan directories for problems, which metadata to extract (README, package inventory per problem, input formats), and the capability-tagging rule (each example maps to ≥1 matrix row). Playwright playbooks (ModelMuse, Aquaveo, HydroShare/Zenodo) describe navigation, extraction targets, and 3–5 catalog rows to fill.
7. Run rounds via `dispatching-parallel-agents` (one agent per source; git-clone agents run locally, web agents use the playwright MCP browser).
8. Agents fill `catalog.md` rows and tag capabilities; the matrix's "example refs" column is populated from catalog rows (a capability with zero examples is a red flag — either rare or our search missed it).
9. Accessibility audit: every row gets `accessibility` + `license`; registration/paywall flagged NOT accessible. For git-clone sources, record clone URL + commit hash (reproducibility).
10. Holdout selection: 3–5 **capability-stratified** projects (≥1 DISU/unstructured, ≥1 SFR or MAW/UZF, ≥1 GWT or SWT, ≥1 with calibration observations, ≥1 flopy-script-driven). Download ONLY these into the holdout folder (note: the full `modflow6` test-problems clone is large — do not archive it; clone on demand during validation sessions instead. `modflow6-examples` clone can be archived if small). Record in `holdout-registry.md`. Nothing holdout-related enters the repo, tests, or docs index.
11. Roadmap: write the v0.2.0 build order into tasks.md 7d from the matrix (DISU first per user; then MAW/UZF/LAK, GNC/MVR, GWT/SWT, STO exposure, pestpp-sen, OBS package tool — order by capability frequency in catalog + user priority).

### Phase C — Validation protocol (pre-registered; executes at v0.1.0 freeze)
12. Freeze: tag v0.1.0. After freeze, no tool signature/description changes from holdout results.
13. Pre-registered success criteria per held-out project:
    - Build: `create_model` → packages → `check_model` no fatal errors
    - Run: `run_simulation` succeeds and converges
    - Outputs plausible: heads in expected range; water-balance closure within tolerance
    - Post-processing: `read_heads`, `read_budget`, `plot_heads_map` valid
    - Calibration (when data exists): `setup_pest_control` → `run_pestpp_glm` → `summarise_calibration` converges or fails with a documented, actionable error
    - AI autonomy (Layer-3): log tool-call sequence + reprompt count; target ≤1 reprompt
    - Known-limitation gate: held-out projects exercising GAP capabilities (e.g., DISU) must fail *cleanly* with actionable errors — that is the expected outcome at v0.1.0 and validates the error envelope, not the feature.
14. Mode A — automated replay: extend the MCP protocol test harness to replay a held-out project's build→run→postprocess sequence from the holdout workspace.
15. Mode B — manual Layer-3: Claude Desktop session on one held-out tutorial, natural language only; save conversation log in `research/sessions/`.
16. Outcomes: passes → publish claim in README/release notes. Failures → categorized into v0.2.0 backlog (missing capability / description ambiguity / data-format gap); NO v0.1.0 changes.

### Phase D — Post-validation (v0.2.0 notes, not executed now)
- Implement v0.2.0 build order from the matrix (Phase B step 11), validating each new tool against the corresponding held-out example (now promoted to dev/test data — after v0.1.0 release).
- Feed validated catalog entries into the docs module (`search_tutorials` metadata).
- Progress notifications for long-running tools; prompts for common workflows; SDK 2.x `MCPServer` migration consideration; MCP Inspector adoption for Layer-3 prep.

## Risks

- **MODFLOW 6 test-problems size**: thousands of problems; do not archive wholesale — clone on demand, catalog by reference (repo + commit hash + path).
- **License/ToS**: tutorial data may restrict redistribution; catalog records licenses; holdout used locally only.
- **Holdout contamination**: `index_builder.py` pulls only from fixed GitHub docs repos — verified safe; holdout is outside the repo so CI never scans it.
- **Playwright flakiness** on JS-heavy pages (USGS): snapshot + retry in playbooks; git-clone fallbacks for GitHub material.
- **Scope creep**: round 1 capped at 7 sources, catalog-first; matrix rows fixed at discovery start so tagging stays consistent.
- **Accidental re-use of local material**: `git rm` after move; holdout folder outside all repo tooling.

## Validation of this plan's completion (evidence)

- `research/` skeleton + capability-matrix.md (baseline verified against source) + 7 playbooks + catalog.md with ≥10 rows across ≥4 sources, every row capability-tagged
- Matrix shows: every MODFLOW 6 GWF/GWT/SWT package and PEST mode has a status; GAP rows have ≥1 catalog example ref
- holdout-registry.md with 3–5 capability-stratified projects incl. licenses + commit hashes
- git log shows the removal commit; `pytest` green; `tests/fixtures/` unchanged
- tasks.md checkboxes/phase status corrected; v0.2.0 build order written into 7d

## Open questions (executor confirms)

- Exact sibling holdout path (default: `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\`)
- Which client hosts the playwright MCP sessions (Kilo vs Cursor) — playbooks are client-agnostic
- Whether `modflow6-examples` (curated, smaller) is archived into the holdout or also cloned on demand (size check at execution)
