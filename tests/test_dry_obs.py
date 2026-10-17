"""R3.11: observation cells that go dry during a calibration run.

Without Newton, MF6 writes -1e30 for the head of a dry cell. PEST++ read that
straight from the obs CSV, so a single dry observation made phi ~1e60 and broke
the derivatives. The forward wrapper now replaces the sentinel in head
observation columns with the cell's bottom elevation (the highest head a dry
cell can have), so a dried-out site costs a finite, monotone residual.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pandas as pd
import pyemu
import pytest

from groundwater_mcp.tools.calibration import (
    _dry_obs_fill_plan,
    _impl_check_parameter_sensitivity,
    _impl_setup_calibration,
)
from groundwater_mcp.tools.runner import _impl_run_simulation
from groundwater_mcp.utils.model_store import flush_model, get_gwf, save_sim
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_calibration_practice import _drying_model, _register
from tests.test_setup_calibration import (
    _build_base_model,
    _register_obs,
    requires_mf6,
    requires_pestpp,
)

K_SPEC = {"k": {"target": "npf:k", "scope": "all", "initial": 1.0}}
SITES = [("WET", 0, 8.0), ("DRYWELL", 4, 0.5)]


def _dry(tmp_path, name="dry"):
    name = _drying_model(tmp_path, name)
    _register(tmp_path, name, SITES)
    return name


def _run_command(name, command):
    """Run a pst model command the way pestpp does (cwd = workspace)."""
    ws = resolve_workspace(name)
    proc = subprocess.run(
        shlex.split(command, posix=False), cwd=ws, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return pd.read_csv(ws / f"{get_gwf(name).name}_head.obs.csv")


def test_convertible_observation_cells_get_their_bottom(tmp_path):
    name = _dry(tmp_path)
    plan = _dry_obs_fill_plan(name)
    assert plan == {f"{get_gwf(name).name}_head.obs.csv": {"WET": 0.0, "DRYWELL": 0.0}}


def test_confined_cells_need_no_fill(tmp_path):
    name = _build_base_model(tmp_path, "conf", recharge=1e-3)  # icelltype 0
    _register_obs(tmp_path, name, n_obs=2)
    assert _dry_obs_fill_plan(name) == {}


def test_newton_models_need_no_fill(tmp_path):
    name = _dry(tmp_path, "nwt")
    gwf = get_gwf(name)
    gwf.name_file.newtonoptions.set_data(["NEWTON"])
    save_sim(name, gwf.simulation)
    flush_model(name)
    assert _dry_obs_fill_plan(name) == {}


@requires_mf6
def test_setup_uses_the_wrapper_and_warns_about_dry_sites(tmp_path):
    name = _dry(tmp_path)
    assert _impl_run_simulation(name, silent=True)["success"]
    res = _impl_setup_calibration(name, K_SPEC)
    assert res["dry_cell_handling"]["mode"] == "cell_bottom"
    assert res["dry_cell_handling"]["n_sites"] == 2
    assert "DRYWELL" in res["dry_warning"]
    assert "gwmcp_run_" in " ".join(res["model_command"])


@requires_mf6
def test_wrapper_replaces_the_dry_sentinel_with_the_bottom(tmp_path):
    name = _dry(tmp_path)
    res = _impl_setup_calibration(name, K_SPEC)
    sim = _run_command(name, res["model_command"][0])
    assert float(sim["DRYWELL"].iloc[-1]) == pytest.approx(0.0)
    assert float(sim["WET"].iloc[-1]) == pytest.approx(8.0)
    log = (resolve_workspace(name) / f"{get_gwf(name).name}_dry_obs.txt").read_text()
    assert log.split() == ["DRYWELL"]


@requires_mf6
@requires_pestpp
def test_pestpp_phi_stays_finite_with_a_dry_observation(tmp_path):
    name = _dry(tmp_path)
    res = _impl_setup_calibration(name, K_SPEC, noptmax=0, obs_std=0.1)
    pst_path = Path(res["pst_file"])
    proc = subprocess.run(
        ["pestpp-glm", pst_path.name], cwd=pst_path.parent, capture_output=True,
        text=True, stdin=subprocess.DEVNULL, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
    resid = pyemu.pst_utils.read_resfile(str(pst_path.with_suffix(".rei")))
    assert resid.loc["drywell", "modelled"] == pytest.approx(0.0)
    phi = float(pd.read_csv(pst_path.with_suffix(".iobj"))["total_phi"].iloc[0])
    assert phi == pytest.approx((0.5 / 0.1) ** 2, rel=1e-3)


@requires_mf6
def test_sensitivity_screen_leaves_dry_sites_out(tmp_path):
    name = _dry(tmp_path)
    res = _impl_setup_calibration(name, K_SPEC)
    sens = _impl_check_parameter_sensitivity(name, {"k": 1.0}, res["template_files"])
    assert sens.get("dry_sites") == ["DRYWELL"]
