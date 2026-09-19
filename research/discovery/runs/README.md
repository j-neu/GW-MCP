# Archived Agent Manager worktree run logs

On **2026-09-19** the Agent Manager was cleaned up: all registered worktree branches were
pruned and the on-disk worktree directories under `.kilo/worktrees/` were deleted. Because the
closed-book playbook writes its `run-log.md` inside the session folder (the worktree), the run
logs were copied here first so the evidence survives the cleanup.

**If a document in this repo cites `.kilo/worktrees/<name>/run-log.md`, the archived copy is at
`research/discovery/runs/<name>/run-log.md`.**

| archive | contents |
|---|---|
| `6d-enkf-disu-rerun1…rerun9/` | the closed-book run logs for the `MF6_EnKF_DISU` sequential-DA reruns (rerun-8 and rerun-9 are the two greens adjudicated as the Target 8 PASS; rerun4's log came from its `session6d-t8/run-log.md`) |
| `6d-enkf-disu-rerun8/`, `6d-enkf-disu-rerun9/` | the run logs plus the small artefacts the agents produced (`obs_neckartal.csv`, `obs_gauges.csv`, `da_cycles.json`) |
| `diag-multiplier-stall/` | the 2026-09-19 multiplier-stall diagnostic: the instrumented wrapper's `wrapper.trace`, the in-process reproducer `repro_multiplier_stall.py` (4 reals) and `repro_multiplier_30.py` (30 reals) — see the SDD ledger for the analysis |

The durable per-run narratives remain in `research/discovery/sessions/*.md`; this archive keeps
the raw agent-authored logs and the exact tool-call sequences that those narratives reference.
