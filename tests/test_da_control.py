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
import sys
from pathlib import Path

import numpy as np
import pyemu
import pytest

from groundwater_mcp.server import mcp

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_disu_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_add_sto_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.calibration import (
    _da_cell_flat_index,
    _detect_pestpp_engine,
    _impl_setup_da_control,
    _impl_run_pestpp_da,
    _impl_summarise_da,
    _write_cycle_table,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.model_store import (
    flush_model,
    get_gwf,
    read_meta,
    write_meta,
)
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


def _mf6_binary_has_space() -> bool:
    """True when the MF6 binary itself lives under a space-containing directory.

    ``_needs_forward_wrapper`` keys off the **binary** path (Task 9), so on such
    a host a wrapper is legitimately generated and a "direct command" assertion
    would false-fail.
    """
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        return " " in _find_mf6_binary()
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")
requires_space_free_mf6 = pytest.mark.skipif(
    _mf6_binary_has_space(),
    reason="MF6 binary path contains a space; a wrapper is expected (see _needs_forward_wrapper)",
)
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


def _da_model(
    tmp_path: Path,
    name: str = "damodel",
    nper: int = 1,
    with_obs: bool = True,
    spatial_dir: str | None = None,
    k: float | np.ndarray | None = None,
) -> str:
    """A single-time-step transient DIS model that can host a sequential DA run.

    ``spatial_dir`` inserts an extra (space-containing) path component so a test
    can exercise a workspace whose path contains a space. ``k`` overrides the
    uniform 5.0 m/d K field (used by the multiplier-scope test to prove the
    spatial pattern survives).
    """
    ws = str(tmp_path / (spatial_dir or "") / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper, [1.0] * nper, [1] * nper, "simple")
    _impl_add_dis_package(name, 1, 3, 3, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(
        name, icelltype=0, k=5.0 if k is None else k, k33=None, save_flows=True
    )
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
# DISU helpers
# ---------------------------------------------------------------------------

# 0-based nodes handed to import_obs_from_csv; it stores them 1-based.
_DISU_OBS_NODES = {"S1": 0, "S2": 2}


def _line_disu_connectivity(nnodes: int) -> tuple[list[int], list[int]]:
    """IAC/JA for an ``nnodes``-long 1-D chain (first connection is the node itself)."""
    iac = [2] + [3] * (nnodes - 2) + [2]
    ja: list[int] = []
    for node in range(nnodes):
        ja.append(node)
        if node > 0:
            ja.append(node - 1)
        if node < nnodes - 1:
            ja.append(node + 1)
    return iac, ja


def _register_disu_obs(tmp_path: Path, name: str) -> None:
    csv_path = tmp_path / f"{name}_obs.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cellid"])
        for i, (site, node) in enumerate(_DISU_OBS_NODES.items()):
            writer.writerow([site, "2020-01-01", 0.6 - 0.2 * i, node])
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
        cellid_col="cellid",
    )


def _disu_da_model(
    tmp_path: Path, name: str = "disudamodel", nnodes: int = 5, with_obs: bool = True
) -> str:
    """A 5-node 1-D DISU model with a CHD gradient and one DA time step.

    ``k`` is deliberately heterogeneous so the transactional test can tell a
    rewired (uniform) field from the original one.
    """
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    iac, ja = _line_disu_connectivity(nnodes)
    _impl_add_disu_package(
        name,
        nnodes,
        len(ja),
        [0.0] * nnodes,
        [-10.0] * nnodes,
        area=[100.0] * nnodes,
        iac=iac,
        ja=ja,
    )
    _impl_add_npf_package(
        name,
        icelltype=0,
        k=[5.0, 10.0, 20.0, 40.0, 80.0][:nnodes],
        k33=None,
        save_flows=True,
    )
    _impl_add_ic_package(name, strt=0.0)
    _impl_add_boundary_package(name, "CHD", {"0": [[0, 1.0], [nnodes - 1, 0.0]]}, None)
    _impl_add_oc_package(name, None, None, None, None)
    if with_obs:
        _register_disu_obs(tmp_path, name)
    flush_model(name)
    return name


def _disu_obs_cycles() -> dict:
    return {"S1": {0: 0.6, 1: 0.7}, "S2": {0: 0.4, 1: 0.5}}


def _assert_model_not_rewired(name: str, k_before) -> None:
    """A rejected setup must not have rewired NPF k or IC strt."""
    ws = resolve_workspace(name)
    gwf = get_gwf(name)
    gname = gwf.name
    assert not (ws / f"{gname}_k.dat").exists()
    assert not (ws / f"{gname}_k.dat.tpl").exists()
    assert not (ws / f"{gname}_strt.dat").exists()
    assert not (ws / f"{gname}_strt.dat.tpl").exists()
    assert f"{gname}_k.dat" not in (ws / f"{gname}.npf").read_text().lower()
    assert np.asarray(gwf.get_package("npf").k.array, dtype=float) == pytest.approx(k_before)


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


def test_summarise_da_second_run_with_fewer_cycles_is_isolated(tmp_path):
    """A second DA run in a reused workspace must report ITS OWN posterior and
    residuals, not the first run's higher-cycle leftovers (6d rerun-4 finding
    F2: the control returned run-1's k=10.0 and 2018-12-20 residuals)."""
    model = _da_model(tmp_path, name="daiso")
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

    # run 1 (6 cycles, 0..5) left its final-cycle ensemble and residuals behind
    (ws / f"{case}.global.5.pe.csv").write_text(
        "real_name,k,h\n0,10.0,1\n1,10.0,1\nbase,10.0,1\n"
    )
    (ws / f"{case}.5.1.base.rei").write_text(
        " MODEL OUTPUTS AT END OF OPTIMISATION ITERATION NO. 1:-\n\n\n"
        " Name        Group      Measured      Modelled      Residual      Weight\n"
        " s1          head       99.0          90.0          9.0           1.0\n"
    )

    # run 2 (3 cycles, 0..2) overwrote the cycle phi file and wrote its own
    # lower-cycle ensemble + residuals; run-1's cycle-5 files are now stale.
    (ws / f"{case}.global.phi.actual.csv").write_text(
        "cycle,iteration,mean,standard_deviation,min,max,0\n"
        "0,0,5.0,4.0,1.0,9.0,5.0\n"
        "0,1,4.0,3.0,1.0,7.0,4.0\n"
        "1,0,3.0,2.0,1.0,5.0,3.0\n"
        "1,1,2.0,1.0,1.0,3.0,2.0\n"
        "2,0,1.5,0.5,1.0,2.0,1.5\n"
        "2,1,1.0,0.2,0.9,1.1,1.0\n"
    )
    (ws / f"{case}.global.2.pe.csv").write_text(
        "real_name,k,h\n0,2.0,1\n1,2.0,1\n2,2.0,1\nbase,2.0,1\n"
    )
    (ws / f"{case}.2.1.base.rei").write_text(
        " MODEL OUTPUTS AT END OF OPTIMISATION ITERATION NO. 1:-\n\n\n"
        " Name        Group      Measured      Modelled      Residual      Weight\n"
        " s1          head       32.0          30.0          2.0           1.0\n"
        " s2          head       30.0          29.0          1.0           1.0\n"
    )

    summary = _impl_summarise_da(model, res["pst_file"])

    assert [c["cycle"] for c in summary["cycles"]] == [0, 1, 2]
    assert summary["final_phi_mean"] == pytest.approx(1.0)
    # run-2 posterior (2.0), not run-1's stale cycle-5 ensemble (10.0)
    assert summary["parameter_ensemble"]["k"]["mean"] == pytest.approx(2.0)
    assert summary["parameter_ensemble"]["k"]["n"] == 3
    # run-2 residuals (2 observations, 32/30), not run-1's stale 99/90
    assert summary["residual_statistics"]["n_observations"] == 2
    assert {r["obs_name"] for r in summary["residuals"]} == {"s1", "s2"}
    assert max(r["measured"] for r in summary["residuals"]) == pytest.approx(32.0)


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


def test_setup_da_control_rejects_par_cycles_colliding_with_adjustable_parameter(tmp_path):
    """A par_cycles key naming an adjustable K parameter is a hard error.

    Otherwise the PST marks K adjustable while the parameter cycle table
    overrides it every cycle — a silent wrong result.
    """
    name = _da_model(tmp_path, name="dacol")
    parameterisation = {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    with pytest.raises(ValueError, match=r"par_cycles key\(s\) \['k'\] collide"):
        _impl_setup_da_control(
            name,
            parameterisation,
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
            par_cycles={"k": {0: 4.0, 1: 6.0}},
        )

    # the tool envelope reports INVALID_INPUT, naming the parameter
    payload = json.loads(
        asyncio.run(
            mcp.call_tool(
                "setup_da_control",
                {
                    "model": name,
                    "parameterisation": parameterisation,
                    "cycles": [0, 1],
                    "obs_cycles": _obs_cycles(),
                    "par_cycles": {"k": {"0": 4.0, "1": 6.0}},
                },
            )
        )[0].text
    )
    assert payload["error"] is True
    assert payload["code"] == "INVALID_INPUT"
    assert "k" in payload["message"]


def test_setup_da_control_rejects_use_simulated_states_false(tmp_path):
    """v5.2.16 needs final-to-initial state linkages the tool does not emit,
    so False yields a PST rejected at run time — reject it up front."""
    name = _da_model(tmp_path, name="danostate")
    parameterisation = {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    with pytest.raises(ValueError, match="use_simulated_states=False"):
        _impl_setup_da_control(
            name,
            parameterisation,
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
            use_simulated_states=False,
        )

    payload = json.loads(
        asyncio.run(
            mcp.call_tool(
                "setup_da_control",
                {
                    "model": name,
                    "parameterisation": parameterisation,
                    "cycles": [0, 1],
                    "obs_cycles": _obs_cycles(),
                    "use_simulated_states": False,
                },
            )
        )[0].text
    )
    assert payload["error"] is True
    assert payload["code"] == "INVALID_INPUT"
    assert "use_simulated_states" in payload["message"]


# ---------------------------------------------------------------------------
# DISU grids (Task 7)
# ---------------------------------------------------------------------------


def test_da_cell_flat_index_maps_disu_node_and_rejects_out_of_bounds(tmp_path):
    """A stored DISU cell id is a 1-based node; the flat index is node - 1."""
    name = _disu_da_model(tmp_path, "disuidx", with_obs=False)
    assert _da_cell_flat_index(name, 5) == 4  # bare int (the stored form)
    assert _da_cell_flat_index(name, [5]) == 4  # 1-element list
    assert _da_cell_flat_index(name, (5,)) == 4  # 1-element tuple
    assert _da_cell_flat_index(name, 1) == 0  # first node
    with pytest.raises(ValueError, match="out of bounds"):
        _da_cell_flat_index(name, 6)  # 1-based 6 -> flat 5 on a 5-node grid
    with pytest.raises(ValueError, match="out of bounds"):
        _da_cell_flat_index(name, 0)  # 1-based nodes start at 1
    with pytest.raises(ValueError, match="1-based node"):
        _da_cell_flat_index(name, [1, 2])


def test_setup_da_control_disu_writes_v2_state_parameters(tmp_path):
    """setup_da_control produces a v2 DA PST on a DISU grid (the 6d blocker)."""
    name = _disu_da_model(tmp_path, "disuda")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_disu_obs_cycles(),
        num_reals=4,
        noptmax=1,
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    assert str(pst.pestpp_options["da_num_reals"]) == "4"
    assert str(pst.pestpp_options["da_observation_cycle_table"]).endswith(".csv")
    assert str(pst.pestpp_options["da_use_simulated_states"]).lower() == "true"
    text = Path(res["pst_file"]).read_text()
    assert "version=2" in text.replace(" ", "")
    assert "cycle" in pst.observation_data.columns

    # one head_state parameter per registered site, sharing the observation name
    state = pst.parameter_data[pst.parameter_data["pargp"] == "head_state"]
    assert set(state.index) == {"s1", "s2"}
    assert (state["partrans"] == "none").all()
    assert res["n_state_parameters"] == 2
    assert res["n_observations"] == 2
    assert res["n_cycles"] == 2

    # the state-augmented IC template targets the external strt array
    assert Path(res["ic_template_file"]).exists()
    ic_tpl_text = Path(res["ic_template_file"]).read_text()
    assert ic_tpl_text.count("~") >= 2  # state tokens present
    in_files = set(pst.model_input_data["pest_file"])
    assert any(f.endswith(".tpl") for f in in_files)


def test_setup_da_control_disu_out_of_bounds_site_is_transactional(tmp_path):
    """A rejected DISU site must not leave the model rewired.

    import_obs_from_csv validates node ids, so an out-of-bounds site is written
    into the model metadata directly — exactly the stale/edited meta a real
    workspace can carry. The failed call must not have rewired NPF k (the 6d
    run log's secondary finding: a failed setup left uniform K=1).
    """
    name = _disu_da_model(tmp_path, "disutxn")
    meta = read_meta(name)
    meta["observations"]["sites"][1]["cellid"] = 99
    write_meta(name, meta)

    k_before = np.asarray(get_gwf(name).get_package("npf").k.array, dtype=float).copy()
    with pytest.raises(ValueError, match="out of bounds"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_disu_obs_cycles(),
        )

    _assert_model_not_rewired(name, k_before)


def test_setup_da_control_rejects_conflicting_prior_before_rewiring(tmp_path):
    """A conflicting prior spec must be rejected before the K rewire.

    ``prior_ensemble`` + ``prior_std`` is rejected inside the prior writer, but
    the check is now run up front so the failed call cannot leave NPF reading
    uniform ``k`` from ``<gwf>_k.dat``.
    """
    name = _da_model(tmp_path, name="datxnprior")
    flush_model(name)
    k_before = np.asarray(get_gwf(name).get_package("npf").k.array, dtype=float).copy()
    with pytest.raises(ValueError, match="prior_ensemble"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
            prior_ensemble={"k": [3.0, 4.0]},
            prior_std=0.2,
        )
    _assert_model_not_rewired(name, k_before)


def test_setup_da_control_rejects_unknown_weight_before_rewiring(tmp_path):
    """An unknown obs_weights site must be rejected before the K rewire."""
    name = _da_model(tmp_path, name="datxnweight")
    flush_model(name)
    k_before = np.asarray(get_gwf(name).get_package("npf").k.array, dtype=float).copy()
    with pytest.raises(ValueError, match="obs_weights"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
            obs_weights={"S9": 4.0},
        )
    _assert_model_not_rewired(name, k_before)



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


@requires_space_free_mf6
@requires_mf6
def test_setup_da_control_space_workspace_uses_space_free_command(tmp_path):
    """Task 9: a space-containing workspace must not force a wrapper command.

    pestpp runs the model command with the workspace as its working directory,
    so a space in the workspace path never enters the command line. Emitting a
    Python-wrapper command instead (``"<venv python>" ...\\gwmcp_run_<model>.py``)
    cost two extra process launches per realisation and left a space in the
    command line (the venv interpreter path) — unnecessary, and it also baked
    the absolute workspace into the wrapper. (It was launchable; see the Task 9
    report §1b.)

    Skipped when the MF6 *binary* path itself contains a space: there a wrapper
    is legitimately expected (``_needs_forward_wrapper``).
    """
    from groundwater_mcp.tools.calibration import _find_mf6_binary, _needs_forward_wrapper

    name = _da_model(tmp_path, name="daspace", spatial_dir="space dir")
    assert " " in str(resolve_workspace(name)), "fixture must contain a space"

    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res
    assert not _needs_forward_wrapper(name), "workspace space alone must not need a wrapper"

    command = pyemu.Pst(res["pst_file"]).model_command
    assert command == [_find_mf6_binary()], command
    assert " " not in command[0], command
    assert "gwmcp_run_" not in command[0], command


@requires_mf6
def test_setup_da_control_multiplier_scope_preserves_base_k(tmp_path):
    """scope="multiplier" keeps ONE adjustable factor over the existing K
    pattern instead of replacing the heterogeneous field with one uniform
    value (the 6d rerun-5 uniform-K collapse / 31,522-token timeout)."""
    base = np.array([[[1.0, 2.0, 4.0], [8.0, 16.0, 32.0], [64.0, 128.0, 256.0]]])
    name = _da_model(tmp_path, name="damult", k=base)
    res = _impl_setup_da_control(
        name,
        {
            "k_mult": {
                "target": "npf:k",
                "scope": "multiplier",
                "initial": 1.0,
                "lower_factor": 0.2,
                "upper_factor": 5.0,
            }
        },
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 1
    assert res["n_state_parameters"] == 3

    ws = resolve_workspace(name)
    gwf_name = get_gwf(name).name

    # the K template holds exactly one token (the multiplier file), not 9
    tpl_lines = Path(res["template_file"]).read_text().splitlines()
    assert tpl_lines[0].strip() == "ptf ~"
    assert len(tpl_lines) == 2, tpl_lines
    assert "k_mult" in tpl_lines[1]
    assert len(tpl_lines[1]) - 2 >= 15

    pst = pyemu.Pst(res["pst_file"])
    k_pars = pst.parameter_data[pst.parameter_data["pargp"] == "k"]
    assert list(k_pars.index) == ["k_mult"]
    assert float(k_pars.loc["k_mult", "parlbnd"]) == pytest.approx(0.2)
    assert float(k_pars.loc["k_mult", "parubnd"]) == pytest.approx(5.0)
    # the multiplier template is the K input of the PST
    assert Path(res["template_file"]).name in set(pst.model_input_data["pest_file"])

    # one all-cells zone; at factor 1.0 the written K equals the base pattern
    assert list(np.loadtxt(ws / f"{gwf_name}_k_zone.dat", dtype=int)) == [1] * 9
    assert (ws / f"{gwf_name}_k_base.dat").exists()
    np.testing.assert_allclose(
        np.loadtxt(ws / f"{gwf_name}_k.dat"), base.reshape(-1)
    )

    # the routed forward wrapper multiplies the base field: factor 2 doubles it
    np.savetxt(ws / f"{gwf_name}_k_mult.dat", np.array([2.0]), fmt="%.10g")
    proc = subprocess.run(
        [sys.executable, res["forward_wrapper"]],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    np.testing.assert_allclose(
        np.loadtxt(ws / f"{gwf_name}_k.dat"), base.reshape(-1) * 2.0
    )


@requires_mf6
def test_multiplier_forward_command_is_space_free_and_stdlib_only(tmp_path):
    """The multiplier scope ALWAYS needs a wrapper, so its model_command must
    stay launchable by pestpp on Windows: a space-free interpreter and a
    stdlib-only wrapper.

    On this host the venv interpreter is ``D:\\Claude Projects\\...\\.venv\\
    Scripts\\python.exe`` — space-containing — and pestpp cannot launch a
    space-containing executable path (its child freezes before numpy is even
    imported and pestpp-da spins at 100 % CPU: 6d rerun-6, 4/4 attempts). The
    space-free base interpreter exists but has no numpy, so the wrapper cannot
    import it.
    """
    from groundwater_mcp.tools.calibration import _space_free_interpreter

    space_free = _space_free_interpreter()
    if space_free is None:
        pytest.skip("no space-free Python interpreter on this host")

    base = np.array([[[1.0, 2.0, 4.0], [8.0, 16.0, 32.0], [64.0, 128.0, 256.0]]])
    name = _da_model(tmp_path, name="dacmd", k=base)
    res = _impl_setup_da_control(
        name,
        {"k_mult": {"target": "npf:k", "scope": "multiplier", "initial": 1.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res

    body = Path(res["forward_wrapper"]).read_text()
    assert "numpy" not in body, body

    command = pyemu.Pst(res["pst_file"]).model_command
    assert len(command) == 1, command
    first_token = command[0].split()[0]
    assert first_token == space_free, command
    assert " " not in first_token, command

    # the space-free interpreter (no numpy) can actually run the wrapper
    ws = resolve_workspace(name)
    gwf_name = get_gwf(name).name
    np.savetxt(ws / f"{gwf_name}_k_mult.dat", np.array([2.0]), fmt="%.10g")
    proc = subprocess.run(
        [space_free, res["forward_wrapper"]],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    np.testing.assert_allclose(
        np.loadtxt(ws / f"{gwf_name}_k.dat"), base.reshape(-1) * 2.0
    )


def test_setup_da_control_multiplier_rejects_mixed_scope(tmp_path):
    """A multiplier spec cannot be mixed with all/layer/cells."""
    name = _da_model(tmp_path, name="damix")
    with pytest.raises(ValueError, match="multiplier"):
        _impl_setup_da_control(
            name,
            {
                "k_mult": {"target": "npf:k", "scope": "multiplier", "initial": 1.0},
                "k_all": {"target": "npf:k", "scope": "all", "initial": 5.0},
            },
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
        )


@requires_mf6
def test_setup_da_control_multiplier_scope_disu_one_token(tmp_path):
    """scope="multiplier" works on a DISU grid (the holdout's grid type) and
    still emits a one-token K template over an all-cells zone."""
    name = _disu_da_model(tmp_path, "disumult", nnodes=5)
    res = _impl_setup_da_control(
        name,
        {
            "k_mult": {
                "target": "npf:k",
                "scope": "multiplier",
                "initial": 1.0,
                "lower_factor": 0.2,
                "upper_factor": 5.0,
            }
        },
        cycles=[0, 1],
        obs_cycles=_disu_obs_cycles(),
        num_reals=3,
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 1
    ws = resolve_workspace(name)
    gwf_name = get_gwf(name).name
    tpl_lines = Path(res["template_file"]).read_text().splitlines()
    assert len(tpl_lines) == 2
    assert "k_mult" in tpl_lines[1]
    assert list(np.loadtxt(ws / f"{gwf_name}_k_zone.dat", dtype=int)) == [1] * 5
    base = np.array([5.0, 10.0, 20.0, 40.0, 80.0])
    np.testing.assert_allclose(np.loadtxt(ws / f"{gwf_name}_k.dat"), base)


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


# ---------------------------------------------------------------------------
# Task 8 — physical state-parameter bounds, clipped prior draws, single flush
# ---------------------------------------------------------------------------


def _register_obs_rows(tmp_path: Path, name: str, rows: list) -> None:
    """Register observations from explicit ``(site, date, value, DIS cell)`` rows."""
    csv_path = tmp_path / f"{name}_obs_multi.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "cell"])
        for site, date, value, cell in rows:
            writer.writerow([site, date, value, " ".join(str(c) for c in cell)])
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


def _state_params(res: dict):
    pst = pyemu.Pst(res["pst_file"])
    return pst, pst.parameter_data[pst.parameter_data["pargp"] == "head_state"]


def test_setup_da_control_state_bounds_from_obs_spread(tmp_path):
    """State bounds are head-scale (strt +/- observed spread), never +/-1e6."""
    name = _da_model(tmp_path, name="daspread", with_obs=False)
    _register_obs_rows(
        tmp_path,
        name,
        [
            ("S1", "2020-01-01", 25.0, (0, 0, 1)),
            ("S1", "2020-01-02", 35.0, (0, 0, 1)),  # spread 10 m
            ("S2", "2020-01-01", 25.0, (0, 1, 1)),
            ("S2", "2020-01-02", 26.0, (0, 1, 1)),  # spread 1 m -> floored at 5
            ("S3", "2020-01-01", 25.0, (0, 2, 1)),  # <2 values -> default 10
        ],
    )
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
    )
    assert "error" not in res, res
    _, state = _state_params(res)

    # shipped strt is 25 m; the bound is the site's observed spread
    assert state.loc["s1", "parlbnd"] == pytest.approx(25.0 - 10.0)
    assert state.loc["s1", "parubnd"] == pytest.approx(25.0 + 10.0)
    assert state.loc["s2", "parlbnd"] == pytest.approx(25.0 - 5.0)
    assert state.loc["s2", "parubnd"] == pytest.approx(25.0 + 5.0)
    assert state.loc["s3", "parlbnd"] == pytest.approx(25.0 - 10.0)
    assert state.loc["s3", "parubnd"] == pytest.approx(25.0 + 10.0)

    # finite and head-scale, not the +/-1e6 relative-change default
    assert np.isfinite(state["parlbnd"]).all() and np.isfinite(state["parubnd"]).all()
    assert (state["parubnd"] - state["parlbnd"]).max() <= 100.0

    # the per-site bound actually used is reported back
    assert res["state_bounds"]["S1"] == pytest.approx(10.0)
    assert res["state_bounds"]["S2"] == pytest.approx(5.0)
    assert res["state_bounds"]["S3"] == pytest.approx(10.0)


def test_setup_da_control_state_bound_reaches_observed_mean(tmp_path):
    """A bound must cover the shift from strt to the observed mean, not just
    the spread floor — rerun-2 needed 1-8 m state moves."""
    name = _da_model(tmp_path, name="daoffset", with_obs=False)
    _register_obs_rows(
        tmp_path,
        name,
        [
            ("S1", "2020-01-01", 10.0, (0, 0, 1)),
            ("S1", "2020-01-02", 12.0, (0, 0, 1)),  # mean 11, spread 2, strt 25
            ("S2", "2020-01-01", 25.0, (0, 1, 1)),
            ("S2", "2020-01-02", 26.0, (0, 1, 1)),  # mean 25.5, spread 1
            ("S3", "2020-01-01", 25.0, (0, 2, 1)),
            ("S3", "2020-01-02", 25.0, (0, 2, 1)),  # mean == strt, spread 0
        ],
    )
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
    )
    assert "error" not in res, res
    _, state = _state_params(res)

    # S1: the bound reaches the observed level (offset 14 dominates spread 2 and
    # the 5 m floor), so the state can move from 25 down to the 11 m evidence.
    assert res["state_bounds"]["S1"] == pytest.approx(14.0)
    assert state.loc["s1", "parlbnd"] == pytest.approx(25.0 - 14.0)
    assert state.loc["s1", "parubnd"] == pytest.approx(25.0 + 14.0)
    assert state.loc["s1", "parlbnd"] <= 11.0  # reaches the observed mean

    # S2: offset 0.5 and spread 1 both below the floor -> 5 m
    assert res["state_bounds"]["S2"] == pytest.approx(5.0)
    # S3: offset 0, spread 0 -> floor
    assert res["state_bounds"]["S3"] == pytest.approx(5.0)


def test_setup_da_control_state_head_bound_override(tmp_path):
    """state_head_bound overrides the spread-derived bound for every site."""
    name = _da_model(tmp_path, name="daover")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
        state_head_bound=3.0,
    )
    assert "error" not in res, res
    _, state = _state_params(res)
    assert state.loc["s1", "parlbnd"] == pytest.approx(25.0 - 3.0)
    assert state.loc["s1", "parubnd"] == pytest.approx(25.0 + 3.0)
    widths = (state["parubnd"] - state["parlbnd"]).to_numpy(dtype=float)
    assert np.allclose(widths, 6.0)
    assert all(res["state_bounds"][s] == pytest.approx(3.0) for s in ("S1", "S2", "S3"))


def test_setup_da_control_rejects_non_positive_state_head_bound(tmp_path):
    name = _da_model(tmp_path, name="dabadbound")
    flush_model(name)
    k_before = np.asarray(get_gwf(name).get_package("npf").k.array, dtype=float).copy()
    with pytest.raises(ValueError, match="state_head_bound"):
        _impl_setup_da_control(
            name,
            {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
            cycles=[0, 1],
            obs_cycles=_obs_cycles(),
            state_head_bound=-1.0,
        )
    _assert_model_not_rewired(name, k_before)


def test_setup_da_control_disu_state_bounds_head_scale(tmp_path):
    """DISU state bounds are physical too (strt=0 m, one value per site)."""
    name = _disu_da_model(tmp_path, "disubound")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_disu_obs_cycles(),
        num_reals=4,
    )
    assert "error" not in res, res
    _, state = _state_params(res)
    assert state.loc["s1", "parlbnd"] == pytest.approx(-10.0)
    assert state.loc["s1", "parubnd"] == pytest.approx(10.0)
    assert state.loc["s2", "parlbnd"] == pytest.approx(-10.0)
    assert state.loc["s2", "parubnd"] == pytest.approx(10.0)
    assert (state["parubnd"] - state["parlbnd"]).max() <= 100.0


def test_prior_std_draws_are_clipped_to_bounds(tmp_path):
    """A large prior_std cannot emit out-of-bounds draws (log K or linear head)."""
    name = _da_model(tmp_path, name="daclip")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=200,
        prior_std=5.0,
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    pe = pyemu.ParameterEnsemble.from_csv(pst, res["prior_ensemble_file"])

    # K is log-transformed with bounds initial*0.1 .. initial*10
    k_vals = np.asarray(pe.loc[:, "k"].values, dtype=float)
    assert k_vals.min() >= 0.5 - 1e-6
    assert k_vals.max() <= 50.0 + 1e-6
    assert k_vals.min() < k_vals.max()  # still drawn

    # heads are linear with the physical state bounds (strt 25 +/- 10)
    head_vals = np.asarray(pe.loc[:, "s1"].values, dtype=float)
    assert head_vals.min() >= 15.0 - 1e-6
    assert head_vals.max() <= 35.0 + 1e-6

    # the clamps are reported, not silent
    assert res["prior_ensemble_n_clipped"] > 0


def test_explicit_prior_ensemble_values_clipped_to_bounds(tmp_path):
    """Explicit out-of-bounds prior values are clipped (in-bounds kept as-is)."""
    name = _da_model(tmp_path, name="daclipx")
    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        prior_ensemble={"k": [0.001, 3.0, 6.0, 1.0e6]},
    )
    assert "error" not in res, res
    pst = pyemu.Pst(res["pst_file"])
    pe = pyemu.ParameterEnsemble.from_csv(pst, res["prior_ensemble_file"])
    vals = [float(v) for v in pe.loc[:, "k"].values]
    assert min(vals) == pytest.approx(0.5)  # clipped up to the lower bound
    assert max(vals) == pytest.approx(50.0)  # clipped down to the upper bound
    assert any(abs(v - 3.0) < 1e-9 for v in vals)  # in-bounds survives
    assert any(abs(v - 6.0) < 1e-9 for v in vals)
    # exactly the two out-of-bounds realisations were clamped, and it is reported
    assert res["prior_ensemble_n_clipped"] == 2


def test_setup_da_control_flushes_model_once(tmp_path, monkeypatch):
    """The K and IC rewires share a single full-model flush (was two)."""
    import groundwater_mcp.tools.calibration as cal

    name = _da_model(tmp_path, name="daflush")
    calls: list[str] = []
    real_flush = cal.flush_model

    def _spy(model: str) -> bool:
        calls.append(model)
        return real_flush(model)

    monkeypatch.setattr(cal, "flush_model", _spy)

    res = _impl_setup_da_control(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        cycles=[0, 1],
        obs_cycles=_obs_cycles(),
        num_reals=4,
    )
    assert "error" not in res, res
    assert calls == [name]

    # the deferred write still lands both external arrays and the OPEN/CLOSE wiring
    ws = resolve_workspace(name)
    gwf = get_gwf(name)
    assert (ws / f"{gwf.name}_k.dat").exists()
    assert (ws / f"{gwf.name}_strt.dat").exists()
    assert "OPEN/CLOSE" in (ws / f"{gwf.name}.npf").read_text()
    assert "OPEN/CLOSE" in (ws / f"{gwf.name}.ic").read_text()
    assert Path(res["pst_file"]).exists()
