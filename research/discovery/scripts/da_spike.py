"""Dev spike: minimal sequential pestpp-da run on a tiny transient MF6 model.

Rebuilds everything from scratch into a work directory, then (optionally) runs
pestpp-da.  This is a research/dev artifact -- it is NOT part of the MCP server.

Usage (from a clean checkout):

    python research/discovery/scripts/da_spike.py --workdir <dir> [--mf6] [--da]
    python research/discovery/scripts/da_spike.py --workdir <dir> --all

    --build   write the MF6 model + DA interface files
    --mf6     run the single MF6 model and report
    --da      run pestpp-da on the generated control file
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from pathlib import Path

import flopy

MF6 = r"C:\Users\jakob\.local\bin\mf6.exe"
PESTPPDA = r"C:\Users\jakob\.local\bin\pestpp-da.exe"
# NOTE: no forward-model wrapper is needed.  The MF6 OBS package writes a CSV
# and pestpp-da reads it via an instruction file (see write_da).  The model
# command is the space-free MF6 executable path.

MODEL = "spike"
NLAY, NROW, NCOL = 1, 3, 3
TOPELEV, BOTELEV = 10.0, 0.0
DELR = DELC = 100.0
PERLEN = 50.0
NSTP = 1
HEAD_WEST, HEAD_EAST = 10.0, 5.0
STRT0 = 7.5
K0 = 1.0
RECHARGE = 0.001
SS, SY = 1e-4, 0.1
# observed/state cells: interior column (col index 1), all rows
STATE_CELLS = [(0, 0, 1), (0, 1, 1), (0, 2, 1)]
OBS_NAMES = [f"h_{r}_{c}" for (_l, r, c) in STATE_CELLS]
NOPTMAX = 1  # v5.2.16: noptmax=1 performs ONE Kalman update per cycle.
# Per-cycle stress-period length (days), driven by the populated
# da_parameter_cycle_table.  Distinct values make the effect observable.
PERLEN_CYCLE = {0: 40.0, 1: 100.0}


def tdis_template() -> str:
    return (
        "ptf ~\n"
        "BEGIN options\n"
        "  TIME_UNITS  days\n"
        "END options\n"
        "BEGIN dimensions\n"
        "  NPER  1\n"
        "END dimensions\n"
        "BEGIN perioddata\n"
        "  ~          perlen          ~  1  1.0\n"
        "END perioddata\n"
    )


def build_model(ws: Path) -> None:
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    sim = flopy.mf6.MFSimulation(
        sim_name=MODEL, version="mf6", exe_name=MF6, sim_ws=str(ws)
    )
    flopy.mf6.ModflowTdis(
        sim,
        time_units="DAYS",
        nper=1,
        perioddata=[(PERLEN, NSTP, 1.0)],
        filename=f"{MODEL}.tdis",
    )
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        filename=f"{MODEL}.ims",
        outer_dvclose=1e-6,
        inner_dvclose=1e-8,
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname=MODEL, save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=NLAY,
        nrow=NROW,
        ncol=NCOL,
        delr=DELR,
        delc=DELC,
        top=TOPELEV,
        botm=[BOTELEV],
        filename=f"{MODEL}.dis",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=STRT0, filename=f"{MODEL}.ic")
    flopy.mf6.ModflowGwfnpf(
        gwf, icelltype=1, k=K0, save_flows=True, filename=f"{MODEL}.npf"
    )
    flopy.mf6.ModflowGwfsto(
        gwf, ss=SS, sy=SY, transient=True, filename=f"{MODEL}.sto"
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge=RECHARGE, filename=f"{MODEL}.rch")
    spd = [((0, r, 0), HEAD_WEST) for r in range(NROW)]
    spd += [((0, r, NCOL - 1), HEAD_EAST) for r in range(NROW)]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=spd, filename=f"{MODEL}.chd")
    flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{MODEL}.cbc",
        head_filerecord=f"{MODEL}.hds",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        filename=f"{MODEL}.oc",
    )
    obs_rows = [(name, "head", cell, None) for name, cell in zip(OBS_NAMES, STATE_CELLS)]
    flopy.mf6.ModflowUtlobs(
        gwf,
        digits=8,
        continuous=obs_rows,
        filename=f"{MODEL}.obs",
        pname="obs",
    )
    sim.write_simulation(silent=True)

    # flopy cannot set the obs output filename in __init__; patch the FILEOUT.
    obsp = ws / f"{MODEL}.obs"
    txt = obsp.read_text()
    txt = txt.replace("FILEOUT  0", f"FILEOUT  {MODEL}.obs.csv")
    obsp.write_text(txt)
    (ws / "0").unlink(missing_ok=True)

    # --- hand-patch: IC reads layered heads from an external (templated) file
    ic = f"""BEGIN OPTIONS
END OPTIONS
BEGIN GRIDDATA
  strt  LAYERED
    OPEN/CLOSE  'heads_0.dat_in'  FACTOR  1.0
END GRIDDATA
"""
    (ws / f"{MODEL}.ic").write_text(ic)

    # --- hand-patch: NPF k reads an external (templated) file
    npf = f"""BEGIN OPTIONS
  SAVE_FLOWS
END OPTIONS
BEGIN GRIDDATA
  icelltype  LAYERED
    CONSTANT  1
  k  LAYERED
    OPEN/CLOSE  'k.dat'  FACTOR  1.0
END GRIDDATA
"""
    (ws / f"{MODEL}.npf").write_text(npf)

    # external arrays
    (ws / "heads_0.dat_in").write_text(
        "\n".join(
            " ".join(f"{STRT0:.6f}" for _ in range(NCOL)) for _ in range(NROW)
        )
        + "\n"
    )
    (ws / "k.dat").write_text(
        "\n".join(" ".join(f"{K0:.6f}" for _ in range(NCOL)) for _ in range(NROW))
        + "\n"
    )

    # --- MF6 observation package is written by flopy (writes spike.obs.csv)

    write_da(ws)
    print(f"[build] model written to {ws}")


def k_template() -> str:
    tok = "~          k_mult          ~"
    return "ptf ~\n" + "\n".join(" ".join([tok] * NCOL) for _ in range(NROW)) + "\n"


def heads_template() -> str:
    def tok(name: str) -> str:
        return f"~          {name}          ~"

    rows = []
    for r in range(NROW):
        row = ["7.5000000"] * NCOL
        row[1] = tok(OBS_NAMES[r])
        rows.append(" ".join(row))
    return "ptf ~\n" + "\n".join(rows) + "\n"


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)


def write_da(ws: Path) -> None:
    # template files (pest_file -> model_file are declared in the tpl file csv)
    (ws / "k.dat.tpl").write_text(k_template())
    (ws / "heads_0.dat_in.tpl").write_text(heads_template())
    (ws / "spike.tdis.tpl").write_text(tdis_template())

    # instruction file: MCP's canonical pif for an MF6 OBS continuous CSV
    # (line 1 = header, line 2 = the single time-step row; ~,~ skips the time
    # and the comma separators, !name! reads each site value in column order).
    ins = "pif ~\nl1\nl1 " + "".join(f"~,~   !{n}!  " for n in OBS_NAMES).strip() + "\n"
    (ws / f"{MODEL}.obs.csv.ins").write_text(ins)

    # parameter groups
    write_csv(
        ws / "spike.pargp_data.csv",
        [
            "pargpnme",
            "inctyp",
            "derinc",
            "derinclb",
            "forcen",
            "derincmul",
            "dermthd",
            "splitthresh",
            "splitreldiff",
            "splitaction",
        ],
        [
            ["k", "relative", 0.01, 0.0, "switch", 2.0, "parabolic", 1e-05, 0.5, "smaller"],
            ["head_state", "relative", 0.01, 0.0, "switch", 2.0, "parabolic", 1e-05, 0.5, "smaller"],
            ["forcing", "relative", 0.01, 0.0, "switch", 2.0, "parabolic", 1e-05, 0.5, "smaller"],
        ],
    )

    # parameters: one adjustable K multiplier + one state parameter per obs cell
    # + one FIXED per-cycle forcing parameter (perlen, set by the cycle table).
    par_rows = [
        ["k_mult", "log", "factor", 1.0, 0.1, 10.0, "k", 1.0, 0.0, 1, -1.0],
    ]
    for n in OBS_NAMES:
        par_rows.append([n, "none", "factor", STRT0, 0.0, 20.0, "head_state", 1.0, 0.0, 1, -1.0])
    par_rows.append(
        ["perlen", "fixed", "factor", PERLEN, 1e-8, 1.1e4, "forcing", 1.0, 0.0, 1, -1.0]
    )
    write_csv(
        ws / "spike.par_data.csv",
        [
            "parnme",
            "partrans",
            "parchglim",
            "parval1",
            "parlbnd",
            "parubnd",
            "pargp",
            "scale",
            "offset",
            "dercom",
            "cycle",
        ],
        par_rows,
    )

    # observations: obsval comes from the cycle table, cycle=-1 = all cycles
    obs_rows = [[n, 0.0, 1.0, "head", -1, ""] for n in OBS_NAMES]
    write_csv(
        ws / "spike.obs_data.csv",
        ["obsnme", "obsval", "weight", "obgnme", "cycle", "state_par_link"],
        obs_rows,
    )

    # template / instruction file listings
    write_csv(
        ws / "spike.tplfile_data.csv",
        ["pest_file", "model_file", "cycle"],
        [
            ["k.dat.tpl", "k.dat", -1],
            ["heads_0.dat_in.tpl", "heads_0.dat_in", -1],
            ["spike.tdis.tpl", "spike.tdis", -1],
        ],
    )
    write_csv(
        ws / "spike.insfile_data.csv",
        ["pest_file", "model_file", "cycle"],
        [[f"{MODEL}.obs.csv.ins", f"{MODEL}.obs.csv", -1]],
    )

    # cycle tables ---------------------------------------------------------
    cycles = [0, 1]
    # parameter cycle table: per-cycle values for the fixed forcing parameter
    write_csv(
        ws / "par_cycle_tbl.csv",
        [""] + cycles,
        [["perlen"] + [PERLEN_CYCLE[c] for c in cycles]],
    )
    # observation values per cycle (one row per obs)
    obs_vals = {
        "h_0_1": [8.80, 8.90],
        "h_1_1": [8.75, 8.85],
        "h_2_1": [8.70, 8.80],
    }
    write_csv(
        ws / "obs_cycle_tbl.csv",
        [""] + cycles,
        [[n] + obs_vals[n] for n in OBS_NAMES],
    )

    # PST -----------------------------------------------------------------
    pst = f"""pcf version=2
* control data keyword
pestmode                     estimation
noptmax                      {NOPTMAX}
da_num_reals                 5
ies_verbose_level            2
da_use_simulated_states      True
da_parameter_cycle_table     par_cycle_tbl.csv
da_observation_cycle_table   obs_cycle_tbl.csv
* parameter groups external
spike.pargp_data.csv
* parameter data external
spike.par_data.csv
* observation data external
spike.obs_data.csv
* model command line
{MF6}
* model input external
spike.tplfile_data.csv
* model output external
spike.insfile_data.csv
"""
    (ws / f"{MODEL}.pst").write_text(pst)
    print(f"[build] DA interface written to {ws}")


def run_da(ws: Path) -> None:
    r = subprocess.run(
        [PESTPPDA, f"{MODEL}.pst"], cwd=str(ws), capture_output=True, text=True
    )
    print("[pestpp-da] returncode", r.returncode)
    print("---- stdout ----")
    print(r.stdout[-6000:])
    if r.stderr.strip():
        print("---- stderr ----")
        print(r.stderr[-3000:])
    rec = ws / f"{MODEL}.rec"
    if rec.exists():
        print("---- rec tail ----")
        print("\n".join(rec.read_text(errors="replace").splitlines()[-40:]))
    for name in (
        f"{MODEL}.phi.actual.csv",
        f"{MODEL}.global.phi.actual.csv",
        f"{MODEL}.global.0.pe.csv",
        f"{MODEL}.global.1.pe.csv",
        f"{MODEL}.tdis",
    ):
        p = ws / name
        if p.exists():
            print(f"---- {name} ----")
            print(p.read_text().strip())


def run_mf6(ws: Path) -> None:
    cmd = [MF6]
    r = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True)
    print("[mf6] returncode", r.returncode)
    lst = ws / f"{MODEL}.lst"
    if lst.exists():
        tail = lst.read_text(errors="replace").splitlines()[-8:]
        print("\n".join(tail))
    csvp = ws / f"{MODEL}.obs.csv"
    if csvp.exists():
        print("[mf6] obs csv:", csvp.read_text().strip().replace("\n", " | "))


def main() -> None:
    global NOPTMAX
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--mf6", action="store_true")
    ap.add_argument("--da", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument(
        "--noptmax",
        type=int,
        default=None,
        help="override the PST noptmax (v5.2.16: 1 = one DA update/cycle, "
        "0 = run base values only, no update)",
    )
    args = ap.parse_args()
    if args.noptmax is not None:
        NOPTMAX = args.noptmax
    ws = Path(args.workdir)
    do_build = args.build or args.all
    do_mf6 = args.mf6 or args.all
    do_da = args.da or args.all
    if not (do_build or do_mf6 or do_da):
        do_build = True
    if do_build:
        build_model(ws)
    if do_mf6:
        run_mf6(ws)
    if do_da:
        run_da(ws)


if __name__ == "__main__":
    main()
