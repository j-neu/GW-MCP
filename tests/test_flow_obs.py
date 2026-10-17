"""R3.10: flow observations (baseflow, river/drain exchange, boundary flows).

``import_flow_observations`` registers a measured flow on a RIV/DRN/GHB/CHD/WEL
package, either the whole package or a set of its cells. The cells get a
MODFLOW 6 boundname per observed site and the package OBS file sums the flow
over that boundname, so PEST++ reads the simulated flow straight from MF6's
CSV. MF6 counts flow into the aquifer as positive; ``direction`` says how the
measured value is signed.
"""

from __future__ import annotations

import csv

import flopy
import numpy as np
import pandas as pd
import pyemu
import pytest

from groundwater_mcp.tools.builder import _impl_add_boundary_package
from groundwater_mcp.tools.calibration import (
    _build_model_obs_interface,
    _impl_check_parameter_sensitivity,
    _impl_setup_calibration,
    _model_output_times,
)
from groundwater_mcp.tools.parameterise import (
    _impl_import_flow_observations,
    _impl_import_obs_from_csv,
)
from groundwater_mcp.tools.postprocess import _impl_compare_to_observed
from groundwater_mcp.tools.runner import _impl_run_simulation
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.spatial import grid_centroids
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_setup_calibration import _build_base_model, requires_mf6, requires_pestpp
from tests.test_transient_obs import _iso, _transient_model

NROW = NCOL = 5
RIV_CELLS = [[0, r, 2] for r in range(NROW)]
EAST_CHD = [[0, r, NCOL - 1] for r in range(NROW)]


def _river_model(tmp_path, name="fq_model", k=5.0, recharge=1e-3):
    name = _build_base_model(tmp_path, name=name, k=k, recharge=recharge)
    riv = [[cell, 20.0, 50.0, 15.0] for cell in RIV_CELLS]
    _impl_add_boundary_package(name, "RIV", {"0": riv}, None)
    return name


def _flow_csv(tmp_path, name, rows, fname="flows.csv"):
    """rows: (site, date, value[, sd])."""
    path = tmp_path / f"{name}_{fname}"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "date", "value", "sd"])
        for row in rows:
            site, date, value = row[:3]
            w.writerow([site, date, value, row[3] if len(row) > 3 else ""])
    return path


def _import_flows(name, path, package="RIV", **kw):
    kw.setdefault("std", 10.0)
    return _impl_import_flow_observations(
        model=name, csv_file=str(path), package=package, **kw
    )


def _head_obs(tmp_path, name, sites, value=30.0, std=0.01):
    """sites: {site: (row, col)}."""
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    path = tmp_path / f"{name}_heads.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "date", "value", "x", "y"])
        for site, (r, c) in sites.items():
            v = value[site] if isinstance(value, dict) else value
            w.writerow([site, "2020-01-01", v, float(xc[r * NCOL + c]), float(yc[r * NCOL + c])])
    _impl_import_obs_from_csv(
        model=name, csv_file=str(path), obs_type="HEAD", site_col="site",
        date_col="date", value_col="value", x_col="x", y_col="y", layer=0, std=std,
    )


def _sim_flows(name, package="riv"):
    ws = resolve_workspace(name)
    return pd.read_csv(ws / f"{get_gwf(name).name}_{package}_flow.obs.csv")


def _cbc_flow(name, text, cells):
    """Sum of a package's cell-by-cell flow over *cells* from the budget file."""
    ws = resolve_workspace(name)
    cbc = flopy.utils.CellBudgetFile(str(ws / f"{get_gwf(name).name}.cbb"))
    rec = cbc.get_data(text=text)[-1]
    nodes = {r * NCOL + c + 1 for _, r, c in cells}
    return float(sum(q for node, q in zip(rec["node"], rec["q"]) if int(node) in nodes))


# ---------------------------------------------------------------------------
# Registration and the MF6 package OBS output
# ---------------------------------------------------------------------------


@requires_mf6
def test_whole_package_flow_matches_the_budget(tmp_path):
    name = _river_model(tmp_path)
    res = _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    assert res["site_count"] == 1
    assert res["targets"]["river"]["n_cells"] == len(RIV_CELLS)
    _impl_run_simulation(name, silent=True)
    sim = _sim_flows(name)
    assert float(sim["RIVER"].iloc[-1]) == pytest.approx(
        _cbc_flow(name, "RIV", RIV_CELLS), rel=1e-6
    )
    assert float(sim["RIVER"].iloc[-1]) < 0  # gaining river: out of the aquifer


@requires_mf6
def test_cell_targets_sum_their_own_cells(tmp_path):
    name = _river_model(tmp_path)
    north, south = RIV_CELLS[:2], RIV_CELLS[2:]
    rows = [("north", "2020-01-01", 300.0), ("south", "2020-01-01", 500.0)]
    _import_flows(
        name, _flow_csv(tmp_path, name, rows), targets={"north": north, "south": south}
    )
    _impl_run_simulation(name, silent=True)
    sim = _sim_flows(name)
    assert float(sim["NORTH"].iloc[-1]) == pytest.approx(_cbc_flow(name, "RIV", north), rel=1e-6)
    assert float(sim["SOUTH"].iloc[-1]) == pytest.approx(_cbc_flow(name, "RIV", south), rel=1e-6)


def test_several_sites_need_targets(tmp_path):
    name = _river_model(tmp_path)
    rows = [("a", "2020-01-01", 1.0), ("b", "2020-01-01", 2.0)]
    with pytest.raises(ValueError, match="targets"):
        _import_flows(name, _flow_csv(tmp_path, name, rows))


def test_overlapping_targets_are_refused(tmp_path):
    name = _river_model(tmp_path)
    rows = [("a", "2020-01-01", 1.0), ("b", "2020-01-01", 2.0)]
    with pytest.raises(ValueError, match="more than one"):
        _import_flows(
            name, _flow_csv(tmp_path, name, rows),
            targets={"a": RIV_CELLS[:3], "b": RIV_CELLS[2:]},
        )


def test_target_cell_without_a_boundary_is_refused(tmp_path):
    name = _river_model(tmp_path)
    with pytest.raises(ValueError, match="no RIV"):
        _import_flows(
            name, _flow_csv(tmp_path, name, [("a", "2020-01-01", 1.0)]),
            targets={"a": [[0, 0, 0]]},
        )


def test_missing_package_is_refused(tmp_path):
    name = _build_base_model(tmp_path, name="nopkg", recharge=1e-3)
    with pytest.raises(ValueError, match="DRN"):
        _import_flows(name, _flow_csv(tmp_path, name, [("a", "2020-01-01", 1.0)]), package="DRN")


def test_unsupported_package_is_refused(tmp_path):
    name = _river_model(tmp_path)
    with pytest.raises(ValueError, match="package"):
        _import_flows(name, _flow_csv(tmp_path, name, [("a", "2020-01-01", 1.0)]), package="RCH")


def test_flow_observations_need_a_measurement_error(tmp_path):
    name = _river_model(tmp_path)
    with pytest.raises(ValueError, match="std"):
        _impl_import_flow_observations(
            model=name,
            csv_file=str(_flow_csv(tmp_path, name, [("a", "2020-01-01", 1.0)])),
            package="RIV",
        )


def test_relative_error_sets_sigma_from_the_value(tmp_path):
    name = _river_model(tmp_path)
    _impl_import_flow_observations(
        model=name,
        csv_file=str(_flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)])),
        package="RIV",
        rel_std=0.1,
    )
    _, obs_data, _ = _build_model_obs_interface(name, resolve_workspace(name))
    assert obs_data["river"]["standard_deviation"] == pytest.approx(80.0)
    assert obs_data["river"]["weight"] == pytest.approx(1 / 80.0)


def test_direction_sets_the_mf6_sign(tmp_path):
    name = _river_model(tmp_path)
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    _, obs_data, _ = _build_model_obs_interface(name, resolve_workspace(name))
    assert obs_data["river"]["obsval"] == pytest.approx(-800.0)

    name2 = _river_model(tmp_path, name="fq_in")
    _import_flows(
        name2, _flow_csv(tmp_path, name2, [("river", "2020-01-01", 800.0)]),
        direction="into_aquifer",
    )
    _, obs_data, _ = _build_model_obs_interface(name2, resolve_workspace(name2))
    assert obs_data["river"]["obsval"] == pytest.approx(800.0)


def test_bad_direction_is_refused(tmp_path):
    name = _river_model(tmp_path)
    with pytest.raises(ValueError, match="direction"):
        _import_flows(
            name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]),
            direction="up",
        )


@requires_mf6
def test_two_packages_register_with_append(tmp_path):
    name = _river_model(tmp_path)
    drn = [[[0, 1, 1], 29.0, 100.0]]
    _impl_add_boundary_package(name, "DRN", {"0": drn}, None)
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    _import_flows(
        name, _flow_csv(tmp_path, name, [("spring", "2020-01-01", 50.0)], "drn.csv"),
        package="DRN", append=True,
    )
    _impl_run_simulation(name, silent=True)
    assert "SPRING" in _sim_flows(name, "drn").columns
    assert "RIVER" in _sim_flows(name, "riv").columns
    _, obs_data, outputs = _build_model_obs_interface(name, resolve_workspace(name))
    assert set(obs_data) == {"river", "spring"}
    assert len(outputs) == 2


def test_flow_site_name_may_not_repeat_a_head_site(tmp_path):
    name = _river_model(tmp_path)
    _head_obs(tmp_path, name, {"river": (1, 1)})
    with pytest.raises(ValueError, match="already"):
        _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))


# ---------------------------------------------------------------------------
# Calibration interface
# ---------------------------------------------------------------------------


def test_heads_and_flows_share_one_control_file(tmp_path):
    name = _river_model(tmp_path)
    _head_obs(tmp_path, name, {"h1": (1, 1), "h2": (3, 3)})
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    res = _impl_setup_calibration(
        name,
        {
            "hk": {"target": "npf:k", "scope": "all", "initial": 5.0},
            "rech": {"target": "rch:recharge", "scope": "all", "initial": 1e-3},
        },
        balance_obs=True,
    )
    pst = pyemu.Pst(res["pst_file"])
    obs = pst.observation_data
    assert set(obs.index) == {"h1", "h2", "river"}
    assert obs.loc["river", "obgnme"] != obs.loc["h1", "obgnme"]
    assert len(pst.instruction_files) == 2
    share = (obs["weight"] ** 2 * obs["standard_deviation"] ** 2).groupby(obs["obgnme"]).sum()
    assert share.max() == pytest.approx(share.min())
    assert "identifiability_warning" not in res


def test_flow_only_registration_builds_an_interface(tmp_path):
    name = _river_model(tmp_path)
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    res = _impl_setup_calibration(name, {"hk": {"target": "npf:k", "scope": "all", "initial": 5.0}})
    assert set(pyemu.Pst(res["pst_file"]).observation_data.index) == {"river"}


def test_transient_flow_series_has_one_observation_per_step(tmp_path):
    name = _transient_model(tmp_path)
    times = _model_output_times(name)
    rows = [("east", _iso(times[i]), 100.0 + i) for i in (2, 4, 6)]
    _import_flows(
        name, _flow_csv(tmp_path, name, rows), package="CHD",
        targets={"east": [[0, r, 6] for r in range(7)]},
    )
    _, obs_data, _, report = _build_model_obs_interface(
        name, resolve_workspace(name), return_report=True
    )
    assert sorted(obs_data) == ["east_t3", "east_t5", "east_t7"]
    assert report["flows"]["n_matched"] == 3


@requires_mf6
def test_boundary_conductance_calibration_keeps_the_boundnames(tmp_path):
    name = _river_model(tmp_path)
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    _impl_setup_calibration(
        name, {"criv": {"target": "riv:cond", "scope": "all", "initial": 50.0}}
    )
    run = _impl_run_simulation(name, silent=True)
    assert run["success"]
    assert float(_sim_flows(name)["RIVER"].iloc[-1]) < 0


# ---------------------------------------------------------------------------
# Comparison and sensitivity read the flows too
# ---------------------------------------------------------------------------


@requires_mf6
def test_compare_to_observed_reports_flows_in_the_measured_sign(tmp_path):
    name = _river_model(tmp_path)
    _head_obs(tmp_path, name, {"h1": (1, 1)})
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    _impl_run_simulation(name, silent=True)
    res = _impl_compare_to_observed(name)
    flows = res["flows"]
    (row,) = flows["residuals"]
    assert row["site"] == "river"
    assert row["observed"] == pytest.approx(800.0)
    assert row["simulated"] == pytest.approx(-_cbc_flow(name, "RIV", RIV_CELLS), rel=1e-6)
    assert row["simulated"] > 0
    assert flows["per_site"]["river"]["n"] == 1
    assert res["n"] == 1  # the head statistics stay heads only


@requires_mf6
def test_compare_to_observed_works_with_flows_only(tmp_path):
    name = _river_model(tmp_path)
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    _impl_run_simulation(name, silent=True)
    res = _impl_compare_to_observed(name)
    assert "error" not in res
    assert res["flows"]["per_site"]["river"]["n"] == 1


@requires_mf6
def test_sensitivity_screen_sees_a_flow_only_parameter(tmp_path):
    name = _river_model(tmp_path)
    _head_obs(tmp_path, name, {"h1": (0, 0)})
    _import_flows(name, _flow_csv(tmp_path, name, [("river", "2020-01-01", 800.0)]))
    res = _impl_setup_calibration(
        name, {"criv": {"target": "riv:cond", "scope": "all", "initial": 50.0}}
    )
    tpls = res["template_files"]
    sens = _impl_check_parameter_sensitivity(name, {"criv": 50.0}, tpls)
    assert sens["parameters"]["criv"]["sensitivity"] > 1e-3


# ---------------------------------------------------------------------------
# A flow target separates K from recharge
# ---------------------------------------------------------------------------


@requires_mf6
@requires_pestpp
def test_glm_recovers_k_and_recharge_with_a_boundary_outflow(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_glm

    sites = {"h1": (1, 1), "h2": (2, 2), "h3": (3, 1)}
    truth = _build_base_model(tmp_path, name="truth", k=5.0, recharge=1e-3)
    _impl_run_simulation(truth, silent=True)
    hds = flopy.utils.HeadFile(str(resolve_workspace(truth) / f"{get_gwf(truth).name}.hds"))
    h = hds.get_data()[0]
    q_east = _cbc_flow(truth, "CHD", EAST_CHD)  # negative: out of the aquifer

    name = _build_base_model(tmp_path, name="fit", k=2.0, recharge=4e-4)
    _head_obs(tmp_path, name, sites, value={s: float(h[r, c]) for s, (r, c) in sites.items()})
    _import_flows(
        name, _flow_csv(tmp_path, name, [("east", "2020-01-01", -q_east)]),
        package="CHD", targets={"east": EAST_CHD}, std=None, rel_std=0.05,
    )
    res = _impl_setup_calibration(
        name,
        {
            "hk": {"target": "npf:k", "scope": "all", "initial": 2.0},
            "rech": {"target": "rch:recharge", "scope": "all", "initial": 4e-4},
        },
        noptmax=25,
    )
    out = _impl_run_pestpp_glm(name, res["pst_file"], 1)
    assert "error" not in out, out
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result

    _impl_apply_calibration_result(name, res["pst_file"])
    gwf = get_gwf(name)
    k = np.asarray(gwf.get_package("npf").k.array).reshape(-1)
    rch = gwf.get_package("rch").stress_period_data.get_data(0)["recharge"]
    print(f"recovered K {k.mean():.4g} (truth 5), R {np.mean(rch):.4g} (truth 1e-3)")
    assert k.mean() == pytest.approx(5.0, rel=0.05)
    assert float(np.mean(rch)) == pytest.approx(1e-3, rel=0.05)
