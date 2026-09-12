import csv, os

PD = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\processed_data"
MF = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
OUT = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3\obs"

os.makedirs(OUT, exist_ok=True)

with open(os.path.join(MF, "neversink.head.obs")) as f:
    header = f.readline().strip().split(",")[1:]
obs_set = set(n.upper() for n in header)

rows = []
# NY DEC wells: obsnme, gw_elev_m, x, y
with open(os.path.join(PD, "NY_DEC_GW_sites.csv"), newline="") as f:
    for row in csv.DictReader(f):
        nm = (row.get("obsnme") or "").strip()
        v = row.get("gw_elev_m")
        x = row.get("x"); y = row.get("y")
        if nm.upper() in obs_set and v not in (None, "", "None") and x and y:
            rows.append((nm, float(v), float(x), float(y), "NY_DEC"))

# NWIS well: site_no, gw_elev_m, x, y (from sites file)
sites = {}
with open(os.path.join(PD, "NWIS_GW_DV_sites.csv"), newline="") as f:
    for row in csv.DictReader(f):
        sites[(row.get("site_no") or "").strip()] = (row.get("x"), row.get("y"))
with open(os.path.join(PD, "NWIS_GW_DV_data.csv"), newline="") as f:
    for row in csv.DictReader(f):
        nm = (row.get("site_no") or "").strip()
        v = row.get("gw_elev_m")
        x, y = sites.get(nm, (None, None))
        if nm.upper() in obs_set and v and x and y:
            rows.append((nm, float(v), float(x), float(y), "NWIS"))

seen = set()
uniq = []
for r in rows:
    if r[0].upper() in seen:
        continue
    seen.add(r[0].upper())
    uniq.append(r)

path = os.path.join(OUT, "obs_heads_field.csv")
with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["site", "date", "value", "x", "y", "source"])
    for nm, v, x, y, src in uniq:
        w.writerow([nm, "2011-01-01", f"{v:.6f}", f"{x:.3f}", f"{y:.3f}", src])

print("wrote", path, "rows:", len(uniq))
vals = [r[1] for r in uniq]
print("gw_elev_m range:", round(min(vals), 2), "-", round(max(vals), 2), "mean", round(sum(vals)/len(vals), 2))
print("sources:", {s: sum(1 for r in uniq if r[4] == s) for s in ("NY_DEC", "NWIS")})
