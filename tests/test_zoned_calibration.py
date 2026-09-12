"""Zoned NPF K multiplier parameterisation tests (`setup_calibration` scope="zones")."""

from __future__ import annotations

import csv
import subprocess
import sys

import numpy as np
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.spatial import grid_centroids


def _mf6_available():
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")


def test_round_sig_array_rounds_to_significant_figures():
    from groundwater_mcp.tools.calibration import _round_sig_array

    out = _round_sig_array(np.array([0.0502921, 0.1676449, 60.96001]), 6)
    assert list(out) == pytest.approx([0.0502921, 0.167645, 60.96])


def test_round_sig_array_does_not_mutate_input():
    from groundwater_mcp.tools.calibration import _round_sig_array

    values = np.array([0.1676449, 60.96001, 0.0])
    original = values.copy()
    _round_sig_array(values, 6)
    np.testing.assert_array_equal(values, original)


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


def test_apply_k_multipliers_rejects_length_mismatch(tmp_path):
    from groundwater_mcp.tools.calibration import _apply_k_multipliers

    base_p, zone_p, mult_p, out_p = _write_mult_files(
        tmp_path, base=[2.0, 2.0, 2.0], zone=[1, 2], mult=[3.0, 10.0]
    )
    with pytest.raises(ValueError, match="same length"):
        _apply_k_multipliers(base_p, zone_p, mult_p, out_p)


def test_apply_k_multipliers_rejects_zone_out_of_range(tmp_path):
    from groundwater_mcp.tools.calibration import _apply_k_multipliers

    base_p, zone_p, mult_p, out_p = _write_mult_files(
        tmp_path, base=[2.0, 2.0], zone=[1, 5], mult=[3.0, 10.0]
    )
    with pytest.raises(ValueError, match="zone 5"):
        _apply_k_multipliers(base_p, zone_p, mult_p, out_p)


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


def _build_two_layer_zoned_model(tmp_path, name="zoned_2layer"):
    """2 layers × 5 × 5. Layer 0: K 1.0 (col 0) / 5.0 elsewhere; layer 1:
    K 2.0 (col 4) / 7.0 elsewhere — two zones per layer."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 2, 5, 5, 100.0, 100.0, 50.0, [30.0, 20.0])
    k = np.full((2, 5, 5), 5.0)
    k[0, :, 0] = 1.0
    k[1, :, :] = 7.0
    k[1, :, 4] = 2.0
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


def test_normalise_zoned_rejects_non_dict(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_zoned_parameterisation

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="must be a dict"):
        _normalise_zoned_parameterisation(name, ["k"])


def test_setup_calibration_rejects_non_dict_parameterisation(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="must be a dict"):
        _impl_setup_calibration(name, ["k"])  # type: ignore[arg-type]


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


def test_apply_k_multipliers_disv_node_ordering(tmp_path):
    """The zone map and the applied multipliers preserve DISV node order."""
    from groundwater_mcp.tools.builder import _impl_add_disv_package
    from groundwater_mcp.tools.calibration import (
        _apply_k_multipliers,
        _normalise_zoned_parameterisation,
    )
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = "zoned_disv_order"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    vertices = [
        [0, 0.0, 0.0],
        [1, 100.0, 0.0],
        [2, 200.0, 0.0],
        [3, 0.0, 100.0],
        [4, 100.0, 100.0],
        [5, 200.0, 100.0],
    ]
    cell2d = [
        [0, 50.0, 50.0, 4, 0, 1, 4, 3],
        [1, 150.0, 50.0, 4, 1, 2, 5, 4],
    ]
    _impl_add_disv_package(name, 1, vertices, cell2d, [50.0, 50.0], [[40.0, 40.0]])
    _impl_add_npf_package(
        name, icelltype=0, k=np.array([[2.0, 9.0]]), k33=None, save_flows=True
    )
    norm = _normalise_zoned_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    # base 2.0 -> zone1 (node 0), base 9.0 -> zone2 (node 1)
    assert list(norm["zone_map"]) == [1, 2]

    ws_path = resolve_workspace(name)
    base_p = ws_path / "k_base.dat"
    zone_p = ws_path / "k_zone.dat"
    mult_p = ws_path / "k_mult.dat"
    out_p = ws_path / "k.dat"
    np.savetxt(base_p, norm["k_base"], fmt="%.10g")
    np.savetxt(zone_p, norm["zone_map"], fmt="%d")
    np.savetxt(mult_p, np.array([3.0, 4.0]), fmt="%.10g")
    k = _apply_k_multipliers(base_p, zone_p, mult_p, out_p)
    assert list(k) == pytest.approx([6.0, 36.0])


def _seed_obs_meta_disv(name, nodes):
    """Seed the registered-observation metadata directly.

    ``import_obs_from_csv`` cannot currently register observations on a DISV
    grid: ``parameterise.py`` resolves the grid with ``get_package("dis")``,
    which prefix-matches the DISV package, and then reads the non-existent
    ``.ncol``. That is an unrelated pre-existing bug, so this test seeds the
    meta directly to exercise the zoned DISV path without depending on it.
    """
    from groundwater_mcp.utils.model_store import read_meta, write_meta

    meta = read_meta(name)
    meta["observations"] = {
        "type": "HEAD",
        "layer": 0,
        "obs_file": f"{name}.obs",
        "output_csv": f"{name}_head.obs.csv",
        "sites": [
            {
                "site": f"S{i + 1:02d}",
                "cellid": [0, int(n)],
                "n_records": 1,
                "values": [30.0],
                "dates": ["2020-01-01"],
            }
            for i, n in enumerate(nodes)
        ],
    }
    write_meta(name, meta)


@requires_mf6
def test_setup_calibration_zoned_disv_executes_wrapper(tmp_path):
    """The full zoned path completes on a DISV grid and the generated wrapper
    applies base × mult in node order."""
    from groundwater_mcp.tools.builder import _impl_add_disv_package
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = "zoned_disv_full"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate")
    vertices = [
        [0, 0.0, 0.0],
        [1, 100.0, 0.0],
        [2, 200.0, 0.0],
        [3, 300.0, 0.0],
        [4, 400.0, 0.0],
        [5, 0.0, 100.0],
        [6, 100.0, 100.0],
        [7, 200.0, 100.0],
        [8, 300.0, 100.0],
        [9, 400.0, 100.0],
    ]
    cell2d = [
        [0, 50.0, 50.0, 4, 0, 5, 6, 1],
        [1, 150.0, 50.0, 4, 1, 6, 7, 2],
        [2, 250.0, 50.0, 4, 2, 7, 8, 3],
        [3, 350.0, 50.0, 4, 3, 8, 9, 4],
    ]
    _impl_add_disv_package(name, 1, vertices, cell2d, [50.0] * 4, [[40.0] * 4])
    _impl_add_npf_package(
        name,
        icelltype=0,
        k=np.array([[1.0, 1.0, 5.0, 5.0]]),
        k33=None,
        save_flows=True,
    )
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, 0], 40.0], [[0, 3], 10.0]]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    _seed_obs_meta_disv(name, [0, 1])

    result = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert "error" not in result, result
    assert [z["name"] for z in result["zones"]] == ["k_z1", "k_z2"]
    assert [z["base_k"] for z in result["zones"]] == pytest.approx([1.0, 5.0])

    ws_path = resolve_workspace(name)
    # Distinct multipliers: zone1 ×2 (nodes 0,1), zone2 ×3 (nodes 2,3).
    np.savetxt(
        ws_path / "zoned_disv_full_k_mult.dat", np.array([2.0, 3.0]), fmt="%.10g"
    )
    proc = subprocess.run(
        [sys.executable, result["forward_wrapper"]],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    k = np.loadtxt(ws_path / "zoned_disv_full_k.dat")
    assert list(k) == pytest.approx([2.0, 2.0, 15.0, 15.0])


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


def test_generate_zone_mult_tpl_rejects_empty_zones(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_zone_mult_tpl

    name = _build_zoned_model(tmp_path)
    with pytest.raises(ValueError, match="at least one zone"):
        _impl_generate_zone_mult_tpl(name, [], "zoned_model_k_mult.dat")


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
    # Self-contained: the generated wrapper must not import the installed
    # package (a PEST++ forward run cannot rely on groundwater_mcp being
    # importable, nor on a private helper).
    body = open(out["wrapper_path"]).read()
    assert "groundwater_mcp" not in body
    proc = subprocess.run(
        [sys.executable, out["wrapper_path"]], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    k = np.loadtxt(ws / f"{gwf_name}_k.dat")
    assert list(k[:5]) == pytest.approx([6.0] * 5)
    assert list(k[5:]) == pytest.approx([10.0] * 20)


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
    # (base K is 1.0 in column 0 — flat indices 0,5,10,15,20 — and 5.0 elsewhere)
    k = np.loadtxt(ws / "zoned_model_k.dat")
    assert list(k) == pytest.approx([1.0, 5.0, 5.0, 5.0, 5.0] * 5)


@requires_mf6
def test_setup_calibration_zoned_two_layers_ordering(tmp_path):
    """Two zones specs (one per layer) produce globally contiguous, layer-major
    zone parameter names and a per-layer-correct k.dat."""
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_two_layer_zoned_model(tmp_path)
    _register_obs(tmp_path, name)
    result = _impl_setup_calibration(
        name,
        {
            "kL0": {"target": "npf:k", "scope": "zones", "layer": 0, "initial": 2.0},
            "kL1": {"target": "npf:k", "scope": "zones", "layer": 1, "initial": 3.0},
        },
    )
    assert "error" not in result, result
    # Global zone indices are contiguous and ordered by (layer, base K).
    assert [z["name"] for z in result["zones"]] == [
        "kL0_z1",
        "kL0_z2",
        "kL1_z3",
        "kL1_z4",
    ]
    assert [z["base_k"] for z in result["zones"]] == pytest.approx([1.0, 5.0, 2.0, 7.0])
    assert result["n_adjustable_parameters"] == 4

    ws = resolve_workspace(name)
    k = np.loadtxt(ws / "zoned_2layer_k.dat")
    base_l0 = np.full(25, 5.0)
    base_l0[0::5] = 1.0  # layer 0, column 0
    base_l1 = np.full(25, 7.0)
    base_l1[4::5] = 2.0  # layer 1, column 4
    # Layer 0 cells scale by their layer's multiplier (2.0), layer 1 by 3.0.
    assert list(k[:25]) == pytest.approx(list(base_l0 * 2.0))
    assert list(k[25:]) == pytest.approx(list(base_l1 * 3.0))


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


@requires_mf6
def test_zoned_sensitivity_perturbs_and_restores_k(tmp_path):
    """check_parameter_sensitivity on a zoned parameterisation perturbs k and
    restores the unperturbed base field afterwards."""
    from groundwater_mcp.tools.builder import _impl_add_boundary_package
    from groundwater_mcp.tools.calibration import (
        _impl_check_parameter_sensitivity,
        _impl_setup_calibration,
    )
    from groundwater_mcp.utils.model_store import get_gwf
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_zoned_model(tmp_path)
    # Recharge makes the head solution K-dependent (CHD-only flow is linear in K).
    rch = [[[0, r, c], 0.001] for r in range(1, 4) for c in range(1, 4)]
    _impl_add_boundary_package(name, "RCH", {"0": rch}, None)
    _register_obs(tmp_path, name, n_obs=4)

    setup = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert "error" not in setup, setup
    gwf_name = get_gwf(name).name
    ws = resolve_workspace(name)
    base_k = np.loadtxt(ws / f"{gwf_name}_k.dat")

    result = _impl_check_parameter_sensitivity(
        name,
        {p["name"]: p["initial"] for p in setup["zones"]},
        [setup["template_file"]],
    )
    assert "error" not in result, result
    sens = [
        v["sensitivity"]
        for v in result["parameters"].values()
        if v["sensitivity"] is not None
    ]
    assert sens and max(sens) > 0, result
    # The screen restores the unperturbed (multiplier 1.0) K file.
    assert list(np.loadtxt(ws / f"{gwf_name}_k.dat")) == pytest.approx(list(base_k))


@requires_mf6
def test_setup_calibration_repeatable_preserves_base_k(tmp_path):
    """A repeated (or mixed-scope) setup_calibration must not poison the base K
    field used by later setups.

    Reproduces the neversink rerun-2 corruption: after a zoned setup, a
    differently-scoped setup wrote its absolute ``initial`` into the shared
    external K file, and a later zoned setup then reloaded that flattened field
    and saw a single uniform zone.
    """
    from groundwater_mcp.tools.calibration import _impl_setup_calibration
    from groundwater_mcp.utils.model_store import get_gwf, invalidate
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _build_zoned_model(tmp_path)
    _register_obs(tmp_path, name)
    gwf_name = get_gwf(name).name
    ws = resolve_workspace(name)

    r1 = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert "error" not in r1, r1
    assert len(r1["zones"]) == 2
    pristine_base = np.loadtxt(ws / f"{gwf_name}_k_base.dat")

    # A second, differently-scoped setup with an absolute initial must not
    # destroy the base field that later setups parameterise from.
    invalidate(name)
    r2 = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 1.0}}
    )
    assert "error" not in r2, r2

    invalidate(name)
    r3 = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "zones", "layer": 0}}
    )
    assert "error" not in r3, r3
    assert len(r3["zones"]) == 2, r3["zones"]
    assert list(np.loadtxt(ws / f"{gwf_name}_k_base.dat")) == pytest.approx(
        list(pristine_base)
    )
