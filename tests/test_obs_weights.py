"""R3.9: observation weights from measurement error, and balanced groups.

A record's standard deviation (``std_col`` or ``std`` at import, or
``obs_std`` at setup) sets its weight to 1/sigma and is written to the control
file as ``standard_deviation``, which pestpp-ies uses for the observation
noise. A transient series gets one observation group per site, and
``balance_obs=True`` scales each site's weights so a site with many records
does not outweigh a site with few.
"""

from __future__ import annotations

import csv
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import pytest

from groundwater_mcp.tools.calibration import (
    _build_model_obs_interface,
    _impl_setup_calibration,
    _model_output_times,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.runner import _impl_run_simulation
from groundwater_mcp.utils.model_store import get_gwf
from groundwater_mcp.utils.spatial import grid_centroids
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_setup_calibration import _build_base_model, requires_mf6, requires_pestpp
from tests.test_transient_obs import SITE_CELLS, _iso, _transient_model

K_SPEC = {"hk": {"target": "npf:k", "scope": "all", "initial": 5.0}}


def _steady(tmp_path, name="w_model"):
    return _build_base_model(tmp_path, name=name, recharge=1e-3)


def _write(tmp_path, name, rows, ncol=None):
    """rows: (site, date, value, std, (row, col)). std None -> empty cell."""
    gwf = get_gwf(name)
    xc, yc = grid_centroids(gwf.modelgrid)
    ncol = ncol or int(gwf.modelgrid.ncol)
    path = tmp_path / f"{name}_obs.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "date", "value", "sd", "x", "y"])
        for site, date, value, std, (r, c) in rows:
            node = r * ncol + c
            w.writerow(
                [site, date, value, "" if std is None else std, float(xc[node]), float(yc[node])]
            )
    return path


def _import(name, path, **kw):
    return _impl_import_obs_from_csv(
        model=name,
        csv_file=str(path),
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
        **kw,
    )


def _obs_df(pst_file) -> pd.DataFrame:
    return pyemu.Pst(pst_file).observation_data


# ---------------------------------------------------------------------------
# Import: sigma per record
# ---------------------------------------------------------------------------


def test_std_column_sets_weight_and_standard_deviation(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, 0.05, (1, 1)), ("B", "2020-01-01", 28.0, 0.5, (2, 2))]
    _import(name, _write(tmp_path, name, rows), std_col="sd")
    res = _impl_setup_calibration(name, K_SPEC)
    obs = _obs_df(res["pst_file"])
    assert obs.loc["a", "weight"] == pytest.approx(20.0)
    assert obs.loc["b", "weight"] == pytest.approx(2.0)
    assert obs.loc["a", "standard_deviation"] == pytest.approx(0.05)
    assert obs.loc["b", "standard_deviation"] == pytest.approx(0.5)
    assert "weights_warning" not in res


def test_scalar_std_applies_to_every_record(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, None, (1, 1)), ("B", "2020-01-01", 28.0, None, (2, 2))]
    _import(name, _write(tmp_path, name, rows), std=0.1)
    obs = _obs_df(_impl_setup_calibration(name, K_SPEC)["pst_file"])
    np.testing.assert_allclose(obs["weight"], 10.0)


def test_std_column_fills_gaps_from_scalar_std(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, 0.05, (1, 1)), ("B", "2020-01-01", 28.0, None, (2, 2))]
    _import(name, _write(tmp_path, name, rows), std_col="sd", std=0.25)
    obs = _obs_df(_impl_setup_calibration(name, K_SPEC)["pst_file"])
    assert obs.loc["b", "weight"] == pytest.approx(4.0)


@pytest.mark.parametrize("bad", [0.0, -0.1, "x"])
def test_non_positive_or_non_numeric_std_is_refused(tmp_path, bad):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, bad, (1, 1))]
    with pytest.raises(ValueError, match="std"):
        _import(name, _write(tmp_path, name, rows), std_col="sd")


def test_missing_std_without_a_default_is_refused(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, 0.1, (1, 1)), ("B", "2020-01-01", 28.0, None, (2, 2))]
    with pytest.raises(ValueError, match="std"):
        _import(name, _write(tmp_path, name, rows), std_col="sd")


def test_steady_mean_of_several_records_has_the_standard_error(tmp_path):
    name = _steady(tmp_path)
    rows = [
        ("A", "2020-01-01", 30.0, 0.2, (1, 1)),
        ("A", "2020-02-01", 31.0, 0.2, (1, 1)),
        ("A", "2020-03-01", 32.0, 0.2, (1, 1)),
        ("A", "2020-04-01", 33.0, 0.2, (1, 1)),
    ]
    _import(name, _write(tmp_path, name, rows), std_col="sd")
    obs = _obs_df(_impl_setup_calibration(name, K_SPEC)["pst_file"])
    # mean of 4 independent records: sigma / sqrt(4) = 0.1
    assert obs.loc["a", "standard_deviation"] == pytest.approx(0.1)
    assert obs.loc["a", "weight"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Setup: default sigma and the uniform-weight warning
# ---------------------------------------------------------------------------


def test_obs_std_at_setup_is_the_default_sigma(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, None, (1, 1)), ("B", "2020-01-01", 28.0, 0.5, (2, 2))]
    _import(name, _write(tmp_path, name, rows), std_col="sd", std=0.5)
    # import-time sigma wins over the setup default
    obs = _obs_df(_impl_setup_calibration(name, K_SPEC, obs_std=0.01)["pst_file"])
    np.testing.assert_allclose(obs["weight"], 2.0)

    name2 = _steady(tmp_path, "w_model2")
    rows = [("A", "2020-01-01", 30.0, None, (1, 1))]
    _import(name2, _write(tmp_path, name2, rows))
    res = _impl_setup_calibration(name2, K_SPEC, obs_std=0.02)
    obs = _obs_df(res["pst_file"])
    assert obs.loc["a", "weight"] == pytest.approx(50.0)
    assert obs.loc["a", "standard_deviation"] == pytest.approx(0.02)
    assert "weights_warning" not in res


def test_no_sigma_keeps_unit_weights_and_warns(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, None, (1, 1))]
    _import(name, _write(tmp_path, name, rows))
    res = _impl_setup_calibration(name, K_SPEC)
    obs = _obs_df(res["pst_file"])
    assert obs.loc["a", "weight"] == pytest.approx(1.0)
    assert "standard_deviation" not in obs.columns
    assert "obs_std" in res["weights_warning"]
    assert res["observation_weights"]["sigma_source"] == "none"


def test_non_positive_obs_std_is_refused(tmp_path):
    name = _steady(tmp_path)
    _import(name, _write(tmp_path, name, [("A", "2020-01-01", 30.0, None, (1, 1))]))
    with pytest.raises(ValueError, match="obs_std"):
        _impl_setup_calibration(name, K_SPEC, obs_std=0.0)


# ---------------------------------------------------------------------------
# Transient: one group per site, optional balancing
# ---------------------------------------------------------------------------


def _series_rows(times, n_mw1, n_mw2, sd=0.1):
    rows = [("MW1", _iso(times[1 + i]), 29.0, sd, SITE_CELLS["MW1"]) for i in range(n_mw1)]
    rows += [("MW2", _iso(times[1 + i]), 29.5, sd, SITE_CELLS["MW2"]) for i in range(n_mw2)]
    return rows


def test_transient_series_gets_one_group_per_site(tmp_path):
    name = _transient_model(tmp_path)
    times = _model_output_times(name)
    _import(name, _write(tmp_path, name, _series_rows(times, 6, 2)), std_col="sd")
    ws = resolve_workspace(name)
    _, obs_data, _ = _build_model_obs_interface(name, ws)
    groups = {v["obgnme"] for v in obs_data.values()}
    assert len(groups) == 2
    assert all(len(g) <= 20 and not g.startswith("regul") for g in groups)


def test_balancing_equalises_each_sites_share_of_phi(tmp_path):
    name = _transient_model(tmp_path)
    times = _model_output_times(name)
    _import(name, _write(tmp_path, name, _series_rows(times, 6, 2)), std_col="sd")
    res = _impl_setup_calibration(name, K_SPEC, balance_obs=True)
    obs = _obs_df(res["pst_file"])
    share = (obs["weight"] ** 2).groupby(obs["obgnme"]).sum()
    assert share.max() == pytest.approx(share.min())
    # the noise stays the measurement error, not the balanced weight
    np.testing.assert_allclose(obs["standard_deviation"], 0.1)
    # total expected phi (sum of w^2 sigma^2) equals the number of records
    assert float((obs["weight"] ** 2 * 0.01).sum()) == pytest.approx(8.0)
    assert res["observation_weights"]["balanced"] is True


def test_unbalanced_transient_weights_are_one_over_sigma(tmp_path):
    name = _transient_model(tmp_path)
    times = _model_output_times(name)
    _import(name, _write(tmp_path, name, _series_rows(times, 6, 2)), std_col="sd")
    obs = _obs_df(_impl_setup_calibration(name, K_SPEC)["pst_file"])
    np.testing.assert_allclose(obs["weight"], 10.0)


def test_append_keeps_each_calls_sigma(tmp_path):
    name = _steady(tmp_path)
    _import(name, _write(tmp_path, name, [("A", "2020-01-01", 30.0, None, (1, 1))]), std=0.1)
    _import(
        name, _write(tmp_path, name, [("B", "2020-01-01", 28.0, None, (2, 2))]),
        std=0.5, append=True,
    )
    obs = _obs_df(_impl_setup_calibration(name, K_SPEC)["pst_file"])
    assert obs.loc["a", "weight"] == pytest.approx(10.0)
    assert obs.loc["b", "weight"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# PEST++ reads the sigma (noise ensemble, phi)
# ---------------------------------------------------------------------------


def _run(exe, pst_file):
    pst_path = Path(pst_file)
    proc = subprocess.run(
        [shutil.which(exe), pst_path.name], cwd=pst_path.parent,
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return pst_path.parent


@requires_mf6
@requires_pestpp
def test_pestpp_ies_noise_follows_the_measurement_sigma(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, 0.05, (1, 1)), ("B", "2020-01-01", 28.0, 0.5, (2, 2))]
    _import(name, _write(tmp_path, name, rows), std_col="sd")
    _impl_run_simulation(name, silent=True)
    res = _impl_setup_calibration(name, K_SPEC, noptmax=-2)
    pst = pyemu.Pst(res["pst_file"])
    pst.pestpp_options["ies_num_reals"] = 300
    pst.write(res["pst_file"], version=2)
    ws = _run("pestpp-ies", res["pst_file"])
    noise = pd.read_csv(ws / f"{Path(res['pst_file']).stem}.obs+noise.csv", index_col=0)
    assert noise["a"].std() == pytest.approx(0.05, rel=0.2)
    assert noise["b"].std() == pytest.approx(0.5, rel=0.2)


@requires_mf6
@requires_pestpp
def test_pestpp_glm_phi_is_the_sigma_weighted_misfit(tmp_path):
    name = _steady(tmp_path)
    rows = [("A", "2020-01-01", 30.0, 0.05, (1, 1)), ("B", "2020-01-01", 28.0, 0.5, (2, 2))]
    _import(name, _write(tmp_path, name, rows), std_col="sd")
    _impl_run_simulation(name, silent=True)
    res = _impl_setup_calibration(name, K_SPEC, noptmax=0)
    ws = _run("pestpp-glm", res["pst_file"])
    res_df = pyemu.pst_utils.read_resfile(str(ws / f"{Path(res['pst_file']).stem}.rei"))
    assert res_df.loc["a", "weight"] == pytest.approx(20.0)
    assert res_df.loc["b", "weight"] == pytest.approx(2.0)
    phi = float(((res_df["residual"] * res_df["weight"]) ** 2).sum())
    iobj = pd.read_csv(ws / f"{Path(res['pst_file']).stem}.iobj")
    assert math.isfinite(phi) and float(iobj["total_phi"].iloc[0]) == pytest.approx(phi, rel=1e-4)
