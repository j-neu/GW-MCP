# Tiny CSUB end-to-end calibration (Task 9)

- **Date**: 2026-09-19
- **Type**: end-to-end integration proof for the CSUB support design
  (`docs/superpowers/specs/2026-09-19-csub-support-and-6d-target-design.md`),
  Tasks 2–8.
- **Test**: `tests/test_csub_end_to_end.py` (2 tests).
- **Script**: none — the test is the artifact; it uses the tool `_impl_*`
  functions directly, no hand-authored model files.

## Verdict

The whole chain composes: builder CSUB package + observations → derived
subsidence registration → `setup_calibration` with a `csub:packagedata` target
and `obs_source="derived"` → pestpp-ies run. pestpp-ies **was present and the
e2e test executed** (not skipped). Both tests pass; the full suite is green
(`730 passed`).

## Environment

| Component | Value |
|---|---|
| Python | 3.12.11 (project venv `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| MF6 | 6.7.0, `C:\Users\jakob\.local\bin\mf6.exe` (present) |
| pestpp-ies | 5.2.16, `C:\Users\jakob\.local\bin\pestpp-ies.exe` (**present → test ran**) |
| Workspace | `%TEMP%\pytest-of-jakob\...` (space-free) |

## The model

Built entirely through the builder tools (`tests/test_csub_end_to_end.py`):

- 1 row × 1 col × 2 layers, DIS, 3 stress periods (`perlen = 1901, 1, 1` days);
  period 0 steady, 1–2 transient.
- NPF `k=k33=1.0`, IC `strt=-1.0`, GHB stepping the head down `-1 → -2 → -3`
  (both layers), STO `ss=sy=0`.
- CSUB: two **no-delay** interbeds (one per layer), `head_based=False`,
  `initial_preconsolidation_head=True`, `specified_initial_interbed_state=True`,
  `sgm=1.7`, `sgs=2.0`, `cg_theta=0.2`, `cg_ske_cr=1e-5`, `beta=2.227e-8`,
  `gammaw=62.48`, `COMPACTION.01/02` cell observations, `strainib` filerecord.

The decimal-year time axis is deliberate: it makes the simulated times
(`1901.0, 1902.0, 1903.0`) fold onto the same `_derived_time_key` as ISO
observed dates (`1902-01-01`, `1903-01-01`), which is how the derived
observation planner matches a date-indexed truth series to a simulated series.

## What ran

1. `test_tiny_csub_derived_setup_assembles_full_chain` (MF6 only) — builds the
   model, runs MF6 once to synthesise truth, registers `base × 1.05` as the
   observed subsidence, and asserts the assembled interface: `OPEN/CLOSE`
   packagedata, template/instruction files, 4 adjustable parameters
   (2 columns × 2 interbeds), the derived plan matched both dates
   (`matching_deferred=False`, no skipped dates) and the stdlib forward wrapper
   was generated.
2. `test_tiny_csub_calibration_end_to_end` (MF6 + pestpp-ies) — same chain plus
   `_impl_run_pestpp_ies(num_reals=6, num_workers=1)`.

### Wall time

| Test | Call time |
|---|---|
| `..._assembles_full_chain` | 0.46 s |
| `..._calibration_end_to_end` | **13.40 s** |

The e2e IES run itself is ~10 s (base MF6 run < 0.5 s; the rest is
pestpp-ies start-up + 3 iterations × 6 realisations). No convergence
difficulty: unlike the Task 1 spike's delay-bed column, this all-no-delay
column converged with the default `MODERATE` IMS and **no Newton option**.

## Observed calibration signal

`_impl_run_pestpp_ies` returned (keys as implemented in `calibration.py`):

```
converged:        True
iterations:       3
num_reals:        6
final_phi_mean:   42.67          # see limitation below
final_phi_std:    30.21
```

pestpp-ies' own `<case>.phi.actual.csv` (ensemble-mean phi, `mean` column):

```
iteration,total_runs,mean,standard_deviation,min,max
0,6,3.48277e-10,3.15619e-10,1.36437e-11,6.99387e-10
1,42,3.48277e-10,3.15619e-10,1.36437e-11,6.99387e-10
2,80,3.48277e-10,3.15619e-10,1.36437e-11,6.99387e-10
```

The tiny absolute phi reflects the observation magnitudes (~1.2e-4 ft), not a
failed run; all 6 realisations produced finite phi and the run terminated
normally.

## Limitations

1. **`final_phi_mean` is an aggregate, not the ensemble-mean phi.**
   `_impl_run_pestpp_ies` parses `.phi.actual.csv` with `_read_phi_csv`, which
   *sums every numeric column* per iteration (`total_runs`, `mean`, `std`,
   `min`, `max`, per-realisation, `base`) and then averages those totals — hence
   42.67 rather than 3.48e-10. This is pre-existing behaviour of the GLM-era
   reader (the summariser uses `_read_ies_phi`, which reads the `mean` column
   correctly). The e2e test therefore asserts `converged is True` (the primary
   signal), `final_phi_mean is not None`, and `iterations >= 1`; it does not
   assert a phi value. Not fixed here: changing `_read_phi_csv` semantics is
   outside Task 9's scope and is a product-behaviour change with its own
   regression surface.
2. **Synthetic truth.** Observed subsidence is `base × 1.05` from the model's
   own run, because pestpp-ies aborts on a perfect prior. That is exactly the
   Task 1 spike's approach and is fine for an integration proof, but it is not
   an independent field dataset.
3. **No-delay sensitivity only.** The Task 1 spike found no-delay `thick_frac`
   numerically silent in its column; this test calibrates `ssv_cc`/`sse_cr`
   (the compaction-controlling storage terms), which are sensitive. Delay-bed
   parameters (`ndelaycells`) are covered by unit tests, not this e2e.
4. **Windows interpreter.** The workspace is space-free and the derived path
   forces the stdlib wrapper; `_space_free_interpreter()` is preferred and this
   venv's space-containing interpreter was only used quoted, and worked.
