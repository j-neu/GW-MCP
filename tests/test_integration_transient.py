"""Integration tests — transient simulations through the MCP tool set.

Require the MODFLOW 6 binary. Verify storage (STO) is genuinely active:
heads evolve across time steps, the budget contains STO terms, and the
transient-without-STO guard fires a loud warning.
"""

from __future__ import annotations

import shutil

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
from groundwater_mcp.tools.runner import (
    _find_mf6_binary,
    _impl_check_model,
    _impl_run_simulation,
)


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


def _pestpp_available() -> bool:
    return shutil.which("pestpp-glm") is not None


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)

requires_pestpp = pytest.mark.skipif(
    not _pestpp_available(), reason="pestpp-glm not installed"
)


@pytest.fixture()
def transient_model(tmp_path, model_name):
    """3-period transient 1-layer 5x5 model with STO; SP0 steady, SP1-2 transient.

    The right-hand CHD drops from 5.0 m (SP0, steady) to 2.0 m (SP1-2), so the
    transient periods see changing stress and heads genuinely evolve with time.
    """
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(
        model_name, nper=3, perlen=[100.0, 100.0, 100.0], nstp=[3, 3, 3], ims_complexity="simple"
    )
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=1, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    _impl_add_sto_package(
        model_name, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True
    )
    chd_sp0 = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 5.0] for row in range(5)]
    chd_sp1 = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 2.0] for row in range(5)]
    _impl_add_boundary_package(
        model_name, "CHD", {"0": chd_sp0, "1": chd_sp1, "2": chd_sp1}, None
    )
    _impl_add_oc_package(model_name, None, None, None, None)
    return model_name


@requires_mf6
def test_transient_model_runs_and_converges(transient_model):
    r = _impl_run_simulation(transient_model, silent=True)
    assert "error" not in r
    assert r["success"] is True
    assert r["convergence"] == "converged"
    assert "warning" not in r  # STO present -> no guard warning


@requires_mf6
def test_transient_heads_evolve_across_time(transient_model):
    """With storage active, head at the last time step must differ from the first."""
    from groundwater_mcp.tools.postprocess import _impl_read_heads

    _impl_run_simulation(transient_model, silent=True)
    h0 = _impl_read_heads(transient_model, kstpkper=[0, 0], layer=0, include_values=True)
    h2 = _impl_read_heads(transient_model, kstpkper=[2, 2], layer=0, include_values=True)
    flat0 = [v for row in h0["values"] for v in row]
    flat2 = [v for row in h2["values"] for v in row]
    max_diff = max(abs(x - y) for x, y in zip(flat0, flat2))
    assert max_diff > 1e-3, f"heads static across time steps — storage inactive: {max_diff}"


@requires_mf6
def test_transient_water_balance_contains_sto(transient_model):
    from groundwater_mcp.tools.postprocess import _impl_compute_water_balance

    _impl_run_simulation(transient_model, silent=True)
    wb = _impl_compute_water_balance(transient_model, kstpkper=[2, 2])
    labels = {**wb["inflow"], **wb["outflow"]}
    assert any(k.upper().startswith("STO") for k in labels), f"no STO budget term: {labels}"


@requires_mf6
def test_transient_without_sto_warns(tmp_path, model_name):
    """The exact trap from the review: transient config without STO must warn."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(
        model_name, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple"
    )
    _impl_add_dis_package(model_name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(model_name, icelltype=1, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(model_name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(model_name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(model_name, None, None, None, None)

    r = _impl_check_model(model_name)
    assert r["check_passed"] is True
    assert any("STO" in w.get("package", "").upper() for w in r["warnings"]), r["warnings"]

    r = _impl_run_simulation(model_name, silent=True)
    assert r["success"] is True
    assert "warning" in r and "STO" in r["warning"], r


@requires_pestpp
def test_transient_calibration_chain(transient_model):
    """setup_pest_control -> run_pestpp_glm -> summarise_calibration on a transient model."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_pest_control,
        _impl_summarise_calibration,
    )
    from groundwater_mcp.utils.workspace import resolve_workspace

    model = transient_model
    _impl_run_simulation(model, silent=True)
    ws = resolve_workspace(model)

    (ws / "k_mult.tpl").write_text("ptf ~\n~  kmult       ~\n")
    (ws / "k_mult").write_text("10.0\n")
    (ws / "obs_heads.ins").write_text(
        "pif @\n" + "\n".join(f"l1 !h{i}!" for i in range(1, 6)) + "\n"
    )
    obs_vals = [7.0, 6.5, 5.5, 4.5, 4.0]
    (ws / "obs_heads").write_text("\n".join(str(v) for v in obs_vals) + "\n")

    obs_data = {f"h{i}": {"obsval": v, "weight": 1.0} for i, v in enumerate(obs_vals, 1)}
    par_data = {"kmult": {"parval1": 1.0, "parlbnd": 0.01, "parubnd": 100.0, "pargp": "hk"}}

    setup = _impl_setup_pest_control(
        model=model,
        obs_data=obs_data,
        par_data=par_data,
        template_files=[str(ws / "k_mult.tpl")],
        instruction_files=[str(ws / "obs_heads.ins")],
        pestpp_options={"noptmax": 3},
    )
    assert "error" not in setup

    run = _impl_run_pestpp_glm(model, setup["pst_file"])
    assert "error" not in run
    assert run["iterations"] >= 0

    # The synthetic obs file is static (the forward model never regenerates
    # it), so GLM cannot build a Jacobian and dies before writing residuals.
    # 7e-B2: summarise_calibration must fail loudly rather than report a
    # successful-looking empty result.
    with pytest.raises(FileNotFoundError, match="residual"):
        _impl_summarise_calibration(model, setup["pst_file"])
