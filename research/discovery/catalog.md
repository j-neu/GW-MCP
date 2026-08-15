# Catalog — Discovery Round 1

Row schema:
`name | source | url | type (tutorial|example model|test problem|exercise) | capabilities showcased (matrix rows) | toolchain (MF6 GWF|GWT|SWT|PEST|UCODE|legacy) | input format (flopy script|MF6 input|ModelMuse .mmp|GMS project|NA) | data formats (GeoTIFF|SHP|CSV|zip|none) | license | accessibility (direct zip|git clone|registration|paywall) | download url | size | calibration-ready (y/n) | notes`

Rules:
- Metadata only during discovery; downloads happen only for holdout selection.
- Git sources: record clone URL + commit hash (reproducibility; re-cloned on
  demand during validation).
- Every row is capability-tagged against `../capability-matrix.md` rows.
- GAP-matrix rows need at least one example ref by end of round 1.

## Sources (round 1)

1. `MODFLOW-USGS/modflow6` test problems (git clone, shallow)
2. `MODFLOW-USGS/modflow6-examples` (git clone, shallow; holdout-archive size check)
3. GitHub topic searches (DISU, UZF, MAW, GWT, SWT, pestpp)
4. `flopy` examples dir (git clone, shallow)
5. USGS ModelMuse tutorials (playwright)
6. Aquaveo GMS tutorials (playwright)
7. HydroShare / Zenodo (playwright)

---
<!-- Rows appended below, one section per source, tagged with matrix capability names -->
