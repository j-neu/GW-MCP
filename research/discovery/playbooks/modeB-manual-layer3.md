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
- **MCP-only gate (added 2026-08-22):** every build/run/postprocess/calibrate
  action goes through a groundwater-mcp tool call — no raw `flopy`/`pyemu`
  Python and no hand-edited model/PEST files. This is enforced the same way
  as the closed-book rule: a violation is a protocol deviation and the run
  is invalid for validating the tool it routed around (though the underlying
  tool gap that prompted it is still a valid finding — see below)

## Setup (once)

1. MCP server registered globally in `C:\Users\jakob\.config\kilo\kilo.jsonc`
   (`groundwater-mcp` → `.venv\Scripts\groundwater-mcp.exe serve`,
   `groundwater-mcp_*` auto-allowed). Any Kilo session in any folder can now
    use the current groundwater-mcp tool set (63 tools as of 2026-08-22 —
    check README.md for the current count, it grows between sessions).
2. Restart Kilo so the server loads.
3. **Closed-book data folder** (self-contained, no answers inside):
   `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\modeB\tutorial05\data\`
   — `river.shp`, `chd_high.shp`, `chd_lower.shp`, `wells.shp`,
   `wells_obs.csv` (heads 30–46 m — reachable with the CHD 40/70 boundaries),
   `activeZone.shp` + `dem_clipped.tif`.

## Session setup checklist (added after rerun-2, 2026-08-15)

- **ALL data must live in the agent's working folder.** Nothing may be
  referenced from outside it. The prompt below references ONLY in-folder
  relative names (`activeZone.shp`, `dem_clipped.tif` are in the same folder).
  Rerun-2's prompt still pointed at `tests\fixtures\tutorial_04` for those two
  files because the user pasted a stale prompt — do not paste stale prompts.
- Before starting, verify the working folder contains **every data file the
  prompt mentions** (river/chd_high/chd_lower/wells `.shp` + `.prj`/`.dbf`,
  `wells_obs.csv`, `activeZone.shp` **and its sidecars** `.dbf`/`.shx`/`.prj`,
  `dem_clipped.tif`). If any file is missing, copy it into the folder BEFORE
  starting. (Rerun-3 lost ~10 min because `activeZone.shx` was missing and the
  agent had to rebuild it by hand.)
- Permission fix (applied 2026-08-15 to `~/.config/kilo/kilo.jsonc`): the
  holdout folder is allow-listed under `permission.external_directory`
  (`"C:\\Users\\jakob\\Documents\\Cursor projects\\GW-MCP-holdout\\**": "allow"`),
  so the session reads/writes it without "allow access to external files"
  prompts. Requires a Kilo restart after editing. The MCP server's own data
  dir (`C:\Users\jakob\.groundwater-mcp\**`) was added 2026-08-16 so default
  workspaces are also prompt-free.

## Preflight (added after rerun-3, 2026-08-16)

Rerun-3 lost time to (a) permission prompts from a default workspace outside
the session folder and (b) the agent wrongly concluding flopy/pyemu were
"not available" because it probed the system Python, not the server venv.
Before building, the assistant should:

1. Call the MCP `check_environment` tool once — it reports the server's own
   Python, the installed packages (flopy/pyemu/geopandas/rasterio) with
   versions, the MODFLOW 6 / PEST++ executable paths, docs index
   state, and the default workspace root. If anything is missing, report it
   and stop; do not guess with shell commands.
2. Create the model workspace **inside the session folder** (e.g. a `model\`
   subfolder) by passing an explicit `workspace` path to `create_model`, so
   all data + model files live in one place and no permission prompts occur.
   The rerun-3 agent used the default `~/.groundwater-mcp/workspaces/...`
   which sat outside the session folder and caused repeated prompts.

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

## MCP-only rule (added 2026-08-22, after the 7e Tier-C work)

The recurring failure mode across **every** prior validation session (Mode B
rerun-2/3/4, the transient run, and — most severely — zenodo run 1, which
bypassed the MCP entirely for a 94-minute calibration) was the agent dropping
to raw `flopy`/`pyemu` Python or hand-edited model/PEST files whenever a tool
felt slow, unclear, or insufficient. That defeats the point of this test:
it's meant to validate whether the MCP tools are *sufficient on their own*,
not whether the agent can write flopy. The prompt below now states this as an
explicit, non-negotiable constraint (see the "MCP-ONLY CONSTRAINT" paragraph)
and it is enforced the same way the closed-book rule is: **using flopy/pyemu
directly, or hand-editing a model/PEST file, is a protocol deviation that
invalidates the run.** If it happens, stop, record exactly what tool gap
forced it (that gap is itself a valid, valuable finding — file it as a
backlog item — the deviation is only about *how* the agent responded to the
gap, not the gap's existence), and either restart after a fix or continue
with the deviation logged.

Do not name specific groundwater-mcp tools (`diagnose_convergence`,
`model_status`, etc.) to the agent — discovering them from their descriptions
is still the point (see the header note above). If the MCP client (Kilo)
exposes `groundwater-mcp`'s registered *prompts* as selectable starting
templates, use `build_model_from_data` as the session's opening message
instead of pasting the prompt below by hand, and note in the session log that
this run started from the MCP prompt — that is itself the C6 verification
this playbook now also covers. If the client does not expose MCP prompts as
a UI feature, paste the prompt below as before.

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

Before building, verify the modelling environment is ready (dependencies,
MODFLOW executables) and list the data files you found in this folder. Keep
all model files in a new subfolder "model" of this folder.

You must work CLOSED-BOOK: do not read the groundwater-mcp source code, its
tests, the tutorial PDFs, or any reference model files. Build everything from
the data files in this folder and the available MCP tools only.

MCP-ONLY CONSTRAINT: every action that builds, runs, or post-processes the
MF6 MODEL ITSELF must go through the groundwater-mcp tools — do NOT call
flopy/pyemu MODFLOW or PEST classes directly, and do NOT hand-edit MODFLOW
or PEST input files (.dis, .npf, .ic, .nam, .tdis, .ims, .pst, .tpl, .ins,
etc.) with a text editor or shell command. Ordinary Python for reading/
transforming the shapefile or CSV data before passing it to a tool is fine.
If a groundwater-mcp tool cannot do something you need, STOP and report
exactly what capability is missing and why — do not work around the gap by
building/running/post-processing the model with raw flopy/pyemu instead.
When something goes wrong (a build error, a non-converging run, an
unbalanced water budget), look for a groundwater-mcp tool that diagnoses it
before writing your own analysis code or reading raw output files by hand.
A workaround invalidates this run: it is testing whether the MCP tools are
sufficient on their own, not your general Python ability.
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
- MCP-only violations: N (each: what forced it, the underlying tool gap, whether it derailed the run)
- Started from the build_model_from_data MCP prompt? yes/no (C6 verification)
- Time: total minutes
```

## After the session

Append the outcome to `research/holdout-registry.md` (validation status for the
tutorial 05 row) and file any tool-description weaknesses as v0.2.0 backlog
items (a reprompt caused by a confusing tool description is a findings, not a
fix at v0.1.0).
