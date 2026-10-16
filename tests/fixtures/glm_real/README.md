# Real pestpp-glm output

`real_glm.iobj` and `real_glm.par` were written by pestpp-glm 5.2.16 on
2026-10-16, not hand-made. The run was the synthetic two-zone pilot-point case
from `tests/test_pilot_points.py`:
- truth K of 20 m/d in the west half and 2 m/d in the east;
- 16 head observations;
- a uniform 6 m/d start;
- 9 pilot points;
- `noptmax=3`.

The capture used `setup_calibration` and `run_pestpp_glm`.

Used by `test_run_pestpp_glm_reads_a_real_iobj` (7e-B1.3).
