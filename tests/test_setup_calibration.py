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
import shlex
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

    # The PST can use this command (space-free interpreter + space-free wrapper
    # path, so nothing on the command line needs quoting).
    assert "gwmcp_run_" in result["model_command"][0]
    assert str(wrapper) in result["model_command"][0]


def test_generate_forward_wrapper_detaches_mf6_stdio(tmp_path, monkeypatch):
    """The MF6 child must not inherit PEST++'s FIFO stdio.

    PEST++ launches the model command with FIFO stdin/stdout/stderr. MF6 writes
    its console listing to stdout; for the 158-period H201 model that listing is
    ~657 KB, which fills the 64 KB Windows pipe buffer and wedges the forward run
    at ``mf6_start`` (6d Target 9 reruns 2-5). The wrapper must detach all three
    streams: MF6 already writes its full listing to ``<gwf>.lst``.
    """
    import groundwater_mcp.tools.calibration as cal

    name = _build_base_model(tmp_path, "wrap_detach")
    monkeypatch.setattr(cal, "_find_mf6_binary", lambda: "/fake/mf6")
    source = Path(cal._generate_forward_wrapper(name)["wrapper_path"]).read_text()
    assert "stdin=subprocess.DEVNULL" in source
    assert "stdout=subprocess.DEVNULL" in source
    assert "stderr=subprocess.DEVNULL" in source


@requires_mf6
def test_generate_forward_wrapper_command_executes_with_spaced_mf6(tmp_path, monkeypatch):
    """The generated wrapper *command* itself runs the model.

    This is the one case that still produces a wrapper — an MF6 binary whose
    own path contains a space — so it covers the interpreter choice and the
    quoting of ``model_command`` (Task 9). The real MF6 binary is copied to a
    space-containing path (offline, no download) so the command is genuinely
    executable, and the command string is tokenised the way pestpp/shell would
    before being run.
    """
    import shutil

    import groundwater_mcp.tools.calibration as cal
    from groundwater_mcp.tools.calibration import (
        _generate_forward_wrapper,
        _space_free_interpreter,
    )

    name = _build_base_model(tmp_path, "wrap_spacedbin")
    spaced_bin = tmp_path / "bin dir" / "mf6 spaced.exe"
    spaced_bin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_find_mf6_binary(), spaced_bin)
    monkeypatch.setattr(cal, "_find_mf6_binary", lambda: str(spaced_bin))

    assert cal._needs_forward_wrapper(name), "a space-containing binary path needs a wrapper"
    result = _generate_forward_wrapper(name)
    command = result["model_command"][0]
    assert "gwmcp_run_" in command

    # The command carries no space in any *path* when a space-free interpreter
    # exists: the wrapper is stdlib-only, so the base interpreter is used and no
    # quoting of a space-containing exe path is needed. (The single space that
    # separates the interpreter from the wrapper script is structural.)
    wrapper = Path(result["wrapper_path"])
    args = [tok.strip('"') for tok in shlex.split(command, posix=False)]
    assert all(" " not in tok for tok in args), args
    assert Path(args[0]).exists(), args
    assert args[1] in (wrapper.name, str(wrapper)), args
    space_free = _space_free_interpreter()
    if space_free is not None:
        assert args[0] == space_free, args

    ws_dir = resolve_workspace(name)
    proc = subprocess.run(args, cwd=str(ws_dir), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list(ws_dir.glob("*.hds")), "expected the wrapper command to run the model"


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


@requires_mf6
@requires_pestpp
def test_setup_calibration_rch_recharge_e2e_moves_parameter(tmp_path):
    """R3.2: a recharge-only calibration really substitutes into the RCH file —
    the heads respond, phi falls and the parameter moves up toward the data."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_calibration,
        _impl_summarise_calibration,
    )

    name = _build_base_model(tmp_path, "rch_e2e", recharge=0.001)
    _register_obs(tmp_path, name)
    setup = _impl_setup_calibration(
        name,
        {
            "rech": {
                "target": "rch:recharge",
                "scope": "all",
                "initial": 0.0001,
                "lower_factor": 0.01,
                "upper_factor": 1000.0,
            }
        },
        noptmax=4,
    )
    assert "error" not in setup, setup
    run = _impl_run_pestpp_glm(name, setup["pst_file"])
    assert "error" not in run, run

    summary = _impl_summarise_calibration(name, setup["pst_file"])
    assert "error" not in summary, summary
    estimate = summary["parameter_estimates"][0]
    assert estimate["name"] == "rech"
    assert estimate["estimated_value"] > estimate["initial_value"] * 2, estimate
    progress = summary["phi_progress"]
    assert progress[-1]["phi"] < progress[0]["phi"]


def test_rejected_setup_leaves_no_artifacts(tmp_path):
    """R4.1: an obs-interface failure must not leave snapshots/externals behind."""
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _build_base_model(tmp_path, "no_obs", recharge=0.001)  # no observations
    ws = resolve_workspace(name)
    before = {p.name for p in ws.iterdir()}
    with pytest.raises(ValueError, match="obs_source='model' requires"):
        _impl_setup_calibration(
            name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
        )
    assert {p.name for p in ws.iterdir()} == before


def _drain_model(tmp_path, name, cond=1000.0, conds=None):
    name = _build_base_model(tmp_path, name, recharge=0.001)
    rows = range(1, 4)
    recs = [
        [[0, r, 2], 5.0, (conds[i] if conds else cond)] for i, r in enumerate(rows)
    ]
    _impl_add_boundary_package(name, "DRN", {"0": recs}, None)
    return name


@requires_mf6
@requires_pestpp
def test_setup_calibration_drn_cond_e2e_moves_parameter(tmp_path):
    """R3.2: drain conductance is substituted into the DRN file by PEST++."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_glm,
        _impl_setup_calibration,
        _impl_summarise_calibration,
    )

    name = _drain_model(tmp_path, "drn_e2e")
    _register_obs(tmp_path, name)
    setup = _impl_setup_calibration(
        name,
        {
            "dcond": {
                "target": "drn:cond",
                "scope": "all",
                "initial": 1000.0,
                "lower_factor": 0.0001,
                "upper_factor": 10.0,
            }
        },
        noptmax=5,
    )
    assert "error" not in setup, setup
    run = _impl_run_pestpp_glm(name, setup["pst_file"])
    assert "error" not in run, run
    summary = _impl_summarise_calibration(name, setup["pst_file"])
    est = summary["parameter_estimates"][0]
    assert est["name"] == "dcond"
    assert est["estimated_value"] != pytest.approx(est["initial_value"], rel=1e-3)
    progress = summary["phi_progress"]
    assert progress[-1]["phi"] < progress[0]["phi"]


def test_drn_cond_refuses_nonuniform_base(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _drain_model(tmp_path, "drn_het", conds=[1.0, 2.0, 3.0])
    _register_obs(tmp_path, name)
    with pytest.raises(ValueError, match="uniform"):
        _impl_setup_calibration(
            name, {"dcond": {"target": "drn:cond", "scope": "all", "initial": 2.0}}
        )


@requires_mf6
@pytest.mark.skipif(not _pestpp_available("pestpp-opt"), reason="pestpp-opt not installed")
@pytest.mark.skipif(not _pestpp_available("pestpp-swp"), reason="pestpp-swp not installed")
def test_run_pestpp_opt_maximises_drainage_subject_to_a_head_limit(tmp_path):
    """Maximise drain conductance while keeping a head above a limit."""
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_opt,
        _impl_run_pestpp_sweep,
        _impl_setup_calibration,
    )

    name = _drain_model(tmp_path, "opt_model")
    _register_obs(tmp_path, name)
    setup = _impl_setup_calibration(
        name,
        {
            "dcond": {
                "target": "drn:cond", "scope": "all", "initial": 1000.0,
                "lower_factor": 0.01, "upper_factor": 10.0,
            }
        },
        noptmax=0,
    )
    assert "error" not in setup, setup
    csv_path = tmp_path / "bounds.csv"
    csv_path.write_text("dcond\n1000.0\n10000.0\n")
    sweep = _impl_run_pestpp_sweep(name, setup["pst_file"], parameter_csv=str(csv_path))
    high = sweep["runs"][0]["observations"]["s01"]  # the starting point, cond 1000
    low = sweep["runs"][1]["observations"]["s01"]   # strongest drain, cond 10000
    assert high > low
    # A limit below the starting head keeps the start feasible, so the linearised
    # problem is well posed; draining harder is then bounded by the limit.
    limit = low + 0.5 * (high - low)

    out = _impl_run_pestpp_opt(
        name,
        setup["pst_file"],
        objective="dcond",
        decision_parameters=["dcond"],
        constraints={"s01": {"type": "greater_than", "value": limit}},
        direction="max",
    )
    cond = out["optimal_decisions"]["dcond"]
    assert 1000.0 < cond <= 10000.0  # drains harder than the start, up to the limit
    assert out["objective_value"] == pytest.approx(cond)
    (c,) = out["constraints"]
    assert c["observation"] == "s01" and c["simulated"] is not None
    # the linearised constraint is respected to within a small fraction of the range
    assert c["simulated"] >= limit - 0.1 * (high - low)

    # A limit the start cannot meet (linearised) is reported as infeasible, not as
    # a nonsense optimum.
    with pytest.raises(ValueError, match="infeasible"):
        _impl_run_pestpp_opt(
            name,
            setup["pst_file"],
            objective="dcond",
            decision_parameters=["dcond"],
            constraints={"s01": {"type": "greater_than", "value": high + 3.0}},
            direction="max",
        )


def test_run_pestpp_opt_validates_inputs(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_opt,
        _impl_setup_calibration,
    )

    name = _drain_model(tmp_path, "opt_bad")
    _register_obs(tmp_path, name)
    setup = _impl_setup_calibration(
        name, {"dcond": {"target": "drn:cond", "scope": "all", "initial": 1000.0}}, noptmax=0
    )
    pst = setup["pst_file"]
    ok = {"s01": {"type": "greater_than", "value": 1.0}}
    with pytest.raises(ValueError, match="not in the control file"):
        _impl_run_pestpp_opt(name, pst, "dcond", ["nope"], ok)
    with pytest.raises(ValueError, match="not a decision parameter"):
        _impl_run_pestpp_opt(name, pst, {"other": 1.0}, ["dcond"], ok)
    with pytest.raises(ValueError, match="type must be"):
        _impl_run_pestpp_opt(name, pst, "dcond", ["dcond"], {"s01": {"type": "equal", "value": 1}})
    with pytest.raises(ValueError, match="direction"):
        _impl_run_pestpp_opt(name, pst, "dcond", ["dcond"], ok, direction="up")


def test_drn_cond_cells_scope_keeps_unclaimed_and_rejects_overlap(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _drain_model(tmp_path, "drn_cells", conds=[1.0, 2.0, 3.0])
    _register_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name,
        {
            "da": {"target": "drn:cond", "scope": "cells", "cells": [[0, 1, 2]], "initial": 7.0},
            "db": {"target": "drn:cond", "scope": "cells", "cells": [[0, 2, 2]], "initial": 8.0},
        },
    )
    assert "error" not in res, res
    assert res["n_adjustable_parameters"] == 2
    ws = resolve_workspace(name)
    rows = [ln.split() for ln in (ws / "drn_cells.drn_0.dat").read_text().splitlines() if ln.strip()]
    assert [float(r[4]) for r in rows] == pytest.approx([7.0, 8.0, 3.0])
    with pytest.raises(ValueError, match="claimed by both"):
        _impl_setup_calibration(
            name,
            {
                "x": {"target": "drn:cond", "scope": "cells", "cells": [[0, 1, 2]]},
                "y": {"target": "drn:cond", "scope": "cells", "cells": [[0, 1, 2]]},
            },
        )


def test_drn_cond_template_tokenises_cond_column(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _drain_model(tmp_path, "drn_tpl")
    _register_obs(tmp_path, name)
    res = _impl_setup_calibration(
        name, {"dcond": {"target": "drn:cond", "scope": "all", "initial": 500.0}}
    )
    assert "error" not in res, res
    ws = resolve_workspace(name)
    tpl = (ws / "drn_tpl.drn_0.dat.tpl").read_text().splitlines()
    assert tpl[0] == "ptf ~"
    for line in tpl[1:]:
        # cellid (3 tokens), elev literal, then the padded cond token
        assert line.rstrip().endswith("~") and "dcond" in line
        assert line.split()[3] == "5.00000000E+00"
    dat = (ws / "drn_tpl.drn_0.dat").read_text().split()
    assert float(dat[4]) == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# R4.2 — a uniform parameter must not silently flatten a heterogeneous array
# ---------------------------------------------------------------------------


def _heterogeneous_k_model(tmp_path, name: str = "hetero") -> str:
    _build_base_model(tmp_path, name=name)
    k = np.full((1, 5, 5), 5.0)
    k[0, :, 3:] = 50.0
    get_gwf(name).get_package("npf").k.set_data(k)
    return name


def test_normalise_rejects_uniform_param_over_heterogeneous_k(tmp_path):
    """scope="all" over a field holding several K values would replace them
    all with ``initial`` (EnKF rerun-5: 10,413 distinct values became one)."""
    from groundwater_mcp.tools.calibration import _normalise_parameterisation

    name = _heterogeneous_k_model(tmp_path)
    with pytest.raises(ValueError, match="allow_flatten") as excinfo:
        _normalise_parameterisation(
            name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
        )
    assert "2 distinct" in str(excinfo.value)


def test_normalise_allows_flatten_when_requested(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_parameterisation

    name = _heterogeneous_k_model(tmp_path)
    norm = _normalise_parameterisation(
        name,
        {"k": {"target": "npf:k", "scope": "all", "initial": 5.0, "allow_flatten": True}},
    )
    assert len(norm["cell_param"]) == 25


def test_normalise_accepts_params_matching_uniform_blocks(tmp_path):
    """Parameters whose cells each hold one value flatten nothing."""
    from groundwater_mcp.tools.calibration import _normalise_parameterisation

    name = _heterogeneous_k_model(tmp_path)
    low = [[0, r, c] for r in range(5) for c in range(3)]
    high = [[0, r, c] for r in range(5) for c in range(3, 5)]
    norm = _normalise_parameterisation(
        name,
        {
            "klow": {"target": "npf:k", "scope": "cells", "cells": low, "initial": 5.0},
            "khigh": {"target": "npf:k", "scope": "cells", "cells": high, "initial": 50.0},
        },
    )
    assert len(norm["cell_param"]) == 25


def test_normalise_ignores_inactive_cells_when_checking_heterogeneity(tmp_path):
    from groundwater_mcp.tools.calibration import _normalise_parameterisation

    name = _heterogeneous_k_model(tmp_path)
    idomain = np.ones((1, 5, 5), dtype=int)
    idomain[0, :, 3:] = 0
    get_gwf(name).get_package("dis").idomain.set_data(idomain)
    norm = _normalise_parameterisation(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}
    )
    assert len(norm["cell_param"]) == 25


def test_setup_calibration_rejects_flattening_after_a_previous_setup(tmp_path):
    """The check reads the pristine snapshot, so a field already flattened by
    an earlier opted-in setup is still reported on the next call."""
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    name = _heterogeneous_k_model(tmp_path)
    _register_obs(tmp_path, name)
    spec = {"target": "npf:k", "scope": "all", "initial": 5.0}
    first = _impl_setup_calibration(name, {"k": {**spec, "allow_flatten": True}})
    assert "error" not in first, first
    with pytest.raises(ValueError, match="allow_flatten"):
        _impl_setup_calibration(name, {"k": spec})


# ---------------------------------------------------------------------------
# R3.1 — write calibrated parameters back into the model
# ---------------------------------------------------------------------------


def _calibration_setup(tmp_path, name="wb_model", scope="all"):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    _build_base_model(tmp_path, name=name, recharge=0.001)
    _register_obs(tmp_path, name)
    param = {"target": "npf:k", "scope": scope, "initial": 5.0}
    result = _impl_setup_calibration(name, {"k": param}, noptmax=0)
    assert "error" not in result, result
    return result["pst_file"]


def _fake_glm_par(pst_file: str, value: float) -> None:
    base = Path(pst_file).with_suffix("")
    Path(f"{base}.par").write_text(f"single point\nk   {value:.8e}  1.0  0.0\n")


def test_apply_calibration_result_writes_glm_estimate_into_npf(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result

    pst = _calibration_setup(tmp_path)
    _fake_glm_par(pst, 12.5)
    result = _impl_apply_calibration_result("wb_model", pst)

    assert result["engine"] == "glm"
    assert result["parameters"] == {"k": pytest.approx(12.5)}
    k = np.asarray(get_gwf("wb_model").get_package("npf").k.array)
    assert np.allclose(k, 12.5)


def test_apply_calibration_result_changes_the_simulated_heads(tmp_path):
    """The point of the tool: a forward run of the model now uses the
    calibrated field, so heads/plots/exports reflect the calibration."""
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result

    pst = _calibration_setup(tmp_path)
    flush_model("wb_model")
    before = _impl_run_simulation("wb_model")
    assert before.get("success") is True, before
    heads_before = _head_array("wb_model").copy()

    _fake_glm_par(pst, 50.0)
    _impl_apply_calibration_result("wb_model", pst)
    after = _impl_run_simulation("wb_model")
    assert after.get("success") is True, after
    assert not np.allclose(heads_before, _head_array("wb_model"))


def test_apply_calibration_result_without_an_estimate_fails_loudly(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result

    pst = _calibration_setup(tmp_path)
    with pytest.raises(FileNotFoundError, match="calibration"):
        _impl_apply_calibration_result("wb_model", pst)


def test_apply_calibration_result_records_what_was_applied(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_apply_calibration_result
    from groundwater_mcp.utils.model_store import read_meta

    pst = _calibration_setup(tmp_path)
    _fake_glm_par(pst, 7.0)
    _impl_apply_calibration_result("wb_model", pst)
    applied = read_meta("wb_model")["calibration_applied"]
    assert applied["engine"] == "glm"
    assert applied["parameters"] == {"k": pytest.approx(7.0)}


# ---------------------------------------------------------------------------
# R2.5 — pestpp-sen global sensitivity (Morris)
# ---------------------------------------------------------------------------


def _sen_model(tmp_path, name="sen_model"):
    from groundwater_mcp.tools.calibration import _impl_setup_calibration

    _build_base_model(tmp_path, name=name, recharge=0.001)
    _register_obs(tmp_path, name)
    result = _impl_setup_calibration(
        name, {"k": {"target": "npf:k", "scope": "all", "initial": 5.0}}, noptmax=0
    )
    assert "error" not in result, result
    return result["pst_file"]


@pytest.mark.skipif(not _pestpp_available("pestpp-sen"), reason="pestpp-sen not installed")
def test_run_pestpp_sen_ranks_parameters(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_sen

    pst = _sen_model(tmp_path)
    pst_before = Path(pst).read_text()
    result = _impl_run_pestpp_sen("sen_model", pst, method="morris", morris_r=4, morris_p=4)

    assert result["method"] == "morris"
    assert result["completed"] is True
    ranked = result["parameters"]
    assert [p["name"] for p in ranked] == ["k"]
    assert ranked[0]["mu_star"] > 0 and ranked[0]["n_samples"] > 0
    assert ranked[0]["rank"] == 1
    assert result["by_observation_group"][0]["obs_group"] == "head_obs"
    assert Path(result["summary_file"]).exists()
    # the control file the caller built must not be modified
    assert Path(pst).read_text() == pst_before


def test_run_pestpp_sen_rejects_unverified_method(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_sen

    pst = _sen_model(tmp_path, "sen_model2")
    with pytest.raises(ValueError, match="morris"):
        _impl_run_pestpp_sen("sen_model2", pst, method="fast")


@pytest.mark.skipif(not _pestpp_available("pestpp-swp"), reason="pestpp-swp not installed")
def test_run_pestpp_sweep_lhs_runs_inside_bounds(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_sweep

    pst = _sen_model(tmp_path, "swp_model")
    before = Path(pst).read_text()
    out = _impl_run_pestpp_sweep("swp_model", pst, num_samples=6, seed=3)
    assert out["n_runs"] == 6 and out["n_failed"] == 0
    assert out["parameter_names"] == ["k"]
    ks = [r["parameters"]["k"] for r in out["runs"]]
    assert all(0.5 <= k <= 50.0 for k in ks)  # base 5, factors 0.1 / 10
    assert len(set(round(k, 6) for k in ks)) == 6
    assert all(r["phi"] is not None and r["observations"] for r in out["runs"])
    # higher K lowers heads under recharge, so phi vs the 30 m targets differs
    assert out["phi_range"]["max"] > out["phi_range"]["min"]
    assert Path(pst).read_text() == before


@pytest.mark.skipif(not _pestpp_available("pestpp-swp"), reason="pestpp-swp not installed")
def test_run_pestpp_sweep_explicit_csv_and_missing_column(tmp_path):
    from groundwater_mcp.tools.calibration import _impl_run_pestpp_sweep

    pst = _sen_model(tmp_path, "swp_model2")
    good = tmp_path / "vectors.csv"
    good.write_text("k\n1.0\n5.0\n20.0\n")
    out = _impl_run_pestpp_sweep("swp_model2", pst, parameter_csv=str(good))
    assert [r["parameters"]["k"] for r in out["runs"]] == [1.0, 5.0, 20.0]
    bad = tmp_path / "bad.csv"
    bad.write_text("other\n1.0\n")
    with pytest.raises(ValueError, match="missing column"):
        _impl_run_pestpp_sweep("swp_model2", pst, parameter_csv=str(bad))


@pytest.mark.skipif(not _pestpp_available("pestpp-sen"), reason="pestpp-sen not installed")
def test_run_pestpp_sen_sobol_ranks_by_total_index(tmp_path):
    from groundwater_mcp.tools.calibration import (
        _impl_run_pestpp_sen,
        _impl_setup_calibration,
    )

    name = "sobol_model"
    _build_base_model(tmp_path, name=name, recharge=0.001)
    _register_obs(tmp_path, name)
    setup = _impl_setup_calibration(
        name,
        {
            "k": {"target": "npf:k", "scope": "all", "initial": 5.0},
            "rech": {"target": "rch:recharge", "scope": "all", "initial": 0.001},
        },
        noptmax=0,
    )
    assert "error" not in setup, setup
    result = _impl_run_pestpp_sen(
        name, setup["pst_file"], method="sobol", sobol_samples=32
    )
    assert result["method"] == "sobol" and result["completed"] is True
    ranked = result["parameters"]
    assert {p["name"] for p in ranked} == {"k", "rech"}
    assert ranked[0]["st"] >= ranked[1]["st"]
    assert [p["rank"] for p in ranked] == [1, 2]
    assert all(p["st"] > 0 for p in ranked)
    assert "phi" in result["by_output"]
    assert Path(result["summary_file"]).exists()
