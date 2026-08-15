# Session log — FloPy examples discovery

**Date:** 2026-08-15
**Playbook:** `research/discovery/playbooks/flopy-examples.md`
**Agent task:** scan FloPy examples directory, produce catalog rows (flopy-script-driven)

## IMPORTANT finding: scripts are no longer in the flopy repo

The playbook assumed scripts (ex-gwf-maw.py etc.) live in `examples/` of the
flopy repo. At current HEAD the flopy repo's `examples/` directory contains
**only `data/` and `images/`** — no scripts, and no `ex-*.py` anywhere in the
repo tree. Verified the same for older tags `3.9.5` and `3.7.0` via the GitHub
API. The flopy repo itself now points to the canonical examples repository:

- `README.md`: "MODFLOW 6 example problems" -> modflow6-examples.readthedocs.io
- `.github/workflows/mf6.yml` (lines ~115-152): checks out
  `MODFLOW-ORG/modflow6-examples` and runs its scripts' autotest against a
  HEAD install of flopy — i.e. this repo is the current canonical home of the
  FloPy example scripts (scripts import `flopy` and are pinned to the flopy
  git HEAD).
- `docs/script_examples.md` in flopy still links to `../examples/scripts/...`
  (flopy_swi2_ex*.py, flopy_henry.py, flopy_lake_example.py) — **broken paths**
  at HEAD; the SWI2/SEAWAT-era scripts are gone from the repo.

**Resolution:** the scan was performed against
`https://github.com/MODFLOW-ORG/modflow6-examples.git` (the official
successor, CI-coupled to flopy). All 12 rows below are flopy-script-driven
validation inputs. Rows have no `flopy`-repo download URL because the files do
not exist there; download URLs point into the modflow6-examples repo, and the
flopy repo is recorded separately.

## Repos scanned

| Repo | URL | Commit (HEAD) |
|---|---|---|
| flopy | https://github.com/modflowpy/flopy.git | `a222eba82d3679a5c870833616161ba92cbf4f4d` |
| modflow6-examples | https://github.com/MODFLOW-ORG/modflow6-examples.git | `ff478a6376612f0bbfd7f9bba0c3268ae651f111` |

Both shallow-cloned (`--depth 1`) into `%TEMP%\kilo\discovery-flopy` /
`discovery-mf6ex`, scanned, then deleted (see Cleanup).

## Scan scope

- flopy repo: full tree grep for `ex-*.py` (0 hits); `examples/` contents
  inspected; LICENSE.md and pyproject.toml read; docs/script_examples.md and
  .github/workflows/mf6.yml reviewed.
- modflow6-examples: all 74 `scripts/ex-*.py` files; per-script docstring
  extraction (most scripts have no module docstring), then package-constructor
  grep (`flopy.mf6.ModflowGwf*/ModflowGwt*/ModflowUtlobs`) to determine real
  capability composition — filenames alone were NOT trusted; `write_simulation`
  presence checked for all; observation/calibration data usage checked
  (`ModflowUtlobs`, `pooch.retrieve`, `np.genfromtxt` of observed data).

## License verification (task asked to verify "MIT (flopy)")

- flopy repo: **NOT MIT.** `LICENSE.md` = USGS public domain + CC0 1.0
  Universal dedication; `pyproject.toml` declares `license = "CC0-1.0"`.
- modflow6-examples repo: **no LICENSE file** and no license statement in
  README. Recorded as such; the underlying toolkit (flopy) is CC0-1.0 and the
  scripts are USGS-origin project material.
- License column below: `CC0-1.0 (flopy; repo LICENSE.md)` for flopy, and
  `no license file (USGS-origin; flopy is CC0-1.0)` for modflow6-examples.

## Catalog rows (12)

Input format = `flopy script` for every row. All rows call
`write_simulation` and produce a full runnable MODFLOW 6 simulation
(valid as MCP create_model validation inputs). Toolchain = Python + FloPy
(dev/HEAD version, per `pixi.toml`: `flopy = { git = "..." }`) + numpy +
matplotlib + modflow-devtools; many scripts read `WRITE`/`RUN`/`PLOT`
environment flags and plot via `flopy.plot.styles`.

| name | source | url | type | capabilities showcased | toolchain | input format | data formats | license | accessibility | download url | size | calibration-ready | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ex-gwf-maw-p01.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-maw-p01.py | flopy script | DIS, MAW, STO, NPF, IC, OC, TDIS/IMS, flopy-script | Python + FloPy (git HEAD) + numpy | flopy script | none (all inputs generated in-script) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-maw-p01.py | 10.7 KB | no (no observations) | MAW well example; writes full MF6 sim (write_simulation); head/flow output post-processed and plotted; no external data; flopy commit a222eba8. |
| ex-gwf-radial.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-radial.py | flopy script | DISU, STO, NPF, IC, OC, TDIS/IMS, OBS, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (WEL), output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | none (DISU radial grid + wells built in-script) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-radial.py | 61.6 KB | partial (head observations via ModflowUtlobs vs analytical solution) | The DISU showcase (radial unstructured grid via flopy DISU utilities); continuous head obs (ModflowUtlobs) compared with analytical solution; full sim; flopy commit a222eba8. |
| ex-gwf-lak-p01.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-lak-p01.py | flopy script | DIS, LAK, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD/RCH/EVT), TDIS/IMS, OBS, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | none (lake problem built in-script) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-lak-p01.py | 14.9 KB | partial (lake-stage obs via ModflowUtlobs vs analytical) | Classic lake-aquifer test (LAK package); continuous stage/flow observations; full sim; flopy commit a222eba8. |
| ex-gwf-drn-p01.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-drn-p01.py | flopy script | DIS, UZF, MVR, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (DRN+WEL+GHB+SFR), TDIS/IMS, water-balance, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | repo data/ex-gwf-drn-p01/ (external input files read via data_path) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-drn-p01.py | 21.5 KB | no (no observations) | UZF + DRN test with MVR mover connecting drain to wells/SFR; seepage results plotted; full sim; flopy commit a222eba8. |
| ex-gwf-lak-p02.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-lak-p02.py | flopy script | DIS, LAK, MVR, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD/RCH/EVT+SFR), TDIS/IMS, OBS, water-balance, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | repo data/ex-gwf-lak-p02/ (external input files) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-lak-p02.py | 21.9 KB | partial (stage obs via ModflowUtlobs) | Lake with SFR inflow + MVR lake-to-stream mover; observation utility active; full sim; flopy commit a222eba8. |
| ex-gwf-sfr-p01b.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-sfr-p01b.py | flopy script | DIS, SFR (CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR), UZF, LAK, MVR, STO, NPF, IC, OC, TDIS/IMS, water-balance, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | repo data/ex-gwf-sfr-p01b/ (external input files) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-sfr-p01b.py | 109.2 KB | no (no observations) | Large streamflow-routing benchmark: SFR + UZF + LAK + MVR all coupled; full sim; flopy commit a222eba8. |
| ex-gwf-sagehen.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-sagehen.py | flopy script | DIS, SFR (CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR), UZF, MVR, STO, NPF, IC, OC, TDIS/IMS, water-balance, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib + gitpython | flopy script | repo data/ex-gwf-sagehen/ (real top/bot/idomain grids as .txt) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-sagehen.py | 64.9 KB | no (no observations) | Real-world Sagehen Creek integrated model: MF2K5-to-MF6 SFR conversion helper, UZF+SFR+MVR; full sim; flopy commit a222eba8. |
| ex-gwf-u1disv.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-u1disv.py | flopy script | DISV, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD), TDIS/IMS, flopy-script | Python + FloPy (git HEAD) + numpy | flopy script | none (all inputs generated in-script) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-u1disv.py | 8.8 KB | no (no observations) | Minimal, clean DISV (unstructured Voronoi-ish grid) steady-state example — best compact DISV baseline for create_model validation; full sim; flopy commit a222eba8. |
| ex-gwf-advtidal.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-advtidal.py | flopy script | DIS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (RIV+WEL+GHB+EVT+RCH), TDIS/IMS, OBS, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | repo data/ex-gwf-advtidal/ (tidal boundary input files) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwf-advtidal.py | 14.8 KB | partial (continuous head + flow-ja-face + GHB obs via ModflowUtlobs) | Advective tidal propagation; transient STO; three observation sets (head, flow-ja-face, GHB flux) read back from output; full sim; flopy commit a222eba8. |
| ex-gwt-keating.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-keating.py | flopy script | GWT, GWF-GWT, OBS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD+RCH), TDIS/IMS, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + pandas + matplotlib | flopy script | repo data/ex-gwt-keating/ (observed-head CSVs, PRT track file) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-keating.py | 22.6 KB | yes (reads observed head time series from data dir; head obs via ModflowUtlobs) | Real-data transport benchmark (Keating); builds coupled GWF + GWT (+ PRT post-processing of particle tracks); GWT-FMI flow coupling; strongest calibration-ready GWF-GWT row; full sim; flopy commit a222eba8. |
| ex-gwt-mt3dsupp82.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-mt3dsupp82.py | flopy script | GWT, GWF-GWT, MAW, MVR, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD), TDIS/IMS, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | none (all inputs generated in-script) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-mt3dsupp82.py | 13.4 KB | no (no observations) | MT3DMS supplement test 82 ported to MF6: GWT transport coupled to GWF with MAW wells and MVR water/contaminant mover; full sim; flopy commit a222eba8. |
| ex-gwt-uzt-2d.py | flopy examples (modflow6-examples repo) | https://github.com/MODFLOW-ORG/modflow6-examples/blob/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-uzt-2d.py | flopy script | GWT, GWF-GWT, UZF, STO, NPF, IC, OC, TDIS/IMS, output, plots, flopy-script | Python + FloPy (git HEAD) + numpy + matplotlib | flopy script | none (built in-script; two dispersivity scenarios) | no license file (USGS-origin; flopy is CC0-1.0) | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-uzt-2d.py | 27.6 KB | no (no observations) | Unsaturated-zone transport test (Morway et al. 2013): GWF with UZF feeding GWT transport; two scenario variants; full sim; flopy commit a222eba8. |

## Matrix coverage and gaps (red flags)

Priority matrix rows covered: DISU (radial), MAW (maw-p01, mt3dsupp82), UZF
(drn-p01, sfr-p01b, sagehen, uzt-2d), LAK (lak-p01, lak-p02, sfr-p01b), MVR
(drn-p01, lak-p02, sfr-p01b, sagehen, mt3dsupp82), STO (most rows), GWT
(keating, mt3dsupp82, uzt-2d), GWF-GWT (keating, mt3dsupp82, uzt-2d), OBS
(radial, lak-p01, lak-p02, advtidal, keating), DIS (maw-p01 etc.), DISV
(u1disv), SFR/boundaries (drn-p01, sfr-p01b, sagehen, advtidal).

Gap rows with NO example found (red flags):

- **GNC** — zero `gnc` matches (case-insensitive) anywhere in the
  modflow6-examples repo. The historical Sagehen example used GNC in the
  flopy-era repo; the current ex-gwf-sagehen.py does not. No GNC example
  exists at this commit.
- **SWT** (saltwater transport; also SWI2) — no ex-swt/ex-swi script exists in
  modflow6-examples; the flopy repo's old SWI2 scripts
  (`examples/scripts/flopy_swi2_ex1..5.py`, referenced by
  `docs/script_examples.md`) have been removed from the flopy repo and are not
  carried over. No runnable SWT/SWI2 flopy-script validation input found at
  this commit (only broken doc links).

Non-gap caveats:

- GWE (energy transport, 8 scripts) and PRT (4 scripts) exist but are not
  matrix rows; noted for future rounds (GWE: ates, barends, bhe, danckwerts,
  geotherm, prt, radial, vsc; PRT: mp7-p01..p04).
- CSUB examples (csub-p01..p04) exist; csub-p01 additionally reads real
  observed compaction data via `pooch.retrieve` (calibration-ready), but CSUB
  is not a matrix row, so no row was written for it.
- License note: task assumption "MIT (flopy)" is wrong — flopy is CC0-1.0
  (USGS public domain); modflow6-examples has no LICENSE file.

## Environment / method notes

- Windows PowerShell; `git clone --depth 1` both repos; scanned with
  Get-ChildItem + Select-String; package composition verified by grep of
  flopy.mf6 constructor calls per script (docstrings were mostly absent).
- One temp clone was deleted by an external cleanup mid-session; re-cloned and
  re-verified (identical commit `ff478a63`).
- flopy pinned via `pixi.toml` to git HEAD (development version, currently
  3.11.0.dev0 per flopy README), so toolchain is "FloPy git HEAD (3.11.0.dev0
  at scan time)".

## Cleanup

Both clones (`discovery-flopy`, `discovery-mf6ex`) deleted after the scan.
No files were copied into the GW-MCP repo or the GW-MCP-holdout folder; no
repo files other than this session log were modified.
