import os
from collections import Counter
import numpy as np

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
sites = {}
with open(os.path.join(BASE, "neversink.obs")) as f:
    for line in f:
        p = line.split()
        if len(p) == 5 and p[1].upper() == "HEAD":
            sites.setdefault(p[0].upper(), set()).add(int(p[2]) - 1)

idom = [np.loadtxt(os.path.join(BASE, f"idomain_00{i}.dat")) for i in range(4)]
# map site -> row,col via the clone's summary (all share row/col with original)
import csv, json
d = json.load(open(r"C:\Users\jakob\AppData\Local\Temp\kilo\neversink_cal\.gwmcp_meta.json"))
cell = {s["site"]: s["cellid"] for s in d["observations"]["sites"]}

for L in range(4):
    n_listed = sum(1 for v in sites.values() if L in v)
    n_active = sum(1 for nm, c in cell.items() if c[0] == 0 and idom[L][c[1], c[2]] > 0)
    print(f"layer {L+1}: sites listing it={n_listed:3d} | layer-{L+1} cell active at mapped row/col={n_active:3d}")

shallow = Counter(min(v) for v in sites.values())
print("shallowest listed layer distribution:", dict(sorted(shallow.items())))
