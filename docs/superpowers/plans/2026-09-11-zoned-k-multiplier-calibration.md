# Zoned NPF K multiplier calibration — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scope: "zones"` to `setup_calibration` so a zoned K field is
calibrated by a small set of per-zone multipliers that preserve the base K
pattern, then rerun the neversink 6d target through the fixed chain.

**Architecture:** Zones are auto-derived from groups of equal positive K values
within a layer. Each zone becomes a dimensionless PEST parameter. A generated
forward wrapper computes `k = base_k × multiplier[zone]` and writes the NPF
external K file before running MODFLOW 6, so PEST never substitutes absolute K
values and the base spatial pattern is preserved at multiplier 1.0.

**Tech Stack:** Python 3.11+, flopy ≥ 3.7, pyemu, PEST++, numpy, pytest, ruff,
mypy.

**Spec:** `docs/superpowers/specs/2026-09-11-zoned-k-multiplier-calibration-design.md`

## Global Constraints

- Python 3.11+; flopy ≥ 3.7; pyemu; numpy/pandas already imported in
  `calibration.py`.
- All new functions live in `src/groundwater_mcp/tools/calibration.py`; no new
  tool is registered, so the tool count stays **66**.
- PEST parameter names are capped at **12 characters**; observation names at
  **20**.
- Template tokens must be **wide fixed-width** (`≥ 15` chars); the existing
  `_TPL_TOKEN_WIDTH = 15` constant is reused.
- Zone parameter names are `<prefix>_z<index>` with a global, 1-based index
  ordered by `(layer ascending, base K ascending)`; indices are contiguous.
- Multiplier `initial` defaults to `1.0`, meaning the base field is unchanged.
- All new user-input failures raise `ValueError` (surfaced as `INVALID_INPUT`).
- Tests run with `pytest`; lint `ruff check`, types `mypy`. Run all three on
  touched files before each commit.
- Do not edit holdout data; the neversink reruns are dispatched separately.

---

### Task 1: Zone derivation helper

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py` (add near
  `_normalise_parameterisation`, after line 807 `_SUPPORTED_TARGETS`).
- Test: `tests/test_zoned_calibration.py` (create).

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `_round_sig_array(values: np.ndarray, sig: int = 6) -> np.ndarray`
  - `_derive_zones(k_layer, max_zones: int) -> tuple[np.ndarray, list[tuple[float, int]]]`
    — returns `(zone_ids, zones)` where `zone_ids` is an int array the same shape
    as `k_layer` (0 = fixed) and `zones` is a list of `(base_k, n_cells)` sorted
    ascending by `base_k`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_zoned_calibration.py`:

```python
"""Zoned NPF K multiplier parameterisation tests (`setup_calibration` scope="zones")."""

from __future__ import annotations

import numpy as np
import pytest


def test_round_sig_array_rounds_to_significant_figures():
    from groundwater_mcp.tools.calibration import _round_sig_array

    out = _round_sig_array(np.array([0.0502921, 0.1676449, 60.96001]), 6)
    assert list(out) == pytest.approx([0.0502921, 0.1676449, 60.96])


def test_derive_zones_groups_equal_values_and_sorts():
    from groundwater_mcp.tools.calibration import _derive_zones

    zids, zones = _derive_zones(np.array([5.0, 1.0, 5.0, 1.0, 1.0]), max_zones=10)
    assert zones == [(1.0, 3), (5.0, 2)]
    assert list(zids) == [2, 1, 2, 1, 1]


def test_derive_zones_excludes_nonpositive_and_nan():
    from groundwater_mcp.tools.calibration import _derive_zones

    zids, zones = _derive_zones(np.array([1.0, -0.0, 0.0, np.nan, 2.0]), max_zones=10)
    assert zones == [(1.0, 1), (2.0, 1)]
    assert zids[1] == 0 and zids[2] == 0 and zids[3] == 0


def test_derive_zones_raises_when_no_positive_cells():
    from groundwater_mcp.tools.calibration import _derive_zones

    with pytest.raises(ValueError, match="no positive"):
        _derive_zones(np.array([0.0, -1.0]), max_zones=10)


def test_derive_zones_raises_over_cap():
    from groundwater_mcp.tools.calibration import _derive_zones

    with pytest.raises(ValueError, match="max_zones"):
        _derive_zones(np.array([1.0, 2.0, 3.0]), max_zones=2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoned_calibration.py -v`
Expected: FAIL (ImportError / cannot import `_derive_zones`).

- [ ] **Step 3: Implement the helpers**

Add to `src/groundwater_mcp/tools/calibration.py` after the
`_SUPPORTED_TARGETS` / `_TPL_TOKEN_WIDTH` block:

```python
def _round_sig_array(values: np.ndarray, sig: int = 6) -> np.ndarray:
    """Round an array to `sig` significant figures, element-wise.

    Used to group K cells into zones: float representation noise must not
    split a shipped zone value into two zones, while the shipped values
    (0.050292, 0.16764, ...) stay distinct.
    """
    arr = np.asarray(values, dtype=float)
    out = np.array(arr, dtype=float, copy=True)
    nz = np.isfinite(arr) & (arr != 0)
    x = np.abs(arr[nz])
    exp = np.floor(np.log10(x))
    factor = 10.0 ** (sig - 1 - exp)
    out[nz] = np.sign(arr[nz]) * (np.round(x * factor) / factor)
    return out


def _derive_zones(k_layer, max_zones: int) -> tuple[np.ndarray, list[tuple[float, int]]]:
    """Group a layer's cells into zones of equal positive K value.

    Returns ``(zone_ids, zones)``: zone_ids is an int array the same shape as
    ``k_layer`` with 0 for fixed (non-positive/non-finite) cells, and zones is
    a list of ``(base_k, n_cells)`` sorted ascending by base_k.
    """
    flat = np.asarray(k_layer, dtype=float).reshape(-1)
    positive = np.isfinite(flat) & (flat > 0)
    if not positive.any():
        raise ValueError("layer has no positive K cells to zone.")
    rounded = _round_sig_array(flat, 6)
    values = np.unique(rounded[positive])
    if len(values) > max_zones:
        raise ValueError(
            f"layer has {len(values)} distinct K values, more than "
            f"max_zones={max_zones}; use a coarser zone input or raise max_zones."
        )
    zone_ids = np.zeros(flat.shape, dtype=int)
    zones: list[tuple[float, int]] = []
    for i, v in enumerate(values, start=1):
        mask = positive & (rounded == v)
        zone_ids[mask] = i
        zones.append((float(v), int(mask.sum())))
    return zone_ids, zones
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoned_calibration.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "feat(calibration): zone derivation helpers for zoned K multiplier"
```

---

### Task 2: Multiplier application helper

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`.
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: nothing.
- Produces:
  `_apply_k_multipliers(base_path, zone_path, mult_path, out_path) -> np.ndarray`
  — reads base/zone/multiplier files, writes `out_path` with
  `k = base × mult[zone]` (zone 0 → base), returns the written array. This is
  called by the generated forward wrapper and by the sensitivity screen.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zoned_calibration.py`:

```python
def _write_mult_files(tmp_path, base, zone, mult):
    base_p = tmp_path / "k_base.dat"
    zone_p = tmp_path / "k_zone.dat"
    mult_p = tmp_path / "k_mult.dat"
    out_p = tmp_path / "k.dat"
    np.savetxt(base_p, np.asarray(base, dtype=float).reshape(-1), fmt="%.10g")
    np.savetxt(zone_p, np.asarray(zone, dtype=int).reshape(-1), fmt="%d")
    np.savetxt(mult_p, np.asarray(mult, dtype=float).reshape(-1), fmt="%.10g")
    return base_p, zone_p, mult_p, out_p


def test_apply_k_multipliers_scales_zoned_cells_only(tmp_path):
    from groundwater_mcp.tools.calibration import _apply_k_multipliers

    base_p, zone_p, mult_p, out_p = _write_mult_files(
        tmp_path,
        base=[2.0, 2.0, 2.0, 2.0],
        zone=[0, 1, 2, 1],
        mult=[3.0, 10.0],
    )
    k = _apply_k_multipliers(base_p, zone_p, mult_p, out_p)
    # zone 0 fixed; zone1 ×3; zone2 ×10
    assert list(k) == pytest.approx([2.0, 6.0, 20.0, 6.0])
    assert list(np.loadtxt(out_p)) == pytest.approx([2.0, 6.0, 20.0, 6.0])


def test_apply_k_multipliers_identity_at_one(tmp_path):
    from groundwater_mcp.tools.calibration import _apply_k_multipliers

    base_p, zone_p, mult_p, out_p = _write_mult_files(
        tmp_path,
        base=[0.05, 0.05, 60.96],
        zone=[1, 1, 2],
        mult=[1.0, 1.0],
    )
    k = _apply_k_multipliers(base_p, zone_p, mult_p, out_p)
    assert list(k) == pytest.approx([0.05, 0.05, 60.96])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoned_calibration.py -k apply_k -v`
Expected: FAIL (cannot import `_apply_k_multipliers`).

- [ ] **Step 3: Implement**

Add after `_derive_zones`:

```python
def _apply_k_multipliers(base_path, zone_path, mult_path, out_path) -> np.ndarray:
    """Write ``k = base_k × multiplier[zone]`` (zone 0 fixed) to ``out_path``."""
    base = np.loadtxt(base_path, dtype=float).reshape(-1)
    zone = np.loadtxt(zone_path, dtype=int).reshape(-1)
    mult = np.atleast_1d(np.loadtxt(mult_path, dtype=float)).reshape(-1)
    factor = np.ones_like(base, dtype=float)
    zoned = zone > 0
    factor[zoned] = mult[zone[zoned] - 1]
    k = base * factor
    np.savetxt(out_path, k, fmt="%.10g")
    return k
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoned_calibration.py -k apply_k -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "feat(calibration): apply zone multipliers to the NPF k array"
```

---

### Task 3: Zoned parameterisation normalisation

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`.
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: `_derive_zones`, `get_gwf`, `_SUPPORTED_TARGETS`.
- Produces:
  `_normalise_zoned_parameterisation(model, parameterisation) -> dict` with keys
  `grid` (same shape as `_normalise_parameterisation`'s grid plus `per_layer`),
  `k_base` (flat `np.ndarray`), `zone_map` (flat int `np.ndarray`, 0 = fixed),
  `zones` (list of dicts: `name`, `index`, `layer`, `base_k`, `n_cells`,
  `initial`, `lower_bound`, `upper_bound`, `partrans`) and `parameters`
  (list of dicts with `name`, `target`, `scope`, `layer`, `initial`,
  `lower_bound`, `upper_bound`, `partrans`).

**Test helpers:** add a zoned model builder at the top of the test file.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zoned_calibration.py`. First add `csv` to the top-of-file
import block (alongside `numpy`/`pytest`), then append the zoned model builder
and tests:

```python
from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)


def _build_zoned_model(tmp_path, name="zoned_model"):
    """1 layer × 5 × 5, two K zones (1.0 in cols 0, 5.0 elsewhere)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 50.0, [30.0])
    k = np.full((1, 5, 5), 5.0)
    k[0, :, 0] = 1.0
    _impl_add_npf_package(name, icelltype=0, k=k, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(5)] + [[[0, r, 4], 10.0] for r in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def test_normalise_zoned_builds_global_indices(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert norm["grid"]["type"] == "DIS"
    assert len(norm["zones"]) == 2
    assert [z["base_k"] for z in norm["zones"]] == [1.0, 5.0]
    assert norm["zones"][0]["name"] == "k_z1"
    assert norm["zones"][1]["name"] == "k_z2"
    assert norm["zones"][0]["n_cells"] == 5
    assert norm["zones"][1]["n_cells"] == 20
    assert norm["zones"][0]["initial"] == 1.0
    assert norm["zone_map"].reshape(5, 5)[0, 0] == 1
    assert norm["zone_map"].reshape(5, 5)[0, 1] == 2


def test_normalise_zoned_requires_layer(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="requires 'layer'"):
        _normalise_zoned_parameterisation(
            name, {"k": {"target": "npf:k", "scope": "zones"}}
        )


def test_normalise_zoned_raises_on_no_positive_layer(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="out of range"):
        _normalise_zoned_parameterisation(
            name, {"k": {"target": "npf:k", "scope": "zones", "layer": 9}}
        )


def test_normalise_zoned_raises_on_name_too_long(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="12"):
        _normalise_zoned_parameterisation(
            name, {"averylongprefix": {"target": "npf:k", "scope": "zones", "layer": 0}}
        )


def test_normalise_zoned_raises_on_max_zones(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="max_zones"):
        _normalise_zoned_parameterisation(
            name,
            {"k": {"target": "npf:k", "scope": "zones", "layer": 0, "max_zones": 1}},
        )


def test_normalise_zoned_disv_layer(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_disv_package
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = "zoned_disv"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    vertices = [[0, 0.0, 0.0], [1, 100.0, 0.0], [2, 100.0, 100.0], [3, 0.0, 100.0]]
    cell2d = [[0, 33.3, 33.3, 3, 0, 1, 2], [1, 66.6, 66.6, 3, 0, 2, 3]]
    _impl_add_disv_package(name, 1, vertices, cell2d, [50.0, 50.0], [[40.0, 40.0]])
    _impl_add_npf_package(name, icelltype=0, k=np.array([[1.0, 4.0]]), k33=None, save_flows=True)
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert norm["grid"]["type"] == "DISV"
    assert norm["grid"]["ncpl"] == 2
    assert [z["base_k"] for z in norm["zones"]] == [1.0, 4.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoned_calibration.py -k normalise_zoned -v`
Expected: FAIL (cannot import `_normalise_zoned_parameterisation`).

- [ ] **Step 3: Implement**

Add after `_apply_k_multipliers`:

```python
def _normalise_zoned_parameterisation(model: str, parameterisation: dict) -> dict:
    """Validate and normalise a ``setup_calibration`` zoned parameterisation.

    Every spec must use ``scope="zones"`` with a ``layer``; zones are derived
    from equal positive K values within that layer. Zone indices are global,
    contiguous and ordered by ``(layer ascending, base K ascending)``.
    """
    if not parameterisation:
        raise ValueError("parameterisation must name at least one parameter.")
    gwf = get_gwf(model)
    npf = gwf.get_package("npf")
    if npf is None:
        raise ValueError(
            "No NPF package found; run add_npf_package before zoned parameterisation."
        )
    dis = gwf.get_package("dis")
    disv = gwf.get_package("disv")
    if dis is not None:
        nlay = int(dis.nlay.data)
        nrow = int(dis.nrow.data)
        ncol = int(dis.ncol.data)
        per_layer = nrow * ncol
        grid = {
            "type": "DIS",
            "nlay": nlay,
            "nrow": nrow,
            "ncol": ncol,
            "per_layer": per_layer,
            "ncell": nlay * per_layer,
        }
    elif disv is not None:
        nlay = int(disv.nlay.data)
        ncpl = int(disv.ncpl.data)
        per_layer = ncpl
        grid = {
            "type": "DISV",
            "nlay": nlay,
            "ncpl": ncpl,
            "per_layer": per_layer,
            "ncell": nlay * per_layer,
        }
    else:
        raise ValueError("No grid package (DIS/DISV) found on the model.")

    k_base = np.asarray(npf.k.array, dtype=float).reshape(-1)
    if k_base.size != grid["ncell"]:
        raise ValueError(
            f"NPF k has {k_base.size} values; grid has {grid['ncell']} cells."
        )

    specs: list[tuple[str, dict, int]] = []
    for name, spec in parameterisation.items():
        key = str(name)
        if not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise ValueError(
                f"Parameter prefix '{key}' must contain only letters, digits and underscores."
            )
        if not isinstance(spec, dict):
            raise ValueError(f"Parameter '{key}' must be a spec dict.")
        scope = spec.get("scope", "all")
        if scope != "zones":
            raise ValueError(
                "Zoned parameterisation cannot be combined with scope "
                f"'{scope}' (parameter '{key}'); all specs must use scope='zones'."
            )
        target = spec.get("target")
        if target not in _SUPPORTED_TARGETS:
            raise ValueError(
                f"Unsupported parameterisation target '{target}'. Supported: "
                f"{list(_SUPPORTED_TARGETS)}."
            )
        layer = spec.get("layer")
        if layer is None:
            raise ValueError(f"Parameter '{key}' scope=zones requires 'layer'.")
        layer = int(layer)
        if not (0 <= layer < nlay):
            raise ValueError(
                f"Parameter '{key}' layer {layer} out of range (nlay={nlay})."
            )
        specs.append((key, spec, layer))

    if len({s[2] for s in specs}) != len(specs):
        raise ValueError("Each layer may appear in at most one zones spec.")

    zone_map = np.zeros(grid["ncell"], dtype=int)
    parameters: list[dict] = []
    zones_out: list[dict] = []
    next_index = 1
    for key, spec, layer in sorted(specs, key=lambda s: s[2]):
        max_zones = int(spec.get("max_zones", 50))
        if max_zones < 1:
            raise ValueError(f"Parameter '{key}' max_zones must be >= 1.")
        initial = float(spec.get("initial", 1.0))
        if not np.isfinite(initial) or initial <= 0:
            raise ValueError(f"Parameter '{key}' initial multiplier must be positive.")
        lower_factor = float(spec.get("lower_factor", 0.1))
        upper_factor = float(spec.get("upper_factor", 10.0))
        if lower_factor >= 1.0 or upper_factor <= 1.0:
            raise ValueError(
                f"Parameter '{key}': lower_factor must be < 1 and upper_factor > 1."
            )
        partrans = str(spec.get("partrans", "log")).lower()

        offset = layer * grid["per_layer"]
        slice_ids, zone_vals = _derive_zones(
            k_base[offset : offset + grid["per_layer"]], max_zones
        )
        for local_id, (base_k, n_cells) in enumerate(zone_vals, start=1):
            pname = f"{key}_z{next_index}"
            if len(pname) > 12:
                raise ValueError(
                    f"Zone parameter name '{pname}' is {len(pname)} characters; "
                    "PEST caps parameter names at 12. Use a shorter prefix."
                )
            zone_map[offset : offset + grid["per_layer"]][slice_ids == local_id] = next_index
            parameters.append(
                {
                    "name": pname,
                    "target": "npf:k",
                    "scope": "zones",
                    "layer": layer,
                    "initial": initial,
                    "lower_bound": initial * lower_factor,
                    "upper_bound": initial * upper_factor,
                    "partrans": partrans,
                }
            )
            zones_out.append(
                {
                    "name": pname,
                    "index": next_index,
                    "layer": layer,
                    "base_k": base_k,
                    "n_cells": n_cells,
                    "initial": initial,
                    "lower_bound": initial * lower_factor,
                    "upper_bound": initial * upper_factor,
                    "partrans": partrans,
                }
            )
            next_index += 1

    return {
        "grid": grid,
        "k_base": k_base,
        "zone_map": zone_map,
        "zones": zones_out,
        "parameters": parameters,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoned_calibration.py -k normalise_zoned -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "feat(calibration): zoned parameterisation normalisation"
```

---

### Task 4: Multiplier template generation

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`.
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: `_normalise_zoned_parameterisation` zones, `_TPL_TOKEN_WIDTH`,
  `resolve_workspace`.
- Produces:
  `_impl_generate_zone_mult_tpl(model, zones: list[dict], target_file: str) -> dict`
  with keys `tpl_path` and `target`. One wide token per zone, in `zones` order.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_zoned_calibration.py`:

```python
def test_generate_zone_mult_tpl_has_one_wide_token_per_zone(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _impl_generate_zone_mult_tpl,
        _normalise_zoned_parameterisation,
    )

    name = _build_zoned_model(tmp_path)
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    out = _impl_generate_zone_mult_tpl(name, norm["zones"], "zoned_model_k_mult.dat")
    text = open(out["tpl_path"]).read().splitlines()
    assert text[0].strip() == "ptf ~"
    # exactly one token line per zone
    assert len(text) == 1 + len(norm["zones"])
    assert "k_z1" in text[1] and "k_z2" in text[2]
    # tokens are wide (>= 15 chars of content)
    for line in text[1:]:
        assert len(line) - 2 >= 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_zoned_calibration.py -k zone_mult_tpl -v`
Expected: FAIL (cannot import `_impl_generate_zone_mult_tpl`).

- [ ] **Step 3: Implement**

Add after `_impl_generate_tpl` (which ends at line 994):

```python
def _impl_generate_zone_mult_tpl(model: str, zones: list[dict], target_file: str) -> dict:
    """Generate a PEST template with exactly one wide token per zone.

    The target file holds one multiplier per line, in ``zones`` order — the
    order the forward wrapper reads and the order the returned ``zones`` list
    reports.
    """
    ws = resolve_workspace(model)
    tpl_path = ws / f"{target_file}.tpl"
    lines = ["ptf ~"]
    for zone in zones:
        lines.append("~" + f"{zone['name']:^{_TPL_TOKEN_WIDTH}s}" + "~")
    tpl_path.write_text("\n".join(lines) + "\n")
    return {"tpl_path": str(tpl_path), "target": str(ws / target_file)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_zoned_calibration.py -k zone_mult_tpl -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "feat(calibration): multiplier template generation for zoned K"
```

---

### Task 5: Forward wrapper multiplier mode

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
  (`_generate_forward_wrapper`, lines 1041–1099).
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: `_apply_k_multipliers`, `get_gwf`, `_find_mf6_binary`,
  `resolve_workspace`, `flush_model`.
- Produces:
  `_generate_forward_wrapper(model, multiply_k: bool = False) -> dict`
  (backward compatible; existing callers pass one argument). When
  `multiply_k=True` the wrapper imports `_apply_k_multipliers` and applies the
  multipliers to `<gwf>_k.dat` before running MODFLOW 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zoned_calibration.py`:

```python
def _mf6_available():
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")


def test_generate_forward_wrapper_default_unchanged(tmp_path):
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper

    if not _mf6_available():
        pytest.skip("MODFLOW 6 binary not installed")
    name = _build_zoned_model(tmp_path)
    out = _generate_forward_wrapper(name)
    body = open(out["wrapper_path"]).read()
    assert "_apply_k_multipliers" not in body


@requires_mf6
def test_generate_forward_wrapper_multiplier_applies_k(tmp_path):
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper
    from groundwater_mcp.utils.model_store import get_gwf
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_zoned_model(tmp_path)
    gwf_name = get_gwf(name).name
    ws = resolve_workspace(name)
    base = np.full(25, 2.0)
    zone = np.zeros(25, dtype=int)
    zone[:5] = 1
    zone[5:] = 2
    np.savetxt(ws / f"{gwf_name}_k_base.dat", base, fmt="%.10g")
    np.savetxt(ws / f"{gwf_name}_k_zone.dat", zone, fmt="%d")
    np.savetxt(ws / f"{gwf_name}_k_mult.dat", np.array([3.0, 5.0]), fmt="%.10g")

    out = _generate_forward_wrapper(name, multiply_k=True)
    proc = subprocess.run(
        [sys.executable, out["wrapper_path"]], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    k = np.loadtxt(ws / f"{gwf_name}_k.dat")
    assert list(k[:5]) == pytest.approx([6.0] * 5)
    assert list(k[5:]) == pytest.approx([10.0] * 20)
```

Add `import subprocess`, `import sys` to the test file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoned_calibration.py -k forward_wrapper -v`
Expected: FAIL on `test_generate_forward_wrapper_multiplier_applies_k` (unexpected
keyword `multiply_k`); `test_generate_forward_wrapper_default_unchanged` may pass
already.

- [ ] **Step 3: Implement**

Replace the body of `_generate_forward_wrapper` after the MF6 lookup with a
branch. Concretely, change the signature line to:

```python
def _generate_forward_wrapper(model: str, multiply_k: bool = False) -> dict:
```

and replace the `wrapper_path.write_text(...)` block (currently the single
`write_text` of the plain wrapper) with:

```python
    if multiply_k:
        gwf_name = get_gwf(model).name
        base_name = f"{gwf_name}_k_base.dat"
        zone_name = f"{gwf_name}_k_zone.dat"
        mult_name = f"{gwf_name}_k_mult.dat"
        k_name = f"{gwf_name}_k.dat"
        wrapper_path.write_text(
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            "\n"
            "from groundwater_mcp.tools.calibration import _apply_k_multipliers\n"
            f"\nWS = {str(ws)!r}\n"
            f"MF6 = {mf6_exe!r}\n"
            "\n"
            "os.chdir(WS)\n"
            "_apply_k_multipliers(\n"
            f"    os.path.join(WS, {base_name!r}),\n"
            f"    os.path.join(WS, {zone_name!r}),\n"
            f"    os.path.join(WS, {mult_name!r}),\n"
            f"    os.path.join(WS, {k_name!r}),\n"
            ")\n"
            "proc = subprocess.run([MF6], cwd=WS)\n"
            "sys.exit(proc.returncode)\n"
        )
    else:
        wrapper_path.write_text(
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            f"\nWS = {str(ws)!r}\n"
            f"MF6 = {mf6_exe!r}\n"
            "\n"
            "os.chdir(WS)\n"
            "proc = subprocess.run([MF6], cwd=WS)\n"
            "sys.exit(proc.returncode)\n"
        )
```

(The `else` branch is the existing body verbatim, so default behaviour is
unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoned_calibration.py -k forward_wrapper -v`
Expected: PASS. Also re-run the existing wrapper tests:

Run: `python -m pytest tests/test_setup_calibration.py -k forward_wrapper -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "feat(calibration): forward wrapper multiplier mode"
```

---

### Task 6: `setup_calibration` zones branch

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
  (`_impl_setup_calibration` at line 1113 and its MCP wrapper docstring at
  line 1955).
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: `_normalise_zoned_parameterisation`, `_impl_rewire_npf_k_external`,
  `_impl_generate_zone_mult_tpl`, `_generate_forward_wrapper`,
  `_build_model_obs_interface`, `_impl_setup_pest_control`, `_tpl_substitute`.
- Produces:
  `_impl_setup_calibration_zoned(model, parameterisation, obs_source, noptmax) -> dict`
  returning the same keys as `_impl_setup_calibration` plus a `zones` list and
  `grid`. `_impl_setup_calibration` dispatches to it when any spec has
  `scope="zones"`, rejecting mixed scopes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zoned_calibration.py` (add the obs registration helper):

```python
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.spatial import grid_centroids


def _register_obs(tmp_path, name, n_obs=5):
    gwf = get_gwf(name)
    mg = gwf.modelgrid
    xc, yc = grid_centroids(mg)
    interior = [r * mg.ncol + c for r in range(1, mg.nrow - 1) for c in range(1, mg.ncol - 1)]
    cells = interior[:n_obs]
    csv_path = tmp_path / f"{name}_obs.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for i, cell in enumerate(cells):
            writer.writerow(
                [f"S{i + 1:02d}", "2020-01-01", 30.0, float(xc[cell]), float(yc[cell])]
            )
    _impl_import_obs_from_csv(
        model=name,
        csv_file=str(csv_path),
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )


@requires_mf6
def test_setup_calibration_zoned_emits_zone_interface(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    from groundwater_mcp.utils.workspace import resolve_workspace
    name = _build_zoned_model(tmp_path)
    _register_obs(tmp_path, name)
    result = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert "error" not in result, result
    assert result["n_adjustable_parameters"] == 2
    assert [z["name"] for z in result["zones"]] == ["k_z1", "k_z2"]
    assert result["forward_wrapper"] is not None
    ws = resolve_workspace(name)
    for fname in ("zoned_model_k_base.dat", "zoned_model_k_zone.dat"):
        assert (ws / fname).exists(), f"missing {fname}"
    # initial multiplier 1.0 leaves the NPF k file equal to the base field
    k = np.loadtxt(ws / "zoned_model_k.dat")
    assert list(k) == pytest.approx([1.0] * 5 + [5.0] * 20)


def test_setup_calibration_zoned_rejects_mixed_scopes(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _build_zoned_model(tmp_path)
    _register_obs(tmp_path, name)
    with pytest.raises(ValueError, match="scope='zones'"):
        _impl_setup_calibration(
            name,
            {
                "kz": {"target": "npf:k", "scope": "zones", "layer": 0},
                "kall": {"target": "npf:k", "scope": "all", "initial": 5.0},
            },
        )


def test_setup_calibration_non_zoned_unchanged(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _build_zoned_model(tmp_path)
    _register_obs(tmp_path, name)
    result = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    )
    assert "error" not in result, result
    assert "zones" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoned_calibration.py -k "setup_calibration" -v`
Expected: FAIL (zoned path not implemented; the `zones` key is missing).

- [ ] **Step 3: Implement the dispatch and the zoned implementation**

In `_impl_setup_calibration`, at the very top of the function body (before
`ws = resolve_workspace(model)`), insert:

```python
    zone_specs = {
        str(n): s
        for n, s in parameterisation.items()
        if isinstance(s, dict) and s.get("scope") == "zones"
    }
    if zone_specs:
        if len(zone_specs) != len(parameterisation):
            raise ValueError(
                "Zoned parameterisation cannot be combined with scope "
                "'all'/'layer'/'cells'; use scope='zones' for every parameter."
            )
        return _impl_setup_calibration_zoned(model, parameterisation, obs_source, noptmax)
```

Then add `_impl_setup_calibration_zoned` immediately before
`_impl_setup_calibration`:

```python
def _impl_setup_calibration_zoned(
    model: str,
    parameterisation: dict,
    obs_source: str = "model",
    noptmax: int = 10,
) -> dict:
    """Emit a zoned/multiplier PEST interface for NPF k (scope="zones").

    Writes the base K field and an integer zone map, rewires NPF k to an
    external ``OPEN/CLOSE`` file, generates a one-token-per-zone multiplier
    template, and forces a forward wrapper that applies
    ``k = base_k × multiplier[zone]`` before each MODFLOW 6 run. At the default
    multiplier 1.0 the written K field equals the base field.
    """
    ws = resolve_workspace(model)
    norm = _normalise_zoned_parameterisation(model, parameterisation)
    gwf_name = get_gwf(model).name

    base_name = f"{gwf_name}_k_base.dat"
    zone_name = f"{gwf_name}_k_zone.dat"
    mult_name = f"{gwf_name}_k_mult.dat"
    k_name = f"{gwf_name}_k.dat"

    np.savetxt(ws / base_name, norm["k_base"], fmt="%.10g")
    np.savetxt(ws / zone_name, norm["zone_map"], fmt="%d")
    _impl_rewire_npf_k_external(model, filename=k_name)

    tpl = _impl_generate_zone_mult_tpl(model, norm["zones"], mult_name)
    tpl_path = Path(tpl["tpl_path"])

    if obs_source != "model":
        raise ValueError(
            f"setup_calibration supports obs_source='model', got '{obs_source}'."
        )
    obs_meta = read_meta(model).get("observations")
    if not obs_meta or not obs_meta.get("sites"):
        raise ValueError(
            "obs_source='model' requires observation targets registered via "
            "import_obs_from_csv. No 'observations' entry found in "
            ".gwmcp_meta.json for this model."
        )
    ins_paths, obs_data, output_files = _build_model_obs_interface(model, ws)

    wrapper = _generate_forward_wrapper(model, multiply_k=True)
    model_command = wrapper["model_command"]

    par_data = {
        p["name"]: {
            "parval1": p["initial"],
            "parlbnd": p["lower_bound"],
            "parubnd": p["upper_bound"],
            "partrans": p["partrans"],
            "pargp": "gwmcp",
        }
        for p in norm["parameters"]
    }
    pestpp_options: dict = {"noptmax": int(noptmax), "model_command": model_command}
    if output_files:
        pestpp_options["output_files"] = output_files

    setup = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(tpl_path)],
        instruction_files=ins_paths,
        obs_source="explicit",
        pestpp_options=pestpp_options,
        _suppress_command_warning=True,
    )
    if setup.get("error"):
        return setup

    initial_values = {p["name"]: p["initial"] for p in norm["parameters"]}
    _tpl_substitute(tpl_path, Path(tpl["target"]), initial_values)
    mult = np.array([initial_values[p["name"]] for p in norm["parameters"]])
    factor = np.where(norm["zone_map"] > 0, mult[norm["zone_map"] - 1], 1.0)
    np.savetxt(ws / k_name, norm["k_base"] * factor, fmt="%.10g")

    result: dict = {
        "model": model,
        "pst_file": setup["pst_file"],
        "template_file": str(tpl_path),
        "target_file": tpl["target"],
        "instruction_file": ins_paths[0],
        "external_array": str(ws / k_name),
        "forward_wrapper": wrapper["wrapper_path"],
        "n_observations": setup["n_observations"],
        "n_adjustable_parameters": setup["n_adjustable_parameters"],
        "n_total_parameters": setup["n_total_parameters"],
        "parameters": [
            {
                "name": p["name"],
                "scope": p["scope"],
                "initial": p["initial"],
                "lower_bound": p["lower_bound"],
                "upper_bound": p["upper_bound"],
                "partrans": p["partrans"],
            }
            for p in norm["parameters"]
        ],
        "zones": norm["zones"],
        "grid": norm["grid"],
        "model_command": setup["model_command"],
        "next_steps": (
            "Run the calibration with run_pestpp_glm (or run_pestpp_ies for "
            "many parameters), then summarise_calibration."
        ),
    }
    if any(z["initial"] != 1.0 for z in norm["zones"]):
        result["warning"] = (
            "One or more zone multipliers have initial != 1.0, so the initial "
            "state is not the shipped base K field."
        )
    return result
```

Update the `setup_calibration` MCP docstring (line ~1962) to add, after the
existing `scope` sentence:

```
        scope may also be "zones" (with "layer": N): zones are derived from
        equal positive K values in that layer and each zone becomes a
        dimensionless multiplier parameter (initial default 1.0, bounds
        0.1-10). A generated forward wrapper applies k = base_k × multiplier
        before each run, preserving the base K pattern. One zones spec per
        layer; zones specs cannot be mixed with all/layer/cells.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoned_calibration.py -k setup_calibration -v`
Expected: PASS (3 tests). Then the existing setup tests:

Run: `python -m pytest tests/test_setup_calibration.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "feat(calibration): setup_calibration scope=zones (NPF k multipliers)"
```

---

### Task 7: Sensitivity screen applies zone multipliers

**Files:**
- Modify: `src/groundwater_mcp/tools/calibration.py`
  (`_impl_check_parameter_sensitivity`, lines 591–688).
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: `_apply_k_multipliers`, `get_gwf`, `resolve_workspace`.
- Produces: `_maybe_apply_zone_multipliers(model, target: Path) -> None` — a
  no-op unless `target` is the model's multiplier file and the base/zone files
  exist; otherwise writes `<gwf>_k.dat` from the multipliers. Called after each
  `_tpl_substitute` in the sensitivity loop.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_zoned_calibration.py`:

```python
def test_maybe_apply_zone_multipliers_writes_k(tmp_path):
    from groundwater_mcp.tools.calibration import _maybe_apply_zone_multipliers
    from groundwater_mcp.utils.model_store import get_gwf
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_zoned_model(tmp_path)
    gwf_name = get_gwf(name).name
    ws = resolve_workspace(name)
    np.savetxt(ws / f"{gwf_name}_k_base.dat", np.array([2.0, 2.0, 2.0]), fmt="%.10g")
    np.savetxt(ws / f"{gwf_name}_k_zone.dat", np.array([1, 1, 2]), fmt="%d")
    mult = ws / f"{gwf_name}_k_mult.dat"
    np.savetxt(mult, np.array([3.0, 5.0]), fmt="%.10g")

    _maybe_apply_zone_multipliers(name, mult)
    k = np.loadtxt(ws / f"{gwf_name}_k.dat")
    assert list(k) == pytest.approx([6.0, 6.0, 10.0])


def test_maybe_apply_zone_multipliers_noop_for_other_target(tmp_path):
    from groundwater_mcp.tools.calibration import _maybe_apply_zone_multipliers
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_zoned_model(tmp_path)
    ws = resolve_workspace(name)
    other = ws / "something_else.dat"
    other.write_text("1\n")
    _maybe_apply_zone_multipliers(name, other)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoned_calibration.py -k maybe_apply -v`
Expected: FAIL (cannot import `_maybe_apply_zone_multipliers`).

- [ ] **Step 3: Implement**

Add after `_apply_k_multipliers`:

```python
def _maybe_apply_zone_multipliers(model: str, target: Path) -> None:
    """Apply zone multipliers to the NPF k file when *target* is the
    multiplier file of a zoned setup; otherwise do nothing."""
    gwf = get_gwf(model)
    ws = resolve_workspace(model)
    base = ws / f"{gwf.name}_k_base.dat"
    zone = ws / f"{gwf.name}_k_zone.dat"
    if target.name == f"{gwf.name}_k_mult.dat" and base.exists() and zone.exists():
        _apply_k_multipliers(base, zone, target, ws / f"{gwf.name}_k.dat")
```

Then in `_impl_check_parameter_sensitivity`, inside the loop, after
`_tpl_substitute(tpl, target, {name: base_value * (1.0 + delta)})` and before
`run = _impl_run_simulation(model, silent=True)`, add:

```python
            _maybe_apply_zone_multipliers(model, target)
```

and inside the `finally:` block, after restoring `target`, re-apply the base
multipliers so the workspace returns to its unperturbed state:

```python
            _maybe_apply_zone_multipliers(model, target)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoned_calibration.py -k maybe_apply -v`
Expected: PASS. Then the sensitivity tests:

Run: `python -m pytest tests/test_hydro_expertise.py -k sensitivity -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
mypy src/groundwater_mcp/tools/calibration.py
git add src/groundwater_mcp/tools/calibration.py tests/test_zoned_calibration.py
git commit -m "fix(calibration): propagate zone multipliers in the sensitivity screen"
```

---

### Task 8: End-to-end zoned calibration test

**Files:**
- Test: `tests/test_zoned_calibration.py`.

**Interfaces:**
- Consumes: `_impl_setup_calibration`, `_impl_run_pestpp_glm`,
  `_impl_run_pestpp_ies`, `_impl_summarise_calibration`.

- [ ] **Step 1: Write the end-to-end test**

Append to `tests/test_zoned_calibration.py`:

```python
def _pestpp_available(exe="pestpp-glm"):
    try:
        from groundwater_mcp.tools.calibration import _find_pestpp_binary

        _find_pestpp_binary(exe)
        return True
    except RuntimeError:
        return False


requires_pestpp = pytest.mark.skipif(
    not _pestpp_available(), reason="PEST++ binaries not installed"
)


@requires_mf6
@requires_pestpp
def test_zoned_calibration_e2e_ies_reduces_phi(tmp_path):
    """setup_calibration(scope='zones') → IES converges and reduces phi."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_ies,
        _impl_setup_calibration,
    )

    name = _build_zoned_model(tmp_path)
    _register_obs(tmp_path, name, n_obs=9)
    setup = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "zones", "layer": 0}},
        noptmax=3,
    )
    assert "error" not in setup, setup
    assert setup["n_adjustable_parameters"] == 2

    run = _impl_run_pestpp_ies(name, setup["pst_file"], num_reals=6, num_workers=1)
    assert "error" not in run, run
    assert run["converged"] is True, run
    assert run["final_phi_mean"] is not None
```

> If pestpp-ies cannot run on this host, the test fails rather than silently
> passing; record the actual run keys in the session log. Do not weaken the
> assertion beyond checking `converged` and a finite `final_phi_mean`.

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_zoned_calibration.py -k e2e -v`
Expected: PASS (skipped if MF6/PEST++ absent). If it fails, inspect
`<case>.phi.actual.csv` and the wrapper output; do not weaken the test beyond
the note above.

- [ ] **Step 3: Run the whole zoned test file and the suite**

Run: `python -m pytest tests/test_zoned_calibration.py -v`
Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 4: Lint, type-check, commit**

```bash
ruff check tests/test_zoned_calibration.py
git add tests/test_zoned_calibration.py
git commit -m "test(calibration): end-to-end zoned K multiplier calibration"
```

---

### Task 9: Documentation

**Files:**
- Modify: `tools.md`, `README.md`, `architecture.md`,
  `research/capability-matrix.md`, `tasks.md`.

- [ ] **Step 1: Update `tools.md`**

In the `setup_calibration` section, extend the `scope` bullet and add a
paragraph:

```markdown
- `scope`: `"all"` (whole array), `"layer"` (with `"layer": N`), `"cells"`
  (with `"cells": [[layer, row, col], ...]` on DIS — `[[layer, node], ...]`
  on DISV), or `"zones"` (with `"layer": N`). Scopes must partition the array
  exactly for all/layer/cells; `zones` is the multiplier mode below.
```

Add after the parameterisation explanation:

```markdown
**Zoned multipliers (scope="zones"):** zones are auto-derived from groups of
equal positive `npf:k` values within the spec's layer (values equal to 6
significant figures group together; inactive/zero cells stay fixed). Each zone
becomes a dimensionless multiplier parameter `<prefix>_z<index>` (names ordered
by layer then base K ascending, ≤12 chars). `initial` defaults to `1.0` (base
field), bounds default 0.1–10. One spec per layer; `zones` specs cannot be
mixed with `all`/`layer`/`cells`. `max_zones` (default 50) fails loudly when a
layer has more distinct values than the cap. The call writes
`<gwf>_k_base.dat`, `<gwf>_k_zone.dat`, `<gwf>_k_mult.dat.tpl` and forces a
forward wrapper that computes `k = base_k × multiplier[zone]` before each
MODFLOW 6 run — so the base spatial pattern is preserved and only the zone
magnitudes are calibrated. `check_parameter_sensitivity` re-applies the
multipliers before its direct runs. The result adds a `zones` block (name,
layer, base_k, n_cells, bounds) and `grid`.
```

- [ ] **Step 2: Update `README.md`**

In the calibration row's supporting text (or after the tool table), add a
sentence noting `setup_calibration` now supports zoned NPF K multipliers; note
the tool count is unchanged at 66.

- [ ] **Step 3: Update `architecture.md`**

Add a short paragraph under the calibration module / deviation notes recording
the zoned/multiplier capability and that it closes the neversink
`setup_calibration` uniform-only gap.

- [ ] **Step 4: Update `research/capability-matrix.md`**

Add a dated changelog paragraph near the other 7f/7e entries:

```markdown
**Zoned K multipliers (2026-09-11):** `setup_calibration` gained
`scope="zones"` — zones auto-derived from equal positive per-layer `npf:k`
values become dimensionless multiplier parameters applied by a generated
forward wrapper (`k = base_k × multiplier[zone]`). Calibration of zoned-field
regional models no longer requires uniform per-layer K replacement. No
capability-coverage rows changed.
```

- [ ] **Step 5: Update `tasks.md`**

- Tick the neversink rerun-1 backlog item
  "`setup_calibration` parameterises `npf:k` only as whole-scope uniform
  per-layer replacement" as addressed by the zones capability.
- Add a note under the neversink row that rerun-2/rerun-3 are dispatched on the
  new capability (target remains NOT PASSED until they are green).

- [ ] **Step 6: Commit**

```bash
git add tools.md README.md architecture.md research/capability-matrix.md tasks.md
git commit -m "docs: zoned NPF K multiplier calibration capability"
```

---

### Task 10: Dispatch the neversink closed-book reruns

**Files:**
- Create: `research/discovery/sessions/2026-09-11-6d-neversink-rerun2.md` (+
  `-runlog.md`) and `...-rerun3.md` (+ `-runlog.md`) after the runs.
- Modify: `research/holdout-registry.md`, `tasks.md`.

**Interfaces:**
- Consumes: the merged zoned capability; the holdout model at
  `D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\`.
- Produces: two closed-book session logs and an updated registry row.

- [ ] **Step 1: Confirm the local server reports the new capability**

Run `check_environment` and a scratch `setup_calibration` on a small zoned model
to confirm the live server (which runs from `main`) has the merged code.
Expected: `scope="zones"` accepted.

- [ ] **Step 2: Dispatch rerun-2**

Start an Agent Manager worktree session (`6d-neversink-rerun2`) with the
6d playbook Target-6 prompt, amended with:

```
This rerun uses the new setup_calibration scope="zones": derive per-layer zone
multipliers for the shipped zoned K (do not replace layers uniformly), register
the reference-derived head obs, run setup_calibration(scope="zones"), then
run_pestpp_ies/glm + summarise_calibration. MCP-only; 0 reprompts expected.
```

Accept the run when the full build/run/postprocess/calibration journey completes
with 0 reprompts and 0 MCP-only violations and phi improves.

- [ ] **Step 3: Record rerun-2**

Write `research/discovery/sessions/2026-09-11-6d-neversink-rerun2.md` following
the existing session-log format (outcome vs criteria, deviations, MCP findings,
time, gate position). Tick/raise backlog items.

- [ ] **Step 4: Dispatch rerun-3 (set-and-forget confirmation)**

Repeat Step 2 with worktree `6d-neversink-rerun3`. The target is PASSED when
rerun-2 and rerun-3 are both green.

- [ ] **Step 5: Record rerun-3 and update the registry + tasks**

Write the rerun-3 log; update the neversink row in
`research/holdout-registry.md` and the 6d target status in `tasks.md`
(`NOT PASSED` → `PASSED` only on two consecutive greens).

- [ ] **Step 6: Commit the session records**

```bash
git add research/discovery/sessions/2026-09-11-6d-neversink-rerun2*.md \
        research/discovery/sessions/2026-09-11-6d-neversink-rerun3*.md \
        research/holdout-registry.md tasks.md
git commit -m "chore(6d): neversink zoned-K reruns + target status"
```

---

## Self-review

- **Spec coverage:** §1 API → Task 6; §2 zone derivation → Tasks 1, 3 (DIS and
  DISV); §3 files/wrapper → Tasks 2, 4, 5, 6 and the sensitivity note → Task 7;
  §4 errors → Tasks 1, 3, 6; §5 tests → Tasks 1–8; §6 docs/validation → Tasks 9–10.
- **Type consistency:** `_derive_zones` returns `(zone_ids, zones)` used by
  `_normalise_zoned_parameterisation`; `_apply_k_multipliers(base, zone, mult,
  out)` is used by the wrapper (Task 5) and `_maybe_apply_zone_multipliers`
  (Task 7); `zones` dict keys (`name`, `index`, `layer`, `base_k`, `n_cells`,
  `initial`, `lower_bound`, `upper_bound`, `partrans`) are consistent across
  Tasks 3, 4, 6 and the result block.
- **Ordering:** helper tasks (1–5) precede the integration (6) and sensitivity
  fix (7); the e2e test (8) follows; docs (9) and reruns (10) close out.
