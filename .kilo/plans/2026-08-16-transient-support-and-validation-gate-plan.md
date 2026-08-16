# v0.1.0 Gate — Transient Support (STO) + Expanded Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transient simulations work and fail loudly through the MCP (new `add_sto_package` tool + transient-without-STO guard), and broaden the v0.1.0 validation to harder real models (test005_advgw_tidal, pestpp freyberg) so the release gate rests on more than simple steady-state tutorials.

**Architecture:** Add `add_sto_package` to `builder.py` following the existing `_impl_add_*` pattern (flopy `ModflowGwfsto`, period indices 0-based in the tool, written 1-based). Add a shared `_transient_like_without_sto` helper consumed by `check_model` (structured warning) and `run_simulation` (result `"warning"` + stderr + listing). Extend the sealed holdout replay (`tests/test_holdout_replay.py`) to replay STO, and add two new sealed projects (test005, freyberg) via sparse git clones. Docs/matrix/tool-count updated to 39 tools.

**Tech Stack:** Python 3.12 (venv at `.venv`), flopy 3.10.0, MODFLOW 6 binary at `C:\Users\jakob\.local\bin\mf6.exe`, PEST++ at `C:\Users\jakob\.local\bin\pestpp-glm.exe`, pytest, ruff + mypy.

## Global Constraints

- Windows / PowerShell 7. Use `& .venv\Scripts\python.exe -m pytest <path> -v` to run tests.
- Verify STO period semantics in flopy 3.10.0: `ModflowGwfsto(..., steady_state={0: True}, transient={1: True})` writes `BEGIN period 1 STEADY-STATE` / `BEGIN period 2 TRANSIENT` (0-based dict keys → 1-based blocks). MCP tool inputs stay **0-based**.
- All tool return envelopes follow the existing schema — success dicts have no `"error"` key; failures use `{"error": True, "code", "message", "suggestion"}`.
- Model-name cap: MODFLOW 6 MODELNAME ≤ 16 chars — validated in `create_model`.
- Holdout data never enters the repo: `GW-MCP-holdout/` is a sibling folder; replay tests read it read-only and skip when absent (`GW_MCP_HOLDOUT` env var).
- GAP capabilities (DISU, MAW, UZF, LAK, GNC, MVR, GWT, SWT, OBS) remain unexposed at v0.1.0 — `add_sto_package` is the ONLY new package tool.
- Existing tests must stay green (233 currently passing). Run the full suite at the end.
- Lint: `ruff` and `mypy` must pass on changed files.
- Commits happen at task end; ask the user before committing (repo guardrail).
- No new runtime dependencies beyond what is already installed (numpy is already a dependency of flopy).

---

### Task 1: `add_sto_package` tool in builder.py

**Files:**
- Modify: `src/groundwater_mcp/tools/builder.py`
- Test: `tests/test_builder.py`

**Interfaces:**
- Produces: `_impl_add_sto_package(model: str, iconvert: int | list, ss: float | list, sy: float | list | None, steady_state: list[int] | None, save_flows: bool) -> dict` and MCP tool `add_sto_package`. Also imports `numpy as np` at module top. Storage period resolution is persisted to the workspace meta file under keys `sto_steady_state` / `sto_transient` (read later by `summarise_model` in Task 2).
- Consumes: `get_gwf`, `get_sim`, `save_sim` from `groundwater_mcp.utils.model_store`; `_read_meta`, `_write_meta` already defined in builder.py.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_builder.py` (import `_impl_add_sto_package` and `numpy` at the top):

```python
from groundwater_mcp.tools.builder import _impl_add_sto_package  # add to existing import block
import numpy as np  # add to imports
```

```python
# ---------------------------------------------------------------------------
# add_sto_package
# ---------------------------------------------------------------------------


def test_add_sto_package_defaults(model_with_dis):
    """Default steady_state=[0] → SP0 steady, rest transient."""
    result = _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=None, save_flows=True
    )
    assert "error" not in result
    assert result["package"] == "STO"
    assert result["steady_state_periods"] == [0]
    assert result["transient_periods"] == [1]
    assert result["save_flows"] is True


def test_add_sto_package_writes_sto_file(model_with_dis):
    from groundwater_mcp.utils.workspace import resolve_workspace

    _impl_add_sto_package(model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=None, save_flows=True)
    ws = resolve_workspace(model_with_dis)
    sto_file = ws / f"{model_with_dis}.sto"
    assert sto_file.exists()
    text = sto_file.read_text().upper()
    assert "SAVE_FLOWS" in text
    assert "STEADY-STATE" in text  # period 1 (0-based 0)
    assert "TRANSIENT" in text     # period 2 (0-based 1)


def test_add_sto_package_sy_required_for_convertible(model_with_dis):
    """sy is mandatory when any cell is convertible (iconvert>0)."""
    with pytest.raises(ValueError, match="sy"):
        _impl_add_sto_package(model_with_dis, iconvert=1, ss=1e-5, sy=None, steady_state=None, save_flows=True)


def test_add_sto_package_sy_optional_when_confined(model_with_dis):
    result = _impl_add_sto_package(model_with_dis, iconvert=0, ss=1e-5, sy=None, steady_state=[0], save_flows=True)
    assert "error" not in result


def test_add_sto_package_requires_tdis(model_with_dis):
    """set_simulation must run first so the period count is known."""
    from groundwater_mcp.tools.builder import _impl_set_simulation

    name = model_with_dis
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    # strip TDIS to force the guard
    from groundwater_mcp.utils.model_store import get_sim, save_sim

    sim = get_sim(name)
    tdis = sim.get_package("tdis")
    sim.remove_package(tdis)
    save_sim(name, sim)
    with pytest.raises(ValueError, match="set_simulation"):
        _impl_add_sto_package(name, iconvert=1, ss=1e-5, sy=0.2, steady_state=None, save_flows=True)


def test_add_sto_package_steady_state_out_of_range(model_with_dis):
    with pytest.raises(ValueError, match="out of range"):
        _impl_add_sto_package(model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[5], save_flows=True)


def test_add_sto_package_overwrite_warns(model_with_dis):
    first = _impl_add_sto_package(model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True)
    assert "warning" not in first
    second = _impl_add_sto_package(model_with_dis, iconvert=1, ss=2e-5, sy=0.3, steady_state=[0], save_flows=True)
    assert "warning" in second


def test_add_sto_package_single_period_stays_steady(tmp_path, model_name):
    """nper=1 → all periods steady, no TRANSIENT block."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    result = _impl_add_sto_package(model_name, iconvert=0, ss=1e-5, sy=None, steady_state=None, save_flows=True)
    assert result["steady_state_periods"] == [0]
    assert result["transient_periods"] == []
    from groundwater_mcp.utils.workspace import resolve_workspace

    text = (resolve_workspace(model_name) / f"{model_name}.sto").read_text().upper()
    assert "TRANSIENT" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_builder.py -k sto -v`
Expected: FAIL — `ImportError: cannot import name '_impl_add_sto_package'`

- [ ] **Step 3: Implement**

In `src/groundwater_mcp/tools/builder.py`:

1. Add `import numpy as np` to the imports (after `from pathlib import Path`).
2. Add the implementation function after `_impl_add_ic_package`:

```python
def _impl_add_sto_package(
    model: str,
    iconvert: int | list,
    ss: float | list,
    sy: float | list | None,
    steady_state: list[int] | None,
    save_flows: bool,
) -> dict:
    """Add a Storage (STO) package.

    Required for transient simulations. ``steady_state`` holds the 0-based
    stress-period indices (matching set_simulation) that are steady-state;
    every other period is transient. Default ``[0]`` → first period steady,
    the rest transient (nper=1 stays fully steady). ``sy`` (specific yield)
    is required when any cell is convertible (iconvert>0).
    """
    gwf = get_gwf(model)
    sim = get_sim(model)

    tdis = sim.get_package("tdis")
    if tdis is None:
        raise ValueError(
            "set_simulation must be called before add_sto_package so the "
            "stress-period count is known."
        )
    nper = int(tdis.nper.array)

    if steady_state is None:
        steady_state = [0]
    else:
        steady_state = sorted(int(i) for i in steady_state)
        for i in steady_state:
            if not (0 <= i < nper):
                raise ValueError(
                    f"steady_state period index {i} out of range for nper={nper}. "
                    "Use 0-based indices matching set_simulation."
                )

    if sy is None:
        iconvert_arr = np.asarray(iconvert, dtype=int)
        has_convertible = (
            int(iconvert_arr) > 0
            if iconvert_arr.ndim == 0
            else bool((iconvert_arr > 0).any())
        )
        if has_convertible:
            raise ValueError(
                "sy (specific yield) is required because iconvert contains at "
                "least one convertible cell (iconvert>0)."
            )

    pkg = gwf.get_package("sto")
    replaced = pkg is not None
    if pkg is not None:
        gwf.remove_package(pkg)

    sto_kwargs: dict = {"iconvert": iconvert, "ss": ss, "save_flows": save_flows}
    if sy is not None:
        sto_kwargs["sy"] = sy
    if steady_state:
        sto_kwargs["steady_state"] = {i: True for i in steady_state}
    transient_start = max(steady_state) + 1
    if transient_start < nper:
        sto_kwargs["transient"] = {transient_start: True}

    mf6.ModflowGwfsto(gwf, **sto_kwargs)
    save_sim(model, sim)

    transient_periods = [i for i in range(nper) if i not in set(steady_state)]
    ws = resolve_workspace(model)
    meta = _read_meta(ws)
    meta["sto_steady_state"] = steady_state
    meta["sto_transient"] = transient_periods
    _write_meta(ws, meta)

    result: dict = {
        "model": model,
        "package": "STO",
        "steady_state_periods": steady_state,
        "transient_periods": transient_periods,
        "save_flows": save_flows,
    }
    if replaced:
        result["warning"] = "A previous STO package was removed and replaced by this call."
    return result
```

3. Register the tool inside `register(mcp)` after `add_ic_package`:

```python
    @mcp.tool()
    def add_sto_package(
        model: str,
        iconvert: int | list,
        ss: float | list,
        sy: float | list | None = None,
        steady_state: list[int] | None = None,
        save_flows: bool = True,
    ) -> dict:
        """Add a Storage (STO) package defining aquifer storage properties.

        Required for transient simulations (without it, a multi-time-step
        model silently runs as steady state). ``steady_state`` lists the
        0-based stress-period indices (matching set_simulation) that are
        steady-state; all other periods run transient. Default ``[0]`` marks
        the first period steady and the rest transient. ``sy`` (specific
        yield) is required when any cell is convertible (iconvert>0)."""
        try:
            return _impl_add_sto_package(
                model, iconvert, ss, sy, steady_state, save_flows
            )
        except KeyError as exc:
            return _err("MODEL_NOT_FOUND", str(exc), "Run create_model first.")
        except ValueError as exc:
            return _err("INVALID_INPUT", str(exc))
        except Exception as exc:
            return _err("PACKAGE_ERROR", str(exc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_builder.py -k sto -v`
Expected: PASS (all new STO tests).

- [ ] **Step 5: Lint and commit (ask user before committing)**

Run: `& .venv\Scripts\python.exe -m ruff check src/groundwater_mcp/tools/builder.py tests/test_builder.py`
If the user approves: `git add src/groundwater_mcp/tools/builder.py tests/test_builder.py && git commit -m "feat(builder): add add_sto_package tool for transient storage"`

---

### Task 2: Transient-without-STO guard + `summarise_model` storage

**Files:**
- Modify: `src/groundwater_mcp/tools/builder.py` (helper + summarise storage)
- Modify: `src/groundwater_mcp/tools/runner.py` (check_model + run_simulation warnings)
- Test: `tests/test_builder.py`, `tests/test_runner.py`

**Interfaces:**
- Produces: `_transient_like_without_sto(sim, gwf) -> tuple[bool, str]` in builder.py; `check_model` warnings gain a structured STO entry (`type`, `package`, `description`); `run_simulation` result gains `"warning"` (str) when the trap fires; `summarise_model` result gains `"storage"` (dict|None).
- Consumes: Task 1's meta keys `sto_steady_state` / `sto_transient`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_builder.py`:

```python
def test_transient_like_without_sto_detects_trap(model_with_dis):
    """nper=2 with no STO must flag the steady-state trap."""
    from groundwater_mcp.tools.builder import _transient_like_without_sto
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    gwf = get_gwf(model_with_dis)
    sim = get_sim(model_with_dis)
    trap, msg = _transient_like_without_sto(sim, gwf)
    assert trap is True
    assert "STO" in msg


def test_transient_like_without_sto_clean_with_sto(model_with_dis):
    from groundwater_mcp.tools.builder import _impl_add_sto_package, _transient_like_without_sto
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    _impl_add_sto_package(model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True)
    gwf = get_gwf(model_with_dis)
    sim = get_sim(model_with_dis)
    trap, msg = _transient_like_without_sto(sim, gwf)
    assert trap is False


def test_transient_like_without_sto_clean_when_steady(tmp_path, model_name):
    """nper=1, nstp=1 without STO is a legitimate steady-state model — no trap."""
    from groundwater_mcp.tools.builder import _impl_add_dis_package, _impl_create_model, _impl_set_simulation, _transient_like_without_sto
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    gwf = get_gwf(model_name)
    sim = get_sim(model_name)
    trap, _ = _transient_like_without_sto(sim, gwf)
    assert trap is False


def test_summarise_model_reports_storage(model_with_dis):
    from groundwater_mcp.tools.builder import _impl_add_sto_package

    _impl_add_sto_package(model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True)
    result = _impl_summarise_model(model_with_dis)
    assert result["storage"] == {
        "package": "STO",
        "steady_state_periods": [0],
        "transient_periods": [1],
    }


def test_summarise_model_storage_none_without_sto(model_with_dis):
    result = _impl_summarise_model(model_with_dis)
    assert result["storage"] is None
```

Append to `tests/test_runner.py` (add `_impl_add_sto_package` to the builder import list):

```python
def test_check_model_warns_transient_without_sto(tmp_path, model_name):
    from groundwater_mcp.tools.builder import _impl_add_dis_package, _impl_create_model, _impl_set_simulation

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    result = _impl_check_model(model_name)
    assert result["check_passed"] is True  # warning, not an error
    stowarns = [w for w in result["warnings"] if isinstance(w, dict) and "STO" in w.get("package", "").upper()]
    assert stowarns, f"expected an STO warning, got: {result['warnings']}"


def test_check_model_clean_with_sto(tmp_path, model_name):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package, _impl_add_sto_package, _impl_create_model, _impl_set_simulation,
    )

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    _impl_add_sto_package(model_name, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True)
    result = _impl_check_model(model_name)
    assert all("STO" not in w.get("package", "").upper() for w in result["warnings"])


def test_run_simulation_warns_transient_without_sto(runnable_model, monkeypatch):
    """run_simulation returns a warning field when the trap fires (no binary needed)."""
    import groundwater_mcp.tools.runner as runner_module
    from groundwater_mcp.tools.builder import _impl_set_simulation
    from groundwater_mcp.utils import model_store

    _impl_set_simulation(runnable_model, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple")
    monkeypatch.setattr(runner_module, "_find_mf6_binary", lambda: "/fake/mf6")
    sim = model_store.get_sim(runnable_model)
    monkeypatch.setattr(sim, "run_simulation", lambda **_kwargs: (True, ["normal termination"]))

    result = _impl_run_simulation(runnable_model, silent=True)
    assert result["success"] is True
    assert "warning" in result
    assert "STO" in result["warning"]
    assert "WARNING" in result["listing_summary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_builder.py -k "transient_like or storage" tests/test_runner.py -k "sto" -v`
Expected: FAIL — helper not defined / missing keys.

- [ ] **Step 3: Implement**

In `builder.py`, after `_impl_add_ic_package` (or after `_impl_add_sto_package`):

```python
def _transient_like_without_sto(sim, gwf) -> tuple[bool, str]:
    """Return (True, message) when TDIS looks transient but no STO exists.

    MODFLOW 6 runs a model without an STO package as steady state regardless
    of TDIS settings — a multi-time-step configuration is therefore silently
    stripped of storage physics. This helper lets check_model and
    run_simulation surface that loudly.
    """
    if gwf.get_package("sto") is not None:
        return False, ""
    tdis = sim.get_package("tdis")
    if tdis is None:
        return False, ""
    try:
        rows = list(tdis.perioddata.array)
    except Exception:
        return False, ""
    if len(rows) > 1 or any(int(row[1]) > 1 for row in rows):
        return True, (
            "No STO (storage) package present — the model runs as steady state "
            "even though multiple time steps are configured. If a transient "
            "simulation is intended, add storage first: "
            "add_sto_package(iconvert=1, ss=1e-5, sy=0.2)."
        )
    return False, ""
```

In `_impl_summarise_model`, before the final return, add:

```python
    storage: dict | None = None
    if gwf.get_package("sto") is not None:
        meta = _read_meta(ws)
        storage = {
            "package": "STO",
            "steady_state_periods": list(meta.get("sto_steady_state", [])),
            "transient_periods": list(meta.get("sto_transient", [])),
        }
```

and add `"storage": storage,` to the returned dict.

In `runner.py`:

1. Add imports: `from groundwater_mcp.tools.builder import _transient_like_without_sto` and `from groundwater_mcp.utils.model_store import get_gwf` (extend the existing model_store import line to `from groundwater_mcp.utils.model_store import get_gwf, get_sim, invalidate`).

2. In `_impl_check_model`, after the warning/error extraction block (before the final return), add:

```python
    gwf = sim.get_model(model) if model in sim.model_names else None
    if gwf is None:
        mnames = list(sim.model_names)
        gwf = sim.get_model(mnames[0]) if mnames else None
    if gwf is not None:
        trap, sto_msg = _transient_like_without_sto(sim, gwf)
        if trap:
            warnings.append({"type": "warning", "package": "STO", "description": sto_msg})
```

3. In `_impl_run_simulation`, after `sim = get_sim(model)` (reuse the existing `sim` variable; there is currently a duplicate `sim = get_sim(model)` line — keep one), add:

```python
    mnames = list(sim.model_names)
    gwf = sim.get_model(model) if model in mnames else (sim.get_model(mnames[0]) if mnames else None)
    trap, sto_msg = _transient_like_without_sto(sim, gwf) if gwf is not None else (False, "")
```

and in the returned dict, add:

```python
    result = {
        "model": model,
        "success": success,
        "elapsed_s": round(elapsed, 2),
        "convergence": convergence,
        "listing_summary": listing_summary,
    }
    if trap:
        result["warning"] = sto_msg
        result["listing_summary"] = "WARNING: " + sto_msg + "\n" + result["listing_summary"]
        print(f"WARNING: {sto_msg}", file=sys.stderr)
    return result
```

(`sys` is already imported in runner.py.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_builder.py tests/test_runner.py -k "sto or transient_like or storage" -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit (ask user before committing)**

Run: `& .venv\Scripts\python.exe -m ruff check src/groundwater_mcp/tools/builder.py src/groundwater_mcp/tools/runner.py tests/test_builder.py tests/test_runner.py`
If approved: `git add -u && git commit -m "feat(runner): warn loudly when transient config has no STO package"`

---

### Task 3: Model-name length guard in `create_model`

**Files:**
- Modify: `src/groundwater_mcp/tools/builder.py`
- Test: `tests/test_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_builder.py`:

```python
def test_create_model_name_too_long_raises(tmp_path):
    from groundwater_mcp.tools.builder import _impl_create_model

    long_name = "tutorial05_catchment"  # 21 chars — exceeds MF6's 16-char MODELNAME cap
    with pytest.raises(ValueError, match="16 characters"):
        _impl_create_model(long_name, str(tmp_path / "ws"), "METERS", "DAYS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_builder.py -k name_too_long -v`
Expected: FAIL (no validation currently).

- [ ] **Step 3: Implement**

In `_impl_create_model`, before `model_dir = create_workspace(...)`, add:

```python
    if len(name) > 16:
        raise ValueError(
            f"Model name '{name}' is {len(name)} characters; MODFLOW 6 caps "
            "MODELNAME at 16 characters. Use a shorter name."
        )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_builder.py -k name_too_long -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit (ask user before committing)**

If approved: `git add src/groundwater_mcp/tools/builder.py tests/test_builder.py && git commit -m "fix(builder): reject model names longer than 16 chars in create_model"`

---

### Task 4: MCP protocol test — 39 tools

**Files:**
- Modify: `tests/test_mcp_protocol.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_mcp_protocol.py`:
- Line 4 docstring: `all 38 tools` → `all 39 tools`.
- `_EXPECTED_TOOL_COUNT = 38` → `39`.
- Add `"add_sto_package",` to the `"builder"` list (after `"add_oc_package"`).

- [ ] **Step 2: Run it to verify it fails**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_mcp_protocol.py -v`
Expected: FAIL — count is 39, expected 38.

- [ ] **Step 3: Re-run to verify it passes**

The tool is registered from Task 1, so the test should now pass:
Run: `& .venv\Scripts\python.exe -m pytest tests/test_mcp_protocol.py -v`
Expected: PASS (24 tests).

- [ ] **Step 4: Commit (ask user before committing)**

If approved: `git add tests/test_mcp_protocol.py && git commit -m "test(protocol): expect 39 tools including add_sto_package"`

---

### Task 5: Transient integration tests (new file)

**Files:**
- Create: `tests/test_integration_transient.py`

**Interfaces:**
- Consumes: Task 1 + Task 2 implementations. `_impl_read_heads` returns `values` (nested list) + `min/max/mean`; `_impl_compute_water_balance` returns `inflow`/`outflow` dicts + totals (labels include `STO-SS` / `STO-SY` when SAVE_FLOWS is on).

- [ ] **Step 1: Write the tests**

Create `tests/test_integration_transient.py`:

```python
"""Integration tests — transient simulations through the MCP tool set.

Require the MODFLOW 6 binary. Verify storage (STO) is genuinely active:
heads evolve across time steps, the budget contains STO terms, and the
transient-without-STO guard fires a loud warning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_add_sto_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.runner import (
    _find_mf6_binary,
    _impl_check_model,
    _impl_run_simulation,
)


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


def _pestpp_available() -> bool:
    return Path(_find_mf6_binary()).parent / "pestpp-glm.exe" or True  # placeholder


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)
```

Replace the `_pestpp_available` placeholder with a real check during implementation (mirror `requires_mf6`, using `shutil.which("pestpp-glm")`), then add:

```python
requires_pestpp = pytest.mark.skipif(
    not _pestpp_available(), reason="pestpp-glm not installed"
)


@pytest.fixture()
def transient_model(tmp_path, model_name):
    """3-period transient 1-layer 5x5 model with STO; SP0 steady, SP1-2 transient."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=3, perlen=[100.0, 100.0, 100.0], nstp=[3, 3, 3], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=1, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    _impl_add_sto_package(model_name, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)
    return model_name


@requires_mf6
def test_transient_model_runs_and_converges(transient_model):
    r = _impl_run_simulation(transient_model, silent=True)
    assert "error" not in r
    assert r["success"] is True
    assert r["convergence"] == "converged"
    assert "warning" not in r  # STO present -> no guard warning


@requires_mf6
def test_transient_heads_evolve_across_time(transient_model):
    """With storage active, head at the last time step must differ from the first."""
    from groundwater_mcp.tools.postprocess import _impl_read_heads

    _impl_run_simulation(transient_model, silent=True)
    h0 = _impl_read_heads(transient_model, kstpkper=[0, 0], layer=0)
    h2 = _impl_read_heads(transient_model, kstpkper=[2, 2], layer=0)
    flat0 = [v for row in h0["values"] for v in row]
    flat2 = [v for row in h2["values"] for v in row]
    max_diff = max(abs(x - y) for x, y in zip(flat0, flat2))
    assert max_diff > 1e-3, f"heads static across time steps — storage inactive: {max_diff}"


@requires_mf6
def test_transient_water_balance_contains_sto(transient_model):
    from groundwater_mcp.tools.postprocess import _impl_compute_water_balance

    _impl_run_simulation(transient_model, silent=True)
    wb = _impl_compute_water_balance(transient_model, kstpkper=[2, 2])
    labels = {**wb["inflow"], **wb["outflow"]}
    assert any(k.upper().startswith("STO") for k in labels), f"no STO budget term: {labels}"


@requires_mf6
def test_transient_without_sto_warns(tmp_path, model_name):
    """The exact trap from the review: transient config without STO must warn."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=1, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)

    r = _impl_check_model(model_name)
    assert r["check_passed"] is True
    assert any("STO" in w.get("package", "").upper() for w in r["warnings"]), r["warnings"]

    r = _impl_run_simulation(model_name, silent=True)
    assert r["success"] is True
    assert "warning" in r and "STO" in r["warning"], r
```

- [ ] **Step 2: Run tests to verify they fail (or confirm the trap)**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_integration_transient.py -v`
Expected: with Tasks 1–2 done these should PASS; before Task 1 the imports fail. If a test fails because `read_heads`/`compute_water_balance` keys differ, adjust the assertions to the actual keys (documented deviation).

- [ ] **Step 3: Verify the suite runs clean**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_integration_transient.py -v`
Expected: 5 PASS.

- [ ] **Step 4: Commit (ask user before committing)**

If approved: `git add tests/test_integration_transient.py && git commit -m "test(integration): transient STO build/run/postprocess + guard warning"`

---

### Task 6: Transient calibration chain test

**Files:**
- Modify: `tests/test_integration_transient.py` (append)

**Interfaces:**
- Consumes: `calibration._impl_setup_pest_control`, `_impl_run_pestpp_glm`, `_impl_summarise_calibration` (signatures verified in `tests/test_calibration.py`).

- [ ] **Step 1: Write the test**

Append to `tests/test_integration_transient.py`:

```python
@requires_pestpp
def test_transient_calibration_chain(transient_model):
    """setup_pest_control -> run_pestpp_glm -> summarise_calibration on a transient model."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_pest_control,
        _impl_summarise_calibration,
    )
    from groundwater_mcp.utils.workspace import resolve_workspace

    model = transient_model
    _impl_run_simulation(model, silent=True)
    ws = resolve_workspace(model)

    (ws / "k_mult.tpl").write_text("ptf ~\n~  kmult       ~\n")
    (ws / "k_mult").write_text("10.0\n")
    (ws / "obs_heads.ins").write_text(
        "pif @\n" + "\n".join(f"l1 !h{i}!" for i in range(1, 6)) + "\n"
    )
    obs_vals = [7.0, 6.5, 5.5, 4.5, 4.0]
    (ws / "obs_heads").write_text("\n".join(str(v) for v in obs_vals) + "\n")

    obs_data = {f"h{i}": {"obsval": v, "weight": 1.0} for i, v in enumerate(obs_vals, 1)}
    par_data = {"kmult": {"parval1": 1.0, "parlbnd": 0.01, "parubnd": 100.0, "pargp": "hk"}}

    setup = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(ws / "k_mult.tpl")],
        instruction_files=[str(ws / "obs_heads.ins")],
        pestpp_options={"noptmax": 3},
    )
    assert "error" not in setup

    run = _impl_run_pestpp_glm(model, setup["pst_file"])
    assert "error" not in run
    assert run["iterations"] >= 0

    summ = _impl_summarise_calibration(model, setup["pst_file"])
    assert "error" not in summ
    assert len(summ["parameter_estimates"]) == 1
    assert summ["parameter_estimates"][0]["name"] == "kmult"
```

- [ ] **Step 2: Run it to verify it passes**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_integration_transient.py -k calibration_chain -v`
Expected: PASS (may take ~30–60 s for the GLM run).

- [ ] **Step 3: Commit (ask user before committing)**

If approved: `git add tests/test_integration_transient.py && git commit -m "test(integration): PEST++ calibration chain on a transient model"`

---

### Task 7: Holdout replay — replay STO, drop STO from GAP list

**Files:**
- Modify: `tests/test_holdout_replay.py`

**Interfaces:**
- Consumes: Task 1's `add_sto_package` MCP tool (via `mcp.call_tool`), Task 2's behaviour.
- Produces: `_load_project` dict gains `"storage"` (dict|None) with `iconvert`/`ss`/`sy`/`steady_periods`; STO added in `_build_flow_model`; `_GAP_TOOLS` no longer contains `add_sto_package`.

- [ ] **Step 1: Update the GAP list + docstring**

In `tests/test_holdout_replay.py`:
- Remove `"add_sto_package",` from `_GAP_TOOLS` (line ~360).
- Update the module docstring Mode A v1 scope bullet: `STO/UZF/MAW/OBS packages are NOT replayed` → `UZF/MAW/OBS packages are NOT replayed; STO IS replayed (v0.1.0 gate)`.
- Update `test_gap_tools_not_exposed` docstring text that references counts.

- [ ] **Step 2: Extend `_load_project` to parse STO**

Inside `_load_project`, after the `boundaries` block, add:

```python
    # STO package — storage arrays + steady/transient period structure.
    storage: dict | None = None
    sto = gwf.get_package("sto")
    if sto is not None:
        import re

        steady_periods: list[int] = []
        transient_periods: list[int] = []
        sto_file = project_dir / str(sto.filename)
        if sto_file.exists():
            in_period: int | None = None
            for line in sto_file.read_text(errors="replace").splitlines():
                m = re.match(r"\s*BEGIN\s+period\s+(\d+)", line, re.I)
                if m:
                    in_period = int(m.group(1)) - 1  # 0-based
                    continue
                if re.match(r"\s*STEADY-STATE\b", line, re.I) and in_period is not None:
                    steady_periods.append(in_period)
                elif re.match(r"\s*TRANSIENT\b", line, re.I) and in_period is not None:
                    transient_periods.append(in_period)
                elif re.match(r"\s*END\s+period", line, re.I):
                    in_period = None
        storage = {
            "iconvert": np.asarray(sto.iconvert.array, dtype=int).tolist(),
            "ss": np.asarray(sto.ss.array, dtype=float).tolist(),
            "sy": np.asarray(sto.sy.array, dtype=float).tolist()
            if sto.sy is not None else None,
            "steady_periods": steady_periods,
        }
```

and add `"storage": storage,` to the returned dict.

- [ ] **Step 3: Replay STO in `_build_flow_model`**

After the `add_oc_package` call and before the boundary section, add:

```python
    if proj.get("storage"):
        s = proj["storage"]
        _call("add_sto_package", {
            "model": model_name,
            "iconvert": s["iconvert"],
            "ss": s["ss"],
            "sy": s["sy"],
            "steady_state": s["steady_periods"],
        })
```

- [ ] **Step 4: Run the replay tests**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_holdout_replay.py -k "flow or gap" -v`
Expected: PASS (test051 + test020 replay now include STO; GAP gate passes without STO listed).

- [ ] **Step 5: Commit (ask user before committing)**

If approved: `git add tests/test_holdout_replay.py && git commit -m "test(holdout): replay STO in Mode A flow projects; STO no longer a GAP"`

---

### Task 8: Holdout expansion — test005_advgw_tidal + freyberg

**Files:**
- Create (outside repo): `GW-MCP-holdout/selected/test005_advgw_tidal/`, `GW-MCP-holdout/selected/mf6_freyberg/`
- Modify: `research/holdout-registry.md`, `research/capability-matrix.md`, `tests/test_holdout_replay.py`

**Interfaces:**
- Produces: registry rows pinned to commits; `_FLOW_PROJECTS` gains `test005_advgw_tidal`; new slow test `test_freyberg_calibration_chain` (env-gated).

- [ ] **Step 1: Download test005 into the holdout**

```powershell
git clone --filter=blob:none --no-checkout https://github.com/MODFLOW-ORG/modflow6-testmodels "$env:TEMP\testmodels"
git -C "$env:TEMP\testmodels" sparse-checkout init --cone
git -C "$env:TEMP\testmodels" sparse-checkout set mf6/test005_advgw_tidal
git -C "$env:TEMP\testmodels" checkout 96a6d4fe015967972b051d311d34679224bc6d75
Copy-Item -Recurse "$env:TEMP\testmodels\mf6\test005_advgw_tidal" "C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\test005_advgw_tidal"
```

Verify: `mfsim.nam`, `.dis`, `.sto`, `.wel`, `.riv`, `.rch`, `.ghb`, `.evt`, `.obs` present.

- [ ] **Step 2: Download freyberg template into the holdout**

```powershell
git clone --filter=blob:none --no-checkout https://github.com/usgs/pestpp "$env:TEMP\pestpp"
git -C "$env:TEMP\pestpp" sparse-checkout init --cone
git -C "$env:TEMP\pestpp" sparse-checkout set benchmarks/mf6_freyberg/template
git -C "$env:TEMP\pestpp" checkout 5d49814962531a0f0400cf75d0f9442c0504c714
New-Item -ItemType Directory -Force -Path "C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\mf6_freyberg"
Copy-Item -Recurse "$env:TEMP\pestpp\benchmarks\mf6_freyberg\template\*" "C:\Users\jakob\Documents\Cursor projects\GW-MCP-holdout\selected\mf6_freyberg"
```

Verify: `freyberg6.nam`, `mfsim.nam`, `.pst`, `.tpl`, `.ins`, obs files present.

- [ ] **Step 3: Update `research/holdout-registry.md`**

Append two rows to the Round-1 selections section (or a new "Round-2 (v0.1.0 gate)" section):

| Name | Source | License | Local path | Capabilities | Validation status | Notes |
|---|---|---|---|---|---|---|
| test005_advgw_tidal | MODFLOW-ORG/modflow6-testmodels @ `96a6d4fe` | USGS public domain | `selected/test005_advgw_tidal/` | STO, WEL, RIV, RCH (x3), GHB, EVT, OBS, time series | pending v0.1.0 freeze | multi-BC + OBS + TS stress; replay covers list-based BCs + STO; RCH/EVT TS not replayed (deviation) |
| mf6_freyberg | usgs/pestpp @ `5d49814` | public domain (USGS) | `selected/mf6_freyberg/` | DIS, STO, SFR, OBS, pestpp-glm | pending v0.1.0 freeze | calibration benchmark (TM7C26); adopted into MCP workspace for run + calibration-chain validation (slow) |

Also update the `capability-matrix.md` STO row: `**gap**` → `covered`, covering tool `add_sto_package`, note "v0.1.0 gate".

- [ ] **Step 4: Add test005 to the flow replay**

In `tests/test_holdout_replay.py`:
- Add `"test005_advgw_tidal": ["WEL", "GHB", "RIV", "DRN", "CHD"]` to `_BOUNDARY_FILES`.
- Add `"test005_advgw_tidal": False` to `_BALANCE_EXPECTED` (RCH/EVT time-series not replayed).
- Add `"test005_advgw_tidal"` to `_FLOW_PROJECTS`.
- Extend the boundary parse loop in `_load_project` from `for pkg in ("WEL", "GHB"):` to `for pkg in ("WEL", "GHB", "RIV", "DRN", "CHD"):` and guard each record: wrap the `float(row[n])` conversion so a non-numeric value (time-series placeholder) skips the whole package:

```python
        try:
            for row in frame:
                cellid = row["cellid"]
                cellid = [int(v) for v in cellid] if hasattr(cellid, "__iter__") else [int(cellid)]
                records.append([cellid, *[float(row[n]) for n in names if n != "cellid"]])
        except (TypeError, ValueError):
            continue  # time-series aux column — package not replayable (deviation)
```

- Note the deviation in the module docstring (RCH/EVT with time series not replayed for test005).

Run: `& .venv\Scripts\python.exe -m pytest tests/test_holdout_replay.py -k "test005 or flow" -v`
Expected: test005 flow replay PASS (with partial boundary replay).

- [ ] **Step 5: Freyberg calibration chain (slow, env-gated)**

Append to `tests/test_holdout_replay.py`:

```python
@pytest.mark.slow
@requires_mf6
def test_freyberg_calibration_chain(holdout_root, tmp_path):
    """Adopt the sealed freyberg benchmark into an MCP workspace and run the
    full calibration chain (setup_pest_control -> run_pestpp_glm ->
    summarise_calibration). Exercises SFR-bearing real-model calibration."""
    import shutil

    src = _selected_dir(holdout_root, "mf6_freyberg")
    if not src.is_dir():
        pytest.skip("holdout project mf6_freyberg not present")

    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_pest_control,
        _impl_summarise_calibration,
    )
    from groundwater_mcp.tools.builder import _impl_create_model
    from groundwater_mcp.tools.runner import _impl_run_simulation

    model = "freyberg"
    _impl_create_model(model, str(tmp_path / model), "METERS", "DAYS")
    ws_dir = resolve_workspace(model)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, ws_dir / f.name)

    # The adopted model replaces the empty MCP skeleton.
    from groundwater_mcp.utils.model_store import invalidate
    invalidate(model)

    r = _impl_run_simulation(model, silent=True)
    assert r["success"] is True, f"freyberg did not converge: {r}"

    # Calibration: build obs_data/par_data from freyberg's shipped .pst.
    # Parse the freyberg .pst's observation + parameter blocks.
    pst = next(ws_dir.glob("*.pst"))
    ...  # see Step 5a — parse obs names/values/weights and parameter rows
    setup = _impl_setup_pest_control(
        model=model, obs_data=obs_data, par_data=par_data,
        template_files=[...freyberg .tpl files...],
        instruction_files=[...freyberg .ins files...],
        pestpp_options={"noptmax": 5},
    )
    run = _impl_run_pestpp_glm(model, setup["pst_file"])
    assert "error" not in run
    summ = _impl_summarise_calibration(model, setup["pst_file"])
    assert "error" not in summ
```

- [ ] **Step 5a: Implement the freyberg .pst parsing helper**

Add a module-level helper in `tests/test_holdout_replay.py`:

```python
def _parse_pst_for_setup(pst_file: Path) -> tuple[dict, dict, list[str], list[str]]:
    """Extract (obs_data, par_data, tpl_files, ins_files) from a classic PEST .pst.

    Parses the observation data + parameter data blocks; template/instruction
    files are resolved relative to the .pst's directory from the *file* columns
    of the observation and parameter data sections (name<->tpl<->ins linkage
    via the tpl/ins filenames stored under 'template file' / 'instruction file'
    rows of the control file header section).
    """
    ...
```

During implementation, verify against freyberg's actual .pst layout (classic PEST `* template data` / `* single point observation data` / `* parameter data` sections) and write the parser to those fixed columns. `obs_data` keys MUST match the `.ins` tokens exactly (case-insensitive) — the `setup_pest_control` validation requires it.

- [ ] **Step 5b: Run the freyberg test (slow)**

Run: `& .venv\Scripts\python.exe -m pytest tests/test_holdout_replay.py -k freyberg -v -m slow`
Expected: PASS. If a specific parse issue blocks it, fix it in the same task and document the deviation in the registry row.

- [ ] **Step 6: Commit (ask user before committing)**

If approved: `git add research/holdout-registry.md research/capability-matrix.md tests/test_holdout_replay.py && git commit -m "test(holdout): add test005 + freyberg validation rows; replay STO"`

---

### Task 9: Docs and matrix sync

**Files:**
- Modify: `tools.md`, `README.md`, `architecture.md`, `research/capability-matrix.md`, `tasks.md`, `.kilo/plans/2026-08-16-transient-support-and-validation-gate.md`

- [ ] **Step 1: tools.md**

- Change title line `38 tools across 7 modules` → `39 tools across 7 modules`.
- Add `add_sto_package` row to the model-builder table:
  `| add_sto_package | model: str, iconvert: int \| list, ss: float \| list, sy: float \| list \| None, steady_state: list[int] \| None, save_flows: bool = True | Package summary with resolved steady/transient periods |`
- Add a note under the model-builder section: "Transient simulations require `add_sto_package`. Without it, a multi-time-step model runs as steady state — `check_model` and `run_simulation` return a warning when they detect that configuration."

- [ ] **Step 2: README.md + architecture.md**

- README: `## Tools (38 total)` → `(39 total)`. Keep the transient example (now achievable).
- architecture.md: update "38 tools across 7 modules" → 39; add `add_sto_package` to the builder tool list in the file-structure section.

- [ ] **Step 3: capability-matrix.md**

- STO row: Status `**gap**` → `covered`; covering tool `add_sto_package`; note `v0.1.0 gate (2026-08-16)`.
- Update the coverage-summary line: gap count 12 → 11, covered 14 → 15.

- [ ] **Step 4: tasks.md**

- Move "STO (storage) exposure — `add_sto_package`" from the v0.2.0 build-order list into a new completed "Phase 6c — Transient support + expanded validation gate (v0.1.0)" section with checkboxes for: `add_sto_package` tool, transient-without-STO guard, name-length guard, transient integration tests, transient calibration test, holdout STO replay, test005 + freyberg replay, 39-tool suite green, docs synced.
- Update the header status line to note the gate is in progress.

- [ ] **Step 5: Verify the full suite + lint + mypy**

Run:
```powershell
& .venv\Scripts\python.exe -m pytest -q
& .venv\Scripts\python.exe -m ruff check src tests
& .venv\Scripts\python.exe -m mypy src/groundwater_mcp
```
Expected: all tests green (incl. holdout replay + integration), ruff clean, mypy clean.

- [ ] **Step 6: Commit (ask user before committing)**

If approved: `git add tools.md README.md architecture.md research/capability-matrix.md tasks.md && git commit -m "docs: 39 tools, STO covered, v0.1.0 transient gate status"`

---

## Self-review notes

- STO tool / guard / name guard / protocol count: Tasks 1–4.
- Transient physics proven: Task 5 (heads evolve, STO budget term).
- Transient calibration: Task 6.
- Holdout STO replay + GAP cleanup: Task 7.
- Harder models (test005 multi-BC, freyberg calibration benchmark): Task 8.
- Docs/matrix/registry/tasks sync: Tasks 8–9.
- Placeholders: freyberg .pst parser (Task 8 Step 5a) is specified as a to-implement helper — its exact column layout is verified against the downloaded file during execution, then fixed in place (no TBD left in code).
- Type consistency: `_impl_add_sto_package` signature identical across Tasks 1, 5, 6, 7; `_transient_like_without_sto(sim, gwf)` identical across Tasks 2 and 5.
