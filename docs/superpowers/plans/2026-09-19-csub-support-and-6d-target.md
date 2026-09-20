# CSUB Support and 6d Target 9 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MODFLOW 6 CSUB (subsidence) builder, observation/post-processing and automated calibration support to groundwater-mcp, and validate it closed-book on the `1DSubsidenceModeling-MF6CSUB` Tier-1 holdout target.

**Architecture:** A new `add_csub_package` builder wraps `flopy.mf6.ModflowGwfcsub` (options, per-layer arrays, externalisable `packagedata`, CSUB observation block, filerecords). Post-processing adds `read_compaction` and `plot_subsidence`; a `import_subsidence_observations` tool registers derived time-series targets that the generated forward wrapper materialises. `setup_calibration` replaces its `npf:k`-only check with a target resolver registry (`npf:k33`, `csub:packagedata`, `csub:cg_theta`, `csub:cg_ske_cr`) and an `obs_source="derived"` mode, so one call still emits the whole PEST interface. A final task adds the 6d Target 9 playbook prompt, registry row and closed-book dispatch.

**Tech Stack:** Python 3.12, flopy 3.10, pyemu 1.4.0, PEST++ `pestpp-ies`, MODFLOW 6, pandas, pytest, ruff, mypy.

## Global Constraints

- Venv: `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`. Run pytest from the repo root.
- `ruff check src` and `mypy src` must stay clean; full `pytest -q` green (currently 70 tools / suite in the 700s).
- Files changed together, patterns copied from `src/groundwater_mcp/tools/builder.py` (`_impl_*` + `register(mcp)`), `src/groundwater_mcp/tools/calibration.py`, `src/groundwater_mcp/utils/model_store.py`.
- Tool count is tracked in **three** places per tool: `tests/test_mcp_protocol.py::_EXPECTED_TOOL_COUNT` (line 61), the `_EXPECTED_TOOLS` dict (lines 66–146), and the `README.md` / `tools.md` / `architecture.md` module tables. Landing all four tools takes 70 → **74**.
- New builder tools must: use `_err(code, message, suggestion)`; write metadata via `model_store.read_meta` / `write_meta`; stage writes with `save_sim` (returns `False`, deferred); let `server.py::_with_next_steps` attach `next_steps`; and raise through `save_sim` for the `MODEL_ADOPTED_READONLY` guard.
- Windows/PEST++ rules already documented in `tools.md`: the forward wrapper is stdlib-only, written at a **space-free** path; the model command must contain no spaces; a space in the *workspace* path is fine.
- New target files use `_TPL_TOKEN_WIDTH = 15` wide fixed-width tokens and every parameter group gets `derinclb = 0.01`.
- Error codes are fixed: `INVALID_INPUT`, `PACKAGE_MISSING`, `OUTPUT_FILE_MISSING`, `MODEL_ADOPTED_READONLY`, `PAYLOAD_TOO_LARGE`, `PACKAGE_ERROR`, `*_FAILED`.
- Closed-book rule applies to Agent Manager validation sessions only (all actions through MCP tools); ordinary Python for reading/preparing source data is allowed.
- CSUB is v0.3.0 scope (`TASKS.md` § 7d); it does not block v0.1.0.

## File Structure

- `src/groundwater_mcp/tools/builder.py` — add `_impl_add_csub_package`, `_CSUB_OBS_TYPES`, `_normalise_csub_packagedata`, `add_csub_package` registration. Existing file; grows ~220 lines.
- `src/groundwater_mcp/tools/postprocess.py` — add `_impl_read_compaction`, `_impl_plot_subsidence`, `_csub_obs_csv_path`; register both tools.
- `src/groundwater_mcp/tools/parameterise.py` — add `_impl_import_subsidence_observations` + registration.
- `src/groundwater_mcp/tools/calibration.py` — add the target resolver registry, `npf:k33` rewire, `csub:packagedata` externalise/template, `csub:cg_theta`/`csub:cg_ske_cr`, derived-observation instruction files, `obs_source="derived"`.
- `tests/test_csub.py` — new: builder, meta, validation, `read_compaction`, `plot_subsidence`, derived-obs registration.
- `tests/test_csub_calibration.py` — new: target normalisers, packagedata externalisation, multi-target `.pst`, derived instruction file, binary-gated tiny pestpp-ies run.
- `tests/test_mcp_protocol.py` — tool count + per-module lists.
- `docs/superpowers/specs/2026-09-19-csub-support-and-6d-target-design.md` — the approved spec (already written; reference only).
- `research/discovery/sessions/2026-09-19-csub-packagedata-spike.md` — Task 1 findings.
- `research/discovery/playbooks/6d-regional-model-validation.md`, `research/holdout-registry.md`, `TASKS.md` — Target 9.

---

### Task 1: Spike — externalise and template CSUB packagedata under pestpp-ies

**Why:** retires the two riskiest unknowns before any tool code: (a) how flopy externalises CSUB list `packagedata` and whether a subset of its columns can be templated; (b) whether a time-indexed instruction file can read a derived subsidence series. If either fails, the calibration design changes before Tasks 6–8 are built.

**Files:**
- Create: `tests/fixtures/csub_spike/` (generated only; not committed model binaries)
- Create: `research/discovery/sessions/2026-09-19-csub-packagedata-spike.md`

**Interfaces:**
- Consumes: `flopy.mf6.ModflowGwfcsub`, pyemu 1.4.0, `pestpp-ies` on PATH (via `_find_pestpp_binary`).
- Produces: the exact working file set and the decision recorded in the findings doc that Tasks 7–8 build against.

- [ ] **Step 1: Build a tiny 2-layer CSUB column model in a scratch dir**

1×1 grid, `delr=delc=1.0`, 2 layers, `icelltype=1`, 3 stress periods (first steady), one no-delay interbed per layer, `head_based=False`, `initial_preconsolidation_head=True`, `specified_initial_interbed_state=True`, `ndelaycells=3`, one delay interbed in layer 0. Write `sim.set_all_data_external()` and confirm on disk which file holds `packagedata` (expected `model.csub6_packagedata.dat` or an inline block).

- [ ] **Step 2: Force `packagedata` external and inspect the file**

Record the exact line format (leading index, cellid, `cdelay` string, numeric columns). Confirm `pkg.packagedata.set_data({"filename": ..., "data": ...})` (or `set_all_data_external`) produces a file MF6 reads — run `mf6` and check `Normal termination`.

- [ ] **Step 3: Hand-author a `ptf` template over one numeric column and run pestpp-ies**

Write `model.csub6_packagedata.dat.tpl` with one wide token per interbed in the target column, create a minimal `.pst` (noptmax 1, a few realisations), run `pestpp-ies pest.pst`, and confirm the substituted value lands in the file each run.

- [ ] **Step 4: Spike the derived time-series instruction file**

From a run's `<model>.csub.obs.csv`, write a pif that reads the sum of the compaction columns for a chosen row, and confirm pestpp accepts it (no `EOL encountered`/whitespace errors) and reports the observation.

- [ ] **Step 5: Write the findings doc**

`research/discovery/sessions/2026-09-19-csub-packagedata-spike.md`: exact working packagedata file name/format, the externalisation call that worked, the template layout, the pif layout, and any pitfall. This doc is the authoritative checklist for Tasks 7–8.

- [ ] **Step 6: Commit the findings doc and spike script (no model outputs)**

```bash
git add research/discovery/sessions/2026-09-19-csub-packagedata-spike.md tests/fixtures/csub_spike/*.py
git commit -m "docs(csub): spike packagedata externalisation, templating and derived obs"
```

---

### Task 2: `add_csub_package` builder

**Files:**
- Modify: `src/groundwater_mcp/tools/builder.py`
- Test: `tests/test_csub.py`

**Interfaces:**
- Consumes: `get_gwf`, `get_sim`, `save_sim`, `_read_meta`/`_write_meta`, `_err`, `_packages_of_type`, `_pkg_nam_name`, `grid_size` (`utils/grid.py`).
- Produces: `_impl_add_csub_package(model, packagedata, ninterbeds=None, sgm=None, sgs=None, cg_theta=None, cg_ske_cr=None, head_based=False, initial_preconsolidation_head=False, specified_initial_interbed_state=False, update_material_properties=False, ndelaycells=None, beta=None, gammaw=None, interbeddata=None, stress_period_data=None, observations=None, filerecords=None, print_input=True, save_flows=True, pname=None) -> dict` returning `{model, package: "CSUB", ninterbeds, n_delay_interbeds, layers, written, ...}`.

- [ ] **Step 1: Write the failing test**

```python
def _csub_model(tmp_path, name="csubmdl", nlay=2):
    from groundwater_mcp.tools.builder import (
        _impl_create_model, _impl_set_simulation, _impl_add_dis_package,
        _impl_add_npf_package, _impl_add_ic_package, _impl_add_sto_package,
        _impl_add_oc_package,
    )
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "FEET", "DAYS")
    _impl_set_simulation(name, 2, [1.0, 1.0], [1, 1], "moderate")
    _impl_add_dis_package(name, nlay, 1, 1, 1.0, 1.0, 0.0, [-10.0, -20.0][:nlay])
    _impl_add_npf_package(name, icelltype=1, k=[1.0] * nlay, k33=[0.1] * nlay, save_flows=True)
    _impl_add_ic_package(name, strt=[0.0] * nlay)
    _impl_add_sto_package(name, iconvert=0, ss=0.0, sy=0.0, steady_state=[0], save_flows=True)
    _impl_add_oc_package(name, None, "model.cbc", None, None)
    return name


def test_add_csub_package_writes_six_options_and_meta(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=2)
    res = _impl_add_csub_package(
        name,
        packagedata=[
            [0, [0, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
            [1, [1, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
        ],
        sgm=[0.1, 0.1],
        sgs=[0.1, 0.1],
        cg_theta=[0.35, 0.35],
        cg_ske_cr=[2.2e-8, 2.2e-8],
        head_based=False,
        initial_preconsolidation_head=True,
        specified_initial_interbed_state=True,
        filerecords={"strainib": "model.strainib.csv"},
    )
    assert "error" not in res, res
    assert res["package"] == "CSUB"
    assert res["ninterbeds"] == 2
    assert res["written"] is False
    meta = model_store.read_meta(name)
    assert meta["csub"]["ninterbeds"] == 2
    assert meta["csub"]["interbeds"][0]["layer"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_csub.py::test_add_csub_package_writes_six_options_and_meta -v`
Expected: FAIL with `ImportError` / `cannot import name '_impl_add_csub_package'`.

- [ ] **Step 3: Implement the normaliser and the builder**

```python
_CSUB_PKG_TYPE = "csub6"
_CSUB_OBS_TYPES = {
    "compaction", "preconstress", "elastic-compaction", "inelastic-compaction",
}
_CSUB_INTERBED_OBS_TYPES = {"interbed-compaction-pct", "delay-preconstress", "delay-head"}
_CSUB_FILERECORDS = {
    "zdisplacement": "zdisplacement_filerecord",
    "package_convergence": "package_convergence_filerecord",
    "strainib": "strainib_filerecord",
    "compaction": "compaction_filerecord",
}


def _normalise_csub_packagedata(packagedata, nlay: int) -> list:
    recs = []
    for i, rec in enumerate(packagedata):
        if len(rec) != 11:
            raise ValueError(f"packagedata record {i} has {len(rec)} fields, expected 11")
        icsubno, cellid, cdelay, pcs0, thick_frac, rnb, ssv_cc, sse_cr, theta, kv, h0 = rec
        if int(icsubno) != i:
            raise ValueError(f"packagedata icsubno must be contiguous from 0 (record {i})")
        cdelay = str(cdelay).lower()
        if cdelay not in ("delay", "nodelay"):
            raise ValueError(f"packagedata record {i}: cdelay must be 'delay' or 'nodelay'")
        layer = int(cellid[0]) if isinstance(cellid, (list, tuple)) else int(cellid)
        if not 0 <= layer < nlay:
            raise ValueError(f"packagedata record {i}: layer {layer} outside 0..{nlay - 1}")
        if float(thick_frac) <= 0.0:
            raise ValueError(f"packagedata record {i}: thick_frac must be > 0")
        if float(rnb) < 1.0:
            raise ValueError(f"packagedata record {i}: rnb must be >= 1")
        if not 0.0 < float(theta) < 1.0:
            raise ValueError(f"packagedata record {i}: theta must be in (0, 1)")
        recs.append(list(rec))
    return recs


def _per_layer_values(value, nlay: int, field: str) -> list:
    vals = list(value) if isinstance(value, (list, tuple)) else [value] * nlay
    if len(vals) != nlay:
        raise ValueError(f"{field} has {len(vals)} values, expected nlay={nlay}")
    return vals
```

Then `_impl_add_csub_package`: resolve `gwf`/`sim`; `nlay, _ = grid_size(gwf)`; normalise packagedata (skip when a `{"filename": ...}` dict is given); default `ninterbeds`; require `ndelaycells` when any `cdelay == "delay"`; build `kw` from the per-layer arrays and the filerecords map; replace via `_packages_of_type(gwf, _CSUB_PKG_TYPE)` (only the named package when `pname` is set); `pkg = mf6.ModflowGwfcsub(gwf, ninterbeds=ninterbeds, packagedata=recs, **kw)`; `written = save_sim(model, sim)`; write the `csub` meta block; return the result dict. `observations` is accepted but handled in Task 3 (raise `ValueError("observations not supported yet")` until then is **not** acceptable — Task 2 must not ship a half parameter, so implement the pass-through now and Task 3 adds the obs package).

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_csub.py -v`
Expected: PASS.

- [ ] **Step 5: Add the validation-error tests**

```python
def test_add_csub_package_rejects_delay_without_ndelaycells(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name, packagedata=[[0, [0, 0, 0], "delay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0]],
    )
    assert res["code"] == "INVALID_INPUT"
```

Run: `pytest tests/test_csub.py -v` → PASS.

- [ ] **Step 6: Register the tool and bump the tool count**

```python
@mcp.tool()
def add_csub_package(
    model: str,
    packagedata: list | dict,
    ninterbeds: int | None = None,
    sgm: float | list | None = None,
    sgs: float | list | None = None,
    cg_theta: float | list | None = None,
    cg_ske_cr: float | list | None = None,
    head_based: bool = False,
    initial_preconsolidation_head: bool = False,
    specified_initial_interbed_state: bool = False,
    update_material_properties: bool = False,
    ndelaycells: int | None = None,
    beta: float | None = None,
    gammaw: float | None = None,
    interbeddata: list | None = None,
    stress_period_data: dict | None = None,
    observations: dict | None = None,
    filerecords: dict | None = None,
    print_input: bool = True,
    save_flows: bool = True,
    pname: str | None = None,
) -> dict:
    """Add or replace the CSUB (subsidence) package on a MODFLOW 6 GWF model."""
```

Wrap with the standard `try/except` envelope (`MODEL_NOT_FOUND`, `MODEL_ADOPTED_READONLY`, `INVALID_INPUT`, `PACKAGE_ERROR`). Update `_EXPECTED_TOOL_COUNT = 71` and add `"add_csub_package"` to `_EXPECTED_TOOLS["builder"]`.

- [ ] **Step 7: Run the full verification**

Run: `pytest -q` && `ruff check src` && `mypy src`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/groundwater_mcp/tools/builder.py tests/test_csub.py tests/test_mcp_protocol.py
git commit -m "feat(builder): add_csub_package wraps ModflowGwfcsub"
```

---

### Task 3: CSUB observation records and `read_compaction`

**Files:**
- Modify: `src/groundwater_mcp/tools/builder.py` (obs block in `add_csub_package`)
- Modify: `src/groundwater_mcp/tools/postprocess.py`
- Test: `tests/test_csub.py`

**Interfaces:**
- Consumes: Task 2's `add_csub_package`; `resolve_workspace`, `read_meta`.
- Produces: `_impl_read_compaction(model, max_rows=500) -> dict` returning `{model, times, layers, compaction, subsidence, interbed_strain, output_csv, truncated, ...}`.

- [ ] **Step 1: Write the failing test for the obs block**

```python
def test_add_csub_package_writes_obs_package(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata=[[0, [0, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0]],
        observations={"compaction.01": [("compaction.01", "compaction-cell", (0, 0, 0))]},
    )
    assert "error" not in res, res
    meta = model_store.read_meta(name)
    assert meta["csub"]["obs_output_csv"].endswith(".csub.obs.csv")
```

Run: `pytest tests/test_csub.py::test_add_csub_package_writes_obs_package -v` → FAIL.

- [ ] **Step 2: Implement the obs block**

Build `continuous = {csv_name: [(name, obs_type, index), ...]}`, validating each `obs_type` against `_CSUB_OBS_TYPES | _CSUB_INTERBED_OBS_TYPES`, then:
```python
pkg.obs.initialize(filename=f"{gwf.name}.csub.obs", digits=10, print_input=True, continuous=continuous)
```
Record `meta["csub"]["obs_output_csv"] = f"{gwf.name}.csub.obs.csv"` and `meta["csub"]["obs_names"] = [...]`. Convert 0-based cellids in `*-cell` records the same way Task 2 does.

- [ ] **Step 3: Write the failing `read_compaction` test with a synthetic obs CSV**

```python
def test_read_compaction_sums_layers_to_subsidence(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction
    name = _csub_model(tmp_path, nlay=2)
    ws = model_store.resolve_workspace(name)
    (ws / "model.csub.obs.csv").write_text(
        "time,COMPACTION.01,COMPACTION.02\n0.0,0.10,0.20\n1.0,0.15,0.25\n"
    )
    meta = model_store.read_meta(name)
    meta["csub"] = {"obs_output_csv": "model.csub.obs.csv"}
    model_store.write_meta(name, meta)
    res = _impl_read_compaction(name)
    assert "error" not in res, res
    assert res["subsidence"] == [0.30000000000000004, 0.4]
```

- [ ] **Step 4: Implement `read_compaction`**

Resolve the CSV from `meta["csub"]["obs_output_csv"]`, else `rglob("*csub.obs.csv")`; error `OUTPUT_FILE_MISSING` when absent. Read with pandas, match compaction columns case-insensitively by `"compaction"` and the `.<layer>` suffix (excluding `elastic`/`inelastic`), sum per time into `subsidence`, read `<gwf>.strainib.csv` when present, cap rows at `max_rows` and write the full table to `<model>_compaction.csv`.

- [ ] **Step 5: Register `read_compaction`, bump count to 72**

Add to `_EXPECTED_TOOLS["postprocess"]`. Run `pytest -q && ruff check src && mypy src` → green.

- [ ] **Step 6: Commit**

```bash
git add src/groundwater_mcp/tools/builder.py src/groundwater_mcp/tools/postprocess.py tests/test_csub.py tests/test_mcp_protocol.py
git commit -m "feat(postprocess): CSUB obs records and read_compaction"
```

---

### Task 4: `plot_subsidence`

**Files:**
- Modify: `src/groundwater_mcp/tools/postprocess.py`
- Test: `tests/test_csub.py`

**Interfaces:**
- Consumes: `_impl_read_compaction`, `utils/plotting.figure` / `save_figure`, `mcp.server.fastmcp.utilities.types.Image`.
- Produces: `_impl_plot_subsidence(model, observed_csv=None, output_file=None) -> dict` returning `{model, output_file, n_times, has_observed, observed_csv}`.

- [ ] **Step 1: Write the failing test**

```python
def test_plot_subsidence_writes_png(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence
    name = _csub_model(tmp_path, nlay=1)
    ws = model_store.resolve_workspace(name)
    (ws / "model.csub.obs.csv").write_text("time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    meta = model_store.read_meta(name)
    meta["csub"] = {"obs_output_csv": "model.csub.obs.csv"}
    model_store.write_meta(name, meta)
    res = _impl_plot_subsidence(name)
    assert "error" not in res, res
    assert Path(res["output_file"]).exists()
```

- [ ] **Step 2: Implement and register**

Plot simulated cumulative subsidence against time; when `observed_csv` is given, auto-detect a value column (`Subsidence_ft` preferred, else the first numeric non-time column) and overlay it. Register with `@mcp.tool(structured_output=False)` returning `[Image(path=result["output_file"]), result]`, matching `plot_heads_map` (`postprocess.py:1384`). Bump `_EXPECTED_TOOL_COUNT` to 73.

- [ ] **Step 3: Verify and commit**

Run: `pytest -q && ruff check src && mypy src`.

```bash
git add src/groundwater_mcp/tools/postprocess.py tests/test_csub.py tests/test_mcp_protocol.py
git commit -m "feat(postprocess): plot_subsidence time series tool"
```

---

### Task 5: `import_subsidence_observations` (derived time-series targets)

**Files:**
- Modify: `src/groundwater_mcp/tools/parameterise.py`
- Test: `tests/test_csub.py`

**Interfaces:**
- Consumes: `resolve_workspace`, `read_meta`/`write_meta`, `_safe_obs_name`.
- Produces: `_impl_import_subsidence_observations(model, observed_csv, time_col="datetime", value_col="Subsidence_ft", sim_source=None, name="subsidence") -> dict`; meta block `derived_observations[name] = {observed_csv, time_col, value_col, values, dates, sim_source: {csv, sum_cols, time_col}}`.

- [ ] **Step 1: Write the failing test**

```python
def test_import_subsidence_observations_registers_series(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations
    name = _csub_model(tmp_path, nlay=1)
    obs = tmp_path / "H201_sub_data.csv"
    obs.write_text("datetime,Subsidence_ft\n2010-01-01,0.0\n2011-01-01,0.5\n")
    res = _impl_import_subsidence_observations(name, str(obs))
    assert "error" not in res, res
    assert res["n_observations"] == 2
    meta = model_store.read_meta(name)
    assert meta["derived_observations"]["subsidence"]["dates"] == ["2010-01-01", "2011-01-01"]
    assert meta["derived_observations"]["subsidence"]["sim_source"]["csv"].endswith(".csub.obs.csv")
```

- [ ] **Step 2: Implement and register, bump count to 74**

Read the CSV, sort by `time_col`, keep numeric `value_col`, default `sim_source` to the model's CSUB obs CSV and `sum_cols="compaction-cell"`. Register on the `parameterise` module (so it gets `next_steps`). Update `_EXPECTED_TOOLS`, `README.md`/`tools.md`/`architecture.md`.

- [ ] **Step 3: Verify and commit**

Run: `pytest -q && ruff check src && mypy src`.

```bash
git add src/groundwater_mcp/tools/parameterise.py tests/test_csub.py tests/test_mcp_protocol.py README.md tools.md architecture.md
git commit -m "feat(parameterise): register derived subsidence time-series targets"
```

---

### Task 6: Calibration target registry — `npf:k33`

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
- Test: `tests/test_csub_calibration.py`

**Interfaces:**
- Consumes: `_normalise_parameterisation`, `_impl_rewire_npf_k_external`, `_impl_generate_tpl`, `_restore_or_snapshot_k_base`, `_SUPPORTED_TARGETS`.
- Produces: `_SUPPORTED_TARGETS = ("npf:k", "npf:k33")`; `_impl_rewire_npf_array_external(model, keyword, filename=None, flush=True)` handling both `k` and `k33`; `_restore_or_snapshot_package_array(model, keyword)`.

- [ ] **Step 1: Write the failing test**

```python
def test_setup_calibration_k33_layer_scope(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    name = _csub_model(tmp_path, nlay=2)
    _register_head_obs(tmp_path, name)  # existing helper pattern from test_da_control.py
    res = _impl_setup_calibration(
        name,
        {"k33_1": {"target": "npf:k33", "scope": "layer", "layer": 0, "initial": 0.1}},
    )
    assert "error" not in res, res
    assert res["target_file"] == "model_k33.dat"
```

- [ ] **Step 2: Generalise the rewire/snapshot and add the target**

Refactor `_impl_rewire_npf_k_external` into `_impl_rewire_npf_array_external(model, keyword, filename=None, flush=True)` (keyword in `{"k", "k33"}`) with the existing `k` wrapper preserved as a thin alias; add `_restore_or_snapshot_package_array(model, keyword)` with snapshot `<gwf>_<keyword>_pristine.npy`; extend `_normalise_parameterisation` to accept `npf:k33` and pass the keyword through to the tpl/substitute calls. `clear_k_base_snapshot` is extended in `model_store.py` to clear both snapshots.

- [ ] **Step 3: Verify and commit**

Run: `pytest tests/test_csub_calibration.py -v && pytest -q && ruff check src && mypy src`.

```bash
git add src/groundwater_mcp/tools/calibration.py src/groundwater_mcp/utils/model_store.py tests/test_csub_calibration.py
git commit -m "feat(calibration): npf:k33 target and generalised package-array rewire"
```

---

### Task 7: Calibration targets — `csub:packagedata`, `csub:cg_theta`, `csub:cg_ske_cr`

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
- Test: `tests/test_csub_calibration.py`

**Interfaces:**
- Consumes: Task 1's spike findings; Task 2's CSUB package/meta.
- Produces: `_normalise_csub_packagedata_parameterisation(...)`, `_impl_externalise_csub_packagedata(model)`, `_impl_generate_csub_table_tpl(...)`; `parameterisation` specs accepted: `{"target": "csub:packagedata", "columns": [...], "layers": [...] | None, "initial": 1.0}` and `{"target": "csub:cg_theta"|"csub:cg_ske_cr", "scope": "layer", "layer": N, "initial": ...}`.

- [ ] **Step 1: Write the failing packagedata target test**

```python
def test_setup_calibration_csub_packagedata_columns(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    name = _csub_model(tmp_path, nlay=2)
    _install_csub(tmp_path, name)               # add_csub_package helper
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {"ssv": {"target": "csub:packagedata", "columns": ["ssv_cc", "sse_cr"],
                 "lower_factor": 0.05, "upper_factor": 20.0, "partrans": "none"}},
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 4   # 2 columns x 2 interbeds
    assert any(t.endswith("packagedata.dat.tpl") for t in res["template_files"])
```

- [ ] **Step 2: Implement externalisation + column templating**

Using the spike's exact file name/format: externalise `packagedata`, emit a template with one wide token per interbed in each requested column and leave all other fields untouched, and record parameter names `f"{key}_{column}_{icsubno}"` with bounds `value × lower_factor` / `× upper_factor`. Extend `_impl_setup_calibration` to collect template/target pairs from multiple targets and pass them all to `_impl_setup_pest_control`.

- [ ] **Step 3: Add the per-layer array targets**

`csub:cg_theta` / `csub:cg_ske_cr` rewire the corresponding CSUB per-layer array to an external file and emit one token per layer (constant per-layer parameter), following `_impl_generate_tpl`'s `ptf ~` layout.

- [ ] **Step 4: Add the multi-target assembly test**

```python
def test_setup_calibration_multi_target_pst(tmp_path):
    ...
    res = _impl_setup_calibration(name, {
        "ssv": {"target": "csub:packagedata", "columns": ["ssv_cc"], ...},
        "cgtheta": {"target": "csub:cg_theta", "scope": "layer", "layer": 0, "initial": 0.35},
        "k33": {"target": "npf:k33", "scope": "layer", "layer": 0, "initial": 0.1},
    })
    assert Path(res["pst_file"]).exists()
    assert res["n_adjustable_parameters"] == 3
```

- [ ] **Step 5: Verify and commit**

Run: `pytest -q && ruff check src && mypy src`.

```bash
git add src/groundwater_mcp/tools/calibration.py tests/test_csub_calibration.py
git commit -m "feat(calibration): csub packagedata and cg_* parameter targets"
```

---

### Task 8: Derived-observation interface and `obs_source="derived"`

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
- Test: `tests/test_csub_calibration.py`

**Interfaces:**
- Consumes: Task 5's `derived_observations` meta; `_generate_forward_wrapper`; `_impl_generate_ins_from_obs_csv`.
- Produces: `_build_derived_obs_interface(model, ws) -> (ins_paths, obs_data, output_files)`; `_impl_setup_calibration(..., obs_source="derived")`; the forward wrapper gains a stdlib-only derived-series step writing `<gwf>_subsidence.csv`.

- [ ] **Step 1: Write the failing test**

```python
def test_setup_calibration_derived_obs_builds_pif(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    name = _csub_model(tmp_path, nlay=1)
    _install_csub(tmp_path, name)
    _register_subsidence_obs(tmp_path, name)     # Task 5 helper
    res = _impl_setup_calibration(
        name, {"ssv": {"target": "csub:packagedata", "columns": ["ssv_cc"], ...}},
        obs_source="derived",
    )
    assert "error" not in res, res
    text = Path(res["instruction_file"]).read_text()
    assert text.startswith("pif")
    assert text.count("l") >= 2                  # one read per observed date
```

- [ ] **Step 2: Implement the derived pif and wrapper step**

Write one pif line per observed date reading the matching row of `<gwf>_subsidence.csv`, and inject a stdlib-only `csv`-module step into `_generate_forward_wrapper` (before the PEST read, after `mf6`) that sums the compaction columns of the CSUB obs CSV into `<gwf>_subsidence.csv`. Reuse the existing space-free/stdlib-only wrapper constraints.

- [ ] **Step 3: Verify and commit**

Run: `pytest -q && ruff check src && mypy src`.

```bash
git add src/groundwater_mcp/tools/calibration.py tests/test_csub_calibration.py
git commit -m "feat(calibration): derived time-series obs source for setup_calibration"
```

---

### Task 9: End-to-end MCP-only tiny CSUB calibration

**Files:**
- Create: `tests/test_csub_end_to_end.py`
- Create: `research/discovery/sessions/2026-09-19-csub-e2e-tiny-model.md`

**Interfaces:**
- Consumes: all tools from Tasks 2–8, in-process via `_impl_*`, gated on `pestpp-ies` and MF6.

- [ ] **Step 1: Write the failing e2e test**

```python
@requires_mf6
@requires_pestpp_ies
def test_tiny_csub_calibration_end_to_end(tmp_path):
    name = _csub_model(tmp_path, nlay=2)
    _install_csub_with_obs(tmp_path, name)
    _register_subsidence_obs(tmp_path, name)
    setup = _impl_setup_calibration(
        name, {"ssv": {"target": "csub:packagedata", "columns": ["ssv_cc", "sse_cr"], ...}},
        obs_source="derived", noptmax=2,
    )
    out = _impl_run_pestpp_ies(name, setup["pst_file"], num_reals=6, num_workers=1)
    assert "error" not in out, out
    assert out["final_phi_mean"] is not None
```

- [ ] **Step 2: Run → fail on the first unmet interface; fix the tool (not the test)**

Run: `pytest tests/test_csub_end_to_end.py -v`.

- [ ] **Step 3: Run to green, then full verification**

Run: `pytest -q && ruff check src && mypy src`.

- [ ] **Step 4: Write the findings doc and commit**

`research/discovery/sessions/2026-09-19-csub-e2e-tiny-model.md`: what worked, wall time, any limitation.

```bash
git add tests/test_csub_end_to_end.py research/discovery/sessions/2026-09-19-csub-e2e-tiny-model.md
git commit -m "test(csub): end-to-end pestpp-ies calibration on a tiny CSUB model"
```

---

### Task 10: 6d Target 9 — playbook, registry, closed-book dispatch

**Files:**
- Modify: `research/discovery/playbooks/6d-regional-model-validation.md` (add "Target 9 — 1DSubsidenceModeling-MF6CSUB")
- Modify: `research/holdout-registry.md` (Round-4 row), `TASKS.md` (6d checkbox + v0.2.0/v0.3.0 status)
- Create: `research/discovery/sessions/2026-09-19-6d-csub-rerun1.md` (+ `-runlog.md`)

**Interfaces:**
- Consumes: the rerun-improvement loop (playbook), Agent Manager worktree mode, holdout `D:\Claude Projects\GW-MCP-holdout\selected\1DSubsidenceModeling-MF6CSUB\`.
- Produces: ≥2 consecutive green closed-book reruns (last = set-and-forget, 0 reprompts, 0 MCP-only violations).

- [ ] **Step 1: Confirm the site**

Read `H201/source_data/H201_lithology.csv` (and two alternates) and run `prep_data.prep_data()` once in a scratch copy to confirm the site has both delay and no-delay interbeds and 2–5 layers. Record the chosen site in the playbook row.

- [ ] **Step 2: Write the Target 9 prompt**

Follow the Target 7/8 shape: `check_environment` first; state the site's data layout; allow running `prep_data.py` as data prep; require the MF6 model to be built/run/calibrated only through MCP tools; require `add_csub_package`, `read_compaction`/`plot_subsidence`, `setup_calibration(obs_source="derived")` → `run_pestpp_ies` → `summarise_calibration`; require `run-log.md` with tool-call sequence, reprompts, deviations, convergence and calibration evidence.

- [ ] **Step 3: Add the registry row and tasks entry**

Holdout-registry Round-4 row: source URL, branch `Multi-IB`, commit, MIT/verify license, local path, capabilities (CSUB, GHB, OBS, pestpp-ies), status. `TASKS.md`: tick the 6d Tier-1 row when passed; keep the v0.3.0 gate note until then.

- [ ] **Step 4: Reload the MCP server (owner action) and dispatch rerun-1**

Owner reloads `/mcps` so the four new tools are live; verify with `check_environment` / tool listing; dispatch one Agent Manager worktree session; capture the run log; file any gap as backlog, fix, re-verify, commit.

- [ ] **Step 5: Rerun-2 (set-and-forget) and record PASS**

Dispatch again with 0 reprompts; on green with no MCP-only violation, record PASS in `TASKS.md` and the registry. Commit the session logs + registry/tasks updates.

```bash
git add research/discovery/playbooks/6d-regional-model-validation.md research/holdout-registry.md TASKS.md research/discovery/sessions/2026-09-19-6d-csub-*
git commit -m "docs(6d): add Target 9 (CSUB) prompt, registry row and rerun logs"
```

---

### Task 11: Final-review fix wave (Criticals 1–2, Importants 3–5, docs)

**Why:** the whole-branch review of Tasks 1–10 found two Critical gaps that will make the closed-book Target 9 run fail, plus three Important defects. The owner approved extending the spec (see the spec's "Addendum (2026-09-19)").

**Files:**
- Modify: `src/groundwater_mcp/tools/builder.py` (`set_simulation` solver + start date; CSUB snapshot invalidation)
- Modify: `src/groundwater_mcp/tools/calibration.py` (time mapping, packagedata snapshot, IES phi reader)
- Modify: `src/groundwater_mcp/utils/model_store.py` (clear CSUB snapshots)
- Modify: `tests/test_csub.py`, `tests/test_csub_calibration.py`, `tests/test_csub_end_to_end.py`
- Modify: `TASKS.md`, `research/discovery/catalog.md`, `research/discovery/sessions/2026-09-19-csub-packagedata-spike.md`

**Interfaces:**
- Consumes: everything from Tasks 1–10.
- Produces: `set_simulation(..., start_date_time=None, newton=None, linear_acceleration=None, outer_maximum=None, under_relaxation=None)`; `model_store.clear_csub_base_snapshot(model, gwf_name)`; a calibrated elapsed-time→date map in `setup_calibration(obs_source="derived")`; `run_pestpp_ies` returning a true IES `mean` phi.

- [ ] **Step 1: Failing tests for Critical 1 (time axis)**

Add a test that builds a model with `start_date_time="1935-01-25"`, `time_units="DAYS"`, a CSUB obs CSV whose `time` column is elapsed days, and observations on non-January-1 calendar dates; assert `setup_calibration(obs_source="derived")` matches every date and never reports a skip. Add a test asserting an elapsed number is not interpreted as a year.

- [ ] **Step 2: Implement the start date and the date map**

Extend `_impl_set_simulation` / `set_simulation` with `start_date_time`, applied to `ModflowTdis` and written to meta. In `calibration.py`, replace the `%Y` numeric shortcut in `_derived_time_key` with conversion via the model start date, and emit the resolved `{sim_time: iso_date}` map as literals into the stdlib-only wrapper. Run the Step 1 tests to green.

- [ ] **Step 3: Failing delay-interbed convergence test for Critical 2**

Add an MF6-gated e2e that mirrors H201: 1×1 column, delay + no-delay interbeds, `ndelaycells=19`, Newton enabled with holdout IMS settings, then `run_simulation` and `read_compaction`. It must fail before Step 4 because Newton cannot be expressed.

- [ ] **Step 4: Implement the solver options**

Extend `_impl_set_simulation` / `set_simulation` with `newton`, `linear_acceleration`, `outer_maximum`, `under_relaxation`; apply to the GWF `newtonoptions` and `ModflowIms`. Do not add a tool; keep the count at 74. Run the Step 3 test to green.

- [ ] **Step 5: Importants 3–5**

- Snapshot the external packagedata on first externalisation and restore it before each setup (`<gwf>.csub_packagedata_pristine.dat`); add a repeatability test.
- Extend the snapshot clearer to remove `*_csub_*_pristine.npy` and call it from `_impl_add_csub_package`; add a test that a deliberate `cg_theta` edit is not reverted.
- Switch the IES phi path to `_read_ies_phi` and tighten the e2e assertion to a meaningful phi.

- [ ] **Step 6: Docs**

Correct the `TASKS.md` v0.3.0 gate sentence (only `1DSubsidenceModeling-MF6CSUB` remains not-passed) and `research/discovery/catalog.md`'s stale CSUB row; record the `add_boundary_package` external-SPD discrepancy (spec risk 3) in the spike findings doc.

- [ ] **Step 7: Full verification and commit**

Run: `pytest -q` && `ruff check src` && `mypy src`
Expected: all green, tool count still 74.

```bash
git add -A
git commit -m "fix(csub): calendar time axis, solver options, snapshots and IES phi reader"
```

---

## Self-Review

**Spec coverage:** Component 1 → Tasks 2–3; Component 2 (`read_compaction`, `plot_subsidence`, `import_subsidence_observations`) → Tasks 3–5; Component 3 (`npf:k33`, `csub:packagedata`, `csub:cg_theta`/`csub:cg_ske_cr`, derived obs) → Tasks 6–8; Component 4 → Task 10. Risks 1–2 → Task 1 spike; risk 3 is an explicit playbook/Task 10 verification item; risks 4–5 → Tasks 3 and 8. Tool count 70 → 74 is asserted in Tasks 2, 3, 4, 5.

**Placeholder scan:** the only intentional non-exact content is the Task 1 spike (an investigation whose deliverable is the findings doc) and the `_install_csub` / `_register_*_obs` test-helper bodies, which are named with their exact responsibilities and follow the existing `tests/test_da_control.py` helpers. No "TODO"/"handle edge cases" steps.

**Type consistency:** `_impl_add_csub_package(...) -> dict`, `_impl_read_compaction(model, max_rows=500) -> dict`, `_impl_plot_subsidence(model, observed_csv=None, output_file=None) -> dict`, `_impl_import_subsidence_observations(model, observed_csv, time_col="datetime", value_col="Subsidence_ft", sim_source=None, name="subsidence") -> dict`, and `_impl_rewire_npf_array_external(model, keyword, filename=None, flush=True)` are used consistently across Tasks 2–9. Meta keys `csub` and `derived_observations` are used consistently.
