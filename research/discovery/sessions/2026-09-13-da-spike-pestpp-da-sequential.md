# Spike — a minimal sequential `pestpp-da` run (cycle tables + simulated-state advance)

- **Date**: 2026-09-13 (spike executed 2026-09-14)
- **Type**: DEV-ONLY spike (no closed-book / MCP-only constraint). Result: **positive — the minimal sequential run works.**
- **Binary**: `pestpp-da` **v5.2.16** (`C:\Users\jakob\.local\bin\pestpp-da.exe`, compiled 2024-12-01) with MF6 6.7.0 (`C:\Users\jakob\.local\bin\mf6.exe`).
- **Rerunnable script**: `research/discovery/scripts/da_spike.py`
- **Purpose**: retire the riskiest unknown before building the `setup_da_control` MCP tool — namely, exactly what file set `pestpp-da` accepts for a **sequential (cycling)** DA run, and whether per-cycle state advance needs `state_par_link` / `da_use_simulated_states`.

---

## 1. Bottom line (the five facts a developer needs)

1. **A v2 control file + external CSVs + 2 cycle tables runs end-to-end** (`pestpp-da spike.pst` → exit 0) over **2 cycles with 5 realisations**, updating one adjustable K multiplier, with **3 head observations per cycle** and a **populated parameter cycle table** driving per-cycle duration (templated TDIS `perlen`: 40 d then 100 d). No wrapper, no `.ins`-from-listing tricks.
2. **`noptmax 0` does NOT perform a DA update in v5.2.16.** It runs only the base parameter set per cycle (1 "realisation") and just carries state. **Use `noptmax 1`** for exactly one Kalman/ensemble update per cycle. (The plan/brief assumed `noptmax 0` = one update; that is wrong for this binary.)
3. **`da_num_reals` is a valid v5.2.16 option and overrides `ies_num_reals`.** The ensemble size may be given either way; both work, and when both are present the `da_` value wins (the `.rec` states `(note: 'da' args override 'ies' args when using pestpp-da)`). Verified: `da_num_reals 5` (alone) → exit 0, `number of active realizations: 5`; `ies_num_reals 5` + `da_num_reals 3` → exit 0, `...drawing parameter realizations: 3`, `number of active realizations: 3`, phi header `...,0,1,base`. **Emit `da_num_reals` to be DA-explicit.** (The literal string `da_num_reals` is absent from the binary because it is resolved through the `da_`→`ies_` alias layer — absence of the literal is *not* evidence that the option is unrecognised; the parser itself is strict, e.g. `da_bogus_option` → exit 1 `control data keyword lines were not accepted`.) The DA-only options listed in `.rec` are `da_parameter_cycle_table`, `da_observation_cycle_table`, `da_hotstart_cycle`, `da_stop_cycle`, `da_use_simulated_states`, `da_noptmax_schedule`; `da_weight_cycle_table` is also accepted but is **ignored** in v5.2.16 (see §7.1) — weights must be non-zero in `obs_data.csv`.
4. **State advance is automatic and easy** with `da_use_simulated_states True`: after each cycle PEST++-DA takes the **simulated** observations of the current cycle and writes them into the **state parameters**, which are the initial-head template tokens, so the next cycle's IC file is the previous cycle's end-of-cycle heads. Two equivalent wirings work:
   - **shared-name**: `obsnme == parnme` (e.g. both `h_0_1`), `state_par_link` left blank → logs `3 dynamic states identified through shared-names`;
   - **explicit link**: `obsnme != parnme` and `obs_data.state_par_link = <parnme>` → logs `3 dynamic states identified through observation data 'state_par_link'`.
   You may **not** do both at once for the same names (fatal, see §7.3).
5. **Keep one MF6 time step per cycle** (`NPER=1`, `NSTP=1`). The canonical MCP pif for the MF6 OBS CSV reads the **first data row**; with a single time step the first (only) row *is* the end-of-cycle value. Then the existing `_impl_generate_ins_from_obs_csv` helper (`src/groundwater_mcp/tools/calibration.py:1357`) is reusable as-is and no forward wrapper is needed.

---

## 2. The spike model (tiny transient MF6, flopy 3.10)

`da_spike.py` builds it from scratch, so a clean checkout reproduces everything.

- 1 layer, 3×3 cells, Δr=Δc=100 m, top 10 m, bottom 0 m.
- CHD west column = 10 m, east column = 5 m; recharge (RCHA) = 0.001 m/d.
- NPF `icelltype=1`, `k` read **OPEN/CLOSE** from `k.dat`.
- STO transient: ss=1e-4, sy=0.1.
- IC `strt LAYERED` read **OPEN/CLOSE** from `heads_0.dat_in`.
- TDIS: **NPER=1, NSTP=1**, `perlen` templated and driven per DA cycle by the populated parameter cycle table (cycle 0 = 40 d, cycle 1 = 100 d) — one time step per cycle (see fact 5).
- MF6 OBS package: 3 `head` observations at the interior column, rows 1–3 → `h_0_1`, `h_1_1`, `h_2_1`.
- One adjustable parameter: `k_mult` (log, 0.1–10, group `k`), repeated 9× in `k.dat.tpl` so a single parameter controls the whole K array.

Initial head is 7.5 m everywhere. With recharge the interior heads rise to ≈8.6 m over a 50-day cycle, so heads demonstrably change between cycles and state advance is observable.

**MF6 snippets** (hand-written; the flopy-written `.ic`/`.npf` are overwritten):

`spike.ic`
```
BEGIN OPTIONS
END OPTIONS
BEGIN GRIDDATA
  strt  LAYERED
    OPEN/CLOSE  'heads_0.dat_in'  FACTOR  1.0
END GRIDDATA
```

`spike.npf`
```
BEGIN OPTIONS
  SAVE_FLOWS
END OPTIONS
BEGIN GRIDDATA
  icelltype  LAYERED
    CONSTANT  1
  k  LAYERED
    OPEN/CLOSE  'k.dat'  FACTOR  1.0
END GRIDDATA
```

---

## 3. Cycle → time mapping that worked

- The DA **cycle index is not an MF6 stress period**; the model always has a single stress period.
- Cycle 0 runs MF6 once per realisation from `heads_0.dat_in` = **7.5 m**, for 50 d.
- At the end of cycle 0 the simulated heads (≈8.61 m) are transferred into the state parameters and written into `heads_0.dat_in`.
- Cycle 1 runs MF6 once per realisation from that carried-forward IC (observed in `spike.global.1.pe.csv`: state columns ≈8.5 m), for another 50 d.
- Cycle-table header `,0,1` = DA cycles 0 and 1. Observation values are supplied per cycle in `da_observation_cycle_table`, weights in `obs_data.csv`.
- **Per-cycle duration**: the spike now varies it via a populated `da_parameter_cycle_table`: TDIS `perlen` is a **fixed** parameter (`forcing` group) whose value per cycle comes from `par_cycle_tbl.csv` (`perlen,40.0,100.0`). Cycle 0 runs 40 d, cycle 1 runs 100 d; the applied value is visible in the written `spike.tdis` per cycle (see §4.9). This mirrors the `mf6_freyberg/template_seq_native` benchmark (`perlen,100000,31,29,31,...`).

---

## 4. Exact working file contents

All files live in the work dir. `MODEL = spike`.

### 4.1 `spike.pst`
```
pcf version=2
* control data keyword
pestmode                     estimation
noptmax                      1
da_num_reals                 5
ies_verbose_level            2
da_use_simulated_states      True
da_parameter_cycle_table     par_cycle_tbl.csv
da_observation_cycle_table   obs_cycle_tbl.csv
* parameter groups external
spike.pargp_data.csv
* parameter data external
spike.par_data.csv
* observation data external
spike.obs_data.csv
* model command line
C:\Users\jakob\.local\bin\mf6.exe
* model input external
spike.tplfile_data.csv
* model output external
spike.insfile_data.csv
```

Notes:
- `* model command line` may be an **absolute, space-free path** to the MF6 executable. No wrapper, no `python.exe`.
- The section order shown works; the external section bodies are the CSV filenames.
- Option names are bare keywords (no `++`) inside `* control data keyword`.

### 4.2 `spike.par_data.csv`
```
parnme,partrans,parchglim,parval1,parlbnd,parubnd,pargp,scale,offset,dercom,cycle
k_mult,log,factor,1.0,0.1,10.0,k,1.0,0.0,1,-1.0
h_0_1,none,factor,7.5,0.0,20.0,head_state,1.0,0.0,1,-1.0
h_1_1,none,factor,7.5,0.0,20.0,head_state,1.0,0.0,1,-1.0
h_2_1,none,factor,7.5,0.0,20.0,head_state,1.0,0.0,1,-1.0
perlen,fixed,factor,50.0,1e-08,11000.0,forcing,1.0,0.0,1,-1.0
```
- `cycle = -1.0` on every row = parameter present in all cycles.
- State parameters (`head_state` group) must be listed; `partrans none` is accepted.
- `perlen` is the per-cycle forcing parameter (see §4.7/§4.9): **`partrans fixed`** marks it non-adjustable (mirrors the benchmark's `perlen,fixed,...`) so the Kalman update only adjusts `k_mult` + the state parameters.
- **The `mf6_freyberg` benchmark's 11-column header has no `state_par_link` column**; the v5.2.16 binary also accepts an optional parameter-data `state_par_link` column (final-state → initial-state name). It is **not needed** with `da_use_simulated_states True`.
- Note: PEST parameter/obs names are 12-char capped for parameter names in some tooling; `h_0_1` etc. are short.

### 4.3 `spike.pargp_data.csv`
```
pargpnme,inctyp,derinc,derinclb,forcen,derincmul,dermthd,splitthresh,splitreldiff,splitaction
k,relative,0.01,0.0,switch,2.0,parabolic,1e-05,0.5,smaller
head_state,relative,0.01,0.0,switch,2.0,parabolic,1e-05,0.5,smaller
forcing,relative,0.01,0.0,switch,2.0,parabolic,1e-05,0.5,smaller
```

### 4.4 `spike.obs_data.csv` (shared-name wiring)
```
obsnme,obsval,weight,obgnme,cycle,state_par_link
h_0_1,0.0,1.0,head,-1,
h_1_1,0.0,1.0,head,-1,
h_2_1,0.0,1.0,head,-1,
```
- `obsval` is superseded by `da_observation_cycle_table`; set it to 0.
- **`weight` must be non-zero here** (v5.2.16 rejects zero-weighted observations in the cycle table, see §7.1).
- `cycle = -1` = the observation is defined for all cycles; per-cycle values come from the cycle table.
- `state_par_link` blank here because obs names equal the state parameter names.
- Explicit-link variant (also verified exit 0) instead has obs names `h_0_1…` and:
  ```
  obsnme,obsval,weight,obgnme,cycle,state_par_link
  h_0_1,0.0,1.0,head,-1,s_0_1
  h_1_1,0.0,1.0,head,-1,s_1_1
  h_2_1,0.0,1.0,head,-1,s_2_1
  ```
  with parameters/state tokens named `s_0_1…` (group `head_state`).

### 4.5 `spike.tplfile_data.csv` (model input)
```
pest_file,model_file,cycle
k.dat.tpl,k.dat,-1
heads_0.dat_in.tpl,heads_0.dat_in,-1
spike.tdis.tpl,spike.tdis,-1
```

### 4.6 `spike.insfile_data.csv` (model output)
```
pest_file,model_file,cycle
spike.obs.csv.ins,spike.obs.csv,-1
```

### 4.7 `par_cycle_tbl.csv` (populated with the per-cycle `perlen` forcing)
```
,0,1
perlen,40.0,100.0
```
- Every parameter named here is **set from the table for that cycle** before its model input is written, overriding the `par_data` `parval1`. Cycle 0 runs 40 d, cycle 1 runs 100 d. Blank cells = not applied that cycle.
- Parameters *not* listed (all adjustable parameters) keep their ensemble values; a header-only table (`,0,1`) is valid when no forcing parameters vary by cycle.
- The benchmark's table drives `perlen,100000,31,29,31,...` the same way.

### 4.8 `obs_cycle_tbl.csv` (observed heads per cycle)
```
,0,1
h_0_1,8.8,8.9
h_1_1,8.75,8.85
h_2_1,8.7,8.8
```

### 4.9 Templates
`k.dat.tpl` — one parameter repeated across the 3×3 array (wide tokens are important):
```
ptf ~
~          k_mult          ~ ~          k_mult          ~ ~          k_mult          ~
~          k_mult          ~ ~          k_mult          ~ ~          k_mult          ~
~          k_mult          ~ ~          k_mult          ~ ~          k_mult          ~
```
`heads_0.dat_in.tpl` — the state parameters are the IC tokens:
```
ptf ~
7.5000000 ~          h_0_1          ~ 7.5000000
7.5000000 ~          h_1_1          ~ 7.5000000
7.5000000 ~          h_2_1          ~ 7.5000000
```
After a run, PEST++ writes full double precision into the token field (e.g. `8.6208882898408649708699159`); the token must be wide enough (≥ 24 chars inner) or values are corrupted.

`spike.tdis.tpl` — per-cycle stress-period length (`perlen`), mirroring the benchmark:
```
ptf ~
BEGIN options
  TIME_UNITS  days
END options
BEGIN dimensions
  NPER  1
END dimensions
BEGIN perioddata
  ~          perlen          ~  1  1.0
END perioddata
```
After a full run this file's output `spike.tdis` holds cycle 1's value (100 d); with `da_stop_cycle 0` it holds cycle 0's value (40 d) — proof the populated cycle table takes effect in the written model input.

### 4.10 `spike.obs.csv.ins` — the MCP's canonical MF6-OBS-CSV reader
```
pif ~
l1
l1 ~,~   !h_0_1!  ~,~   !h_1_1!  ~,~   !h_2_1!
```
- `l1` skips the header; `~,~` (a *literal marker*) steps past the time value and each comma; `!name!` reads each site value in column order.
- Reads the **first data row**. With NSTP=1 there is exactly one data row, which is the end-of-cycle value.
- Generated by `_impl_generate_ins_from_obs_csv` (`calibration.py:1357`); names are positional so CSV header capitalisation (`H_0_1`) does not matter (PEST obs names are case-insensitive).

---

## 5. Exact commands

```
# full clean rebuild + MF6 sanity run + pestpp-da run (5 reals, 2 cycles, update)
& "D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe" ^
    research/discovery/scripts/da_spike.py --workdir <dir> --all

# reproduce the noptmax=0 (no-update) behaviour
... da_spike.py --workdir <dir> --build --da --noptmax 0

# prove the populated parameter cycle table takes effect (cycle 0 only):
# add `da_stop_cycle 0` to the PST, run, then inspect the written model input
cd <dir> && C:\Users\jakob\.local\bin\pestpp-da.exe spike.pst   # spike.tdis -> perlen 40
# without da_stop_cycle the full run ends with spike.tdis -> perlen 100 (cycle 1)

# direct
cd <dir> && C:\Users\jakob\.local\bin\pestpp-da.exe spike.pst
```

Observed: `mf6` returncode 0, `pestpp-da` returncode 0, `number of active realizations: 5`, `transferring 3 dynamic states from obs to par ensemble for 5 realizations` twice (once per cycle).

---

## 6. Output artifacts produced (all in the work dir)

| File | Meaning |
|---|---|
| `spike.phi.actual.csv` | final-cycle phi (`iteration,total_runs,mean,std,min,max,realisation columns`) |
| `spike.phi.group.csv`, `spike.phi.composite.csv`, `spike.phi.lambda.csv`, `spike.phi.meas.csv`, `spike.phi.regul.csv` | phi breakdowns |
| `spike.global.phi.actual.csv` | **per-cycle** phi: rows `cycle,iteration`, two rows per cycle (iter 0 = prior, iter 1 = post-update). Observed: cycle 1 mean 0.4163 → 0.3482. |
| `spike.global.prior.pe.csv` | prior parameter ensemble (5 rows: `0..3,base`) |
| `spike.global.<cycle>.pe.csv` | parameter ensemble at each cycle (`k_mult` + state params). Cycle 1 state params ≈ 8.5 m = carried-forward heads. |
| `spike.global.<cycle>.oe.csv` | simulated-observation ensemble per cycle |
| `spike.<cycle>.<iter>.obs.csv` | per-iteration obs ensemble (e.g. `spike.1.1.obs.csv`) |
| `spike.<cycle>.base.obs.csv` | base-controlled obs run per cycle |
| `cycle_curr_noise.csv`, `spike.global.obs+noise.csv`, `spike.0/1.obs+noise.csv` | noise realisations |
| `spike.rec` | full echo of options, external files, and per-cycle summaries |
| `heads_0.dat_in` | **state carried to the next cycle** (ends at ≈8.62 m) |
| `spike.tdis` | templated TDIS written from the parameter ensemble: holds the **last cycle's** `perlen` (100 d); with `da_stop_cycle 0` it holds cycle 0's (40 d). This is the proof the populated cycle table is applied. |

Note: the `perlen` column in `spike.global.<cycle>.pe.csv` reports the ensemble's `par_data` value (50.0), **not** the cycle-forced value — do not use `pe.csv` to verify cycle-table application; inspect the written model input (`spike.tdis`) instead.

---

## 7. Pitfalls and verbatim errors (v5.2.16)

### 7.1 Zero observation weight is fatal
First attempt set `obs_data.csv` weights to 0 and relied on a `da_weight_cycle_table`:
```
observation warning: no non-zero weighted observations
Error condition prevents further execution:
DA_OBSERVATION_CYCLE_TABLE contains zero-weighted observations, see rec file for listing
ERROR: The following observations in DA_OBSERVATION_CYCLE_TABLE have zero weight in the control file:
H_0_1 ...
```
The `da_weight_cycle_table` option was accepted but **not applied** in this build (it does not appear in the `pestpp-da options` list in `.rec`, and the weight table was never processed). **Fix: put a non-zero `weight` in `obs_data.csv`.** (A weight cycle table is not required for a minimal run.)

### 7.2 Ensemble size: `da_num_reals` (preferred) or `ies_num_reals`; `da_` wins
`da_num_reals` **is** accepted and effective in v5.2.16, resolved through the `da_`→`ies_` alias layer, so the literal string does not appear in the binary even though the option works. Verified:
```
# da_num_reals 5 alone:
...drawing parameter realizations: 5
number of active realizations: 5              # exit 0
# ies_num_reals 5 + da_num_reals 3:
...drawing parameter realizations: 3
number of active realizations: 3              # exit 0
# phi header: iteration,total_runs,mean,standard_deviation,min,max,0,1,base
```
The `.rec` records the shared list and the rule:
```
...shared pestpp-ies/pestpp-da options:
(note: 'da' args override 'ies' args when using pestpp-da)
...
ies_num_reals: ...
```
Emit `da_num_reals <N>` to be DA-explicit (`ies_num_reals` also works). The parser is genuinely strict — an unknown keyword such as `da_bogus_option` fails with `control data keyword lines were not accepted` (exit 1) — so the accepted-but-absent-literal case is specific to the alias layer, not lax parsing.

### 7.3 Do not tag a state both by shared name and by `state_par_link`
Setting `state_par_link = h_0_1` while the parameter is also named `h_0_1`:
```
...3 dynamic states identified through shared-names
EnsembleMethod error: the following state parameters nominated thru obs data linking
were already tagged as 'states' by identically named observations:
H_0_1,H_1_1,H_2_1,
```
**Fix: blank `state_par_link` (shared-name wiring) or rename the state parameters (explicit-link wiring).**

### 7.4 `noptmax 0` = no assimilation in v5.2.16
```
Note: 'NOPTMAX' == 0, switching to forgiveness mode when checking inputs
noptmax = 0, resetting max_run_fail = 1
---  'noptmax'=0, running current cycle base parameter values  ---
...transferring 3 dynamic states from obs to par ensemble for 1 realizations
```
Only `base` is run; `k_mult` stays at its control-file value. With `noptmax 1` the full 5-member ensemble runs and `k_mult` is updated each cycle. **`setup_da_control` should default `noptmax = 1`.**

### 7.5 MF6/NPF/IC input syntax
- `icelltype CONSTANT 1` in NPF is rejected:
  ```
  Error reading control record for ICELLTYPE. Use CONSTANT, INTERNAL, or OPEN/CLOSE.
  ```
  Use the benchmark form `icelltype LAYERED` / `CONSTANT 1`.
- Layered external arrays: `k LAYERED` + `OPEN/CLOSE 'k.dat' FACTOR 1.0`; IC `strt LAYERED` + `OPEN/CLOSE 'heads_0.dat_in' FACTOR 1.0`.

### 7.6 flopy cannot set the MF6 OBS output filename
`flopy.mf6.ModflowUtlobs` writes `BEGIN continuous  FILEOUT  0`; MF6 then creates a file literally named `0`. Patch the generated `.obs` to `FILEOUT  spike.obs.csv` (the record is `fileout obs_output_file_name` inside the continuous block).

### 7.7 PEST instruction files cannot parse a comma-delimited row generically
The reliable, already-tested pattern is the literal-marker pif in §4.10 (`l1 ~,~ !name! …`), which reads the *first* data row. That is why **NSTP must be 1 per cycle**. (Alternative if multiple time steps per cycle are unavoidable: a forward wrapper that writes the end-of-cycle values to a whitespace file with one value per line and an `.ins` of `l1 !name!` lines. Verified working, but unnecessary here.)

---

## 8. What `setup_da_control` must generate (concrete checklist)

Given a model + registered observations + a parameterisation, the tool must write:

1. `*.pst` v2 with: `pcf version=2`, `* control data keyword`, `pestmode estimation`, **`noptmax 1`**, **`da_num_reals <N>`**, `da_use_simulated_states True`, `da_parameter_cycle_table`, `da_observation_cycle_table`, and the five external sections (`* parameter groups/data`, `* observation data`, `* model command line`, `* model input`, `* model output`).
2. `*.pargp_data.csv` (10-col benchmark header) — one row per parameter group.
3. `*.par_data.csv` (11-col benchmark header, optional `state_par_link` 12th col) — adjustable parameters with `cycle -1`, plus one **state parameter per state cell** in a `head_state` group.
4. `*.obs_data.csv` (`obsnme,obsval,weight,obgnme,cycle,state_par_link`) — non-zero weights; `cycle -1`; `state_par_link` blank (names shared) or the state parameter name.
5. `tplfile_data.csv` / `insfile_data.csv` (`pest_file,model_file,cycle`) — IC template→`heads_0.dat_in`, K template→`k.dat`, `obs.csv.ins`→`obs.csv`, all `cycle -1`.
6. Cycle tables: `obs_cycle_tbl.csv` (per-cycle observed values, blank = inactive) and a **populated** `par_cycle_tbl.csv` for every forcing parameter whose value changes by cycle — each entry is a **fixed** parameter in a `forcing` group (e.g. templated TDIS `perlen`), with one value column per cycle. Header-only `,0,1` is valid only when no forcing parameter varies by cycle.
7. A **templated TDIS** (`spike.tdis.tpl` → `spike.tdis`) if cycle durations vary, listed in `tplfile_data.csv` with `cycle -1`.
7. A state-augmented **IC template** whose tokens are the state parameter names, and an IC package that reads it via `OPEN/CLOSE`; plus the model must have `NPER=1, NSTP=1` per cycle (or a wrapper) so the obs-CSV reader sees the end-of-cycle value.

## 9. Scope / caveats

- Positive result obtained on v5.2.16 only. `noptmax` semantics (0 = no update here) are version-specific; `da_num_reals`/`ies_num_reals` are supported in v5.2.16. `setup_da_control` should emit the v5.2.16 form and document the version assumption.
- The explicit final-state→initial-state parameter linkage route (`da_use_simulated_states False` + parameter-data `state_par_link`) was **not** exercised; v5.2.16 refuses it without linkages (`'da_use_simulated_states is false but no final-to-initial state par linkages are provided'`). The simulated-states route was chosen because it needs no such wiring.
- `tests/fixtures/da_spike/` was intentionally **not** populated: all spike outputs are binary/CSV and git-ignored. The rerunnable script rebuilds everything into any work directory.
