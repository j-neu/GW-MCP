import csv, os
import numpy as np

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
PD = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\processed_data"

dec = {}
for r in csv.DictReader(open(os.path.join(PD, "NY_DEC_GW_sites.csv"), newline="")):
    dec[(r["obsnme"] or "").strip().upper()] = r

with open(os.path.join(BASE, "neversink.head.obs")) as f:
    hdr = f.readline().strip().split(",")[1:]
    vals = f.readline().strip().split(",")[1:]
sim = {}
for name, v in zip(hdr, vals):
    sim.setdefault(name.upper(), []).append(float(v))

rows = list(csv.DictReader(open(r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3\obs\obs_heads_field.csv", newline="")))
res = {}
for r in rows:
    n = r["site"].upper()
    if n in sim and n in dec:
        res[n] = sim[n][-1] - float(r["value"])

gw0 = [n for n in res if str(dec[n].get("GW_Depth", "")).strip() in ("0", "0.0", "")]
print("sites total:", len(res), "| with GW_Depth 0/blank:", len(gw0))
r_all = np.array(list(res.values()))
r_non = np.array([res[n] for n in res if n not in gw0])
for label, a in [("all", r_all), ("GW_Depth>0", r_non)]:
    print(f"{label:14s} n={len(a):3d} RMSE={np.sqrt((a**2).mean()):7.2f} bias={a.mean():7.2f} max|r|={np.abs(a).max():7.1f}")

worst = sorted(res, key=lambda n: -abs(res[n]))[:12]
print("worst sites (name, res, GW_Depth, ls_elev_m, gw_elev_m):")
for n in worst:
    print(" ", n, round(res[n], 1), dec[n].get("GW_Depth"), dec[n].get("ls_elev_m"), dec[n].get("gw_elev_m"))
