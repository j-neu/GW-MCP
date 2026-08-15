# Session log — Mode A holdout replay dry-run

- Date: 2026-08-15
- Protocol: Phase C Mode A (pre-registered in `research/holdout-registry.md`)
- Harness: `tests/test_holdout_replay.py` (7 tests, in-process FastMCP, same
  pattern as `tests/test_mcp_protocol.py`)
- Holdout: `C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\`
  (resolved via sibling-default; `GW_MCP_HOLDOUT` env var overrides)

## Prerequisites installed this session

- MODFLOW 6 6.7.0 + legacy binaries → `~/.local/bin` (`get-modflow`)
- PEST++ 5.2.16 (glm/ies/sen/opt/swp/da/mou/sqp) → `~/.local/bin` (`get-pestpp`)
- Verified by the MCP's own `_find_mf6_binary` / `_find_pestpp_binary`.
- Full suite: 157 passed + 49 skipped → **213 passed, 0 skipped, 0 failed**.

## Findings (categorised per plan step 16)

| # | Category | Finding | Disposition |
|---|---|---|---|
| 1 | BUG (pre-existing, fixed) | `setup_pest_control` wrote `noptmax` into the pestpp `++` section; pestpp-glm 5.2.16 rejects unknown `++` args and exits before producing any output — calibration silently did nothing. noptmax is native control data. | Fixed in `calibration.py` (control_data routing) + test corrected. |
| 2 | BUG (pre-existing, fixed) | `test_calibration.py` integration fixture called `_impl_add_npf_package` without `k33` — latent, because the tests were skipped without PEST++ binaries. | Fixture fixed; integration calibration tests now execute. |
| 3 | BUG (pre-existing, fixed) | `compute_water_balance` summed plain-array `FLOW-JA-FACE` (internal cell-to-cell) records as boundary fluxes; only the structured-record variant was skipped. A CHD-only model exposed it (net = -2.27 internal flows). | Fixed in `postprocess.py` (label-level skip). Found by the holdout replay; no API/signature change. |
| 4 | REPLAY DEVIATIONS (documented) | (a) `add_dis_package` does not expose `idomain` → inactive cells (top==botm==0, MF5to6 output) would be zero-thickness and fatal; replay nudges them to 1-unit thickness. (b) GAP stress packages (SFR/UZF/STO/MAW) not replayed at v0.1.0 → water-balance closure asserted only for fully-replayed projects (test020 CHD-only; test051 asserts structure only). (c) test020 uses a synthetic CHD gradient (its only stress is MAW — GAP). | Recorded in the harness docstring + `_BALANCE_EXPECTED`. v0.2.0 item: expose `idomain` in `add_dis_package`. |
| 5 | OBSERVATION | test020's .cbb contains only FLOW-JA-FACE — CHD flux not written as a separate budget record in this configuration (OC BUDGET ALL). Water-balance net=0 is therefore vacuous for it; read_heads plausibility remains the meaningful check. | Note for v0.2.0 (budget record coverage check). |

## Mode A results (dry-run, pre-freeze)

- `test_replay_flow_build_check_run_postprocess[test051_uzfp2]` — **PASS**
  (build → check_model clean → run converges → heads in range → budget →
  balance structure → heads-map PNG; closure not asserted — partial stress)
- `test_replay_flow_build_check_run_postprocess[test020_NevilleTonkinTransient]`
  — **PASS** (same chain; closure asserted — CHD-only)
- Known-limitation gates (5 tests) — **PASS**: no GAP tools exposed
  (DISU/MAW/UZF/LAK/GNC/MVR/STO/GWT/SWT/OBS), unsupported boundary packages
  fail with the structured error envelope, DISU + transport projects sealed
  with no tool path.
- Seal integrity — **PASS**: all 5 selected projects + pools archive present.

## Status

Dry-run complete, harness green, suite green (213). The pre-registered
protocol executes officially at the v0.1.0 freeze (Phase C step 12); findings
above are recorded for the v0.2.0 backlog. No tool signatures or descriptions
were changed by holdout results; fixes 1–3 are pre-existing correctness bugs
exposed by enabling the previously-skipped integration tests.
