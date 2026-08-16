# Mode B rerun-2 — lessons + MCP improvement list (apply in a session with edit rights)

Source: `research/discovery/sessions/2026-08-15-modeB-tutorial05-rerun2.md` + chatlog.
Rerun-2: closed-book, no source/PDF reads, journey completed, 0 reprompts,
calibration genuinely converged (K 10 → 8.1 m/d, phi 1190, RMSE 6.4 m) — but
only by bypassing the MCP calibration chain (pyemu-built PST + direct pestpp).
Total ~65 min; ~45 min were the calibration leg fighting tool bugs.

**Status: all items implemented 2026-08-15 in the `modeB-lessons-and-mcp-fixes`
session. Tier 1 items 1–5 and Tier 2 items 7–10 applied; Tier 2 item 6
(async pestpp runner) left as a v0.2.0 design item (still in tasks.md backlog).**

## 1. Permission fix — KILLS the "allow access to external files" prompts (user's #1 pain)

`C:\Users\jakob\.config\kilo\kilo.jsonc` → `permission.external_directory`:
add the holdout allow line:

```jsonc
"external_directory": {
  "*": "ask",
  "C:\\Users\\jakob\\AppData\\Local\\Temp\\kilo\\*": "allow",
  "C:\\Users\\jakob\\AppData\\Local\\Temp\\*": "allow",
  "C:\\Users\\jakob\\Documents\\Cursor projects\\GW-MCP-holdout\\**": "allow"
},
```

Restart Kilo after editing. Every Mode B / holdout session then reads and writes
the holdout folder without prompts. (Note: `edit: allow` in the same file only
applies to NEW sessions — the runtime state is fixed at session start.)

## 2. Runbook lessons (update `research/discovery/playbooks/modeB-manual-layer3.md`)

- **ALL data must live in the agent's working folder.** Rerun-2's prompt still
  pointed at `tests\fixtures\tutorial_04` for activeZone/dem even though the
  staging folder already contains them — the user pasted the stale prompt. The
  runbook prompt must reference ONLY `modeB\tutorial05\data\` (in-folder paths).
- Add to the runbook: "Session setup checklist — the working folder must
  contain every data file the prompt mentions; nothing is referenced from
  outside. If a file is missing, copy it into the folder BEFORE starting."
- Note the permission fix above so future sessions are prompt-free.

## 3. MCP improvements (rerun-2 findings, prioritized)

### Tier 1 — quick bug fixes (same class as the earlier noptmax / FLOW-JA-FACE fixes; no signature changes)

1. `setup_pest_control` **silently drops observations** — `n_observations=0`
   regardless of `obs_data`, and maps the instruction file to the wrong output
   filename (strips `.ins` → wrong name). THE calibration blocker. Fix the
   obs-to-instruction alignment (names must match instruction-file tokens) and
   raise instead of silently dropping when nothing aligns. ✅ DONE
2. `pestpp_options.model_command_line` is **silently ignored** (pyemu 1.4.0
   attribute is `model_command`, a list) → PST written with default `model.bat`
   which doesn't exist / fails on this machine
   (`NoDefaultCurrentDirectoryInExePath=1`; pestpp mangles `cmd /c`). Fix the
   assignment; write an explicit command. ✅ DONE (Windows default = located MF6 binary)
3. `add_boundary_package` doesn't write `SAVE_FLOWS` → CHD/WEL flows invisible
   to `compute_water_balance` until package files are hand-edited. Add
   `save_flows` option (default on for CHD/WEL/GHB/RIV). ✅ DONE
4. Re-adding a package of the same type **silently overwrites** (first CHD call
   lost, caught only via `check_model`). Return a warning in the response. ✅ DONE
5. `search_docs` fails with `INDEX_NOT_BUILT` — no offline docs at all.
   Auto-build the index on first call (or return build instructions). ✅ DONE (background build + retry message)

### Tier 2 — v0.2.0 design items

6. `run_pestpp_glm` hits the client's 60 s MCP timeout — make it async with a
   status/poll tool, or return progress immediately. ⏳ DEFERRED (v0.2.0; still in tasks.md backlog)
7. `import_river_from_shapefile`: document/default stage + rbot (default
   stage=0 drains the aquifer to ~3 m heads); add stage-from-DEM option. ✅ DONE (docs + `stage_raster`/`stage_offset` params)
8. Document 0-based cellid + stress-period semantics in `add_boundary_package`
   (1-based input produced "invalid BC index" that only check_model caught). ✅ DONE (docstring + tools.md)
9. Image-viewing tool (read a PNG from the workspace) so `plot_heads_map`
   output can be verified by the agent, not just file existence. ✅ DONE (`view_image`, 37th tool)
10. Integration test: full `setup_pest_control → run_pestpp_glm →
    summarise_calibration` on this machine's environment (paths with spaces,
    Windows cmd quirks) so the chain is green before the next Mode B run. ✅ DONE
    (`test_integration_full_calibration_chain_windows`)

## 4. Evidence to keep

Rerun-2's calibrated model workspace:
`C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\modeB\tutorial05\model\`
(tutorial05.pst/.par/.rei, heads_map.png, heads_map_calibrated.png). Registry
status for tutorial 05: Mode B rerun-2 complete (closed-book, 0 reprompts,
calibration partial-via-workaround — MCP chain broken, see Tier 1).
