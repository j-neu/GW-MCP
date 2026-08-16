# Patch — Mode B rerun updates (apply in a session with edit rights)

Source: Mode B dry-run 1 findings (2026-08-15, `research/discovery/sessions/2026-08-15-modeB-tutorial05.md`).
Apply all three edits below, then commit. The closed-book staging folder is already
built at `GW-MCP-holdout\modeB\tutorial05\data\` (5 shapefile sets + activeZone.shp
+ dem_clipped.tif + wells_obs.csv with reachable heads 30–46 m); tutorial PDFs and
reference models moved to `initial-local\Tutorials Modelmuse\05\docs\`.

## 1. `research/discovery/playbooks/modeB-manual-layer3.md`

Replace the "## Setup (once)" step 3 and the whole "## Prep: observation CSV (tutorial 05 has no real CSV)" section with:

```markdown
3. **Closed-book data folder** (self-contained, no answers inside):
   `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\modeB\tutorial05\data\`
   — `river.shp`, `chd_high.shp`, `chd_lower.shp`, `wells.shp`,
   `wells_obs.csv` (heads 30–46 m — reachable with the CHD 40/70 boundaries),
   `activeZone.shp` + `dem_clipped.tif`.

## Closed-book rules (added after dry-run 1, 2026-08-15)

Dry-run 1 proved the agent will read every answer in reach: the tutorial PDFs
(05 root), the reference solved model (`05\Model2a\Model\Model1_b.*`), the
repo's reference test (`tests/test_tutorial_05.py`), and the server source.
All of those are now moved/staged out of reach:

- Tutorial PDFs + reference models live in
  `initial-local\Tutorials Modelmuse\05\docs\` — never in the session folder.
- The session must run in the closed-book `modeB\tutorial05\data\` folder,
  NOT inside `Tutorials Modelmuse\` and NOT in the repo.
- The prompt forbids reading answers (constraint below). A violation is
  recorded as a protocol deviation and the run is invalid.
- Data prep is complete in the staging folder; no PDFs, no repo references,
  no reference models are reachable from it.

## Prep: observation CSV (already staged)

The staged `wells_obs.csv` has reachable synthetic heads (30–46 m). If it
needs regenerating from `wells.shp`, use heads in the 30–46 m band (dry-run 1
proved heads ≥ ~49 m are structurally unattainable with the CHD=40 side
boundaries, which makes calibration impossible and wastes the run):
```

Then, in the "## The session" step 2 and the Mode B prompt block, add this constraint
line at the END of the prompt (after "Work step by step..."):

```
You must work CLOSED-BOOK: do not read the groundwater-mcp source code, its
tests, the tutorial PDFs, or any reference model files. Build everything from
the data files in this folder and the available MCP tools only.
```

Also update "## The session" step 1: session starts in
`GW-MCP-holdout\modeB\tutorial05\data\` (never in `Tutorials Modelmuse\` or the repo).

## 2. `research/holdout-registry.md`

In the `### initial-local` table, change the "Tutorials Modelmuse 01–05" row's
`Validation status` cell from `pending v0.1.0 freeze` to:

```markdown
Mode B dry-run 1 (2026-08-15): journey completed, 0 reprompts, build/run/
postprocess pass, calibration partial — see
`sessions/2026-08-15-modeB-tutorial05.md`; closed-book rerun pending
```

## 3. `tasks.md` — v0.2.0 backlog from Mode B dry-run 1

Under the "**Other v0.2.0 candidates (pre-existing):**" list, add:

```markdown
**Validation backlog (Mode B dry-run 1, 2026-08-15; see research/discovery/sessions/2026-08-15-modeB-tutorial05.md):**
- [ ] fix `setup_pest_control` model command: `model_command_line` in pestpp_options is silently dropped by pyemu 1.4.0 (attribute is `model_command`, a list) → PST written with default `model.bat` which doesn't exist → every PEST++ forward run fails
- [ ] write relative tpl/ins paths into the PST (absolute paths with spaces are rejected by pestpp-glm "wrong number of tokens")
- [ ] make `run_pestpp_glm` resilient to the 60 s MCP client timeout (async/streaming or documented direct-invocation fallback)
- [ ] write `phi.actual.csv` (or return phi progress) when GLM aborts at parameter bounds — currently `summarise_calibration` gets empty progress
- [ ] CHD/WEL shapefile importers (cell mapping currently needs server-internal helpers); document `stress_period_data` record format in tool descriptions
- [ ] document `import_river_from_shapefile` polygon handling (stage 0, conductance = overlap perimeter — acts as a strong drain)
```

## After applying

Commit: `docs: Mode B closed-book rerun setup (runbook, registry, backlog)`.
Then the rerun: new Kilo session in `GW-MCP-holdout\modeB\tutorial05\data\`,
paste the Mode B prompt from the runbook INCLUDING the closed-book constraint,
fill `research/discovery/sessions/2026-08-15-modeB-tutorial05.md` again (overwrite
as rerun 2) and save the transcript alongside.
