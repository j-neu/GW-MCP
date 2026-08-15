# Playbook — FloPy examples (git clone)

**Source:** `https://github.com/modflowpy/flopy`. **Verified 2026-08-15:** the
flopy repo's `examples/` directory now contains ONLY `data/` and `images/` —
no `ex-*.py` scripts at HEAD or recent tags. The canonical FloPy example
scripts moved to `https://github.com/MODFLOW-ORG/modflow6-examples` (flopy's
own CI checks out that repo and runs its scripts' autotest against flopy HEAD).
Scan THAT repo's `scripts/` instead; record the flopy repo commit as the
toolchain pin. License: flopy is **CC0-1.0** (LICENSE.md / pyproject), NOT MIT;
modflow6-examples has no LICENSE file (USGS-origin content).

FloPy's own examples are the canonical **flopy-script-driven** showcase: every
package has at least one scripted example, and the scripts are directly
reusable as validation inputs for groundwater-mcp (create_model + packages are
the MCP analogue of a flopy script).

**Client:** any (no browser needed).

## Procedure

1. **Shallow clone both repos:**
   ```powershell
   git clone --depth 1 https://github.com/modflowpy/flopy.git <tmp>/flopy
   git clone --depth 1 https://github.com/MODFLOW-ORG/modflow6-examples.git <tmp>/modflow6-examples
   ```
   Record both commits (`git -C <repo> rev-parse HEAD`).
2. **Scan `modflow6-examples/scripts/`**: scripts are named by pattern (e.g.
   `ex-gwf-maw.py`, `ex-gwt-*`, `ex-gwe-*`, `ex-prt-*`). For each script:
   - Read the docstring (often absent — then grep constructor calls
     `flopy.mf6.ModflowGwf*`/`ModflowGwt*` to determine the real package
     composition; never trust filenames alone).
   - Note whether it writes a full runnable MF6 problem (`write_simulation`
     present) vs. only reads/plots.
   - Note whether it references observation/calibration data (`ModflowUtlobs`,
     `pooch.retrieve`, `np.genfromtxt` of observed data).
3. **Capability-tag** against the matrix; round-1 priority rows: DISU, MAW,
   UZF, LAK, GNC, MVR, STO, GWT, SWT, GWF-GWT, OBS. (Known: GNC and SWT/SWI2
   have NO scripts at current commits — old `flopy_swi2_ex*.py` were removed
   and docs still link them = red flag rows.)
4. **Catalog:** append rows under the `flopy examples` section of
   `research/discovery/catalog.md` — `input format: flopy script` for every
   row; `download url` = modflow6-examples URL (flopy repo has no scripts);
   both commits in `notes`.
5. **Session log:** `research/discovery/sessions/YYYY-MM-DD-flopy-examples.md`.

## Rules

- Metadata only; never copy scripts into the repo or fixtures (they are
  reference rows; validation clones them on demand).
- Rows are capability-tagged by the script's actual content, not its filename.
