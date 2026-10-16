"""IMS solver controls on set_simulation and budget CSV on add_oc_package."""

from __future__ import annotations

import shutil

import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.runner import _impl_run_simulation
from groundwater_mcp.utils.workspace import resolve_workspace


def _model(tmp_path, name, **sim_kwargs):
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate", **sim_kwargs)
    _impl_add_dis_package(name, 1, 3, 3, 100.0, 100.0, 50.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=20.0)
    chd = [[[0, r, 0], 30.0] for r in range(3)] + [[[0, r, 2], 10.0] for r in range(3)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    return name


def test_set_simulation_writes_solver_controls(tmp_path):
    name = _model(
        tmp_path,
        "ims1",
        inner_maximum=77,
        outer_dvclose=1e-5,
        inner_dvclose=1e-6,
        relaxation_factor=0.97,
    )
    from groundwater_mcp.utils.model_store import flush_model

    flush_model(name)
    (ims_file,) = resolve_workspace(name).glob("*.ims")
    text = ims_file.read_text().upper()
    assert "INNER_MAXIMUM  77" in text
    assert "OUTER_DVCLOSE  1.00000000E-05" in text
    assert "INNER_DVCLOSE  1.00000000E-06" in text
    assert "RELAXATION_FACTOR       0.97000000" in text


@pytest.mark.parametrize(
    "kwargs",
    [
        {"inner_maximum": 0},
        {"outer_dvclose": -1.0},
        {"inner_dvclose": 0.0},
        {"relaxation_factor": 1.5},
    ],
)
def test_set_simulation_rejects_bad_solver_controls(tmp_path, kwargs):
    with pytest.raises(ValueError):
        _model(tmp_path, "ims_bad", **kwargs)


@pytest.mark.skipif(shutil.which("mf6") is None, reason="mf6 not on PATH")
def test_oc_budgetcsv_is_written_by_a_run(tmp_path):
    name = _model(tmp_path, "oc1")
    _impl_add_oc_package(name, None, None, None, None, budgetcsv_filerecord="oc1.budget.csv")
    run = _impl_run_simulation(name, silent=True)
    assert run["success"], run
    csv = resolve_workspace(name) / "oc1.budget.csv"
    assert csv.exists()
    header = csv.read_text().splitlines()[0].lower()
    assert "time" in header or "totim" in header
