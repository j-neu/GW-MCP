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
