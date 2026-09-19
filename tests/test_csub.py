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


def test_add_csub_package_rejects_interbeddata(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name, packagedata=[_rec(layer=0)], interbeddata=[[(0, 0, 0), 0.0]]
    )
    assert res["code"] == "INVALID_INPUT"
    assert "interbeddata" in res["message"]


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
    ws = resolve_workspace(name)
    ext = ws / "ext" / "csubmdl.csub_packagedata.dat"
    ext.parent.mkdir(parents=True, exist_ok=True)
    ext.write_text(
        "1  1 1 1  nodelay  0.0  0.5  2.0  0.05  0.02  0.35  1e-6  0.0\n"
    )
    res = _impl_add_csub_package(
        name,
        packagedata={"filename": "ext/csubmdl.csub_packagedata.dat"},
        ninterbeds=1,
    )
    assert "error" not in res, res
    assert res["ninterbeds"] == 1
    assert res["packagedata_filename"] == "ext/csubmdl.csub_packagedata.dat"
    assert ext.exists()
    model_store.flush_model(name)
    text = (ws / "csubmdl.csub").read_text()
    assert "OPEN/CLOSE" in text
    assert "ext/csubmdl.csub_packagedata.dat" in text
    meta = model_store.read_meta(name)
    assert meta["csub"]["packagedata_filename"] == "ext/csubmdl.csub_packagedata.dat"


def test_add_csub_package_external_filename_missing_rejected(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata={"filename": "ext/missing.csub_packagedata.dat"},
        ninterbeds=1,
    )
    assert res["code"] == "INVALID_INPUT"
    assert "data" in res["message"]
    assert "csub" not in model_store.read_meta(name)


def test_add_csub_package_external_filename_requires_ninterbeds(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(name, packagedata={"filename": "ext.dat"})
    assert res["code"] == "INVALID_INPUT"
    assert "ninterbeds" in res["message"]


def test_add_csub_package_external_filename_with_data(tmp_path):
    from groundwater_mcp.tools.builder import _impl_add_csub_package
    from groundwater_mcp.utils import model_store
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_add_csub_package(
        name,
        packagedata={
            "filename": "ext/csubmdl.csub_packagedata.dat",
            "data": [_rec(layer=0)],
        },
    )
    assert "error" not in res, res
    assert res["ninterbeds"] == 1
    assert res["packagedata_filename"] == "ext/csubmdl.csub_packagedata.dat"
    ws = resolve_workspace(name)
    ext = ws / "ext" / "csubmdl.csub_packagedata.dat"
    assert ext.exists()
    assert "nodelay" in ext.read_text()
    model_store.flush_model(name)
    text = (ws / "csubmdl.csub").read_text()
    assert "OPEN/CLOSE" in text
    assert "ext/csubmdl.csub_packagedata.dat" in text
    assert "nodelay" not in text.lower()  # records externalised, not inline
    meta = model_store.read_meta(name)
    assert meta["csub"]["packagedata_filename"] == "ext/csubmdl.csub_packagedata.dat"


# ---------------------------------------------------------------------------
# read_compaction
# ---------------------------------------------------------------------------


def _write_csub_obs(tmp_path, name, text, filename="model.csub.obs.csv"):
    from groundwater_mcp.utils import model_store
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(name)
    (ws / filename).write_text(text)
    meta = model_store.read_meta(name)
    meta["csub"] = {"obs_output_csv": filename}
    model_store.write_meta(name, meta)
    return ws


def test_read_compaction_sums_layers_to_subsidence(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction

    name = _csub_model(tmp_path, nlay=2)
    _write_csub_obs(
        tmp_path, name,
        "time,COMPACTION.01,COMPACTION.02\n0.0,0.10,0.20\n1.0,0.15,0.25\n",
    )
    res = _impl_read_compaction(name)
    assert "error" not in res, res
    assert res["subsidence"] == pytest.approx([0.30, 0.40])
    assert res["times"] == pytest.approx([0.0, 1.0])
    assert res["layers"] == [1, 2]
    assert res["output_csv"].endswith("model.csub.obs.csv")


def test_read_compaction_excludes_elastic_and_interbed_columns(tmp_path):
    """Only layer compaction columns sum to subsidence."""
    from groundwater_mcp.tools.postprocess import _impl_read_compaction

    name = _csub_model(tmp_path, nlay=2)
    _write_csub_obs(
        tmp_path, name,
        "time,compaction.01,COMPACTION.02,ELASTIC-COMPACTION.01,"
        "INELASTIC-COMPACTION.01,PRECONSTRESS.01,INTERBED-COMPACTION-PCT.01\n"
        "0.0,0.10,0.20,9.0,9.0,9.0,9.0\n"
        "1.0,0.15,0.25,9.0,9.0,9.0,9.0\n",
    )
    res = _impl_read_compaction(name)
    assert "error" not in res, res
    assert res["subsidence"] == pytest.approx([0.30, 0.40])
    assert res["layers"] == [1, 2]


def test_read_compaction_missing_csv_returns_output_file_missing(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_read_compaction(name)
    assert res["error"] is True
    assert res["code"] == "OUTPUT_FILE_MISSING"


def test_read_compaction_truncates_and_writes_full_table(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction

    name = _csub_model(tmp_path, nlay=1)
    ws = _write_csub_obs(
        tmp_path, name,
        "time,COMPACTION.01\n0.0,0.1\n1.0,0.2\n2.0,0.3\n",
    )
    res = _impl_read_compaction(name, max_rows=2)
    assert "error" not in res, res
    assert res["truncated"] is True
    assert res["n_rows"] == 3
    assert res["subsidence"] == pytest.approx([0.1, 0.2])
    full = (ws / "csubmdl_compaction.csv").read_text()
    assert full.count("\n") == 4  # header + 3 rows


def test_read_compaction_reads_strainib_file(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction

    name = _csub_model(tmp_path, nlay=1)
    ws = _write_csub_obs(
        tmp_path, name, "time,COMPACTION.01\n0.0,0.1\n1.0,0.2\n"
    )
    (ws / "csubmdl.strainib.csv").write_text(
        " INTERBED_NUMBER,INTERBED_TYPE,NODE,LAYER,ROW,COLUMN,"
        "INITIAL_THICKNESS,FINAL_THICKNESS,TOTAL_COMPACTION,TOTAL_STRAIN,"
        "PERCENT_COMPACTION\n"
        " 1, 0, 1, 1, 1, 1, 2.0, 1.99, 0.01, 0.005, 0.5\n"
    )
    res = _impl_read_compaction(name)
    assert "error" not in res, res
    assert res["interbed_strain"] is not None
    assert res["interbed_strain"][0]["interbed_number"] == 1
    assert res["interbed_strain"][0]["total_compaction"] == pytest.approx(0.01)


def test_read_compaction_no_compaction_columns_is_invalid_input(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,PRECONSTRESS.01\n0.0,1.0\n")
    res = _impl_read_compaction(name)
    assert res["error"] is True
    assert res["code"] == "INVALID_INPUT"


def test_read_compaction_rglob_fallback_when_meta_absent(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_compaction
    from groundwater_mcp.utils import model_store
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    ws = resolve_workspace(name)
    (ws / "csubmdl.csub.obs.csv").write_text("time,COMPACTION.01\n0.0,0.4\n")
    meta = model_store.read_meta(name)
    meta.pop("csub", None)
    model_store.write_meta(name, meta)
    res = _impl_read_compaction(name)
    assert "error" not in res, res
    assert res["subsidence"] == pytest.approx([0.4])


# ---------------------------------------------------------------------------
# plot_subsidence
# ---------------------------------------------------------------------------


def test_plot_subsidence_writes_png(tmp_path):
    from pathlib import Path

    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    res = _impl_plot_subsidence(name)
    assert "error" not in res, res
    assert Path(res["output_file"]).exists()
    assert res["n_times"] == 2
    assert res["has_observed"] is False
    assert res["observed_csv"] is None


def test_plot_subsidence_overlays_observed_subsidence_ft(tmp_path):
    from pathlib import Path

    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    obs = resolve_workspace(name) / "observed.csv"
    obs.write_text("time,Subsidence_ft\n0.0,0.0\n1.0,0.6\n")
    res = _impl_plot_subsidence(name, observed_csv=str(obs))
    assert "error" not in res, res
    assert res["has_observed"] is True
    assert Path(res["observed_csv"]).exists()
    assert Path(res["output_file"]).exists()


def test_plot_subsidence_observed_first_numeric_column_fallback(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    obs = resolve_workspace(name) / "observed.csv"
    obs.write_text("time,measured_settlement\n0.0,0.0\n1.0,0.7\n")
    res = _impl_plot_subsidence(name, observed_csv=str(obs))
    assert "error" not in res, res
    assert res["has_observed"] is True


def test_plot_subsidence_propagates_read_compaction_error(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_plot_subsidence(name)
    assert res["error"] is True
    assert res["code"] == "OUTPUT_FILE_MISSING"


def test_plot_subsidence_missing_observed_csv(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    res = _impl_plot_subsidence(name, observed_csv="absent_observed.csv")
    assert res["error"] is True
    assert res["code"] == "OUTPUT_FILE_MISSING"


def test_plot_subsidence_non_numeric_observed_is_invalid_input(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence
    from groundwater_mcp.utils.workspace import resolve_workspace

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    obs = resolve_workspace(name) / "observed.csv"
    obs.write_text("time,note\n0.0,a\n1.0,b\n")
    res = _impl_plot_subsidence(name, observed_csv=str(obs))
    assert res["error"] is True
    assert res["code"] == "INVALID_INPUT"


def test_plot_subsidence_respects_output_file_name(tmp_path):
    from pathlib import Path

    from groundwater_mcp.tools.postprocess import _impl_plot_subsidence

    name = _csub_model(tmp_path, nlay=1)
    _write_csub_obs(tmp_path, name, "time,COMPACTION.01\n0.0,0.0\n1.0,0.5\n")
    res = _impl_plot_subsidence(name, output_file="custom_subsidence.png")
    assert "error" not in res, res
    out = Path(res["output_file"])
    assert out.name == "custom_subsidence.png"
    assert out.exists()


# ---------------------------------------------------------------------------
# import_subsidence_observations
# ---------------------------------------------------------------------------


def test_import_subsidence_observations_registers_series(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    obs = tmp_path / "H201_sub_data.csv"
    obs.write_text("datetime,Subsidence_ft\n2010-01-01,0.0\n2011-01-01,0.5\n")
    res = _impl_import_subsidence_observations(name, str(obs))
    assert "error" not in res, res
    assert res["n_observations"] == 2
    meta = model_store.read_meta(name)
    block = meta["derived_observations"]["subsidence"]
    assert block["dates"] == ["2010-01-01", "2011-01-01"]
    assert block["values"] == pytest.approx([0.0, 0.5])
    assert block["sim_source"]["csv"].endswith(".csub.obs.csv")
    assert block["sim_source"]["sum_cols"] == ["compaction"]
    assert block["sim_source"]["time_col"] == "time"


def test_import_subsidence_observations_unnamed_index_sorted_drops_nonfinite(tmp_path):
    """Holdout layout: the time column is the unnamed first (index) column;
    rows are sorted ascending and non-finite values are dropped."""
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    obs = tmp_path / "H201_sub_data.csv"
    obs.write_text(",Subsidence_ft\n2011-01-01,0.5\n2012-01-01,\n2010-01-01,0.1\n")
    res = _impl_import_subsidence_observations(name, str(obs))
    assert "error" not in res, res
    assert res["n_observations"] == 2
    block = model_store.read_meta(name)["derived_observations"]["subsidence"]
    assert block["dates"] == ["2010-01-01", "2011-01-01"]
    assert block["values"] == pytest.approx([0.1, 0.5])


def test_import_subsidence_observations_uses_csub_meta_obs_csv(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    meta = model_store.read_meta(name)
    meta["csub"] = {"obs_output_csv": "custom.csub.obs.csv"}
    model_store.write_meta(name, meta)
    obs = tmp_path / "obs.csv"
    obs.write_text("datetime,Subsidence_ft\n2010-01-01,0.1\n")
    res = _impl_import_subsidence_observations(name, str(obs))
    assert "error" not in res, res
    assert res["sim_source"]["csv"] == "custom.csub.obs.csv"
    stored = model_store.read_meta(name)["derived_observations"]["subsidence"]
    assert stored["sim_source"]["csv"] == "custom.csub.obs.csv"


def test_import_subsidence_observations_custom_sim_source_merged(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations
    from groundwater_mcp.utils import model_store

    name = _csub_model(tmp_path, nlay=1)
    obs = tmp_path / "obs.csv"
    obs.write_text("datetime,Subsidence_ft\n2010-01-01,0.1\n")
    res = _impl_import_subsidence_observations(
        name, str(obs), sim_source={"sum_cols": ["compaction", "elastic"]}
    )
    assert "error" not in res, res
    stored = model_store.read_meta(name)["derived_observations"]["subsidence"]
    assert stored["sim_source"]["sum_cols"] == ["compaction", "elastic"]
    assert stored["sim_source"]["csv"].endswith(".csub.obs.csv")


def test_import_subsidence_observations_missing_file_is_invalid_input(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations

    name = _csub_model(tmp_path, nlay=1)
    res = _impl_import_subsidence_observations(name, str(tmp_path / "absent.csv"))
    assert res["error"] is True
    assert res["code"] == "INVALID_INPUT"


def test_import_subsidence_observations_no_value_column_is_invalid_input(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations

    name = _csub_model(tmp_path, nlay=1)
    obs = tmp_path / "obs.csv"
    obs.write_text("datetime,note\n2010-01-01,a\n2011-01-01,b\n")
    res = _impl_import_subsidence_observations(name, str(obs))
    assert res["error"] is True
    assert res["code"] == "INVALID_INPUT"


def test_import_subsidence_observations_zero_finite_is_invalid_input(tmp_path):
    from groundwater_mcp.tools.parameterise import _impl_import_subsidence_observations

    name = _csub_model(tmp_path, nlay=1)
    obs = tmp_path / "obs.csv"
    obs.write_text("datetime,Subsidence_ft\n2010-01-01,\n2011-01-01,\n")
    res = _impl_import_subsidence_observations(name, str(obs))
    assert res["error"] is True
    assert res["code"] == "INVALID_INPUT"
