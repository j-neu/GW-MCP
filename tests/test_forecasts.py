"""R3.13: forecasts (predictions) in the calibration control file.

``register_forecasts`` stores head forecasts (a location and a time) and
whole-package flow forecasts. The calibration setup adds them to the PST with
weight 0 in group ``forecast`` and lists them in the PEST++ ``forecasts``
option, so pestpp-glm reports their FOSM uncertainty and pestpp-ies carries
them through every realisation. The forward wrapper writes their simulated
values to ``<gwf>_forecasts.csv``: heads from a separate OBS package (an
``import_obs_from_csv`` call never replaces it), flows as OUT - IN from the
MF6 budget CSV.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import flopy
import numpy as np
import pandas as pd
import pyemu
import pytest

from groundwater_mcp.tools.calibration import (
    _impl_run_ies_uncertainty,
    _impl_setup_calibration,
    _impl_summarise_calibration,
)
from groundwater_mcp.tools.parameterise import _impl_register_forecasts
from groundwater_mcp.utils.model_store import flush_model, get_gwf, read_meta
from groundwater_mcp.utils.spatial import grid_centroids
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_setup_calibration import requires_mf6, requires_pestpp
from tests.test_transient_obs import NCOL, _import, _iso, _transient_model, _write_obs_csv

K_SPEC = {"k": {"target": "npf:k", "scope": "all", "initial": 2.0}}


def _xy(name, r, c):
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    node = r * NCOL + c
    return float(xc[node]), float(yc[node])


def _model(tmp_path, name="fc"):
    name = _transient_model(tmp_path, name)
    rows = [(s, _iso(t), 30.0 - 0.01 * t) for s in ("MW1", "MW2") for t in (6, 21, 41)]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    return name


def _forecasts(name):
    x, y = _xy(name, 3, 4)
    return [
        {"name": "h_end", "kind": "head", "x": x, "y": y},
        {"name": "h_day11", "kind": "head", "x": x, "y": y, "time": 11.0},
        {"name": "chd_in", "kind": "flow", "package": "CHD", "direction": "into_aquifer",
         "time": _iso(21)},
    ]


def _run_command(name, command):
    proc = subprocess.run(
        shlex.split(command, posix=False), cwd=resolve_workspace(name),
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- registration ---------------------------------------------------------


def test_register_stores_cells_and_model_times(tmp_path):
    name = _model(tmp_path)
    res = _impl_register_forecasts(name, _forecasts(name))
    by_name = {f["name"]: f for f in res["forecasts"]}
    assert by_name["h_end"]["model_time"] == pytest.approx(41.0)
    assert by_name["h_day11"]["model_time"] == pytest.approx(11.0)
    assert by_name["chd_in"]["model_time"] == pytest.approx(21.0)
    assert by_name["h_end"]["cellid"] == [0, 3, 4]
    assert by_name["chd_in"]["columns"] == ["CHD(CHD_0)_IN", "CHD(CHD_0)_OUT"]
    stored = read_meta(name)["forecasts"]
    assert [f["name"] for f in stored["items"]] == ["h_end", "h_day11", "chd_in"]
    gwf = get_gwf(name)
    assert gwf.oc.budgetcsv_filerecord.get_data() is not None
    flush_model(name)
    obs_text = (resolve_workspace(name) / f"{gwf.name}.obs").read_text().lower()
    assert f"{gwf.name}_fc_head.obs.csv" in obs_text  # MF6 takes one model OBS6
    assert f"{gwf.name}_head.obs.csv" in obs_text


def test_head_forecasts_survive_a_new_observation_import(tmp_path):
    name = _model(tmp_path)
    _impl_register_forecasts(name, _forecasts(name))
    rows = [("MW3", _iso(41), 29.0)]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    flush_model(name)
    gwf = get_gwf(name)
    obs_text = (resolve_workspace(name) / f"{gwf.name}.obs").read_text().lower()
    assert f"{gwf.name}_fc_head.obs.csv" in obs_text
    assert "mw3" in obs_text and "mw1" not in obs_text


def test_append_adds_and_replace_drops(tmp_path):
    name = _model(tmp_path)
    fcs = _forecasts(name)
    _impl_register_forecasts(name, fcs[:1])
    _impl_register_forecasts(name, fcs[1:2], append=True)
    assert [f["name"] for f in read_meta(name)["forecasts"]["items"]] == ["h_end", "h_day11"]
    _impl_register_forecasts(name, fcs[2:])
    assert [f["name"] for f in read_meta(name)["forecasts"]["items"]] == ["chd_in"]


@pytest.mark.parametrize(
    "bad, match",
    [
        ({"name": "a_name_longer_than_20", "kind": "head"}, "20"),
        ({"name": "mw1", "kind": "head"}, "already"),
        ({"name": "f1", "kind": "concentration"}, "kind"),
        ({"name": "f1", "kind": "head", "time": 500.0}, "after the simulated"),
        ({"name": "f1", "kind": "flow", "package": "RIV"}, "RIV"),
        ({"name": "f1", "kind": "flow", "package": "CHD", "direction": "up"}, "direction"),
        ({"name": "f1", "kind": "head", "x": 1e7, "y": 1e7}, "outside"),
    ],
)
def test_invalid_forecasts_are_refused(tmp_path, bad, match):
    name = _model(tmp_path)
    spec = dict(bad)
    if spec["kind"] == "head":
        x, y = _xy(name, 3, 4)
        spec.setdefault("x", x)
        spec.setdefault("y", y)
    with pytest.raises(ValueError, match=match):
        _impl_register_forecasts(name, [spec])


def test_repeated_forecast_names_are_refused(tmp_path):
    name = _model(tmp_path)
    fc = _forecasts(name)[0]
    with pytest.raises(ValueError, match="h_end"):
        _impl_register_forecasts(name, [fc, dict(fc)])


# --- control file ---------------------------------------------------------


def test_setup_puts_forecasts_in_the_pst_with_zero_weight(tmp_path):
    name = _model(tmp_path)
    _impl_register_forecasts(name, _forecasts(name))
    res = _impl_setup_calibration(name, K_SPEC, obs_std=0.05, balance_obs=True)
    pst = pyemu.Pst(res["pst_file"])
    obs = pst.observation_data
    fc = obs.loc[["h_end", "h_day11", "chd_in"]]
    assert (fc["weight"] == 0).all()
    assert set(fc["obgnme"]) == {"forecast"}
    assert pst.pestpp_options["forecasts"] == "h_end,h_day11,chd_in"
    assert res["forecasts"] == ["h_end", "h_day11", "chd_in"]
    assert "gwmcp_run_" in " ".join(res["model_command"])
    # Forecasts change neither the weight summary nor the group balance.
    assert res["observation_weights"]["weight_min"] > 0
    assert res["observation_weights"]["n_groups"] == 2
    fitted = obs[obs["weight"] > 0]
    phi_share = fitted.groupby("obgnme")["weight"].apply(lambda w: float((w**2).sum()))
    assert phi_share.max() == pytest.approx(phi_share.min())


@requires_mf6
def test_wrapper_writes_the_simulated_forecasts(tmp_path):
    name = _model(tmp_path)
    _impl_register_forecasts(name, _forecasts(name))
    res = _impl_setup_calibration(name, K_SPEC)
    _run_command(name, res["model_command"][0])
    ws = resolve_workspace(name)
    gwf = get_gwf(name)
    fc = pd.read_csv(ws / f"{gwf.name}_forecasts.csv")
    hds = flopy.utils.HeadFile(str(ws / f"{gwf.name}.hds"))
    assert float(fc["h_end"].iloc[0]) == pytest.approx(hds.get_data(totim=41.0)[0, 3, 4])
    assert float(fc["h_day11"].iloc[0]) == pytest.approx(hds.get_data(totim=11.0)[0, 3, 4])
    cbb = flopy.utils.CellBudgetFile(str(ws / f"{gwf.name}.cbb"))
    chd = cbb.get_data(text="CHD", totim=21.0)[0]
    net_in = float(np.sum(chd["q"]))
    assert float(fc["chd_in"].iloc[0]) == pytest.approx(net_in, rel=1e-6)
    assert net_in > 0  # the well draws water in through the CHD boundary


def _pestpp(exe, pst_file):
    pst_path = Path(pst_file)
    proc = subprocess.run(
        [exe, pst_path.name], cwd=pst_path.parent, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
    return pst_path


@requires_mf6
@requires_pestpp
def test_glm_reports_the_forecast_uncertainty(tmp_path):
    name = _model(tmp_path)
    _impl_register_forecasts(name, _forecasts(name))
    res = _impl_setup_calibration(name, K_SPEC, noptmax=3, obs_std=0.05)
    pst_path = _pestpp("pestpp-glm", res["pst_file"])
    summary = _impl_summarise_calibration(name, str(pst_path))
    fc = summary["forecasts"]
    assert set(fc) == {"h_end", "h_day11", "chd_in"}
    for info in fc.values():
        assert info["method"] == "fosm"
        assert info["posterior_std"] < info["prior_std"]
        assert np.isfinite(info["simulated"])
    names = {r["obs_name"] for r in summary["residuals"]}
    assert not names & {"h_end", "h_day11", "chd_in"}


@requires_mf6
@requires_pestpp
def test_ies_uncertainty_defaults_to_the_registered_forecasts(tmp_path):
    name = _model(tmp_path)
    _impl_register_forecasts(name, _forecasts(name))
    res = _impl_setup_calibration(name, K_SPEC, noptmax=1, obs_std=0.05)
    pst = pyemu.Pst(res["pst_file"])
    pst.pestpp_options["ies_num_reals"] = 8
    pst.write(res["pst_file"])
    pst_path = _pestpp("pestpp-ies", res["pst_file"])
    out = _impl_run_ies_uncertainty(name, str(pst_path))
    assert set(out["forecasts"]) == {"h_end", "h_day11", "chd_in"}
    assert out["ensemble_file"].endswith(".1.obs.csv")
    for info in out["forecasts"].values():
        assert info["n_realizations"] >= 2
        assert "prior_std" in info
    summary = _impl_summarise_calibration(name, str(pst_path))
    assert summary["forecasts"]["h_end"]["method"] == "ensemble"
    assert summary["forecasts"]["h_end"]["posterior_std"] >= 0


@requires_mf6
def test_a_dry_forecast_cell_reports_its_bottom(tmp_path):
    from tests.test_calibration_practice import _drying_model, _register

    name = _drying_model(tmp_path, "fcdry")
    _register(tmp_path, name, [("WET", 0, 8.0)])
    _impl_register_forecasts(name, [{"name": "h_dry", "kind": "head", "cellid": [0, 0, 4]}])
    res = _impl_setup_calibration(name, {"k": {"target": "npf:k", "scope": "all", "initial": 1.0}})
    _run_command(name, res["model_command"][0])
    ws = resolve_workspace(name)
    fc = pd.read_csv(ws / f"{get_gwf(name).name}_forecasts.csv")
    assert float(fc["h_dry"].iloc[0]) == pytest.approx(0.0)


def test_ies_uncertainty_reads_the_last_iteration_numerically(tmp_path):
    name = _model(tmp_path)
    ws = resolve_workspace(name)
    for it, value in ((0, 1.0), (2, 2.0), (10, 3.0)):
        pd.DataFrame({"real_name": ["0", "1"], "f": [value, value + 0.1]}).to_csv(
            ws / f"case.{it}.obs.csv", index=False
        )
    (ws / "case.pst").write_text("pcf\n")
    out = _impl_run_ies_uncertainty(name, str(ws / "case.pst"), ["f"])
    assert out["ensemble_file"].endswith("case.10.obs.csv")
    assert out["forecasts"]["f"]["mean"] == pytest.approx(3.05)
    assert out["forecasts"]["f"]["prior_mean"] == pytest.approx(1.05)
