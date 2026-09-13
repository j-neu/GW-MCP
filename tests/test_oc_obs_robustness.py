"""Regression tests for two bugs exposed by the GMS mf6_pest_obs_ss rerun.

1. OC period SAVERECORD dropped on model rewrite when the period block is an
   external ``OPEN/CLOSE`` file (GMS ships
   ``BEGIN PERIOD 1 / OPEN/CLOSE GWF_Model_input/GWF_Model.oc_1.txt``), which
   left ``.hds``/``.cbc`` empty.
2. ``#`` in an observation site name (GMS ``POINT_#1``) corrupted the generated
   OBS file because MF6 treats ``#`` as a comment, aborting the base run.
"""

from __future__ import annotations

import csv
import shutil

import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_adopt_model,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.utils.model_store import (
    flush_model,
    get_gwf,
    get_sim,
    read_meta,
    save_sim,
)
from groundwater_mcp.utils.workspace import resolve_workspace


def _mf6_available() -> bool:
    try:
        from groundwater_mcp.tools.runner import _find_mf6_binary

        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(not _mf6_available(), reason="MODFLOW 6 binary not installed")


def _make_dis_model(tmp_path, name: str) -> str:
    """1-layer 2x2 DIS model with a CHD gradient, flushed to disk."""
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "simple")
    _impl_add_dis_package(name, 1, 2, 2, 100.0, 100.0, 50.0, [30.0])
    _impl_add_npf_package(name, icelltype=0, k=5.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, 0, 0], 40.0], [[0, 1, 1], 10.0]]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    flush_model(name)
    return name


# ---------------------------------------------------------------------------
# 1. OC period SAVERECORD preservation across adopt + rewrite
# ---------------------------------------------------------------------------


def _write_gms_style_oc(ws, gwf_name: str) -> None:
    """Rewrite the OC package the way GMS ships it: external period file."""
    (ws / f"{gwf_name}.oc").write_text(
        "BEGIN OPTIONS\n"
        f"  BUDGET FILEOUT outdir/{gwf_name}.cbc\n"
        f"  HEAD FILEOUT outdir/{gwf_name}.hds\n"
        "END OPTIONS\n\n"
        "BEGIN PERIOD 1\n"
        f"  OPEN/CLOSE {gwf_name}_input/{gwf_name}.oc_1.txt\n"
        "END PERIOD\n"
    )
    (ws / f"{gwf_name}_input").mkdir(exist_ok=True)
    (ws / "outdir").mkdir(exist_ok=True)
    (ws / f"{gwf_name}_input" / f"{gwf_name}.oc_1.txt").write_text(
        "PRINT BUDGET FIRST\nSAVE HEAD FIRST\nSAVE BUDGET FIRST\n"
    )


def test_adopt_restores_oc_period_records(tmp_path):
    src = _make_dis_model(tmp_path, "ocsrc")
    src_ws = resolve_workspace(src)
    _write_gms_style_oc(src_ws, "ocsrc")

    dst_ws = tmp_path / "ocdst"
    shutil.copytree(src_ws, dst_ws)
    _impl_adopt_model("ocdst", str(dst_ws), "METERS", "DAYS", allow_modify=True)

    oc = get_gwf("ocdst").get_package("oc")
    arr = (oc.saverecord.data or {}).get(0)
    pairs = {(str(r["rtype"]), str(r["ocsetting"])) for r in arr}
    assert ("HEAD", "FIRST") in pairs
    assert ("BUDGET", "FIRST") in pairs


def test_rewrite_after_adopt_preserves_oc_period_block(tmp_path):
    src = _make_dis_model(tmp_path, "ocsrc2")
    src_ws = resolve_workspace(src)
    _write_gms_style_oc(src_ws, "ocsrc2")

    dst_ws = tmp_path / "ocdst2"
    shutil.copytree(src_ws, dst_ws)
    _impl_adopt_model("ocdst2", str(dst_ws), "METERS", "DAYS", allow_modify=True)

    # Any write-triggering tool re-serialises the simulation; the period block
    # (with SAVE HEAD/BUDGET) must survive.
    save_sim("ocdst2", get_sim("ocdst2"))
    flush_model("ocdst2")
    oc_file = dst_ws / f"{get_gwf('ocdst2').name}.oc"
    text = oc_file.read_text().upper()
    assert "BEGIN PERIOD" in text
    assert "HEAD" in text and "FIRST" in text


@requires_mf6
def test_adopted_model_writes_heads_after_rewrite(tmp_path):
    from groundwater_mcp.tools.postprocess import _impl_read_heads
    from groundwater_mcp.tools.runner import _impl_run_simulation

    src = _make_dis_model(tmp_path, "ocrun")
    src_ws = resolve_workspace(src)
    _write_gms_style_oc(src_ws, "ocrun")

    dst_ws = tmp_path / "ocrun_work"
    shutil.copytree(src_ws, dst_ws)
    _impl_adopt_model("ocrunwork", str(dst_ws), "METERS", "DAYS", allow_modify=True)
    save_sim("ocrunwork", get_sim("ocrunwork"))
    flush_model("ocrunwork")

    run = _impl_run_simulation("ocrunwork")
    assert run.get("success") is True, run
    heads = _impl_read_heads("ocrunwork")
    assert heads["min"] < heads["max"]


# ---------------------------------------------------------------------------
# 2. Observation site-name sanitisation + unsupported obs types
# ---------------------------------------------------------------------------


def _write_obs_csv(tmp_path, name: str, sites, x=50.0, y=50.0):
    path = tmp_path / f"{name}_obs.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for s in sites:
            writer.writerow([s, "2020-01-01", 30.0, x, y])
    return str(path)


def test_import_obs_sanitises_hash_in_site_names(tmp_path):
    name = _make_dis_model(tmp_path, "obshash")
    csv_path = _write_obs_csv(tmp_path, name, ["POINT_#1"])
    result = _impl_import_obs_from_csv(
        name, csv_path, "HEAD", "site", "date", "value", "x", "y", 0
    )
    assert result["obs_names"]["POINT_#1"] == "POINT_1"
    # Original spelling is still the key the caller sees.
    assert "POINT_#1" in result["site_cellid_map"]

    entry = read_meta(name)["observations"]["sites"][0]
    assert entry["site"] == "POINT_1"
    assert entry["original_site"] == "POINT_#1"

    flush_model(name)
    obs_text = (resolve_workspace(name) / f"{name}.obs").read_text()
    record_lines = [
        ln
        for ln in obs_text.splitlines()
        if "HEAD" in ln.upper() and not ln.lstrip().startswith("#")
    ]
    assert record_lines
    assert "#" not in record_lines[0]


def test_import_obs_deduplicates_sanitised_names(tmp_path):
    name = _make_dis_model(tmp_path, "obsdup")
    csv_path = _write_obs_csv(tmp_path, name, ["A#1", "A 1"])
    result = _impl_import_obs_from_csv(
        name, csv_path, "HEAD", "site", "date", "value", "x", "y", 0
    )
    names = result["obs_names"]
    assert names["A#1"] == "A_1"
    assert names["A 1"] == "A_1_1"
    assert len(set(names.values())) == 2


def test_import_obs_rejects_unsupported_flow_type(tmp_path):
    name = _make_dis_model(tmp_path, "obsflow")
    csv_path = _write_obs_csv(tmp_path, name, ["FLOW1"])
    with pytest.raises(ValueError, match="Unsupported obs_type"):
        _impl_import_obs_from_csv(
            name, csv_path, "FLOW", "site", "date", "value", "x", "y", 0
        )
