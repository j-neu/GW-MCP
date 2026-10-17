"""Calibration defaults that would contradict groundwater-modelling practice.

- bounded properties (specific yield, porosity) never get a bound >= 1;
- a dry observation cell (MF6's -1e30 sentinel) is reported, not fitted;
- a solver closure too loose for finite-difference derivatives is flagged;
- an observation site on an inactive cell is refused at import.
"""

from __future__ import annotations

import csv

import pyemu
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
from groundwater_mcp.tools.calibration import _impl_setup_calibration
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.runner import _impl_run_simulation
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.spatial import grid_centroids
from tests.test_csub_calibration import _csub_model, _install_csub, _register_head_obs
from tests.test_setup_calibration import _build_base_model, _register_obs, requires_mf6
from tests.test_sto_calibration import _sto_model


def _bounds(pst_file):
    return pyemu.Pst(pst_file).parameter_data[["parval1", "parlbnd", "parubnd"]]


# ---------------------------------------------------------------------------
# Physical bounds
# ---------------------------------------------------------------------------


def test_specific_yield_upper_bound_stays_physical(tmp_path):
    name = _sto_model(tmp_path)
    res = _impl_setup_calibration(
        name, {"sy": {"target": "sto:sy", "scope": "layer", "layer": 0, "initial": 0.2}}
    )
    ub = float(_bounds(res["pst_file"])["parubnd"].iloc[0])
    assert 0.2 < ub <= 0.5


def test_porosity_bounds_stay_below_one(tmp_path):
    name = _csub_model(tmp_path)
    _install_csub(tmp_path, name)
    _register_head_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {"t": {"target": "csub:cg_theta", "scope": "layer", "layer": 0, "initial": 0.35}},
    )
    assert float(_bounds(res["pst_file"])["parubnd"].max()) < 1.0
    res = _impl_setup_calibration(
        name, {"s": {"target": "csub:packagedata", "columns": ["theta"], "layers": [0]}}
    )
    assert float(_bounds(res["pst_file"])["parubnd"].max()) < 1.0


def test_unbounded_properties_keep_their_factor_bounds(tmp_path):
    name = _sto_model(tmp_path)
    res = _impl_setup_calibration(
        name, {"ss": {"target": "sto:ss", "scope": "layer", "layer": 0, "initial": 1e-5}}
    )
    assert float(_bounds(res["pst_file"])["parubnd"].iloc[0]) == pytest.approx(1e-4)


# ---------------------------------------------------------------------------
# Dry observation cells
# ---------------------------------------------------------------------------


def _drying_model(tmp_path, name="dry"):
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate")
    _impl_add_dis_package(name, 1, 1, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(name, icelltype=1, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=5.0)
    _impl_add_boundary_package(name, "CHD", {"0": [[[0, 0, 0], 8.0]]}, None)
    _impl_add_boundary_package(name, "WEL", {"0": [[[0, 0, 4], -30.0]]}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _register(tmp_path, name, sites):
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    path = tmp_path / f"{name}_obs.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "date", "value", "x", "y"])
        for site, col, value in sites:
            w.writerow([site, "2020-01-01", value, xc[col], yc[col]])
    return _impl_import_obs_from_csv(name, str(path), "HEAD", "site", "date", "value", "x", "y", 0)


@requires_mf6
def test_dry_observation_cells_are_reported_not_fitted(tmp_path):
    from groundwater_mcp.tools.postprocess import _compute_obs_fit, _impl_compare_to_observed

    name = _drying_model(tmp_path)
    _register(tmp_path, name, [("WET", 0, 8.0), ("DRYWELL", 4, 0.5)])
    assert _impl_run_simulation(name, silent=True)["success"]

    out = _impl_compare_to_observed(name)
    assert out["n"] == 1
    assert out["rmse"] < 1.0
    assert out["dry_sites"] == ["DRYWELL"]
    fit = _compute_obs_fit(name)
    assert fit["n"] == 1 and fit["dry_sites"] == ["DRYWELL"]


# ---------------------------------------------------------------------------
# Solver closure vs derivative increments
# ---------------------------------------------------------------------------


def test_loose_solver_closure_is_flagged_at_calibration_setup(tmp_path):
    name = _build_base_model(tmp_path, "loose", recharge=1e-3)  # MODERATE: 0.01 m
    _register_obs(tmp_path, name, n_obs=3)
    res = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    )
    assert "outer_dvclose" in res.get("solver_warning", ""), res


def test_tight_solver_closure_is_not_flagged(tmp_path):
    name = _build_base_model(tmp_path, "tight", recharge=1e-3)
    _impl_set_simulation(
        name, 1, [1.0], [1], "moderate", outer_dvclose=1e-5, inner_dvclose=1e-6
    )
    _register_obs(tmp_path, name, n_obs=3)
    res = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    )
    assert "solver_warning" not in res


# ---------------------------------------------------------------------------
# K and recharge from heads alone
# ---------------------------------------------------------------------------


def test_k_with_recharge_from_steady_heads_is_flagged_non_unique(tmp_path):
    name = _build_base_model(tmp_path, "kr", recharge=1e-3)
    _register_obs(tmp_path, name, n_obs=3)
    res = _impl_setup_calibration(
        name,
        {
            "k": {"target": "npf:k", "scope": "all", "initial": 5.0},
            "rech": {"target": "rch:recharge", "scope": "all", "initial": 1e-3},
        },
    )
    assert "ratio" in res.get("identifiability_warning", ""), res


def test_k_alone_is_not_flagged_non_unique(tmp_path):
    name = _build_base_model(tmp_path, "konly", recharge=1e-3)
    _register_obs(tmp_path, name, n_obs=3)
    res = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    )
    assert "identifiability_warning" not in res


# ---------------------------------------------------------------------------
# Observation sites on inactive cells
# ---------------------------------------------------------------------------


def test_site_on_an_inactive_cell_is_refused(tmp_path):
    name = _drying_model(tmp_path, "inact")
    get_gwf(name).get_package("dis").idomain.set_data([[[1, 0, 1, 1, 1]]])
    with pytest.raises(ValueError, match="inactive"):
        _register(tmp_path, name, [("A", 1, 5.0), ("B", 3, 5.0)])
