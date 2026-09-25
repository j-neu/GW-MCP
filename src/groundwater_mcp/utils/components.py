"""Component registry for multi-model MODFLOW 6 simulations.

A MODFLOW 6 simulation (``mfsim.nam``) can hold several models of different
types -- a flow model (``gwf``), an energy-transport model (``gwe``), a
particle-tracking model (``prt``). Historically groundwater-mcp assumed a
single GWF model per simulation; this registry lets tools address one
component at a time. Later capability specs (GWE, PRT) extend it with
:func:`register_component` instead of editing foundation call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import flopy.mf6 as mf6


@dataclass(frozen=True)
class ComponentSpec:
    """Everything the foundation needs to know about one model type."""

    name: str
    model_class: type
    grid_classes: dict[str, type] = field(default_factory=dict)
    ic_class: type | None = None
    oc_class: type | None = None
    oc_value_keyword: str | None = None
    exchange_class: type | None = None


class UnknownComponentError(KeyError, ValueError):
    """Raised when a component name is unknown or absent from a simulation.

    Subclasses both ``KeyError`` (so existing callers that catch KeyError keep
    working) and ``ValueError`` (so tool wrappers can map it to INVALID_INPUT
    ahead of the MODEL_NOT_FOUND KeyError branch).
    """


_COMPONENTS: dict[str, ComponentSpec] = {}


def register_component(
    name: str,
    *,
    model_class: type,
    grid_classes: dict[str, type] | None = None,
    ic_class: type | None = None,
    oc_class: type | None = None,
    oc_value_keyword: str | None = None,
    exchange_class: type | None = None,
) -> None:
    """Register (or replace) a component in the registry."""
    _COMPONENTS[name.lower()] = ComponentSpec(
        name=name.lower(),
        model_class=model_class,
        grid_classes=dict(grid_classes or {}),
        ic_class=ic_class,
        oc_class=oc_class,
        oc_value_keyword=oc_value_keyword,
        exchange_class=exchange_class,
    )


register_component(
    "gwf",
    model_class=mf6.ModflowGwf,
    grid_classes={
        "dis": mf6.ModflowGwfdis,
        "disv": mf6.ModflowGwfdisv,
        "disu": mf6.ModflowGwfdisu,
    },
    ic_class=mf6.ModflowGwfic,
    oc_class=mf6.ModflowGwfoc,
    oc_value_keyword="head_filerecord",
)

register_component(
    "gwe",
    model_class=mf6.ModflowGwe,
    grid_classes={
        "dis": mf6.ModflowGwedis,
        "disv": mf6.ModflowGwedisv,
        "disu": mf6.ModflowGwedisu,
    },
    ic_class=mf6.ModflowGweic,
    oc_class=mf6.ModflowGweoc,
    oc_value_keyword="temperature_filerecord",
    exchange_class=mf6.ModflowGwfgwe,
)

register_component(
    "prt",
    model_class=mf6.ModflowPrt,
    grid_classes={"dis": mf6.ModflowPrtdis, "disv": mf6.ModflowPrtdisv},
    oc_class=mf6.ModflowPrtoc,
    exchange_class=mf6.ModflowGwfprt,
)


def spec_for(component: str) -> ComponentSpec:
    """Return the spec for *component*, raising ValueError when unknown."""
    key = component.lower()
    if key not in _COMPONENTS:
        raise ValueError(
            f"Unknown component '{component}'. Known components: "
            f"{sorted(_COMPONENTS)}"
        )
    return _COMPONENTS[key]


def model_class_for(component: str) -> type:
    """Return the FloPy model class for a component."""
    return spec_for(component).model_class


def grid_class_for(component: str, kind: str) -> type | None:
    """Return the grid class for a discretisation kind ('dis'/'disv'/'disu')."""
    return spec_for(component).grid_classes.get(kind.lower())


def all_components() -> dict[str, ComponentSpec]:
    """Return a shallow copy of the registry."""
    return dict(_COMPONENTS)
