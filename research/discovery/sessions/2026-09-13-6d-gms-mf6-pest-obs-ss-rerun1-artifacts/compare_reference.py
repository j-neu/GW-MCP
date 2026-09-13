import numpy as np, os, json

sess = r"D:\Claude Projects\GW-MCP\.kilo\worktrees\6d-gms-pest-obs-ss-rerun1"
work = os.path.join(sess, "work", "pest_obs_ss")
ref  = os.path.join(sess, "extract", "mf6_pest_obs_ss", "sample", "pest_obs_ss_models", "MODFLOW 6", "pest_obs_ss", "GWF_Model_pest")

heads = np.load(os.path.join(work, "pest_obs_ss_heads_l0_k0_0.npy")).ravel()
print("simulated heads: n=%d min=%.5f max=%.5f mean=%.5f" % (len(heads), heads.min(), heads.max(), heads.mean()))

# node-to-bore interpolation
n2b = []
with open(os.path.join(ref, "model.n2b")) as f:
    for line in f:
        t = line.split()
        if not t: continue
        name = t[0]; nn = int(t[1])
        pairs = [(int(t[2+2*i]), float(t[3+2*i])) for i in range(nn)]
        n2b.append((name, pairs))

# reference simulated (bsamp.out)
bsamp_out = {}
with open(os.path.join(ref, "model.bsamp.out")) as f:
    for line in f:
        t = line.split()
        if len(t) >= 4:
            bsamp_out[t[0]] = float(t[-1])

# observed (bsamp)
bsamp = {}
with open(os.path.join(ref, "model.bsamp")) as f:
    for line in f:
        t = line.split()
        if len(t) >= 4:
            bsamp[t[0]] = float(t[-1])

# weights bwt
bwt = {}
with open(os.path.join(ref, "model.bwt")) as f:
    for line in f:
        t = line.split()
        if len(t) >= 4:
            bwt[t[0]] = float(t[-1])

print("\n%-10s %10s %10s %10s %10s %10s" % ("point","obs","sim(mcp)","sim(ref)","resid","w"))
sims = {}
for name, pairs in n2b:
    h = sum(w * heads[n - 1] for n, w in pairs)
    sims[name] = h
    r = bsamp[name] - h
    print("%-10s %10.5f %10.5f %10.5f %10.5f %10.6f" % (name, bsamp[name], h, bsamp_out[name], r, bwt[name]))

# flow
flow_ref = None
with open(os.path.join(ref, "model.fsamp.out")) as f:
    t = f.read().split()
    flow_ref = float(t[-1])
with open(os.path.join(ref, "model.fsamp")) as f:
    t = f.read().split()
    flow_obs = float(t[-1])
print("\nflow: obs=%.4f ref_sim=%.4f" % (flow_obs, flow_ref))

# our run's RIV outflow from budget
our_flow = -5434.209358316869
print("flow: mcp_sim=%.6f  resid(obs-sim)=%.4f" % (our_flow, flow_obs - our_flow))

# stats
head_res = np.array([bsamp[n] - sims[n] for n, _ in n2b])
w_head = np.array([bwt[n] for n, _ in n2b])
f_res = flow_obs - flow_ref
f_w = 0.009333161904167185
print("\nHEAD: mean=%.6f meanabs=%.6f rmse=%.6f" % (head_res.mean(), np.abs(head_res).mean(), np.sqrt((head_res**2).mean())))
print("FLOW: mean=%.6f" % f_res)
wres = np.concatenate([w_head * head_res, [f_w * f_res]])
print("WEIGHTED: mean=%.6f meanabs=%.6f rmse=%.6f sse=%.6f" % (wres.mean(), np.abs(wres).mean(), np.sqrt((wres**2).mean()), (wres**2).sum()))
print("\nref stats file: head mean 7.707681, abs 7.951675, rmse 10.274824")
print("                flow mean 790.209358")
print("                weighted mean 7.726109, abs 8.044922, rmse 11.134540, sse 1239.779813")
