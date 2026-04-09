"""Tests for tools/runner.py — MODFLOW 6 execution and log retrieval."""

from __future__ import annotations

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
from groundwater_mcp.tools.runner import (
    _find_mf6_binary,
    _impl_check_model,
    _impl_get_run_log,
    _impl_run_simulation,
)


# ---------------------------------------------------------------------------
# Skip marker — integration tests require the mf6 binary
# ---------------------------------------------------------------------------


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bare_model(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    return model_name


@pytest.fixture()
def runnable_model(tmp_path, model_name):
    """Minimal complete 1-layer 5x5 steady-state model ready to run.

    Left column CHD=10 m, right column CHD=5 m — produces a simple
    uniform horizontal gradient that converges in 1 outer iteration.
    """
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    # Use head values clearly inside the model (top=10, botm=0) to avoid
    # FloPy's "head at or above model top" check warning.
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)
    return model_name


@pytest.fixture()
def nonconverging_model(tmp_path):
    """Model configured to fail convergence: initial heads far from solution,
    outer_maximum=1 and outer_dvclose=1e-50 (impossible tolerance in 1 step).
    """
    import flopy.mf6 as mf6

    from groundwater_mcp.utils.model_store import get_sim, save_sim

    name = "bad_model"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")

    # Replace IMS: 1 outer iteration with an impossible head-change tolerance
    sim = get_sim(name)
    ims = sim.get_package("ims")
    if ims is not None:
        sim.remove_package(ims)
    tight_ims = mf6.ModflowIms(
        sim,
        pname="ims",
        outer_maximum=1,
        inner_maximum=25,
        outer_dvclose=1e-50,
        inner_dvclose=1e-10,
    )
    sim.register_ims_package(tight_ims, list(sim.model_names))
    save_sim(name, sim)

    # Initial heads at 0, CHD boundaries at 50/80 — large first-step Δh ensures
    # the outer convergence check (Δh < 1e-50) is never satisfied in 1 iteration.
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 100.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=0.0)
    chd = [[[0, row, 0], 50.0] for row in range(5)] + [[[0, row, 4], 80.0] for row in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


# ---------------------------------------------------------------------------
# _find_mf6_binary
# ---------------------------------------------------------------------------


def test_find_mf6_binary_raises_when_missing(monkeypatch):
    """_find_mf6_binary must raise RuntimeError when the binary is not on PATH
    and none of the candidate paths exist."""
    from pathlib import Path

    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(Path, "exists", lambda _self: False)

    with pytest.raises(RuntimeError, match="MODFLOW 6"):
        _find_mf6_binary()


def test_find_mf6_binary_uses_which(monkeypatch):
    """_find_mf6_binary should return whatever shutil.which returns."""
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/mf6")
    assert _find_mf6_binary() == "/usr/bin/mf6"


# ---------------------------------------------------------------------------
# check_model
# ---------------------------------------------------------------------------


def test_check_model_returns_expected_keys(runnable_model):
    result = _impl_check_model(runnable_model)
    assert "error" not in result
    for key in ("model", "check_passed", "warnings", "errors", "raw_output"):
        assert key in result, f"Missing key: {key}"


def test_check_model_valid_model_passes(runnable_model):
    result = _impl_check_model(runnable_model)
    assert result["model"] == runnable_model
    assert result["check_passed"] is True
    assert isinstance(result["warnings"], list)
    assert isinstance(result["errors"], list)


def test_check_model_bare_model(bare_model):
    """A model with no packages should not raise — check_passed may be True or False."""
    result = _impl_check_model(bare_model)
    assert "error" not in result
    assert "check_passed" in result


def test_check_model_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_check_model("no_such_model_xyz")


# ---------------------------------------------------------------------------
# run_simulation — unit tests (no binary needed)
# ---------------------------------------------------------------------------


def test_run_simulation_binary_not_found_raises(runnable_model, monkeypatch):
    """run_simulation must raise RuntimeError when the mf6 binary is missing."""
    import groundwater_mcp.tools.runner as runner_module

    def _raise():
        raise RuntimeError("MODFLOW 6 binary not found")

    monkeypatch.setattr(runner_module, "_find_mf6_binary", _raise)

    with pytest.raises(RuntimeError, match="MODFLOW 6"):
        _impl_run_simulation(runnable_model)


def test_run_simulation_convergence_failed_reporting(runnable_model, monkeypatch):
    """When sim.run_simulation() reports failure, the result should reflect it."""
    import groundwater_mcp.tools.runner as runner_module
    from groundwater_mcp.utils import model_store

    monkeypatch.setattr(runner_module, "_find_mf6_binary", lambda: "/fake/mf6")

    sim = model_store.get_sim(runnable_model)
    monkeypatch.setattr(
        sim,
        "run_simulation",
        lambda **_kwargs: (False, ["ERROR: solver failed to converge"]),
    )

    result = _impl_run_simulation(runnable_model)
    assert result["success"] is False
    assert result["convergence"] == "failed"


def test_run_simulation_cache_invalidated_after_run(runnable_model, monkeypatch):
    """After run_simulation, the model should be evicted from the in-process cache."""
    import groundwater_mcp.tools.runner as runner_module
    from groundwater_mcp.utils import model_store

    monkeypatch.setattr(runner_module, "_find_mf6_binary", lambda: "/fake/mf6")

    sim = model_store.get_sim(runnable_model)
    monkeypatch.setattr(
        sim, "run_simulation", lambda **_kwargs: (True, ["normal termination"])
    )
    model_store._cache[runnable_model] = sim  # ensure it's in cache

    _impl_run_simulation(runnable_model)

    assert runnable_model not in model_store._cache


# ---------------------------------------------------------------------------
# run_simulation — integration tests (require mf6 binary)
# ---------------------------------------------------------------------------


@requires_mf6
def test_run_simulation_success(runnable_model):
    result = _impl_run_simulation(runnable_model, silent=True)
    assert "error" not in result
    assert result["success"] is True
    assert result["convergence"] == "converged"
    assert result["elapsed_s"] >= 0.0


@requires_mf6
def test_run_simulation_produces_hds_file(runnable_model):
    _impl_run_simulation(runnable_model, silent=True)
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(runnable_model)
    assert len(list(ws.glob("*.hds"))) > 0, "Expected .hds output file"


@requires_mf6
def test_run_simulation_produces_budget_file(runnable_model):
    _impl_run_simulation(runnable_model, silent=True)
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(runnable_model)
    assert len(list(ws.glob("*.cbb"))) > 0, "Expected .cbb budget file"


@requires_mf6
def test_run_simulation_elapsed_time_positive(runnable_model):
    result = _impl_run_simulation(runnable_model, silent=True)
    assert isinstance(result["elapsed_s"], float)
    assert result["elapsed_s"] > 0


@requires_mf6
def test_run_simulation_convergence_failed(nonconverging_model):
    """Deliberately ill-conditioned model should return success=False."""
    result = _impl_run_simulation(nonconverging_model, silent=True)
    assert result["success"] is False
    assert result["convergence"] == "failed"


# ---------------------------------------------------------------------------
# get_run_log — unit tests (no binary needed)
# ---------------------------------------------------------------------------


def test_get_run_log_no_lst_raises(runnable_model):
    """Before any run there is no listing file — should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match=r"\.lst"):
        _impl_get_run_log(runnable_model)


def test_get_run_log_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_get_run_log("no_such_model_xyz")


def test_get_run_log_reads_synthetic_lst(runnable_model):
    """Write a synthetic .lst file into the workspace and verify get_run_log reads it."""
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(runnable_model)
    lst = ws / "mfsim.lst"
    lines = [f"line {i}" for i in range(200)]
    lst.write_text("\n".join(lines))

    result = _impl_get_run_log(runnable_model, tail=50)
    assert "error" not in result
    assert result["listing_file"] == str(lst)
    assert result["total_lines"] == 200
    assert len(result["tail_lines"]) == 50
    assert result["tail_lines"][0] == "line 150"


def test_get_run_log_tail_smaller_than_file(runnable_model):
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(runnable_model)
    (ws / "mfsim.lst").write_text("\n".join(f"L{i}" for i in range(10)))

    result = _impl_get_run_log(runnable_model, tail=100)
    assert len(result["tail_lines"]) == 10  # file shorter than requested tail


def test_get_run_log_extracts_convergence_table(runnable_model):
    """Lines containing 'CONVERGENCE' should be captured in convergence_table."""
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(runnable_model)
    content = "\n".join([
        "header line",
        "CONVERGENCE SUMMARY",
        "iter  dvmax",
        "1     0.001",
    ])
    (ws / "mfsim.lst").write_text(content)

    result = _impl_get_run_log(runnable_model)
    assert "CONVERGENCE" in result["convergence_table"]


# ---------------------------------------------------------------------------
# get_run_log — integration tests (require mf6 binary)
# ---------------------------------------------------------------------------


@requires_mf6
def test_get_run_log_after_run(runnable_model):
    _impl_run_simulation(runnable_model, silent=True)
    result = _impl_get_run_log(runnable_model)
    assert "error" not in result
    assert result["listing_file"].endswith(".lst")
    assert result["total_lines"] > 0
    assert len(result["tail_lines"]) > 0


@requires_mf6
def test_get_run_log_tail_limit_respected(runnable_model):
    _impl_run_simulation(runnable_model, silent=True)
    result = _impl_get_run_log(runnable_model, tail=10)
    assert len(result["tail_lines"]) <= 10
