import csv, os, sys
import numpy as np

BASE = r"D:\Claude Projects\GW-MCP-holdout\selected\neversink_workflow\neversink_mf6"
CAL = r"C:\Users\jakob\AppData\Local\Temp\kilo\neversink_cal"
OBS = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-neversink-rerun3\obs"

obs = {}
for r in csv.DictReader(open(os.path.join(OBS, "obs_heads_field.csv"), newline="")):
    obs[r["site"].upper()] = float(r["value"])

def read_obs_csv(path):
    """Return dict site->value from an MF6 obs CSV (header row names, first data row)."""
    with open(path) as f:
        hdr = f.readline().strip().split(",")[1:]
        vals = f.readline().strip().split(",")[1:]
    out = {}
    for n, v in zip(hdr, vals):
        out.setdefault(n.upper(), []).append(float(v))
    return out

def fit(pairs):
    r = np.array([s - o for s, o in pairs])
    return len(r), float(np.sqrt((r**2).mean())), float(r.mean())

# native: deepest available (layer-4 cell is what the calibrated set observes)
native = read_obs_csv(os.path.join(BASE, "neversink.head.obs"))
nat_pairs = [(native[n][-1], obs[n]) for n in obs if n in native]
print("NATIVE  ", fit(nat_pairs))

cal_path = os.path.join(CAL, "neversink_head.obs.csv")
if os.path.exists(cal_path):
    cal = read_obs_csv(cal_path)
    cal_pairs = [(cal[n][0], obs[n]) for n in obs if n in cal]
    print("CALIBR " , fit(cal_pairs))
    # largest improvements / degradations
    if len(cal_pairs) == len(nat_pairs):
        d = {}
        for n in obs:
            if n in native and n in cal:
                d[n] = abs(native[n][-1] - obs[n]) - abs(cal[n][0] - obs[n])
        top = sorted(d, key=lambda k: -d[k])[:8]
        print("most improved:", [(k, round(d[k], 1)) for k in top])

# parameter estimates
par = os.path.join(CAL, "neversink_cal.par")
if os.path.exists(par):
    with open(par) as f:
        lines = [l.rstrip("\n") for l in f if l.strip() and not l.startswith("#")]
    # PEST++ .par format: name then value on following line, or same line
    vals = {}
    i = 0
    while i < len(lines):
        tok = lines[i].split()
        if len(tok) >= 2:
            try:
                vals[tok[0]] = float(tok[1])
            except ValueError:
                pass
        i += 1
    print("n params in .par:", len(vals))
    for k in list(vals)[:25]:
        print("  ", k, vals[k])
