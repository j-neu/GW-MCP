"""GWE (groundwater energy transport) support tests."""

from __future__ import annotations

from pathlib import Path

import flopy.mf6 as mf6
import pytest

from groundwater_mcp.tools.runner import _find_mf6_binary


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 not installed")


def _build_flow_and_heat(root: Path):
    flow_ws = root / "flow"
    flow_ws.mkdir()
    sim = mf6.MFSimulation(sim_name="f", version="mf6", sim_ws=str(flow_ws))
    mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = mf6.ModflowGwf(sim, modelname="gwf", model_nam_file="gwf.nam", save_flows=True)
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    mf6.ModflowGwfnpf(
        gwf, icelltype=0, k=1.0, save_flows=True,
        save_specific_discharge=True, save_saturation=True,
    )
    mf6.ModflowGwfic(gwf, strt=1.0)
    mf6.ModflowGwfchd(
        gwf,
        auxiliary="TEMPERATURE",
        stress_period_data={0: [[(0, 0, 0), 1.0, 20.0], [(0, 2, 2), 0.0, 0.0]]},
        pname="CHD",
    )
    mf6.ModflowGwfoc(
        gwf,
        head_filerecord="gwf.hds",
        budget_filerecord="gwf.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    ok, buff = sim.run_simulation(silent=True)
    assert ok, "\n".join(buff or [])

    heat_ws = root / "heat"
    heat_ws.mkdir()
    hsim = mf6.MFSimulation(sim_name="h", version="mf6", sim_ws=str(heat_ws))
    mf6.ModflowTdis(hsim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="DAYS")
    mf6.ModflowIms(hsim, complexity="SIMPLE", linear_acceleration="BICGSTAB")
    gwe = mf6.ModflowGwe(hsim, modelname="gwe", model_nam_file="gwe.nam")
    mf6.ModflowGwedis(gwe, nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    mf6.ModflowGweic(gwe, strt=0.0)
    mf6.ModflowGweadv(gwe, scheme="TVD")
    mf6.ModflowGwecnd(gwe, alh=0.0, ath1=0.0, ktw=48.384, kts=216.0)
    mf6.ModflowGweest(
        gwe,
        porosity=0.2,
        heat_capacity_water=4180.0,
        density_solid=2650.0,
        heat_capacity_solid=900.0,
    )
    mf6.ModflowGwessm(gwe, sources=[("CHD", "AUX", "TEMPERATURE")])
    mf6.ModflowGweoc(
        gwe,
        temperature_filerecord="gwe.ucn",
        budget_filerecord="gwe.cbc",
        saverecord=[("TEMPERATURE", "LAST")],
    )
    mf6.ModflowGwefmi(
        gwe,
        packagedata=[
            ("GWFHEAD", "../flow/gwf.hds", None),
            ("GWFBUDGET", "../flow/gwf.cbc", None),
        ],
    )
    hsim.write_simulation(silent=True)
    ok, buff = hsim.run_simulation(silent=True)
    if not ok:
        raise AssertionError((heat_ws / "gwe.lst").read_text(errors="replace"))
    return heat_ws


@requires_mf6
def test_gwe_fmi_two_simulation_run_and_temperature_reader(tmp_path):
    import flopy.utils as fu

    heat_ws = _build_flow_and_heat(tmp_path)
    ucn = heat_ws / "gwe.ucn"
    assert ucn.exists()

    data = None
    for precision in ("double", "single"):
        try:
            reader = fu.HeadFile(str(ucn), text="TEMPERATURE", precision=precision)
            data = reader.get_data()
            break
        except EOFError:
            continue
    assert data is not None, "could not read the GWE temperature file"
    assert data.shape == (1, 3, 3)
    assert float(data.min()) > -50.0  # plausible temperatures, not garbage
