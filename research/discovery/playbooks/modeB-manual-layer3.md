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
3. Data folder (sealed material, no copying needed):
   `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\initial-local\Tutorials Modelmuse\05\data1a\Data`
   — `river.shp`, `chd_high.shp`, `chd_lower.shp`, `wells.shp`.
   Grid boundary + DEM come from the dev set (absolute paths, referenced in the
   prompt): `tests/fixtures/tutorial_04\activeZone.shp` and `dem_clipped.tif`.

## Prep: observation CSV (tutorial 05 has no real CSV)

The HOB tutorial ships PDFs only. Generate the observations CSV from the well
locations before the session (keeps calibration in the journey):

```powershell
uv run python -c "
import csv, geopandas as gpd
gdf = gpd.read_file(r'<DATA_DIR>\wells.shp')
with open(r'<DATA_DIR>\wells_obs.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['site', 'date', 'head_m', 'x', 'y'])
    for i, row in enumerate(gdf.itertuples(), 1):
        w.writerow([f'w{i}', '2000-01-01', round(55.0 + (i % 5), 2), row.geometry.x, row.geometry.y])
print('written')
"
```

## The session

1. Start a new Kilo session **in** `<DATA_DIR>` (any folder works now that the
   server is global, but the data folder keeps relative paths natural).
2. Paste the Mode B prompt below, verbatim. Do NOT name tools or file formats
   — the point is that the assistant figures them out.
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
elevation raster is dem_clipped.tif — both are in
C:\Users\jakob\Documents\Cursor projects\GW-MCP\tests\fixtures\tutorial_04\

Please:
1. Build the model — one layer, grid cells of about 200 m, the DEM as the
   ground surface.
2. Add the river, the two fixed-head boundaries, and the pumping wells.
3. Check the model for problems, then run it.
4. Report the water balance and produce a head map.
5. Calibrate the hydraulic conductivity against the head observations using
   parameter estimation, then summarise the calibration results.

Work step by step and explain what you are doing at each step.
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
