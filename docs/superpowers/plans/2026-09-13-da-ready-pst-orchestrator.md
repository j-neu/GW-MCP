# DA-ready-PST Orchestrator (pestpp-da cycles) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a closed-book agent express a sequential data-assimilation (EnKF) workflow on a real MF6 model through MCP tools only — build a DA-ready PEST++ version-2 control file (cycle tables + optional prior ensemble), run `pestpp-da`, and summarise the result — so the `MF6_EnKF_DISU` Tier-1 target can be validated.

**Architecture:** Add a `setup_da_control` tool that reuses the existing calibration machinery (NPF `k` external-array rewire, template generation, observation registration, forward-command handling) and additionally writes a PEST++ **version-2** control file whose external parameter/observation/model-IO sections carry a `cycle` column, plus the `da_observation_cycle_table` / `da_weight_cycle_table` / `da_parameter_cycle_table` CSVs and the `da_*` `++` options. A companion optional prior-ensemble writer emits `da_parameter_ensemble`. `run_pestpp_da` (already correct as of `388839d`) executes it; `summarise_calibration` gains DA-engine detection. The riskiest unknown — how a MODFLOW 6 transient exposes per-cycle state to `pestpp-da` (`da_use_simulated_states` + `state_par_link`) — is retired first with a tiny-model spike.

**Tech Stack:** Python 3.12, pyemu 1.4.0, FloPy 3.10, PEST++ `pestpp-da` 5.2.16, MODFLOW 6, pytest, ruff, mypy.

## Global Constraints

- Venv: `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`. Run pytest from the repo root.
- Files changed together, patterns from `src/groundwater_mcp/tools/calibration.py` (helpers + `register(mcp)`), `src/groundwater_mcp/utils/grid.py`.
- `ruff check src` and `mypy src` must stay clean; full `pytest -q` green (currently 591).
- Tool count is tracked: `tests/test_mcp_protocol.py::_EXPECTED_TOOL_COUNT` and the expected-tools list, plus `README.md`, `tools.md`, `architecture.md`, `research/capability-matrix.md`.
- **PEST++-DA option names are exact** (unknown control-data keywords are a fatal parse error): `da_num_reals`, `da_observation_cycle_table`, `da_parameter_cycle_table`, `da_weight_cycle_table`, `da_parameter_ensemble`, `da_hotstart_cycle`, `da_stop_cycle`, `da_use_simulated_states`, `da_noptmax_schedule`. There is **no** `da_cycle` / `da_ensemble`.
- **Target binary is `pestpp-da` v5.2.16** (the installed one). Its semantics were verified by the Task 1 spike and differ from the newer `pestpp-da_benchmarks`:
  - `noptmax` = update **iterations per cycle**; **`0` performs NO update** (base parameter set only, 1 realisation) — for an EnKF use `noptmax >= 1` (default 1).
  - Ensemble size: **`da_num_reals` works** and overrides `ies_num_reals` (both accepted).
  - `da_weight_cycle_table` is accepted but **ignored** — observation weights must be non-zero in `obs_data.csv`.
  - Sequential DA runs **one MF6 stress period / one time step per cycle** (`NPER=1`, `NSTP=1`) so the obs-CSV pif's first data row is the end-of-cycle value; per-cycle duration needs a templated `perlen` driven by `da_parameter_cycle_table`.
  - State advance is automatic with `da_use_simulated_states True`: the state parameters are the IC-template tokens, wired by shared obs/param name or by `obs_data.state_par_link` (not both).
- Writes must be **version=2** (`pst.write(path, version=2)`); version-1 cannot express the `cycle` column.
- Closed-book rule applies to Agent Manager validation sessions only: no source/tests reading, no raw flopy/pyemu there — every action through an MCP tool.

---

## Verified PEST++-DA facts (from `pestpp/pestpp-da_benchmarks` + local parse probe)

> **Version warning.** The benchmark below is a *newer* PEST++ build than the installed `pestpp-da` v5.2.16. The Global Constraints section records the v5.2.16-verified semantics (spike, Task 1); where the two disagree, the installed binary governs.

Reference: `github.com/pestpp/pestpp-da_benchmarks` → `mf6_freyberg/template_seq_native/`.

**Control file skeleton (version 2):**
```
pcf version=2
* control data keyword
pestmode                                 estimation
noptmax                                 0
ies_num_reals                           15        # optional; da_num_reals wins when both present
da_num_reals                            5
da_observation_cycle_table              obs_cycle_tbl.csv
da_weight_cycle_table                   weight_cycle_tbl.csv
da_parameter_cycle_table                par_cycle_tbl.csv
da_use_simulated_states                 True
* parameter groups external
<case>.pargp_data.csv
* parameter data external
<case>.par_data.csv
* observation data external
<case>.obs_data.csv
* model command line
mf6
* model input external
<case>.tplfile_data.csv
* model output external
<case>.insfile_data.csv
```

**External section columns:**
- `par_data.csv`: `parnme,partrans,parchglim,parval1,parlbnd,parubnd,pargp,scale,offset,dercom,cycle` — adjustable params use `cycle=-1`.
- `obs_data.csv`: `obsnme,obsval,weight,obgnme,cycle,state_par_link` — table-driven obs use `cycle=-1` and a non-zero weight; `state_par_link` names the state parameter an observation writes (dynamic-state linkage).
- `tplfile_data.csv` / `insfile_data.csv`: `pest_file,model_file,cycle` — the same model file may be written by several cycle-specific templates.

**Cycle tables** (header = empty first cell then integer cycles; one row per name; blank = not applied that cycle):
```
,0,1,2,...
obs_a,12.1,,13.4,...
perlen,31,29,31,...
```

**Verified locally** (probe at `C:\Users\jakob\.local\bin\pestpp-da.exe`): `++da_cycle(1)` → fatal `control file parsing error: the following control data keyword lines were not accepted: da_cycle`; `da_num_reals`/`da_observation_cycle_table` are accepted.

**Note:** pyemu 1.4.0 has no DA helpers, but `Pst.write(version=2)` preserves extra DataFrame columns (`cycle`, `state_par_link`) through `to_csv`, and `_decide_version()` selects v2 when a `cycle` column is present.

---

## File Structure

- `src/groundwater_mcp/tools/calibration.py` — add `_impl_setup_da_control`, `_write_cycle_table`, `_build_da_pst`, `_impl_summarise_da` (or extend `_impl_summarise_calibration`), and the `setup_da_control` / `summarise_da` tool registrations. (Existing file; grows ~250 lines.)
- `tests/test_da_control.py` — new: cycle-table writer, v2 round-trip, option injection, prior-ensemble file, missing-input errors.
- `tests/test_da_end_to_end.py` — new: a tiny transient MF6 model run through MCP tools only with `pestpp-da`.
- `tests/test_mcp_protocol.py` — bump `_EXPECTED_TOOL_COUNT` and expected-tools list (69 → 70 as tools land).
- `tools.md`, `README.md`, `architecture.md`, `research/capability-matrix.md` — tool rows/count.
- `research/discovery/playbooks/6d-regional-model-validation.md` — add the EnKF target prompt (Task 6).
- `docs/superpowers/specs/2026-09-13-da-ready-pst-orchestrator-design.md` — this design's spec companion.

---

## Task 1: Spike — a minimal sequential `pestpp-da` run (retire the riskiest unknown)

**Files:**
- Create: `tests/fixtures/da_spike/` (generated artifacts only; do not commit model binaries)
- Create: `research/discovery/sessions/2026-09-13-da-spike-pestpp-da-sequential.md`
- Test: none (investigation; the deliverable is the findings doc + a rerunnable script under `tools/` or `research/`)

**Interfaces:**
- Consumes: `pestpp-da.exe` at `C:\Users\jakob\.local\bin\pestpp-da.exe`.
- Produces: the exact, minimal file set `pestpp-da` accepts for a sequential run over ≥2 cycles on a model whose state advances between cycles; the decision on how hard the state-linkage task is.

- [ ] **Step 1: Build a tiny 2-cycle transient MF6 model** (dev script, not MCP) with one adjustable K (a template writing `npf.k`) and one head observation per cycle, plus a per-cycle recharge fixed parameter.

- [ ] **Step 2: Hand-author a v2 PST + cycle tables modelled on the freyberg benchmark.** Set `da_num_reals 5`, `noptmax 0`, `da_use_simulated_states True`, `da_observation_cycle_table`, `da_parameter_cycle_table`, and one obs per cycle.

- [ ] **Step 3: Run `pestpp-da <case>.pst` and record the exact parser/runtime errors** verbatim (this is the fast feedback loop — each unknown option/format is a fatal parse error).

- [ ] **Step 4: Iterate until it runs ≥2 cycles**, then read the outputs (`<case>.phi.actual.csv`, `<case>.0.par.csv`, `<case>.0.obs.csv`, `<case>.da.*`).

- [ ] **Step 5: Write the findings doc** `research/discovery/sessions/2026-09-13-da-spike-pestpp-da-sequential.md` with: the exact working file contents, the cycle→time mapping that worked, whether `state_par_link` was needed, and the pitfalls. This doc drives Tasks 2–3.

- [ ] **Step 6: Commit** the findings doc and the spike script (no model outputs).

```bash
git add research/discovery/sessions/2026-09-13-da-spike-pestpp-da-sequential.md
git commit -m "docs(da): spike a minimal sequential pestpp-da run (cycle tables + state link)"
```

---

## Task 2: `setup_da_control` — v2 PST with cycle tables + `da_*` options

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py` (add `_write_cycle_table`, `_impl_setup_da_control`, `setup_da_control` registration)
- Test: `tests/test_da_control.py`

**Interfaces:**
- Consumes: `_restore_or_snapshot_k_base`, `_impl_rewire_npf_k_external`, `_impl_generate_tpl`, `_normalise_parameterisation`, `_tpl_substitute`, `_needs_forward_wrapper`, `_generate_forward_wrapper`, `read_meta` — all existing in `calibration.py`.
- Produces: `_impl_setup_da_control(model, parameterisation, cycles, obs_cycles, obs_weights=None, par_cycles=None, num_reals=50, noptmax=1, use_simulated_states=True, da_options=None) -> dict` returning `{model, pst_file, template_file, target_file, ic_template_file, cycle_tables: {obs, parameter?}, n_observations, n_adjustable_parameters, n_state_parameters, n_cycles, model_command, next_steps}`.

- [ ] **Step 1: Write the failing cycle-table-writer test**

```python
def test_write_cycle_table(tmp_path):
    from groundwater_mcp.tools.calibration import _write_cycle_table

    p = tmp_path / "obs_cycle_tbl.csv"
    _write_cycle_table(p, ["S1", "S2"], [0, 1], {"S1": {0: 12.5, 1: 13.0}, "S2": {1: 9.0}})
    assert p.read_text().splitlines()[0] == ",0,1"
    rows = {ln.split(",")[0]: ln.split(",")[1:] for ln in p.read_text().splitlines()[1:]}
    assert rows["S1"] == ["12.5", "13"]
    assert rows["S2"] == ["", "9"]
```

- [ ] **Step 2: Run it and confirm it fails** — `pytest tests/test_da_control.py::test_write_cycle_table -q` → `ImportError`.

- [ ] **Step 3: Implement `_write_cycle_table`**

```python
def _write_cycle_table(
    path: Path, names: list[str], cycles: list[int], values: dict
) -> None:
    """Write a PEST++-DA cycle table (header = '' then integer cycles)."""
    lines = ["," + ",".join(str(int(c)) for c in cycles)]
    for name in names:
        by_cycle = values.get(name, {})
        row = [f"{by_cycle[c]:g}" if c in by_cycle and by_cycle[c] is not None else ""
               for c in cycles]
        lines.append(f"{name}," + ",".join(row))
    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run the test** → PASS.

- [ ] **Step 5: Write the failing v2-round-trip test**

```python
def _da_model(tmp_path, name="damodel"):
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 2, [1.0, 1.0], [1, 1], "simple")
    _impl_add_dis_package(name, 1, 2, 2, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def test_setup_da_control_writes_v2_cycle_tables(tmp_path):
    import pyemu

    name = _da_model(tmp_path)
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles={"S1": {0: 30.0, 1: 29.0}},
        num_reals=5,
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_num_reals"]) == "5"
    assert str(pst.pestpp_options["da_observation_cycle_table"]).endswith(".csv")
    assert int(pst.control_data.noptmax) == 1
    # version 2 + cycle column survive the write
    text = Path(res["pst_file"]).read_text()
    assert "version=2" in text.replace(" ", "")
    assert "cycle" in pst.observation_data.columns
```

- [ ] **Step 6: Run it** → FAIL (`_impl_setup_da_control` missing).

- [ ] **Step 7: Implement `_impl_setup_da_control`** — reuse the `setup_calibration` non-zoned path for the K rewire/template/initial substitution and the forward-command decision, then build a `pyemu.Pst` with `pyemu.pst_utils.generic_pst(par_names, obs_names)`, set `model_input_data`/`model_output_data` with a `cycle=-1` column, set `observation_data["cycle"]=-1` and `observation_data["state_par_link"]=""`, set `parameter_data["cycle"]=-1`, write the obs cycle table (and weight table when `obs_weights` given), set `pestpp_options` (`da_num_reals`, `da_observation_cycle_table`, `da_use_simulated_states`, plus `da_options`), set `control_data.noptmax` (default 1), apply `derinclb=0.01`, and `pst.write(pst_path, version=2)`. Return the `dict` in **Interfaces**. Note: the DA observation interface is built from `obs_cycles` (per-site, per-cycle values) rather than `_build_model_obs_interface` (which is single-row/steady-state); generate one instruction-file token per site reading that site's column at the current cycle — spike findings decide the exact line.

  **Also required (from the Task 1 spike, `research/discovery/sessions/2026-09-13-da-spike-pestpp-da-sequential.md` §8 — read it as the authoritative build checklist):**
  - Parametrize the model's **IC `strt`** as an external `OPEN/CLOSE` array and generate a **state-augmented IC template** whose tokens are the **state parameter names** (one per state cell — the observed sites), so `da_use_simulated_states True` can carry each cycle's simulated heads into the next cycle's IC. Add those state parameters to the PST (non-adjustable, group `head_state`, `cycle=-1`). Reuse the existing ``_restore_or_snapshot``/rewire helpers where possible; the K rewire alone is not enough.
  - The model must write an **MF6 OBS CSV** for the instruction file to read (register sites via `import_obs_from_csv`); the canonical pif (`_impl_generate_ins_from_obs_csv`) reads the **first data row**, so require **`NPER=1`, `NSTP=1` per cycle** and return a clear error if the model's TDIS is not single-step (or document a forward-wrapper fallback).
  - Emit the exact working shapes from the spike: `pargp_data.csv` (10-col), `par_data.csv` (11-col + optional `state_par_link`), `obs_data.csv` (non-zero weights), `tplfile_data.csv`/`insfile_data.csv`, `* model command line`. `da_weight_cycle_table` must NOT be relied on (ignored by v5.2.16) — weights live in `obs_data.csv`.
  - `da_parameter_cycle_table` must be emitted populated when per-cycle fixed parameters are supplied (`par_cycles`), header-only otherwise; verify a populated table end-to-end.

- [ ] **Step 8: Run the test** → PASS. Then `pytest tests/test_da_control.py -q`.

- [ ] **Step 9: Add a parse validation** — if `pestpp-da.exe` exists, run it on the written PST with a fake forward command and assert the parse error is **not** an unknown-`++`-arg error (mark `@pytest.mark.skipif(not binary)`); otherwise assert the PST text contains only known `da_*` keys.

- [ ] **Step 10: Register the tool + bump count**

```python
@mcp.tool()
def setup_da_control(
    model: str,
    parameterisation: dict,
    cycles: list[int],
    obs_cycles: dict,
    obs_weights: dict | None = None,
    par_cycles: dict | None = None,
    num_reals: int = 50,
    noptmax: int = 1,
    use_simulated_states: bool = True,
    da_options: dict | None = None,
) -> dict:
    """Build a DA-ready PEST++ v2 control file (cycle tables + da_* options)."""
```

Update `tests/test_mcp_protocol.py::_EXPECTED_TOOL_COUNT` (69) and `_EXPECTED_TOOLS["calibration"]`.

- [ ] **Step 11: Run `pytest -q`, `ruff check src`, `mypy src`** — all green.

- [ ] **Step 12: Commit**

```bash
git add src/groundwater_mcp/tools/calibration.py tests/test_da_control.py tests/test_mcp_protocol.py
git commit -m "feat(calibration): setup_da_control builds a DA-ready v2 PST with cycle tables"
```

---

## Task 3: Prior parameter ensemble (`da_parameter_ensemble`)

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py` (extend `_impl_setup_da_control` with `prior_ensemble` / `prior_std`)
- Test: `tests/test_da_control.py`

**Interfaces:**
- Produces: when `prior_ensemble` is supplied or `prior_std` given, write `<gwf>_da_prior.csv` (rows = realisations, columns = parameters) and set `pst.pestpp_options["da_parameter_ensemble"]`; return `prior_ensemble_file`.
- Consumes: Task 2's `_impl_setup_da_control`.

- [ ] **Step 1: Failing test** — `setup_da_control(..., num_reals=4, prior_std=0.2)` writes a CSV pyemu can read as a `ParameterEnsemble` with 4 rows and the right parameter columns; `pestpp_options["da_parameter_ensemble"]` points at it.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `pyemu.ParameterEnsemble.from_gaussian_draw(pst, num_reals=num_reals, std=prior_std)` (or from an explicit `prior_ensemble` dict) then `.to_csv(...)`; when omitted, leave PESTPP-DA to generate the prior internally from bounds.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `feat(calibration): optional DA prior parameter ensemble`.

---

## Task 4: `summarise_da` — engine detection + DA outputs

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py` (`_detect_pestpp_engine`: add `"da"`; `_impl_summarise_calibration` or a thin `_impl_summarise_da`)
- Test: `tests/test_da_control.py`

**Interfaces:**
- Consumes: `_detect_pestpp_engine`, `_latest_ensemble_file`, `_read_phi_csv`.
- Produces: `summarise_da(model, pst_file, max_residuals=500) -> {engine:"da", cycles:[{cycle, phi}], final_phi_mean, final_phi_std, parameter_ensemble:{name:{mean,std,min,max}}, residuals}`.

- [ ] **Step 1: Failing test** — synthesise `<case>.phi.actual.csv` + `<case>.0.par.csv`/`<case>.1.par.csv` in a workspace; assert `_detect_pestpp_engine` returns `"da"` and the summary reports per-cycle phi and posterior parameter stats.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Register `summarise_da`, bump count (70), update docs.**
- [ ] **Step 6: Commit** `feat(calibration): summarise_da reads DA cycle/ensemble outputs`.

---

## Task 5: End-to-end MCP-only validation on a tiny transient model

**Files:**
- Create: `tests/test_da_end_to_end.py`
- Create: `research/discovery/sessions/2026-09-13-da-e2e-tiny-model.md`

**Interfaces:**
- Consumes: `check_environment`-style stack, `create_model`, `add_dis_package`, `add_npf_package`, `add_ic_package`, `add_boundary_package` (CHD/RCH), `import_obs_from_csv`, `setup_da_control`, `run_pestpp_da`, `summarise_da` — all through MCP tool callables (`_impl_*`) in-process, mirroring how tests exercise the server.
- Produces: a green end-to-end DA run on a ≥2-cycle model with ≥5 realisations, and a findings doc.

- [ ] **Step 0: Make `run_pestpp_da` ensemble size PST-aware** (Task 3 review finding). `run_pestpp_da` currently overwrites the PST's `da_num_reals` with its own default `num_reals=50` when the caller omits it, so a `setup_da_control(num_reals=5)` PST run without an explicit `num_reals` silently becomes a 50-member run (harmful when no prior file caps the ensemble; surprising for a closed-book agent). Change the parameter to `num_reals: int | None = None` so an omitted value **preserves** the PST's existing `da_num_reals` (mirroring the `noptmax` handling), and still writes it when provided. Update the tool docstring and `tools.md`. Prove it in the e2e test by calling `run_pestpp_da` without `num_reals` and asserting the run used the PST's ensemble size.
- [ ] **Step 1: Write the failing e2e test** — build a 1×4×4, 2-cycle transient model with a CHD gradient and 2 registered gauge obs at cycle 0 and 1; run `setup_da_control` → `run_pestpp_da` → `summarise_da`; assert `converged`, `cycles >= 2`, and finite `final_phi_mean`. Skip if `pestpp-da.exe` is missing.
- [ ] **Step 2: Run → fail** on the first unmet interface; fix in the tool (not the test) until green.
- [ ] **Step 3: Write the findings doc** (what worked, cycle→time mapping, wall time, any residual limitation).
- [ ] **Step 4: Full verification** — `pytest -q`, `ruff check src`, `mypy src`.
- [ ] **Step 5: Commit** `test(da): end-to-end pestpp-da run on a tiny transient model`.

---

## Task 6: Dispatch the `MF6_EnKF_DISU` Tier-1 closed-book validation

**Files:**
- Modify: `research/discovery/playbooks/6d-regional-model-validation.md` (add "Target 8 — MF6_EnKF_DISU (EnKF)"), `research/holdout-registry.md`, `tasks.md`.
- Create: `research/discovery/sessions/2026-09-13-6d-enkf-disu-rerun1.md` (+ `rerun2`), `...-runlog.md`.

**Interfaces:**
- Consumes: the Tier-1 rerun-improvement loop (playbook §Rerun-improvement loop), Agent Manager worktree mode, holdout `D:\Claude Projects\GW-MCP-holdout\selected\MF6_EnKF_DISU\`.
- Produces: ≥2 consecutive green closed-book reruns (last = set-and-forget, 0 reprompts, 0 MCP-only violations).

- [ ] **Step 1: Write the target prompt** with the standard closed-book + MCP-only paragraph, the holdout sim path (`NeckartalModel1718/NeckartalCalib_try_models/MODFLOW 6/sim`), the gauge CSVs (`csv data/Pegel.csv`, `Pegel_Cell_ID.csv`), and the required workflow (`adopt_model` → register gauges → `setup_da_control` → `run_pestpp_da` → `summarise_da`).

- [ ] **Step 2: Reload the MCP server** (owner action: toggle `/mcps` or reload the window — the agent cannot restart it) so the merged `setup_da_control` is live, then verify with `check_environment` / tool listing.

- [ ] **Step 3: Rerun-1** — dispatch one Agent Manager worktree session; capture the run-log; extract any tool gap into a new task; fix it, re-verify, commit.

- [ ] **Step 4: Rerun-2 (set-and-forget)** — dispatch again with 0 reprompts; if green and no MCP-only violation, record PASS in `tasks.md` (6d Tier-1 → 7 of 8) and `research/holdout-registry.md`.

- [ ] **Step 5: Commit** the session logs + registry/tasks updates.

---

## Task 7: DISU support for the DA IC state parameterisation (unblocks the Tier-1 target)

**Why:** the first closed-book rerun on `MF6_EnKF_DISU` (a **DISU** model) was blocked: `setup_da_control` forces `use_simulated_states=True`, whose IC state parameterisation accepts **DIS/DISV only**; `use_simulated_states=False` is rejected, so no DA-ready PST can be produced for DISU. The run log also found the failure is **non-transactional**: `setup_da_control` rewires NPF/IC *before* the grid check, so the failed call left the model with uniform K=1. Run log: `.kilo/worktrees/6d-enkf-disu-rerun1/run-log.md`.

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py` (`_da_cell_flat_index` DISU branch; reorder `_impl_setup_da_control` so all grid/state validation precedes any model write)
- Test: `tests/test_da_control.py`
- Modify: `tools.md` (grid-support note: DIS/DISV/DISU)
- Create: `research/discovery/sessions/2026-09-14-6d-enkf-disu-rerun1.md` (session log citing the run log)

**Interfaces:**
- `_da_cell_flat_index(model, cellid) -> int` supports **DIS/DISV/DISU**. DISU: `import_obs_from_csv` stores the cell id as an **int, 1-based node** (`site_to_cellid[site] = node + 1`; `_cellid_as_json` keeps ints as ints), so the flat index is `int(cellid) - 1`, validated `0 <= flat < disu.nnodes`. Accept either a bare int or a 1-element list/tuple.
- `_impl_setup_da_control` performs the grid-support + state-cell mapping + out-of-bounds validation **before** `_restore_or_snapshot_k_base`/`_impl_rewire_npf_k_external`/`_impl_rewire_ic_strt_external`, so a rejected call leaves the model untouched.

**Interfaces note:** `_impl_rewire_npf_k_external` (`calibration.py:1107`) and `_impl_rewire_ic_strt_external` (`calibration.py:1897`) already handle DISU (grid-agnostic flat array + FloPy write) — do not rewrite them.

- [ ] **Step 1: Failing test — DISU flat index.** Build a small DISU model with `add_disu_package`; assert `_da_cell_flat_index` maps a stored 1-based node (e.g. `5` → flat `4`) and raises on an out-of-bounds node.

- [ ] **Step 2: Run → fail** (current message: "supports DIS and DISV grids only").

- [ ] **Step 3: Failing test — DISU `setup_da_control`.** Register 2 sites on the DISU model (`import_obs_from_csv` with `cellid_col`), call `_impl_setup_da_control(..., cycles=[0,1], obs_cycles={...}, noptmax=1)`; assert no error, a v2 PST exists, `da_num_reals`/`da_observation_cycle_table` set, and one `head_state` state parameter per site.

- [ ] **Step 4: Failing test — transactional.** With an out-of-bounds DISU site, assert `_impl_setup_da_control` raises AND the model's NPF `k` is unchanged (no `*_k.dat` external rewire applied).

- [ ] **Step 5: Implement** the DISU branch + reorder validation before mutation. Run the three tests → pass.

- [ ] **Step 6: Extend the e2e.** Add a DISU variant to `tests/test_da_end_to_end.py` (small DISU grid, real `pestpp-da` run, gated on the binary) proving the chain works end-to-end on DISU.

- [ ] **Step 7: Docs + session log.** Update `tools.md` grid note; write `research/discovery/sessions/2026-09-14-6d-enkf-disu-rerun1.md` (citing the run log and this fix).

- [ ] **Step 8: Verify** — `pytest -q`, `ruff check src`, `mypy src` green. Commit.

---

## Task 8: DA background run, physical state priors, clip prior draws (fixes surfaced by rerun-2)

**Why:** the first green EnKF rerun (run log `.kilo/worktrees/6d-enkf-disu-rerun2/run-log.md` §10) surfaced three gaps that risk the set-and-forget rerun-3: (1) `setup_da_control`/`run_pestpp_da` exceed the MCP client timeout with no job/progress API; (2) DA state parameters are written with ±1e6 `relative` bounds (`calibration.py:2397-2398`), so pestpp-da's default bounds-derived prior is unphysical and cycle 0 is wasted; (3) `prior_std` draws are not clipped to `parlbnd`/`parubnd`.

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
- Test: `tests/test_da_control.py`, `tests/test_pestpp_da.py`
- Modify: `tools.md`

**Interfaces:**
- `start_calibration(method="da")` (and `_impl_start_calibration`) runs `pestpp-da` in the background via the existing `jobs.submit` machinery, returning a `job_id`; `get_job_status` reports DA progress from `<case>.global.phi.actual.csv` (add a `"da"` branch to `_pestpp_progress`, and a DA result shape matching `run_pestpp_da`); `cancel_job` works. `num_reals` maps to `da_num_reals`.
- `_impl_setup_da_control` gains a physical state-bound rule: state parameters get `parlbnd = strt - bound`, `parubnd = strt + bound` (not ±1e6), where `bound = max(per_site_observed_spread, |strt - mean(observed)|, 5.0)` — the `|strt - mean(observed)|` term guarantees the bound reaches the observed level (rerun-2 evidence shows the state needed 1–8 m shifts), and `bound` is overridable via a new `state_head_bound: float | None = None` argument. The result reports the per-site `state_bound` used.
- `_impl_write_da_prior_ensemble` clips every drawn/supplied realisation into `[parlbnd, parubnd]` (in the parameter's own `partrans` space), and reports `n_clipped` so a clamped submission is visible in the tool result.

- [ ] **Step 1: Failing test — DA background job.** With a fake `jobs.submit`/process or a synthetic `<case>.global.phi.actual.csv`, assert `_impl_start_calibration(method="da")` returns a job id and `_pestpp_progress(..., "da")` parses the per-cycle phi; assert an invalid method is still rejected.

- [ ] **Step 2: Run → fail.** Implement the method dispatch + DA progress + DA result shape; run → pass.

- [ ] **Step 3: Failing test — physical state bounds.** Build a DISU (and DIS) model with registered obs having a known per-site value spread; assert `setup_da_control` writes state params with `parlbnd`/`parubnd` = `strt ± bound` (finite, head-scale, not ±1e6) and that `state_head_bound` overrides it; assert the default is physical.

- [ ] **Step 4: Run → fail.** Implement the bound rule; run → pass.

- [ ] **Step 5: Failing test — clipped prior draws.** With a log-transformed K and `prior_std`, assert no drawn value falls outside `[parlbnd, parubnd]` (and the same for an out-of-bounds explicit `prior_ensemble` value, which must be clipped or rejected with a clear message — pick one and document it).

- [ ] **Step 6: Run → fail.** Implement clipping; run → pass.

- [ ] **Step 7: `setup_da_control` runtime.** Profile the DISU setup path; eliminate redundant full-model flushes (the NPF and IC rewire helpers each `save_sim`+`flush_model`) so setup performs a single flush. Verify the written files are unchanged. Record the before/after timing in the report.

- [ ] **Step 8: Docs** — `tools.md` rows for `start_calibration` (DA method), `setup_da_control` (`state_head_bound`), and any changed description. Update the rerun-2 backlog items in `tasks.md` to "fixed".

- [ ] **Step 9: Verify** — `pytest -q`, `ruff check src`, `mypy src` green. Commit.

---

## Task 9: DA must run in a space-containing workspace; setup under the client timeout

**Why:** rerun-3 (run log `.kilo/worktrees/6d-enkf-disu-rerun3/run-log.md` §7/§7b) found that `start_calibration(method="da")` **stalls** when the workspace path contains spaces (the mandated holdout path): `pestpp-da` spins at 100 % CPU in "making runs", the Python-wrapper model processes sit idle, and no `mf6` child is launched. The identical config in a **space-free** copy completes the full 6-cycle assimilation in 7.8 min with a direct `mf6.exe` command. Separately, `setup_da_control` on the 31.5k-node model still exceeds the ~90 s MCP client timeout, losing the tool result.

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py` (model-command/wrapper generation; the DA background launch; setup hot path)
- Test: `tests/test_da_control.py`, `tests/test_pestpp_da.py`
- Modify: `tools.md`

**Interfaces:** unchanged tool signatures; `start_calibration(method="da")` and `run_pestpp_da` must both complete a DA run in a workspace whose path contains a space.

- [ ] **Step 1: Reproduce cheaply.** Create a small DISU or DIS model in a temp dir whose path **contains a space** (e.g. `...\Temp\kilo\space dir\`) and run both `_impl_start_calibration(method="da")` and `_impl_run_pestpp_da` on it with a real `pestpp-da`. Confirm the stall (background path) vs success (sync path) and capture the `.pst` model command line in each case. If the small model does not reproduce, escalate rather than guess.

- [ ] **Step 2: Root-cause.** Determine why the background path stalls where the sync path succeeds: the wrapper script, `CREATE_NEW_PROCESS_GROUP`, stdout draining in the job worker, or the model-command parsing of the `python.exe` path that contains a space (`D:\Claude Projects\GW-MCP\.venv\...`). Record the mechanism with evidence.

- [ ] **Step 3: Fix + test.** Make the DA (and, if the same path is affected, GLM/IES) background run launch the forward model reliably from a space-containing workspace — e.g. make the model command space-free (direct `mf6.exe` with `cwd=ws`, so the space is in the working directory, not the command line) and/or drain the child's stdout correctly and drop `CREATE_NEW_PROCESS_GROUP` if it is implicated. Add a regression test that fails on the current code and passes after the fix (a space-containing temp workspace, real binaries, no network).

- [ ] **Step 4: `setup_da_control` runtime.** Profile the 31.5k-node DISU setup path (K template 605 kB / 31 522 tokens, IC template, `_tpl_substitute`, pyemu write) and optimise it under the ~90 s client timeout (or, if it cannot be made reliably fast, make it non-blocking like the run). Report before/after timings; verify the written files are byte-identical.

- [ ] **Step 5: Docs + verify** — `tools.md` (workspace/space behaviour, any timing note); `pytest -q`, `ruff check src`, `mypy src` green. Commit.

---

## Task 10: multiplier K scope for DA + run-isolated summarise_da

**Why:** the EnKF reruns (run logs `.kilo/worktrees/6d-enkf-disu-rerun4/session6d-t8/run-log.md`, `…/6d-enkf-disu-rerun5/run-log.md`) show that `scope="all"` on `npf:k` **replaces** the 10,413-value heterogeneous K field with one uniform value — it collapsed to ≈0.1 m/d and aborted rerun-5's first attempt on MF6 convergence, and it is why K rails at a bound. `scope="zones"` is infeasible here (10,413 zones), and the 31,522-token template is why `setup_da_control` exceeds the client timeout. A single **multiplier** on the base field preserves the pattern *and* shrinks the template to one token. Separately, `summarise_da` is not run-isolated: after a second DA run in the same directory it returned the first run's posterior and residuals.

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
- Test: `tests/test_da_control.py`, `tests/test_calibration.py`
- Modify: `tools.md`

**Interfaces:**
- New K scope `"multiplier"`: one dimensionless factor applied to the **existing** K array (`k = base_k × factor`), base pattern preserved. Reuse the existing multiplier machinery: `_apply_k_multipliers` (`calibration.py:1070`), `_maybe_apply_zone_multipliers` (`:1102`) and `_generate_forward_wrapper(multiply_k=True)` (`:1562`) with a **single all-cells zone** (zone id 1), so the external multiplier file holds one value and the K template one token. Default factor 1.0; bounds from `lower_factor`/`upper_factor`; `partrans` default `"log"`.
- `_impl_setup_da_control` accepts `scope="multiplier"` (it currently rejects non-`all`/`layer`/`cells` for DA) and routes through the multiplier/wrapper path instead of a per-cell token template.
- `_impl_summarise_da` derives its run base from the current PST/run so a second DA run in the same directory reports **that run's** posterior and residuals.

- [ ] **Step 1: Failing test — multiplier preserves the base field.** On a small DIS model with a heterogeneous K array, `setup_da_control(parameterisation={"k_mult": {"target":"npf:k","scope":"multiplier","initial":1.0,"lower_factor":0.2,"upper_factor":5.0}}, ...)` produces a v2 PST with **one** adjustable K parameter and a K template holding one token; at the default factor the written K equals the base field (pattern preserved), and a factor of 2 doubles it.
- [ ] **Step 2: Run → fail.** Implement the scope (normaliser + DA routing via the single-zone multiplier/wrapper). Run → pass.
- [ ] **Step 3: Failing test — `summarise_da` run isolation.** Two successive DA runs in one workspace with different cycle counts: after the second, `summarise_da` reports the **second** run's cycle count/posterior, not the first's.
- [ ] **Step 4: Run → fail.** Implement the run-scoped base resolution. Run → pass.
- [ ] **Step 5: Setup runtime.** Confirm `setup_da_control` with `scope="multiplier"` is comfortably under the ~90 s client timeout on a large (≥30k-cell) model (1-token template), recording before/after.
- [ ] **Step 6: Docs + verify.** `tools.md` (the new scope); `pytest -q`, `ruff check src`, `mypy src` green; tool count unchanged (70). Commit.

---

## Self-Review

- **Spec coverage:** engine exposure (done, `388839d`) → Task 2; cycle tables → Task 2; prior ensemble → Task 3; run → existing `run_pestpp_da`; summarise → Task 4; end-to-end proof → Task 5; Tier-1 gate → Task 6. The high-risk state-linkage unknown is Task 1 (spike) and feeds Tasks 2–3.
- **Placeholder scan:** the only intentionally non-exact content is Task 1's spike (an investigation whose *deliverable* is a findings doc) and Task 2's DA observation-interface line, which is explicitly gated on the spike — both are concrete work with named outputs, not "TODO".
- **Type consistency:** `_write_cycle_table(path, names, cycles, values)`, `_impl_setup_da_control(...) -> dict`, `_impl_summarise_da(...) -> dict` are used consistently across tasks; tool-count bumps land once per registered tool (69 in Task 2, 70 in Task 4).
