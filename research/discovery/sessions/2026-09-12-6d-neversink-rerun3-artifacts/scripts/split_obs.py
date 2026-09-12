import csv, os

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
OBS = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3\obs"

# shallowest active layer per site, from the pristine base OBS package
shallow = {}
with open(os.path.join(BASE, "neversink.obs")) as f:
    for line in f:
        p = line.split()
        if len(p) == 5 and p[1].upper() == "HEAD":
            nm = p[0].upper()
            lay = int(p[2]) - 1
            shallow[nm] = min(shallow.get(nm, 99), lay)

rows = list(csv.DictReader(open(os.path.join(OBS, "obs_heads_field.csv"), newline="")))

shallow_rows = [r for r in rows if shallow.get(r["site"].upper(), 0) == 0]
deep_rows = [r for r in rows if shallow.get(r["site"].upper(), 0) > 0]
print("shallow(layer1) rows:", len(shallow_rows), "deep rows:", len(deep_rows))

for name, sel in [("obs_heads_shallow.csv", shallow_rows), ("obs_heads_deep.csv", deep_rows)]:
    with open(os.path.join(OBS, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["site", "date", "value", "x", "y", "source"])
        w.writeheader()
        w.writerows(sel)
    print("wrote", name, len(sel))

from collections import Counter
print("deep shallowest-layer dist:", dict(Counter(shallow[r["site"].upper()] for r in deep_rows)))
