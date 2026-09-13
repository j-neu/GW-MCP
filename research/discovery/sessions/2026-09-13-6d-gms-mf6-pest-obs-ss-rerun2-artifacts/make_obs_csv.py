import json, csv, os

base = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun2\data\mf6_pest_obs_ss\sample\pest_obs_ss_data\Components\d9b1d0e5-5d30-467e-b370-74ae197807dc"

with open(os.path.join(base, "model.b2map")) as f:
    b2map = json.load(f)

weights = {}
with open(os.path.join(base, "model.bwt")) as f:
    for line in f:
        parts = line.split()
        if parts:
            weights[parts[0]] = float(parts[-1])

flow_obs = None
with open(os.path.join(base, "model.fsamp")) as f:
    parts = f.read().split()
    flow_obs = float(parts[-1])

with open(os.path.join(base, "model.fwt")) as f:
    flow_wt = float(f.read().split()[-1])

rows = []
for site, meta in b2map.items():
    if not site.startswith("POINT_"):
        continue
    x, y, obs = meta["geometry"]
    rows.append((site, "1950-01-01", obs, x, y, weights.get(site, 1.0)))

out = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun2\run\obs_points.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["site", "date", "value", "x", "y", "weight"])
    for r in rows:
        w.writerow(r)

print("wrote", out)
for site, d, obs, x, y, wt in rows:
    print(f"{site:10s} x={x:12.4f} y={y:12.4f} obs={obs:9.3f} weight={wt:.6f}")
print(f"FLOW obs={flow_obs} weight={flow_wt}")
