"""Tests for tools/calibration.py — PEST++ calibration tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import pytest

from groundwater_mcp.tools.calibration import (
    _find_pestpp_binary,
    _impl_run_ies_uncertainty,
    _impl_run_pestpp_glm,
    _impl_run_pestpp_ies,
    _impl_setup_pest_control,
    _impl_summarise_calibration,
    _parse_par_file,
    _read_phi_csv,
)
from groundwater_mcp.utils.workspace import create_workspace, resolve_workspace


# ---------------------------------------------------------------------------
# Skip marker — integration tests require PEST++ binaries
# ---------------------------------------------------------------------------


def _pestpp_available(exe: str = "pestpp-glm") -> bool:
    try:
        _find_pestpp_binary(exe)
        return True
    except RuntimeError:
        return False


requires_pestpp = pytest.mark.skipif(
    not _pestpp_available(), reason="PEST++ binaries not installed"
)


# ---------------------------------------------------------------------------
# Synthetic fixture helpers
# ---------------------------------------------------------------------------


def _write_minimal_tpl(path: Path, par_names: list[str]) -> None:
    """Write a minimal PEST++ template file defining par_names."""
    lines = ["ptf ~"]
    # One parameter per line: ~  par_name  ~
    lines += [f"~  {n:12s}  ~" for n in par_names]
    path.write_text("\n".join(lines) + "\n")


def _write_minimal_ins(path: Path, obs_names: list[str]) -> None:
    """Write a minimal PEST++ instruction file defining obs_names."""
    lines = ["pif @"]
    for obs in obs_names:
        lines.append(f"l1 !{obs}!")
    path.write_text("\n".join(lines) + "\n")


def _write_minimal_in(path: Path, par_names: list[str], values: list[float]) -> None:
    """Write a model input file with one value per line (matching the tpl structure)."""
    lines = [str(v) for v in values]
    path.write_text("\n".join(lines) + "\n")


def _write_minimal_out(path: Path, obs_names: list[str], values: list[float]) -> None:
    """Write a model output file with one observation value per line."""
    lines = [str(v) for v in values]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def calib_workspace(tmp_path, model_name) -> str:
    """Register a model workspace and return the model name.

    Creates a 2-parameter, 5-observation synthetic PEST++ problem:
      parameters: k, ss
      observations: h1, h2, h3, h4, h5
    """
    ws = str(tmp_path / model_name)
    create_workspace(model_name, ws)
    ws_path = Path(ws)

    par_names = ["k", "ss"]
    obs_names = ["h1", "h2", "h3", "h4", "h5"]

    tpl = ws_path / "params.tpl"
    ins = ws_path / "heads.ins"
    in_file = ws_path / "params"
    out_file = ws_path / "heads"

    _write_minimal_tpl(tpl, par_names)
    _write_minimal_ins(ins, obs_names)
    _write_minimal_in(in_file, par_names, [10.0, 0.001])
    _write_minimal_out(out_file, obs_names, [5.1, 4.9, 4.7, 4.5, 4.3])

    return model_name


@pytest.fixture()
def pst_model(calib_workspace) -> tuple[str, str]:
    """calib_workspace with a .pst file already written.

    Returns (model_name, pst_file_path).
    """
    model = calib_workspace
    ws = resolve_workspace(model)

    obs_data = {
        "h1": {"obsval": 5.0, "weight": 1.0, "obgnme": "heads"},
        "h2": {"obsval": 4.8, "weight": 1.0, "obgnme": "heads"},
        "h3": {"obsval": 4.6, "weight": 1.0, "obgnme": "heads"},
        "h4": {"obsval": 4.4, "weight": 1.0, "obgnme": "heads"},
        "h5": {"obsval": 4.2, "weight": 1.0, "obgnme": "heads"},
    }
    par_data = {
        "k": {"parval1": 10.0, "parlbnd": 0.1, "parubnd": 1000.0, "pargp": "hk"},
        "ss": {"parval1": 0.001, "parlbnd": 1e-6, "parubnd": 0.1, "pargp": "ss"},
    }

    result = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(ws / "params.tpl")],
        instruction_files=[str(ws / "heads.ins")],
        pestpp_options={"noptmax": 5},
    )
    return model, result["pst_file"]


# ---------------------------------------------------------------------------
# _find_pestpp_binary
# ---------------------------------------------------------------------------


def test_find_pestpp_binary_raises_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(Path, "exists", lambda _self: False)

    with pytest.raises(RuntimeError, match="PEST\\+\\+"):
        _find_pestpp_binary("pestpp-glm")


def test_find_pestpp_binary_uses_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/pestpp-glm")
    assert _find_pestpp_binary("pestpp-glm") == "/usr/bin/pestpp-glm"


# ---------------------------------------------------------------------------
# _read_phi_csv
# ---------------------------------------------------------------------------


def test_read_phi_csv_returns_empty_for_missing_file(tmp_path):
    progress, final = _read_phi_csv(tmp_path / "nonexistent.csv")
    assert progress == []
    assert final is None


def test_read_phi_csv_parses_correctly(tmp_path):
    phi_csv = tmp_path / "test.phi.actual.csv"
    data = pd.DataFrame({"group1": [100.0, 50.0, 20.0], "group2": [10.0, 8.0, 5.0]})
    data.to_csv(phi_csv)

    progress, final = _read_phi_csv(phi_csv)

    assert len(progress) == 3
    assert progress[0]["iteration"] == 0
    assert progress[0]["phi"] == pytest.approx(110.0)
    assert progress[2]["phi"] == pytest.approx(25.0)
    assert final == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# _parse_par_file
# ---------------------------------------------------------------------------


def test_parse_par_file_returns_empty_for_missing_file(tmp_path):
    result = _parse_par_file(tmp_path / "nonexistent.par")
    assert result == {}


def test_parse_par_file_reads_values(tmp_path):
    par_file = tmp_path / "model.par"
    par_file.write_text(
        "single point\n"
        "k        12.345    1.0   0\n"
        "ss       0.00234   1.0   0\n"
    )
    result = _parse_par_file(par_file)
    assert result["k"] == pytest.approx(12.345)
    assert result["ss"] == pytest.approx(0.00234)


def test_parse_par_file_lowercase_keys(tmp_path):
    par_file = tmp_path / "model.par"
    par_file.write_text("single point\nK  10.0  1.0  0\n")
    result = _parse_par_file(par_file)
    assert "k" in result


# ---------------------------------------------------------------------------
# _impl_setup_pest_control
# ---------------------------------------------------------------------------


def test_setup_pest_control_creates_pst_file(pst_model):
    model, pst_file = pst_model
    assert Path(pst_file).exists(), "PST file should be written to disk"
    assert pst_file.endswith(".pst")


def test_setup_pest_control_returns_expected_keys(pst_model):
    model, pst_file = pst_model
    ws = resolve_workspace(model)

    result = _impl_setup_pest_control(
        model=model,
        obs_data={"h1": {"obsval": 5.0, "weight": 1.0}},
        par_data={"k": {"parval1": 10.0, "parlbnd": 0.1, "parubnd": 1000.0}},
        template_files=[str(ws / "params.tpl")],
        instruction_files=[str(ws / "heads.ins")],
    )
    for key in ("model", "pst_file", "n_observations", "n_adjustable_parameters", "n_total_parameters"):
        assert key in result, f"Missing key: {key}"


def test_setup_pest_control_observation_values(pst_model):
    """Observation values written to PST should match obs_data."""
    model, pst_file = pst_model
    pst = pyemu.Pst(pst_file)
    obs_df = pst.observation_data

    assert "h1" in obs_df.index
    assert obs_df.loc["h1", "obsval"] == pytest.approx(5.0)
    assert obs_df.loc["h1", "weight"] == pytest.approx(1.0)
    assert str(obs_df.loc["h1", "obgnme"]) == "heads"


def test_setup_pest_control_parameter_values(pst_model):
    """Parameter bounds written to PST should match par_data."""
    model, pst_file = pst_model
    pst = pyemu.Pst(pst_file)
    par_df = pst.parameter_data

    assert "k" in par_df.index
    assert par_df.loc["k", "parval1"] == pytest.approx(10.0)
    assert par_df.loc["k", "parlbnd"] == pytest.approx(0.1)
    assert par_df.loc["k", "parubnd"] == pytest.approx(1000.0)


def test_setup_pest_control_pestpp_options_written(pst_model):
    """PEST++ options dict should be written to the PST."""
    model, pst_file = pst_model
    pst = pyemu.Pst(pst_file)
    assert "noptmax" in pst.pestpp_options


def test_setup_pest_control_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_setup_pest_control(
            "no_such_model_xyz", {}, {}, [], []
        )


# ---------------------------------------------------------------------------
# _impl_run_pestpp_glm — unit tests (no binary needed)
# ---------------------------------------------------------------------------


def test_run_pestpp_glm_binary_not_found_raises(pst_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: (_ for _ in ()).throw(
        RuntimeError("PEST++ binary 'pestpp-glm' not found")
    ))

    with pytest.raises(RuntimeError, match="PEST\\+\\+"):
        _impl_run_pestpp_glm(*pst_model)


def test_run_pestpp_glm_returns_expected_keys(pst_model, monkeypatch):
    """Monkeypatch subprocess.run to simulate a successful GLM run."""
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: "/fake/pestpp-glm")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="done", stderr=""),
    )

    model, pst_file = pst_model
    result = _impl_run_pestpp_glm(model, pst_file)

    for key in ("model", "pst_file", "converged", "final_phi", "iterations", "stdout"):
        assert key in result, f"Missing key: {key}"


def test_run_pestpp_glm_converged_on_returncode_zero(pst_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: "/fake/pestpp-glm")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )

    model, pst_file = pst_model
    result = _impl_run_pestpp_glm(model, pst_file)
    assert result["converged"] is True


def test_run_pestpp_glm_not_converged_on_nonzero_returncode(pst_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: "/fake/pestpp-glm")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 1, stdout="", stderr="error"),
    )

    model, pst_file = pst_model
    result = _impl_run_pestpp_glm(model, pst_file)
    assert result["converged"] is False


def test_run_pestpp_glm_reads_phi_csv(pst_model, monkeypatch):
    """If a phi CSV exists after the run, its values should be reflected."""
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: "/fake/pestpp-glm")

    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    # Write a synthetic phi CSV before the "run"
    phi_csv = ws / f"{pst_stem}.phi.actual.csv"
    pd.DataFrame({"heads": [200.0, 50.0, 10.0]}).to_csv(phi_csv)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )

    result = _impl_run_pestpp_glm(model, pst_file)
    assert result["iterations"] == 3
    assert result["final_phi"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# _impl_run_pestpp_ies — unit tests (no binary needed)
# ---------------------------------------------------------------------------


def test_run_pestpp_ies_returns_expected_keys(pst_model, monkeypatch):
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: "/fake/pestpp-ies")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )

    model, pst_file = pst_model
    result = _impl_run_pestpp_ies(model, pst_file, num_reals=10)

    for key in ("model", "pst_file", "converged", "final_phi_mean", "final_phi_std", "iterations", "num_reals"):
        assert key in result, f"Missing key: {key}"
    assert result["num_reals"] == 10


def test_run_pestpp_ies_writes_num_reals_to_pst(pst_model, monkeypatch):
    """ies_num_reals should be injected into the PST before running."""
    import groundwater_mcp.tools.calibration as cal_module

    monkeypatch.setattr(cal_module, "_find_pestpp_binary", lambda _name: "/fake/pestpp-ies")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )

    model, pst_file = pst_model
    _impl_run_pestpp_ies(model, pst_file, num_reals=25)

    pst = pyemu.Pst(pst_file)
    # pyemu stores pestpp_options values as strings
    assert int(pst.pestpp_options.get("ies_num_reals")) == 25


# ---------------------------------------------------------------------------
# _impl_summarise_calibration — unit tests
# ---------------------------------------------------------------------------


def test_summarise_calibration_returns_expected_keys(pst_model):
    model, pst_file = pst_model
    result = _impl_summarise_calibration(model, pst_file)

    for key in ("model", "pst_file", "phi_progress", "parameter_estimates", "residual_statistics", "residuals"):
        assert key in result, f"Missing key: {key}"


def test_summarise_calibration_parameter_estimates_shape(pst_model):
    """Should return one entry per parameter defined in the PST."""
    model, pst_file = pst_model
    result = _impl_summarise_calibration(model, pst_file)
    estimates = result["parameter_estimates"]
    assert len(estimates) == 2  # k and ss

    names = {e["name"] for e in estimates}
    assert "k" in names
    assert "ss" in names


def test_summarise_calibration_reads_phi_csv(pst_model):
    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    phi_csv = ws / f"{pst_stem}.phi.actual.csv"
    pd.DataFrame({"heads": [150.0, 60.0, 18.0]}).to_csv(phi_csv)

    result = _impl_summarise_calibration(model, pst_file)
    assert len(result["phi_progress"]) == 3
    assert result["phi_progress"][-1]["phi"] == pytest.approx(18.0)


def test_summarise_calibration_reads_par_file(pst_model):
    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    par_file = ws / f"{pst_stem}.par"
    par_file.write_text("single point\nk        42.0  1.0  0\nss       0.005  1.0  0\n")

    result = _impl_summarise_calibration(model, pst_file)
    k_est = next(e for e in result["parameter_estimates"] if e["name"] == "k")
    assert k_est["estimated_value"] == pytest.approx(42.0)


def test_summarise_calibration_residual_stats_no_rei(pst_model):
    """With no .rei file present, residual_statistics should have None values gracefully."""
    model, pst_file = pst_model
    result = _impl_summarise_calibration(model, pst_file)
    stats = result["residual_statistics"]
    assert "rmse" in stats
    assert "bias" in stats
    assert "r_squared" in stats


def test_summarise_calibration_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_summarise_calibration("no_such_model_xyz", "fake.pst")


# ---------------------------------------------------------------------------
# _impl_run_ies_uncertainty — unit tests
# ---------------------------------------------------------------------------


def test_run_ies_uncertainty_no_ensemble_raises(pst_model):
    model, pst_file = pst_model
    with pytest.raises(FileNotFoundError, match=r"\.obs\.csv"):
        _impl_run_ies_uncertainty(model, pst_file, ["h1"])


def test_run_ies_uncertainty_missing_forecast_raises(pst_model):
    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    # Write synthetic ensemble without the requested forecast column
    obs_csv = ws / f"{pst_stem}.0.obs.csv"
    pd.DataFrame({"h1": [5.0, 5.1, 4.9], "h2": [4.8, 4.9, 4.7]}).to_csv(obs_csv)

    with pytest.raises(ValueError, match="h_nonexistent"):
        _impl_run_ies_uncertainty(model, pst_file, ["h_nonexistent"])


def test_run_ies_uncertainty_returns_expected_keys(pst_model):
    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    rng = np.random.default_rng(42)
    obs_csv = ws / f"{pst_stem}.3.obs.csv"
    pd.DataFrame({
        "h1": rng.normal(5.0, 0.2, 50),
        "h2": rng.normal(4.8, 0.15, 50),
    }).to_csv(obs_csv)

    result = _impl_run_ies_uncertainty(model, pst_file, ["h1", "h2"])

    for key in ("model", "pst_file", "ensemble_file", "forecasts"):
        assert key in result, f"Missing key: {key}"
    assert "h1" in result["forecasts"]
    assert "h2" in result["forecasts"]


def test_run_ies_uncertainty_forecast_statistics(pst_model):
    """Verify the returned statistics match numpy computations on the ensemble."""
    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    rng = np.random.default_rng(0)
    h1_vals = rng.normal(5.0, 0.3, 100)
    obs_csv = ws / f"{pst_stem}.0.obs.csv"
    pd.DataFrame({"h1": h1_vals}).to_csv(obs_csv)

    result = _impl_run_ies_uncertainty(model, pst_file, ["h1"])
    fc = result["forecasts"]["h1"]

    assert fc["mean"] == pytest.approx(float(h1_vals.mean()), rel=1e-6)
    # pandas Series.std() uses ddof=1 (sample std); match that here
    assert fc["std"] == pytest.approx(float(h1_vals.std(ddof=1)), rel=1e-4)
    assert fc["p5"] < fc["mean"] < fc["p95"]
    assert fc["n_realizations"] == 100


def test_run_ies_uncertainty_uses_latest_iteration(pst_model):
    """When multiple ensemble CSVs exist, the last one (highest N) should be used."""
    model, pst_file = pst_model
    ws = resolve_workspace(model)
    pst_stem = Path(pst_file).stem

    # Write two iteration files
    pd.DataFrame({"h1": [5.0, 4.8, 5.2]}).to_csv(ws / f"{pst_stem}.0.obs.csv")
    pd.DataFrame({"h1": [4.9, 5.0, 4.95]}).to_csv(ws / f"{pst_stem}.3.obs.csv")

    result = _impl_run_ies_uncertainty(model, pst_file, ["h1"])
    assert "3.obs.csv" in result["ensemble_file"]


def test_run_ies_uncertainty_unknown_model_raises():
    with pytest.raises(KeyError):
        _impl_run_ies_uncertainty("no_such_model_xyz", "fake.pst", ["h1"])


# ---------------------------------------------------------------------------
# Integration tests (require PEST++ binaries and a real MODFLOW model)
# ---------------------------------------------------------------------------
#
# These tests are intentionally minimal — a 1-layer 5×5 steady-state model
# with K as the single calibration parameter against 5 synthetic head obs.
# They verify the full subprocess → file I/O → parse round-trip.
# ---------------------------------------------------------------------------


@pytest.fixture()
def integration_model(tmp_path, model_name):
    """Full MODFLOW model + PEST++ setup ready for integration calibration tests."""
    from groundwater_mcp.tools.builder import (
        _impl_add_boundary_package,
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_add_oc_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.tools.runner import _impl_run_simulation

    ws_str = str(tmp_path / model_name)
    _impl_create_model(model_name, ws_str, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=0, k=10.0, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)

    _impl_run_simulation(model_name, silent=True)

    return model_name


@pytest.fixture()
def simple_pst(integration_model, tmp_path):
    """Build a PST for the integration model with a single parameter (K multiplier).

    The forward model run command just re-runs MODFLOW; the observation
    instruction file reads a synthetic output file.
    """
    model = integration_model
    ws = resolve_workspace(model)

    # Write a template for a single parameter multiplier
    tpl = ws / "k_mult.tpl"
    tpl.write_text("ptf ~\n~  kmult       ~\n")

    # Write initial model input file
    (ws / "k_mult").write_text("10.0\n")

    # Write instruction file for 5 synthetic head observations
    ins = ws / "obs_heads.ins"
    ins.write_text("pif @\n" + "\n".join(f"l1 !h{i}!" for i in range(1, 6)) + "\n")

    # Write synthetic output file (observed-like values)
    obs_vals = [7.0, 6.5, 5.5, 4.5, 4.0]
    (ws / "obs_heads").write_text("\n".join(str(v) for v in obs_vals) + "\n")

    obs_data = {f"h{i}": {"obsval": v, "weight": 1.0} for i, v in enumerate(obs_vals, 1)}
    par_data = {"kmult": {"parval1": 1.0, "parlbnd": 0.01, "parubnd": 100.0, "pargp": "hk"}}

    result = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(tpl)],
        instruction_files=[str(ins)],
        pestpp_options={"noptmax": 3},
    )
    return model, result["pst_file"]


@requires_pestpp
def test_integration_run_pestpp_glm(simple_pst):
    model, pst_file = simple_pst
    result = _impl_run_pestpp_glm(model, pst_file)
    assert "error" not in result
    assert result["converged"] is True or result["converged"] is False  # just must complete
    assert isinstance(result["final_phi"], (float, type(None)))
    assert result["iterations"] >= 0


@requires_pestpp
def test_integration_run_pestpp_glm_produces_par_file(simple_pst):
    model, pst_file = simple_pst
    _impl_run_pestpp_glm(model, pst_file)
    ws = resolve_workspace(model)
    par_files = list(ws.glob("*.par"))
    assert len(par_files) > 0, "Expected a .par file after GLM run"


@requires_pestpp
def test_integration_summarise_calibration_after_glm(simple_pst):
    model, pst_file = simple_pst
    _impl_run_pestpp_glm(model, pst_file)
    result = _impl_summarise_calibration(model, pst_file)
    assert "error" not in result
    assert len(result["parameter_estimates"]) == 1
    km = result["parameter_estimates"][0]
    assert km["name"] == "kmult"
    assert km["initial_value"] == pytest.approx(1.0)
