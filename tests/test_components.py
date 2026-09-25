"""Tests for multi-model (component) support."""

from __future__ import annotations

import flopy.mf6 as mf6
import pytest

from groundwater_mcp.utils import components


def test_registry_has_builtin_components():
    specs = components.all_components()
    assert set(specs) >= {"gwf", "gwe", "prt"}


def test_model_classes_resolve():
    assert components.model_class_for("gwf") is mf6.ModflowGwf
    assert components.model_class_for("gwe") is mf6.ModflowGwe
    assert components.model_class_for("prt") is mf6.ModflowPrt


def test_grid_classes_resolve_per_component():
    assert components.grid_class_for("gwf", "dis") is mf6.ModflowGwfdis
    assert components.grid_class_for("gwe", "disv") is mf6.ModflowGwedisv
    assert components.grid_class_for("prt", "dis") is mf6.ModflowPrtdis
    # PRT has no DISU grid class
    assert components.grid_class_for("prt", "disu") is None


def test_unknown_component_raises_value_error():
    with pytest.raises(ValueError, match="Unknown component"):
        components.spec_for("gwt")


def test_register_component_extends_registry():
    class FakeModel:
        pass

    components.register_component(
        "fake", model_class=FakeModel, grid_classes={"dis": FakeModel}
    )
    assert components.model_class_for("fake") is FakeModel
    assert "fake" in components.all_components()


def _two_model_sim(tmp_path):
    """Write a two-model (gwf + gwe) simulation to disk and register it."""
    from groundwater_mcp.utils.model_store import cache_sim
    from groundwater_mcp.utils.workspace import create_workspace

    ws = tmp_path / "ws_two"
    ws.mkdir()
    sim = mf6.MFSimulation(sim_name="mfsim", version="mf6", sim_ws=str(ws))
    mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    mf6.ModflowIms(sim)
    gwf = mf6.ModflowGwf(sim, modelname="run_a", model_nam_file="run_a.nam")
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    gwe = mf6.ModflowGwe(sim, modelname="run_a_gwe", model_nam_file="run_a_gwe.nam")
    mf6.ModflowGwedis(gwe, nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    mf6.ModflowGwfgwe(sim, exgmnamea="run_a", exgmnameb="run_a_gwe")
    sim.write_simulation(silent=True)
    create_workspace("run_a", str(ws))
    cache_sim("run_a", sim)
    return sim


def test_detect_components(tmp_path):
    from groundwater_mcp.utils import model_store

    sim = _two_model_sim(tmp_path)
    assert model_store.detect_components(sim) == {"gwf": "run_a", "gwe": "run_a_gwe"}


def test_get_model_resolves_component(tmp_path):
    from groundwater_mcp.utils import model_store

    _two_model_sim(tmp_path)
    assert model_store.get_model("run_a", "gwf").name == "run_a"
    assert model_store.get_model("run_a", "gwe").name == "run_a_gwe"
    assert model_store.get_gwf("run_a").name == "run_a"


def test_get_model_unknown_component_raises(tmp_path):
    from groundwater_mcp.utils import model_store

    _two_model_sim(tmp_path)
    with pytest.raises(KeyError, match="Available components"):
        model_store.get_model("run_a", "prt")


def test_create_model_writes_components(tmp_path):
    from groundwater_mcp.tools.builder import _impl_create_model
    from groundwater_mcp.utils.model_store import read_meta

    _impl_create_model("cmp_create", str(tmp_path / "cmp_create"), "METERS", "DAYS")
    assert read_meta("cmp_create")["components"] == {"gwf": "cmp_create"}


def test_adopt_model_detects_components(tmp_path):
    from groundwater_mcp.tools.builder import _impl_adopt_model
    from groundwater_mcp.utils.model_store import read_meta

    _two_model_sim(tmp_path)  # writes mfsim.nam + models to tmp_path/ws_two
    _impl_adopt_model("cmp_adopt", str(tmp_path / "ws_two"), "METERS", "DAYS")
    assert read_meta("cmp_adopt")["components"] == {"gwf": "run_a", "gwe": "run_a_gwe"}


def test_add_component_model_mirrors_grid_and_exchange(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    _impl_create_model("cmp_add", str(tmp_path / "cmp_add"), "METERS", "DAYS")
    _impl_set_simulation("cmp_add", 1, [1.0], [1], "moderate")
    _impl_add_dis_package(
        "cmp_add", nlay=1, nrow=2, ncol=3, delr=2.0, delc=2.0, top=5.0, botm=[0.0]
    )
    result = _impl_add_component_model("cmp_add", "gwe")
    assert result["component"] == "gwe"
    assert result["grid_type"] == "DIS"

    sim = model_store.get_sim("cmp_add")
    assert set(sim.model_names) == {"cmp_add", "cmp_add_gwe"}
    gwe_dis = model_store.get_model("cmp_add", "gwe").get_package("dis")
    assert int(gwe_dis.nrow.data) == 2 and int(gwe_dis.ncol.data) == 3
    assert model_store.component_map("cmp_add")["gwe"] == "cmp_add_gwe"
    # exchange written on flush
    model_store.flush_model("cmp_add")
    assert (tmp_path / "cmp_add" / "mfsim.gwfgwe").exists()


def test_add_component_model_rejects_duplicate(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_create_model,
    )

    _impl_create_model("cmp_dup", str(tmp_path / "cmp_dup"), "METERS", "DAYS")
    _impl_add_dis_package("cmp_dup", nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_component_model("cmp_dup", "gwe")
    with pytest.raises(ValueError, match="already"):
        _impl_add_component_model("cmp_dup", "gwe")


def test_add_dis_and_ic_per_component(tmp_path):
    import flopy.mf6 as mf6

    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_create_model,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "cmp_shared"
    _impl_create_model("cmp_shared", str(ws), "METERS", "DAYS")
    _impl_add_dis_package(
        "cmp_shared", nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0]
    )
    _impl_add_component_model("cmp_shared", "gwe")
    _impl_add_ic_package("cmp_shared", strt=10.0)
    _impl_add_ic_package("cmp_shared", strt=20.0, component="gwe")

    gwf_ic = model_store.get_model("cmp_shared", "gwf").get_package("ic")
    gwe_ic = model_store.get_model("cmp_shared", "gwe").get_package("ic")
    assert float(gwf_ic.strt.array.ravel()[0]) == 10.0
    assert float(gwe_ic.strt.array.ravel()[0]) == 20.0
    assert isinstance(gwe_ic, mf6.ModflowGweic)


def test_summarise_model_reports_components(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_create_model,
        _impl_summarise_model,
    )

    _impl_create_model("cmp_sum", str(tmp_path / "cmp_sum"), "METERS", "DAYS")
    _impl_add_dis_package(
        "cmp_sum", nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0]
    )
    _impl_add_component_model("cmp_sum", "gwe")
    out = _impl_summarise_model("cmp_sum")
    assert set(out["components"]) == {"gwf", "gwe"}
    assert out["components"]["gwe"]["model"] == "cmp_sum_gwe"
    assert out["components"]["gwf"]["model"] == "cmp_sum"


def test_model_status_reports_components(tmp_path):
    from groundwater_mcp.tools.builder import (
        _compute_model_status,
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_create_model,
    )

    _impl_create_model("cmp_stat", str(tmp_path / "cmp_stat"), "METERS", "DAYS")
    _impl_add_dis_package(
        "cmp_stat", nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0]
    )
    _impl_add_component_model("cmp_stat", "gwe")
    assert set(_compute_model_status("cmp_stat")["components"]) == {"gwf", "gwe"}


def test_restore_oc_gated_to_gwf(tmp_path):
    """A non-GWF OC must be left alone by the GWF-specific OC restore."""
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "ws_gate"
    ws.mkdir()
    sim = mf6.MFSimulation(sim_name="mfsim", version="mf6", sim_ws=str(ws))
    mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    mf6.ModflowIms(sim)
    gwf = mf6.ModflowGwf(sim, modelname="g1", model_nam_file="g1.nam")
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    gwe = mf6.ModflowGwe(sim, modelname="g1_gwe", model_nam_file="g1_gwe.nam")
    mf6.ModflowGwedis(gwe, nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    mf6.ModflowGweoc(gwe, filename="g1_gwe.oc")
    mf6.ModflowGwfgwe(sim, exgmnamea="g1", exgmnameb="g1_gwe")
    (ws / "g1_gwe.oc_1.txt").write_text("SAVE HEAD FIRST\n")
    (ws / "g1_gwe.oc").write_text(
        "BEGIN PERIOD 1\n  OPEN/CLOSE g1_gwe.oc_1.txt\nEND PERIOD\n"
    )

    model_store.restore_oc_period_records(sim, ws)
    oc = gwe.get_package("oc")
    assert not oc.saverecord.data  # untouched: non-gwf OC is skipped


def test_get_run_log_component_param(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_create_model,
    )
    from groundwater_mcp.tools.runner import _impl_get_run_log
    from groundwater_mcp.utils.model_store import flush_model

    ws = tmp_path / "cmp_log"
    _impl_create_model("cmp_log", str(ws), "METERS", "DAYS")
    _impl_add_dis_package(
        "cmp_log", nlay=1, nrow=2, ncol=3, delr=1.0, delc=1.0, top=1.0, botm=[0.0]
    )
    flush_model("cmp_log")
    (ws / "mfsim.lst").write_text("Normal termination\n")
    out = _impl_get_run_log("cmp_log", tail=5, component="gwf")
    assert out["listing_file"].endswith("mfsim.lst")
