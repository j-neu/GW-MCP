# research/ — Capability-Coverage Discovery + Holdout Validation

This directory holds the discovery artifacts for groundwater-mcp: a capability
coverage map of everything MODFLOW 6 and PEST can do, catalogued open-source
models/tutorials that showcase each capability, and the sealed holdout registry
used for independent validation at the v0.1.0 freeze.

**Status (2026-08-15/16):** Discovery round 1 complete — 62 catalog rows across
6 sources; 7 playbooks; capability matrix populated; holdout sealed (5
capability-stratified projects + curated pool). Validation: Mode A replay
dry-run green (7 tests, 2 bugs found & fixed), Mode B closed-book manual
sessions complete (dry-run 1 + rerun-2, 0 reprompts) with rerun-2 fixes applied
2026-08-16. Official Phase C validation runs at the v0.1.0 freeze.

## Purpose

1. **Capability matrix** — every MODFLOW 6 (GWF/GWT/SWT) package and PEST mode
   vs. current MCP tool coverage (covered | partial | gap | legacy-out-of-scope).
2. **Catalog** — metadata-only rows for open-source models, tutorials, test
   problems, and exercises, capability-tagged, with accessibility/license info.
3. **Playbooks** — repeatable per-source discovery procedures (git-clone scans
   and playwright browser sessions), re-runnable for v0.2.0 rounds.
4. **Holdout registry** — sealed projects used to validate the frozen v0.1.0
   tool set. The data itself lives OUTSIDE this repo
   (`C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\`), never in
   `tests/fixtures/` — that seal is what makes validation independent.

## How to run a discovery round

1. Pick sources from the playbooks (`discovery/playbooks/`) that cover matrix
   rows with `gap` status or thin example coverage.
2. Run one agent per source in parallel (git-clone agents run locally; web
   sources use the playwright MCP browser: `browser_navigate` /
   `browser_snapshot` / `browser_extract_content`).
3. Append rows to `discovery/catalog.md` per source section, capability-tagged
   against `capability-matrix.md` rows. Record clone URL + commit hash for git
   sources (reproducibility).
4. Log the session (source, date, rows added, blockers) in
   `discovery/sessions/YYYY-MM-DD-<source>.md`.
5. Update the matrix's "catalog example refs" column. A GAP row with zero
   examples is a red flag — either the capability is genuinely rare or the
   search missed it.
6. Holdout selection (3–5 capability-stratified projects) → download into the
   holdout folder → record in `holdout-registry.md`. Nothing holdout-related
   enters the repo, tests, or the docs index.

## Playwright setup

- Server: `npx @playwright/mcp@latest` (v0.0.79), registered in
  `C:\Users\jakob\.config\kilo\kilo.jsonc` under `mcp.playwright`
  (`playwright_*` tools auto-allowed). Playbooks are client-agnostic.
- No dedicated web-scrape skill exists that beats the playwright browser tools;
  hand-written playbooks are the approach (checked 2026-08-15).

## Files

| File | Purpose |
|---|---|
| `capability-matrix.md` | Capability × coverage status × example refs |
| `discovery/catalog.md` | Catalog rows, one section per source |
| `discovery/playbooks/*.md` | Per-source discovery procedures (7) |
| `discovery/sessions/*.md` | Dated session logs |
| `holdout-registry.md` | Sealed projects: source, license, path, validation status |
