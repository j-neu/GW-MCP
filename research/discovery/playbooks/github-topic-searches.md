# Playbook — GitHub topic searches (per capability)

**Purpose:** find open-source models/tutorials for GAP or thin-coverage matrix
rows that the canonical repos may not showcase well: DISU, MAW, UZF, LAK, GNC,
MVR, GWT, SWT, GWF-GWT coupling, pestpp-sen, pestpp-sweep/pareto.

**Client:** any (no browser needed — GitHub code/repo search via web is
acceptable, but cloning candidate repos and scanning is preferred when the
repo is small).

## Procedure

1. For each target capability, search GitHub:
   - Repos: `https://github.com/search?q=modflow6+<capability>&type=repositories`
   - Code: `https://github.com/search?q=<package-name>+<keyword>&type=code`
   - Also `flopy` discussions/issues referencing the package (via web search)
     and `MODFLOW-USGS/modflow6` issue tags for community examples.
2. For each candidate repo (clone on demand, `--depth 1`):
   - Verify it actually contains a runnable MODFLOW 6 problem using the
     capability (check `.nam`/`.mfsim.nam` files or flopy scripts — not just
     mentions in the README).
   - Record: repo URL, default-branch commit hash, license (from LICENSE /
     README), what it showcases, input format, calibration data present (y/n).
3. Skip-and-note anything that is (a) a fork of a canonical repo (dedupe), or
   (b) not MODFLOW 6 (e.g. MODFLOW-2005/USG — tag `legacy-out-of-scope`).
4. **Catalog:** append rows under the `GitHub topic searches` section of
   `research/discovery/catalog.md`.
5. **Session log:** `research/discovery/sessions/YYYY-MM-DD-github-topics.md`
   with one line per query + hits.

## Fallbacks

- Bot protection / search limits → use websearch for the same queries; record
  hits with URLs.
- Repo too large to inspect → record URL + commit + package claim, mark
  `accessibility: git clone (large)` and move on.
