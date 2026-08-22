# 7f-E session — build-loop write cost (defer writes, flush explicitly)

- Date: 2026-08-17
- Scope: tasks.md § 7f Tier E (E1.1, E1.2, E1.3), promoted into the v0.1.0 gate
  by owner decision 2026-08-17d. Next gate item after 7f-D.
- Method: E1.1 measures the current eager-write build; E1.2 implements deferred
  writes + explicit flush; E1.3 guards wall time against the recorded baseline.

## E1.1 — Baseline measurement (eager writes, current code)

Benchmark: `scripts/benchmark_build.py` — representative 12-call regional-scale
build (create, set_sim, dis, npf, ic, sto, oc, CHD, WEL, RIV, DRN, GHB) with
raster-style top/botm/K arrays. Fixture grid: **5 layers x 100 x 120 (60,000
cells/layer)** — the "same fixture grid" used by the E1.3 guard test.

Two runs (2026-08-17), flopy 3.10.0, Python 3.12, Windows:

| call | run 1 s | run 2 s | bytes |
|---|---|---|---|
| create_model | 0.067 | 0.080 | 286 |
| set_simulation | 0.009 | 0.009 | 526 |
| add_dis_package | 0.186 | 0.215 | 1,227,924 |
| add_npf_package | 0.485 | 0.590 | 2,046,499 |
| add_ic_package | 0.519 | 0.640 | 191 |
| add_sto_package | 0.543 | 0.682 | 368 |
| add_oc_package | 0.527 | 0.694 | 252 |
| add_boundary CHD | 0.548 | 0.575 | 25,180 |
| add_boundary WEL | 0.757 | 0.597 | 312 |
| add_boundary RIV | 0.717 | 0.700 | 898 |
| add_boundary DRN | 0.616 | 0.718 | 718 |
| add_boundary GHB | 0.668 | 0.719 | 21,186 |
| **TOTAL** | **5.641** | **6.219** | **3,324,340** |

Observation: after the first array write (add_dis), every subsequent call takes
~0.5-0.7 s re-serialising the unchanged dis/npf arrays (the workspace file set
is rewritten wholesale by each `save_sim` → `write_simulation`). The per-call
byte delta is ~0 from add_ic onward precisely because the same arrays are
overwritten in place — the quadratic cost is in wall time, not in new bytes.

Recorded baseline for E1.3: **eager 12-call build ≈ 6.2 s** on the fixture
grid. E1.3 asserts the deferred build completes in under half this.

## E1.2 — Deferred writes

Implemented 2026-08-17. `save_sim` now stages the mutation in the cache and
marks the model dirty; the disk write happens at `flush_model` (new tool) or
implicitly at `check_model` / `run_simulation` / `list_model_files`, plus the
calibration handoff (`setup_pest_control`, `run_pestpp_glm`, `run_pestpp_ies`).
Builder/parameterise tools report `written: false` when deferred; flush points
report `flushed: true`. Regression tests: a 5-call build performs exactly one
`write_simulation` (monkeypatched count) and the final on-disk file set is
byte-identical to the same build writing eagerly.

## E1.3 — Wall-time regression guard

Deferred build on the same fixture grid, measured post-E1.2:

| strategy | total s |
|---|---|
| eager (baseline, E1.1) | ~6.2 |
| deferred (E1.2) | **0.73** (8.5x faster; the single flush at the end writes the whole 3.3 MB in 0.58 s; every builder call is now ~1-20 ms) |

`tests/test_build_performance.py` measures both strategies live in the same run
and asserts the deferred build is under half the eager build's wall time.

## Notes / decisions

- `_files_changed` now returns False when no on-disk mtime snapshot exists yet
  (a freshly created, never-flushed model is authoritative in memory); D4.1
  still fires for models with files on disk (adopted models, or after the first
  flush).
- `flush_model` is a no-op (returns `written: false`) for clean or adopted
  read-only models.
- The AttributeError fallback (bare model with no TDIS → write only name files)
  is preserved inside `flush_model`.
