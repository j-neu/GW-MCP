import csv, os, sys
import numpy as np

MF = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
PD = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\processed_data"

# --- model OBS header ---
with open(os.path.join(MF, "neversink.head.obs")) as f:
    header = f.readline().strip().split(",")
obs_names = header[1:]  # drop 'time'
print("head.obs columns:", len(obs_names), "unique names:", len(set(n.upper() for n in obs_names)))
from collections import Counter
c = Counter(n.upper() for n in obs_names)
dups = {k: v for k, v in c.items() if v > 1}
print("names appearing >1x:", len(dups), "| max dupes:", max(c.values()))
print("example dupes:", list(dups.items())[:5])

# --- NY DEC observed elevations ---
dec = {}
with open(os.path.join(PD, "NY_DEC_GW_sites.csv"), newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        nm = (row.get("obsnme") or "").strip().upper()
        v = row.get("gw_elev_m")
        if nm and v not in (None, "", "None"):
            try:
                dec[nm] = float(v)
            except ValueError:
                pass
print("NY_DEC sites with gw_elev_m:", len(dec))

# --- NWIS observed elevation ---
nwis = {}
with open(os.path.join(PD, "NWIS_GW_DV_data.csv"), newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        nm = (row.get("site_no") or "").strip().upper()
        v = row.get("gw_elev_m")
        if nm and v:
            nwis[nm] = float(v)
print("NWIS sites:", nwis)

obs_set = set(c)
dec_match = sorted(n for n in dec if n in obs_set)
nwis_match = sorted(n for n in nwis if n in obs_set)
print("DEC matches model OBS:", len(dec_match))
print("NWIS matches model OBS:", nwis_match)
print("union observed sites:", len(dec_match) + len(nwis_match))

# --- K unique values per layer ---
for lay in range(4):
    a = np.loadtxt(os.path.join(MF, f"k{lay}.dat"))
    a = a[np.isfinite(a)]
    u = np.unique(a)
    print(f"k{lay}.dat unique K values ({len(u)}):", np.round(u, 6)[:30])
