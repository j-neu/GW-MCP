"""R3.5: pilot-point K parameterisation with a geostatistical prior.

``setup_calibration(scope="pilot_points")`` places pilot points on a layer
(a regular ``spacing`` lattice or explicit ``points``), computes ordinary-kriging
factors once at setup time, and lets a stdlib-only forward wrapper rebuild
``k = base_k x 10 ** (sum_i w_i * log10(pp_i))`` before every run. The pilot
point values are dimensionless multipliers (initial 1.0 = the base field). The
prior covariance between pilot points comes from the variogram and is handed
to PEST++ as ``parcov``.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
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
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_zoned_calibration import _register_obs, requires_mf6, requires_pestpp

N = 10
CELL = 100.0


def _pp_model(tmp_path, name="pp_model", k=None, idomain=None):
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 1, N, N, CELL, CELL, 50.0, [0.0], idomain=idomain)
    k = np.full((1, N, N), 5.0) if k is None else k
    _impl_add_npf_package(name, icelltype=0, k=k, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(N)] + [[[0, r, N - 1], 10.0] for r in range(N)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    rch = [[[0, r, c], 0.002] for r in range(N) for c in range(1, N - 1)]
    _impl_add_boundary_package(name, "RCH", {"0": rch}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _spec(**extra):
    spec = {"target": "npf:k", "scope": "pilot_points", "layer": 0, "spacing": 300.0}
    spec.update(extra)
    return {"kpp": spec}


# ---------------------------------------------------------------------------
# normalisation and kriging factors
# ---------------------------------------------------------------------------


def test_spacing_lattice_places_points_on_active_cells(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_pilot_point_parameterisation

    name = _pp_model(tmp_path)
    norm = _normalise_pilot_point_parameterisation(name, _spec())
    # 1000 m square, spacing 300 m -> x, y in {150, 450, 750} -> 9 points
    assert len(norm["points"]) == 9
    assert [p["name"] for p in norm["points"]][:3] == ["kpp_p1", "kpp_p2", "kpp_p3"]
    xs = sorted({p["x"] for p in norm["points"]})
    assert xs == pytest.approx([150.0, 450.0, 750.0])


def test_lattice_skips_inactive_cells(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_pilot_point_parameterisation

    idomain = np.ones((1, N, N), dtype=int)
    idomain[0, :4, :4] = 0  # x < 400, y > 600 inactive: holds only the (150, 750) point
    name = _pp_model(tmp_path, idomain=idomain.tolist())
    norm = _normalise_pilot_point_parameterisation(name, _spec())
    assert (150.0, 750.0) not in {(p["x"], p["y"]) for p in norm["points"]}
    assert len(norm["points"]) == 8


def test_explicit_points_are_used_verbatim(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_pilot_point_parameterisation

    name = _pp_model(tmp_path)
    spec = {"kpp": {"target": "npf:k", "scope": "pilot_points", "layer": 0,
                    "points": [[200.0, 200.0], [800.0, 800.0]]}}
    norm = _normalise_pilot_point_parameterisation(name, spec)
    assert [(p["x"], p["y"]) for p in norm["points"]] == [(200.0, 200.0), (800.0, 800.0)]


def test_kriging_factors_sum_to_one_and_honour_the_points(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_pilot_point_parameterisation

    name = _pp_model(tmp_path)
    norm = _normalise_pilot_point_parameterisation(name, _spec())
    assert len(norm["factors"]) == N * N
    for _cell, pairs in norm["factors"].items():
        assert sum(w for _i, w in pairs) == pytest.approx(1.0, abs=1e-6)
    # cell (row 8, col 1) is centred at x=150, y=150: a pilot point sits there
    cell = 8 * N + 1
    pp = next(i for i, p in enumerate(norm["points"]) if (p["x"], p["y"]) == (150.0, 150.0))
    weights = dict(norm["factors"][cell])
    assert weights.get(pp, 0.0) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    "bad, match",
    [
        ({"target": "npf:k33"}, "npf:k"),
        ({"layer": None}, "layer"),
        ({"spacing": None}, "spacing"),
        ({"variogram": {"type": "cubic"}}, "variogram"),
        ({"points": [[5000.0, 5000.0]], "spacing": None}, "outside"),
    ],
)
def test_invalid_specs_are_rejected(tmp_path, bad, match):
    from groundwater_mcp.tools.calibration import _normalise_pilot_point_parameterisation

    name = _pp_model(tmp_path)
    spec = _spec()
    spec["kpp"].update(bad)
    spec["kpp"] = {k: v for k, v in spec["kpp"].items() if v is not None}
    with pytest.raises(ValueError, match=match):
        _normalise_pilot_point_parameterisation(name, spec)


def test_pilot_points_cannot_mix_with_other_scopes(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _pp_model(tmp_path)
    _register_obs(tmp_path, name)
    spec = _spec()
    spec["k2"] = {"target": "npf:k", "scope": "all", "initial": 5.0}
    with pytest.raises(ValueError, match="pilot_points"):
        _impl_setup_calibration(name, spec)


# ---------------------------------------------------------------------------
# applying the multipliers
# ---------------------------------------------------------------------------


def test_apply_pilot_point_multipliers(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _apply_pilot_point_multipliers,
        _write_pp_factors,
    )

    base = tmp_path / "base.dat"
    fac = tmp_path / "fac.dat"
    pp = tmp_path / "pp.dat"
    out = tmp_path / "k.dat"
    np.savetxt(base, np.array([2.0, 2.0, 2.0, 2.0]), fmt="%.10g")
    # cell 0 = pp0; cell 1 = halfway in log space; cell 2 = pp1; cell 3 no factors
    _write_pp_factors(fac, {0: [(0, 1.0)], 1: [(0, 0.5), (1, 0.5)], 2: [(1, 1.0)]})
    np.savetxt(pp, np.array([10.0, 1.0]), fmt="%.10g")
    k = _apply_pilot_point_multipliers(base, fac, pp, out)
    assert list(k) == pytest.approx([20.0, 2.0 * 10 ** 0.5, 2.0, 2.0])
    assert list(np.loadtxt(out)) == pytest.approx(list(k))


# ---------------------------------------------------------------------------
# setup_calibration end to end
# ---------------------------------------------------------------------------


@requires_mf6
def test_setup_emits_pilot_point_interface_and_prior(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _pp_model(tmp_path)
    _register_obs(tmp_path, name)
    res = _impl_setup_calibration(name, _spec(variogram={"type": "exp", "a": 600.0}))
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 9
    assert len(res["pilot_points"]) == 9

    ws = resolve_workspace(name)
    gwf = get_gwf(name).name
    # initial multipliers 1.0 leave K at the base field
    assert np.loadtxt(ws / f"{gwf}_k.dat") == pytest.approx(np.full(N * N, 5.0))

    pst = pyemu.Pst(res["pst_file"])
    pars = pst.parameter_data
    assert set(pars.partrans) == {"log"}
    assert set(pars.pargp) == {"kpp"}
    assert pst.pestpp_options["parcov"] == res["prior_covariance_file"].split("\\")[-1].split("/")[-1]

    cov = pyemu.Cov.from_binary(res["prior_covariance_file"])
    assert sorted(cov.row_names) == sorted(pars.index)
    mat = cov.to_dataframe()
    np.testing.assert_allclose(mat.values, mat.values.T)
    assert np.all(np.linalg.eigvalsh(mat.values) > 0)
    # correlation decays with distance: neighbours > far corners
    p = {pt["name"]: pt for pt in res["pilot_points"]}
    corner, near, far = "kpp_p1", None, None
    for n2, pt in p.items():
        d = np.hypot(pt["x"] - p[corner]["x"], pt["y"] - p[corner]["y"])
        if np.isclose(d, 300.0) and near is None:
            near = n2
        if d > 800.0:
            far = n2
    assert mat.loc[corner, near] > mat.loc[corner, far] > 0


@requires_mf6
def test_forward_wrapper_rebuilds_k_from_pilot_points(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _pp_model(tmp_path)
    _register_obs(tmp_path, name)
    res = _impl_setup_calibration(name, _spec())
    assert "error" not in res, res
    body = open(res["forward_wrapper"]).read()
    assert "groundwater_mcp" not in body and "numpy" not in body
    assert "stdout=subprocess.DEVNULL" in body

    ws = resolve_workspace(name)
    gwf = get_gwf(name).name
    values = np.ones(9)
    values[0] = 10.0
    np.savetxt(ws / res["target_file"].replace("\\", "/").split("/")[-1], values, fmt="%.10g")
    proc = subprocess.run(
        [sys.executable, res["forward_wrapper"]], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    k = np.loadtxt(ws / f"{gwf}_k.dat").reshape(N, N)
    p1 = res["pilot_points"][0]
    row = int((N * CELL - p1["y"]) // CELL)
    col = int(p1["x"] // CELL)
    assert k[row, col] == pytest.approx(50.0, rel=1e-6)
    assert k.min() == pytest.approx(5.0, rel=1e-3)
    assert 5.0 < k[row, col + 1] < 50.0


@requires_mf6
def test_apply_calibration_result_rebuilds_k_from_pilot_points(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _impl_apply_calibration_result,
        _impl_setup_calibration,
    )

    name = _pp_model(tmp_path)
    _register_obs(tmp_path, name)
    res = _impl_setup_calibration(name, _spec(), noptmax=0)
    pst_file = res["pst_file"]
    names = list(pyemu.Pst(pst_file).parameter_data.index)
    with open(pst_file[: -len(".pst")] + ".par", "w") as fh:
        fh.write("single point\n")
        for n in names:
            fh.write(f"{n} {2.0:.6e} 1.0 0.0\n")
    _impl_apply_calibration_result(name, pst_file)
    k = np.asarray(get_gwf(name).get_package("npf").k.array).reshape(-1)
    assert k == pytest.approx(np.full(N * N, 10.0), rel=1e-6)


@requires_mf6
@requires_pestpp
def test_pestpp_ies_draws_its_prior_from_the_pilot_point_covariance(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_ies, _impl_setup_calibration

    name = _pp_model(tmp_path)
    _register_obs(tmp_path, name, n_obs=9)
    res = _impl_setup_calibration(name, _spec(variogram={"a": 900.0}), noptmax=1)
    run = _impl_run_pestpp_ies(name, res["pst_file"], num_reals=30, num_workers=1)
    assert run["converged"] is True, run.get("stdout", "")[-2000:]

    ws = resolve_workspace(name)
    prior = pyemu.ParameterEnsemble.from_csv(
        pst=pyemu.Pst(res["pst_file"]), filename=str(ws / f"{name}.0.par.csv")
    )
    logs = np.log10(prior._df.astype(float))
    corr = logs.corr()
    # neighbouring points (300 m apart) are strongly correlated under a 900 m
    # range; with a diagonal prior they would scatter around zero
    p = {pt["name"]: pt for pt in res["pilot_points"]}
    pairs = [
        corr.loc[a, b]
        for a in p
        for b in p
        if a < b and np.isclose(np.hypot(p[a]["x"] - p[b]["x"], p[a]["y"] - p[b]["y"]), 300.0)
    ]
    assert np.mean(pairs) > 0.4, pairs


@requires_mf6
@requires_pestpp
def test_pilot_point_calibration_recovers_a_heterogeneous_field(tmp_path):
    """Synthetic truth: K = 20 m/d in the west half, 2 m/d in the east. Heads
    from the truth are the observations; calibration starts from uniform 6 m/d
    with 9 pilot points and must cut phi by at least 90 %."""
    import csv

    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_calibration,
        _impl_summarise_calibration,
    )
    from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
    from groundwater_mcp.tools.runner import _impl_run_simulation
    from groundwater_mcp.utils.spatial import grid_centroids

    truth_k = np.full((1, N, N), 2.0)
    truth_k[0, :, : N // 2] = 20.0
    truth = _pp_model(tmp_path, "pp_truth", k=truth_k)
    assert _impl_run_simulation(truth)["success"]
    heads = np.asarray(
        __import__("flopy").utils.HeadFile(str(resolve_workspace(truth) / "pp_truth.hds")).get_data()
    ).reshape(N, N)

    name = _pp_model(tmp_path, "pp_cal", k=np.full((1, N, N), 6.0))
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    csv_path = tmp_path / "obs.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["site", "date", "value", "x", "y"])
        i = 0
        for r in range(1, N - 1, 2):
            for c in range(1, N - 1, 2):
                i += 1
                w.writerow([f"W{i:02d}", "2020-01-01", float(heads[r, c]),
                            float(xc[r * N + c]), float(yc[r * N + c])])
    _impl_import_obs_from_csv(model=name, csv_file=str(csv_path), obs_type="HEAD",
                              site_col="site", date_col="date", value_col="value",
                              x_col="x", y_col="y", layer=0)

    res = _impl_setup_calibration(name, _spec(lower_factor=0.05, upper_factor=20.0), noptmax=6)
    assert "error" not in res, res
    run = _impl_run_pestpp_glm(name, res["pst_file"], 1)
    summary = _impl_summarise_calibration(name, res["pst_file"])
    phis = [p["phi"] for p in summary["phi_progress"]]
    assert phis, (run, summary)
    assert phis[-1] < 0.1 * phis[0], phis

    # The recovered field has the truth's structure, not just a lower phi.
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result

    _impl_apply_calibration_result(name, res["pst_file"])
    k = np.asarray(get_gwf(name).get_package("npf").k.array).reshape(N, N)
    west, east = k[:, 1 : N // 2].mean(), k[:, N // 2 : N - 1].mean()
    print(f"phi {phis[0]:.4g} -> {phis[-1]:.4g}; K west {west:.3g}, east {east:.3g}")
    assert west > 3.0 * east, (west, east)
