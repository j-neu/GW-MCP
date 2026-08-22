"""7e-A2 tests — automated calibration setup (`setup_calibration`).

A2.1: external-array rewiring for NPF k (OPEN/CLOSE) preserves heads.
A2.2: template generation with wide fixed-width tokens (>= 15 chars).
A2.3: instruction-file generation from the MF6 OBS CSV header.
A2.4: forward-run wrapper generation at a space-free path.
A2.5: PST assembly with derinclb > 0 and base/10–base×10 default bounds;
      a 2-parameter GLM run produces a non-zero Jacobian.
A2.6: end-to-end setup_calibration → run_pestpp_glm → summarise_calibration
      reduces phi with zero hand-written files.

See tasks.md § 7e Tier A.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import pytest
from flopy.utils import HeadFile

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.runner import _find_mf6_binary, _impl_run_simulation
from groundwater_mcp.utils.model_store import flush_model, get_gwf
from groundwater_mcp.utils.spatial import grid_centroids
from groundwater_mcp.utils.workspace import resolve_workspace


def _mf6_available() -> bool:
    try:
        _find_mf6_binary()
        return True
    except RuntimeError:
        return False


def _pestpp_available(exe: str = "pestpp-glm") -> bool:
    try:
        from groundwater_mcp.tools.calibration import _find_pestpp_binary

        _find_pestpp_binary(exe)
        return True
    except RuntimeError:
        return False


requires_mf6 = pytest.mark.skipif(
    not _mf6_available(), reason="MODFLOW 6 binary not installed"
)
requires_pestpp = pytest.mark.skipif(
    not _pestpp_available(), reason="PEST++ binaries not installed"
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _build_base_model(
    tmp_path,
    name: str = "cal_model",
    k: float = 5.0,
    nlay: int = 1,
    nrow: int = 5,
    ncol: int = 5,
    recharge: float = 0.0,
) -> str:
    """1-layer (or nlay-layer) steady-state model, CHD gradient, K uniform.

    With ``recharge > 0`` the head solution becomes K-dependent (CHD-only
    steady-state flow is linear in K and cannot constrain it).
    """
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, nlay, nrow, ncol, 100.0, 100.0, 50.0, [30.0] * nlay)
    _impl_add_npf_package(name, icelltype=0, k=k, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    chd = [[[0, r, 0], 40.0] for r in range(nrow)] + [
        [[0, r, ncol - 1], 10.0] for r in range(nrow)
    ]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    if recharge > 0:
        rch = {
            "0": [
                [0, r, c]
                for r in range(1, nrow - 1)
                for c in range(1, ncol - 1)
            ]
        }
        _impl_add_boundary_package(
            name,
            "RCH",
            {sp: [[cell, recharge] for cell in cells] for sp, cells in rch.items()},
            None,
        )
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _register_obs(tmp_path, name: str, n_obs: int = 5, cells=None) -> None:
    """Register head observations at interior grid centroids."""
    gwf = get_gwf(name)
    mg = gwf.modelgrid
    xc, yc = grid_centroids(mg)
    if cells is None:
        interior = []
        for r in range(1, mg.nrow - 1):
            for c in range(1, mg.ncol - 1):
                interior.append(r * mg.ncol + c)
        cells = interior[:n_obs]
    csv_path = tmp_path / f"{name}_obs.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["site", "date", "value", "x", "y"])
        for i, cell in enumerate(cells):
            writer.writerow(
                [f"S{i + 1:02d}", "2020-01-01", 30.0, float(xc[cell]), float(yc[cell])]
            )
    _impl_import_obs_from_csv(
        model=name,
        csv_file=str(csv_path),
        obs_type="HEAD",
        site_col="site",
        date_col="date",
        value_col="value",
        x_col="x",
        y_col="y",
        layer=0,
    )


def _head_array(name: str) -> np.ndarray:
    ws = resolve_workspace(name)
    hds = list(ws.glob("*.hds"))
    assert hds, "no .hds produced"
    return HeadFile(str(hds[0])).get_data(kstpkper=(0, 0))


# ---------------------------------------------------------------------------
# A2.1 — external-array rewiring for NPF k
# ---------------------------------------------------------------------------


@requires_mf6
def test_rewire_npf_k_external_preserves_heads(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_rewire_npf_k_external

    name = _build_base_model(tmp_path, "rewire_model")
    _impl_run_simulation(name, silent=True)
    heads_before = _head_array(name)

    result = _impl_rewire_npf_k_external(name)
    assert "error" not in result, result
    ws = resolve_workspace(name)

    # The written NPF reads k via OPEN/CLOSE and the external file exists.
    npf_text = (ws / f"{name}.npf").read_text()
    assert "OPEN/CLOSE" in npf_text, npf_text
    ext = ws / result["external_file"]
    assert ext.exists()

    # The model still runs and produces identical heads.
    run = _impl_run_simulation(name, silent=True)
    assert run["success"] is True, run.get("listing_summary", "")
    heads_after = _head_array(name)
    np.testing.assert_allclose(heads_after, heads_before, atol=1e-9)


def test_rewire_npf_k_external_requires_npf(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_rewire_npf_k_external

    name = _build_base_model(tmp_path, "no_npf_model")
    # Remove the NPF package so the helper must fail loudly.
    gwf = get_gwf(name)
    npf = gwf.get_package("npf")
    gwf.remove_package(npf)
    from groundwater_mcp.utils.model_store import save_sim

    save_sim(name, gwf.simulation)
    flush_model(name)
    with pytest.raises(ValueError, match="NPF"):
        _impl_rewire_npf_k_external(name)


# ---------------------------------------------------------------------------
# A2.2 — template generation with wide fixed-width tokens
# ---------------------------------------------------------------------------


def test_generate_tpl_uniform_wide_tokens_round_trip(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl

    name = _build_base_model(tmp_path, "tpl_uniform")
    result = _impl_generate_tpl(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    )
    tpl = Path(result["tpl_path"])
    assert tpl.exists()

    lines = tpl.read_text().splitlines()
    assert lines[0].lower().startswith("ptf")
    tokens = [ln.strip() for ln in lines[1:] if ln.strip()]
    assert len(tokens) == 25  # 1 layer × 5 rows × 5 cols
    # Every token's inner field is >= 15 characters wide (guards the @k@
    # truncation bug from Mode B rerun-4).
    for tok in tokens:
        assert tok[0] == "~" and tok[-1] == "~"
        assert len(tok) - 2 >= 15, tok

    # parse_tpl_file returns exactly the expected parameter names.
    names = pyemu.pst_utils.parse_tpl_file(str(tpl))
    assert sorted(names) == ["k"]

    # Substituting 12345.678 through the template writes a value that
    # round-trips to 12345.678 (no truncation). The template writes one
    # value per line (valid MF6 free-format external array).
    from groundwater_mcp.tools.calibration import _tpl_substitute

    target = Path(result["target"])
    _tpl_substitute(tpl, target, {"k": 12345.678})
    vals = np.loadtxt(target)
    assert vals.shape == (25,)
    assert np.all(vals == pytest.approx(12345.678, abs=1e-9))


def test_generate_tpl_zones_partition_array(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl

    name = _build_base_model(tmp_path, "tpl_zones")
    cells_left = [[0, r, c] for r in range(5) for c in range(2)]
    cells_right = [[0, r, c] for r in range(5) for c in range(2, 5)]
    result = _impl_generate_tpl(
        name,
        {
            "k_left": {
                "target": "npf:k",
                "scope": "cells",
                "cells": cells_left,
                "initial": 4.0,
            },
            "k_right": {
                "target": "npf:k",
                "scope": "cells",
                "cells": cells_right,
                "initial": 6.0,
            },
        },
    )
    names = pyemu.pst_utils.parse_tpl_file(result["tpl_path"])
    assert sorted(names) == ["k_left", "k_right"]

    # Substitute zone values: left cells (cols 0-1) get 4.0, rest get 6.0.
    from groundwater_mcp.tools.calibration import _tpl_substitute

    target = Path(result["target"])
    _tpl_substitute(Path(result["tpl_path"]), target, {"k_left": 4.0, "k_right": 6.0})
    arr = np.loadtxt(target)
    left_idx = [r * 5 + c for r in range(5) for c in range(2)]
    right_idx = [r * 5 + c for r in range(5) for c in range(2, 5)]
    assert np.all(arr[left_idx] == pytest.approx(4.0, abs=1e-9))
    assert np.all(arr[right_idx] == pytest.approx(6.0, abs=1e-9))


def test_generate_tpl_layer_scope(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl

    name = _build_base_model(tmp_path, "tpl_layers", nlay=2)
    result = _impl_generate_tpl(
        name,
        {
            "k_l0": {"target": "npf:k", "scope": "layer", "layer": 0, "initial": 5.0},
            "k_l1": {"target": "npf:k", "scope": "layer", "layer": 1, "initial": 5.0},
        },
    )
    names = pyemu.pst_utils.parse_tpl_file(result["tpl_path"])
    assert sorted(names) == ["k_l0", "k_l1"]

    from groundwater_mcp.tools.calibration import _tpl_substitute

    target = Path(result["target"])
    _tpl_substitute(Path(result["tpl_path"]), target, {"k_l0": 1.0, "k_l1": 2.0})
    arr = np.loadtxt(target)
    # External array order is layer-major: flat indices 0..24 are layer 0,
    # 25..49 are layer 1 (each cell one line in the free-format file).
    assert np.all(arr[:25] == pytest.approx(1.0, abs=1e-9))
    assert np.all(arr[25:] == pytest.approx(2.0, abs=1e-9))


def test_generate_tpl_rejects_overlapping_cells(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl

    name = _build_base_model(tmp_path, "tpl_overlap")
    shared = [[0, 0, 0], [0, 0, 1]]
    with pytest.raises(ValueError, match="overlap"):
        _impl_generate_tpl(
            name,
            {
                "k_a": {
                    "target": "npf:k",
                    "scope": "cells",
                    "cells": shared,
                    "initial": 1.0,
                },
                "k_b": {
                    "target": "npf:k",
                    "scope": "cells",
                    "cells": [[0, 0, 0]],
                    "initial": 2.0,
                },
            },
        )


def test_generate_tpl_rejects_unassigned_cells(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl

    name = _build_base_model(tmp_path, "tpl_gap")
    # Only 2 of 25 cells claimed -> the rest are unassigned.
    with pytest.raises(ValueError, match="unassigned"):
        _impl_generate_tpl(
            name,
            {
                "k_a": {
                    "target": "npf:k",
                    "scope": "cells",
                    "cells": [[0, 0, 0], [0, 0, 1]],
                    "initial": 1.0,
                }
            },
        )


def test_generate_tpl_rejects_invalid_spec(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_tpl

    name = _build_base_model(tmp_path, "tpl_invalid")
    with pytest.raises(ValueError, match="target"):
        _impl_generate_tpl(name, {"k": {"target": "npf:k22", "initial": 1.0}})
    with pytest.raises(ValueError, match="scope"):
        _impl_generate_tpl(
            name, {"k": {"target": "npf:k", "scope": "pilot", "initial": 1.0}}
        )
    with pytest.raises(ValueError, match="layer"):
        _impl_generate_tpl(
            name,
            {"k": {"target": "npf:k", "scope": "layer", "layer": 7, "initial": 1.0}},
        )
    with pytest.raises(ValueError, match="initial"):
        _impl_generate_tpl(name, {"k": {"target": "npf:k"}})


# ---------------------------------------------------------------------------
# A2.3 — instruction-file generation from the model's OBS CSV header
# ---------------------------------------------------------------------------


def test_generate_ins_from_obs_csv_header(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_ins_from_obs_csv

    csv_path = tmp_path / "m_head.obs.csv"
    csv_path.write_text("time,S01,S02,S03\n1.0,9.9,8.8,7.7\n")

    result = _impl_generate_ins_from_obs_csv(str(csv_path))
    ins = Path(result["ins_path"])
    assert ins.exists()

    # The generated pif parses via pyemu and the names equal the OBS CSV
    # column names (minus time).
    names = pyemu.pst_utils.parse_ins_file(str(ins))
    assert sorted(names) == ["s01", "s02", "s03"]

    # And it reads the right values from the CSV.
    inst = pyemu.pst_utils.InstructionFile(str(ins))
    vals = inst.read_output_file(str(csv_path))
    assert float(vals.loc["s01", "obsval"]) == pytest.approx(9.9)
    assert float(vals.loc["s03", "obsval"]) == pytest.approx(7.7)


def test_generate_ins_from_obs_csv_missing_file(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_ins_from_obs_csv

    with pytest.raises(FileNotFoundError):
        _impl_generate_ins_from_obs_csv(str(tmp_path / "nope.csv"))


def test_generate_ins_from_obs_csv_truncates_long_names(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_generate_ins_from_obs_csv

    csv_path = tmp_path / "m_head.obs.csv"
    long_site = "A_SITE_WITH_A_RIDICULOUSLY_LONG_NAME"
    csv_path.write_text(f"time,{long_site}\n1.0,9.9\n")
    result = _impl_generate_ins_from_obs_csv(str(csv_path))
    names = pyemu.pst_utils.parse_ins_file(result["ins_path"])
    assert len(names) == 1
    assert len(names[0]) <= 20  # PEST obsnme cap


# ---------------------------------------------------------------------------
# A2.4 — forward-run wrapper generation at a space-free path
# ---------------------------------------------------------------------------


@requires_mf6
def test_generate_forward_wrapper_space_free_and_runs(tmp_path):
    """The wrapper is a .py file at a space-free path (never .bat/.cmd) and
    executing it in the fixture workspace produces the model output file."""
    from groundwater_mcp.tools.builder import _impl_create_model
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper

    name = "wrap_spaces"
    ws = str(tmp_path / "model with spaces" / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=7.5)
    chd = [[[0, r, 0], 10.0] for r in range(5)] + [[[0, r, 4], 5.0] for r in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)

    result = _generate_forward_wrapper(name)
    wrapper = Path(result["wrapper_path"])
    assert " " not in str(wrapper)
    assert wrapper.suffix == ".py"
    assert ".bat" not in wrapper.name.lower()
    assert ".cmd" not in wrapper.name.lower()

    # Executing it in the fixture workspace produces the model output file.
    proc = subprocess.run(
        [sys.executable, str(wrapper)], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ws_dir = resolve_workspace(name)
    assert list(ws_dir.glob("*.hds")), "expected a head output file"

    # The PST can use this command (quoted python + space-free wrapper path).
    assert "gwmcp_run_" in result["model_command"][0]
    assert str(wrapper) in result["model_command"][0]


@requires_mf6
def test_generate_forward_wrapper_space_free_workspace_inline(tmp_path):
    """When the workspace path itself is space-free, the wrapper lives in the
    workspace and the command references it by relative name."""
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper

    name = _build_base_model(tmp_path, "wrap_plain")
    result = _generate_forward_wrapper(name)
    wrapper = Path(result["wrapper_path"])
    assert " " not in str(wrapper)
    ws_dir = resolve_workspace(name)
    assert wrapper.parent == ws_dir
    assert Path(result["model_command"][0].split()[-1]) == wrapper.name or (
        wrapper.name in result["model_command"][0]
    )


def test_generate_forward_wrapper_requires_mf6(tmp_path, monkeypatch):
    from groundwater_mcp.tools.calibration import _generate_forward_wrapper

    name = _build_base_model(tmp_path, "wrap_nomf6")
    monkeypatch.setattr(
        "groundwater_mcp.tools.calibration._find_mf6_binary",
        lambda: (_ for _ in ()).throw(RuntimeError("MODFLOW 6 binary not found")),
    )
    with pytest.raises(RuntimeError, match="MODFLOW 6"):
        _generate_forward_wrapper(name)


# ---------------------------------------------------------------------------
# A2.5 — PST assembly with safe numeric defaults
# ---------------------------------------------------------------------------


def test_setup_pest_control_safe_defaults(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_pest_control
    from groundwater_mcp.utils.workspace import create_workspace

    ws_str = str(tmp_path / "safe_defaults")
    create_workspace("safe_defaults", ws_str)
    ws_path = Path(ws_str)
    (ws_path / "params.tpl").write_text("ptf ~\n~  k  ~\n~  ss  ~\n")
    (ws_path / "heads.ins").write_text("pif @\nl1 !h1!\n")

    result = _impl_setup_pest_control(
        model="safe_defaults",
        obs_data={"h1": {"obsval": 5.0, "weight": 1.0}},
        par_data={"k": {"parval1": 5.0}, "ss": {"parval1": 0.001}},
        template_files=["params.tpl"],
        instruction_files=["heads.ins"],
    )
    pst = pyemu.Pst(result["pst_file"])
    par_df = pst.parameter_data

    # Defaulted bounds are base/10–base×10, not the old blanket 0.01–100.
    assert par_df.loc["k", "parlbnd"] == pytest.approx(0.5)  # 5.0 / 10
    assert par_df.loc["k", "parubnd"] == pytest.approx(50.0)  # 5.0 * 10
    assert par_df.loc["ss", "parlbnd"] == pytest.approx(0.0001)  # 0.001 / 10
    assert par_df.loc["ss", "parubnd"] == pytest.approx(0.01)  # 0.001 * 10
    assert par_df.loc["k", "parubnd"] / par_df.loc["k", "parval1"] <= 10.0

    # derinclb > 0 on every parameter group (zero derinclb → zero Jacobian).
    assert (pst.parameter_groups["derinclb"] > 0).all()


def test_setup_calibration_parameterisation_safe_defaults_in_pst(tmp_path):
    """setup_calibration emits bounds derived from each parameter's initial
    value and a nonzero derinclb on the group."""
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _build_base_model(tmp_path, "cal_defaults", recharge=0.001)
    _register_obs(tmp_path, name)
    result = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
    )
    assert "error" not in result, result
    pst = pyemu.Pst(result["pst_file"])
    par_df = pst.parameter_data
    assert par_df.loc["k", "parlbnd"] == pytest.approx(0.5)
    assert par_df.loc["k", "parubnd"] == pytest.approx(50.0)
    assert (pst.parameter_groups["derinclb"] > 0).all()


# ---------------------------------------------------------------------------
# A2.6 — end-to-end setup_calibration → run_pestpp_glm → summarise_calibration
# ---------------------------------------------------------------------------


@requires_mf6
@requires_pestpp
def test_setup_calibration_glm_produces_nonzero_jacobian(tmp_path):
    """A 2-parameter (zone) GLM run produces a non-zero Jacobian — guards the
    derinclb=0.0 bug that zeroed the Jacobian in Mode B rerun-4."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_calibration,
    )

    name = _build_base_model(tmp_path, "glm_zones", recharge=0.001)
    _register_obs(tmp_path, name)
    cells_left = [[0, r, c] for r in range(5) for c in range(2)]
    cells_right = [[0, r, c] for r in range(5) for c in range(2, 5)]
    setup = _impl_setup_calibration(
        name,
        {
            "k_left": {
                "target": "npf:k",
                "scope": "cells",
                "cells": cells_left,
                "initial": 5.0,
            },
            "k_right": {
                "target": "npf:k",
                "scope": "cells",
                "cells": cells_right,
                "initial": 5.0,
            },
        },
        noptmax=3,
    )
    assert "error" not in setup, setup

    run = _impl_run_pestpp_glm(name, setup["pst_file"])
    assert "error" not in run, run

    ws_dir = resolve_workspace(name)
    # GLM writes its objective-function history to <case>.iobj (7e-B1.1).
    # A decreasing total_phi proves derivatives were computed — a zero
    # Jacobian (derinclb=0.0 bug) cannot descend.
    iobj = ws_dir / f"{Path(setup['pst_file']).stem}.iobj"
    assert iobj.exists(), "no .iobj produced by the GLM run"
    df = pd.read_csv(iobj)
    assert len(df) >= 2, "GLM did not iterate"
    assert float(df["total_phi"].iloc[-1]) < float(df["total_phi"].iloc[0])
    # And the Jacobian file exists (matrix written for the 2-parameter run).
    assert list(ws_dir.glob("*.jco")), "no Jacobian (.jco) file produced"


@requires_mf6
@requires_pestpp
def test_setup_calibration_e2e_reduces_phi(tmp_path):
    """A single setup_calibration call (zero hand-written files) followed by
    run_pestpp_glm + summarise_calibration reduces phi."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_calibration,
        _impl_summarise_calibration,
    )

    name = _build_base_model(tmp_path, "e2e_cal", recharge=0.001)
    _register_obs(tmp_path, name)

    setup = _impl_setup_calibration(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}},
        noptmax=3,
    )
    assert "error" not in setup, setup
    # Zero hand-written files: everything referenced was generated.
    for key in ("template_file", "instruction_file", "pst_file"):
        assert Path(setup[key]).exists(), f"missing generated {key}: {setup[key]}"

    run = _impl_run_pestpp_glm(name, setup["pst_file"])
    assert "error" not in run, run

    summary = _impl_summarise_calibration(name, setup["pst_file"])
    assert "error" not in summary, summary
    assert summary["residual_statistics"]["n_observations"] == 5
    assert len(summary["parameter_estimates"]) == 1
    assert summary["parameter_estimates"][0]["name"] == "k"
    # The calibration actually improved the fit (nonzero Jacobian + descent).
    progress = summary["phi_progress"]
    assert progress, "expected phi progress from the GLM run"
    assert progress[-1]["phi"] < progress[0]["phi"] or summary["verdict"]["improved"]
