# Findings — end-to-end, MCP-only sequential `pestpp-da` run on a tiny transient model

- **Date**: 2026-09-14
- **Type**: validation (Task 5 of the DA-ready-PST orchestrator plan)
- **Test**: `tests/test_da_end_to_end.py::test_mcp_only_sequential_da_run`
- **Binary**: `pestpp-da` **v5.2.16** (`C:\Users\jakob\.local\bin\pestpp-da.exe`) + MF6 6.7.0
  (`C:\Users\jakob\.local\bin\mf6.exe`)
- **Result**: **positive** — the whole chain runs closed-book through the MCP tool callables,
  over 2 DA cycles, with the PST's ensemble size preserved when `run_pestpp_da` is called
  without `num_reals`.

---

## 1. What was driven (all through `mcp.call_tool`, no `_impl_*` shortcuts)

```
create_model → set_simulation → add_dis_package → add_npf_package →
add_ic_package → add_sto_package → add_boundary_package(add_oc_package) →
import_obs_from_csv → setup_da_control → run_pestpp_da → summarise_da
```

The model (1 layer × 4 × 4, Δr = Δc = 100 m, top 50 m, bottom 30 m):

| Piece | Value |
|---|---|
| NPF | `icelltype=0` (confined), `k=5 m/d` |
| IC | `strt=25 m` |
| STO | transient, `ss=1e-4` |
| CHD | (0,0,0) = 40 m, (0,3,3) = 10 m |
| TDIS | `NPER=1`, `NSTP=1`, `perlen=50 d` |
| gauges | `G1` @ (0,1,1), `G2` @ (0,2,2) |

`setup_da_control` was called with `num_reals=5`, `cycles=[0, 1]`, observed
`G1 {0: 31, 1: 32}`, `G2 {0: 23, 1: 24}`, and one log-transformed K multiplier
(`npf:k`, `scope="all"`).

Observed after the run: `converged=True`, `cycles=2`, `final_phi_mean=11.34`, and the
constant is finite. Cycle phis (post-update ensemble mean, from
`da_e2e.global.phi.actual.csv`): cycle 0 = 281745, cycle 1 = 11.34 — the state carry-forward
makes the second cycle far better conditioned.

## 2. Step 0 — `run_pestpp_da` ensemble size is now PST-aware

`_impl_run_pestpp_da(num_reals: int | None = None)` (and the `run_pestpp_da` tool) now only
writes `da_num_reals` when `num_reals` is provided, mirroring the `noptmax=None` handling. An
omitted value preserves the PST's own `da_num_reals`, and the tool reports that effective
value in `result["num_reals"]`.

Evidence in the same e2e run:

- `run_pestpp_da(model, pst_file)` called **without** `num_reals`;
- `result["num_reals"] == 5` (the value `setup_da_control(num_reals=5)` wrote);
- the real binary output header `<case>.phi.actual.csv` is
  `iteration,total_runs,mean,standard_deviation,min,max,0,1,2,3,base` — 5 member columns
  (4 draws + `base`), proof the binary did not run a clobbering 50-member ensemble;
- `.rec` line `number of active realizations: 5`.

Unit-level regression (no binaries): `tests/test_pestpp_da.py::test_run_pestpp_da_omitted_num_reals_preserves_pst_ensemble`.

## 3. Cycle → time mapping (what "cycle" means here)

A DA **cycle is not an MF6 stress period**. The model has exactly one stress period with one
time step (`NPER=1`, `NSTP=1`), which is the sequential-DA requirement enforced by
`setup_da_control` — the canonical OBS-CSV instruction file reads the *first* data row, which
is the end-of-cycle value only when there is one time step per cycle.

- **Cycle 0**: MF6 runs once per ensemble member from IC = 25 m for 50 d. At the end of the
  cycle the simulated heads at the gauge cells are transferred into the `head_state`
  parameters (shared-name state wiring, `da_use_simulated_states True`) and written into the
  IC template target, so the next cycle starts from the previous end-of-cycle heads.
- **Cycle 1**: MF6 runs again from that carried-forward IC for another 50 d.
- The cycle tables are indexed by the DA cycle (`obs_cycle_tbl.csv` header `,0,1`), not by
  stress period.

`noptmax` stays at `setup_da_control`'s default `1` (one ensemble-Kalman update per cycle).
Per the spike, `noptmax=0` on v5.2.16 performs **no** update.

## 4. Wall time

| Portion | Time |
|---|---|
| Full e2e test (build + setup + run + summarise) | **7.1 s** |
| `run_pestpp_da` alone (5 members × 2 cycles, MF6 runs) | **4.1 s** |

Fast enough to leave un-marked in the default suite behind the `pestpp-da`/`mf6` availability
skip guard.

## 5. Limitations / residual notes

- **Phi scale is arbitrary** here because the gauge values are not calibrated to the model's
  simulated heads; cycle 0 phi is large (2.8e5) yet the run still converges and produces finite
  phi. The test therefore asserts finiteness, not a phi threshold.
- **v5.2.16 labels the member columns as `da_num_reals − 1` draws plus a `base` column** (the
  header holds `0..N-2,base` for `da_num_reals=N`). The e2e asserts on that 5-member shape,
  not on `0..4`.
- The same NPER=1/NSTP=1 restriction applies to any sequential DA model; multi-time-step
  cycles would need a forward wrapper (out of scope).
- `da_weight_cycle_table` remains accepted-but-ignored on v5.2.16; weights come from
  `obs_data.csv`, as documented.
- No new tool was added: the tool count is unchanged at 70.
