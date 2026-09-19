"""Step 1 reproducer: multiplier-scope DA on the real 31,831-node holdout, run
through the same background job machinery `start_calibration(method="da")` uses,
so the instrumented wrapper trace records where (if anywhere) it blocks.

Deliberately small: 1 DA cycle, 4 realizations. The stall is in the cycle-0
initial ensemble, so this should reproduce in ~2 minutes.
"""

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"D:\Claude Projects\GW-MCP")
sys.path.insert(0, str(REPO / "src"))

from groundwater_mcp.tools import builder, calibration, parameterise  # noqa: E402
from groundwater_mcp.utils import jobs  # noqa: E402
from groundwater_mcp.utils.workspace import resolve_workspace  # noqa: E402

HOLDOUT = Path(r"E:\GW-MCP-holdout\selected\MF6_EnKF_DISU")
SIM = HOLDOUT / "NeckartalModel1718" / "NeckartalCalib_try_models" / "MODFLOW 6" / "sim"
NAME = "neck_trace"
POLL_S = 10
MAX_POLLS = 24  # 4 minutes


def mf6_count() -> int:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq mf6.exe"], capture_output=True, text=True
    ).stdout
    return out.lower().count("mf6.exe")


def main() -> None:
    cellmap = next(HOLDOUT.rglob("Pegel_Cell_ID.csv"))
    rows = list(csv.DictReader(cellmap.open(newline="", encoding="utf-8-sig")))
    sites = [r["Name"].strip() for r in rows]
    print(f"gauges: {len(sites)} from {cellmap}")

    print(builder._impl_adopt_model(NAME, str(SIM), "METERS", "DAYS", allow_modify=True))

    obs = Path(os.environ["TEMP"]) / "kilo" / "repro_obs.csv"
    with obs.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["site", "date", "value", "Cell_ID"])
        for r in rows:
            w.writerow([r["Name"].strip(), "2017-01-30", 330.0, r["Cell_ID"].strip()])
    print(
        parameterise._impl_import_obs_from_csv(
            NAME, str(obs), "HEAD", "site", "date", "value", None, None, 0, cellid_col="Cell_ID"
        )
    )

    print(builder._impl_set_simulation(NAME, 1, [1.0], [1], "complex"))

    t0 = time.time()
    setup = calibration._impl_setup_da_control(
        NAME,
        {"k_mult": {"target": "npf:k", "scope": "multiplier", "initial": 1.0}},
        cycles=[0],
        obs_cycles={s: {0: 330.0} for s in sites},
        par_cycles={"perlen": {0: 1.0}},
        num_reals=4,
        noptmax=1,
        use_simulated_states=True,
    )
    print(f"setup took {time.time() - t0:.1f}s")
    print("setup:", json.dumps(setup, indent=1, default=str))

    ws = resolve_workspace(NAME)
    pst = Path(setup["pst_file"])

    import pyemu  # noqa: E402

    command = pyemu.Pst(str(pst)).model_command[0]
    print("model_command:", command)
    tokens = command.split()
    wrapper = Path(tokens[1]) if len(tokens) > 1 else Path(tokens[0])
    if not wrapper.is_absolute():
        wrapper = ws / wrapper
    trace = wrapper.with_suffix(".trace")
    print("wrapper:", wrapper, "exists:", wrapper.exists())
    if wrapper.exists():
        body = wrapper.read_text()
        print("wrapper has trace statements:", "_trace(" in body, "| bytes:", len(body))
    print("trace file:", trace, "exists:", trace.exists())

    start = calibration._impl_start_calibration(NAME, str(pst), method="da")
    print("start_calibration ->", start)
    job_id = start.get("job_id") or start.get("id")

    k_file = ws / "flow_k.dat"
    for i in range(1, MAX_POLLS + 1):
        time.sleep(POLL_S)
        st = jobs.get_status(job_id) if job_id else {}
        run_info = (ws / "run.info").read_text().strip().replace("\n", " ") if (ws / "run.info").exists() else ""
        k = k_file.stat()
        print(
            f"[{i * POLL_S:4d}s] status={st.get('status')!r} mf6={mf6_count()} "
            f"k.dat={k.st_size}B@{k.st_mtime:0.0f} | {run_info}",
            flush=True,
        )
        if st.get("status") not in ("running", "pending", None):
            print("job finished:", json.dumps(st, default=str)[:800])
            break

    print("\n--- wrapper trace ---")
    print(trace.read_text() if trace.exists() else "(no trace file: python never executed!)")

    if job_id:
        try:
            print("cancel:", jobs.cancel(job_id))
        except Exception as exc:  # noqa: BLE001
            print("cancel failed:", exc)
    subprocess.run(["taskkill", "/IM", "pestpp-da.exe", "/T", "/F"], capture_output=True)


if __name__ == "__main__":
    main()
