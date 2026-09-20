"""7f-H tests — encode expertise as behaviour, not prose.

H1: dimensional arguments carry units; conductance is derived, not guessed.
H2: run_simulation(auto_fix=True) escalation ladder.
H3: check_parameter_sensitivity n+1 screen + setup_pest_control warning.
H4: calibrate method choice + calibration verdict.

See tasks.md § 7f Tier H.
"""

from __future__ import annotations

import csv
from pathlib import Path

import flopy.mf6 as mf6
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
from groundwater_mcp.tools.calibration import (
    _choose_method,
    _impl_check_parameter_sensitivity,
    _impl_setup_pest_control,
    _impl_summarise_calibration,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.runner import _find_mf6_binary
from groundwater_mcp.utils.model_store import get_gwf, get_sim, save_sim
from groundwater_mcp.utils.workspace import create_workspace, resolve_workspace


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
# H1.1 — units
# ---------------------------------------------------------------------------


def _small_base_model(tmp_path, name: str = "units_model") -> str:
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    return name


def test_npf_k_units_conversion(tmp_path):
    name = _small_base_model(tmp_path)
    _impl_add_npf_package(name, 1, 1e-5, 1e-7, True, k_units="m/s")
    from groundwater_mcp.utils.model_store import flush_model

    flush_model(name)
    k = float(np.asarray(get_gwf(name).npf.k.array).ravel()[0])
    assert k == pytest.approx(0.864, abs=1e-6)


def test_npf_k_units_recorded_in_meta(tmp_path):
    name = _small_base_model(tmp_path)
    _impl_add_npf_package(name, 1, 10.0, 1.0, True, k_units="m/d")
    summary = _impl_summarise_model(name)
    assert summary["units"]["k"] == "m/d"
    assert summary["units"]["time"] == "DAYS"
    assert summary["units"]["length"] == "METERS"


def test_rch_rate_units_conversion(tmp_path):
    name = _small_base_model(tmp_path)
    _impl_add_boundary_package(
        name, "RCH", {"0": [[[0, 0, 0], 300.0]]}, None, True, rate_units="mm/yr"
    )
    from groundwater_mcp.utils.model_store import flush_model, invalidate

    flush_model(name)
    invalidate(name)
    rec = np.asarray(get_gwf(name).rch.stress_period_data.array).ravel()[0]
    rate = float(rec["recharge"])
    assert rate == pytest.approx(8.219e-4, abs=1e-7)
    assert _impl_summarise_model(name)["units"]["recharge"] == "mm/yr"


def test_unknown_k_units_rejected(tmp_path):
    name = _small_base_model(tmp_path)
    with pytest.raises(ValueError, match="k_units"):
        _impl_add_npf_package(name, 1, 10.0, None, True, k_units="parsecs/week")


def _small_feet_model(tmp_path, name: str = "feet_units") -> str:
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "FEET", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    return name


def test_npf_k_units_respect_model_length_unit(tmp_path):
    """In a FEET model, k_units="ft/d", k=10 must write 10 (not 3.048).

    7f-H1.1 converted k into **metres** regardless of the model's length unit,
    so a FEET model silently received a 0.3048x K and callers had to compensate
    with 32.808 (6d Target 9 rerun-3).
    """
    from groundwater_mcp.utils.model_store import flush_model

    name = _small_feet_model(tmp_path)
    _impl_add_npf_package(name, 1, 10.0, 0.01, True, k_units="ft/d")
    flush_model(name)
    k = float(np.asarray(get_gwf(name).npf.k.array).ravel()[0])
    k33 = float(np.asarray(get_gwf(name).npf.k33.array).ravel()[0])
    assert k == pytest.approx(10.0, rel=1e-9)
    assert k33 == pytest.approx(0.01, rel=1e-9)


def test_npf_k_units_convert_metres_into_feet(tmp_path):
    """k_units="m/d", k=10 in a FEET model must write 32.808 ft/d."""
    from groundwater_mcp.utils.model_store import flush_model

    name = _small_feet_model(tmp_path, "feet_units2")
    _impl_add_npf_package(name, 1, 10.0, None, True, k_units="m/d")
    flush_model(name)
    k = float(np.asarray(get_gwf(name).npf.k.array).ravel()[0])
    assert k == pytest.approx(32.80839895, rel=1e-8)


def test_rch_rate_units_respect_model_units(tmp_path):
    """rate_units="mm/yr" in a FEET model must convert to ft/d, not m/d."""
    from groundwater_mcp.utils.model_store import flush_model, invalidate

    name = _small_feet_model(tmp_path, "feet_rch")
    _impl_add_boundary_package(
        name, "RCH", {"0": [[[0, 0, 0], 300.0]]}, None, True, rate_units="mm/yr"
    )
    flush_model(name)
    invalidate(name)
    rec = np.asarray(get_gwf(name).rch.stress_period_data.array).ravel()[0]
    rate = float(rec["recharge"])
    # 300 mm/yr -> 0.3 m/yr -> ft/d in a FEET model (RCH stores float32).
    assert rate == pytest.approx(0.3 / 365.0 / 0.3048, rel=1e-6)


def test_unknown_rate_units_rejected(tmp_path):
    name = _small_base_model(tmp_path)
    with pytest.raises(ValueError, match="rate_units"):
        _impl_add_boundary_package(
            name, "RCH", {"0": [[[0, 0, 0], 1.0]]}, None, True, rate_units="furlongs"
        )


# ---------------------------------------------------------------------------
# H1.2 — conductance derived, not guessed
# ---------------------------------------------------------------------------


def _write_line_shapefile(tmp_path, ncol: int = 5, delr: float = 100.0) -> str:
    import geopandas as gpd
    from shapely.geometry import LineString

    # A straight line along row 2, spanning the grid (no CRS → matches a
    # no-CRS add_dis grid).
    y = 2.5 * delr
    line = LineString([(0.0, y), (ncol * delr, y)])
    gdf = gpd.GeoDataFrame({"geometry": [line]})
    path = tmp_path / "river_line.shp"
    gdf.to_file(path)
    return str(path)


def test_river_conductance_derived_from_bed_properties(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    name = _small_base_model(tmp_path, "riv_deriv")
    shp = _write_line_shapefile(tmp_path)
    result = _impl_import_river_from_shapefile(
        model=name,
        shapefile=shp,
        package="RIV",
        stage_field=None,
        cond_field=None,
        depth_field=None,
        bed_k=1.0,
        bed_thickness=2.0,
        channel_width=10.0,
    )
    assert "error" not in result, result
    from groundwater_mcp.utils.model_store import flush_model, invalidate

    flush_model(name)
    invalidate(name)
    arr = np.asarray(get_gwf(name).riv.stress_period_data.array)
    conds = [float(r["cond"]) for rec in arr for r in rec]
    # cond = bed_k * width * length / thickness = 1 * 10 * 100 / 2 = 500
    for cond in conds:
        assert cond == pytest.approx(500.0, abs=1.0)


def test_river_without_conductance_source_errors(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_river_from_shapefile

    name = _small_base_model(tmp_path, "riv_nocond")
    shp = _write_line_shapefile(tmp_path)
    with pytest.raises(ValueError, match="conductance"):
        _impl_import_river_from_shapefile(model=name, shapefile=shp, package="RIV")

    # Through the MCP layer the same failure is the INVALID_INPUT envelope.
    import asyncio
    import json

    from groundwater_mcp.server import mcp

    result = asyncio.run(mcp.call_tool(
        "import_river_from_shapefile",
        {"model": name, "shapefile": shp, "package": "RIV"},
    ))
    payload = json.loads(result[0].text)
    assert payload.get("error") is True
    assert payload["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# H2 — auto_fix escalation ladder
# ---------------------------------------------------------------------------


def _iteration_starved_model(tmp_path, name: str = "starved") -> str:
    """A model that fails with outer_maximum=1 but converges with more
    iterations (needs a few outer iterations for the convertible-cell solve)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 2, 10, 10, 500.0, 500.0, 50.0, [40.0, 30.0])
    _impl_add_npf_package(name, icelltype=1, k=10.0, k33=1.0, save_flows=True)
    _impl_add_ic_package(name, strt=45.0)
    _impl_add_boundary_package(name, "WEL", {"0": [[[0, 5, 5], -2000.0]]}, None)
    chd = [[[0, r, 0], 70.0] for r in range(10)] + [[[1, r, 0], 40.0] for r in range(10)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    ims = get_sim(name).get_package("ims")
    ims.outer_maximum.set_data(1)
    save_sim(name, get_sim(name))
    return name


@requires_mf6
def test_auto_fix_recovers_iteration_starved_model(tmp_path):
    from groundwater_mcp.tools.runner import _impl_run_simulation

    name = _iteration_starved_model(tmp_path)
    fail = _impl_run_simulation(name, silent=True, auto_fix=False)
    assert fail["success"] is False

    fixed = _impl_run_simulation(name, silent=True, auto_fix=True)
    assert fixed["success"] is True
    assert fixed["convergence"] == "converged"
    applied = fixed.get("auto_fix_applied")
    assert applied, "expected auto_fix_applied changes"
    assert applied[0]["changes"][0]["setting"] == "complexity"
    assert applied[0]["changes"][0]["from"] == "simple"
    assert applied[0]["changes"][0]["to"] == "moderate"


def test_auto_fix_lists_every_rung_on_persistent_failure(tmp_path, monkeypatch):
    """When no rung can make the run converge, every rung is reported."""
    from groundwater_mcp.tools.runner import _IMS_RUNGS, _impl_run_simulation

    name = _iteration_starved_model(tmp_path, "always_fail")

    def always_fail(self, **kwargs):
        return False, ["ERROR: solver failed to converge"]

    monkeypatch.setattr(mf6.MFSimulation, "run_simulation", always_fail)

    result = _impl_run_simulation(name, silent=True, auto_fix=True)
    assert result["success"] is False
    assert len(result.get("auto_fix_applied", [])) == len(_IMS_RUNGS)


# ---------------------------------------------------------------------------
# H3 — sensitivity screen
# ---------------------------------------------------------------------------


def _hk_model_with_obs(tmp_path, name: str = "sens_model", obs_at_chd: bool = False) -> str:
    """A model whose NPF reads k from hk.dat via OPEN/CLOSE, with observations
    at interior cells (or at CHD cells when obs_at_chd)."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 1, 10, 10, 500.0, 500.0, 50.0, [0.0])
    sim = get_sim(name)
    gwf = get_gwf(name)
    arr = np.full((1, 10, 10), 5.0)
    mf6.ModflowGwfnpf(gwf, icelltype=0, k={"filename": "hk.dat", "data": arr}, save_flows=True)
    save_sim(name, sim)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(10)] + [[[0, r, 9], 10.0] for r in range(10)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    # Recharge makes the head solution K-dependent (CHD-only flow is linear in K).
    rch = {"0": [[[0, r, c], 0.001] for r in range(10) for c in range(1, 9)]}
    _impl_add_boundary_package(name, "RCH", rch, None)
    _impl_add_oc_package(name, None, None, None, None)
    flush(name)

    # Template over hk.dat: one token per line (uniform array).
    n_values = 10 * 10
    (Path(ws) / "hk.dat.tpl").write_text("ptf ~\n" + "~      k      ~\n" * n_values)

    # Obs CSV at grid centroids (or CHD cells for the insensitive case)
    from groundwater_mcp.utils.spatial import grid_centroids

    mg = gwf.modelgrid
    xc, yc = grid_centroids(mg)
    cells = [0, 0, 0, 0] if obs_at_chd else [12, 22, 32, 42]
    csv_path = tmp_path / "sens_obs.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for i, cell in enumerate(cells):
            writer.writerow([f"S{i + 1:02d}", "2020-01-01", 30.0, float(xc[cell]), float(yc[cell])])
    _impl_import_obs_from_csv(
        model=name,
        csv_file=str(csv_path),
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )
    return name


def flush(name):
    from groundwater_mcp.utils.model_store import flush_model

    flush_model(name)


@requires_mf6
def test_sensitivity_runs_exactly_n_plus_1_forward_runs(tmp_path, monkeypatch):
    import groundwater_mcp.tools.runner as runner_module

    name = _hk_model_with_obs(tmp_path)
    calls = {"n": 0}
    original = runner_module._impl_run_simulation

    def counting(model, silent=False, auto_fix=False):
        calls["n"] += 1
        return original(model, silent=silent, auto_fix=auto_fix)

    monkeypatch.setattr(runner_module, "_impl_run_simulation", counting)

    result = _impl_check_parameter_sensitivity(
        model=name, parameters={"k": 5.0}, template_files=["hk.dat.tpl"], delta=0.1
    )
    assert "error" not in result, result
    assert calls["n"] == 2  # base + one perturbed run


def test_sensitivity_rejects_parameter_absent_from_template(tmp_path):
    """A parameter that appears in no template would never be substituted and
    would be reported as spurious zero sensitivity — fail loudly instead."""
    name = _hk_model_with_obs(tmp_path)
    with pytest.raises(ValueError, match="do not appear in any template"):
        _impl_check_parameter_sensitivity(
            model=name,
            parameters={"k": 5.0, "ghost": 1.0},
            template_files=["hk.dat.tpl"],
            delta=0.1,
        )


@requires_mf6
def test_sensitivity_flags_insensitive_parameter_at_chd_cell(tmp_path):
    name = _hk_model_with_obs(tmp_path, obs_at_chd=True)
    result = _impl_check_parameter_sensitivity(
        model=name, parameters={"k": 5.0}, template_files=["hk.dat.tpl"], delta=0.1
    )
    assert "error" not in result
    sens = result["parameters"]["k"]["sensitivity"]
    assert sens is not None and sens < 1e-3  # heads pinned by CHD → insensitive


@requires_mf6
def test_sensitivity_reports_sensitive_parameter_at_interior(tmp_path):
    name = _hk_model_with_obs(tmp_path, obs_at_chd=False)
    result = _impl_check_parameter_sensitivity(
        model=name, parameters={"k": 5.0}, template_files=["hk.dat.tpl"], delta=0.1
    )
    assert "error" not in result
    sens = result["parameters"]["k"]["sensitivity"]
    assert sens is not None and sens > 1e-3


@requires_mf6
def test_setup_pest_control_warns_on_insensitive_parameter(tmp_path):
    from groundwater_mcp.utils.model_store import read_meta

    name = _hk_model_with_obs(tmp_path, obs_at_chd=True)
    _impl_check_parameter_sensitivity(
        model=name, parameters={"k": 5.0}, template_files=["hk.dat.tpl"], delta=0.1
    )
    assert "k" in read_meta(name)["sensitivity"]["insensitive"]

    ws = resolve_workspace(name)
    (ws / "k.tpl").write_text("ptf ~\n~      k      ~\n")
    result = _impl_setup_pest_control(
        model=name,
        obs_data={},
        par_data={"k": {"parval1": 5.0, "parlbnd": 0.5, "parubnd": 50.0, "partrans": "log"}},
        template_files=["k.tpl"],
        instruction_files=[],
        obs_source="model",
    )
    assert "error" not in result
    assert result.get("warning") and "k" in result["warning"]


# ---------------------------------------------------------------------------
# H4 — calibrate method choice + verdict
# ---------------------------------------------------------------------------


def test_choose_method_selects_glm_for_small_problem():
    method, rationale = _choose_method(2, 29, 30.0)
    assert method == "glm"
    assert "GLM" in rationale


def test_choose_method_selects_ies_for_many_parameters():
    method, _ = _choose_method(200, 29, 30.0)
    assert method == "ies"


def _write_calib_artifacts(
    tmp_path, model_name, phi_values, par_values, par_at_bound=False, n_resid=1
):
    """Register a workspace and fabricate .pst/.phi/.par/.rei artifacts."""
    ws = str(tmp_path / model_name)
    create_workspace(model_name, ws)
    ws_path = Path(ws)

    (ws_path / "params.tpl").write_text("ptf ~\n~  k  ~\n~  ss  ~\n")
    (ws_path / "heads.ins").write_text("pif @\nl1 !h1!\n")
    pst = _impl_setup_pest_control(
        model=model_name,
        obs_data={"h1": {"obsval": 5.0, "weight": 1.0, "obgnme": "heads"}},
        par_data={
            "k": {"parval1": 10.0, "parlbnd": 0.1, "parubnd": 1000.0, "pargp": "hk"},
            "ss": {"parval1": 0.001, "parlbnd": 1e-6, "parubnd": 0.1, "pargp": "ss"},
        },
        template_files=["params.tpl"],
        instruction_files=["heads.ins"],
    )
    stem = Path(pst["pst_file"]).stem
    pd.DataFrame({"heads": phi_values}).to_csv(ws_path / f"{stem}.phi.actual.csv")
    k_val = 1000.0 if par_at_bound else 42.0
    (ws_path / f"{stem}.par").write_text(
        f"single point\nk        {k_val}  1.0  0\nss       0.005  1.0  0\n"
    )
    rows = "\n".join(
        f"h{i + 1} heads {5.0 + i * 0.01} 4.9 {0.1 + i * 0.01} 1.0"
        for i in range(n_resid)
    )
    (ws_path / f"{stem}.rei").write_text(
        "Run used in this session: summary\n"
        "name group measured modelled residual weight\n"
        + rows
        + "\n"
    )
    return model_name, pst["pst_file"]


def test_summarise_calibration_verdict(tmp_path):
    model, pst_file = _write_calib_artifacts(tmp_path, "verdict", [200.0, 50.0, 10.0], None)
    result = _impl_summarise_calibration(model, pst_file)
    verdict = result["verdict"]
    assert verdict["final_phi"] == pytest.approx(10.0)
    assert verdict["improved"] is True  # no prior baseline → first run
    assert verdict["parameters_at_bounds"] == []

    # Second run with a worse phi → improved: false
    model2, pst2 = _write_calib_artifacts(tmp_path, "verdict2", [50.0, 10.0, 30.0], None)
    _impl_summarise_calibration(model2, pst2)
    second = _impl_summarise_calibration(model2, pst2)["verdict"]
    assert second["final_phi"] == pytest.approx(30.0)
    assert second["prior_phi"] == pytest.approx(30.0)
    assert second["improved"] is False


def test_summarise_calibration_verdict_names_parameter_at_bound(tmp_path):
    model, pst_file = _write_calib_artifacts(
        tmp_path, "bound", [200.0, 50.0, 10.0], None, par_at_bound=True
    )
    verdict = _impl_summarise_calibration(model, pst_file)["verdict"]
    assert "k" in verdict["parameters_at_bounds"]


def test_summarise_calibration_fit_within_measurement_error(tmp_path):
    model, pst_file = _write_calib_artifacts(tmp_path, "fit", [200.0, 50.0, 10.0], None)
    result = _impl_summarise_calibration(model, pst_file, measurement_error=1000.0)
    assert result["verdict"]["fit_within_measurement_error"] is True


def test_summarise_calibration_residual_cap(tmp_path):
    """residuals are capped in the response with the full table to CSV;
    residual_statistics always cover all observations (7e-A1.6)."""
    model, pst_file = _write_calib_artifacts(
        tmp_path, "cap", [200.0, 50.0, 10.0], None, n_resid=5000
    )
    result = _impl_summarise_calibration(model, pst_file, max_residuals=500)
    assert len(result["residuals"]) == 500
    assert result["n_residuals_total"] == 5000
    assert result["residual_statistics"]["n_observations"] == 5000
    csv_path = Path(result["residuals_csv"])
    assert csv_path.exists()
    assert len(pd.read_csv(csv_path)) == 5000
