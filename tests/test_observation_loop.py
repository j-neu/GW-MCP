"""7f-F tests — close the observation loop.

F1.1: observation targets become model state (.gwmcp_meta.json observations).
F1.2: read_simulated_observations parses the model's obs CSV.
F1.3: compare_to_observed returns RMSE/bias/R²/MAE + residuals + scatter.
F1.4: run_simulation reports observation_fit when targets are registered.
F1.5: setup_pest_control(obs_source="model") builds the obs interface from
      registered targets.

See tasks.md § 7f Tier F.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
    _impl_summarise_model,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.postprocess import (
    _impl_compare_to_observed,
    _impl_read_simulated_observations,
)
from groundwater_mcp.tools.runner import _find_mf6_binary
from groundwater_mcp.utils import model_store
from groundwater_mcp.utils.model_store import invalidate, read_meta
from groundwater_mcp.utils.workspace import resolve_workspace


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
# Shared fixtures
# ---------------------------------------------------------------------------


def _build_small_model(tmp_path, name: str = "obs_model") -> str:
    """1-layer 5x5 steady-state model with a CHD gradient (left 10, right 5)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=7.5)
    chd = [[[0, r, 0], 10.0] for r in range(5)] + [[[0, r, 4], 5.0] for r in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _write_obs_csv(tmp_path, rows: list[tuple[str, str, float, float, float]]) -> str:
    """rows = (site, date, value, x, y)."""
    csv_path = tmp_path / "obs.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for row in rows:
            writer.writerow(row)
    return str(csv_path)


@pytest.fixture()
def obs_csv_at_centroids(tmp_path):
    """An obs CSV with 5 sites placed at grid cell centroids."""
    from groundwater_mcp.tools.builder import _impl_add_dis_package
    from groundwater_mcp.utils.model_store import get_gwf
    from groundwater_mcp.utils.spatial import grid_centroids

    # Build a throwaway grid just to obtain centroid coordinates (5x5, delr=delc=100)
    name = "centroid_probe"
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])

    mg = get_gwf(name).modelgrid
    xc, yc = grid_centroids(mg)
    model_store.invalidate(name)

    cells = [0, 2, 12, 22, 24]  # spread across the grid
    values = [55.0, 54.0, 53.0, 52.0, 51.0]
    rows = []
    for i, cell in enumerate(cells):
        rows.append((f"S{i + 1:02d}", "2020-01-01", values[i], float(xc[cell]), float(yc[cell])))
    return _write_obs_csv(tmp_path, rows)


# ---------------------------------------------------------------------------
# F1.1 — observation targets become model state
# ---------------------------------------------------------------------------


def test_import_obs_persists_targets_to_meta(tmp_path, obs_csv_at_centroids):
    name = _build_small_model(tmp_path)
    result = _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    assert "error" not in result
    assert result["site_count"] == 5

    meta = read_meta(name)
    obs = meta.get("observations")
    assert obs is not None
    assert obs["type"] == "HEAD"
    assert obs["output_csv"].endswith("_head.obs.csv")
    assert len(obs["sites"]) == 5
    assert obs["sites"][0]["site"] == "S01"
    assert obs["sites"][0]["values"] == [55.0]
    assert len(obs["sites"][0]["cellid"]) == 3


def test_summarise_model_reports_registered_targets(tmp_path, obs_csv_at_centroids):
    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    # Fresh process: evict the cache so state must come from .gwmcp_meta.json
    from groundwater_mcp.utils.model_store import flush_model

    flush_model(name)
    invalidate(name)
    summary = _impl_summarise_model(name)
    assert summary["observations"] == {
        "type": "HEAD",
        "layer": 0,
        "output_csv": "obs_model_head.obs.csv",
        "site_count": 5,
    }


# ---------------------------------------------------------------------------
# F1.2 — read_simulated_observations
# ---------------------------------------------------------------------------


def test_read_simulated_observations_before_run_returns_error(tmp_path, obs_csv_at_centroids):
    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    result = _impl_read_simulated_observations(name)
    assert result.get("error") is True
    assert result["code"] == "OUTPUT_FILE_MISSING"


def test_read_simulated_observations_no_targets_error(tmp_path):
    name = _build_small_model(tmp_path)
    result = _impl_read_simulated_observations(name)
    assert result.get("error") is True
    assert result["code"] == "MODEL_HAS_NO_OBSERVATIONS"


@requires_mf6
def test_read_simulated_observations_after_run(tmp_path, obs_csv_at_centroids):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    run = _impl_run_simulation(name, silent=True)
    assert run["success"] is True, run.get("listing_summary", "")

    result = _impl_read_simulated_observations(name)
    assert "error" not in result
    assert result["obs_type"] == "HEAD"
    assert set(result["sites"].keys()) == {"S01", "S02", "S03", "S04", "S05"}

    # Match a direct read of the obs CSV within 1e-9
    ws = resolve_workspace(name)
    csv_files = list(ws.glob("*_head.obs.csv"))
    assert csv_files, "no obs CSV produced"
    df = pd.read_csv(csv_files[0])
    for site, value in result["sites"].items():
        assert float(df[site].iloc[-1]) == pytest.approx(value, abs=1e-9)


# ---------------------------------------------------------------------------
# F1.3 — compare_to_observed
# ---------------------------------------------------------------------------


def test_obs_matching_is_case_insensitive(tmp_path, obs_csv_at_centroids):
    """MODFLOW uppercases observation names in the continuous obs CSV, so a
    site registered as lowercase (the user's CSV) must still match the
    uppercased column (modeB tutorial-05 rerun-5 finding)."""
    from groundwater_mcp.utils.model_store import read_meta

    lower_csv = tmp_path / "obs_lower.csv"
    df = pd.read_csv(obs_csv_at_centroids)
    df["site"] = df["site"].str.lower()
    df.to_csv(lower_csv, index=False)

    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=str(lower_csv),
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    assert read_meta(name)["observations"]["sites"][0]["site"] == "s01"

    output_csv = (
        resolve_workspace(name) / read_meta(name)["observations"]["output_csv"]
    )
    output_csv.write_text(
        "time,S01,S02,S03,S04,S05\n1.0,60.0,59.0,58.0,57.0,56.0\n"
    )

    result = _impl_read_simulated_observations(name)
    assert "error" not in result
    assert set(result["sites"].keys()) == {"s01", "s02", "s03", "s04", "s05"}
    assert result["sites"]["s01"] == pytest.approx(60.0)

    compared = _impl_compare_to_observed(name)
    assert "error" not in compared
    assert compared["n"] == 5
    assert compared["residuals"][0]["site"] == "s01"


@requires_mf6
def test_compare_to_observed_rmse_matches_hand_computed(tmp_path, obs_csv_at_centroids):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    run = _impl_run_simulation(name, silent=True)
    assert run["success"] is True

    result = _impl_compare_to_observed(name)
    assert "error" not in result

    sim = _impl_read_simulated_observations(name)["sites"]
    observed = np.array([55.0, 54.0, 53.0, 52.0, 51.0])
    simulated = np.array([sim[f"S{i + 1:02d}"] for i in range(5)])
    residual = observed - simulated
    expected_rmse = float(np.sqrt(np.mean(residual**2)))
    assert result["rmse"] == pytest.approx(expected_rmse, abs=1e-6)
    assert result["n"] == 5
    assert result["bias"] == pytest.approx(float(np.mean(residual)), abs=1e-9)
    assert result["mae"] == pytest.approx(float(np.mean(np.abs(residual))), abs=1e-9)
    assert result["r2"] is not None

    # Residual table + scatter plot written to the workspace
    assert Path(result["residuals_csv"]).exists()
    assert Path(result["scatter_plot"]).exists()
    residual_df = pd.read_csv(result["residuals_csv"])
    assert len(residual_df) == 5


# ---------------------------------------------------------------------------
# F1.4 — run_simulation reports observation_fit
# ---------------------------------------------------------------------------


@requires_mf6
def test_run_reports_observation_fit_when_targets_registered(tmp_path, obs_csv_at_centroids):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    run = _impl_run_simulation(name, silent=True)
    assert run["success"] is True
    fit = run["observation_fit"]
    assert fit is not None
    assert fit["n"] == 5
    assert fit["rmse"] == pytest.approx(_impl_compare_to_observed(name)["rmse"], abs=1e-9)
    assert len(fit["worst_sites"]) <= 5


def test_run_reports_observation_fit_null_without_targets(tmp_path, monkeypatch):
    import groundwater_mcp.tools.runner as runner_module

    name = _build_small_model(tmp_path)
    monkeypatch.setattr(runner_module, "_find_mf6_binary", lambda: "/fake/mf6")
    sim = model_store.get_sim(name)
    monkeypatch.setattr(sim, "run_simulation", lambda **_kwargs: (True, ["normal termination"]))
    run = runner_module._impl_run_simulation(name, silent=True)
    assert run["success"] is True
    assert run["observation_fit"] is None


# ---------------------------------------------------------------------------
# F1.5 — setup_pest_control(obs_source="model")
# ---------------------------------------------------------------------------


def _write_minimal_tpl(path: Path, par_names: list[str]) -> None:
    lines = ["ptf ~"]
    lines += [f"~  {n:12s}  ~" for n in par_names]
    path.write_text("\n".join(lines) + "\n")


def test_setup_pest_control_obs_source_model(tmp_path, obs_csv_at_centroids):
    from groundwater_mcp.tools.calibration import _impl_setup_pest_control

    name = _build_small_model(tmp_path)
    _impl_import_obs_from_csv(
        model=name,
        csv_file=obs_csv_at_centroids,
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    ws = resolve_workspace(name)
    tpl = ws / "k.tpl"
    _write_minimal_tpl(tpl, ["k"])

    result = _impl_setup_pest_control(
        model=name,
        obs_data={},  # ignored with obs_source="model"
        par_data={"k": {"parval1": 10.0, "parlbnd": 1.0, "parubnd": 100.0, "pargp": "hk"}},
        template_files=["k.tpl"],
        instruction_files=[],  # generated with obs_source="model"
        obs_source="model",
    )
    assert "error" not in result
    assert result["n_observations"] == 5
    assert result["n_observations_matched"] == 5

    pst = __import__("pyemu").Pst(result["pst_file"])
    obs_names = sorted(pst.observation_data.index)
    assert obs_names == ["s01", "s02", "s03", "s04", "s05"]  # pyemu lowercases obs names
    assert pst.observation_data.loc["s01", "obsval"] == pytest.approx(55.0)

    # The generated instruction file parses a synthetic obs CSV correctly
    import pyemu as pyemu_mod

    ws_dir = resolve_workspace(name)
    out_csv = ws_dir / "obs_model_head.obs.csv"
    out_csv.write_text(
        "time,S01,S02,S03,S04,S05\n1.0,9.9,8.8,7.7,6.6,5.5\n"
    )
    ins_file = ws_dir / "obs_model_head.obs.csv.ins"
    assert ins_file.exists()
    ins = pyemu_mod.pst_utils.InstructionFile(str(ins_file))
    vals = ins.read_output_file(str(out_csv))
    assert float(vals.loc["s01", "obsval"]) == pytest.approx(9.9)
    assert float(vals.loc["s05", "obsval"]) == pytest.approx(5.5)


def test_setup_pest_control_obs_source_model_requires_targets(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_pest_control

    name = _build_small_model(tmp_path)
    with pytest.raises(ValueError, match="import_obs_from_csv"):
        _impl_setup_pest_control(
            model=name,
            obs_data={},
            par_data={"k": {"parval1": 10.0, "parlbnd": 1.0, "parubnd": 100.0}},
            template_files=["k.tpl"],
            instruction_files=[],
            obs_source="model",
        )
