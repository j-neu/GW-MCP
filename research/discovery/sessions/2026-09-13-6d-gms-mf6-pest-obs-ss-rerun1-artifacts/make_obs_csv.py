import os

sess = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun1"
work = os.path.join(sess, "work", "pest_obs_ss")
ref  = os.path.join(sess, "extract", "mf6_pest_obs_ss", "sample", "pest_obs_ss_models", "MODFLOW 6", "pest_obs_ss", "GWF_Model_pest")

# cell centers from CELL2D
centers = {}
with open(os.path.join(work, "GWF_Model_input", "GWF_Model.disv_CELL2D.txt")) as f:
    for i, line in enumerate(f):
        t = line.split()
        centers[i + 1] = (float(t[1]), float(t[2]))  # node -> (x, y)

# dominant node per bore
dominant = []
with open(os.path.join(ref, "model.n2b")) as f:
    for line in f:
        t = line.split()
        if not t: continue
        name = t[0]; nn = int(t[1])
        pairs = [(int(t[2+2*i]), float(t[3+2*i])) for i in range(nn)]
        node, w = max(pairs, key=lambda p: p[1])
        dominant.append((name, node, w))

# observed heads
obs = {}
with open(os.path.join(ref, "model.bsamp")) as f:
    for line in f:
        t = line.split()
        if len(t) >= 4:
            obs[t[0]] = float(t[-1])

out = os.path.join(sess, "heads_obs.csv")
with open(out, "w") as f:
    f.write("site,date,value,x,y\n")
    for name, node, w in dominant:
        x, y = centers[node]
        f.write("%s,01/01/1950,%.6f,%.4f,%.4f\n" % (name, obs[name], x, y))
        print("%-10s node=%4d w=%.4f center=(%.2f, %.2f) obs=%.2f" % (name, node, w, x, y, obs[name]))
print("wrote", out)
