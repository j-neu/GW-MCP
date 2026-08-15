# Playbook — MODFLOW 6 test-problem suite (git clone)

**Source:** `https://github.com/MODFLOW-USGS/modflow6` — plus its two sibling
repos. Canonical showcase of every GWF/GWT package the USGS ships.

**Layout as of 2026-08-15 (verified):**
- `modflow6/examples/` **no longer exists at HEAD** — the example suite moved to
  `MODFLOW-ORG/modflow6-examples` (flopy scripts; inputs generated at runtime).
- The materialized `.nam`-bearing test-problem suite is
  `MODFLOW-ORG/modflow6-testmodels` → `mf6/` (241 numbered test models with
  `description.txt` + complete MF6 input files; used by modflow6's autotest).
- Extensive GWT test scripts (~90) live in `modflow6/autotest/` (flopy scripts,
  no materialized inputs).

**Client:** any (no browser needed). **When to run:** discovery rounds and
clone-on-demand during holdout validation.

## Procedure

1. **Shallow clone** (large repo, thousands of problems — never archive it):
   ```powershell
   git clone --depth 1 https://github.com/MODFLOW-ORG/modflow6-testmodels.git <tmp>/modflow6-testmodels
   ```
   Record the resolved commit: `git -C <tmp>/modflow6-testmodels rev-parse HEAD`.
   (The `modflow6` repo itself is only needed for `autotest/` GWT scripts.)
2. **Scan `mf6/`**: each numbered subdirectory is one test model (e.g.
   `test006_gwf3_gnc`, `test051_uzfp2`, `test201_gwtbuy-*`). For each model:
   - Read `description.txt` (purpose, source problem).
   - Inspect the `.nam` files (model nam + `mfsim.nam`) for the package list —
     never trust directory names alone.
   - `OBS6` package present → `calibration-ready: y` (observation CSVs are
     generated at run time; no committed data files).
3. **Extract per problem:** name, relative path, purpose, package inventory
   (map to matrix rows), toolchain (GWF|GWT|SWT|GWF-GWT), input format (MF6
   input / flopy script), data formats, license (repo LICENSE), calibration
   observations present (y/n), size (top-level file count).
4. **Capability-tag** against `research/capability-matrix.md` rows: every
   example maps to ≥1 row. Priority targets for round 1: **DISU, MAW, UZF, LAK,
   GNC, MVR, STO, GWT, GWF-GWT, OBS** — the gap/partial rows. (Known: no SWT6
   package exists anywhere in MF6; variable density is via GWT hydraulic-head
   formulation or the standalone `swtv4` code — tag BUY-based Henry tests as
   the nearest analogue.)
5. **Catalog:** append rows under the `MODFLOW-ORG/modflow6-testmodels`
   section of `research/discovery/catalog.md` (schema at file top). Record
   `download url` as `repo URL + relative path`, plus the commit hash in
   `notes` (re-cloned on demand during validation — do NOT copy files now).
6. **Session log:** `research/discovery/sessions/YYYY-MM-DD-modflow6-test-problems.md`
   (source, date, rows added, commit hash, blockers).

## Rules

- Metadata only. No downloads into the holdout or repo.
- Representative sampling is fine: 8–15 rows covering all priority matrix rows
  beats exhaustive listing. Every GAP row needs ≥1 ref by end of round 1.
- A package that appears in no example is a red flag to record in the log.
