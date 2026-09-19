"""CSUB builder tests (Task 2).

Covers ``_impl_add_csub_package``: packagedata normalisation/validation,
per-layer arrays, filerecords, observations, external packagedata, meta
persistence, replacement semantics and the deferred write.
"""

from __future__ import annotations

import pytest


def _csub_model(tmp_path, name="csubmdl", nlay=2):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_ic_package,
        _impl_add_npf_package,
        _impl_add_oc_package,
        _impl_add_sto_package,
        _impl_create_model,
        _impl_set_simulation,
    )

    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "FEET", "DAYS")
    _impl_set_simulation(name, 2, [1.0, 1.0], [1, 1], "moderate")
    _impl_add_dis_package(name, nlay, 1, 1, 1.0, 1.0, 0.0, [-10.0, -20.0][:nlay])
    _impl_add_npf_package(
        name, icelltype=1, k=[1.0] * nlay, k33=[0.1] * nlay, save_flows=True
    )
    _impl_add_ic_package(name, strt=[0.0] * nlay)
    _impl_add_sto_package(
        name, iconvert=0, ss=0.0, sy=0.0, steady_state=[0], save_flows=True
    )
    _impl_add_oc_package(name, None, "model.cbc", None, None)
    return name


def _rec(layer=0, cdelay="nodelay", pcs0=0.0, thick_frac=0.5, rnb=2.0,
         ssv_cc=0.05, sse_cr=0.02, theta=0.35, kv=1e-6, h0=0.0, i=0):
    return [i, [layer, 0, 0], cdelay, pcs0, thick_frac, rnb, ssv_cc, sse_cr,
            theta, kv, h0]


# ---------------------------------------------------------------------------
# Happy path / meta
# ---------------------------------------------------------------------------


def test_add_csub_package_writes_six_options_and_meta(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=2)
    res = _impl_add_csub_package(
        name,
        packagedata=[
            [0, [0, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
            [1, [1, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
        ],
        sgm=[0.1, 0.1],
        sgs=[0.1, 0.1],
        cg_theta=[0.35, 0.35],
        cg_ske_cr=[2.2e-8, 2.2e-8],
        head_based=False,
        initial_preconsolidation_head=True,
        specified_initial_interbed_state=True,
        filerecords={"strainib": "model.strainib.csv"},
    )
    assert "error" not in res, res
    assert res["package"] == "CSUB"
    assert res["ninterbeds"] == 2
    assert res["n_delay_interbeds"] == 0
    assert res["layers"] == [0, 1]
    assert res["written"] is False
    meta = model_store.read_meta(name)
    assert meta["csub"]["ninterbeds"] == 2
    assert meta["csub"]["interbeds"][0]["layer"] == 0
    assert meta["csub"]["interbeds"][1]["layer"] == 1
    assert meta["csub"]["filerecords"] == {"strainib": "model.strainib.csv"}


def test_add_csub_package_flush_writes_csub_file(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    _impl_add_csub_package(name, packagedata=[_rec(layer=0)])
    assert model_store.flush_model(name) is True
    ws = resolve_workspace(name)
    text = (ws / "csubmdl.csub").read_text()
    assert "NINTERBEDS  1" in text
    assert "NODELAY" not in text  # cdelay is a packagedata column, not an option
    assert "nodelay" in text


def test_add_csub_package_delay_requires_ndelaycells(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name, packagedata=[_rec(layer=0, cdelay="delay")]
    )
    assert res["code"] == "INVALID_INPUT"
    assert "ndelaycells" in res["message"]


def test_add_csub_package_delay_with_ndelaycells(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=2)
    res = _impl_add_csub_package(
        name,
        packagedata=[_rec(layer=0, cdelay="delay"), _rec(layer=1, i=1)],
        ndelaycells=19,
    )
    assert "error" not in res, res
    assert res["n_delay_interbeds"] == 1
    assert res["ndelaycells"] == 19


def test_add_csub_package_accepts_pcs0_zero(tmp_path):
    """Holdout: initial_preconsolidation_head=True sets pcs0=0.0."""
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata=[_rec(layer=0, pcs0=0.0)],
        initial_preconsolidation_head=True,
    )
    assert "error" not in res, res


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record, match",
    [
        ([0, [0, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6],
         "expected 11"),
        ([1, [0, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
         "contiguous"),
        ([0, [0, 0, 0], "sometimes", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
         "cdelay"),
        ([0, [7, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
         "outside"),
        ([0, [0, 0, 0], "nodelay", 0.0, 0.0, 2.0, 0.05, 0.02, 0.35, 1e-6, 0.0],
         "thick_frac"),
        ([0, [0, 0, 0], "nodelay", 0.0, 0.5, 0.5, 0.05, 0.02, 0.35, 1e-6, 0.0],
         "rnb"),
        ([0, [0, 0, 0], "nodelay", 0.0, 0.5, 2.0, 0.05, 0.02, 1.0, 1e-6, 0.0],
         "theta"),
    ],
)
def test_normalise_csub_packagedata_rejects_bad_records(record, match):
    from groundwater_mcp.tools.builder import _normalise_csub_packagedata

    with pytest.raises(ValueError, match=match):
        _normalise_csub_packagedata([record], nlay=2)


def test_add_csub_package_ninterbeds_mismatch(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name, packagedata=[_rec(layer=0)], ninterbeds=2
    )
    assert res["code"] == "INVALID_INPUT"


def test_add_csub_package_per_layer_length_mismatch(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=2)
    res = _impl_add_csub_package(
        name, packagedata=[_rec(layer=0), _rec(layer=1, i=1)], sgm=[0.1]
    )
    assert res["code"] == "INVALID_INPUT"


def test_add_csub_package_unknown_filerecord(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name, packagedata=[_rec(layer=0)], filerecords={"bogus": "x.csv"}
    )
    assert res["code"] == "INVALID_INPUT"


def test_add_csub_package_scalar_per_layer_values_broadcast(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=2)
    res = _impl_add_csub_package(
        name,
        packagedata=[_rec(layer=0), _rec(layer=1, i=1)],
        sgm=0.1,
        sgs=0.1,
        cg_theta=0.35,
        cg_ske_cr=2.2e-8,
    )
    assert "error" not in res, res


# ---------------------------------------------------------------------------
# Replacement (pname semantics)
# ---------------------------------------------------------------------------


def test_add_csub_package_replaces_existing(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package, _packages_of_type
    from groundwater_mcp.utils.model_store import get_gwf

    name = _csub_model(tmp_path, nlay=1)
    first = _impl_add_csub_package(name, packagedata=[_rec(layer=0)])
    assert "warning" not in first
    second = _impl_add_csub_package(name, packagedata=[_rec(layer=0)])
    assert second["warning"]
    assert len(_packages_of_type(get_gwf(name), "csub")) == 1


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


def test_add_csub_package_writes_obs_package(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata=[_rec(layer=0)],
        observations={"compaction.01": [("compaction.01", "compaction-cell", (0, 0, 0))]},
    )
    assert "error" not in res, res
    meta = model_store.read_meta(name)
    assert meta["csub"]["obs_output_csv"].endswith(".csub.obs.csv")
    assert meta["csub"]["obs_names"] == ["compaction.01"]
    assert res["obs_output_csv"].endswith(".csub.obs.csv")


def test_add_csub_package_writes_obs_file(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=2)
    res = _impl_add_csub_package(
        name,
        packagedata=[_rec(layer=0, cdelay="delay"), _rec(layer=1, i=1)],
        ndelaycells=19,
        observations={
            "csubmdl.csub.obs.csv": [
                ("compaction01", "compaction-cell", (0, 0, 0)),
                ("preconstress02", "preconstress", (1, 0, 0)),
                ("interbedpc01", "interbed-compaction-pct", 0),
                ("delaypres02", "delay-preconstress", 1),
            ]
        },
    )
    assert "error" not in res, res
    assert res["obs_names"] == [
        "compaction01", "preconstress02", "interbedpc01", "delaypres02"
    ]
    model_store.flush_model(name)
    ws = resolve_workspace(name)
    text = (ws / "csubmdl.csub.obs").read_text()
    assert "compaction-cell  1 1 1" in text
    assert "preconstress-cell  2 1 1" in text
    assert "interbed-compaction-pct  1" in text
    assert "delay-preconstress  2" in text


def test_add_csub_package_rejects_unknown_obs_type(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata=[_rec(layer=0)],
        observations={"x.csv": [("o1", "bogus", (0, 0, 0))]},
    )
    assert res["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# External packagedata
# ---------------------------------------------------------------------------


def test_add_csub_package_external_packagedata_filename_only(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata={"filename": "ext/csubmdl.csub_packagedata.dat"},
        ninterbeds=1,
    )
    assert "error" not in res, res
    assert res["ninterbeds"] == 1
    model_store.flush_model(name)
    ws = resolve_workspace(name)
    text = (ws / "csubmdl.csub").read_text()
    assert "OPEN/CLOSE" in text
    assert "ext/csubmdl.csub_packagedata.dat" in text
    meta = model_store.read_meta(name)
    assert meta["csub"]["packagedata_filename"] == "ext/csubmdl.csub_packagedata.dat"


def test_add_csub_package_external_filename_requires_ninterbeds(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(name, packagedata={"filename": "ext.dat"})
    assert res["code"] == "INVALID_INPUT"
    assert "ninterbeds" in res["message"]


def test_add_csub_package_external_filename_with_data(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata={"filename": "ext.dat", "data": [_rec(layer=0)]},
    )
    assert "error" not in res, res
    assert res["ninterbeds"] == 1
    assert model_store.read_meta(name)["csub"]["ninterbeds"] == 1
