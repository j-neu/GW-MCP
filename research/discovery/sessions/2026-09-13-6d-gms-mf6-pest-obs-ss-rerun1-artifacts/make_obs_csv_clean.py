import os

sess = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun1"
work = os.path.join(sess, "work", "pest_obs_ss")
ref  = os.path.join(sess, "extract", "mf6_pest_obs_ss", "sample", "pest_obs_ss_models", "MODFLOW 6", "pest_obs_ss", "GWF_Model_pest")

centers = {}
with open(os.path.join(work, "GWF_Model_input", "GWF_Model.disv_CELL2D.txt")) as f:
    for i, line in enumerate(f):
        t = line.split()
        centers[i + 1] = (float(t[1]), float(t[2]))

obs = {}
with open(os.path.join(ref, "model.bsamp")) as f:
    for line in f:
        t = line.split()
        if len(t) >= 4:
            obs[t[0]] = float(t[-1])

rows = []
with open(os.path.join(ref, "model.n2b")) as f:
    for line in f:
        t = line.split()
        if not t: continue
        name = t[0]; nn = int(t[1])
        pairs = [(int(t[2+2*i]), float(t[3+2*i])) for i in range(nn)]
        node, w = max(pairs, key=lambda p: p[1])
        rows.append((name, node, w))

out = os.path.join(sess, "heads_obs_clean.csv")
with open(out, "w") as f:
    f.write("site,date,value,x,y\n")
    for name, node, w in rows:
        x, y = centers[node]
        site = "pt%02d" % int(name.split("#")[1])  # pt01..pt10
        f.write("%s,01/01/1950,%.6f,%.4f,%.4f\n" % (site, obs[name], x, y))
        print("%-6s <- %-10s node=%4d obs=%.2f" % (site, name, node, obs[name]))
print("wrote", out)
