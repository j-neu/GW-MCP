import csv, os
import numpy as np

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
OBS = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3\obs"

with open(os.path.join(BASE, "neversink.head.obs")) as f:
    hdr = f.readline().strip().split(",")[1:]
    vals = f.readline().strip().split(",")[1:]
sim = {}
for name, v in zip(hdr, vals):
    sim.setdefault(name.upper(), []).append(float(v))
obs = {r["site"].upper(): float(r["value"]) for r in csv.DictReader(open(os.path.join(OBS, "obs_heads_field.csv"), newline=""))}

# vertical spread among multi-layer sites (reference run)
spreads = [max(sim[n]) - min(sim[n]) for n in sim if len(sim[n]) > 1]
print("multi-layer sites:", len(spreads), "median spread:", round(float(np.median(spreads)), 3),
      "p95:", round(float(np.percentile(spreads, 95)), 3), "max:", round(float(max(spreads)), 3))

# residual distribution using deepest available layer for all 448
res = np.array([sim[n][-1] - obs[n] for n in obs if n in sim])
print("residual (sim_L4 - obs) quantiles:")
for q in [5, 25, 50, 75, 95]:
    print(f"  p{q}: {np.percentile(res, q):8.2f}")
print("  mean %.2f  RMSE %.2f" % (res.mean(), np.sqrt((res**2).mean())))
print("  |res|>100 m:", int((np.abs(res) > 100).sum()), " |res|>50 m:", int((np.abs(res) > 50).sum()))
# worst sites
order = np.argsort(-np.abs(res))
names = [n for n in obs if n in sim]
print("worst 10:", [(names[i], round(res[i], 1)) for i in order[:10]])
