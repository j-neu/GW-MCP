# CSUB `packagedata` externalisation, templating and derived-observation spike (Task 1)

- **Date**: 2026-09-19
- **Type**: de-risking spike for the CSUB support design
  (`docs/superpowers/specs/2026-09-19-csub-support-and-6d-target-design.md`), Tasks 7–8.
- **Script**: `tests/fixtures/csub_spike/spike_csub_packagedata.py` (self-contained, re-runnable;
  writes only to a scratch workspace outside the repo).
- **Verdict**: both unknowns **retired**. A subset of `packagedata` columns externalises, templates
  and substitutes under pestpp-ies, and a time-indexed instruction file reads both a raw CSUB
  compaction column and a wrapper-derived subsidence sum at a chosen row. Two non-obvious pitfalls
  were found and are recorded below (the `pyemu.Pst.from_io_files` path stripping bug, and
  `ndelaycells=3` delay-bed instability).

## Environment

| Component | Value used by the spike |
|---|---|
| Python | 3.12.11 (project venv `D:\Claude Projects\GW-MCP\.venv\Scripts\python.exe`) |
| flopy | 3.10.0 |
| pyemu | 1.4.0 |
| MF6 | 6.7.0 (2026-02-05), `C:\Users\jakob\.local\bin\mf6.exe` |
| pestpp-ies | 5.2.16, `C:\Users\jakob\.local\bin\pestpp-ies.exe` (present; no need for the glm fallback) |
| Workspace | `C:\Users\jakob\AppData\Local\Temp\kilo\csub-spike` (space-free) |

Repro (from the repo root, ~5 s, 14/14 checks):

```
.venv/Scripts/python.exe tests/fixtures/csub_spike/spike_csub_packagedata.py
```

## 1. Which file flopy writes CSUB `packagedata` into

**Inline by default.** With no externalisation, `packagedata` is a block inside `<model>.csub`
(`BEGIN packagedata ... END packagedata`); nothing is written to a separate `.dat`.

**Externalised.** Two forms work.

- Simulation-wide, all data:

  ```python
  sim.set_all_data_external(external_data_folder="external", check_data=False)
  sim.write_simulation()
  ```

  For model name `spike` this writes `external/spike.csub_packagedata.txt` and rewrites the CSUB
  block to `OPEN/CLOSE  'external\spike.csub_packagedata.txt'`. **The brief's expected
  `model.csub6_packagedata.dat` is wrong for flopy 3.10.0** — the package-flag `6` is dropped and
  the extension is `.txt`.

- Per-package, explicit filename (recommended for the builder, because it externalises *only*
  CSUB and lets the caller name the file):

  ```python
  csub.packagedata.set_data({"filename": "spike.csub_packagedata.dat", "data": packagedata})
  sim.write_simulation()
  ```

  This produced exactly that file (relative to the sim workspace) and rewrote the CSUB block to
  `OPEN/CLOSE  'spike.csub_packagedata.dat'`. MF6 read it and terminated normally.

Both files contain the same bytes and both are read by MF6 (`Normal termination of simulation`).

## 2. `packagedata` line format

One record per interbed, whitespace-delimited, **13 columns with `boundname` omitted**
(`icsubno cellid cdelay pcs0 thick_frac rnb ssv_cc sse_cr theta kv h0`; for a DIS grid `cellid`
expands to `lay row col`, so the on-disk field count is 13):

```
  1  1 1 1  nodelay       0.00000000       0.50000000       1.00000000  1.00000000E-05  1.00000000E-06       0.20000000  1.00000000E-06       0.00000000
  2  2 1 1  nodelay       0.00000000       0.50000000       1.00000000  1.00000000E-05  1.00000000E-06       0.20000000  1.00000000E-06       0.00000000
  3  1 1 1  delay       0.00000000       0.50000000       1.00000000  1.00000000E-05  1.00000000E-06       0.20000000  1.00000000E-06       0.00000000
```

- `icsubno` is right-aligned in a 3-char field (2 leading spaces for the 1-based numbers);
  `cdelay` is right-aligned in an 8-char field; the numerics use `%15.8f` / `%15.8E`
  (`<something> 0.00000000` style with leading padding).
- **flopy renumbers `icsubno` to 1-based on write**: the spike passed `0,1,2` and flopy wrote
  `1,2,3`. Do not assume the Python list value is preserved.
- **EOL is CRLF** on Windows.

## 3. Working `ptf` template layout

One wide token per interbed, placed over the target numeric **column position**, leaving all other
fields verbatim (this is the "template a subset of columns" case the design needs):

```
ptf ~
1  1  1  1  nodelay  0.00000000  ~csub_thickfrac_1~  1.00000000  1.00000000E-05  1.00000000E-06  0.20000000  1.00000000E-06  -1.00000000
2  2  1  1  nodelay  0.00000000  ~csub_thickfrac_2~  1.00000000  1.00000000E-05  1.00000000E-06  0.20000000  1.00000000E-06  -1.00000000
3  1  1  1  delay  0.00000000  ~csub_thickfrac_3~  1.00000000  1.00000000E-05  1.00000000E-06  0.20000000  1.00000000E-06  -1.00000000
```

- Token = `~` + name centred to `_TPL_TOKEN_WIDTH = 15` + `~`, i.e. **17 characters total**;
  matches the repository convention in `calibration.py`.
- Field selection is positional (`fields[6]` = `thick_frac`); the field is rebuilt by
  `"  ".join(fields)` so the remaining columns are preserved.
- Substitution was verified directly: setting `parval1 = [0.4, 0.5, 0.6]` and calling
  `pst.write_input_files()` rewrote the three rows to those values in PEST's own format
  (`4.000000E-01`, right-justified in the 17-char field) and MF6 read the result. pestpp-ies
  likewise gave each realisation a distinct simulated observation, proving per-run substitution.
- **Field width**: PEST writes values in its own `%.6E`-style format inside the token width, so the
  token must be wide enough for the largest substituted number. 17 chars is ample for `thick_frac`;
  for `ssv_cc`/`sse_cr` (already `E-05`/`E-06` magnitudes) widen to a consistent 15–17-char name
  field and confirm no overflow.
- **CRLF**: flopy writes the target with CRLF; the spike normalises the template to LF and it works.
  Either normalise or keep consistent, but do not mix.

## 4. Working `pif` instruction-file layout

The instruction file **cannot compute a sum** — it only reads tokens. The derived subsidence series
must first be materialised by the forward wrapper (which is exactly what the design already plans
for `_generate_forward_wrapper`): the wrapper reads `<model>.csub.obs.csv`, sums the `COMPACTION.*`
columns row-wise, and writes a two-column CSV:

```
time,subsidence
1.000000000000,-1.8236508240E-21
2.000000000000,1.2524020084E-04
3.000000000000,2.3999127710E-04
```

Two working pif layouts (both accepted by pestpp-ies; `nnz_obs` counted both):

Read the derived `subsidence` at data row 3:

```
pif ~
l1
l1
l1
l1 ~,~   !subsidence_row3!  
```

Read the raw `COMPACTION.02` column at data row 3 directly from `<model>.csub.obs.csv`:

```
pif ~
l1
l1
l1
l1 ~,~ ~,~   !compaction02_row3!  
```

Verified semantics (tested against a known 5-row file):

- Each `l1` result consumes one line; **`l1` count = line number read**, line 1 being the header.
  To read data row *r* you need **`r + 1`** `l1` results (header + rows 1..*r*).
- Each `~,~` group skips one leading comma-delimited field; `!name!` then captures the next field.
  (`time` → skip 1 group; `time,COMPACTION.01` → skip 2 groups; etc.)
- Values read matched the source exactly (`2.3999127710E-04` / `1.3127684380E-04`).
- No `EOL encountered` or whitespace errors: pestpp-ies exited 0 and reported both observations.
  (Note `l1` line reads, not `w` whitespace reads, are what make the comma-delimited CSV safe.)

## 5. Exact CSUB obs CSV column names MF6 emits

`<model>.csub.obs.csv` header (upper-cased obs names, `.NN` suffix preserved):

```
time,COMPACTION.01,COMPACTION.02,PRECONSTRESS.01
```

- Names come back **upper-cased** (`COMPACTION.01`, not `compaction.01`); matching must be
  case-insensitive, as the design's risk #4 already flags.
- Rows are indexed by cumulative `time` (one row per stress period when `nstp=1`); the first
  steady-state row is ~0 compaction.
- The companion `<model>.strainib.csv` (when `strainib_filerecord` is set) has a leading space and
  trailing spaces: ` INTERBED_NUMBER,INTERBED_TYPE,NODE,LAYER,ROW,COLUMN,INITIAL_THICKNESS,
  FINAL_THICKNESS,TOTAL_COMPACTION,TOTAL_STRAIN,PERCENT_COMPACTION`. Parse defensively
  (`skipinitialspace` / strip).

## 6. Pitfalls (authoritative checklist for Tasks 7–8)

1. **`pyemu.Pst.from_io_files(pst_path=".")` silently strips directories.** Passing
   `in_files=["external/spike.csub_packagedata.txt"]` with `pst_path="."` stored
   `spike.csub_packagedata.txt`, so `write_input_files()` wrote the substituted file to the
   workspace root while `<model>.csub` still opened `external/...` — pestpp then ran every
   realisation against the *un-substituted* file. **Use `pst_path=None`** to preserve relative
   subfolders. This is the single most dangerous finding: the bug produces a green run with no
   substitution at all, and only the "each realisation used its own value" check caught it.
2. **`ndelaycells=3` is numerically unstable** for a single delay interbed: CSUB `dvmax` on the
   delay node blew up to `1.08E+26` and MF6 aborted with
   `PACKAGE (…-CSUB-(3)-head) CAUSED CONVERGENCE FAILURE` for many `thick_frac` values
   (`0.1, 0.49, 0.8`, intermittently even `0.5`). **`ndelaycells=19`** (MF6 default; the holdout's
   value) converged for every value 0.01–0.95, twice in a row. The brief's `ndelaycells=3` is only
   safe for the file-format/step-1 checks; use 19 for any pestpp run.
3. **Coupled CSUB solve needs Newton + the holdout IMS settings.** `newtonoptions="newton"` on the
   GWF plus `complexity="simple"`, `outer_maximum=300`, `inner_maximum=200`,
   `outer_dvclose=inner_dvclose=1e-3`, `linear_acceleration="bicgstab"`, `relaxation_factor=0.97`
   (from `1DSubsidenceModeling-MF6CSUB/model_functions.py:202-272`). Without Newton a 1×1 column
   does not converge.
4. **Degenerate initial effective stress.** With `head_based=False`,
   `initial_preconsolidation_head=True`, `specified_initial_interbed_state=True`, an initial head
   equal to `pcs0=0` with `top=0` gave garbage (`dvmax 1E+26`) and `Negative recompression index`
   errors. Keep the initial head below ground (spike uses `strt=h0=-1.0`, GHB `-1/-2/-3`, `pcs0=0`).
5. **pestpp-ies aborts on a perfect prior.** If `obsval` equals the base simulated value, IES exits
   with `initial actual phi mean too low, ... perfect model`. Give the synthetic observation a
   non-zero residual (spike uses base × 1.05).
6. **Windows launch rules** (already in `tools.md`): the forward wrapper is stdlib-only and the
   model command uses a space-free interpreter (`calibration._space_free_interpreter()`); the
   workspace path must be space-free. The scratch path `…\Temp\kilo\csub-spike` qualifies.
7. **`sgs` is passed `sgm`'s value in the holdout script** (`model_functions.py:317`), which is a
   holdout quirk, not a required setting; do not copy it into the builder.
8. **No-delay `thick_frac` was numerically silent in the synthetic model** (direct MF6 runs: changing
   the layer-0/layer-1 no-delay interbed thickness 0.05 → 5.0 left `COMPACTION.01/02` unchanged to
   ~1E-12; only the delay interbed's `thick_frac` moved compaction). This is a model-design note,
   not an interface problem, but it means the spike's sensitivity comes from the delay interbed.
   Worth re-checking against the real holdout before shipping `csub:packagedata` bounds.

## 7. What Tasks 7–8 should build against

- Externalise with `csub.packagedata.set_data({"filename": <path>, "data": records})` so only CSUB
  is externalised and the filename is controlled; the builder's `{"filename": ...}` branch is valid.
- Template selected columns positionally over the external file, 17-char tokens
  (`~` + `_TPL_TOKEN_WIDTH=15` + `~`), one token per `(column × interbed)`; `derinclb > 0`.
- Register the input mapping with `pyemu.Pst.from_io_files(..., pst_path=None)` (or equivalent) so
  the external subfolder survives; assert at build time that the substituted file lives where
  `<model>.csub` opens it.
- Derived observations: the wrapper writes `<time>,<sum>` (case-insensitive `COMPACTION` prefix
  match); the pif reads `row+1` `l1` lines and one `~,~` group per preceding column.
- Model command: space-free interpreter + stdlib wrapper; run MF6 with `newtonoptions="newton"`
  and the holdout IMS settings.

## 8. Verification evidence

Clean run: `14 passed, 0 failed`. Key lines:

```
[PASS] set_all_data_external writes external packagedata -- external\spike.csub_packagedata.txt
[PASS] flopy writes packagedata with CRLF line endings
[PASS] MF6 reads the external packagedata
[PASS] pestpp/pyemu substitution lands in packagedata -- wrote [0.4, 0.5, 0.6]
[PASS] CSUB obs CSV column names -- time,COMPACTION.01,COMPACTION.02,PRECONSTRESS.01
[PASS] pif reads chosen row/column (spike.csub.obs.csv.pif) -- 1.3127684380E-04
[PASS] pif reads chosen row/column (derived_subsidence.csv.pif) -- 2.3999127710E-04
[PASS] pestpp-ies exited 0
[PASS] each realisation used its own substituted value
```

pestpp-ies prior ensemble (`spike.0.obs.csv`) shows distinct per-realisation simulated subsidence
(`0.000240388 / 0.000239646 / 0.000239456` vs base `0.000239991`), i.e. the template was
substituted before every forward run.

## 9. Final-review notes (2026-09-19)

Recorded during the whole-branch review's Task 11 fix wave.

- **`add_boundary_package` has no external stress-period-data form (spec risk 3).** The mf6brabant
  rerun-3 note claims a boundary package was given `{"filename": ...}` for its
  `stress_period_data`, but the delivered builder
  (`src/groundwater_mcp/tools/builder.py::_impl_add_boundary_package`) accepts only an inline
  `{stress_period: [records]}` mapping and has **no** `{"filename": ...}` branch. For Target 9 the
  GHB table is tiny (1 row × nlay × nper), so inline data is sufficient and no capability is
  missing — but the mf6brabant note's provenance is unverified and an external-SPD form is not
  implemented. CSUB `packagedata` is unaffected: it externalises through
  `pkg.packagedata.set_data({"filename": ..., "data": ...})` (this spike, §1).

