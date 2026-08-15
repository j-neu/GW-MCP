# Session log — MODFLOW 6 test-problem suite discovery

**Date:** 2026-08-15
**Playbook:** `research/discovery/playbooks/modflow6-test-problems.md`
**Operator:** discovery agent (deepseek-v4-flash-0731)

## Commit hashes

| Repo | Commit | Date |
|---|---|---|
| MODFLOW-USGS/modflow6 | `88b9a074be81e21e8c74a522716eb59e6d9a0086` | 2026-08-12 |
| MODFLOW-ORG/modflow6-testmodels | `96a6d4fe015967972b051d311d34679224bc6d75` | 2026-08-07 |
| MODFLOW-ORG/modflow6-examples | `ff478a6376612f0bbfd7f9bba0c3268ae651f111` | 2026-08-13 |

## Scan scope & deviations from playbook

- The playbook assumed a `examples/` tree inside the `modflow6` repo. **This no
  longer exists at HEAD (2026-08-12).** `modflow6`'s own README (lines 33–34)
  states the example suite moved to the separate repo
  `MODFLOW-ORG/modflow6-examples` (flopy scripts; inputs generated at runtime,
  only `data/` payloads committed).
- The materialized, .nam-file test-problem suite is
  `MODFLOW-ORG/modflow6-testmodels` → `mf6/` (241 numbered test models, each
  with a `description.txt` and complete MF6 input files). This is the suite
  used by `modflow6`'s autotest (`test_external_models.py` pulls from the
  registry). **All GWF/GNC/MVR/MAW/UZF/LAK/STO/OBS rows are taken from this
  repo, package lists verified from .nam contents.**
- GWT coverage: `modflow6-testmodels/mf6` contains only the 5 `gwtbuy`
  (Henry-type, GWF-GWT coupled with BUY package) tests. The extensive GWT
  suite (`test_gwt_adv01…`, `test_gwt_mst01…` etc., ~90 scripts) lives in
  `modflow6/autotest` as flopy scripts without materialized inputs, and the
  showcase examples (`ex-gwt-*`) live in `modflow6-examples/scripts/`.
  Two representative GWT rows therefore reference `modflow6-examples`
  flopy scripts (input format = flopy script; runnable to produce MF6 input).
- No SWT6 package anywhere: no `*.swt` files, no `SWT6` in any .nam, no swt
  sources in `modflow6/src`, no SWT in ReleaseNotes.tex. SWT v4 exists only as
  a separate standalone binary download (`swtv4` in `autotest/conftest.py`),
  not as an MF6 package. The BUY (buoyancy) package in the `gwtbuy` tests is
  the closest saltwater analogue. **SWT matrix row = RED FLAG (no example).**
- GNC6 present in testmodels (2 nams) but no `gnc` source in `modflow6/src`
  (GhostNode lives under `src/Exchange`); GNC6 still accepted by the .nam
  parser. Test problems `test006_gwf3_gnc` and `test006_gwf3_disv` exercise it.
- No OBS CSV *data* files are committed; observations are OBS6 package files
  (head/flow observation definitions) with expected outputs generated at run
  time. `calibration-ready = y` = OBS6 package present in .nam.

## Catalog rows (14)

| name | source | url | type | capabilities showcased | toolchain | input format | data formats | license | accessibility | download url | size | calibration-ready | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| test006_gwf3_gnc | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test006_gwf3_gnc | test problem | DISU, GNC, CHD, NPF, IC, OC | MF6 GWF | MF6 input | .disu(+aux .area/.cl12/.hwva/.iac/.ja), .nam, .gnc, .chd, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test006_gwf3_gnc (clone on demand, shallow) | 16 | n | MODFLOW-USG doc problem 1; ghost nodes on unstructured grid; GNC6 row ref |
| test009_3lay-disu | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test009_3lay-disu | test problem | DISU, GNC, CHD, NPF, IC, OC | MF6 GWF | MF6 input | .disu, .nam, .gnc, .chd, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test009_3lay-disu (clone on demand, shallow) | 11 | n | 3-layer unstructured grid; DISU row ref |
| test020_NevilleTonkinTransient | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test020_NevilleTonkinTransient | test problem | MAW, STO, OBS, DIS, NPF, IC, OC | MF6 GWF | MF6 input | .dis, .maw(+.maw.obs), .obs, .sto, .nam, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test020_NevilleTonkinTransient (clone on demand, shallow) | 14 | y | Multi-aquifer well (Neville & Tonkin 2004); OBS6 + MAW obs in nam; ~12 variant dirs (aniso, constantMAW, cumcond, TS…) |
| test051_uzfp2 | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test051_uzfp2 | test problem | UZF, SFR, STO, WEL, GHB, OBS, DIS, NPF, IC, OC | MF6 GWF | MF6 input | .dis, .uzf(+.uzf.obs), .sfr, .sto, .nam, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test051_uzfp2 (clone on demand, shallow) | 15 | y | UZF doc problem 2 (Niswonger et al 2006); variants add MVR routing (test051_uzfp2_mvr, test051_uzfp3_lakmvr_*) |
| test045_lake1ss | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test045_lake1ss | test problem | LAK, EVT, RCH, CHD, DIS, NPF, IC, OC | MF6 GWF | MF6 input | .dis, .lak, .evt, .rch, .chd, .nam, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test045_lake1ss (clone on demand, shallow) | 13 | n | Lake package doc problem 1 (Merritt & Konikow 2000), steady state; ~30 lake variants incl. transient/table/embedded |
| test001g_MVR | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test001g_MVR | test problem | MVR, MAW, CHD, DIS, NPF, IC, OC | MF6 GWF | MF6 input | .dis, .mvr, .maw (x2), .chd, .nam, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test001g_MVR (clone on demand, shallow) | 12 | n | MVR row ref; two MAW wells mover; transient variant test001g_MVR_transient |
| test003_gwfs_tr | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test003_gwfs_tr | test problem | STO, DIS, CHD, NPF, IC, OC | MF6 GWF | MF6 input | .dis, .sto, .chd, .nam, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test003_gwfs_tr (clone on demand, shallow) | 12 | n | STO row ref; transient storage with left/right CHD; sibling test003_gwfs steady + test003_gwfs_obs (OBS) |
| test005_advgw_tidal | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test005_advgw_tidal | test problem | OBS, STO, WEL, RIV, RCH (x3), GHB, EVT, DIS, NPF, IC, OC, TDIS/IMS | MF6 GWF | MF6 input | .dis, .obs, .sto, .wel, .riv, .rch, .ghb, .evt, .nam, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test005_advgw_tidal (clone on demand, shallow) | 31 | y | time series + observation demo; multiple BCs incl. 3 recharge zones; calibration-ready (OBS6 in nam) |
| test006_gwf3_disv | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test006_gwf3_disv | test problem | DISV, GNC, CHD, RCH, NPF, IC, OC | MF6 GWF | MF6 input | .disv, .nam, .gnc, .chd, .rch, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test006_gwf3_disv (clone on demand, shallow) | 14 | n | DISV + ghost nodes; trimesh/xt3d variants; DISV+BC calibration-adjacent |
| test201_gwtbuy-henryCHD | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test201_gwtbuy-henryCHD | test problem | GWF-GWT, GWT (ADV/DSP/MST/SSM/CNC), BUY, CHD, WEL, DIS, NPF, IC, OC | MF6 GWF-GWT | MF6 input | .dis, .nam (gwf+gwt), .buy, .adv, .dsp, .sto, .ssm, .cnc, .gwfgwt exchange, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test201_gwtbuy-henryCHD (clone on demand, shallow) | 22 | n | Henry saltwater problem via BUY (buoyancy) — nearest SWT analogue in MF6; 5 variants test201–205 |
| test205_gwtbuy-henrytidal | MODFLOW-ORG/modflow6-testmodels | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test205_gwtbuy-henrytidal | test problem | GWF-GWT, GWT, BUY, STO, DRN, GHB, WEL, DIS, NPF, IC, OC | MF6 GWF-GWT | MF6 input | .dis, .nam (gwf+gwt), .buy, .sto, .gwfgwt exchange, mfsim.nam | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-testmodels/tree/96a6d4fe015967972b051d311d34679224bc6d75/mf6/test205_gwtbuy-henrytidal (clone on demand, shallow) | 24 | n | Henry with tidal boundary; GWF-GWT coupling + STO row ref |
| ex-gwt-prudic2004t2 | MODFLOW-ORG/modflow6-examples | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-prudic2004t2.py | example (flopy script) | GWT, GWF-GWT (FMI), SFR, LAK, MVR, LKT, SFT, OBS, DIS, NPF, IC, OC | MF6 GWF-GWT | flopy script | script + data/ (bot1.dat, chd.dat, idomain1.dat, lakibd.dat, stream.csv, teststrm.sg1-4); MF6 input written at runtime | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-prudic2004t2.py (clone on demand, shallow) | 9 | y | Prudic et al 2004 Test 2: transport through aquifer+streams+lakes; GWT reads GWF via FMI; sfr/lkt/sft obs defined in script |
| ex-gwt-mt3dms-p01 | MODFLOW-ORG/modflow6-examples | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-mt3dms-p01.py | example (flopy script) | GWT (ADV/DSP/MST/SSM), DIS, NPF, IC, CHD, OC, output | MF6 GWT | flopy script | script; MF6 input written at runtime; head/conc files for read_heads/plots | USGS public domain | public GitHub | https://github.com/MODFLOW-ORG/modflow6-examples/tree/ff478a6376612f0bbfd7f9bba0c3268ae651f111/scripts/ex-gwt-mt3dms-p01.py (clone on demand, shallow) | 1 | n | MT3DMS doc problem 1 recreated in GWT; p01–p10 series; water-balance/plots/read_heads workflow in script |

## Coverage summary vs capability matrix

| Matrix row | Ref found |
|---|---|
| DIS | yes (test005_advgw_tidal, test003_gwfs_tr) |
| DISV | yes (test006_gwf3_disv) |
| DISU | yes (test009_3lay-disu, test006_gwf3_gnc) |
| TDIS/IMS | yes (all — mfsim.nam TDIS6/IMS6) |
| STO | yes (test003_gwfs_tr, test020, test051_uzfp2) |
| NPF | yes (all) |
| IC / OC | yes (all) |
| CHD/WEL/RIV/DRN/RCH/EVT/GHB/SFR | yes (test005_advgw_tidal = WEL/RIV/RCH/GHB/EVT; test051_uzfp2 = SFR; SFR MVR: test028_sfr_mvr) |
| MAW | yes (test020_NevilleTonkinTransient) |
| UZF | yes (test051_uzfp2) |
| LAK | yes (test045_lake1ss) |
| GNC | yes (test006_gwf3_gnc) |
| MVR | yes (test001g_MVR, test028_sfr_mvr, test102-105_*_mvr) |
| GWT | yes (ex-gwt-mt3dms-p01, ex-gwt-prudic2004t2; 90+ autotest scripts in modflow6 repo) |
| SWT | **NO example — red flag** (no SWT6 package anywhere; BUY-based Henry tests closest) |
| GWF-GWT | yes (test201/205_gwtbuy, ex-gwt-prudic2004t2) |
| OBS | yes (test005_advgw_tidal, test020, test051_uzfp2, test003_gwfs_obs) |
| pestpp-glm/ies, pestpp-ppu, pestpp-sen, pestpp-pareto/swp, ucode | n/a — no PEST/UCODE content in USGS suite (expected; MCP tools cover) |
| output (read_heads/read_budget) | yes (all problems produce .hds/.cbb; ex-gwt scripts demonstrate readback) |
| water-balance / plots | partial (ex-gwt scripts plot + compute; testmodels are batch-run only) |
| flopy-script | yes (modflow6-examples) |

## Blockers / notes for next round

- `modflow6/examples/` is gone at this commit; playbook's step 2 needs updating
  to point at `modflow6-testmodels` (materialized) + `modflow6-examples`
  (scripts) + `modflow6/autotest` (GWT test scripts).
- SWT is genuinely absent from MF6 — verify against `MODFLOW-USGS/swtv4`
  repo (standalone code) as the row's example source in a later round.
- Test models contain `mf2005/`, `mfnwt/`, `mfusg/` legacy input subdirs and
  `zonebudget/` files in some dirs (size column = top-level file count only).
