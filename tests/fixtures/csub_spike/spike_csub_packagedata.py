#!/usr/bin/env python
"""Task 1 spike: externalise and template CSUB ``packagedata`` under pestpp-ies.

Retires the two riskiest unknowns before the CSUB builder/calibration tasks are
written:

(a) how flopy externalises CSUB list ``packagedata`` and whether a numeric column
    of it can be templated and substituted by pestpp-ies; and
(b) whether a time-indexed instruction file can read a derived subsidence series
    (and a raw compaction column) from ``<model>.csub.obs.csv``.

It writes no product code. All model files and binaries go to a scratch
workspace *outside* the repository (default
``%TEMP%/kilo/csub-spike``) so the repository stays clean.

Usage (from the repository root, with the project venv)::

    .venv/Scripts/python.exe tests/fixtures/csub_spike/spike_csub_packagedata.py

Options::

    --ws DIR         scratch workspace (default: <temp>/kilo/csub-spike)
    --ndelaycells N  delay-bed discretisation (default 19; see findings doc)
    --keep           keep the workspace instead of rebuilding it from scratch

Findings: ``research/discovery/sessions/2026-09-19-csub-packagedata-spike.md``.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

import flopy  # noqa: E402
import pyemu  # noqa: E402

from groundwater_mcp.tools.calibration import (  # noqa: E402
    _find_mf6_binary,
    _find_pestpp_binary,
    _space_free_interpreter,
)

MODEL = "spike"
NINTERBEDS = 3
TOKEN_W = 15  # must match calibration._TPL_TOKEN_WIDTH
# 0-based whitespace field index of thick_frac in a packagedata line:
#   0 icsubno | 1-3 cellid(lay,row,col) | 4 cdelay | 5 pcs0 | 6 thick_frac
#   7 rnb | 8 ssv_cc | 9 sse_cr | 10 theta | 11 kv | 12 h0
PKG_THICKFRAC_COL = 6
SUMMARY = {"PASS": 0, "FAIL": 0}


def check(ok: bool, label: str, detail: str = "") -> bool:
    SUMMARY["PASS" if ok else "FAIL"] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    return ok


def build_model(ws: Path, ndelaycells: int):
    """1x1, 2-layer CSUB column: 3 periods (first steady), 2 no-delay interbeds
    (one per layer) and one delay interbed in layer 0."""
    sim = flopy.mf6.MFSimulation(sim_name=MODEL, version="mf6", sim_ws=str(ws))
    flopy.mf6.ModflowTdis(sim, nper=3, perioddata=[(1.0, 1, 1.0)] * 3, time_units="DAYS")
    # Solver settings mirror the 1DSubsidenceModeling-MF6CSUB holdout model:
    # Newton-Raphson flow plus these IMS settings are what make the coupled
    # CSUB/flow solve converge.
    flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        complexity="simple",
        outer_maximum=300,
        outer_dvclose=1e-3,
        inner_dvclose=1e-3,
        inner_maximum=200,
        linear_acceleration="bicgstab",
        relaxation_factor=0.97,
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname=MODEL, save_flows=True, newtonoptions="newton")
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=2,
        nrow=1,
        ncol=1,
        delr=1.0,
        delc=1.0,
        top=0.0,
        botm=[-10.0, -20.0],
        idomain=1,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=1.0)
    flopy.mf6.ModflowGwfic(gwf, strt=-1.0)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=0, ss=0.0, sy=0.0)
    flopy.mf6.ModflowGwfghb(
        gwf,
        stress_period_data={
            0: [[(0, 0, 0), -1.0, 1.0], [(1, 0, 0), -1.0, 1.0]],
            1: [[(0, 0, 0), -2.0, 1.0], [(1, 0, 0), -2.0, 1.0]],
            2: [[(0, 0, 0), -3.0, 1.0], [(1, 0, 0), -3.0, 1.0]],
        },
    )
    packagedata = [
        [0, (0, 0, 0), "nodelay", 0.0, 0.5, 1.0, 1e-5, 1e-6, 0.2, 1e-6, -1.0],
        [1, (1, 0, 0), "nodelay", 0.0, 0.5, 1.0, 1e-5, 1e-6, 0.2, 1e-6, -1.0],
        [2, (0, 0, 0), "delay", 0.0, 0.5, 1.0, 1e-5, 1e-6, 0.2, 1e-6, -1.0],
    ]
    csub = flopy.mf6.ModflowGwfcsub(
        gwf,
        print_input=True,
        save_flows=True,
        head_based=False,
        initial_preconsolidation_head=True,
        specified_initial_interbed_state=True,
        update_material_properties=False,
        ndelaycells=ndelaycells,
        ninterbeds=NINTERBEDS,
        beta=2.2270e-8,
        gammaw=62.48,
        sgm=[1.7, 1.7],
        sgs=[2.0, 2.0],
        cg_theta=[0.2, 0.2],
        cg_ske_cr=[1e-5, 1e-5],
        packagedata=packagedata,
        zdisplacement_filerecord=f"{MODEL}.displacement.hds",
        strainib_filerecord=f"{MODEL}.strainib.csv",
    )
    csub.obs.initialize(
        filename=f"{MODEL}.csub.obs",
        digits=10,
        print_input=True,
        continuous={
            f"{MODEL}.csub.obs.csv": [
                ("COMPACTION.01", "compaction-cell", (0, 0, 0)),
                ("COMPACTION.02", "compaction-cell", (1, 0, 0)),
                ("PRECONSTRESS.01", "preconstress-cell", (0, 0, 0)),
            ]
        },
    )
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord=f"{MODEL}.hds", saverecord=[("HEAD", "ALL")])
    return sim, csub, packagedata


def write_thickfrac_template(pkg_path: Path, tpl_path: Path, par_names: list[str]):
    """Rewrite flopy's external packagedata as a wide-token template.

    One token per interbed, placed over the ``thick_frac`` numeric field; every
    other field is copied verbatim. Returns (eol_kind, base_values).
    """
    raw = pkg_path.read_bytes()
    eol_kind = "CRLF" if b"\r\n" in raw else "LF"
    lines = raw.decode("ascii").replace("\r\n", "\n").rstrip("\n").split("\n")
    out = ["ptf ~"]
    bases: list[float] = []
    for i, line in enumerate(lines):
        fields = line.split()
        bases.append(float(fields[PKG_THICKFRAC_COL]))
        fields[PKG_THICKFRAC_COL] = "~" + f"{par_names[i]:^{TOKEN_W}s}" + "~"
        out.append("  ".join(fields))
    tpl_path.write_text("\n".join(out) + "\n", encoding="ascii")
    return eol_kind, bases


def write_derived_wrapper(wrapper_path: Path, mf6_exe: str) -> None:
    """stdlib-only forward wrapper: run MF6, sum the COMPACTION columns of
    ``<model>.csub.obs.csv`` into ``derived_subsidence.csv``."""
    wrapper_path.write_text(
        "import csv, os, subprocess\n"
        "\n"
        f"MF6 = {mf6_exe!r}\n"
        "WS = os.path.dirname(os.path.abspath(__file__))\n"
        "subprocess.run([MF6], cwd=WS, check=True)\n"
        "\n"
        f"src = os.path.join(WS, {MODEL + '.csub.obs.csv'!r})\n"
        "with open(src, newline='') as fh:\n"
        "    rows = list(csv.reader(fh))\n"
        "header = rows[0]\n"
        "cols = [i for i, h in enumerate(header)\n"
        "        if h.strip().upper().startswith('COMPACTION')]\n"
        "out = os.path.join(WS, 'derived_subsidence.csv')\n"
        "with open(out, 'w', newline='') as fh:\n"
        "    fh.write('time,subsidence\\n')\n"
        "    for r in rows[1:]:\n"
        "        if not r or not r[0].strip():\n"
        "            continue\n"
        "        total = sum(float(r[i]) for i in cols)\n"
        "        fh.write('%s,%.10E\\n' % (r[0], total))\n",
        encoding="ascii",
    )


def write_pif(pif_path: Path, obs_name: str, row: int, skip_cols: int) -> None:
    """Read data ``row`` (1-based) of a comma-delimited CSV.

    ``l1`` results consume one line each, so ``row + 1`` line reads are needed
    to land on data row ``row`` (line 1 is the header). ``skip_cols`` groups of
    ``~,~`` skip that many leading comma-delimited fields before ``!obs!``.
    """
    lines = ["pif ~"] + ["l1"] * row + ["l1 " + "~,~ " * skip_cols + f"  !{obs_name}!  "]
    pif_path.write_text("\n".join(lines) + "\n", encoding="ascii")


def run_exe(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    default_ws = Path(tempfile.gettempdir()) / "kilo" / "csub-spike"
    ap.add_argument("--ws", default=str(default_ws))
    ap.add_argument("--ndelaycells", type=int, default=19)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    ws = Path(args.ws)
    if ws.exists() and not args.keep:
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)
    os.chdir(ws)

    mf6_exe = _find_mf6_binary()
    pestpp_ies = _find_pestpp_binary("pestpp-ies")
    interpreter = _space_free_interpreter() or sys.executable
    print(f"workspace   : {ws}")
    print(f"mf6         : {mf6_exe}")
    print(f"pestpp-ies  : {pestpp_ies}")
    print(f"interpreter : {interpreter}")

    # ---- Step 1/2: build, externalise, inspect -------------------------
    print("\n[1/5] build model and externalise packagedata")
    sim, csub, packagedata = build_model(ws, args.ndelaycells)
    sim.write_simulation(silent=True)
    inline = (ws / f"{MODEL}.csub").read_text()
    check(
        "BEGIN packagedata" in inline and "nodelay" in inline,
        "packagedata is inline in <model>.csub by default",
    )
    sim.set_all_data_external(external_data_folder="external", check_data=False)
    sim.write_simulation(silent=True)
    pkg_path = ws / "external" / f"{MODEL}.csub_packagedata.txt"
    check(
        pkg_path.exists(),
        "set_all_data_external writes external packagedata",
        str(pkg_path.relative_to(ws)),
    )
    raw = pkg_path.read_bytes()
    eol_kind = "CRLF" if b"\r\n" in raw else "LF"
    print(f"  packagedata bytes ({len(raw)}, EOL={eol_kind}): {raw[:120]!r} ...")
    check(eol_kind == "CRLF", "flopy writes packagedata with CRLF line endings")

    r = run_exe([mf6_exe], ws)
    check("Normal termination" in r.stdout, "MF6 reads the external packagedata")

    # ---- Step 3: template thick_frac -----------------------------------
    print("\n[2/5] template thick_frac and prove substitution lands on disk")
    par_names = [f"csub_thickfrac_{i + 1}" for i in range(NINTERBEDS)]
    tpl_path = ws / f"{MODEL}.csub_packagedata.txt.tpl"
    _, bases = write_thickfrac_template(pkg_path, tpl_path, par_names)
    check(
        bases == [0.5, 0.5, 0.5],
        "template built from flopy's external file",
        f"base values {bases}",
    )
    print("  tpl:")
    print("    " + tpl_path.read_text().replace("\n", "\n    ").rstrip())

    write_derived_wrapper(ws / "spike_fwd.py", mf6_exe)
    write_pif(ws / "spike.csub.obs.csv.pif", "compaction02_row3", 3, skip_cols=2)
    write_pif(ws / "derived_subsidence.csv.pif", "subsidence_row3", 3, skip_cols=1)
    print("  raw pif     :", (ws / "spike.csub.obs.csv.pif").read_text().replace("\n", " | "))
    print("  derived pif :", (ws / "derived_subsidence.csv.pif").read_text().replace("\n", " | "))

    pst = pyemu.Pst.from_io_files(
        tpl_files=[tpl_path.name],
        in_files=[f"external/{pkg_path.name}"],
        ins_files=[f"{MODEL}.csub.obs.csv.pif", "derived_subsidence.csv.pif"],
        out_files=[f"{MODEL}.csub.obs.csv", "derived_subsidence.csv"],
        pst_filename=f"{MODEL}.pst",
        pst_path=None,  # preserve the external/ subfolder in the IO mapping
    )
    pst.control_data.noptmax = 1
    pst.pestpp_options["ies_num_reals"] = 4
    par = pst.parameter_data
    par.index = par_names
    par.loc[:, "parnme"] = par_names
    par.loc[:, "partrans"] = "none"
    par.loc[:, "pname"] = "csub"
    par.loc[:, "pargp"] = "csub_thickfrac"
    par.loc[:, "parval1"] = [0.5] * NINTERBEDS
    par.loc[:, "parlbnd"] = 0.05
    par.loc[:, "parubnd"] = 0.95
    obs = pst.observation_data
    obs.loc[:, "obsval"] = [0.0, 0.0]
    obs.loc[:, "weight"] = 1.0
    obs.loc[:, "obgnme"] = "subsidence"
    pst.model_command = [f"{interpreter} spike_fwd.py"]

    # Direct substitution check: pyemu writes the model input from parval1.
    probe = [0.4, 0.5, 0.6]
    par.loc[:, "parval1"] = probe
    pst.write_input_files(pst_path=str(ws))
    written = [
        float(pkg_path.read_text().splitlines()[i].split()[PKG_THICKFRAC_COL])
        for i in range(NINTERBEDS)
    ]
    check(written == probe, "pestpp/pyemu substitution lands in packagedata", f"wrote {written}")

    # ---- Step 4: pif over the time-indexed obs CSV ----------------------
    print("\n[3/5] run derived wrapper and validate the pifs")
    par.loc[:, "parval1"] = [0.5] * NINTERBEDS
    pst.write_input_files(pst_path=str(ws))
    r = run_exe([interpreter, "spike_fwd.py"], ws)
    check(r.returncode == 0, "forward wrapper ran", (r.stderr or "").strip()[-200:])
    obs_csv = ws / f"{MODEL}.csub.obs.csv"
    with obs_csv.open() as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    check(
        header[0] == "time" and header[1] == "COMPACTION.01",
        "CSUB obs CSV column names",
        ",".join(header),
    )
    expected_sum = sum(
        float(rows[3][i])
        for i, h in enumerate(header)
        if h.strip().upper().startswith("COMPACTION")
    )
    derived = (ws / "derived_subsidence.csv").read_text().splitlines()
    got_sum = float(derived[3].split(",")[1])
    check(
        abs(got_sum - expected_sum) < 1e-15,
        "derived wrapper sums compaction",
        f"row3 sum={expected_sum:.10E}",
    )
    from pyemu.pst import pst_utils

    for name, path, want in (
        (f"{MODEL}.csub.obs.csv.pif", obs_csv, float(rows[3][2])),
        ("derived_subsidence.csv.pif", ws / "derived_subsidence.csv", got_sum),
    ):
        extracted = pst_utils.InstructionFile(ws / name).read_output_file(path)
        got = float(extracted["obsval"].iloc[0])
        check(abs(got - want) < 1e-15, f"pif reads chosen row/column ({name})", f"{got:.10E}")

    # ---- Step 5: pestpp-ies end-to-end ----------------------------------
    print("\n[4/5] run pestpp-ies")
    # Give the observations a non-zero residual (the base run is the truth, so
    # pestpp would otherwise abort with "initial actual phi mean too low").
    obs.loc[:, "obsval"] = [float(rows[3][2]) * 1.05, got_sum * 1.05]
    pst.write(str(ws / f"{MODEL}.pst"))
    r = run_exe([pestpp_ies, f"{MODEL}.pst"], ws)
    log = (r.stdout or "") + (r.stderr or "")
    check(
        r.returncode == 0,
        "pestpp-ies exited 0",
        log.strip().splitlines()[-1][:160] if log.strip() else "",
    )
    combined = ws / f"{MODEL}.0.obs.csv"
    if check(
        combined.exists(),
        "pestpp-ies wrote ensemble obs CSV",
        combined.read_text().strip().replace("\n", " / ") if combined.exists() else "",
    ):
        with combined.open() as fh:
            ens = list(csv.reader(fh))[1:]
        values = {row[2] for row in ens if row and row[0] != "base"}
        check(len(values) > 1, "each realisation used its own substituted value")
    par_after = ws / f"{MODEL}.1.par"
    if par_after.exists():
        lines = par_after.read_text().splitlines()
        pv = [float(line.split()[1]) for line in lines[1 : 1 + NINTERBEDS]]
        check(all(0.05 <= v <= 0.95 for v in pv), "IES posterior parameters within bounds", f"{pv}")

    print(f"\n[5/5] summary: {SUMMARY['PASS']} passed, {SUMMARY['FAIL']} failed")
    return 0 if SUMMARY["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
