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


# ---------------------------------------------------------------------------
# Task 2: component-simulation cache
# ---------------------------------------------------------------------------


def test_component_sim_cache_roundtrip(tmp_path):
    from groundwater_mcp.utils import model_store

    component = mf6.MFSimulation(sim_name="heat", version="mf6", sim_ws=str(tmp_path / "heat"))
    model_store.cache_component_sim("gwe_cache", "gwe", component)
    assert model_store.get_component_sim("gwe_cache", "gwe") is component
    assert model_store.component_sim_names("gwe_cache") == ["gwe"]
    with pytest.raises(KeyError, match="add_gwe_model"):
        model_store.get_component_sim("gwe_cache", "prt")
    # invalidate() forces a flow reload but keeps derived component simulations
    model_store.invalidate("gwe_cache")
    assert model_store.get_component_sim("gwe_cache", "gwe") is component
    model_store.invalidate_component_sim("gwe_cache", "gwe")
    with pytest.raises(KeyError):
        model_store.get_component_sim("gwe_cache", "gwe")


def test_flush_writes_component_sim(tmp_path):
    from groundwater_mcp.tools.builder import _impl_create_model
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "gwe_flush"
    _impl_create_model("gwe_flush", str(ws), "METERS", "DAYS")
    csim = mf6.MFSimulation(sim_name="heat", version="mf6", sim_ws=str(ws / "gwe"))
    import flopy.mf6 as m6

    m6.ModflowTdis(csim, nper=1, perioddata=[(1.0, 1, 1.0)])
    m6.ModflowIms(csim, complexity="SIMPLE", linear_acceleration="BICGSTAB")
    gwe = m6.ModflowGwe(csim, modelname="gf_gwe", model_nam_file="gf_gwe.nam")
    m6.ModflowGwedis(gwe, nlay=1, nrow=2, ncol=2, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    model_store.cache_component_sim("gwe_flush", "gwe", csim)
    model_store.save_sim("gwe_flush", model_store.get_sim("gwe_flush"))
    assert model_store.flush_model("gwe_flush") is True
    assert (ws / "gwe" / "mfsim.nam").exists()
    assert (ws / "gwe" / "gf_gwe.nam").exists()


# ---------------------------------------------------------------------------
# Task 3: add_gwe_model (FMI)
# ---------------------------------------------------------------------------


def test_add_gwe_model_creates_fmi_simulation(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_gwe_model,
        _impl_add_npf_package,
        _impl_add_oc_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "gm"
    _impl_create_model("gm", str(ws), "METERS", "DAYS")
    _impl_set_simulation("gm", 1, [1.0], [1], "moderate")
    _impl_add_dis_package("gm", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("gm", 0, 1.0, None, True)
    _impl_add_oc_package("gm", "gm.hds", "gm.cbc", [("HEAD", "ALL")], None)

    out = _impl_add_gwe_model("gm")
    assert out["component"] == "gwe"
    hsim = model_store.get_component_sim("gm", "gwe")
    gwe = hsim.get_model(model_store.component_map("gm")["gwe"])
    assert gwe.get_package("fmi") is not None
    assert model_store.component_workspace("gm", "gwe") == "gwe"
    # FMI requires the flow model to save specific discharge/saturation.
    npf = model_store.get_model("gm", "gwf").get_package("npf")
    assert npf.save_specific_discharge is not None
    assert npf.save_saturation is not None


# ---------------------------------------------------------------------------
# Task 4: GWE packages + GWE OC + CHD auxiliary
# ---------------------------------------------------------------------------


def test_gwe_packages_and_oc(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_gwe_adv_package,
        _impl_add_gwe_cnd_package,
        _impl_add_gwe_esl_package,
        _impl_add_gwe_est_package,
        _impl_add_gwe_model,
        _impl_add_gwe_ssm_package,
        _impl_add_oc_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "pk"
    _impl_create_model("pk", str(ws), "METERS", "DAYS")
    _impl_set_simulation("pk", 1, [1.0], [1], "moderate")
    _impl_add_dis_package("pk", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_gwe_model("pk")
    _impl_add_gwe_adv_package("pk", scheme="TVD")
    _impl_add_gwe_cnd_package("pk", alh=0.0, ath1=0.0, ktw=48.384, kts=216.0)
    _impl_add_gwe_est_package(
        "pk", porosity=0.2, heat_capacity_water=4180.0,
        density_solid=2650.0, heat_capacity_solid=900.0,
    )
    _impl_add_gwe_ssm_package("pk", sources=[("CHD", "AUX", "TEMPERATURE")])
    _impl_add_gwe_esl_package("pk", stress_period_data={0: [[0, 0, 100.0]]})
    _impl_add_oc_package(
        "pk", "pk.ucn", "pk.cbc",
        [("TEMPERATURE", "LAST")], None, component="gwe",
    )
    gwe = model_store.get_model("pk", "gwe")
    for name in ("adv", "cnd", "est", "ssm", "esl", "oc"):
        assert gwe.get_package(name) is not None, f"missing {name}"


def test_chd_auxiliary_temperature(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_boundary_package,
        _impl_add_dis_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    _impl_create_model("auxmod", str(tmp_path / "auxmod"), "METERS", "DAYS")
    _impl_set_simulation("auxmod", 1, [1.0], [1], "moderate")
    _impl_add_dis_package("auxmod", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_boundary_package(
        "auxmod", "CHD",
        {0: [[(0, 0, 0), 1.0, 20.0], [(0, 2, 2), 0.0, 0.0]]},
        {"auxiliary": "TEMPERATURE"}, pname="CHD",
    )
    chd = model_store.get_model("auxmod", "gwf").get_package("chd")
    assert chd is not None
    assert "TEMPERATURE" in str(chd.auxiliary.array.tolist()).upper()


# ---------------------------------------------------------------------------
# Task 5: run flow then heat
# ---------------------------------------------------------------------------


def test_run_simulation_runs_heat_after_flow(tmp_path, monkeypatch):
    from groundwater_mcp.tools import builder, runner
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "rk"
    builder._impl_create_model("rk", str(ws), "METERS", "DAYS")
    builder._impl_set_simulation("rk", 1, [1.0], [1], "moderate")
    builder._impl_add_dis_package("rk", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    builder._impl_add_npf_package("rk", 0, 1.0, None, True)
    builder._impl_add_ic_package("rk", 1.0)
    builder._impl_add_oc_package("rk", "rk.hds", "rk.cbc", [("HEAD", "ALL")], None)
    builder._impl_add_gwe_model("rk")
    builder._impl_add_dis_package(
        "rk", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0], component="gwe"
    )

    flow_sim = model_store.get_sim("rk")
    heat_sim = model_store.get_component_sim("rk", "gwe")
    flow_sim.run_simulation = lambda **kw: (True, ["flow ok"])
    heat_sim.run_simulation = lambda **kw: (True, ["heat ok"])
    monkeypatch.setattr(runner, "_find_mf6_binary", lambda: "mf6")

    out = runner._impl_run_simulation("rk", silent=True)
    assert out["success"] is True
    assert [c["component"] for c in out["components"]] == ["gwe"]
    assert out["components"][0]["success"] is True


def test_heat_run_skipped_when_flow_fails(tmp_path, monkeypatch):
    from groundwater_mcp.tools import builder, runner
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "rk2"
    builder._impl_create_model("rk2", str(ws), "METERS", "DAYS")
    builder._impl_set_simulation("rk2", 1, [1.0], [1], "moderate")
    builder._impl_add_dis_package("rk2", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    builder._impl_add_npf_package("rk2", 0, 1.0, None, True)
    builder._impl_add_ic_package("rk2", 1.0)
    builder._impl_add_oc_package("rk2", "rk2.hds", "rk2.cbc", [("HEAD", "ALL")], None)
    builder._impl_add_gwe_model("rk2")

    flow_sim = model_store.get_sim("rk2")
    heat_sim = model_store.get_component_sim("rk2", "gwe")
    flow_sim.run_simulation = lambda **kw: (False, ["flow failed"])
    ran = {"heat": False}

    def _heat(**kw):
        ran["heat"] = True
        return True, []

    heat_sim.run_simulation = _heat
    monkeypatch.setattr(runner, "_find_mf6_binary", lambda: "mf6")

    out = runner._impl_run_simulation("rk2", silent=True)
    assert out["success"] is False
    assert out["components"][0]["success"] is False
    assert out["components"][0]["skipped"] == "flow run failed"
    assert ran["heat"] is False


# ---------------------------------------------------------------------------
# Task 6: read_temperature (end-to-end)
# ---------------------------------------------------------------------------


@requires_mf6
def test_read_temperature_end_to_end(tmp_path):
    from groundwater_mcp.tools import builder, postprocess, runner

    ws = tmp_path / "rt"
    builder._impl_create_model("rt", str(ws), "METERS", "DAYS")
    builder._impl_set_simulation("rt", 1, [1.0], [1], "moderate")
    builder._impl_add_dis_package("rt", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    builder._impl_add_npf_package("rt", 0, 1.0, None, True)
    builder._impl_add_ic_package("rt", 1.0)
    builder._impl_add_boundary_package(
        "rt", "CHD",
        {0: [[(0, 0, 0), 1.0, 20.0], [(0, 2, 2), 0.0, 0.0]]},
        {"auxiliary": "TEMPERATURE"}, pname="CHD",
    )
    builder._impl_add_oc_package("rt", "rt.hds", "rt.cbc", [("HEAD", "ALL"), ("BUDGET", "ALL")], None)
    builder._impl_add_gwe_model("rt")
    builder._impl_add_dis_package(
        "rt", nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0], component="gwe"
    )
    builder._impl_add_ic_package("rt", 0.0, component="gwe")
    builder._impl_add_gwe_adv_package("rt", "TVD")
    builder._impl_add_gwe_cnd_package("rt", alh=0.0, ath1=0.0, ktw=48.384, kts=216.0)
    builder._impl_add_gwe_est_package(
        "rt", porosity=0.2, heat_capacity_water=4180.0,
        density_solid=2650.0, heat_capacity_solid=900.0,
    )
    builder._impl_add_gwe_ssm_package("rt", sources=[("CHD", "AUX", "TEMPERATURE")])
    builder._impl_add_oc_package(
        "rt", "rt_gwe.ucn", "rt_gwe.cbc", [("TEMPERATURE", "ALL")], None, component="gwe"
    )

    out = runner._impl_run_simulation("rt", silent=True)
    if not out["success"]:
        heat_lst = ws / "gwe" / "rt_gwe.lst"
        detail = heat_lst.read_text(errors="replace") if heat_lst.exists() else ""
        raise AssertionError(f"{out}\n{detail[-2000:]}")

    temp = postprocess._impl_read_temperature("rt")
    assert temp["component"] == "gwe"
    assert temp["shape"] == [3, 3]
    assert temp["n_active"] == 9
    assert temp["max"] >= 0.0


# ---------------------------------------------------------------------------
# Task 7: temperature plots
# ---------------------------------------------------------------------------


def _build_and_run_heat(tmp_path, name: str = "pt"):
    from groundwater_mcp.tools import builder, runner

    ws = tmp_path / name
    builder._impl_create_model(name, str(ws), "METERS", "DAYS")
    builder._impl_set_simulation(name, 2, [0.5, 0.5], [1, 1], "moderate")
    builder._impl_add_dis_package(name, nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    builder._impl_add_npf_package(name, 0, 1.0, None, True)
    builder._impl_add_ic_package(name, 1.0)
    builder._impl_add_boundary_package(
        name, "CHD",
        {0: [[(0, 0, 0), 1.0, 20.0], [(0, 2, 2), 0.0, 0.0]]},
        {"auxiliary": "TEMPERATURE"}, pname="CHD",
    )
    builder._impl_add_oc_package(name, f"{name}.hds", f"{name}.cbc",
                                 [("HEAD", "ALL"), ("BUDGET", "ALL")], None)
    builder._impl_add_gwe_model(name)
    builder._impl_add_dis_package(name, nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0,
                                  top=1.0, botm=[0.0], component="gwe")
    builder._impl_add_ic_package(name, 0.0, component="gwe")
    builder._impl_add_gwe_adv_package(name, "TVD")
    builder._impl_add_gwe_cnd_package(name, alh=0.0, ath1=0.0, ktw=48.384, kts=216.0)
    builder._impl_add_gwe_est_package(name, porosity=0.2, heat_capacity_water=4180.0,
                                      density_solid=2650.0, heat_capacity_solid=900.0)
    builder._impl_add_gwe_ssm_package(name, sources=[("CHD", "AUX", "TEMPERATURE")])
    builder._impl_add_oc_package(name, f"{name}_gwe.ucn", f"{name}_gwe.cbc",
                                 [("TEMPERATURE", "ALL")], None, component="gwe")
    out = runner._impl_run_simulation(name, silent=True)
    assert out["success"] is True, out.get("components")
    return ws


@requires_mf6
def test_temperature_plots(tmp_path):
    from groundwater_mcp.tools import postprocess

    ws = _build_and_run_heat(tmp_path, "pt")

    m = postprocess._impl_plot_temperature_map("pt", output_file=str(ws / "tmap.png"))
    assert m["component"] == "gwe"
    assert Path(m["output_file"]).exists()

    obs = ws / "obs.csv"
    obs.write_text("0.0,0.0\n0.5,5.0\n1.0,8.0\n")
    ts = postprocess._impl_plot_temperature_timeseries(
        "pt", cells=[4], observed_csv=str(obs), output_file=str(ws / "ts.png")
    )
    assert Path(ts["output_file"]).exists()
    assert ts["n_times"] == 2
    assert ts["has_observed"] is True
