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
