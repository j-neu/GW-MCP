from __future__ import annotations

from pathlib import Path

import flopy.mf6 as mf6
import numpy as np
import pytest

from groundwater_mcp.tools.runner import _find_mf6_binary

EXPECTED_TRACK_HEADER = (
    "kper,kstp,imdl,iprp,irpt,ilay,icell,izone,istatus,ireason,trelease,t,x,y,z,name"
)


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 not installed")


def _build_flow_and_prt(root: Path, *, nstp: int = 10) -> Path:
    """Build and run the minimal same-simulation GWF+PRT model.

    Requirements proven by the Task 1 spike (see task-1-report.md):

    * The same-simulation GWF-PRT exchange is declared with ``ModflowGwfprt``.
    * The GWF model is solved by an IMS.
    * The PRT model is an *explicit* model and must be solved by an EMS, not an
      IMS. With an IMS the PRT solution runs with suppressed output, so
      ``prt_solve`` never tracks particles and the track CSV stays header-only.
    * The track CSV is declared exactly once, on the PRT OC package.
    * The PRT OC enables the release/timestep/terminate events.
    * The GWF NPF saves specific discharge and the GWF model saves flows.
    """
    ws = root / "prtsim"
    ws.mkdir()
    sim = mf6.MFSimulation(sim_name="prt", version="mf6", sim_ws=str(ws))
    mf6.ModflowTdis(sim, nper=1, perioddata=[(float(nstp), nstp, 1.0)], time_units="DAYS")

    gwf = mf6.ModflowGwf(sim, modelname="gwf", model_nam_file="gwf.nam", save_flows=True)
    ims_gwf = mf6.ModflowIms(sim, complexity="SIMPLE", filename="gwf.ims")
    sim.register_ims_package(ims_gwf, ["gwf"])
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=1, ncol=10, delr=1.0, delc=1.0,
                      top=1.0, botm=0.0, length_units="METERS")
    mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0, save_flows=True, save_specific_discharge=True)
    mf6.ModflowGwfic(gwf, strt=1.0)
    mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(0, 0, 0), 1.0], [(0, 0, 9), 0.0]]})
    mf6.ModflowGwfoc(gwf, head_filerecord="gwf.hds", budget_filerecord="gwf.cbc",
                     saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])

    prt = mf6.ModflowPrt(sim, modelname="prt", model_nam_file="prt.nam", save_flows=True)
    # PRT is explicit: solve it with an EMS so prt_solve actually tracks particles.
    ems_prt = mf6.ModflowEms(sim, pname="ems", filename="prt.ems")
    sim.register_solution_package(ems_prt, ["prt"])
    mf6.ModflowPrtdis(prt, nlay=1, nrow=1, ncol=10, delr=1.0, delc=1.0,
                      top=1.0, botm=0.0, length_units="METERS")
    mf6.ModflowPrtmip(prt, porosity=0.2, retfactor=1.0)
    mf6.ModflowPrtprp(prt, nreleasepts=1,
                      packagedata=[(0, (0, 0, 4), 4.5, 0.5, 0.5)],
                      perioddata=[["all"]])
    mf6.ModflowPrtoc(prt, trackcsv_filerecord="prt.trk.csv",
                     track_release=True, track_timestep=True, track_terminate=True)
    mf6.ModflowGwfprt(sim, exgmnamea="gwf", exgmnameb="prt")

    sim.write_simulation(silent=True)
    ok, buff = sim.run_simulation(silent=True)
    assert ok, "\n".join(buff or []) + "\n" + (ws / "mfsim.lst").read_text()[-4000:]
    return ws


@requires_mf6
def test_prt_track_csv_has_particles(tmp_path):
    ws = _build_flow_and_prt(tmp_path)
    csv = ws / "prt.trk.csv"
    assert csv.exists()
    rows = [ln for ln in csv.read_text().splitlines() if ln.strip()]
    # header + at least one particle record
    assert rows[0] == EXPECTED_TRACK_HEADER
    assert len(rows) >= 2, "PRT released particles but wrote no pathline rows"


def test_add_prt_model_mirrors_grid_and_registers_exchange(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_npf_package,
        _impl_add_prt_model,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "prtadd"
    _impl_create_model("prtadd", str(ws), "METERS", "DAYS")
    _impl_set_simulation("prtadd", nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package("prtadd", nlay=1, nrow=1, ncol=10,
                          delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("prtadd", 0, 1.0, None, True)

    out = _impl_add_prt_model("prtadd")
    assert out["component"] == "prt"
    assert out["grid_type"] == "DIS"
    assert "Gwfprt" in out["exchange"]

    sim = model_store.get_sim("prtadd")
    prt = model_store.get_model("prtadd", "prt")
    assert isinstance(prt, mf6.ModflowPrt)
    assert prt.get_package("dis") is not None
    assert out["component_model"] in sim.model_names

    # same-sim component recorded as a plain model name, not a dict
    assert model_store.component_map("prtadd")["prt"] == out["component_model"]

    # The same-simulation exchange is proven by the written exchange file.
    model_store.flush_model("prtadd")
    workspace = model_store.resolve_workspace("prtadd")
    assert (workspace / "mfsim.gwfprt").exists()

    # PRT is explicit: the GWF IMS is listed before the PRT EMS (ruling).
    solutions = []
    for line in (workspace / "mfsim.nam").read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("ims6"):
            solutions.append(("ims", stripped))
        elif stripped.startswith("ems6"):
            solutions.append(("ems", stripped))
    assert [kind for kind, _ in solutions] == ["ims", "ems"], solutions
    assert out["component_model"] in solutions[-1][1]
    assert out["solution"] == f"{out['component_model']}.ems"


def test_add_prt_mip_package(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package, _impl_add_npf_package, _impl_create_model,
        _impl_add_prt_model, _impl_add_prt_mip_package,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "prtmip"
    _impl_create_model("prtmip", str(ws), "METERS", "DAYS")
    _impl_add_dis_package("prtmip", nlay=1, nrow=1, ncol=5,
                          delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("prtmip", 0, 1.0, None, True)
    _impl_add_prt_model("prtmip")
    out = _impl_add_prt_mip_package("prtmip", porosity=0.2, retfactor=1.0)
    assert out["package"] == "MIP"
    mip = model_store.get_model("prtmip", "prt").get_package("mip")
    assert mip is not None
    assert float(np.asarray(mip.porosity.array).ravel()[0]) == pytest.approx(0.2)


def test_add_prt_prp_package(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package, _impl_add_npf_package, _impl_create_model,
        _impl_add_prt_model, _impl_add_prt_prp_package, _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "prtprp"
    _impl_create_model("prtprp", str(ws), "METERS", "DAYS")
    _impl_set_simulation("prtprp", nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package("prtprp", nlay=1, nrow=1, ncol=5,
                          delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("prtprp", 0, 1.0, None, True)
    _impl_add_prt_model("prtprp")
    out = _impl_add_prt_prp_package(
        "prtprp", release_points=[(0, (0, 0, 2), 2.5, 0.5, 0.5)], perioddata=[["first"]]
    )
    assert out["package"] == "PRP"
    prp = model_store.get_model("prtprp", "prt").get_package("prp")
    assert prp is not None
    model_store.flush_model("prtprp")
    prtprp_file = (tmp_path / "prtprp" / out["file"]).read_text()
    assert "NRELEASEPTS  1" in prtprp_file


def test_add_prt_oc_package(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package, _impl_add_npf_package, _impl_create_model,
        _impl_add_prt_model, _impl_add_prt_oc_package, _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "prtoc"
    _impl_create_model("prtoc", str(ws), "METERS", "DAYS")
    _impl_set_simulation("prtoc", nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package("prtoc", nlay=1, nrow=1, ncol=5,
                          delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("prtoc", 0, 1.0, None, True)
    _impl_add_prt_model("prtoc")
    out = _impl_add_prt_oc_package("prtoc", trackcsv_filerecord="prtoc.trk.csv")
    assert out["package"] == "OC"
    oc = model_store.get_model("prtoc", "prt").get_package("oc")
    assert oc is not None
    assert (tmp_path / "prtoc" / "prtoc.trk.csv").exists() is False  # written at run time
    model_store.flush_model("prtoc")
    oc_file = (tmp_path / "prtoc" / f"{out['model_name']}.oc").read_text()
    assert "TRACKCSV" in oc_file.upper()
    assert "TRACK_TIMESTEP" in oc_file.upper()


def test_add_prt_prp_package_save_flows_is_noop(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package, _impl_add_npf_package, _impl_create_model,
        _impl_add_prt_model, _impl_add_prt_prp_package, _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "prtprpflows"
    _impl_create_model("prtprpflows", str(ws), "METERS", "DAYS")
    _impl_set_simulation("prtprpflows", nper=1, perlen=[1.0], nstp=[1],
                         ims_complexity="simple")
    _impl_add_dis_package("prtprpflows", nlay=1, nrow=1, ncol=5,
                          delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("prtprpflows", 0, 1.0, None, True)
    _impl_add_prt_model("prtprpflows")

    # PRP has no budget, so save_flows is an accepted no-op: the True path
    # must not be forwarded to ModflowPrtprp (which would reject it).
    out = _impl_add_prt_prp_package(
        "prtprpflows", release_points=[(0, (0, 0, 2), 2.5, 0.5, 0.5)],
        perioddata=[["first"]], save_flows=True,
    )
    assert out["package"] == "PRP"
    assert model_store.get_model("prtprpflows", "prt").get_package("prp") is not None


def test_add_npf_rebuild_preserves_prt_flow_saving(tmp_path):
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_add_npf_package,
        _impl_add_prt_model,
        _impl_create_model,
        _impl_set_simulation,
    )
    from groundwater_mcp.utils import model_store

    ws = tmp_path / "prtflags"
    _impl_create_model("prtflags", str(ws), "METERS", "DAYS")
    _impl_set_simulation("prtflags", nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package("prtflags", nlay=1, nrow=1, ncol=10,
                          delr=1.0, delc=1.0, top=1.0, botm=[0.0])
    _impl_add_npf_package("prtflags", 0, 1.0, None, True)
    _impl_add_prt_model("prtflags")

    # A later NPF rebuild (e.g. to change k) must not silently drop the
    # flow-saving flags the same-simulation GWF-PRT exchange requires.
    _impl_add_npf_package("prtflags", 0, 2.0, None, False)

    model_store.flush_model("prtflags")
    npf_text = (
        model_store.resolve_workspace("prtflags") / "prtflags.npf"
    ).read_text().upper()
    assert "SAVE_FLOWS" in npf_text
    assert "SAVE_SPECIFIC_DISCHARGE" in npf_text
