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
2. Data staged (2026-08-16; relocated to the D: sibling folder 2026-09-05): see
   `research/holdout-registry.md` Round-3 rows.
   - mf6brabant → `GW-MCP-holdout/selected/mf6brabant/` (520 MiB) — **PASSED 2026-09-06**
   - zenodo-21381071 → `GW-MCP-holdout/selected/zenodo-21381071/` (1.28 GiB) — **PASSED 2026-08-30**
   - aare-valley → `GW-MCP-holdout/selected/aare-valley/` (**staged 2026-09-07**, ~3 GB zip
     `PriorPosteriorHydro.zip` verified 3,019,972,140 bytes; extracted root `exportPaper/`)
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

## Worktree hygiene (added 2026-08-23 after the 12 GB bloat)

The first wave of worktrees consumed ~12 GB because they branched from a
pre-deletion commit (`08103b5`) that still tracked the tutorial/GMS archives
(~708 MB of zips + PDFs per checkout, 10x duplicated) plus model run outputs
(.grb/.hds/.cbb/.npy, up to ~2.5 GB per regional run). Rules going forward:

1. **Base is now clean** — current `main` tracks no archives or large files, so
   worktrees created from it start lean. Do not branch validation worktrees
   from old commits; always create them from current `main` (Agent Manager does
   this by default).
2. **Never commit large binaries.** `.gitignore` now excludes `.grb/.hds/.cbb/
   .cbc/.npy/.ucn/*.png/*.csv` — model outputs are validation artifacts, not
   repo content. A committed 829 MB `.grb` would bloat the shared git object
   store permanently.
3. **When a session closes**: extract the raw `run-log.md`/report into
   `research/discovery/sessions/` first (copy it), then stop/remove the
   worktree via Agent Manager (`stop` removes the session; then remove the git
   worktree with `git worktree remove --force .kilo/worktrees/<name>`, retrying
   if a file is briefly locked). Model outputs do not need preserving once the
   session log is written. **Then delete the branch** (`git branch -D <name>`)
   — otherwise committed model inputs keep the objects alive in the shared git
   store forever. The session log is the record; the branch is not a backup.
4. **Keep the model workspace inside the worktree** (unchanged) — the
   ~100 MB fixture data stays in the holdout folder, never copied into
   worktrees.

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

**Data:** `D:\Claude Projects\GW-MCP-holdout\selected\mf6brabant\`
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

DATA: D:\Claude Projects\GW-MCP-holdout\selected\mf6brabant\
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

**Data:** `D:\Claude Projects\GW-MCP-holdout\selected\zenodo-21381071\`
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

DATA: D:\Claude Projects\GW-MCP-holdout\selected\zenodo-21381071\simulation\c1\
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

**Data:** `D:\Claude Projects\GW-MCP-holdout\selected\aare-valley\`
(CC BY 4.0; **staged 2026-09-07** — zip `PriorPosteriorHydro.zip`, 3,019,972,140
bytes verified; `curl` note: the `/records/<id>/files/` URL 404s, use
`https://zenodo.org/api/records/8047723/files/PriorPosteriorHydro.zip/content`).
Extract root is `exportPaper/`. Actual archive structure (differs from the
record description's folder names): `HydrologicalModel/` = a **complete,
runnable MODFLOW 6 input set with solved reference outputs shipped**;
`ArchPyPrior/` (~5 MB) and `ArchPyPosterior/` (~16 GB) = ArchPy stochastic-
geology prior/posterior ensembles (data-assimilation results); `LoadAndPlotArchpy.ipynb`,
`environment.yml`, `ReadME.txt`.

MF6 model facts (verified 2026-09-07): single GWF model `aar_2d`, mfsim.nam +
`aar_2d.{dis,dis.grb,hds,ic,ims,lst,npf,obs,oc,rcha,tdis}`, plus `Aar.riv`,
`Gurbe.riv`, `lake.chd`, `wel.wel`. Grid **1 layer × 205 rows × 202 cols**,
steady state (NPER 1), `TIME_UNITS seconds`, DIS XORIGIN/YORIGIN set
(CH1903+/LV95 ~ EPSG:2056). BCs: RCH (CONSTANT recharge 1.78e-8), WEL (2
wells), CHD (`lake.chd`), **two RIV6 packages** (`Aar.riv`, `Gurbe.riv`), NPF k
CONSTANT 0.03 (m/s) with SAVE_FLOWS. **34 head-observation points Obs0–Obs33**
defined in `aar_2d.obs` (OBS6 continuous → writes `head_obs.csv` at run time);
observation VALUES are NOT shipped. Solved reference present: `mfsim.lst`
"Normal termination of simulation" (elapsed ~1 s), `aar_2d.hds`/`.cbc`/`.grb`.
The posterior is a published reference (WRR 2023). Original calibration
toolchain is ArchPy/Bayesian — that is NOT a blocker: this run calibrates the
MF6 model with PEST++ and compares against the published posterior values.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 3 (Aare Valley).

You are a groundwater modelling assistant validating an MCP toolchain on a REAL
published regional model. Do NOT read the groundwater-mcp repository source
code, its tests, .kilo plans, or prior research session logs. You MAY read the
dataset's own notebooks and model files — they are the model specification and
the published reference.

DATA: D:\Claude Projects\GW-MCP-holdout\selected\aare-valley\exportPaper\
(CC BY 4.0, Zenodo 8047723, Neven & Renard 2023 Water Resources Research).
Layout: HydrologicalModel/ = complete MODFLOW 6 hydrologic model (single GWF
model aar_2d; mfsim.nam + aar_2d.* package files; 1 layer x 205 rows x 202
cols; steady state; TIME_UNITS seconds; CHD/RCH/WEL/RIV BCs incl. TWO RIV6
packages Aar.riv + Gurbe.riv; NPF k CONSTANT 0.03 m/s; 34 OBS6 head points
Obs0-Obs33 in aar_2d.obs; solved reference aar_2d.hds + mfsim.lst shipped,
"Normal termination of simulation"). ArchPyPrior/ and ArchPyPosterior/ =
stochastic-geology prior/posterior ensembles from the paper's data
assimilation; ArchPyPosterior/ is the published reference this run compares
against (~16 GB, ~50 realizations). LoadAndPlotArchpy.ipynb + ReadME.txt
document the format.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Inspect the archive layout and identify the MF6 model under
   HydrologicalModel/. Adopt it into an MCP workspace with the adopt_model tool
   (the shipped mfsim.nam + package files ARE the model — do NOT rebuild the
   grid, do NOT rename files): pick a model name <= 16 chars and point the
   workspace at the HydrologicalModel directory. Make the model runnable
   through the MCP tools. The two RIV6 packages and solved outputs already in
   the directory are part of the adopted model — adopt_model registers the
   existing simulation on disk.
3) check_model clean (or documented).
4) run_simulation converges / normal termination. Verify via get_run_log if a
   client timeout occurs. (The shipped reference run took ~1 s.)
5) Postprocess: read_heads, compute_water_balance (must close), plot_heads_map.
6) Calibrate the MF6 model with the MCP calibration chain (setup_pest_control →
   run_pestpp_glm or run_pestpp_ies → summarise_calibration) against the 34
   shipped observation points. Observed head VALUES are not shipped: derive
   pseudo-observed heads at the Obs0-Obs33 cells from the shipped reference
   aar_2d.hds (or the run's own head_obs.csv) and document this approach.
   Then COMPARE your calibrated parameter values against the published
   posterior (ArchPy posterior realizations in ArchPyPosterior/, e.g. k/facies
   fields P1.*) and report how they compare — document units and structural
   differences between the two models.
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
`D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip`
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

DATA: D:\Claude Projects\GW-MCP-holdout\initial-local\GMS Tutorials\MODFLOW6\mf6_pest_obs_ss.zip
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

## Target 5 — mf6_freyberg (usgs/pestpp PEST++ benchmark)

**Data:** `D:\Claude Projects\GW-MCP-holdout\selected\mf6_freyberg/`
(usgs/pestpp @ `5d49814`, USGS public domain; TM7C26 — White et al. 2020
PEST++ report benchmark; staged in Round-2 holdout). Complete runnable MF6
input set **plus** the shipped PEST++ parameterisation. Verified 2026-09-07:
single GWF `freyberg6`; DIS **3 layers × 40 rows × 20 cols @ 250 m** (meters);
**transient 25 monthly stress periods** (perlen in days, 1 timestep each),
TIME_UNITS days; packages DIS/IC/NPF/STO/OC/WEL/RCH/GHB/SFR (NEWTON) + OBS6
(`head.obs` → `heads.csv`, **26 `trgw_*` head observations** at layers 1 and 3).
Shipped PEST++ interface: array parameterisation with templates (`npf_k_0/1/2`,
`npf_k33_0/1/2`, `sto_ss_*`, `sto_sy_*`, `wel.tpl`, `rch.tpl`, `sfr.csv.ins`,
`freyberg6.lst.ins`), pyemu CSV sets (`*.par_data.csv`/`*.obs_data.csv`), `.pst`
variants (`freyberg6_run/glm/ies/sen/opt/sweep/truth`), and prior covariance
matrices (`glm_prior.cov`, `ies_prior.jcb`, `temporal_loc.jcb`). Solved
`freyberg6.dis.grb` present; the benchmark's "observed" heads.csv series and
`truth.*` files define the reference. No closed-book 6d run yet (the Round-2
2026-08-16 chain PASS was a pre-6d toolchain check, not an Agent Manager
closed-book run).

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 5 (mf6_freyberg PEST++ benchmark).

You are a groundwater modelling assistant validating an MCP toolchain on a real
published PEST++ benchmark model. Do NOT read the groundwater-mcp repository
source code, its tests, .kilo plans, or prior research session logs. You MAY
read the dataset's own model files, PEST++ files, and the report example's data
— they are the model specification and the reference.

DATA: D:\Claude Projects\GW-MCP-holdout\selected\mf6_freyberg\
(usgs/pestpp @ 5d49814, USGS public domain, TM7C26 White et al 2020).
Single GWF model freyberg6: DIS 3 layers x 40 rows x 20 cols @ 250 m
(METERS); TRANSIENT 25 monthly stress periods (perlen in days, 1 timestep
each), TIME_UNITS days; packages DIS/IC/NPF/STO/OC/WEL/RCH/GHB/SFR (NEWTON) +
OBS6 head.obs writing heads.csv (26 trgw_* head observations at layers 1 and
3). The folder also ships the full PEST++ parameterisation: K/k33/STO array
templates (npf_k_*.dat.tpl, npf_k33_*.dat.tpl, sto_ss_*.dat.tpl,
sto_sy_*.dat.tpl), wel/rch templates, par/obs CSV sets, .pst files for
run/glm/ies/sen/opt/sweep/truth variants, and prior covariance matrices
(glm_prior.cov, ies_prior.jcb, temporal_loc.jcb). This is the calibration
reference this run works against.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Adopt the model into an MCP workspace with the adopt_model tool (the shipped
   mfsim.nam + package files ARE the model — do NOT rebuild the grid, do NOT
   rename files): pick a model name <= 16 chars and point the workspace at the
   mf6_freyberg directory. Make the model runnable through the MCP tools.
3) check_model clean (or documented).
4) run_simulation converges / normal termination across all 25 transient stress
   periods. Verify via get_run_log if a client timeout occurs.
5) Postprocess: read_heads (pick representative stress periods, e.g. first/last,
   or the period matching the shipped heads.csv observations), compute_water_balance
   (must close), plot_heads_map.
6) Calibrate through the MCP calibration chain (setup_pest_control →
   run_pestpp_glm or run_pestpp_ies → summarise_calibration) against the shipped
   observation series (heads.csv / the head.obs sites; values as shipped or as
   documented pseudo-observations from the reference run). Calibrate a documented
   parameter set (the shipped K/STO/WEL/RCH array parameterisation, or a clearly
   documented subset) and compare your results against the shipped reference
   (e.g. the benchmark truth files / observed series / prior covariance).
7) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, convergence evidence,
   calibration results, and the reference comparison.

MCP-ONLY CONSTRAINT: every action that builds, adopts, runs, post-processes,
or calibrates the MF6 MODEL ITSELF must go through a groundwater-mcp tool
call — do NOT call flopy/pyemu MODFLOW or PEST classes directly, and do NOT
hand-edit MODFLOW or PEST files with a text editor or shell command.
Ordinary Python for reading the shipped CSV/PEST reference files and preparing
observation CSVs is fine — that is data prep/reference reading, not model
building. If a groundwater-mcp tool cannot do something you need, STOP and
report exactly what capability is missing and why — do not work around the
gap by building/running/calibrating the model with raw flopy/pyemu instead.
A workaround invalidates this run: it is testing whether the MCP tools are
sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Target 6 — neversink_workflow (DOI-USGS, Neversink–Rondout watershed, NY)

**Data:** `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow/`
(DOI-USGS/neversink_workflow @ main, USGS public domain; **staged 2026-09-07**,
~231 MB = `neversink_mf6/` + `processed_data/`). Real watershed MF6 model built
with modflow-setup/flopy 3.3.3 (2021) for the source-water-delineation
workflow (Rondoni & Hunt USGS). Verified 2026-09-07: single GWF `neversink`;
DIS **4 layers × 680 rows × 619 cols @ 50 m** (meters, projected
XORIGIN/YORIGIN); **single steady-state stress period** (perlen 1 d, START
2011-01-01), TIME_UNITS days; packages DIS/IC/NPF/RCH/OC/WEL/CHD/**SFR** +
OBS6 (`neversink.obs`, continuous head `neversink.head.obs`, USGS-well site
ids in layers 1/2/3/4) + SFR obs (`neversink.sfr.obs`). All arrays external
files (`top.dat`, `botm_*.dat`, `idomain_*.dat`, `k0-3.dat`, `k330-333.dat`,
`rch_000.dat`, `wel_000.dat`); shipped solved listings (`mfsim.lst`,
`neversink.list`, `neversink_SFR.chk`) and `neversink.dis.grb`. **No binary
`.hds`/`.cbc` are committed** and no ready-made observed-value table ships in
`neversink_mf6/` — observed head/streamflow series derive from the NWIS /
NY-DEC gage data in `processed_data/` (and the repo's source_data/output),
so the calibration-target approach must be documented (field-obs where a
defensible source exists, else reference-derived pseudo-obs from the shipped
solved listings). The full DOI-USGS repo (source GIS, notebooks, 455 MB
`output/` reference results) stays in the upstream repo — compare against the
shipped solved listings; fetch more only if genuinely needed.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 6 (neversink_workflow watershed model).

You are a groundwater modelling assistant validating an MCP toolchain on a real
published watershed model. Do NOT read the groundwater-mcp repository source
code, its tests, .kilo plans, or prior research session logs. You MAY read the
dataset's own model files and reference listings — they are the model
specification and the reference.

DATA: D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\
(DOI-USGS/neversink_workflow, USGS public domain; Neversink–Rondout basin NY
source-water-delineation model, modflow-setup/flopy 3.3.3 2021).
Layout: neversink_mf6/ = the runnable MODFLOW 6 model (single GWF model
neversink: DIS 4 layers x 680 rows x 619 cols @ 50 m METERS; single steady
stress period, perlen 1 day from 2011-01-01, TIME_UNITS days; DIS/IC/NPF/RCH/
OC/WEL/CHD/SFR + OBS6 continuous head observations neversink.head.obs at
USGS-well sites across layers + SFR obs neversink.sfr.obs; all arrays are
external files top.dat/botm_*.dat/idomain_*.dat/k*.dat/rch_000.dat; shipped
solved listings mfsim.lst + neversink.list + neversink_SFR.chk and
neversink.dis.grb — no binary .hds/.cbc are committed). processed_data/ =
the GIS/geology/K-zone and NWIS / NY-DEC gage sources behind the model
(observed head/streamflow series live here or in the upstream repo's
source_data/output, which is NOT fully staged).

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Adopt the model into an MCP workspace with the adopt_model tool (the shipped
   mfsim.nam + package files ARE the model — do NOT rebuild the grid, do NOT
   rename files): pick a model name <= 16 chars and point the workspace at the
   neversink_mf6 directory. Make the model runnable through the MCP tools.
3) check_model clean (or documented).
4) run_simulation converges / normal termination (large model ~1.7M cells,
   843k active — allow minutes; verify via get_run_log if a client timeout
   occurs).
5) Postprocess: read_heads, compute_water_balance (must close), plot_heads_map.
6) Calibrate through the MCP calibration chain (setup_pest_control →
   run_pestpp_glm or run_pestpp_ies → summarise_calibration) against a
   documented observation set for this model. Observed head/streamflow VALUES
   are not shipped as a ready target table: derive a defensible observed set
   (field observations from the NWIS/NY-DEC data in processed_data/ where
   possible, otherwise reference-derived pseudo-observations from the shipped
   solved listings) and DOCUMENT the approach. Compare your calibrated results
   against the shipped reference (the solved listings reproduce the native
   parameter run).
7) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, convergence evidence,
   calibration results, and the reference comparison.

MCP-ONLY CONSTRAINT: every action that builds, adopts, runs, post-processes,
or calibrates the MF6 MODEL ITSELF must go through a groundwater-mcp tool
call — do NOT call flopy/pyemu MODFLOW or PEST classes directly, and do NOT
hand-edit MODFLOW or PEST files with a text editor or shell command.
Ordinary Python for reading the shipped reference listings / obs CSVs and
preparing observation CSVs is fine — that is data prep/reference reading, not
model building. If a groundwater-mcp tool cannot do something you need, STOP
and report exactly what capability is missing and why — do not work around
the gap by building/running/calibrating the model with raw flopy/pyemu
instead. A workaround invalidates this run: it is testing whether the MCP
tools are sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Target 7 — DISU capability row (test009_3lay-disu)

**What it validates:** fully-unstructured (DISU) grid build/adopt/run/report —
the v0.2.0 DISU capability row and the prerequisite for the `MF6_EnKF_DISU`
Tier-1 target. Introduced 2026-09-13 with the `add_disu_package` capability
(commit `839ebb7`).

**Criteria:** adopt a shipped DISU model and run it; recognise the DISU grid in
`summarise_model`/`model_status`; register observations by sequential node id;
calibrate with `setup_calibration`; build a fresh DISU model with
`add_disu_package`; and report the exact behaviour of the x/y-dependent tools
(which cannot work on a DISU grid defined without vertices).

**Data:** `D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\`
(MODFLOW 6 test009: 3 layers, 228 nodes, nested grid in layer 2, GNC).
Additional gate refs (future reruns): `ex-gwf-radial` (flopy builder script in
`pools/modflow6-examples/scripts/`) and GMS Quadtree
(`initial-local/GMS Tutorials/MODFLOW-USG/Quadtree.zip`).

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d capability row: DISU (fully unstructured grid).

You are a groundwater modelling assistant validating an MCP toolchain on a
published MODFLOW 6 DISU model. Do NOT read the groundwater-mcp repository
source code, its tests, .kilo plans, or prior research session logs. You MAY
read the model's own input files — they are the model specification.

DATA: D:\Claude Projects\GW-MCP-holdout\selected\test009_3lay-disu\
A complete MODFLOW 6 DISU model: a 3-layer model with a nested grid in layer 2
(MODFLOW 6 test problem test009). Files: mfsim.nam, flow.nam, flow.disu (228
nodes, NJA 1372), flow.ic, flow.npf, flow.chd, flow.gnc (ghost-node
corrections), flow.oc, flow.tdis, flow.ims, readme.txt.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Copy the model into this session folder, then adopt it into an MCP workspace
   with the adopt_model tool (model name <= 16 chars, allow_modify=true, and the
   units/time units the model declares). Do NOT rebuild the grid.
3) check_model clean (or documented).
4) run_simulation converges / normal termination. Verify via get_run_log if a
   client timeout occurs.
5) Postprocess on the adopted model: read_heads (report the head statistics),
   compute_water_balance (must close), and summarise_model (report the grid
   block verbatim). Also call model_status and validate_model and report what
   they return for this DISU model.
6) Test the DISU builder path: create a SECOND, brand-new small DISU model with
   add_disu_package (a 3-node line is fine: nodes 1-2-3, IAC [2,3,2], JA
   [0,1,1,0,2,2,1]), add NPF/IC/CHD/OC, flush it, then check_model and
   run_simulation it. On that model register observations with
   import_obs_from_csv using a CSV WITHOUT x/y columns (sequential node
   mapping), then call setup_calibration with a single spec
   {"k": {"target": "npf:k", "scope": "all", "initial": 1.0}} and
   obs_source="model". Report the results and any errors.
7) Explicitly note how the tools behave for operations that need cell x/y on a
   DISU grid with no vertices (plot_heads_map and coordinate-based
   import_obs_from_csv): report the exact error/behaviour, and state whether the
   head map is produced.
8) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, convergence evidence, and the
   results of each criterion above.

MCP-ONLY CONSTRAINT: every action that builds, adopts, runs, post-processes, or
calibrates an MF6 MODEL must go through a groundwater-mcp tool call — do NOT
call flopy/pyemu MODFLOW classes directly, and do NOT hand-edit MODFLOW files
with a text editor or shell command. Ordinary Python to READ a model file or the
solution outputs is fine — that is reading the specification, not building your
model. If a groundwater-mcp tool cannot do something you need, STOP and report
exactly what capability is missing and why — do not work around the gap by
building/running the model with raw flopy instead. A workaround invalidates
this run: it is testing whether the MCP tools are sufficient on their own.

Work step by step and explain what you are doing at each step.
```

---

## Target 8 — MF6_EnKF_DISU (Neckartal DE; sequential EnKF-style data assimilation)

**What it validates:** the sequential data-assimilation chain — `setup_da_control`
→ `run_pestpp_da` → `summarise_da` (7f-DA) — on a real DISU model with real gauge
observations. Introduced 2026-09-13 with the DA capability (commits
`d30a9fc`…`fb7164a`: DA-ready v2 `.pst` + cycle tables, optional weight table,
optional prior ensemble, `summarise_da`, and the end-to-end MCP-only proof in
`sessions/2026-09-13-da-e2e-tiny-model.md`). The tool count is unchanged at 70.

**Data:** `E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\`
(github.com/JanGei/MF6_EnKF_DISU, cloned 2026-09-13; no LICENSE file — verify,
academic/ToS). Verified facts (recon `sessions/2026-09-13-6d-enkf-disu-recon.md`):

- The runnable MF6 model is
  `NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim\`: single GWF model
  `flow` (`mfsim.nam` + `flow.nam`), **DISU 31,831 nodes / NJA 198,261 / 31,522
  active** with **vertices + CELL2D present**, packages DISU/NPF/IC/CHD/OC/RCH/RIV/
  WEL/STO, external arrays in `flow_input/`, solved `flow_output/flow.hds` + `.cbc`.
  `sim.tdis` is **NPER 6, one 1.0-day time step each, TIME_UNITS days** (6×1-day
  transient).
- Gauge data: `csv data\Pegel.csv` (wide table — `Date` + 14 gauge columns, water
  level in m, **-9999 = missing**) and `csv data\Pegel_Cell_ID.csv` (`Name,Cell_ID`
  — the 14 gauges mapped to scalar DISU node ids).
- The repo's own EnKF is bespoke Python over the model (`main.py`,
  `Transient_Run.py`, `generator.py`); it is NOT run in this target — the MCP
  sequential-DA chain replaces it.
- Recon also confirmed adopt → check (clean) → run (converged, 5.7 s) →
  postprocess (heads 305–343 m, balance closes, spec exports) through the MCP, so
  the grid/transient/obs substrate is ready. `plot_heads_map` on this grid was
  fixed 2026-09-13 (tasks.md) — the run produces a head map.

**Pre-registered criteria (Target 8):**

- **check_environment** called first; stack verified before any build.
- **Adopt**: `adopt_model` the shipped sim (model name ≤ 16 chars, workspace = the
  sim directory, `allow_modify=True`); the grid/packages/boundaries match the
  source set (`{DISU, nnodes 31831, nja 198261, n_active 31522}`).
- **Single-step re-expression**: the model is run with **NPER=1/NSTP=1** per cycle
  (see the scope note below); the cycle definition and its deviation from the
  shipped 6-period TDIS are documented.
- **DA setup**: `setup_da_control` returns a DA-ready v2 `.pst` — `noptmax ≥ 1`
  (v5.2.16: `noptmax 0` performs no update), `da_num_reals N`,
  `da_use_simulated_states True`, a `head_state` parameter per gauge cell, and
  populated observation/parameter cycle tables.
- **Run**: the DA engine runs to completion with an N-realisation ensemble over
  the requested cycles and per-cycle state carry-forward observable — either
  `run_pestpp_da` (synchronous) or the equivalent background
  `start_calibration(model, pst_file, method="da")` + `get_job_status`.
- **Summarise**: `summarise_da` returns the per-cycle **post-update** phi, the
  final-cycle phi mean/std, posterior parameter statistics and residuals, with no
  error.
- **Fit**: the gauge observed values are assimilated and the prior→post-update phi
  behaviour is reported. The gauge/head baseline may not be calibrated (phi scale
  arbitrary) — document that rather than fabricate a fit.
- **Reprompts ≤ 1**; every deviation from the source model recorded.
- **Closed-book** and **MCP-only** as in the pre-registered criteria above.
- **PASS bar**: **≥ 2 consecutive green closed-book reruns**, and the **last rerun
  = set-and-forget** (0 permission prompts) with **0 reprompts** and **0 MCP-only
  violations**. A target passes only when the agent uses the MCP chain as-is with no
  workarounds.

**Honest scope notes (target-expressibility):**

- The shipped set is a **6×1-day transient** (NPER 6, one time step each), but
  sequential PEST++-DA requires **one stress period with one time step per cycle**
  (`setup_da_control` refuses anything else). The target **is** expressible, but
  only by re-expressing the TDIS: call
  `set_simulation(model, 1, [<cycle length in days>], [1])` (an MCP tool) and then
  define the DA cycles explicitly — each cycle is one 1-day (or parameter-cycle-
  table-driven) stress period, with heads carried between cycles by
  `da_use_simulated_states`. **The DA cycles therefore do NOT map 1:1 onto the
  model's native 6 stress periods**; this is a required deviation and must be
  recorded in every run log.
- The repo's bespoke EnKF (**15-member pilot-point/kriging ensemble + sequential
  assimilation at `t_enkf=300`**) is **not reproduced**. The MCP chain runs
  PESTPP-DA — an ensemble-Kalman/ensemble-smoother update over a standard K
  parameterisation (`npf:k` `all`/`layer`/`cells`/`zones`), with the prior drawn
  from the parameter bounds or from `prior_ensemble`/`prior_std`. There is no MCP
  tool that generates an ensemble from pilot points by kriging. The pre-registered
  bar is therefore **capability expression** (a real sequential DA run on a real
  DISU model with real gauges), **not numerical equivalence** with the published
  EnKF.
- `Pegel.csv` is a **long daily record** (from 2003, mostly gaps, `-9999` sentinel)
  while the model is only 6 days long; the agent selects the per-cycle observed
  values (aligned to its chosen 1-day periods) and reshapes the wide gauge tables
  into the long `site,date,value,Cell_ID` form `import_obs_from_csv` expects. This
  prep is ordinary Python and allowed; the table then enters the model via the tool.
- The adopted workspace is the holdout sim directory and `setup_da_control`/
  `set_simulation` rewires NPF/IC and regenerates `mfsim.nam` **in place**, so a
  run dirties the holdout. **Run hygiene (required):** restore the sim directory
  from the pristine snapshot `E:\GW-MCP-holdout\_pristine\MF6_EnKF_DISU_sim\`
  before every rerun, so each run starts from the shipped model. `clone_model` to
  a session-folder workspace first is the equivalent MCP-only alternative if the
  holdout must stay pristine; either is acceptable as long as it is documented.
- **Storage relocation (2026-09-15):** the original holdout volume `D:` reports
  exFAT `OperationalStatus: Full Repair Needed`, which caused slow/ stalling model
  I/O (rerun-3 stalled in `pestpp-da` with "MF6 itself 1.2 s" but ~90–130 s wall per
  realisation). The holdout is therefore **mirrored to healthy NTFS `E:`**
  (`E:\GW-MCP-holdout\`) and Target 8 runs against the E: copy; `D:` is retained as
  the un-repaired original. Repair `D:` and remove this note once it is healthy.
- **DISU support (fixed 2026-09-14, commits `8fb4742`/`f5d7a4f`):** the first closed-book
  rerun was blocked because `setup_da_control`'s IC state parameterisation accepted
  DIS/DISV only; it now supports **DISU** and validates all inputs before any model
  write (a rejected call no longer leaves the model on uniform K). See
  `sessions/2026-09-14-6d-enkf-disu-rerun1.md` for the original failure.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 8 (MF6_EnKF_DISU, Neckartal DE; sequential DA).

You are a groundwater modelling assistant validating an MCP toolchain on a REAL
DISU model with real gauge observations. Do NOT read the groundwater-mcp
repository source code, its tests, .kilo plans, or prior research session logs.
You MAY read the target repository's own data, model files, and scripts — they
are the model specification.

DATA: E:\GW-MCP-holdout\selected\MF6_EnKF_DISU\
(github.com/JanGei/MF6_EnKF_DISU, cloned 2026-09-13; no LICENSE file — verify).
Layout: the runnable MF6 model is at
NeckartalModel1718\NeckartalCalib_try_models\MODFLOW 6\sim\ — a single GWF model
`flow` (mfsim.nam + flow.nam): DISU 31,831 nodes / NJA 198,261 / 31,522 active,
vertices + CELL2D present; packages DISU/NPF/IC/CHD/OC/RCH/RIV/WEL/STO; external
arrays in flow_input\; solved outputs flow_output\flow.hds + .cbc. sim.tdis is
NPER 6, one 1.0-day time step each, TIME_UNITS days (a 6x1-day transient).
Gauge data: "csv data\Pegel.csv" (wide table: Date + 14 gauge columns, water
level in m, -9999 = missing) and "csv data\Pegel_Cell_ID.csv" (Name,Cell_ID — the
14 gauges mapped to scalar DISU node ids). The repo's own EnKF is bespoke Python
(main.py / Transient_Run.py / generator.py) and is NOT part of this run.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Adopt the shipped model into an MCP workspace with the adopt_model tool: model
   name <= 16 chars, workspace = the sim directory above, allow_modify=true, and
   the units/time units the model declares. Do NOT rebuild the grid, do NOT rename
   files.
3) check_model clean (or documented).
4) Re-express the run as sequential DA. Sequential PEST++-DA needs exactly ONE
   MF6 stress period with ONE time step per cycle (NPER=1, NSTP=1) — the canonical
   OBS-CSV instruction file reads the first data row, which is the end-of-cycle
   value only with a single time step. The shipped TDIS has NPER=6 (six 1-day
   periods), so call set_simulation(model, 1, [<cycle length in days>], [1], ...)
   to reduce it to one step, then define your DA cycles explicitly (each cycle is
   one 1-day — or cycle-table-driven — stress period; heads carry between cycles).
   Do NOT hand-edit the tdis file.
5) Register the gauges. Build the long observation table the tool expects
   (site,date,value,Cell_ID) from Pegel.csv + Pegel_Cell_ID.csv with ordinary
   Python (allowed data prep: reshape the wide table, treat -9999 as missing,
   select the dates/values for your cycles), then call import_obs_from_csv with
   cellid_col="Cell_ID" (scalar DISU node id; the tool converts to the 1-based OBS
   id) plus the site/date/value columns. Verify the 14 gauges map to the intended
   nodes (e.g. a converged run + compare_to_observed).
6) Set up the DA: call setup_da_control with a K parameterisation on npf:k —
   use scope "all" for this target's gate runs. `scope="multiplier"` preserves
   the heterogeneous K pattern and is the preferred mode in general, but the
   helper script it requires stalls under the background DA job on this
   31,831-node model (open defect: the multiplier/zones model-command wrapper
   freezes before mf6 starts — see the MF6_EnKF_DISU rerun-7 backlog block in
   tasks.md and the neversink-3 / mf6brabant-3 / zenodo-4 findings). Document
   the resulting collapse as a deviation: the shipped 0.864–86,400 m/d /
   10,413-unique K field becomes a single uniform value. Log-transform it.
   Pass cycles=[...], obs_cycles
   mapping every registered site to {cycle: observed value} (the gauge values
   from step 5), par_cycles supplying the per-cycle TDIS perlen, num_reals = your
   ensemble size, noptmax=1 (v5.2.16: noptmax 0 performs NO update), and
   use_simulated_states=True. Report the generated .pst and the state-parameter
   count.
7) Run the assimilation with `start_calibration(model, pst_file, method="da")` —
   a background DA job that returns a job id immediately (poll progress with
   `get_job_status`, stop with `cancel_job`); the DA run is long and a synchronous
   call would exceed the client timeout. Then `summarise_da`. Report the per-cycle
   phi, the final-cycle phi mean/std, posterior parameter statistics, and
   residuals. A cycle-0 prior -> post-update phi improvement is expected where the
   observations inform the parameters; if the gauge/head baseline is not
   calibrated (arbitrary phi scale), document that rather than fabricate a fit.
8) Postprocess: produce a plot_heads_map (this vertex-carrying DISU grid is
   supported) and, on the final cycle, compare_to_observed /
   read_simulated_observations for the gauge fit.
9) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model (especially the 6-period ->
   single-step-cycles re-expression and the PESTPP-DA vs bespoke-EnKF method
   change), convergence/phi evidence, and the DA results.

MCP-ONLY CONSTRAINT: every action that adopts, builds, runs, post-processes, or
calibrates/assimilates the MF6 MODEL ITSELF must go through a groundwater-mcp tool
call — do NOT call flopy/pyemu MODFLOW or PEST classes directly, and do NOT
hand-edit MODFLOW or PEST files with a text editor or shell command. Ordinary
Python for data prep (reshaping Pegel.csv + Pegel_Cell_ID.csv into the observation
CSV) is fine — the table then goes INTO the model via import_obs_from_csv, not via
a direct flopy call or a hand-written file. Do NOT run the repo's EnKF scripts
(generator.py / main.py / Transient_Run.py) — they are raw flopy and bypass the
MCP. If a groundwater-mcp tool cannot do something you need, STOP and report
exactly what capability is missing and why — do not work around the gap by
building/running/assimilating the model with raw flopy/pyemu instead. A workaround
invalidates this run: it is testing whether the MCP tools are sufficient on their
own.

Work step by step and explain what you are doing at each step.
```

---

## Target 9 — 1DSubsidenceModeling-MF6CSUB (California Central Valley 1D CSUB benchmark sites)

**What it validates:** the MODFLOW 6 **CSUB** capability path added for v0.3.0 —
building a CSUB package (delay + no-delay interbeds), CSUB observation records,
compaction/subsidence post-processing, derived time-series observations, and CSUB
interbed-property calibration through `setup_calibration(obs_source="derived")` →
`run_pestpp_ies` → `summarise_calibration`. It is the Tier-1 half of the v0.3.0
CSUB gate (the Tier-2 example rows are listed in `tasks.md` § 7d).

**Provenance:** `https://github.com/leila-saberi/1DSubsidenceModeling-MF6CSUB`,
branch **`Multi-IB`**, pinned commit
**`ff5ef1deafd9aaa228440bee9736f776233f8d74`** (catalogued in
`research/discovery/catalog.md`, GitHub-topic round 1). **License verification
task:** the catalog records license `none` and the staged checkout ships **no
LICENSE file** — treat as unlicensed/academic, local validation use only, and
confirm the upstream license before any redistribution. Local holdout:
`D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB\`
(~103 MB; relocated to the D: sibling folder for closed-book runs — copy a site
into the session worktree and run there, never inside the holdout).

**Data / chosen site (read-only inspection 2026-09-19):** the repo is a 1D CSUB
framework for 50 CA Central Valley benchmark sites; the `Multi-IB` branch carries
the 48 multi-interbed sites (the two single-interbed sites live on `Single-IB`).
**Chosen site: `H201`** — the repo's own `__main__` example
(`model_functions.py:558` calls `build_model(..., use_delay=True)` /
`prep_data(True)`). Verified facts:

- `H201/source_data/H201_lithology.csv`: two aquifer units (`Upper` 131 ft,
  `Middle` 1040 ft) with many sand/clay beds.
- `H201/prep_data.py` sets `nlay = 2` (line 43) and, with `use_delay=True`,
  writes `cdelay = ["nodelay", "delay"]` (lines 106–111) — so the site exercises
  **both no-delay and delay interbeds** and yields **2 layers** (inside the 2–5
  band, at the low end).
- Scratch run (copy of `H201` + `dependencies/` under
  `%TEMP%\kilo\csub-site-check\`, `prep_data.prep_data(True)`) produced
  `processed_data/H201.model_property_data.csv` with 2 columns, `cdelay` =
  `nodelay` (layer 0) / `delay` (layer 1), `clay_thickness_0` = 44 ft (upper) /
  551 ft (middle), plus `H201.ts_data.csv` (dated groundwater levels per aquifer).
- Per-site layout: `source_data/{site}_{lithology,obs_data,sub_data}.csv` +
  `{site}_{par_data,scenario_data,scenario_data_2015,CH_forecast}.xlsx`;
  `output/SimulatedSubsidence_{site}.csv` + `{site}_MeanCH.csv`;
  `ib_results_{site}_*.xlsx` (calibrated interbed parameters); `README.md`;
  `prep_data.py`. Repo root: `workflow.py`, `model_functions.py` (builds the MF6
  1×1-column DIS/NPF/STO/GHB/CSUB6 + head/CSUB OBS), `ies_functions.py`
  (PEST-PyEMU IES), `DWR.py`, a vendored `dependencies/` tree
  (flopy/pyemu/pastas/project_functions) and `bin/{linux,mac,win}/` (MF6 +
  pestpp-ies binaries).

**Pre-registered criteria (Target 9):**

- **check_environment** called first; stack verified before any build.
- **Data prep (allowed):** the agent MAY run the repo's `prep_data.py` to produce
  `processed_data/*.csv` (data preparation, explicitly allowed by the MCP-only
  rule) and MAY transform the source CSVs / processed outputs in ordinary Python.
  The **MF6 model itself** must be built, run, post-processed and calibrated
  **only** through groundwater-mcp tools.
- **Build via MCP:** `create_model` → `set_simulation` → `add_dis_package` (the
  1×1 column with the site's tops/bottoms) → `add_npf_package` →
  `add_ic_package` → `add_sto_package` → `add_boundary_package` (GHB head
  series) → **`add_csub_package`** (11-field `packagedata` with
  `cdelay="nodelay"`/`"delay"`, `ndelaycells`, `cg_theta`/`cg_ske_cr`, CSUB
  observation records and filerecords) → `add_oc_package` → `check_model` →
  `run_simulation` (Newton; converges).
- **Post-process:** `read_compaction` (per-layer compaction + derived cumulative
  subsidence) and `plot_subsidence` (PNG) through the MCP; compare the simulated
  series against the shipped `{site}_sub_data.csv`.
- **Observation interface:** `import_subsidence_observations` registers the
  measured `{site}_sub_data.csv` as a **derived** target with the simulated-series
  recipe.
- **Calibrate:** `setup_calibration` with **`obs_source="derived"`** and at least
  one **`csub:packagedata`** target (`csub:cg_theta` / `csub:cg_ske_cr` /
  `npf:k33` may be added) → `run_pestpp_ies` → `summarise_calibration`.
  Convergence or a documented, actionable error.
- **Reprompts ≤ 1**; every deviation from the source model recorded.
  **Closed-book** and **MCP-only** as in the pre-registered criteria above.
- **Run log required:** `run-log.md` in the session folder with the tool-call
  sequence, reprompts, deviations, convergence evidence and calibration evidence.
- **PASS bar:** **≥2 consecutive green closed-book reruns**, the **last rerun =
  set-and-forget** (0 permission prompts, **0 reprompts**, 0 MCP-only
  violations). A target passes only when the agent uses the MCP chain as-is with
  no workarounds.

**Honest scope notes (target-expressibility):**

- The repo's native build is flopy-script (`model_functions.py` builds
  `ModflowGwfcsub` directly) and its native calibration is a bespoke pyEMU IES
  loop (`ies_functions.py`). **Neither is run.** The target re-expresses the same
  physics through the MCP: the CSUB model is built with `add_csub_package` and
  calibrated with `setup_calibration` + `run_pestpp_ies`. Numerical equivalence
  with the repo's IES posterior is **not** the bar — capability expression (a real
  CSUB model built, run and calibrated through the MCP) is.
- `prep_data.py` is **allowed** as data preparation (it only reads/reshapes CSVs
  and writes `processed_data/*.csv`); the MF6 build must not use the repo's
  `model_functions.py` / `workflow.py` / raw flopy.
- `H201` is 1×1×2 — small enough for a fast calibration, and it contains both
  delay and no-delay interbeds so the CSUB delay path is exercised (the reason
  H201 was selected over the other 2-layer sites `D289`/`J859`/`K852`/`N128`/
  `N200`/`T200`/`W85_RESET`/`X692` and the 3-layer sites).
- The derived-observation path (`obs_source="derived"`) is the only CSUB
  observation interface: CSUB compaction is a model output, not a native MF6
  observation time series the head-OBS reader can consume, so the calibration
  forward wrapper materialises the simulated subsidence series for PEST++ to
  read.

### Prompt (paste verbatim into the Agent Manager session)

```
CLOSED-BOOK VALIDATION RUN — Phase 6d target 9 (1DSubsidenceModeling-MF6CSUB; MODFLOW 6 CSUB).

You are a groundwater modelling assistant validating an MCP toolchain on a real
1D CSUB subsidence benchmark. Do NOT read the groundwater-mcp repository source
code, its tests, .kilo plans, or prior research session logs. You MAY read the
target repository's own data, model files, and scripts — they are the model
specification.

DATA: D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB\
(github.com/leila-saberi/1DSubsidenceModeling-MF6CSUB, branch Multi-IB, commit
ff5ef1deafd9aaa228440bee9736f776233f8d74; license not shipped — local validation
use only). The repo holds 1D MODFLOW 6-CSUB models for 50 CA Central Valley
benchmark sites; this run uses site H201 (the repo's own __main__ example). Each
site folder (e.g. H201\) contains source_data\{site}_lithology.csv,
{site}_obs_data.csv, {site}_sub_data.csv, {site}_par_data.xlsx,
{site}_scenario_data*.xlsx, {site}_CH_forecast.xlsx, output\
SimulatedSubsidence_{site}.csv + {site}_MeanCH.csv, ib_results_{site}_*.xlsx,
README.md, and prep_data.py. The repo root has model_functions.py (builds the MF6
model), workflow.py, ies_functions.py and a vendored dependencies\ tree.

H201 facts (verified read-only): two aquifers (Upper 131 ft, Middle 1040 ft) and
two model layers; with delay enabled, prep_data.py yields cdelay = [nodelay,
delay] — both a no-delay and a delay interbed. Model dimensions are 1 row x 1
column x 2 layers (units FEET/DAYS, Newton solver). obs_data.csv holds dated
groundwater-level observations for each aquifer and sub_data.csv holds the
measured subsidence time series.

SUCCESS CRITERIA:
1) check_environment first; report the stack.
2) Copy the H201 site folder (and the repo's dependencies\ folder) into THIS
   session folder; do NOT run anything inside the holdout and do NOT modify the
   holdout tree. Run the repo's prep_data.py THERE as DATA PREPARATION (or
   reproduce its outputs in ordinary Python) to produce the processed property
   table and the dated groundwater-level series. Transforming the source CSVs in
   ordinary Python is allowed.
3) Build the CSUB model through the MCP tools only. Pick a model name <= 16 chars
   and an explicit workspace inside THIS session folder. create_model ->
   set_simulation -> add_dis_package (1 x 1 x 2 column with the site's layer
   tops/bottoms) -> add_npf_package -> add_ic_package -> add_sto_package ->
   add_boundary_package (GHB head series from the processed groundwater levels)
   -> add_csub_package (11-field packagedata records with cdelay nodelay/delay,
   ndelaycells, cg_theta/cg_ske_cr, and CSUB observation records; use the
   interbed thicknesses/parameters from the processed property table) ->
   add_oc_package -> check_model -> run_simulation. Document any deviation from
   the repo's model_functions.py build.
4) Post-process through the MCP tools: read_compaction (per-layer compaction and
   cumulative subsidence) and plot_subsidence (return the PNG). Compare the
   simulated subsidence series against the site's own sub_data.csv.
5) Register the measured subsidence as a derived observation with
   import_subsidence_observations (from H201's sub_data.csv), then calibrate
   through the MCP chain: setup_calibration with obs_source="derived" and at
   least one csub:packagedata parameter target (add csub:cg_theta /
   csub:cg_ske_cr / npf:k33 as appropriate) -> run_pestpp_ies ->
   summarise_calibration. Report phi progress, parameter estimates vs priors and
   the residual statistics, or a documented, actionable error.
6) Write run-log.md in the session folder: tool-call sequence, reprompts,
   decisions, deviations from the source model, run convergence evidence, and
   calibration evidence.

MCP-ONLY CONSTRAINT: every action that builds, runs, post-processes or
calibrates the MF6 MODEL ITSELF must go through a groundwater-mcp tool call — do
NOT call flopy/pyemu MODFLOW or PEST classes directly, and do NOT hand-edit
MODFLOW or PEST files with a text editor or shell command. Running the repo's
prep_data.py as data preparation and transforming the source CSVs in ordinary
Python are explicitly allowed (they produce inputs, not the model). Do NOT run
the repo's model_functions.py / workflow.py / ies_functions.py — they build and
calibrate the model with raw flopy/pyemu and bypass the MCP. If a groundwater-mcp
tool cannot do something you need, STOP and report exactly what capability is
missing and why — do not work around the gap by building/running/calibrating the
model with raw flopy/pyemu instead. A workaround invalidates this run: it is
testing whether the MCP tools are sufficient on their own.

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
