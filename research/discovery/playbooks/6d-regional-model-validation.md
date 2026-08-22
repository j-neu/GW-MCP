# Playbook — Phase 6d: real-life regional model validation (Agent Manager)

Validates the MCP toolchain on **genuinely real regional models** (not
test/benchmark/tutorial scale), closed-book, before the v0.1.0 release. Each
target runs in its own Agent Manager worktree session, then logged under
`research/discovery/sessions/`. The four detailed targets below are the first
wave; the release gate in `tasks.md` extends the list to all Tier-1 targets
(mf6brabant, zenodo-21381071, aare-valley, GMS `mf6_pest_obs_ss`, mf6_freyberg,
neversink_workflow, 1DSubsidenceModeling-MF6CSUB, MF6_EnKF_DISU) plus Tier-2
capability gates for each new tool in later releases.

**Governing policy (tasks.md release gate, 2026-08-16):** every target runs
through the **rerun-improvement loop** — multiple closed-book reruns with MCP
fixes applied between, until ≥2 consecutive reruns are green (0 reprompts, full
criteria met, final rerun = set-and-forget / zero permission prompts). A target
passes only when the agent uses the MCP chain as-is with no workarounds. No
release (0.1.0, 0.2.0, 0.3.0) ships until its Tier-1/Tier-2 target list passes.

Aare Valley (3 GB) and Emilia-Romagna (22.6 GB) were originally NOT targets:
Aare's own calibration is ArchPy/Bayesian (not PEST++-based) and ER's size makes
an agent iteration loop impractically slow plus it documents no observations.
**CORRECTED 2026-08-16:** Aare IS a strong 6d target (see Target 3) — the
archive ships a complete MF6 hydrologic model with boundary conditions, pumping
wells and observation points, so the session builds/runs it and calibrates with
PEST++, then compares calibrated values against the published posterior.
ER remains excluded (22.6 GB, no observations). GMS MF6 tutorials are also now
viable (see Target 4): the zips ship the generated MF6 input sets + GIS source
data, so no `.gpr/.gpt` is needed.
**UCODE decision (2026-08-17):** UCODE is no longer part of the project's
calibration scope (the tools were never-implemented stubs and have been
removed) — every target in this playbook calibrates via PEST++ only.

## Pre-registered criteria (per target)

- **check_environment** called first; stack verified before any build.
- **Build / adopt**: models built from data via `create_model` (workspace inside
  the session folder) OR adopted from an existing MF6 input set via
  `adopt_model` (workspace = the model directory); grid/boundaries match the
  source model or the deviation is documented.
- **Run**: `run_simulation` converges / "normal termination".
- **Postprocess**: heads in plausible range, water balance closes, head map
  produced; `read_heads` / `compute_water_balance` / `plot_heads_map` valid.
- **Calibrate** (zenodo-21381071, aare-valley, gms-pest_obs_ss): calibration
  chain run through the MCP tools (`setup_pest_control` → `run_pestpp_ies`/
  `run_pestpp_glm` → `summarise_calibration` → `run_ies_uncertainty`),
  converged or documented with an actionable error.
  (mf6brabant: no committed observations — calibrate against the model's own
  outputs and document; the build/run/postprocess at regional scale is the point.)
- **Reprompts ≤ 1**; every deviation from the source model recorded.
- **Closed-book**: no reading of the groundwater-mcp source, tests, `.kilo`
  plans, or prior research session logs. Reading the *target's own* data,
  notebooks, and scripts is allowed — they ARE the model specification.
- **MCP-only (added 2026-08-22):** every build/adopt/run/postprocess/
  calibrate action goes through a groundwater-mcp tool call. No raw
  `flopy`/`pyemu` Python, no hand-edited MF6/PEST files. Zenodo run 1
  bypassed the MCP entirely for its 94-minute calibration — that is exactly
  what this gate exists to catch. A violation is a protocol deviation
  (same enforcement as closed-book); the tool gap that forced it is still a
  valid finding to log, but the workaround itself invalidates the run for
  whatever it routed around. See `modeB-manual-layer3.md`'s "MCP-only rule"
  section for the full rationale — each target prompt below now inlines the
  same constraint paragraph.

## Setup

1. MCP server registered globally in `~/.config/kilo/kilo.jsonc`
   (`groundwater-mcp_*` auto-allowed; holdout + `.groundwater-mcp` folders
   allow-listed under `permission.external_directory`) — already done.
2. Data staged (2026-08-16): see `research/holdout-registry.md` Round-3 rows.
   - mf6brabant → `GW-MCP-holdout/selected/mf6brabant/` (520 MiB) — run 1 cancelled 2026-08-17d; held until 7e+7f gate work
   - zenodo-21381071 → `GW-MCP-holdout/selected/zenodo-21381071/` (1.28 GiB) — rerun-3 held until 7e+7f gate work
   - aare-valley → `GW-MCP-holdout/selected/aare-valley/` (**download pending**, ~3 GB)
   - gms-pest_obs_ss → already local at
     `GW-MCP-holdout/initial-local/GMS Tutorials/MODFLOW6/mf6_pest_obs_ss.zip`
3. **Gating (2026-08-17d):** the owner promoted ALL of tasks.md § 7e (Tiers A–C)
   and § 7f (Tiers D–I) into the v0.1.0 gate. **No 6d rerun may start until that
   gate work is complete.** Re-check tasks.md before launching any session.
4. Start one Agent Manager **worktree** session per target (they are
   independent; run in parallel). The session folder = the worktree checkout.
   `create_model` must use an explicit `workspace` **inside the session
   folder** (e.g. a `model/` subfolder) so no permission prompts occur.
   `adopt_model` points at the (read-only) holdout model directory — the holdout
   folder is permission allow-listed.

## Rerun-improvement loop (per target)

1. **Run 1 (closed-book):** attempt the full journey; log tool-call sequence,
   reprompts, deviations, and every MCP bug/limitation. Write the session log
   under `research/discovery/sessions/`.
2. **Fix the MCP** before the next rerun (bug fixes + regression tests +
   tools.md updates; tick backlog items in tasks.md).
3. **Rerun (closed-book):** 0-reprompt clean run expected; repeat fix → rerun
   until green.
4. **PASSED** when ≥2 consecutive green reruns, last one set-and-forget (zero
   permission prompts), MCP chain used as-is.
5. Update holdout-registry validation status + tick the 6d checkbox.

## Known 6d-relevant MCP limitations (from Mode B / transient runs)

- `create_model` rejects model names > 16 chars (MF6 MODELNAME cap) — fail early.
- `adopt_model` (40th tool, 2026-08-17) registers an existing MF6 simulation on
  disk without rewriting files — use it for real model directories instead of
  `create_model` + manual file copying. The GWF model name inside the files need
  NOT match the registered name (tools fall back to the first model).
- `run_simulation` / `run_pestpp_*` can hit the 60 s MCP client timeout even
  when the run completes server-side (`-32001`). After a timeout, verify via
  `get_run_log` / listing file before concluding failure.
- `summarise_calibration` may report `phi_progress: []` / `iterations: 0`
  cosmetically even when the log shows iterations.
- PEST++ template tokens must be **wide fixed-width** (`@          k          @`);
  `derinclb` needs a nonzero default. `setup_pest_control` warns on Windows when
  the model command is a `.bat`/`.cmd` wrapper or contains a space in the
  executable path (pestpp cannot launch either) — use a space-free Python
  wrapper. Documented in tools.md / backlog.
- Instruction files: pyemu pif format is `pif @` + `l1 !dum! !o0001!` lines; the
  `[l1]…@o0001@` style is rejected. `input_files` / `output_files` overrides in
  `setup_pest_control` pin the template/instruction target file names.
- **Canonical pif (use this — do NOT reverse-engineer pyemu):** for an output
  file with one observation per line, the instruction file is
  `pif ~` followed by one `l1 !dum! !o0001!` line per observation
  (`!dum!` reads-and-discards a leading dummy column, `!name!` reads the value;
  `w` reads-and-discards a word). One instruction line per output-file line.
  The marker (`~`/`@`) is arbitrary. Same format pyemu's own writer emits
  (`pyemu/utils/pst_from.py:_write_observation_instruction`).
- Regional models are large: scope IES runs (small `num_reals`, `num_workers`)
  and budget time per forward run. Treat tool-payload limits (arrays as JSON)
  as findings to document, not reasons to skip.

### Known limitations added by the implementation audit (2026-08-17b)

Measured, not estimated. Remediation tasks: `tasks.md` § 7e.

- **`read_heads` / `compute_drawdown` return the entire layer array as JSON.**
  Measured at **38.4 MB (~9.6M tokens) for one call** on the zenodo 0205
  domain (1600×1252); ~5 MB per layer on mf6brabant. Until 7e-A1 lands,
  request a single layer at a time, expect the client to truncate, and rely on
  the returned `min`/`max`/`mean` rather than the array. `read_budget` on a
  list-based package with many reaches has the same problem.
- **`summarise_calibration` after a PESTPP-GLM run always reports
  `phi_progress: []` / `iterations: 0`** — it reads `<case>.phi.actual.csv`,
  which only PESTPP-IES writes. GLM's real progress file is `<case>.iobj`
  (columns `iteration,total_phi,measurement_phi,…`). Read that file directly
  and record the phi trace in the run log. If `<case>.rei` is absent the same
  tool reports `rmse: None, n_observations: 0` **as a success** — treat that
  combination as "the run died before residuals", not "zero observations".
- **No array-based recharge/ET (`RCHA`/`EVTA`) and no `idomain` on
  `add_dis_package`** — both block a faithful mf6brabant build (`RP1.tif`
  recharge, `ibound.tif` active domain). Document the deviation and use the
  closest feasible representation (list-based RCH over active cells).
- **Only one boundary package per type** can exist (`add_boundary_package`
  replaces the same type on re-add) — combine boundaries of one type into a
  single call, and record it as a deviation where the source model uses
  several.
- **A grid built with `add_dis_package` has no CRS**, so raster/vector
  sampling silently assumes the model coordinates already match the data.
  Build the grid with `import_grid_from_shapefile` where possible; otherwise
  verify sampled elevations against the source raster before trusting them.
- **Model names are globally unique across the whole machine, forever**, and
  there is no `delete_model`/`list_models` tool. Pick a target-specific name
  (`brabant`, `zen0205`); if `MODEL_EXISTS` fires, choose a new name rather
  than trying to clear the registry.

### Rerun-2 status (zenodo-21381071, 2026-08-17)

Stopped after starting: the agent stalled reverse-engineering pyemu's
instruction-file grammar (grep in the venv site-packages) instead of writing the
pif from the documented format, and hit repeated permission prompts reading
library source. **Rerun-3 must use the canonical pif above** (it is documented
in tools.md) and treat `setup_pest_control`'s pif hint in its description as
authoritative — no venv/site-packages reading needed. No MCP fixes were required
for this stall; it was an agent-format-discovery problem, now documented.
**Rerun-3 is HELD (2026-08-17d):** no 6d rerun starts until the promoted
tasks.md § 7e (Tiers A–C) + § 7f (Tiers D–I) v0.1.0 gate work is complete.

---

## Target 1 — mf6brabant (Brabant NL regional aquifer)

**Data:** `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\mf6brabant\`
(commit `d681f912`, MIT). Steady-state regional model. The repo is
**flopy-script-only for MF6** — inputs are generated at runtime by
`mf6brabant/` + `notebooks/run_mf6_using_external_files.ipynb`. The agent
**reproduces the model via MCP tools from the repo's data** (do NOT run the
repo's scripts to produce the model; use the MCP toolchain). Legacy
MODFLOW-2005 inputs in `data/mf2005/` (triwaco.*) are source material, not MF6.

**Reference facts (physics to reproduce, not answers):** 19 aquifer layers
(reference notebook constructs 37 layers = alternating aquifer/confining),
grid 450 × 601 @ 250 m (delr = delc = 250), origin xll = 60000, yll = 322500,
units METERS/DAYS, steady state (1 SP). Top/botm from `data/topbot/TH*.tif` /
`RL*.tif`; hydraulic conductivity from transmissivity `data/kdc/TX*.tif` (and
confining-layer conductance `CL*.tif`); start heads `data/startingheads/HH*.tif`;
recharge `data/recharge/RP1.tif`; active domain `data/boundary/ibound.tif` +
`boundary.shp`; DRN/GHB/RIV list data in `data/mf2005/*.csv`; pumping wells in
`data/wells/sq_list.csv`. Boundaries: CHD on active boundary cells, DRN, GHB,
RIV, RCH, WEL. No committed observations (`calibration-ready: n`).

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 1 (mf6brabant).

You are a groundwater modelling assistant validating an MCP toolchain on a REAL
regional model. Do NOT read the groundwater-mcp repository source code, its
tests, .kilo plans, or prior research session logs. You MAY read the target
repository's own data, notebooks, and scripts — they are the model
specification. Do NOT run the repository's flopy scripts to generate the model;
build it through the available MCP tools from the repository's data.

DATA: C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\mf6brabant\
(commit d681f912, MIT). Reference facts: steady-state Brabant regional aquifer;
19 aquifer layers (reference constructs 37 alternating layers); grid 450 x 601
@ 250 m; origin xll=60000, yll=322500; units METERS/DAYS, 1 stress period.
Data layout: top/botm in data\topbot (TH*.tif / RL*.tif), transmissivity +
confining conductance in data\kdc (TX*.tif / CL*.tif), start heads in
data\startingheads (HH*.tif), recharge data\recharge\RP1.tif, active domain
data\boundary\ibound.tif + boundary.shp, DRN/GHB/RIV list data in
data\mf2005\*.csv, pumping wells data\wells\sq_list.csv. Boundaries: CHD on the
active boundary, DRN, GHB, RIV, RCH, WEL.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Build the regional model via the MCP tools from this data. create_model with
   a model name <= 16 chars and an explicit workspace inside THIS session
   folder (a "model" subfolder). Reconstruct the grid, layer elevations, K,
   storage-free steady state, and the boundary conditions as faithfully as the
   toolchain allows. Where a tool cannot ingest a data form (e.g. raster-based
   K or CSV boundary lists), document the limitation precisely and proceed with
   the closest feasible representation — the build/run/postprocess at regional
   scale is the point of this run.
3) check_model clean (or documented).
4) run_simulation converges / normal termination. Verify via get_run_log if a
   client timeout occurs.
5) Postprocess: read_heads, compute_water_balance (must close), plot_heads_map.
   Heads should be hydrologically plausible for the Brabant aquifer.
6) No committed observations exist. Exercise the calibration chain by
   calibrating against the model's OWN outputs (e.g. derive a reference head
   field by running the repository's reference notebook in a SCRATCH folder,
   sample heads at well/synthetic observation points, then calibrate your MCP
   model's K against those heads via the MCP calibration chain) and document
   the approach, or document why calibration is skipped.
7) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the reference, convergence evidence, calibration
   results or the documented reason for skipping.

MCP-ONLY CONSTRAINT: every action that builds, runs, or post-processes the
MF6 MODEL ITSELF must go through a groundwater-mcp tool call — do NOT call
flopy/pyemu MODFLOW or PEST classes directly, and do NOT hand-edit MODFLOW
or PEST files with a text editor or shell command. Ordinary Python for
reading/transforming the source GeoTIFF/CSV data before passing it to a
tool is fine. If a groundwater-mcp tool cannot do something you need, STOP
and report exactly what capability is missing and why — do not work around
the gap by building/running/calibrating the model with raw flopy/pyemu
instead; the reference notebook run in step 6 is the one documented
exception (it produces a scratch reference field for comparison, not part
of your MCP model). A workaround invalidates this run: it is testing
whether the MCP tools are sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Target 2 — zenodo-21381071 (real calibrated MF6 + PESTPP-IES ensemble)

**Data:** `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\zenodo-21381071\`
(CC BY 4.0, md5-verified). Sample from Nature Sustainability 2026 supplement
(GMDSI notebook workflow). Extract already done: the sample zip contains a
nested `subdirs_unzip_here.zip` → `simulation/`. **Four complete real model
domains** `simulation/c1/{0205,0501,0504,0505}`, each a full runnable MF6 input
set (DIS 1 layer × 1600 × 1252 @ 250 m, unconfined steady-state) with CHD,
GHB, DRN, RCH, OBS6 head observations (`*.ob_gw`), MODPATH files (out of scope
at v0.1.0), PEST K-zone templates (`parzon_*_tpl.{csv,xlsx}`) and realization
CSVs (`hk_*rlz_*_c1.csv`), plus a `run_mp1a_pcon_<domain>.py` PESTPP-IES driver.

**Important:** the shipped NPF references an external `hk.dat` K array that is
NOT included — it is generated from the `parzon_*_tpl` template + a realization
row (see `run_mp1a_pcon_0205.py` / the sample notebook). The agent must produce
that K input before the model is runnable. Observed head VALUES for the OBS6
wells are not shipped (only names/cell ids) — derive observations from the
model's own reference outputs for calibration and document this.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 2 (zenodo-21381071).

You are a groundwater modelling assistant validating an MCP toolchain on a REAL
calibrated regional model. Do NOT read the groundwater-mcp repository source
code, its tests, .kilo plans, or prior research session logs. You MAY read the
dataset's own README, notebooks, and scripts — they are the model
specification.

DATA: C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\zenodo-21381071\simulation\c1\
Four real domains: 0205, 0501, 0504, 0505 (each a complete MF6 input set, 1
layer x 1600 x 1252 @ 250 m, unconfined steady-state; CHD/GHB/DRN/RCH + OBS6
head observations). The NPF references an external K array (hk.dat) that must
be generated from the domain's parzon_*_tpl template and the shipped hk_*rlz
realization CSV (the run_mp1a_pcon_*.py script and the sample notebook show the
format). MODPATH files are present but OUT OF SCOPE for this run.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Adopt ONE domain (0205 is the smallest) into an MCP workspace using the
   adopt_model tool: pick a model name <= 16 chars and point the workspace at
   the domain directory. The shipped mfsim.nam + package files are the model —
   do NOT rebuild the grid from scratch, do NOT rename files. Generate the
   missing hk.dat K array from the shipped template + a realization, and make
   the model runnable through the MCP tools.
3) check_model clean (or documented).
4) run_simulation converges / normal termination. Verify via get_run_log if a
   client timeout occurs.
5) Postprocess: read_heads, compute_water_balance (must close), plot_heads_map.
6) Calibrate through the MCP calibration chain: setup_pest_control (K-zone
   parameters from the shipped parzon template; wide fixed-width template
   tokens), run_pestpp_ies (scope num_reals/num_workers for the model size and
   the 60 s client timeout), summarise_calibration, then run_ies_uncertainty on
   a forecast. Observed head values are not shipped: derive them from the
   model's own reference outputs and document this pseudo-observation approach.

   INSTRUCTION FILE — use the canonical pyemu pif format (documented in
   tools.md and the setup_pest_control tool description); do NOT read pyemu
   source or probe the venv. For an output CSV with one observation value per
   line, write an instruction file:
       pif ~
       l1 !dum! !o0001!
       l1 !dum! !o0002!
   (one `l1` line per output line; `!dum!` reads-and-discards a leading dummy
   column, `!name!` reads the value; `w` reads-and-discards a word). If the
   output file has a header row or extra columns, match it with `l1`/
   `w`/`!dum!`/`!name!` tokens in order.
7) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, convergence evidence,
   calibration + uncertainty results.

MCP-ONLY CONSTRAINT: every build/adopt/run/postprocess/calibrate action on
the MF6 MODEL ITSELF must go through a groundwater-mcp tool call — do NOT
call flopy/pyemu MODFLOW or PEST classes directly, and do NOT hand-edit MF6
or PEST files with a text editor or shell command. Ordinary Python for data
prep (e.g. reading the parzon template + realization CSV in step 2 and
computing the K array with pandas/numpy) is fine — the array then goes INTO
the model via add_npf_package's k argument, not via a direct flopy call or a
hand-written hk.dat. If a groundwater-mcp tool cannot do something you need,
STOP and report exactly what capability is missing and why — do not work
around the gap by building/running/calibrating the model with raw
flopy/pyemu instead. A workaround invalidates this run: it is testing
whether the MCP tools are sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Target 3 — Aare Valley (Zenodo 8047723; Neven & Renard 2023, WRR)

**Data:** `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\aare-valley\`
(CC BY 4.0; **download pending — stage via playbook step:**
`curl -L -o <zip> "https://zenodo.org/records/8047723/files/PriorPosteriorHydro.zip/content"`
≈ 3 GB, then extract). Archive structure (per record description):
`PriorModel/` (ArchPy, borehole-conditioned), `PosteriorModel/` (ArchPy with
data-assimilation results), **`HydrologicalModel/` = a complete MODFLOW 6 model
"with all the boundary conditions, pumping well and observation points"**,
`LoadAndPlotArchpy.ipynb`, `environment.yml`. The posterior is a published
reference (WRR 2023). Original calibration toolchain is ArchPy/Bayesian — that
is NOT a blocker: this run calibrates the MF6 model with PEST++ and
compares against the published posterior values.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 3 (Aare Valley).

You are a groundwater modelling assistant validating an MCP toolchain on a REAL
published regional model. Do NOT read the groundwater-mcp repository source
code, its tests, .kilo plans, or prior research session logs. You MAY read the
dataset's own notebooks and model files — they are the model specification and
the published reference.

DATA: C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\aare-valley\
(CC BY 4.0, Zenodo 8047723, Neven & Renard 2023 Water Resources Research). The
archive contains: PriorModel/ and PosteriorModel/ (ArchPy stochastic-geology
models — prior/posterior from data assimilation) and HydrologicalModel/ (a
complete MODFLOW 6 hydrologic model with all boundary conditions, pumping
wells and observation points). The published posterior is the reference this
run compares against.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Inspect the archive layout and identify the MF6 model under HydrologicalModel/.
   Adopt it into an MCP workspace: create_model with a model name <= 16 chars
   and an explicit workspace inside THIS session folder; make the model
   runnable through the MCP tools.
3) check_model clean (or documented).
4) run_simulation converges / normal termination. Verify via get_run_log if a
   client timeout occurs.
5) Postprocess: read_heads, compute_water_balance (must close), plot_heads_map.
6) Calibrate the MF6 model with the MCP calibration chain (setup_pest_control →
   run_pestpp_glm or run_pestpp_ies → summarise_calibration) against the
   observation points shipped in the archive. Then COMPARE your calibrated
   parameter values against the published posterior (ArchPy posterior
   realizations in PosteriorModel/) and report how they compare — document
   units and structural differences between the two models.
7) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, convergence evidence,
   calibration results, and the posterior comparison.

MCP-ONLY CONSTRAINT: every action that builds, adopts, runs, post-processes,
or calibrates the MF6 MODEL ITSELF must go through a groundwater-mcp tool
call — do NOT call flopy/pyemu MODFLOW or PEST classes directly, and do NOT
hand-edit MODFLOW or PEST files with a text editor or shell command.
Ordinary Python to read the ArchPy posterior realizations for the step-6
comparison is fine — that's reading a published reference, not building your
model. If a groundwater-mcp tool cannot do something you need, STOP and
report exactly what capability is missing and why — do not work around the
gap by building/running/calibrating the model with raw flopy/pyemu instead.
A workaround invalidates this run: it is testing whether the MCP tools are
sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Target 4 — GMS MODFLOW 6 tutorial (mf6_pest_obs_ss)

**Data:** already local at
`C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
(Aquaveo GMS 10.9 tutorial, ToS — not public domain; local validation use
only). **CORRECTED 2026-08-16:** the zip ships the *generated MF6 input sets*
(`sample/…_models/MODFLOW 6/` — `pest_obs_ss.*` incl. `.disv`/`.nam`/`.npf`/
`.chd`/`.wel`/`.riv`/`.rch` + `_input/` + `_output/` with solved `.hds/.cbc`)
AND a complete PEST observation interface (`GWF_Model_pest/`: `model.pobs`,
`mf6mod2obs.in/.bat`, `smp2smp`, `obs.out`, `pest_obs_stats.txt`), plus DISU
quadtree (MODFLOW-USG) and MF6 quadtree DISV variants. The `.gpr/.gpt` files
are NOT needed. This is the strongest GMS row: real observation + PEST
workflow with solved reference outputs.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 4 (GMS MODFLOW 6 PEST observations).

You are a groundwater modelling assistant validating an MCP toolchain on a
published GMS tutorial model. Do NOT read the groundwater-mcp repository source
code, its tests, .kilo plans, or prior research session logs. You MAY read the
tutorial's own model files and PEST interface files — they are the model
specification and the solved reference.

DATA: C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip
(Aquaveo GMS 10.9 tutorial, local copy). The zip contains a complete MODFLOW 6
model with a PEST observation workflow: generated MF6 input sets (DISV grid;
CHD/WEL/RIV/RCH; `_input/` external arrays), solved reference outputs
(`_output/` .hds/.cbc), and a PEST obs interface (model.pobs, mf6mod2obs,
smp2smp, obs.out, pest_obs_stats.txt). The .gpr/.gpt GMS project files are NOT
needed. Use the MF6 input + PEST files only.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Extract the zip in this session folder. Adopt the MF6 model into an MCP
   workspace using the adopt_model tool: pick a model name <= 16 chars and
   point the workspace at the directory containing the generated MF6 input set
   (use the `sample/…_models/MODFLOW 6/` output — the shipped runnable model —
   or the `_data/Components/` inputs reassembled into a runnable set). Do NOT
   rebuild the grid from scratch. Make the model runnable through the MCP tools.
3) check_model clean (or documented).
4) run_simulation converges / normal termination. Verify via get_run_log if a
   client timeout occurs.
5) Postprocess: read_heads, compute_water_balance (must close), plot_heads_map.
6) Calibrate through the MCP calibration chain (setup_pest_control →
   run_pestpp_glm → summarise_calibration) against the observations defined in
   the shipped PEST interface, and compare your results against the shipped
   solved reference (pest_obs_stats.txt / obs.out).
7) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, convergence evidence,
   calibration results, and the reference comparison.

MCP-ONLY CONSTRAINT: every action that builds, adopts, runs, post-processes,
or calibrates the MF6 MODEL ITSELF must go through a groundwater-mcp tool
call — do NOT call flopy/pyemu MODFLOW or PEST classes directly, and do NOT
hand-edit MODFLOW or PEST files with a text editor or shell command.
Ordinary Python to read pest_obs_stats.txt/obs.out for the step-6 comparison
is fine — that's reading the solved reference, not building your model. If a
groundwater-mcp tool cannot do something you need, STOP and report exactly
what capability is missing and why — do not work around the gap by
building/running/calibrating the model with raw flopy/pyemu instead. A
workaround invalidates this run: it is testing whether the MCP tools are
sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Session log template

`research/discovery/sessions/YYYY-MM-DD-6d-<target>.md`:

```markdown
# 6d session — <target> (regional model validation)
- Date / client / model / worktree branch
- Prompt used: (paste)
- Tool-call sequence: 1. … 2. … (names + one-line outcome each)
- Reprompts: N (describe each)
- Outcome vs criteria: build/adopt, run, postprocess, calibrate (pass/partial/fail + evidence)
- Deviations from the source model: (each documented)
- MCP findings: (tool limitations → v0.2.0 backlog)
- MCP-only violations: N (each: what forced it, the underlying tool gap, whether it derailed the run)
- Time: total minutes
```

## After each session

1. Update the matching Round-3 row's validation status in
   `research/holdout-registry.md`.
2. File any tool-description/limitation findings as v0.2.0 backlog items in
   `tasks.md`.
3. Tick the corresponding 6d checkbox in `tasks.md` when the full criteria
   (build/run/postprocess + calibration where required) are met **across ≥2
   consecutive green reruns** (release-gate policy).
