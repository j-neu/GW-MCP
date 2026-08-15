# Playbook — Mode B: manual Layer-3 session (natural language)

Validates natural-language usability, tool-description quality, and the full
user journey against a held-out project — pre-registered at `../holdout-registry.md`
(Phase C step 15). This is a HUMAN-GRADED test: the assistant must not be told
tool names; it must discover them from the tool descriptions.

## Pre-registered criteria

- Full journey completed: build → check → run → post-process → calibrate
- Tool-call sequence logged; every reprompt counted
- **Target: ≤1 reprompt** (a reprompt = user has to repeat/clarify an
  instruction because the assistant misread the task or a tool)
- Known-limitation gate: if the assistant proposes a GAP capability (UZF, MAW,
  STO, DISU, GWT…), it must discover the limitation cleanly and proceed with
  what exists — count as a note, not a failure, unless it derails the journey

## Setup (once)

1. MCP server registered globally in `C:\Users\jakob\.config\kilo\kilo.jsonc`
   (`groundwater-mcp` → `.venv\Scripts\groundwater-mcp.exe serve`,
   `groundwater-mcp_*` auto-allowed). Any Kilo session in any folder can now
   use the 36 groundwater-mcp tools.
2. Restart Kilo so the server loads.
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

## The session

1. Start a new Kilo session **in**
   `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\modeB\tutorial05\data\`
   (never in `Tutorials Modelmuse\` or the repo — see closed-book rules above).
2. Paste the Mode B prompt below, verbatim, including the closed-book
   constraint line. Do NOT name tools or file formats — the point is that the
   assistant figures them out.
3. Do not correct the assistant unless it derails (>1 reprompt is the
   measurement; record it).
4. Afterwards, fill the session log (template below).

## Mode B prompt (paste verbatim)

```
You are a groundwater modelling assistant. I am modelling a small catchment
aquifer in MODFLOW 6.

The data files are in this folder: river.shp (a river crossing the catchment),
chd_high.shp and chd_lower.shp (fixed-head boundaries at about 70 m and 40 m),
wells.shp (pumping wells), and wells_obs.csv (head observations with columns
site, date, head_m, x, y).

The catchment boundary polygon is activeZone.shp and the ground-surface
elevation raster is dem_clipped.tif — both are in this folder.

Please:
1. Build the model — one layer, grid cells of about 200 m, the DEM as the
   ground surface.
2. Add the river, the two fixed-head boundaries, and the pumping wells.
3. Check the model for problems, then run it.
4. Report the water balance and produce a head map.
5. Calibrate the hydraulic conductivity against the head observations using
   parameter estimation, then summarise the calibration results.

Work step by step and explain what you are doing at each step.

You must work CLOSED-BOOK: do not read the groundwater-mcp source code, its
tests, the tutorial PDFs, or any reference model files. Build everything from
the data files in this folder and the available MCP tools only.
```

## Session log template

`research/discovery/sessions/YYYY-MM-DD-modeB-tutorial05.md`:

```markdown
# Mode B session — tutorial 05 (natural language)
- Date / client / model
- Prompt used: (paste)
- Tool-call sequence: 1. … 2. … (names + one-line outcome each)
- Reprompts: N (describe each)
- Outcome vs criteria: build/check/run/postprocess/calibrate (pass/partial/fail + evidence)
- Known-limitation notes: (e.g., assistant proposed UZF/STO → clean discovery)
- Time: total minutes
```

## After the session

Append the outcome to `research/holdout-registry.md` (validation status for the
tutorial 05 row) and file any tool-description weaknesses as v0.2.0 backlog
items (a reprompt caused by a confusing tool description is a findings, not a
fix at v0.1.0).
