"""PEST++-DA control-file builder (setup_da_control) — cycle tables + da_* options.

Covers the v2 control-file writer used for sequential data assimilation with
``pestpp-da`` v5.2.16: the cycle-table writer, the version-2 round trip, the
state-parameter / IC-template wiring, the populated parameter cycle table, and
the missing-input / single-time-step errors. An end-to-end ``pestpp-da`` run is
included when both binaries are installed.
"""

from __future__ import annotations

import asyncio
import csv
import json
import subprocess
from pathlib import Path

import pyemu
import pytest

from groundwater_mcp.server import mcp

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
    _detect_pestpp_engine,
    _impl_setup_da_control,
    _impl_run_pestpp_da,
    _impl_summarise_da,
    _write_cycle_table,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.workspace import resolve_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OBS_CELLS = {"S1": (0, 0, 1), "S2": (0, 1, 1), "S3": (0, 2, 1)}


def _mf6_available() -> bool:
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


def _pestpp_da_available() -> bool:
    try:
        from groundwater_mcp.tools.calibration import _find_pestpp_binary

        _find_pestpp_binary("pestpp-da")
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")
requires_pestpp_da = pytest.mark.skipif(
    not _pestpp_da_available(), reason="pestpp-da binary not installed"
)


def _register_obs(tmp_path: Path, name: str) -> None:
    csv_path = tmp_path / f"{name}_obs.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cell"])
        for i, (site, cell) in enumerate(_OBS_CELLS.items()):
            writer.writerow([site, "2020-01-01", 30.0 - i, " ".join(str(c) for c in cell)])
    _impl_import_obs_from_csv(
        name,
        str(csv_path),
        "HEAD",
        "site",
        "date",
        "value",
        None,
        None,
        0,
        cellid_col="cell",
    )


def _da_model(tmp_path: Path, name: str = "damodel", nper: int = 1, with_obs: bool = True) -> str:
    """A single-time-step transient DIS model that can host a sequential DA run."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper, [1.0] * nper, [1] * nper, "simple")
    _impl_add_dis_package(name, 1, 3, 3, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    _impl_add_sto_package(name, iconvert=0, ss=1e-4, sy=None, steady_state=[], save_flows=True)
    _impl_add_boundary_package(
        name, "CHD", {"0": [[[0, 0, 0], 40.0], [[0, 2, 2], 10.0]]}, None
    )
    _impl_add_oc_package(name, None, None, None, None)
    if with_obs:
        _register_obs(tmp_path, name)
    return name


def _obs_cycles() -> dict:
    return {
        "S1": {0: 32.0, 1: 33.0},
        "S2": {0: 30.0, 1: 31.0},
        "S3": {0: 28.0, 1: 29.0},
    }


# ---------------------------------------------------------------------------
# Cycle-table writer
# ---------------------------------------------------------------------------


def test_write_cycle_table(tmp_path):
    p = tmp_path / "obs_cycle_tbl.csv"
    _write_cycle_table(p, ["S1", "S2"], [0, 1], {"S1": {0: 12.5, 1: 13.0}, "S2": {1: 9.0}})
    assert p.read_text().splitlines()[0] == ",0,1"
    rows = {ln.split(",")[0]: ln.split(",")[1:] for ln in p.read_text().splitlines()[1:]}
    assert rows["S1"] == ["12.5", "13"]
    assert rows["S2"] == ["", "9"]


# ---------------------------------------------------------------------------
# v2 control file round trip
# ---------------------------------------------------------------------------


def test_setup_da_control_writes_v2_cycle_tables(tmp_path):
    name = _da_model(tmp_path)
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=5,
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_num_reals"]) == "5"
    assert str(pst.pestpp_options["da_observation_cycle_table"]).endswith(".csv")
    assert int(pst.control_data.noptmax) == 1
    # version 2 + cycle column survive the write
    text = Path(res["pst_file"]).read_text()
    assert "version=2" in text.replace(" ", "")
    assert "cycle" in pst.observation_data.columns

    # the returned schema from the brief
    for key in (
        "model",
        "pst_file",
        "template_file",
        "target_file",
        "ic_template_file",
        "cycle_tables",
        "n_observations",
        "n_adjustable_parameters",
        "n_state_parameters",
        "n_cycles",
        "model_command",
        "next_steps",
    ):
        assert key in res, f"missing {key!r} in result"

    assert res["n_observations"] == 3
    assert res["n_state_parameters"] == 3
    assert res["n_cycles"] == 2
    assert res["cycle_tables"]["obs"].endswith(".csv")
    assert res["cycle_tables"]["parameter"].endswith(".csv")

    # obs cycle table has one row per site with the supplied per-cycle values
    obs_tbl = Path(res["cycle_tables"]["obs"]).read_text().splitlines()
    assert obs_tbl[0] == ",0,1"
    rows = {ln.split(",")[0]: ln.split(",")[1:] for ln in obs_tbl[1:]}
    assert rows["S1"] == ["32", "33"]
    assert rows["S3"] == ["28", "29"]


def test_setup_da_control_state_parameters_and_ic_wiring(tmp_path):
    name = _da_model(tmp_path)
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
    )
    assert "error" not in res, res

    # state parameters share the observation names (shared-name state wiring),
    # live in the head_state group and are not Kalman-adjusted.
    pst = pyemu.Pst(res["pst_file"])
    state = pst.parameter_data[pst.parameter_data["pargp"] == "head_state"]
    assert set(state.index) == {"s1", "s2", "s3"}
    assert (state["partrans"] == "none").all()
    assert (state["cycle"] == -1).all()

    # observed sites drive the states; non-zero weights in obs_data.csv
    assert str(pst.pestpp_options["da_use_simulated_states"]).lower() == "true"
    assert (pst.observation_data["weight"] > 0).all()
    assert set(pst.observation_data.index) == {"s1", "s2", "s3"}

    # the IC template targets the external IC array the model reads
    ic_tpl = Path(res["ic_template_file"])
    assert ic_tpl.exists()
    assert ic_tpl.name.endswith(".tpl")
    ins = pst.model_input_data
    assert len(ins) == 2  # K array + IC array
    assert list(ins["cycle"]) == [-1, -1]

    # the model output section points at the MF6 OBS CSV via the pif
    assert len(pst.model_output_data) == 1
    assert pst.model_output_data["model_file"].iloc[0].endswith(".obs.csv")


def test_setup_da_control_populated_parameter_cycle_table(tmp_path):
    name = _da_model(tmp_path)
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        par_cycles={"perlen": {0: 40.0, 1: 100.0}},
        num_reals=4,
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_parameter_cycle_table"]).endswith(".csv")

    lines = Path(res["cycle_tables"]["parameter"]).read_text().splitlines()
    assert lines[0] == ",0,1"
    assert lines[1] == "perlen,40,100"

    forcing = pst.parameter_data.loc["perlen"]
    assert forcing["partrans"] == "fixed"
    assert forcing["pargp"] == "forcing"
    assert int(forcing["cycle"]) == -1

    # a templated TDIS perlen is listed as a model input the DA run rewrites
    in_files = set(pst.model_input_data["pest_file"])
    assert any(f.endswith(".tdis.tpl") for f in in_files)


def test_setup_da_control_accepts_string_cycle_keys(tmp_path):
    """MCP clients often send JSON object keys as strings; normalise them."""
    name = _da_model(tmp_path, name="dastr")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles={
            "S1": {"0": 32.0, "1": 33.0},
            "S2": {"0": 30.0, "1": 31.0},
            "S3": {"0": 28.0, "1": 29.0},
        },
        par_cycles={"perlen": {"0": 40.0, "1": 100.0}},
    )
    assert "error" not in res, res
    lines = Path(res["cycle_tables"]["obs"]).read_text().splitlines()
    assert lines[0] == ",0,1"
    assert lines[1].split(",")[1:] == ["32", "33"]
    assert Path(res["cycle_tables"]["parameter"]).read_text().splitlines()[1] == "perlen,40,100"


def test_setup_da_control_writes_weight_cycle_table_when_given(tmp_path):
    name = _da_model(tmp_path, name="daweight")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        obs_weights={"S1": 4.0, "S2": 2.0},
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_weight_cycle_table"]).endswith(".csv")
    lines = Path(res["cycle_tables"]["weight"]).read_text().splitlines()
    assert lines[0] == ",0,1"
    rows = {ln.split(",")[0]: ln.split(",")[1:] for ln in lines[1:]}
    assert rows["S1"] == ["4", "4"]
    assert rows["S2"] == ["2", "2"]
    assert rows["S3"] == ["1", "1"]

    res2 = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
    )
    assert "da_weight_cycle_table" not in pyemu.Pst(res2["pst_file"]).pestpp_options
    assert "weight" not in res2["cycle_tables"]


def test_setup_da_control_empty_parameter_cycle_table_by_default(tmp_path):
    name = _da_model(tmp_path)
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
    )
    lines = Path(res["cycle_tables"]["parameter"]).read_text().splitlines()
    assert lines == [",0,1"]


# ---------------------------------------------------------------------------
# Prior parameter ensemble (da_parameter_ensemble)
# ---------------------------------------------------------------------------


def test_setup_da_control_draws_prior_ensemble_from_std(tmp_path):
    name = _da_model(tmp_path, name="daprior")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
        prior_std=0.2,
    )
    assert "error" not in res, res
    assert res["prior_ensemble_file"].endswith("_da_prior.csv")

    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_parameter_ensemble"]) == Path(
        res["prior_ensemble_file"]
    ).name

    pe = pyemu.ParameterEnsemble.from_csv(pst, res["prior_ensemble_file"])
    assert pe.shape[0] == 4
    # one column per control-file parameter (K + states + any forcing)
    assert set(pst.parameter_data.index).issubset(set(pe.columns))
    assert "k" in pe.columns
    assert len(set(pe.loc[:, "k"].values.tolist())) > 1  # actually drawn


def test_setup_da_control_uses_explicit_prior_ensemble(tmp_path):
    name = _da_model(tmp_path, name="daprie")
    values = [3.0, 4.0, 6.0, 7.0]
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        prior_ensemble={"k": values},
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_num_reals"]) == "4"
    pe = pyemu.ParameterEnsemble.from_csv(pst, res["prior_ensemble_file"])
    assert pe.shape[0] == 4
    assert list(pe.loc[:, "k"].values) == pytest.approx(values)


def test_setup_da_control_no_prior_ensemble_by_default(tmp_path):
    name = _da_model(tmp_path, name="daprinone")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
    )
    assert "error" not in res, res
    assert "prior_ensemble_file" not in res
    assert "da_parameter_ensemble" not in pyemu.Pst(res["pst_file"]).pestpp_options


def test_setup_da_control_rejects_conflicting_prior_specs(tmp_path):
    name = _da_model(tmp_path, name="dapriconf")
    with pytest.raises(ValueError, match="prior_ensemble"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
            prior_ensemble={"k": [3.0, 4.0]},
            prior_std=0.2,
        )


# ---------------------------------------------------------------------------
# summarise_da — engine detection + DA cycle / posterior outputs
# ---------------------------------------------------------------------------


def _write_da_outputs(ws: Path, case: str) -> None:
    """Synthesise the artifact set ``pestpp-da`` leaves after a 2-cycle run."""
    # final-cycle phi (the same file run_pestpp_da reads)
    (ws / f"{case}.phi.actual.csv").write_text(
        "iteration,total_runs,mean,standard_deviation,min,max,0,1,base\n"
        "0,5,0.41,0.42,0.06,1.13,0.33,0.06,0.36\n"
        "1,42,0.28,0.31,0.04,0.90,0.22,0.04,0.28\n"
    )
    # per-cycle phi: two rows per cycle (iteration 0 = prior, 1 = post-update)
    (ws / f"{case}.global.phi.actual.csv").write_text(
        "cycle,iteration,mean,standard_deviation,min,max,0,1,base\n"
        "0,0,4e+59,5.47e+59,0.008,1e+60,1e+60,0.008,0.07\n"
        "0,1,0.25,0.30,0.008,0.80,0.21,0.008,0.07\n"
        "1,0,0.41,0.42,0.06,1.13,0.33,0.06,0.36\n"
        "1,1,0.28,0.31,0.04,0.90,0.22,0.04,0.28\n"
    )
    # posterior parameter ensemble per cycle: 3 realisations + a base row that
    # is not a realisation and must not enter the posterior statistics
    for cycle, head in ((0, 7.5), (1, 8.5)):
        (ws / f"{case}.global.{cycle}.pe.csv").write_text(
            "real_name,k,h_0_1\n"
            f"0,1.0,{head}\n"
            f"1,2.0,{head}\n"
            f"2,3.0,{head}\n"
            f"base,9.0,{head}\n"
        )
    # a per-cycle iteration par.csv the real run leaves behind — without the DA
    # check preceding the IES check this would read as an IES run
    (ws / f"{case}.0.par.csv").write_text("real_name,k\n0,1.0\n1,2.0\n")
    # latest base residuals (cycle 1, iteration 1)
    (ws / f"{case}.1.1.base.rei").write_text(
        " MODEL OUTPUTS AT END OF OPTIMISATION ITERATION NO. 1:-\n\n\n"
        " Name        Group      Measured      Modelled      Residual      Weight\n"
        " s1          head       10.0          9.0           1.0           1.0\n"
        " s2          head       20.0          18.0          2.0           1.0\n"
    )


def _da_summary_workspace(tmp_path: Path, name: str) -> tuple[str, Path, str]:
    """A DA-ready model plus the synthesised pestpp-da output artifacts."""
    model = _da_model(tmp_path, name=name)
    res = _impl_setup_da_control(
        model,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res
    ws = resolve_workspace(model)
    case = Path(res["pst_file"]).stem
    _write_da_outputs(ws, case)
    return model, ws, res["pst_file"]


def test_detect_pestpp_engine_returns_da(tmp_path):
    _, ws, pst_file = _da_summary_workspace(tmp_path, "dadetect")
    assert _detect_pestpp_engine(ws, Path(pst_file).stem) == "da"


def test_summarise_da_reports_per_cycle_phi_and_posterior(tmp_path):
    model, _ws, pst_file = _da_summary_workspace(tmp_path, "dasum")
    summary = _impl_summarise_da(model, pst_file)

    assert summary["engine"] == "da"
    assert [c["cycle"] for c in summary["cycles"]] == [0, 1]
    # per-cycle phi is the post-update (iteration 1) ensemble mean, never the
    # 4e59 prior row of cycle 0
    assert summary["cycles"][0]["phi"] == pytest.approx(0.25)
    assert summary["cycles"][1]["phi"] == pytest.approx(0.28)
    assert summary["final_phi_mean"] == pytest.approx(0.28)
    assert summary["final_phi_std"] == pytest.approx(0.31)

    # posterior statistics come from the final-cycle ensemble; the base row is
    # excluded (mean would be 3.75 if it were counted)
    k_stats = summary["parameter_ensemble"]["k"]
    assert k_stats["mean"] == pytest.approx(2.0)
    assert k_stats["std"] == pytest.approx(0.816496580927726)
    assert k_stats["min"] == pytest.approx(1.0)
    assert k_stats["max"] == pytest.approx(3.0)
    assert k_stats["n"] == 3

    # residuals come from the latest per-cycle base .rei
    assert summary["residual_statistics"]["n_observations"] == 2
    assert summary["residual_statistics"]["rmse"] == pytest.approx(2.5**0.5)
    assert summary["n_residuals_total"] == 2
    assert {r["obs_name"] for r in summary["residuals"]} == {"s1", "s2"}


def test_summarise_da_missing_run_outputs_fails_loudly(tmp_path):
    """A PST with no DA run outputs must error, not return an empty success."""
    model = _da_model(tmp_path, name="danotrun")
    res = _impl_setup_da_control(
        model,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res

    # no <case>.global.phi.actual.csv and no <case>.global.<cycle>.pe.csv
    with pytest.raises(FileNotFoundError, match="run_pestpp_da"):
        _impl_summarise_da(model, res["pst_file"])

    # the tool envelope reports the missing output, never a success dict
    payload = json.loads(
        asyncio.run(
            mcp.call_tool("summarise_da", {"model": model, "pst_file": res["pst_file"]})
        )[0].text
    )
    assert payload["error"] is True
    assert payload["code"] == "OUTPUT_FILE_MISSING"


def test_summarise_da_without_ensemble_but_with_cycle_phi(tmp_path):
    """A partial (no-update-style) run is summarised, not called 'not run'."""
    model, ws, pst_file = _da_summary_workspace(tmp_path, "daphi")
    case = Path(pst_file).stem
    for pe in ws.glob(f"{case}.global.*.pe.csv"):
        pe.unlink()
    summary = _impl_summarise_da(model, pst_file)
    assert [c["cycle"] for c in summary["cycles"]] == [0, 1]
    assert summary["final_phi_mean"] == pytest.approx(0.28)
    assert summary["parameter_ensemble"] == {}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_setup_da_control_requires_single_time_step(tmp_path):
    name = _da_model(tmp_path, name="da2step", nper=2)
    with pytest.raises(ValueError, match="NPER=1"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
        )


def test_setup_da_control_requires_registered_observations(tmp_path):
    name = _da_model(tmp_path, name="danobs", with_obs=False)
    with pytest.raises(ValueError, match="import_obs_from_csv"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
        )


def test_setup_da_control_requires_every_site_obs_cycles(tmp_path):
    name = _da_model(tmp_path, name="damissing")
    with pytest.raises(ValueError, match="S3"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles={"S1": {0: 32.0, 1: 33.0}, "S2": {0: 30.0, 1: 31.0}},
        )


def test_setup_da_control_rejects_unknown_obs_cycles(tmp_path):
    name = _da_model(tmp_path, name="daextra")
    obs = _obs_cycles()
    obs["S9"] = {0: 1.0}
    with pytest.raises(ValueError, match="S9"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=obs,
        )


# ---------------------------------------------------------------------------
# Binary-backed validation
# ---------------------------------------------------------------------------


@requires_pestpp_da
def test_written_control_file_is_accepted_by_pestpp_da(tmp_path):
    """pestpp-da must accept the *control file* (cycle tables + da_* options).

    The forward command is replaced by a fake so only the control-file parse is
    exercised; the assertion is that the failure (if any) is not an unknown
    control-data keyword or a missing cycle-table file.
    """
    name = _da_model(tmp_path, name="daparse")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res
    pst_path = Path(res["pst_file"])
    pst = pyemu.Pst(str(pst_path))
    pst.model_command = ["python -c \"pass\""]
    pst.write(str(pst_path), version=2)

    ws = resolve_workspace(name)
    from groundwater_mcp.tools.calibration import _find_pestpp_binary

    proc = subprocess.run(
        [_find_pestpp_binary("pestpp-da"), pst_path.name],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    assert "control data keyword lines were not accepted" not in output
    assert "DA_OBSERVATION_CYCLE_TABLE" not in output
    assert "DA_PARAMETER_CYCLE_TABLE" not in output


@requires_mf6
@requires_pestpp_da
def test_setup_da_control_end_to_end(tmp_path):
    """A real sequential DA run: >=2 cycles, finite phi, state carried forward."""
    name = _da_model(tmp_path, name="dae2e")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=5,
        noptmax=1,
    )
    assert "error" not in res, res

    run = _impl_run_pestpp_da(name, res["pst_file"], num_reals=5)
    assert run["converged"], run
    assert run["cycles"] >= 2, run
    assert run["final_phi_mean"] is not None
    assert run["final_phi_mean"] == run["final_phi_mean"]  # not NaN


@requires_mf6
@requires_pestpp_da
def test_setup_da_control_prior_ensemble_end_to_end(tmp_path):
    """pestpp-da accepts and reads the caller-supplied da_parameter_ensemble."""
    name = _da_model(tmp_path, name="dae2eprior")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
        prior_std=0.2,
    )
    assert "error" not in res, res
    run = _impl_run_pestpp_da(name, res["pst_file"], num_reals=4)
    assert run["converged"], run
    assert run["cycles"] >= 2, run
    ws = resolve_workspace(name)
    rec_files = list(ws.glob("*.rec"))
    assert rec_files, "pestpp-da did not write a .rec file"
    rec = rec_files[0].read_text().lower()

    # pestpp-da echoes the whole control file into .rec, so the filename alone
    # proves nothing. Require the explicit load line...
    prior_name = Path(res["prior_ensemble_file"]).name.lower()
    assert f"loading par ensemble from csv file {prior_name}" in rec

    # ...and prove the ensemble it actually used carries the supplied values
    # (an ignored option would make pestpp-da draw internally instead).
    pst = pyemu.Pst(res["pst_file"])
    case = Path(res["pst_file"]).stem
    used_pe = pyemu.ParameterEnsemble.from_csv(pst, ws / f"{case}.global.prior.pe.csv")
    supplied_pe = pyemu.ParameterEnsemble.from_csv(pst, res["prior_ensemble_file"])
    assert list(used_pe.columns) == list(supplied_pe.columns)
    supplied_k = [float(v) for v in supplied_pe.loc[:, "k"].values]
    used_k = {
        str(r): float(v)
        for r, v in zip(used_pe.index, used_pe.loc[:, "k"].values)
    }
    used_reals = [r for r in used_k if r != "base"]
    assert used_reals, "pestpp-da wrote no prior realisations"
    for real in used_reals:
        value = used_k[real]
        assert any(abs(value - s) <= 1e-4 * max(1.0, abs(s)) for s in supplied_k), (
            f"prior realisation {real!r} k={value} is not one of the supplied "
            f"values {supplied_k}"
        )


@requires_mf6
@requires_pestpp_da
def test_setup_da_control_populated_parameter_cycle_table_end_to_end(tmp_path):
    """The populated parameter cycle table drives the written TDIS perlen."""
    name = _da_model(tmp_path, name="dae2ecyc")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        par_cycles={"perlen": {0: 40.0, 1: 100.0}},
        num_reals=5,
    )
    assert "error" not in res, res
    run = _impl_run_pestpp_da(name, res["pst_file"], num_reals=5)
    assert run["converged"], run

    # the final written TDIS holds cycle 1's value (100 d)
    ws = resolve_workspace(name)
    tdis_text = (ws / "mfsim.tdis").read_text()
    perlen_line = next(
        ln for ln in tdis_text.splitlines() if "perioddata" not in ln and "1.0" in ln
    )
    assert float(perlen_line.split()[0]) == pytest.approx(100.0)
