# Playbook — MODFLOW 6 curated examples (git clone)

**Source:** `https://github.com/MODFLOW-ORG/modflow6-examples` (formerly
MODFLOW-USGS org; redirects) — the curated set of MODFLOW 6 example problems,
smaller than the full test-problem suite and written for teaching (each
example pairs flopy scripts with input/output). FloPy's canonical example
scripts live here (flopy's own `examples/` is data-only now).

**Client:** any (no browser needed).

## Procedure

1. **Shallow clone:**
   ```powershell
   git clone --depth 1 https://github.com/MODFLOW-ORG/modflow6-examples.git <tmp>/modflow6-examples
   ```
   Record `git -C <tmp>/modflow6-examples rev-parse HEAD` (default branch: `develop`).
2. **Size check (holdout-archive decision):** measure the full checkout
   (`(Get-ChildItem -Recurse -File | Measure-Object -Property Length -Sum).Sum`)
   and record it. **Decision rule:** if the clone is small (≤ ~50 MB) it is a
   candidate to be archived into the holdout as a curated pool; otherwise treat
   like the test-problems suite (clone on demand, catalog by reference). Log
   the decision in the session log.
3. **Scan:** same metadata extraction as `modflow6-test-problems.md` — README,
   package inventory from `.nam` files or flopy scripts, capability tags.
4. **Capability-tag** against the matrix; round-1 priority rows: DISU, MAW, UZF,
   LAK, GNC, MVR, STO, GWT, SWT, GWF-GWT, OBS.
5. **Catalog:** append rows under the `MODFLOW-USGS/modflow6-examples` section
   of `research/discovery/catalog.md` with commit hash in `notes`.
6. **Session log:** `research/discovery/sessions/YYYY-MM-DD-modflow6-examples.md`
   including the archive-vs-clone-on-demand decision + size measurement.

## Rules

- Metadata only unless the size check decides otherwise (see step 2) — and that
  decision is recorded in `holdout-registry.md`, not executed silently.
- Every row capability-tagged; calibration-ready flagged where observation
  files exist.
