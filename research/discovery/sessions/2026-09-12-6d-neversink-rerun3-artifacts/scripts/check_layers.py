import os
import numpy as np

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"

# parse pristine original OBS package from the untouched BASE model
sites = {}   # name -> sorted list of (layer,row,col) 0-based
with open(os.path.join(BASE, "neversink.obs")) as f:
    for line in f:
        p = line.split()
        if len(p) == 5 and p[1].upper() == "HEAD":
            nm = p[0].upper()
            lay, r, c = int(p[2]) - 1, int(p[3]) - 1, int(p[4]) - 1
            sites.setdefault(nm, []).append((lay, r, c))

layers = sorted({l for v in sites.values() for l, r, c in v})
print("unique sites:", len(sites), "| layers present:", layers)

idom = np.loadtxt(os.path.join(BASE, "idomain_000.dat"))
print("idomain_000 active cells:", int((idom > 0).sum()))

inactive_l1 = []
for nm, v in sites.items():
    r, c = v[0][1], v[0][2]
    # shallowest listed layer for this site
    minlay = min(l for l, r2, c2 in v)
    if minlay != 0:
        inactive_l1.append((nm, minlay))
n_deep = len(inactive_l1)
print("sites whose SHALLOWEST listed layer is >1 (layer-1 inactive/inapplicable):", n_deep)

# for those sites, does layer index 0 idomain show inactive?
cnt_inact = 0
for nm, v in sites.items():
    r, c = v[0][1], v[0][2]
    if idom[r, c] <= 0:
        cnt_inact += 1
print("sites where idomain_000 row/col is INACTIVE:", cnt_inact)
print("examples (shallowest-only-deeper):", inactive_l1[:10])
