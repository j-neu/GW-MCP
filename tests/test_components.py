"""Tests for multi-model (component) support."""

from __future__ import annotations

import flopy.mf6 as mf6
import numpy as np
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


# ---------------------------------------------------------------------------
# Review-fix tests (Critical C1 + Important I1-I7)
# ---------------------------------------------------------------------------


def _call_tool(name: str, args: dict):
    import asyncio
    import json

    from groundwater_mcp.server import mcp

    result = asyncio.run(mcp.call_tool(name, args))
    return json.loads(result[0].text)


def test_component_model_name_no_collision_at_16_chars(tmp_path):
    """C1: a legal 16-char base must not truncate onto itself."""
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_create_model,
    )
    from groundwater_mcp.utils import model_store

    name = "abcdefghijklmnop"  # exactly 16 → the MF6 limit
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_add_dis_package(name, nlay=1, nrow=2, ncol=2, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    result = _impl_add_component_model(name, "gwe")
    comp = result["component_model"]
    assert comp != name
    assert len(comp) <= 16
    sim = model_store.get_sim(name)
    assert len(sim.model_names) == 2  # two distinct model names
    assert model_store.component_map(name)["gwe"] == comp


def test_unknown_component_is_invalid_input(tmp_path):
    """I1: a bad component through a tool must be INVALID_INPUT, not MODEL_NOT_FOUND."""
    from groundwater_mcp.tools.builder import _impl_add_dis_package, _impl_create_model

    _impl_create_model("cmp_bad", str(tmp_path / "cmp_bad"), "METERS", "DAYS")
    _impl_add_dis_package("cmp_bad", nlay=1, nrow=2, ncol=2, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    out = _call_tool("add_ic_package", {"model": "cmp_bad", "strt": 1.0, "component": "gwt"})
    assert out["error"] is True
    assert out["code"] == "INVALID_INPUT"
    assert "Available components" in out["message"]


def test_get_run_log_unknown_component_errors(tmp_path):
    """I2: get_run_log must not silently fall back to mfsim.lst for a bad component."""
    from groundwater_mcp.tools.builder import _impl_add_dis_package, _impl_create_model
    from groundwater_mcp.utils.model_store import flush_model

    ws = tmp_path / "cmp_log2"
    _impl_create_model("cmp_log2", str(ws), "METERS", "DAYS")
    _impl_add_dis_package("cmp_log2", nlay=1, nrow=2, ncol=2, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    flush_model("cmp_log2")
    (ws / "mfsim.lst").write_text("Normal termination\n")
    out = _call_tool("get_run_log", {"model": "cmp_log2", "component": "gwt"})
    assert out["error"] is True
    assert out["code"] == "INVALID_INPUT"


def test_component_grid_type_replacement(tmp_path):
    """I3: switching a component's grid type must not leave two grid packages."""
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_add_disv_package,
        _impl_create_model,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "cmp_grid"
    _impl_create_model("cmp_grid", str(ws), "METERS", "DAYS")
    _impl_add_disv_package(
        "cmp_grid",
        nlay=1,
        vertices=[[0, 0.0, 0.0], [1, 1.0, 0.0], [2, 1.0, 1.0], [3, 0.0, 1.0],
                  [4, 2.0, 0.0], [5, 3.0, 0.0], [6, 3.0, 1.0], [7, 2.0, 1.0]],
        cell2d=[[0, 0.5, 0.5, 4, 0, 1, 2, 3], [1, 2.5, 0.5, 4, 4, 5, 6, 7]],
        top=[1.0, 1.0],
        botm=[[0.0, 0.0]],
    )
    _impl_add_component_model("cmp_grid", "gwe")
    _impl_add_dis_package(
        "cmp_grid", nlay=1, nrow=2, ncol=2, delr=1.0, delc=1.0, top=1.0, botm=[0.0],
        component="gwe",
    )
    pkgs = model_store.get_model("cmp_grid", "gwe").get_package_list()
    assert "DIS" in pkgs
    assert "DISV" not in pkgs


def test_summarise_reports_component_grid_type(tmp_path):
    """I4: _grid_type_of must work for non-GWF components."""
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_dis_package,
        _impl_create_model,
        _impl_summarise_model,
    )

    _impl_create_model("cmp_gt", str(tmp_path / "cmp_gt"), "METERS", "DAYS")
    _impl_add_dis_package("cmp_gt", nlay=1, nrow=2, ncol=2, delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_component_model("cmp_gt", "gwe")
    out = _impl_summarise_model("cmp_gt")
    assert out["components"]["gwf"]["grid_type"] == "DIS"
    assert out["components"]["gwe"]["grid_type"] == "DIS"


def test_add_component_model_mirrors_disu_extras(tmp_path):
    """I5: DISU mirroring must carry idomain and cell geometry."""
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_disu_package,
        _impl_create_model,
    )
    from groundwater_mcp.utils import model_store

    name = "cmp_disu"
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_add_disu_package(
        name,
        nodes=2,
        nja=2,
        top=[10.0, 10.0],
        bot=[0.0, 0.0],
        area=[1.0, 1.0],
        iac=[1, 1],
        ja=[0, 1],
        idomain=[1, 0],
        vertices=[[0, 0.0, 0.0], [1, 1.0, 0.0], [2, 1.0, 1.0], [3, 0.0, 1.0],
                  [4, 2.0, 0.0], [5, 3.0, 0.0], [6, 3.0, 1.0], [7, 2.0, 1.0]],
        cell2d=[[0, 0.5, 0.5, 4, 0, 1, 2, 3], [1, 2.5, 0.5, 4, 4, 5, 6, 7]],
        nvert=8,
    )
    _impl_add_component_model(name, "gwe")
    disu = model_store.get_model(name, "gwe").get_package("disu")
    assert disu is not None
    assert list(np.asarray(disu.idomain.array).ravel()) == [1, 0]
    assert disu.cell2d is not None


def test_add_component_model_rolls_back_on_failure(tmp_path):
    """I6: a failed component build must not leave an orphan model."""
    from groundwater_mcp.tools.builder import (
        _impl_add_component_model,
        _impl_add_disu_package,
        _impl_create_model,
    )
    from groundwater_mcp.utils import model_store

    name = "cmp_rb"
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_add_disu_package(
        name, nodes=2, nja=2, top=[10.0, 10.0], bot=[0.0, 0.0], area=[1.0, 1.0],
        iac=[1, 1], ja=[0, 1],
    )
    before = list(model_store.get_sim(name).model_names)
    with pytest.raises(ValueError):
        _impl_add_component_model(name, "prt")  # PRT has no DISU grid class
    assert list(model_store.get_sim(name).model_names) == before
    assert "prt" not in model_store.component_map(name)


def test_component_map_reconciles_stale_meta(tmp_path):
    """I7: a stored map naming models absent from the sim must not create phantoms."""
    from groundwater_mcp.utils import model_store

    _two_model_sim(tmp_path)
    model_store.write_meta("run_a", {
        "name": "run_a",
        "units": "METERS",
        "time_units": "DAYS",
        "components": {"gwf": "ghostgwf", "gwe": "ghostgwe"},
    })
    comps = model_store.component_map("run_a")
    assert comps == {"gwf": "run_a", "gwe": "run_a_gwe"}
    assert "ghostgwf" not in comps.values()
    assert model_store.get_model("run_a", "gwe").name == "run_a_gwe"
