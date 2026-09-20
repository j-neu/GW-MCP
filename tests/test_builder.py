"""Tests for tools/builder.py — model creation and package configuration."""

from __future__ import annotations

import pytest

from groundwater_mcp.tools.builder import (
    _compute_model_status,
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_disv_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_add_sto_package,
    _impl_adopt_model,
    _impl_create_model,
    _impl_list_model_files,
    _impl_set_model_crs,
    _impl_set_simulation,
    _impl_summarise_model,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bare_model(tmp_path, model_name):
    """Create a bare model (no packages) and return its name."""
    ws = str(tmp_path / model_name)
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    assert "error" not in result
    return model_name


@pytest.fixture()
def model_with_dis(bare_model):
    """Extend bare_model with TDIS, IMS, and a 3-layer 10x10 DIS grid."""
    name = bare_model
    _impl_set_simulation(name, nper=2, perlen=[1.0, 9.0], nstp=[1, 3], ims_complexity="moderate")
    _impl_add_dis_package(
        name,
        nlay=3,
        nrow=10,
        ncol=10,
        delr=100.0,
        delc=100.0,
        top=50.0,
        botm=[40.0, 30.0, 20.0],
    )
    return name


@pytest.fixture()
def full_model(model_with_dis):
    """Extend model_with_dis with NPF, IC, WEL, and OC packages."""
    name = model_with_dis
    _impl_add_npf_package(name, icelltype=1, k=10.0, k33=1.0, save_flows=True)
    _impl_add_ic_package(name, strt=45.0)
    _impl_add_boundary_package(
        name,
        "WEL",
        {"0": [[[0, 5, 5], -500.0]], "1": [[[0, 5, 5], -600.0]]},
        None,
    )
    _impl_add_oc_package(name, None, None, None, None)
    return name


# ---------------------------------------------------------------------------
# create_model
# ---------------------------------------------------------------------------


def test_create_model_returns_workspace(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    assert "error" not in result
    assert result["model"] == model_name
    assert result["units"] == "METERS"
    assert result["time_units"] == "DAYS"


def test_create_model_writes_nam_file(tmp_path, model_name):
    """Builder calls defer their disk write; flush_model performs it (7f-E1.2)."""
    from groundwater_mcp.utils.model_store import flush_model

    ws = str(tmp_path / model_name)
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    ws_path = __import__("pathlib").Path(result["workspace"])
    assert result["written"] is False
    assert not (ws_path / "mfsim.nam").exists()  # deferred, not yet on disk
    assert flush_model(model_name) is True
    assert (ws_path / "mfsim.nam").exists()
    assert (ws_path / f"{model_name}.nam").exists()


def test_create_model_re_register_same_path_idempotent(tmp_path, model_name):
    """Re-registering the same name+path is idempotent, not an error (7e-B4.2)."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    result = _impl_create_model(model_name, ws, "METERS", "DAYS")
    assert result["workspace"] == ws


def test_create_model_duplicate_different_path_raises(tmp_path, model_name):
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    with pytest.raises(ValueError, match="already exists"):
        _impl_create_model(model_name, str(tmp_path / "elsewhere"), "METERS", "DAYS")


def test_create_model_same_name_different_root_ok(tmp_path):
    """The registry is scoped per workspace root (7e-B4.2): the same model
    name may live under two different roots without colliding."""
    ws_a = str(tmp_path / "project_a" / "m")
    ws_b = str(tmp_path / "project_b" / "m")
    _impl_create_model("m", ws_a, "METERS", "DAYS")
    _impl_create_model("m", ws_b, "METERS", "DAYS")
    from groundwater_mcp.utils.workspace import resolve_workspace

    assert str(resolve_workspace("m")) in (ws_a, ws_b)


def test_resolve_workspace_prefers_most_recently_registered_root(tmp_path):
    """With the same name under several roots, the newest registration wins.

    Keeps the per-root registry contract but makes resolution deterministic so
    a model just adopted in a new worktree is the one the tools read (the
    2026-09-13 DISU rerun friction).
    """
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws_a = str(tmp_path / "project_a" / "m")
    ws_b = str(tmp_path / "project_b" / "m")
    ws_c = str(tmp_path / "project_c" / "m")
    _impl_create_model("m", ws_a, "METERS", "DAYS")
    _impl_create_model("m", ws_b, "METERS", "DAYS")
    assert str(resolve_workspace("m")) == ws_b  # most recent

    _impl_create_model("m", ws_c, "METERS", "DAYS")
    assert str(resolve_workspace("m")) == ws_c


def test_create_model_name_too_long_raises(tmp_path):
    long_name = "tutorial05_catchment"  # 21 chars — exceeds MF6's 16-char MODELNAME cap
    with pytest.raises(ValueError, match="16 characters"):
        _impl_create_model(long_name, str(tmp_path / "ws"), "METERS", "DAYS")


# ---------------------------------------------------------------------------
# set_simulation
# ---------------------------------------------------------------------------


def test_set_simulation_basic(bare_model):
    result = _impl_set_simulation(
        bare_model, nper=1, perlen=[365.0], nstp=[12], ims_complexity="simple"
    )
    assert "error" not in result
    assert result["nper"] == 1
    assert result["total_time"] == pytest.approx(365.0)


def test_set_simulation_multiperiod(bare_model):
    result = _impl_set_simulation(
        bare_model, nper=3, perlen=[1.0, 10.0, 100.0], nstp=[1, 2, 5], ims_complexity="moderate"
    )
    assert result["nper"] == 3
    assert result["total_time"] == pytest.approx(111.0)


def test_set_simulation_mismatched_arrays_raises(bare_model):
    with pytest.raises(ValueError):
        _impl_set_simulation(bare_model, nper=2, perlen=[1.0], nstp=[1, 2], ims_complexity="simple")


def test_set_simulation_start_date_time_applied_and_persisted(bare_model):
    from groundwater_mcp.utils.model_store import get_sim, read_meta

    result = _impl_set_simulation(
        bare_model, 1, [10.0], [1], "simple", start_date_time="1935-01-25"
    )
    assert result["start_date_time"] == "1935-01-25"
    assert get_sim(bare_model).tdis.start_date_time.get_data() == "1935-01-25"
    assert read_meta(bare_model)["start_date_time"] == "1935-01-25"


def test_set_simulation_without_start_date_clears_stale_meta(bare_model):
    from groundwater_mcp.utils.model_store import get_sim, read_meta

    _impl_set_simulation(
        bare_model, 1, [1.0], [1], "simple", start_date_time="1935-01-25"
    )
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    assert "start_date_time" not in read_meta(bare_model)
    assert get_sim(bare_model).tdis.start_date_time.get_data() is None


def test_set_simulation_solver_options_applied(bare_model):
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    result = _impl_set_simulation(
        bare_model,
        1,
        [1.0],
        [1],
        "simple",
        newton=True,
        linear_acceleration="bicgstab",
        outer_maximum=300,
        under_relaxation="simple",
    )
    sim = get_sim(bare_model)
    ims = sim.get_package("ims")
    assert ims.linear_acceleration.get_data().upper() == "BICGSTAB"
    assert int(ims.outer_maximum.get_data()) == 300
    assert str(ims.under_relaxation.get_data()).lower() == "simple"
    assert get_gwf(bare_model).newtonoptions.get_data()
    assert result["newton"] is True


def test_set_simulation_rejects_nonpositive_outer_maximum(bare_model):
    with pytest.raises(ValueError, match="outer_maximum"):
        _impl_set_simulation(
            bare_model, 1, [1.0], [1], "simple", outer_maximum=0
        )


# ---------------------------------------------------------------------------
# add_dis_package
# ---------------------------------------------------------------------------


def test_add_dis_package_returns_grid_summary(bare_model):
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    result = _impl_add_dis_package(bare_model, 3, 10, 10, 100.0, 100.0, 50.0, [40.0, 30.0, 20.0])
    assert "error" not in result
    assert result["grid_type"] == "DIS"
    assert result["nlay"] == 3
    assert result["nrow"] == 10
    assert result["ncol"] == 10
    assert result["ncells"] == 300


def test_add_dis_package_writes_dis_file(model_with_dis):
    """The .dis file appears on disk once the staged build is flushed (7f-E1.2)."""
    from groundwater_mcp.utils.model_store import flush_model
    from groundwater_mcp.utils.workspace import resolve_workspace

    flush_model(model_with_dis)
    ws = resolve_workspace(model_with_dis)
    assert (ws / f"{model_with_dis}.dis").exists()


def test_add_dis_package_botm_mismatch_raises(bare_model):
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    with pytest.raises(ValueError, match="nlay"):
        # only 2 botm entries for nlay=3
        _impl_add_dis_package(
            bare_model, 3, 10, 10, 100.0, 100.0, 50.0, [40.0, 30.0]
        )


# ---------------------------------------------------------------------------
# add_disv_package
# ---------------------------------------------------------------------------


def test_add_disv_package(bare_model):
    _impl_set_simulation(bare_model, 1, [1.0], [1], "simple")
    # Minimal 2-cell DISV grid (2 triangles, 4 vertices)
    vertices = [[0, 0.0, 0.0], [1, 100.0, 0.0], [2, 100.0, 100.0], [3, 0.0, 100.0]]
    cell2d = [
        [0, 33.3, 33.3, 3, 0, 1, 2],
        [1, 66.6, 66.6, 3, 0, 2, 3],
    ]
    top = [50.0, 50.0]
    botm = [[40.0, 40.0], [30.0, 30.0]]
    result = _impl_add_disv_package(bare_model, 2, vertices, cell2d, top, botm)
    assert "error" not in result
    assert result["grid_type"] == "DISV"
    assert result["ncpl"] == 2
    assert result["nvert"] == 4
    assert result["ncells"] == 4  # 2 layers x 2 cells


# ---------------------------------------------------------------------------
# add_npf_package
# ---------------------------------------------------------------------------


def test_add_npf_package(model_with_dis):
    result = _impl_add_npf_package(model_with_dis, icelltype=1, k=10.0, k33=1.0, save_flows=True)
    assert "error" not in result
    assert result["package"] == "NPF"


def test_add_npf_package_no_k33(model_with_dis):
    result = _impl_add_npf_package(model_with_dis, icelltype=0, k=5.0, k33=None, save_flows=False)
    assert "error" not in result


# ---------------------------------------------------------------------------
# add_ic_package
# ---------------------------------------------------------------------------


def test_add_ic_package(model_with_dis):
    result = _impl_add_ic_package(model_with_dis, strt=45.0)
    assert "error" not in result
    assert result["package"] == "IC"


# ---------------------------------------------------------------------------
# add_boundary_package
# ---------------------------------------------------------------------------


def test_add_well_package(model_with_dis):
    spd = {"0": [[[0, 5, 5], -500.0]]}
    result = _impl_add_boundary_package(model_with_dis, "WEL", spd, None)
    assert "error" not in result
    assert result["package"] == "WEL"
    assert result["stress_periods"][0] == 1


def test_add_chd_package(model_with_dis):
    # Constant head along first column
    cells = [[[lay, row, 0], 45.0] for lay in range(3) for row in range(10)]
    spd = {"0": cells}
    result = _impl_add_boundary_package(model_with_dis, "CHD", spd, None)
    assert "error" not in result
    assert result["stress_periods"][0] == 30


def test_add_invalid_package_raises(model_with_dis):
    with pytest.raises(ValueError, match="Unsupported package"):
        _impl_add_boundary_package(model_with_dis, "XYZ", {}, None)


def test_add_boundary_package_save_flows_default_on(model_with_dis):
    """SAVE FLOWS should be on by default so compute_water_balance can see
    CHD/WEL/GHB/RIV fluxes without hand-editing the package file."""
    spd = {"0": [[[0, 0, 0], -500.0]]}
    result = _impl_add_boundary_package(model_with_dis, "WEL", spd, None)
    assert result["save_flows"] is True

    from groundwater_mcp.utils.model_store import get_gwf

    gwf = get_gwf(model_with_dis)
    wel_pkg = gwf.get_package("wel")
    assert wel_pkg.save_flows.array is True


def test_add_boundary_package_save_flows_false(model_with_dis):
    spd = {"0": [[[0, 0, 0], -500.0]]}
    result = _impl_add_boundary_package(
        model_with_dis, "WEL", spd, None, save_flows=False
    )
    assert result["save_flows"] is False

    from groundwater_mcp.utils.model_store import get_gwf

    gwf = get_gwf(model_with_dis)
    assert gwf.get_package("wel").save_flows.array is False


def test_add_boundary_package_overwrite_warns(model_with_dis):
    """Re-adding a package of the same type must return a warning (previously
    it silently overwrote the first package)."""
    spd1 = {"0": [[[0, 0, 0], 45.0]]}
    spd2 = {"0": [[[0, 0, 1], 40.0]]}
    first = _impl_add_boundary_package(model_with_dis, "CHD", spd1, None)
    assert "warning" not in first
    second = _impl_add_boundary_package(model_with_dis, "CHD", spd2, None)
    assert "warning" in second
    assert "replaced" in second["warning"].lower()


# ---------------------------------------------------------------------------
# add_oc_package
# ---------------------------------------------------------------------------


def test_add_oc_package_defaults(model_with_dis):
    result = _impl_add_oc_package(model_with_dis, None, None, None, None)
    assert "error" not in result
    assert result["head_file"].endswith(".hds")
    assert result["budget_file"].endswith(".cbb")


def test_add_oc_package_custom_filenames(model_with_dis):
    result = _impl_add_oc_package(
        model_with_dis,
        head_filerecord="my_heads.hds",
        budget_filerecord="my_budget.cbb",
        saverecord=[["HEAD", "LAST"]],
        printrecord=None,
    )
    assert result["head_file"] == "my_heads.hds"
    assert result["budget_file"] == "my_budget.cbb"


# ---------------------------------------------------------------------------
# add_sto_package
# ---------------------------------------------------------------------------


def test_add_sto_package_defaults(model_with_dis):
    """Default steady_state=[0] → SP0 steady, rest transient."""
    result = _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=None, save_flows=True
    )
    assert "error" not in result
    assert result["package"] == "STO"
    assert result["steady_state_periods"] == [0]
    assert result["transient_periods"] == [1]
    assert result["save_flows"] is True


def test_add_sto_package_writes_sto_file(model_with_dis):
    from groundwater_mcp.utils.model_store import flush_model
    from groundwater_mcp.utils.workspace import resolve_workspace

    _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=None, save_flows=True
    )
    flush_model(model_with_dis)
    ws = resolve_workspace(model_with_dis)
    sto_file = ws / f"{model_with_dis}.sto"
    assert sto_file.exists()
    text = sto_file.read_text().upper()
    assert "SAVE_FLOWS" in text
    assert "STEADY-STATE" in text  # period 1 (0-based 0)
    assert "TRANSIENT" in text     # period 2 (0-based 1)


def test_add_sto_package_sy_required_for_convertible(model_with_dis):
    """sy is mandatory when any cell is convertible (iconvert>0)."""
    with pytest.raises(ValueError, match="sy"):
        _impl_add_sto_package(
            model_with_dis, iconvert=1, ss=1e-5, sy=None, steady_state=None, save_flows=True
        )


def test_add_sto_package_sy_optional_when_confined(model_with_dis):
    result = _impl_add_sto_package(
        model_with_dis, iconvert=0, ss=1e-5, sy=None, steady_state=[0], save_flows=True
    )
    assert "error" not in result


def test_add_sto_package_requires_tdis(model_with_dis):
    """set_simulation must run first so the period count is known."""
    from groundwater_mcp.utils.model_store import get_sim, save_sim

    name = model_with_dis
    sim = get_sim(name)
    tdis = sim.get_package("tdis")
    sim.remove_package(tdis)
    save_sim(name, sim)
    with pytest.raises(ValueError, match="set_simulation"):
        _impl_add_sto_package(name, iconvert=1, ss=1e-5, sy=0.2, steady_state=None, save_flows=True)


def test_add_sto_package_steady_state_out_of_range(model_with_dis):
    with pytest.raises(ValueError, match="out of range"):
        _impl_add_sto_package(
            model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[5], save_flows=True
        )


def test_add_sto_package_overwrite_warns(model_with_dis):
    first = _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True
    )
    assert "warning" not in first
    second = _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=2e-5, sy=0.3, steady_state=[0], save_flows=True
    )
    assert "warning" in second


def test_add_sto_package_single_period_stays_steady(tmp_path, model_name):
    """nper=1 → all periods steady, no TRANSIENT block."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    result = _impl_add_sto_package(
        model_name, iconvert=0, ss=1e-5, sy=None, steady_state=None, save_flows=True
    )
    assert result["steady_state_periods"] == [0]
    assert result["transient_periods"] == []

    from groundwater_mcp.utils.model_store import flush_model
    from groundwater_mcp.utils.workspace import resolve_workspace

    flush_model(model_name)
    text = (resolve_workspace(model_name) / f"{model_name}.sto").read_text().upper()
    assert "TRANSIENT" not in text


def test_add_sto_package_all_transient(tmp_path, model_name):
    """steady_state=[] → all periods transient (PERIOD 1 TRANSIENT), no STEADY-STATE block."""
    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(
        model_name, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple"
    )
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    result = _impl_add_sto_package(
        model_name, iconvert=0, ss=1e-5, sy=None, steady_state=[], save_flows=True
    )
    assert result["steady_state_periods"] == []
    assert result["transient_periods"] == [0, 1]

    from groundwater_mcp.utils.model_store import flush_model
    from groundwater_mcp.utils.workspace import resolve_workspace

    flush_model(model_name)
    text = (resolve_workspace(model_name) / f"{model_name}.sto").read_text().upper()
    assert "TRANSIENT" in text
    assert "STEADY-STATE" not in text


# ---------------------------------------------------------------------------
# transient-without-STO guard + storage reporting
# ---------------------------------------------------------------------------


def test_transient_like_without_sto_detects_trap(model_with_dis):
    """nper=2 with no STO must flag the steady-state trap."""
    from groundwater_mcp.tools.builder import _transient_like_without_sto
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    gwf = get_gwf(model_with_dis)
    sim = get_sim(model_with_dis)
    trap, msg = _transient_like_without_sto(sim, gwf)
    assert trap is True
    assert "STO" in msg


def test_transient_like_without_sto_clean_with_sto(model_with_dis):
    from groundwater_mcp.tools.builder import _impl_add_sto_package, _transient_like_without_sto
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True
    )
    gwf = get_gwf(model_with_dis)
    sim = get_sim(model_with_dis)
    trap, msg = _transient_like_without_sto(sim, gwf)
    assert trap is False


def test_transient_like_without_sto_clean_when_steady(tmp_path, model_name):
    """nper=1, nstp=1 without STO is a legitimate steady-state model — no trap."""
    from groundwater_mcp.tools.builder import (
        _impl_add_dis_package,
        _impl_create_model,
        _impl_set_simulation,
        _transient_like_without_sto,
    )
    from groundwater_mcp.utils.model_store import get_gwf, get_sim

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 2, 2, 100.0, 100.0, 10.0, [0.0])
    gwf = get_gwf(model_name)
    sim = get_sim(model_name)
    trap, _ = _transient_like_without_sto(sim, gwf)
    assert trap is False


def test_summarise_model_reports_storage(model_with_dis):
    from groundwater_mcp.tools.builder import _impl_add_sto_package

    _impl_add_sto_package(
        model_with_dis, iconvert=1, ss=1e-5, sy=0.2, steady_state=[0], save_flows=True
    )
    result = _impl_summarise_model(model_with_dis)
    assert result["storage"] == {
        "package": "STO",
        "steady_state_periods": [0],
        "transient_periods": [1],
    }


def test_summarise_model_storage_none_without_sto(model_with_dis):
    result = _impl_summarise_model(model_with_dis)
    assert result["storage"] is None


# ---------------------------------------------------------------------------
# summarise_model
# ---------------------------------------------------------------------------


def test_summarise_model_full(full_model):
    result = _impl_summarise_model(full_model)
    assert "error" not in result
    assert result["model"] == full_model
    assert result["grid"]["type"] == "DIS"
    assert result["grid"]["nlay"] == 3
    assert result["grid"]["nrow"] == 10
    assert result["grid"]["ncol"] == 10
    assert len(result["stress_periods"]) == 2
    assert "WEL" in result["boundary_types"]
    assert "NPF" in result["packages"]
    assert "IC" in result["packages"]


def test_summarise_bare_model(bare_model):
    result = _impl_summarise_model(bare_model)
    assert "error" not in result
    assert result["grid"] == {}
    assert result["stress_periods"] == []


# ---------------------------------------------------------------------------
# list_model_files
# ---------------------------------------------------------------------------


def test_list_model_files(full_model):
    result = _impl_list_model_files(full_model)
    assert "error" not in result
    file_names = [f["name"] for f in result["files"]]
    assert "mfsim.nam" in file_names
    assert f"{full_model}.nam" in file_names


def test_list_model_files_has_size(full_model):
    result = _impl_list_model_files(full_model)
    for f in result["files"]:
        assert f["size_bytes"] >= 0


# ---------------------------------------------------------------------------
# Round-trip: create → write → reload from disk
# ---------------------------------------------------------------------------


def test_round_trip_reload_from_disk(tmp_path, model_name):
    """Verify model survives a cache invalidation (simulating server restart)."""
    from groundwater_mcp.utils.model_store import flush_model, invalidate

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, 1, [1.0], [1], "simple")
    _impl_add_dis_package(model_name, 2, 5, 5, 100.0, 100.0, 10.0, [5.0, 0.0])

    # Flush the staged build so a reload from disk has files to read (7f-E1.2)
    assert flush_model(model_name) is True

    # Evict from cache — next call must reload from disk
    invalidate(model_name)

    result = _impl_summarise_model(model_name)
    assert result["grid"]["type"] == "DIS"
    assert result["grid"]["nlay"] == 2


# ---------------------------------------------------------------------------
# adopt_model — register an existing MODFLOW 6 simulation on disk
# ---------------------------------------------------------------------------


def _write_existing_mf6_setup(dir_path, gwf_name="0205"):
    """Write a minimal runnable MF6 input set into dir_path (like a real
    adopted model: sim name file + GWF nam + tdis/ims + dis/npf/ic/oc)."""
    import flopy.mf6 as mf6

    sim = mf6.MFSimulation(sim_name="mfsim", version="mf6", sim_ws=str(dir_path))
    gwf = mf6.ModflowGwf(
        sim,
        modelname=gwf_name,
        model_nam_file=f"{gwf_name}.nam",
        xll=0.0,
        yll=0.0,
    )
    mf6.ModflowTdis(sim, pname="tdis", time_units="DAYS", nper=1, perioddata=[(1.0, 1, 1.0)])
    mf6.ModflowIms(sim, pname="ims", complexity="SIMPLE")
    sim.register_ims_package(sim.get_package("ims"), [gwf.name])
    mf6.ModflowGwfdis(gwf, nlay=1, nrow=5, ncol=5, delr=100.0, delc=100.0, top=10.0, botm=[0.0])
    mf6.ModflowGwfnpf(gwf, icelltype=0, k=5.0)
    mf6.ModflowGwfic(gwf, strt=8.0)
    mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{gwf.name}.hds",
        budget_filerecord=f"{gwf.name}.cbb",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)


def test_adopt_model_loads_existing_simulation(tmp_path, model_name):
    """adopt_model registers an on-disk MF6 input set and loads it into cache
    so summarise_model sees the real packages (not a create_model stub)."""
    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)

    result = _impl_adopt_model(model_name, str(src), "METERS", "DAYS")
    assert "error" not in result
    assert result["adopted"] is True

    summary = _impl_summarise_model(model_name)
    assert summary["grid"]["type"] == "DIS"
    assert summary["grid"]["ncol"] == 5
    assert "DIS" in summary["packages"]
    assert "NPF" in summary["packages"]


def test_adopt_model_workspace_requires_mfsim_nam(tmp_path, model_name):
    """A directory without mfsim.nam is rejected with a clear error."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="mfsim.nam"):
        _impl_adopt_model(model_name, str(empty), "METERS", "DAYS")


def test_adopt_model_name_length_guard(tmp_path):
    with pytest.raises(ValueError, match="16 characters"):
        _impl_adopt_model("a_very_long_model_name", str(tmp_path), "METERS", "DAYS")


def test_adopt_model_then_run_flow(tmp_path, model_name):
    """Adopted model is usable end-to-end: check → run → read_heads."""
    from groundwater_mcp.tools.postprocess import _impl_read_heads
    from groundwater_mcp.tools.runner import _impl_check_model, _impl_run_simulation
    from groundwater_mcp.utils.model_store import invalidate

    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)

    _impl_adopt_model(model_name, str(src), "METERS", "DAYS")
    check = _impl_check_model(model_name)
    assert check["check_passed"] is True

    run = _impl_run_simulation(model_name)
    assert run["success"] is True or "CONVERGENCE" in run.get("convergence", "")

    invalidate(model_name)
    heads = _impl_read_heads(model_name, layer=0, kstpkper=[0, 0])
    assert heads["shape"] == [5, 5]


# ---------------------------------------------------------------------------
# 7f-D4 — cache staleness and adopted-model read-only guard
# ---------------------------------------------------------------------------


def _snapshot_package_files(model_name) -> dict[str, bytes]:
    """Read every non-output file in the workspace keyed by name."""
    from groundwater_mcp.utils.workspace import resolve_workspace

    ws = resolve_workspace(model_name)
    out = {}
    for p in sorted(ws.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            out[p.name] = p.read_bytes()
    return out


def test_cache_reloads_on_external_edit(tmp_path, model_name):
    """An external edit to a package file must be picked up by reloading from
    disk (never serving a stale in-memory copy) and reported on the calling
    tool's result (7f-D4.1)."""
    import os
    import time

    from groundwater_mcp.utils.model_store import get_gwf
    from groundwater_mcp.utils.workspace import resolve_workspace

    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)
    _impl_adopt_model(model_name, str(src), "METERS", "DAYS", allow_modify=True)

    ws = resolve_workspace(model_name)
    ic_file = ws / f"{get_gwf(model_name).name}.ic"  # internal GWF name is 0205
    edited = ic_file.read_text().replace("8.0", "3.0")
    assert edited != ic_file.read_text(), "IC file does not contain 8.0 to edit"
    ic_file.write_text(edited)
    future = time.time() + 10
    os.utime(ic_file, (future, future))

    result = _impl_summarise_model(model_name)
    assert result.get("reloaded_from_disk") is True

    gwf = get_gwf(model_name)
    assert float(gwf.ic.strt.array.ravel()[0]) == pytest.approx(3.0)


def test_modelgrid_crs_survives_disk_reload(tmp_path, model_name):
    """A CRS set via set_model_crs must survive a reload from disk (7e-C5).

    Regression for modeB rerun-6: after the calibration rewrites the model was
    reloaded from disk and the exporters failed CRS_UNKNOWN because flopy does
    not store the CRS in MF6 input files — the reload must re-apply the
    persisted CRS from .gwmcp_meta.json.
    """
    from groundwater_mcp.utils.model_store import flush_model, get_gwf, invalidate

    ws = str(tmp_path / model_name)
    _impl_create_model(model_name, ws, "METERS", "DAYS")
    _impl_set_simulation(model_name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(model_name, 1, 3, 3, 100.0, 100.0, 10.0, [0.0])
    _impl_set_model_crs(model_name, "EPSG:32718", xorigin=350000.0, yorigin=8546000.0)
    flush_model(model_name)
    assert get_gwf(model_name).modelgrid.crs is not None

    invalidate(model_name)  # drop the cached sim — next access reloads from disk
    gwf = get_gwf(model_name)
    assert gwf.modelgrid.crs is not None, "CRS lost after reload from disk"
    assert gwf.modelgrid.crs.to_epsg() == 32718
    assert gwf.modelgrid.xoffset == pytest.approx(350000.0)


def test_adopt_model_readonly_refuses_builder_calls(tmp_path, model_name):
    """An adopted model is read-only by default: a save_sim-backed builder call
    raises ModelReadOnlyError and leaves the package files byte-identical
    (7f-D4.2)."""
    from groundwater_mcp.utils.model_store import ModelReadOnlyError

    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)
    _impl_adopt_model(model_name, str(src), "METERS", "DAYS")
    before = _snapshot_package_files(model_name)

    with pytest.raises(ModelReadOnlyError):
        _impl_add_npf_package(model_name, icelltype=0, k=5.0, k33=None, save_flows=True)

    after = _snapshot_package_files(model_name)
    assert after == before, "refused builder call modified files on disk"


def test_adopt_model_allow_modify_succeeds(tmp_path, model_name):
    """adopt_model(allow_modify=True) opts out of the read-only guard."""
    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)
    _impl_adopt_model(model_name, str(src), "METERS", "DAYS", allow_modify=True)

    result = _impl_add_npf_package(model_name, icelltype=0, k=5.0, k33=None, save_flows=True)
    assert "error" not in result


def test_adopt_model_readonly_nonmutating_tools_work(tmp_path, model_name):
    """check_model, run_simulation, summarise_model and read_heads still work on
    an adopted read-only model (7f-D4.2)."""
    from groundwater_mcp.tools.postprocess import _impl_read_heads
    from groundwater_mcp.tools.runner import _impl_check_model, _impl_run_simulation

    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)
    _impl_adopt_model(model_name, str(src), "METERS", "DAYS")

    summary = _impl_summarise_model(model_name)
    assert summary["grid"]["ncol"] == 5

    check = _impl_check_model(model_name)
    assert check["check_passed"] is True

    run = _impl_run_simulation(model_name)
    assert run["success"] is True or "CONVERGENCE" in run.get("convergence", "")

    heads = _impl_read_heads(model_name, layer=0, kstpkper=[0, 0])
    assert heads["shape"] == [5, 5]


# ---------------------------------------------------------------------------
# _compute_model_status / model_status (7e-C8)
# ---------------------------------------------------------------------------


def test_model_status_bare_model_missing_everything(bare_model):
    status = _compute_model_status(bare_model)
    assert status["runnable"] is False
    assert status["missing_required"] == ["simulation", "grid", "npf", "ic", "oc"]
    assert status["missing_recommended"] == ["boundary"]
    assert len(status["next_steps"]) == 6  # 5 required + 1 recommended
    assert status["warnings"] == []


def test_model_status_unknown_model_raises():
    with pytest.raises(KeyError):
        _compute_model_status("no_such_model_xyz")


def test_model_status_next_steps_in_build_order(bare_model):
    """simulation, then grid, then npf, then ic, then oc — matching the order
    a build actually has to happen in."""
    status = _compute_model_status(bare_model)
    steps = status["next_steps"]
    assert steps[0].startswith("set_simulation")
    assert steps[1].startswith("add_dis_package")
    assert steps[2].startswith("add_npf_package")
    assert steps[3].startswith("add_ic_package")
    assert steps[4].startswith("add_oc_package")
    assert steps[5].startswith("add_boundary_package")


def test_model_status_partial_build_narrows_missing(bare_model):
    name = bare_model
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])

    status = _compute_model_status(name)
    assert status["missing_required"] == ["npf", "ic", "oc"]
    assert "simulation" not in status["missing_required"]
    assert "grid" not in status["missing_required"]


def test_model_status_steady_state_does_not_require_sto(bare_model):
    """nper=1, nstp=1 — steady state; STO is genuinely optional, not missing."""
    name = bare_model
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=5.0)
    _impl_add_oc_package(name, None, None, None, None)

    status = _compute_model_status(name)
    assert status["runnable"] is True
    assert "sto" not in status["missing_required"]
    assert status["missing_required"] == []


def test_model_status_transient_requires_sto(bare_model):
    """Multiple time steps configured — STO becomes required, and the same
    trap check_model/run_simulation use fires as a warning."""
    name = bare_model
    _impl_set_simulation(
        name, nper=2, perlen=[100.0, 100.0], nstp=[2, 2], ims_complexity="simple"
    )
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=5.0)
    _impl_add_oc_package(name, None, None, None, None)

    status = _compute_model_status(name)
    assert status["runnable"] is False
    assert "sto" in status["missing_required"]
    assert any("add_sto_package" in step for step in status["next_steps"])
    assert status["warnings"]


def test_model_status_fully_built_is_runnable_no_missing(bare_model):
    name = bare_model
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="simple")
    _impl_add_dis_package(name, 1, 5, 5, 100.0, 100.0, 10.0, [0.0])
    _impl_add_npf_package(name, icelltype=0, k=10.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=5.5)
    chd = [[[0, row, 0], 8.0] for row in range(5)] + [[[0, row, 4], 3.0] for row in range(5)]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)

    status = _compute_model_status(name)
    assert status["runnable"] is True
    assert status["missing_required"] == []
    assert status["missing_recommended"] == []
    assert status["next_steps"] == []


def test_model_status_adopted_model_runnable(tmp_path, model_name):
    """adopt_model brings in a complete model — model_status should read it
    as runnable without any builder calls."""
    src = tmp_path / "existing"
    src.mkdir()
    _write_existing_mf6_setup(src)
    _impl_adopt_model(model_name, str(src), "METERS", "DAYS")

    status = _compute_model_status(model_name)
    assert status["runnable"] is True
    assert status["missing_required"] == []
