# Discovery session log — MODFLOW-USGS/modflow6-examples

- Date: 2026-08-15
- Playbook: `research/discovery/playbooks/modflow6-examples.md`
- Source repo: https://github.com/MODFLOW-USGS/modflow6-examples
- Clone: `C:\Users\jakob\AppData\Local\Temp\kilo\discovery-mf6ex` (deleted after scan)
- Commit (HEAD): `ff478a6376612f0bbfd7f9bba0c3268ae651f111`
- Branch: develop (shallow, depth 1)

## Size check + holdout-archive decision

- Total checkout size: **33.17 MB** (`(Get-ChildItem -Recurse -File | Measure-Object -Property Length -Sum).Sum`)
- File count: **330**
- **Decision: ARCHIVE INTO HOLDOUT** (33.17 MB <= ~50 MB threshold).
  This is a small curated teaching repo (flopy scripts + doc + data, no binary
  outputs, no history in shallow clone). It is a candidate for the curated
  pool in `GW-MCP-holdout`. Per playbook rules the decision is recorded here
  and should be mirrored into `holdout-registry.md` by the orchestrator; no
  files were copied into `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout`
  during this session.
- Note: the repo has NO `.nam`/input files checked in — inputs are generated at
  runtime by FloPy scripts. Releases (`https://github.com/MODFLOW-ORG/modflow6-examples/releases`)
  carry an input-file archive + scenario PDF; the release archive is the
  natural "inputs-only" artifact if a holdout copy of inputs (not scripts) is
  desired.

## Scan notes

- Structure: `scripts/` (79 flopy .py), `data/` (25 example data dirs), `doc/sections/` (one .tex per example), `autotest/`, `.doc/`.
- No LICENSE file in repo (GitHub API reports none); USGS-authored content is public domain.
- Default branch is `develop` (API-verified).
- Capability keyword scan results (Get-ChildItem + Select-String, no rg):
  - DISU: ex-gwf-radial only
  - MAW: ex-gwf-maw-p01/02/03, ex-gwf-csub-p03/04, ex-gwt-mt3dsupp82
  - UZF: ex-gwt-uzt-2d, ex-gwf-sagehen, ex-gwf-drn-p01, ex-gwf-sfr-p01b, ex-gwe-danckwerts
  - LAK: ex-gwf-lak-p01/02, ex-gwt-prudic2004t2, ex-gwt-saltlake (boundary only)
  - MVR: ex-gwf-lak-p02, ex-gwf-sagehen, ex-gwf-sfr-p01b, ex-gwf-lgr, ex-gwf-drn-p01
  - GNC: **no matches anywhere** (ex-gwf-u1gwfgwf explicitly notes it replaces the MODFLOW-USG ghost-node feature)
  - SWT package: **no matches anywhere** (variable density only via GWF+GWT hydraulic-head formulation: henry, saltlake)
  - OBS (flopy obs classes/obs output): ex-gwf-advtidal, ex-gwf-fhb, ex-gwf-radial, ex-gwt-moc3d-p01
  - pestpp/ucode/pest: **no matches** — no calibration tooling in this repo
  - GWF-GWT exchange: uzt-2d, henry, saltlake, gwtgwt-p10, mt3dms-p*, rotate, stallman, etc.
  - STO: nearly all transient GWF examples (advtidal, csub-*, lak-*, maw-*, sagehen, sfr-*, radial)
- `calibration-ready` is therefore only true where observation output is requested: ex-gwf-radial, ex-gwf-advtidal, ex-gwf-fhb, ex-gwt-moc3d-p01.

## Catalog rows (for append under `MODFLOW-USGS/modflow6-examples` in `research/discovery/catalog.md`)

| name | source | url | type | capabilities showcased | toolchain | input format | data formats | license | accessibility | download url | size | calibration-ready | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ex-gwf-radial (rad-disu) | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-radial.py | flopy script + generated MF6 inputs; benchmark vs analytical | DISU, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (WEL), TDIS/IMS, OBS | Python + FloPy, MF6 executable, matplotlib | .py (flopy writes .nam/.disu/...) | MF6 text inputs, binary .hds output, obs csv | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 61.6 KB (script, no data dir) | yes | Radial DISU grid (22 bands x 25 layers); partially penetrating well; head obs at 3 depths every timestep vs Neuman (1974) solution; helper get_disu_radial_kwargs.py. Commit ff478a6 |
| ex-gwf-maw-p01 | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-maw-p01.py | flopy script + generated MF6 inputs; benchmark vs Sokol solution | DIS, TDIS/IMS, STO, NPF, IC, OC, MAW | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 10.7 KB (script) | no | Neville-Tonkin (2004) multi-aquifer well open across two aquifers; Thiem conductance; transient 2.13 d, 50 steps; pumping vs non-pumping compared to Sokol solution. Commit ff478a6 |
| ex-gwt-uzt-2d | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwt-uzt-2d.py | flopy script + generated MF6 inputs; benchmark vs MT3D-USGS/VS2DT | DIS, TDIS/IMS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD), UZF, GWT, GWF-GWT | Python + FloPy, MF6 + MT3D-USGS comparison, matplotlib | .py (flopy; gwfgwt exchange) | MF6 text inputs, binary .ucn/.uzt.bin, budget files | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 27.6 KB (script) | no | 2D profile 10x5 m; UZF/UZT unsaturated-zone transport coupled GWF6-GWT6; 2 scenarios (with/without unsat dispersion; MF6 UZT is advective-only in UZ); Morway et al. (2013) scenario 6. Commit ff478a6 |
| ex-gwf-sagehen | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-sagehen.py | flopy script + generated MF6 inputs; real-watershed demonstration | DIS, TDIS/IMS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD, DRN, SFR), UZF, MVR | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary .hds/.bud/.uzf.bud/.mvr.bud/.sfr.bud, infiltration/ET time-series data (16 files) | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 472.4 KB (script 64.9 + data 407.5) | no | UZF1 test problem 1: Sagehen watershed (73x81, 1 layer, daily SPs, steady-state 1st SP); UZF+SFR+DRN+CHD, MVR routes DRN/UZF runoff to downhill reaches; orographic infiltration factors; 213 reaches. Commit ff478a6 |
| ex-gwf-lak-p02 | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-lak-p02.py | flopy script + generated MF6 inputs; benchmark (LAK3 problem 2, Newton variant) | DIS, TDIS/IMS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD, RCH, EVT, SFR), LAK, MVR | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output; 2 data files | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 26.4 KB (script 21.9 + data 4.5) | no | Two lakes + connecting stream (22 SFR reaches), lake outlets (Manning), MVR moves water SFR->LAK->SFR->LAK->SFR; Newton-Raphson formulation; RCH+EVT; 17x27x5, 1500 d transient. Commit ff478a6 |
| ex-gwf-advtidal | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-advtidal.py | flopy script + generated MF6 inputs; synthetic tidal demo | DIS, TDIS/IMS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (GHB, WEL, RIV, RCH, EVT), OBS | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output, obs csv, tidal time-series data (6 files) | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 20.0 KB (script 14.8 + data 5.2) | yes | Head + flow observations with time series; multiple stress packages of same type (3x RCH); tidal GHB via time series (linear interp), WEL stepwise rates, RIV stage time series; steady + 3x10 d transient. Commit ff478a6 |
| ex-gwt-henry | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwt-henry.py | flopy script + generated MF6 inputs; classic benchmark vs semianalytical/SEAWAT | DIS, TDIS/IMS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (GHB), GWT, GWF-GWT | Python + FloPy, MF6 executable, matplotlib | .py (flopy; gwfgwt exchange) | MF6 text inputs, binary .ucn output | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 8.2 KB (script) | no | Classic Henry problem, hydraulic-head variable-density formulation (Langevin et al. 2020); 80x40, 0.5 d/500 steps; original + low-inflow scenarios; GHB seawater reservoir with mixed concentration BC; no SWT package used. Commit ff478a6 |
| ex-gwt-saltlake | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwt-saltlake.py | flopy script + generated MF6 inputs; benchmark vs Hele-Shaw/SEAWAT | DIS, TDIS/IMS, STO, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD, RCH), GWT, GWF-GWT | Python + FloPy, MF6 executable, matplotlib | .py (flopy; gwfgwt exchange) | MF6 text inputs, binary .ucn output | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 11.4 KB (script) | no | Simmons et al. (1999) salt-finger benchmark; 135x57; negative RCH evaporation boundary with random concentration perturbation; variable density via GWT (no SWT package); 400 min, 60 s transport steps. Commit ff478a6 |
| ex-gwf-csub-p01 | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-csub-p01.py | flopy script + generated MF6 inputs; benchmark (Jacob 1939 train loading) | DIS, TDIS/IMS, STO, NPF, IC, OC | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output; 2 data files (train load) | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 16.8 KB (script 12.3 + data 4.5) | no | Elastic aquifer loading by passing train (CSUB package; CSUB not in capability-tag list, tagged STO); 3-layer half cross-section, 35 cols, 2 SPs (steady 0.5 s + transient 58.5 s/117 steps). Commit ff478a6 |
| ex-gwf-zaidel | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-zaidel.py | flopy script + generated MF6 inputs; benchmark vs analytical (Zaidel 2013) | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD) | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 6.6 KB (script) | no | Discontinuous water table over stair-step impervious base; drying-rewetting stress test (Newton); 200x1x1, 2 scenarios (CHD 1 m / 10 m); representative DIS steady-state. Commit ff478a6 |
| ex-gwf-u1disv | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-u1disv.py | flopy script + generated MF6 inputs; benchmark (MODFLOW-USG nested grid) | DISV, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD) | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 8.8 KB (script) | no | Nested DISV grid from MODFLOW-USG docs (100 m outer / 33.3 m inner); run with standard and XT3D NPF formulations; steady-state CHD 1/0 m; representative DISV. Commit ff478a6 |
| ex-gwf-hani | MODFLOW-USGS/modflow6-examples | https://github.com/MODFLOW-USGS/modflow6-examples/blob/develop/scripts/ex-gwf-hani.py | flopy script + generated MF6 inputs; synthetic anisotropic pumping demo | DIS, TDIS/IMS, NPF, IC, OC, CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR (CHD, WEL) | Python + FloPy, MF6 executable, matplotlib | .py (flopy) | MF6 text inputs, binary output | Public domain (USGS; no LICENSE file in repo) | Public GitHub, no auth | https://github.com/MODFLOW-USGS/modflow6-examples/archive/refs/heads/develop.zip | 7.0 KB (script) | no | Groundwater flow to pumping well under horizontal anisotropy; 51x51x1 steady-state; CHD + WEL; representative DIS flow-only problem commonly used as calibration base case (no obs/pestpp in repo though). Commit ff478a6 |

## Matrix gaps (red flags)

- **GNC**: no example in this repo uses ghost-node correction; `ex-gwf-u1gwfgwf` explicitly implements the MODFLOW-USG problem WITHOUT GNC. GNC row is a gap for this source.
- **SWT**: no example uses the SWT (saltwater) package; variable-density problems (henry, saltlake) use the GWT hydraulic-head formulation instead. SWT row is a gap for this source.
- **pestpp-glm/ies, pestpp-ppu, pestpp-sen, pestpp-pareto/swp, ucode**: no calibration/uncertainty tooling exists in this repo at all (teaching-focused). Calibration-ready is only where OBS output is requested: ex-gwf-radial, ex-gwf-advtidal, ex-gwf-fhb, ex-gwt-moc3d-p01.
- **water-balance / output / plots**: covered implicitly (every example runs `gwf.output.budget()`/head plots via matplotlib, OC save_flows), but there is no dedicated water-balance demonstration beyond standard OC/SAVE flows.

## Post-scan cleanup

- Clone directory `C:\Users\jakob\AppData\Local\Temp\kilo\discovery-mf6ex` deleted after metadata extraction.
- No files copied into the repo or into `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout`.
