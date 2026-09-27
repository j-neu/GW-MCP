from __future__ import annotations

from pathlib import Path

import flopy.mf6 as mf6
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
