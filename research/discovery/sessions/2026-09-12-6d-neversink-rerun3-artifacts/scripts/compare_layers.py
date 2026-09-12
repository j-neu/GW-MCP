import csv, os
import numpy as np

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
OBS = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3\obs"

# base (native-parameter) simulated heads at the ORIGINAL 857 obs entries
with open(os.path.join(BASE, "neversink.head.obs")) as f:
    hdr = f.readline().strip().split(",")[1:]
    vals = f.readline().strip().split(",")[1:]
sim = {}
for name, v in zip(hdr, vals):
    sim.setdefault(name.upper(), []).append(float(v))
print("base obs columns:", len(hdr))

# per-site multilayer reference: layer order in header is layer 1,2,3,4 ascending
obs = {}
for r in csv.DictReader(open(os.path.join(OBS, "obs_heads_field.csv"), newline="")):
    obs[r["site"].upper()] = float(r["value"])

def stats(pred):
    p = np.array([v for v in pred])
    return np.sqrt(np.mean(p**2)), np.mean(p), len(p)

# choice: shallowest available layer (per-site correct)
res_shallow = [sim[n][0] - obs[n] for n in obs if n in sim]
# choice: layer 1 (only sites that have it)
res_l1 = [sim[n][0] - obs[n] for n in obs if n in sim]
# choice: layer 4 (last available) - all 448
res_l4 = [sim[n][-1] - obs[n] for n in obs if n in sim]

for label, res in [("shallowest-available", res_shallow), ("layer1", res_l1), ("layer4", res_l4)]:
    rmse, bias, n = stats(res)
    print(f"{label:22s} n={n:3d} RMSE={rmse:7.2f} m  bias={bias:7.2f} m")

# how many sites have 4 layers vs fewer
from collections import Counter
print("layer-count dist:", dict(Counter(len(v) for v in sim.values())))
