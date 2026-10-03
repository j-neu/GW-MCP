"""Tests for legacy MT3D-USGS post-processing."""

from __future__ import annotations

from pathlib import Path

import numpy as np


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
