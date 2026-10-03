"""Tests for legacy MT3D-USGS post-processing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def _build_legacy_model(
    ws: Path, name: str = "legacy", nlay: int = 1, nrow: int = 3, ncol: int = 4
) -> Path:
    """Write a minimal MODFLOW-2005 flow model + MT3D-USGS transport model.

    Spike notes (flopy 3.10 round-trip — the exact working kwargs Tasks 2-5
    must reuse):

    * MODFLOW-2005 BASIC is ``flopy.modflow.ModflowBas`` (there is no
      ``ModflowBas6`` in flopy 3.10).
    * ``flopy.mt3d.Mt3dDsp`` accepts ``al, trpt, trpv, dmcoef`` — there is no
      ``trpy`` kwarg; the vertical transverse dispersivity is ``trpv``.
    * The MT3D-USGS nam file is ``<name>_mt3d.nam`` (the Ft3dms model name);
      the flow nam file is ``<name>.nam``.
    """
    import flopy

    mf = flopy.modflow.Modflow(
        name, exe_name="mf2005", version="mf2005", model_ws=str(ws)
    )
    flopy.modflow.ModflowDis(
        mf, nlay=nlay, nrow=nrow, ncol=ncol, nper=1, delr=100.0, delc=100.0,
        top=10.0, botm=[10.0 - 10.0 * (k + 1) for k in range(nlay)],
        itmuni=4, lenuni=2,
    )
    flopy.modflow.ModflowBas(mf, ibound=1, strt=5.0)
    flopy.modflow.ModflowLpf(mf, hk=1.0)
    flopy.modflow.ModflowOc(
        mf, stress_period_data={(0, 0): ["save head", "save budget"]}
    )
    mf.write_input()

    mt = flopy.mt3d.Mt3dms(
        modelname=f"{name}_mt3d", modflowmodel=mf, version="mt3d-usgs",
        model_ws=str(ws),
    )
    flopy.mt3d.Mt3dBtn(
        mt, nlay=nlay, nrow=nrow, ncol=ncol, nper=1, icbund=1, prsity=0.3,
        delr=100.0, delc=100.0, htop=10.0, dz=[10.0] * nlay,
    )
    flopy.mt3d.Mt3dAdv(mt, mixelm=0)
    flopy.mt3d.Mt3dDsp(mt, al=1.0, trpt=0.1, trpv=0.1)
    mt.write_input()
    return ws


def _write_ucn(path: Path, records, precision: str = "single") -> None:
    """Write a binary MT3D-USGS concentration (.UCN) file."""
    from flopy.utils.binaryfile import BinaryHeader

    real = np.float32 if precision == "single" else np.float64
    dt = BinaryHeader.set_dtype(bintype="Ucn", precision=precision)
    with open(path, "wb") as f:
        for kstp, kper, totim, arr in records:
            arr = np.asarray(arr, dtype=real)
            if arr.ndim == 2:
                arr = arr[np.newaxis, :, :]
            nlay, nrow, ncol = arr.shape
            for k in range(nlay):
                rec = np.zeros(1, dtype=dt)
                rec["ntrans"][0] = 1
                rec["kstp"][0] = kstp
                rec["kper"][0] = kper
                rec["totim"][0] = totim
                rec["text"][0] = b"CONCENTRATION"
                rec["ncol"][0] = ncol
                rec["nrow"][0] = nrow
                rec["ilay"][0] = k + 1
                f.write(rec.tobytes())
                f.write(arr[k].astype(real).tobytes())


def test_legacy_round_trip(tmp_path: Path):
    import flopy
    import flopy.utils as fu

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    _write_ucn(
        ws / "MT3D001.UCN",
        [(1, 1, 1.0, np.arange(12.0).reshape(1, 3, 4))],
    )

    flow = flopy.modflow.Modflow.load(
        "legacy.nam", version="mf2005", exe_name="mf2005",
        model_ws=str(ws), verbose=False, check=False,
    )
    transport = flopy.mt3d.Mt3dms.load(
        "legacy_mt3d.nam", version="mt3d-usgs", model_ws=str(ws),
        modflowmodel=flow, verbose=False,
    )
    assert (flow.dis.nlay, flow.dis.nrow, flow.dis.ncol) == (1, 3, 4)
    assert transport.version == "mt3d-usgs"

    ucn = fu.UcnFile(str(ws / "MT3D001.UCN"))
    assert ucn.get_kstpkper() == [(0, 0)]
    data = ucn.get_data(kstpkper=(0, 0))
    assert np.asarray(data).shape == (1, 3, 4)
    assert float(np.asarray(data).max()) == 11.0

    from flopy.plot import PlotMapView

    from groundwater_mcp.utils.plotting import figure, save_figure

    with figure(figsize=(3, 3)) as fig:
        ax = fig.add_subplot(1, 1, 1)
        pmv = PlotMapView(model=flow, ax=ax, layer=0)
        pmv.plot_array(np.asarray(data)[0], cmap="jet")
        out = save_figure(fig, ws / "plume.png", ws)
    assert Path(out).exists()


def test_adopt_legacy_model(tmp_path: Path):
    from groundwater_mcp.utils import legacy_transport

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    legacy = legacy_transport.adopt_legacy_mt3d_usgs("m1", ws)
    assert legacy.flow_nam == "legacy.nam"
    assert legacy.transport_nam == "legacy_mt3d.nam"
    assert legacy.version == "mt3d-usgs"
    assert (legacy.flow_model.dis.nlay, legacy.flow_model.dis.nrow,
            legacy.flow_model.dis.ncol) == (1, 3, 4)
    assert legacy_transport.is_legacy("m1")
    assert legacy_transport.get_legacy_model("m1") is legacy


def test_adopt_legacy_ambiguous_nam(tmp_path: Path):
    from groundwater_mcp.utils import legacy_transport

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    # A second flow nam makes discovery ambiguous.
    (ws / "second.nam").write_text("DIS  second.dis\nBAS6 second.ba6\n")
    with pytest.raises(ValueError):
        legacy_transport.adopt_legacy_mt3d_usgs("m2", ws)


def test_model_store_guard_rejects_legacy_name(tmp_path: Path):
    from groundwater_mcp.utils import legacy_transport, model_store

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    legacy_transport.adopt_legacy_mt3d_usgs("m3", ws)
    with pytest.raises(ValueError, match="legacy MT3D-USGS"):
        model_store.get_sim("m3")


def test_adopt_mt3d_usgs_tool(tmp_path: Path):
    from groundwater_mcp.tools.builder import _impl_adopt_mt3d_usgs_model
    from groundwater_mcp.utils.model_store import read_meta
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, np.ones((1, 3, 4)))])

    out = _impl_adopt_mt3d_usgs_model("m4", str(ws), "METERS", "DAYS")
    assert out["type"] == "mt3d-usgs"
    assert out["flow_version"] == "mf2005"
    assert out["grid"] == {"nlay": 1, "nrow": 3, "ncol": 4}
    assert "BTN" in out["transport_packages"]
    assert out["ucn_file"] == "MT3D001.UCN"
    assert out["read_only"] is True

    meta = read_meta("m4")
    assert meta["time_units"] == "DAYS"
    assert meta["legacy"]["flow_nam"] == "legacy.nam"
    assert meta["legacy"]["transport_nam"] == "legacy_mt3d.nam"
    assert resolve_workspace("m4") == ws


def test_adopt_mt3d_usgs_conflicts_with_mf6_name(tmp_path: Path):
    from groundwater_mcp.tools.builder import (
        _impl_adopt_mt3d_usgs_model,
        _impl_create_model,
    )

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    # Register the same path/name as an MF6 model first; the legacy adopt must
    # refuse to overwrite it.
    _impl_create_model("m5", str(ws), "METERS", "DAYS")
    with pytest.raises(ValueError, match="MODFLOW 6"):
        _impl_adopt_mt3d_usgs_model("m5", str(ws))


def _adopt(tmp_path: Path, name: str = "m6", nlay: int = 1) -> tuple[str, Path]:
    from groundwater_mcp.tools.builder import _impl_adopt_mt3d_usgs_model

    ws = tmp_path / name
    ws.mkdir()
    _build_legacy_model(ws, nlay=nlay)
    return _impl_adopt_mt3d_usgs_model(name, str(ws))["model"], ws


def test_read_concentration(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_read_concentration

    name, ws = _adopt(tmp_path)
    arr0 = np.arange(12.0).reshape(1, 3, 4)
    arr1 = arr0 + 100.0
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, arr0), (1, 2, 2.0, arr1)])

    out = _impl_read_concentration(name)
    assert out["kstpkper"] == [0, 1]          # default = last record
    assert out["shape"] == [3, 4]
    assert out["max"] == 111.0
    assert out["n_times"] == 2
    assert Path(out["output_file"]).exists()

    first = _impl_read_concentration(name, kstpkper=(0, 0))
    assert first["totim"] == 1.0
    assert first["max"] == 11.0

    vals = _impl_read_concentration(name, kstpkper=(0, 0), include_values=True)
    assert np.asarray(vals["values"]).shape == (3, 4)


def test_read_concentration_errors(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_read_concentration

    name, ws = _adopt(tmp_path, "m7")
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, np.ones((1, 3, 4)))])

    with pytest.raises(ValueError, match="not found"):
        _impl_read_concentration(name, kstpkper=(5, 5))
    with pytest.raises(ValueError, match="layer"):
        _impl_read_concentration(name, layer=9)


def test_read_concentration_missing_ucn(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_read_concentration

    name, _ = _adopt(tmp_path, "m8")
    with pytest.raises(FileNotFoundError):
        _impl_read_concentration(name)


def test_read_concentration_double_precision(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_read_concentration

    name, ws = _adopt(tmp_path, "m10")
    _write_ucn(
        ws / "MT3D001.UCN",
        [(1, 1, 1.0, np.full((1, 3, 4), 2.5))],
        precision="double",
    )
    out = _impl_read_concentration(name)
    assert out["max"] == 2.5


def test_plot_concentration_map(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_plot_concentration_map

    name, ws = _adopt(tmp_path, "m9")
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, np.arange(12.0).reshape(1, 3, 4))])

    out = _impl_plot_concentration_map(name, output_file="plume.png")
    assert out["type"] == "mt3d-usgs"
    assert out["shape"] == [3, 4]
    assert out["max"] == 11.0
    png = Path(out["output_file"])
    assert png.exists() and png.suffix == ".png" and png.stat().st_size > 0


def test_adopt_partial_nam_disambiguation(tmp_path: Path):
    from groundwater_mcp.utils import legacy_transport

    ws = tmp_path / "legacy"
    ws.mkdir()
    _build_legacy_model(ws)
    # A second flow nam makes full discovery ambiguous.
    (ws / "second.nam").write_text("DIS  second.dis\nBAS6 second.ba6\n")

    # Supplying flow_nam excludes that candidate, so the single remaining
    # transport nam is discovered and the adopt succeeds.
    legacy = legacy_transport.adopt_legacy_mt3d_usgs(
        "m11", ws, flow_nam="legacy.nam"
    )
    assert legacy.flow_nam == "legacy.nam"
    assert legacy.transport_nam == "legacy_mt3d.nam"

    # With neither supplied, the two flow candidates stay ambiguous.
    with pytest.raises(ValueError):
        legacy_transport.adopt_legacy_mt3d_usgs("m12", ws)


def test_read_concentration_shape_mismatch(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_read_concentration

    name, ws = _adopt(tmp_path, "m13")
    # .UCN nrow/ncol (2, 5) disagree with the adopted flow grid (3, 4).
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, np.ones((1, 2, 5)))])
    with pytest.raises(ValueError, match="does not match"):
        _impl_read_concentration(name)


def test_create_model_rejects_legacy_name(tmp_path: Path):
    from groundwater_mcp.tools.builder import _impl_create_model
    from groundwater_mcp.utils import legacy_transport

    name, ws = _adopt(tmp_path, "m14")
    assert legacy_transport.is_legacy(name)
    with pytest.raises(ValueError, match="legacy MT3D-USGS"):
        _impl_create_model(name, str(ws), "METERS", "DAYS")


def test_delete_model_frees_legacy_name(tmp_path: Path):
    from groundwater_mcp.tools.builder import (
        _impl_create_model,
        _impl_delete_model,
    )
    from groundwater_mcp.utils import legacy_transport

    name, ws = _adopt(tmp_path, "m15")
    assert legacy_transport.is_legacy(name)
    _impl_delete_model(name)
    assert not legacy_transport.is_legacy(name)
    out = _impl_create_model(name, str(ws), "METERS", "DAYS")
    assert out["model"] == name


def test_read_concentration_reloads_from_meta(tmp_path: Path):
    from groundwater_mcp.tools.postprocess import _impl_read_concentration
    from groundwater_mcp.utils import legacy_transport

    name, ws = _adopt(tmp_path, "m16")
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, np.arange(12.0).reshape(1, 3, 4))])

    # Simulate a server restart: the in-memory cache is empty, so the model
    # must be reloaded from .gwmcp_meta.json.
    legacy_transport.clear()
    out = _impl_read_concentration(name)
    assert out["max"] == 11.0


def test_adopt_ucn_in_subdirectory(tmp_path: Path):
    from groundwater_mcp.tools.builder import _impl_adopt_mt3d_usgs_model
    from groundwater_mcp.tools.postprocess import _impl_read_concentration
    from groundwater_mcp.utils.model_store import read_meta

    name = "m17"
    ws = tmp_path / name
    ws.mkdir()
    _build_legacy_model(ws)
    sub = ws / "outputs"
    sub.mkdir()
    _write_ucn(sub / "MT3D001.UCN", [(1, 1, 1.0, np.arange(12.0).reshape(1, 3, 4))])

    out = _impl_adopt_mt3d_usgs_model(name, str(ws))
    assert out["ucn_file"] == "outputs/MT3D001.UCN"
    assert read_meta(name)["legacy"]["ucn_file"] == "outputs/MT3D001.UCN"

    # _find_ucn_file's declared branch (workspace / declared) resolves it.
    res = _impl_read_concentration(name)
    assert res["max"] == 11.0


def test_read_concentration_closes_ucn_handle(tmp_path: Path):
    import gc
    import warnings

    from groundwater_mcp.tools.postprocess import _impl_read_concentration

    name, ws = _adopt(tmp_path, "m18")
    _write_ucn(ws / "MT3D001.UCN", [(1, 1, 1.0, np.ones((1, 3, 4)))])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        _impl_read_concentration(name)
        gc.collect()
    leaked = [
        w for w in caught
        if issubclass(w.category, ResourceWarning)
        and "MT3D001.UCN" in str(w.message)
    ]
    assert not leaked

