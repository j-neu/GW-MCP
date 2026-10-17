"""R3.7: transient head time-series observations in the calibration chain.

A transient model writes one obs-CSV row per time step. Registered head
records are matched by date to those rows, so the PEST interface has one
observation per (site, matched time) instead of one per site read from the
first row.
"""

from __future__ import annotations

import csv
import datetime

import numpy as np
import pandas as pd
import pyemu
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
from tests.test_setup_calibration import (
    _build_base_model,
    _register_obs,
    requires_mf6,
    requires_pestpp,
)

START = datetime.date(2020, 1, 1)
NROW = NCOL = 7
SITE_CELLS = {"MW1": (2, 3), "MW2": (3, 2), "MW3": (4, 4)}


def _transient_model(tmp_path, name="tr_model", k=5.0, ss=1e-4, start="2020-01-01"):
    """1 layer, steady SP0 (1 d) then a 40-day pumping period of 8 steps."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(
        name,
        nper=2,
        perlen=[1.0, 40.0],
        nstp=[1, 8],
        ims_complexity="moderate",
        start_date_time=start,
    )
    _impl_add_dis_package(name, 1, NROW, NCOL, 100.0, 100.0, 50.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=k, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=30.0)
    _impl_add_sto_package(name, 0, ss, 0.1, [0], True)
    chd = [[[0, r, 0], 30.0] for r in range(NROW)] + [
        [[0, r, NCOL - 1], 30.0] for r in range(NROW)
    ]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_boundary_package(
        name, "WEL", {"0": [[[0, 3, 3], 0.0]], "1": [[[0, 3, 3], -400.0]]}, None
    )
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _write_obs_csv(tmp_path, name, rows):
    """rows: (site, date_str, value). Coordinates from SITE_CELLS."""
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    path = tmp_path / f"{name}_obs.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "date", "value", "x", "y"])
        for site, date, value in rows:
            r, c = SITE_CELLS[site]
            node = r * NCOL + c
            w.writerow([site, date, value, float(xc[node]), float(yc[node])])
    return path


def _import(name, path):
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
    )


def _iso(days: float) -> str:
    return (START + datetime.timedelta(days=round(days))).isoformat()


def _obs_csv(name) -> pd.DataFrame:
    ws = resolve_workspace(name)
    return pd.read_csv(ws / f"{name}_head.obs.csv")


# ---------------------------------------------------------------------------
# Output times come from TDIS, without a model run
# ---------------------------------------------------------------------------


@requires_mf6
def test_output_times_match_the_mf6_obs_csv(tmp_path):
    name = _transient_model(tmp_path)
    _import(name, _write_obs_csv(tmp_path, name, [("MW1", "2020-01-05", 29.0)]))
    times = _model_output_times(name)
    _impl_run_simulation(name, silent=True)
    sim_times = _obs_csv(name)["time"].to_numpy()
    np.testing.assert_allclose(times, sim_times, rtol=1e-9)


def test_output_times_honour_tsmult(tmp_path):
    name = _transient_model(tmp_path)
    tdis = get_gwf(name).simulation.get_package("tdis")
    tdis.perioddata.set_data([(1.0, 1, 1.0), (31.0, 5, 2.0)])
    times = _model_output_times(name)
    # dt1 = 31 * (2-1) / (2**5 - 1) = 1 -> steps 1, 2, 4, 8, 16
    np.testing.assert_allclose(times, [1.0, 2.0, 4.0, 8.0, 16.0, 32.0])


# ---------------------------------------------------------------------------
# Matching dated records to output rows
# ---------------------------------------------------------------------------


def test_transient_interface_has_one_obs_per_site_and_time(tmp_path):
    name = _transient_model(tmp_path)
    times = _model_output_times(name)  # 1, 6, 11, ..., 41
    rows = [
        ("MW1", _iso(times[2]), 29.0),
        ("MW1", _iso(times[5]), 28.0),
        ("MW2", _iso(times[2]), 29.5),
    ]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    ws = resolve_workspace(name)
    ins_paths, obs_data, _ = _build_model_obs_interface(name, ws)

    assert len(obs_data) == 3
    by_value = {round(v["obsval"], 3): k for k, v in obs_data.items()}
    assert set(by_value) == {29.0, 28.0, 29.5}
    assert all(len(k) <= 20 for k in obs_data)
    assert len(set(k.lower() for k in obs_data)) == 3
    ins_names = set(pyemu.pst_utils.InstructionFile(ins_paths[0]).obs_name_set)
    assert ins_names == {k.lower() for k in obs_data}


def test_off_grid_dates_snap_to_the_nearest_output_time(tmp_path):
    name = _transient_model(tmp_path)
    # Output times 1, 6, 11, ...: day 7 is nearest to 6, day 9 nearest to 11.
    rows = [("MW1", _iso(7), 29.0), ("MW1", _iso(9), 28.0)]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    ws = resolve_workspace(name)
    _, obs_data, _, report = _build_model_obs_interface(name, ws, return_report=True)
    matched = {m["date"][:10]: m["model_time"] for m in report["sites"]["MW1"]["matched"]}
    assert matched == {_iso(7): pytest.approx(6.0), _iso(9): pytest.approx(11.0)}
    assert len(obs_data) == 2


def test_records_outside_the_simulated_window_are_skipped_and_reported(tmp_path):
    name = _transient_model(tmp_path)
    rows = [
        ("MW1", _iso(11), 29.0),
        ("MW1", "2019-06-01", 30.0),  # before the start date
        ("MW1", _iso(200), 27.0),  # long after the last time step (41 d)
    ]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    ws = resolve_workspace(name)
    _, obs_data, _, report = _build_model_obs_interface(name, ws, return_report=True)
    assert len(obs_data) == 1
    skipped = report["sites"]["MW1"]["skipped"]
    assert {s["date"][:10] for s in skipped} == {"2019-06-01", _iso(200)}
    assert report["n_matched"] == 1
    assert report["n_skipped"] == 2


def test_records_on_the_same_output_time_are_averaged(tmp_path):
    name = _transient_model(tmp_path)
    rows = [("MW1", _iso(10), 29.0), ("MW1", _iso(12), 28.0)]  # both -> t=11
    _import(name, _write_obs_csv(tmp_path, name, rows))
    ws = resolve_workspace(name)
    _, obs_data, _ = _build_model_obs_interface(name, ws)
    assert [v["obsval"] for v in obs_data.values()] == [pytest.approx(28.5)]


def test_tolerance_option_narrows_matching(tmp_path):
    name = _transient_model(tmp_path)
    rows = [("MW1", _iso(11), 29.0), ("MW1", _iso(13), 28.0)]  # 0 d and 2 d off
    _import(name, _write_obs_csv(tmp_path, name, rows))
    ws = resolve_workspace(name)
    _, obs_data, _, report = _build_model_obs_interface(
        name, ws, time_tolerance=1.0, return_report=True
    )
    assert len(obs_data) == 1
    assert report["n_skipped"] == 1


def test_calendar_dates_without_start_date_are_an_error(tmp_path):
    name = _transient_model(tmp_path, start=None)
    _import(name, _write_obs_csv(tmp_path, name, [("MW1", "2020-01-05", 29.0)]))
    ws = resolve_workspace(name)
    with pytest.raises(ValueError, match="start_date_time"):
        _build_model_obs_interface(name, ws)


def test_numeric_dates_are_elapsed_model_time(tmp_path):
    name = _transient_model(tmp_path, start=None)
    rows = [("MW1", "11", 29.0), ("MW1", "41.0", 28.0)]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    ws = resolve_workspace(name)
    _, obs_data, _, report = _build_model_obs_interface(name, ws, return_report=True)
    times = sorted(m["model_time"] for m in report["sites"]["MW1"]["matched"])
    assert times == [pytest.approx(11.0), pytest.approx(41.0)]


def test_steady_state_interface_is_unchanged(tmp_path):
    name = _build_base_model(tmp_path, "ss_model")
    _register_obs(tmp_path, name, n_obs=3)
    ws = resolve_workspace(name)
    ins_paths, obs_data, _ = _build_model_obs_interface(name, ws)
    assert sorted(obs_data) == ["S01", "S02", "S03"]
    lines = (ws / ins_paths[0]).read_text().splitlines()
    assert lines[:2] == ["pif ~", "l1"]
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# The instruction file reads the right rows of a real run
# ---------------------------------------------------------------------------


@requires_mf6
def test_instruction_file_reads_the_matched_rows(tmp_path):
    name = _transient_model(tmp_path)
    times = _model_output_times(name)
    picks = {"MW1": [1, 4, 8], "MW2": [8], "MW3": [0, 3]}
    rows = [
        (site, _iso(times[i]), 30.0 - i * 0.1)
        for site, idx in picks.items()
        for i in idx
    ]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    run = _impl_run_simulation(name, silent=True)
    assert run["success"], run
    sim = _obs_csv(name)
    ws = resolve_workspace(name)
    ins_paths, obs_data, output_files, report = _build_model_obs_interface(
        name, ws, return_report=True
    )
    read = pyemu.pst_utils.InstructionFile(ins_paths[0]).read_output_file(
        str(ws / output_files[0])
    )
    assert len(read) == sum(len(v) for v in picks.values())
    for site, info in report["sites"].items():
        for m in info["matched"]:
            expected = sim.loc[m["row"], site]
            assert read.loc[m["obs_name"].lower(), "obsval"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# compare_to_observed and the sensitivity screen use the series too
# ---------------------------------------------------------------------------


@requires_mf6
def test_compare_to_observed_pairs_records_with_their_time_step(tmp_path):
    from groundwater_mcp.tools.postprocess import _compute_obs_fit, _impl_compare_to_observed

    name = _transient_model(tmp_path, ss=1e-3)
    _import(name, _write_obs_csv(tmp_path, name, [("MW1", "2020-01-02", 0.0)]))
    assert _impl_run_simulation(name, silent=True)["success"]
    sim = _obs_csv(name)
    times = _model_output_times(name)
    # Observed = simulated at the early steps: a perfect fit only if each
    # record is compared with its own time step, not the final head.
    rows = [("MW1", _iso(times[i]), float(sim.loc[i, "MW1"])) for i in (1, 2, 3)]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    assert _impl_run_simulation(name, silent=True)["success"]

    out = _impl_compare_to_observed(name)
    assert out["n"] == 3
    assert out["rmse"] == pytest.approx(0.0, abs=1e-6)
    assert sorted(r["time"] for r in out["residuals"]) == pytest.approx(
        [times[i] for i in (1, 2, 3)]
    )
    fit = _compute_obs_fit(name)
    assert fit["rmse"] == pytest.approx(0.0, abs=1e-6)
    assert fit["n"] == 3


@requires_mf6
def test_sensitivity_screen_sees_storage_in_a_transient_series(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_check_parameter_sensitivity

    name = _transient_model(tmp_path, ss=1e-3)
    times = _model_output_times(name)
    rows = [("MW1", _iso(t), 29.8) for t in times]
    _import(name, _write_obs_csv(tmp_path, name, rows))
    res = _impl_setup_calibration(
        name, {"ss": {"target": "sto:ss", "scope": "layer", "layer": 0, "initial": 1e-3}}
    )
    out = _impl_check_parameter_sensitivity(name, {"ss": 1e-3}, res["template_files"])
    print(out)
    # At the final step the drawdown has nearly equilibrated; the transient
    # rows are where Ss shows.
    assert out["parameters"]["ss"]["sensitivity"] > 1e-4, out


# ---------------------------------------------------------------------------
# End to end: GLM recovers K and Ss from a head time series
# ---------------------------------------------------------------------------


@requires_mf6
@requires_pestpp
def test_glm_recovers_k_and_ss_from_a_transient_series(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_glm

    # Ss large enough that the drawdown builds over several 5-day steps
    # (T/S = 400/0.05 m2/d, ~11 d to the CHD edges); a faster aquifer is at
    # equilibrium by the first transient step and leaves Ss unidentifiable.
    truth = _transient_model(tmp_path, "tr_truth", k=8.0, ss=1e-3)
    _import(
        truth,
        _write_obs_csv(tmp_path, truth, [(s, "2020-01-02", 0.0) for s in SITE_CELLS]),
    )
    assert _impl_run_simulation(truth, silent=True)["success"]
    sim = _obs_csv(truth)
    times = _model_output_times(truth)

    rows = [
        (site, _iso(t), float(sim.loc[i, site]))
        for site in SITE_CELLS
        for i, t in enumerate(times)
        if not (site == "MW2" and i % 2 == 0)  # gaps: rows that skip a column
    ]
    name = _transient_model(tmp_path, "tr_cal", k=3.0, ss=3e-3)
    _import(name, _write_obs_csv(tmp_path, name, rows))
    res = _impl_setup_calibration(
        name,
        {
            "k": {"target": "npf:k", "scope": "all", "initial": 3.0},
            "ss": {"target": "sto:ss", "scope": "layer", "layer": 0, "initial": 3e-3},
        },
        noptmax=12,
    )
    assert "error" not in res, res
    assert res["n_observations"] == len(rows)
    assert res["time_series"]["n_matched"] == len(rows)

    out = _impl_run_pestpp_glm(name, res["pst_file"], 1)
    assert "error" not in out, out
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result

    _impl_apply_calibration_result(name, res["pst_file"])
    gwf = get_gwf(name)
    k = np.asarray(gwf.get_package("npf").k.array).reshape(-1)
    ss = np.asarray(gwf.get_package("sto").ss.array).reshape(-1)
    print(f"recovered K {k.mean():.4g} (truth 8), Ss {ss.mean():.4g} (truth 1e-3)")
    assert k.mean() == pytest.approx(8.0, rel=0.05)
    assert ss.mean() == pytest.approx(1e-3, rel=0.1)
