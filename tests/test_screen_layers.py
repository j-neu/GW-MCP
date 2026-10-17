"""R3.12: assign each head observation to the layer of its well screen.

``import_obs_from_csv`` put every site of a call into the one ``layer``
argument. With ``screen_top_col`` / ``screen_bot_col`` (elevations) each site
goes to the layer its screen draws the most transmissivity from (K times the
screened thickness in that layer); a screen that spans several layers is
reported with each layer's share.
"""

from __future__ import annotations

import csv

import numpy as np
import pandas as pd
import pytest

from groundwater_mcp.tools.builder import (
    _impl_add_boundary_package,
    _impl_add_dis_package,
    _impl_add_disv_package,
    _impl_add_ic_package,
    _impl_add_npf_package,
    _impl_add_oc_package,
    _impl_create_model,
    _impl_set_simulation,
)
from groundwater_mcp.tools.parameterise import _impl_import_obs_from_csv
from groundwater_mcp.tools.runner import _impl_run_simulation
from groundwater_mcp.utils.model_store import flush_model, get_gwf, read_meta, save_sim
from groundwater_mcp.utils.spatial import grid_centroids
from groundwater_mcp.utils.workspace import resolve_workspace
from tests.test_setup_calibration import requires_mf6

# Layers: 50-40 (K 10), 40-20 (K 1), 20-0 (K 5).
BOTM = [40.0, 20.0, 0.0]
K_LAYERS = [10.0, 1.0, 5.0]
NROW, NCOL = 3, 5


def _three_layer(tmp_path, name="scr"):
    ws = str(tmp_path / name)
    _impl_create_model(name, ws, "METERS", "DAYS")
    _impl_set_simulation(name, nper=1, perlen=[1.0], nstp=[1], ims_complexity="moderate")
    _impl_add_dis_package(name, 3, NROW, NCOL, 100.0, 100.0, 50.0, BOTM)
    k = np.array([np.full((NROW, NCOL), v) for v in K_LAYERS])
    _impl_add_npf_package(name, icelltype=0, k=k, k33=0.01, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    # West boundary high in the top layer, east boundary low in the bottom
    # layer: heads differ between layers, so the assigned layer matters.
    chd = [[[0, r, 0], 40.0] for r in range(NROW)] + [
        [[2, r, NCOL - 1], 10.0] for r in range(NROW)
    ]
    _impl_add_boundary_package(name, "CHD", {"0": chd}, None)
    _impl_add_oc_package(name, None, None, None, None)
    return name


def _write(tmp_path, name, rows):
    """rows: (site, node, screen_top, screen_bottom) on the layer-0 footprint."""
    xc, yc = grid_centroids(get_gwf(name).modelgrid)
    path = tmp_path / f"{name}_screens.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "date", "value", "x", "y", "top", "bot"])
        for site, node, top, bot in rows:
            w.writerow([site, "2020-01-01", 30.0, float(xc[node]), float(yc[node]), top, bot])
    return str(path)


def _import(name, path, **kw):
    args = dict(
        model=name, csv_file=path, obs_type="HEAD", site_col="site", date_col="date",
        value_col="value", x_col="x", y_col="y", layer=0,
        screen_top_col="top", screen_bot_col="bot",
    )
    args.update(kw)
    return _impl_import_obs_from_csv(**args)


def test_each_site_goes_to_the_layer_of_its_screen(tmp_path):
    name = _three_layer(tmp_path)
    path = _write(tmp_path, name, [("SHALLOW", 6, 48, 42), ("MID", 7, 35, 25), ("DEEP", 8, 15, 5)])
    res = _import(name, path)
    cells = res["site_cellid_map"]
    assert cells["SHALLOW"] == [0, 1, 1]
    assert cells["MID"] == [1, 1, 2]
    assert cells["DEEP"] == [2, 1, 3]
    assert res["site_mapping"] == "coordinates+screen"
    assert "multi_layer_screens" not in res
    sites = {e["site"]: e for e in read_meta(name)["observations"]["sites"]}
    assert sites["MID"]["screen"] == [35.0, 25.0]
    assert sites["MID"]["layer"] == 1


def test_a_long_screen_goes_to_the_layer_with_the_most_transmissivity(tmp_path):
    # 45-30: 5 m of K 10 (T 50) in layer 0, 10 m of K 1 (T 10) in layer 1.
    name = _three_layer(tmp_path)
    res = _import(name, _write(tmp_path, name, [("LONG", 6, 45, 30)]))
    assert res["site_cellid_map"]["LONG"][0] == 0
    shares = res["multi_layer_screens"]["LONG"]
    assert shares == {"0": pytest.approx(50 / 60), "1": pytest.approx(10 / 60)}
    assert "LONG" in res["screen_warning"]


def test_inactive_layers_take_no_share(tmp_path):
    name = _three_layer(tmp_path)
    gwf = get_gwf(name)
    idomain = np.ones((3, NROW, NCOL), dtype=int)
    idomain[0, 1, 1] = 0
    gwf.dis.idomain.set_data(idomain)
    save_sim(name, gwf.simulation)
    flush_model(name)
    res = _import(name, _write(tmp_path, name, [("LONG", 6, 45, 30)]))
    assert res["site_cellid_map"]["LONG"] == [1, 1, 1]


def test_screen_outside_the_model_column_is_refused(tmp_path):
    name = _three_layer(tmp_path)
    path = _write(tmp_path, name, [("OK", 6, 35, 25), ("ABOVE", 7, 60, 55)])
    with pytest.raises(ValueError, match="ABOVE"):
        _import(name, path)


def test_screen_only_in_inactive_cells_is_refused(tmp_path):
    name = _three_layer(tmp_path)
    gwf = get_gwf(name)
    idomain = np.ones((3, NROW, NCOL), dtype=int)
    idomain[1, 1, 1] = 0
    gwf.dis.idomain.set_data(idomain)
    save_sim(name, gwf.simulation)
    flush_model(name)
    with pytest.raises(ValueError, match="MID"):
        _import(name, _write(tmp_path, name, [("MID", 6, 35, 25)]))


def test_inverted_or_missing_screen_values_are_refused(tmp_path):
    name = _three_layer(tmp_path)
    with pytest.raises(ValueError, match="BAD"):
        _import(name, _write(tmp_path, name, [("BAD", 6, 25, 35)]))
    path = tmp_path / "nan.csv"
    pd.DataFrame(
        {"site": ["N"], "date": ["2020-01-01"], "value": [30.0], "x": [150.0],
         "y": [150.0], "top": [None], "bot": [10.0]}
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="N"):
        _import(name, str(path))


def test_a_site_needs_one_screen(tmp_path):
    name = _three_layer(tmp_path)
    path = tmp_path / "two.csv"
    pd.DataFrame(
        {"site": ["W", "W"], "date": ["2020-01-01", "2020-02-01"], "value": [30.0, 31.0],
         "x": [150.0, 150.0], "y": [150.0, 150.0], "top": [35.0, 15.0], "bot": [25.0, 5.0]}
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="W"):
        _import(name, str(path))


def test_screen_columns_need_each_other_and_coordinates(tmp_path):
    name = _three_layer(tmp_path)
    path = _write(tmp_path, name, [("MID", 6, 35, 25)])
    with pytest.raises(ValueError, match="together"):
        _import(name, path, screen_bot_col=None)
    with pytest.raises(ValueError, match="x_col"):
        _import(name, path, x_col=None, y_col=None, allow_sequential=True)
    with pytest.raises(ValueError, match="not found"):
        _import(name, path, screen_top_col="missing")


def test_disv_screens_pick_the_layer(tmp_path):
    name = "scrv"
    _impl_create_model(name, str(tmp_path / name), "METERS", "DAYS")
    _impl_set_simulation(name, 1, [1.0], [1], "moderate")
    vertices = [[i, 100.0 * (i % 3), 100.0 * (i // 3)] for i in range(6)]
    cell2d = [[0, 50.0, 50.0, 4, 0, 3, 4, 1], [1, 150.0, 50.0, 4, 1, 4, 5, 2]]
    _impl_add_disv_package(name, 2, vertices, cell2d, [50.0, 50.0], [[30.0] * 2, [0.0] * 2])
    _impl_add_npf_package(name, icelltype=0, k=1.0, k33=None, save_flows=True)
    _impl_add_ic_package(name, strt=25.0)
    _impl_add_oc_package(name, None, None, None, None)
    path = tmp_path / "v.csv"
    pd.DataFrame(
        {"site": ["A", "B"], "date": ["2020-01-01"] * 2, "value": [30.0] * 2,
         "x": [50.0, 150.0], "y": [50.0, 50.0], "top": [45.0, 20.0], "bot": [35.0, 5.0]}
    ).to_csv(path, index=False)
    res = _import(name, str(path))
    assert res["site_cellid_map"] == {"A": [0, 0], "B": [1, 1]}


def test_append_keeps_earlier_layers(tmp_path):
    name = _three_layer(tmp_path)
    _import(name, _write(tmp_path, name, [("DEEP", 8, 15, 5)]))
    _import(name, _write(tmp_path, name, [("SHALLOW", 6, 48, 42)]), append=True)
    sites = {e["site"]: e["cellid"] for e in read_meta(name)["observations"]["sites"]}
    assert sites == {"DEEP": [2, 1, 3], "SHALLOW": [0, 1, 1]}


@requires_mf6
def test_simulated_head_is_the_screened_layers_head(tmp_path):
    import flopy

    name = _three_layer(tmp_path)
    _import(name, _write(tmp_path, name, [("SHALLOW", 7, 48, 42), ("DEEP", 7, 15, 5)]))
    assert _impl_run_simulation(name, silent=True)["success"]
    ws = resolve_workspace(name)
    gwf = get_gwf(name)
    sim = pd.read_csv(ws / f"{gwf.name}_head.obs.csv")
    heads = flopy.utils.HeadFile(str(ws / f"{gwf.name}.hds")).get_data()
    assert float(sim["SHALLOW"].iloc[-1]) == pytest.approx(heads[0, 1, 2])
    assert float(sim["DEEP"].iloc[-1]) == pytest.approx(heads[2, 1, 2])
    assert abs(heads[0, 1, 2] - heads[2, 1, 2]) > 0.5
