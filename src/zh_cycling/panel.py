"""Dense hour x site panel shared by all models.

Everything is held as small numpy arrays (~44k hours x ~30 sites), so the whole
experiment fits comfortably in memory on a laptop.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config as C
from .graph import load_travel_time

STATIC_COLS = [
    "log_betweenness", "velonetz_rank", "road_rank", "facility", "bike_km_500m",
    "facility_share_500m", "dist_hb_km", "bridge", "tunnel", "canton",
]
WEATHER = list(C.WEATHER_COLS.values())


@dataclass
class Panel:
    hours: pd.DatetimeIndex  # local wall-clock hour starts
    sites: list[str]  # sensor node ids == physical site ids
    Y: np.ndarray  # (H, S) raw total passages, NaN where not observed
    M: np.ndarray  # (H, S) bool, usable observation
    dev: np.ndarray  # (H, S) standort id (device period) or -1
    devmean: np.ndarray  # (H, S) mean log1p of that device period (input normalisation)
    weather: np.ndarray  # (H, W) standardised weather
    calendar: pd.DataFrame  # (H, ...) calendar columns
    glob: np.ndarray  # (H, G) standardised weather + calendar features
    nodes: pd.DataFrame  # all graph nodes (sensors first), static covariates
    static: np.ndarray  # (N, K) standardised static covariates, rows = nodes
    T: np.ndarray  # (N, N) cycling time between nodes, s
    groups: dict[str, str]  # site -> hold-out group
    source: dict[str, str]  # site -> "city" | "canton"
    ambiguous: np.ndarray  # (H,) DST-ambiguous hour

    @property
    def S(self) -> int:
        return len(self.sites)

    def period(self, start: str, end: str) -> np.ndarray:
        return (self.hours >= pd.Timestamp(start)) & (self.hours < pd.Timestamp(end))


def build_panel(start: str = C.PANEL_START, end: str = C.PANEL_END) -> Panel:
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    counts = pd.read_parquet(C.PROCESSED / "counts_hourly.parquet")
    counts = counts[(counts.ts_local >= start) & (counts.ts_local < end)]
    nodes = gpd.read_parquet(C.PROCESSED / "nodes.parquet")
    sites_tbl = pd.read_parquet(C.PROCESSED / "sites.parquet")

    active = sorted(counts.loc[counts.observed, "site_id"].unique())
    sensor_nodes = nodes[(nodes.node_type == "sensor") & nodes.node_id.isin(active)]
    junctions = nodes[nodes.node_type == "junction"]
    nodes = pd.concat([sensor_nodes, junctions], ignore_index=True)
    sites = list(sensor_nodes.node_id)

    hidx = pd.Series(np.arange(len(hours)), index=hours)
    sidx = {s: i for i, s in enumerate(sites)}
    c = counts[counts.site_id.isin(sidx)]
    hi = hidx.reindex(c.ts_local).to_numpy()
    si = c.site_id.map(sidx).to_numpy()
    Y = np.full((len(hours), len(sites)), np.nan)
    M = np.zeros_like(Y, bool)
    dev = np.full(Y.shape, -1, int)
    Y[hi, si] = c.raw_total.astype(float).to_numpy()
    M[hi, si] = c.observed.to_numpy()
    dev[hi, si] = c.standort_id.to_numpy()
    Y[~M] = np.nan

    # per-device-period mean of log1p: normalises *input* sites (sensor swaps
    # can shift levels). Never used for a held-out target.
    devmean = np.zeros_like(Y)
    L = np.log1p(Y)
    for d in np.unique(dev[dev >= 0]):
        sel = (dev == d) & M
        if sel.any():
            devmean[dev == d] = L[sel].mean()

    w = pd.read_parquet(C.PROCESSED / "weather_hourly.parquet")
    utc = hours.tz_localize(C.TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")
    w = w.set_index("ts_utc").reindex(utc)
    wx = w[WEATHER].to_numpy()
    wx = np.where(np.isnan(wx), np.nanmean(wx, 0), wx)
    wx[:, WEATHER.index("precip_mm")] = np.log1p(wx[:, WEATHER.index("precip_mm")])
    weather = (wx - wx.mean(0)) / wx.std(0)

    cal = pd.read_parquet(C.PROCESSED / "calendar_hourly.parquet").set_index("ts_local").reindex(hours)
    cal = cal.reset_index(names="ts_local")
    g = [
        weather,
        np.sin(2 * np.pi * cal.hour.to_numpy() / 24)[:, None],
        np.cos(2 * np.pi * cal.hour.to_numpy() / 24)[:, None],
        np.eye(7)[cal.dow.to_numpy()][:, 1:],  # Monday = reference level
        cal[["public_holiday", "school_holiday", "school_free_day", "workday"]].to_numpy(float),
        cal[["doy_sin", "doy_cos"]].to_numpy(),
        (cal[["sun_elev"]].to_numpy() / 30.0),
        _covid_flags(hours),
    ]
    glob = np.concatenate(g, axis=1).astype(np.float32)

    st = nodes.reindex(columns=STATIC_COLS).fillna(0.0).to_numpy(float)
    st = (st - st.mean(0)) / np.where(st.std(0) > 0, st.std(0), 1)
    st = np.c_[st, (nodes.node_type == "junction").to_numpy(float)]

    node_ids, T_all = load_travel_time()
    pos = {n: i for i, n in enumerate(node_ids)}
    ix = [pos[n] for n in nodes.node_id]
    T = T_all[np.ix_(ix, ix)]

    groups = dict(zip(sites_tbl.site_id, sites_tbl.holdout_group))
    source = dict(zip(sites_tbl.site_id, sites_tbl.get("source", pd.Series("city", index=sites_tbl.index))))
    amb = np.asarray((hours.month == 10) & (hours.dayofweek == 6) & (hours.day >= 25) & (hours.hour == 2))
    return Panel(hours, sites, Y, M, dev, devmean, weather, cal, glob, nodes.reset_index(drop=True),
                 st.astype(np.float32), T, {s: groups[s] for s in sites}, {s: source[s] for s in sites}, amb)


def _covid_flags(hours: pd.DatetimeIndex) -> np.ndarray:
    """Federal home-office obligation periods (context confounder, see events ledger)."""
    periods = [("2021-01-18", "2021-05-31"), ("2021-12-20", "2022-02-03")]
    f = np.zeros(len(hours))
    for a, b in periods:
        f[(hours >= a) & (hours < b)] = 1
    return f[:, None]


def eligible_test_sites(p: Panel, start=C.VAL_END, end=C.TEST_END, min_hours=C.MIN_TEST_HOURS) -> list[str]:
    """City counters only: cantonal stations are inputs/training sites, never test targets."""
    per = p.period(start, end)
    return [s for i, s in enumerate(p.sites) if p.source[s] == "city" and p.M[per, i].sum() >= min_hours]


def holdout_folds(p: Panel, radius_groups: dict[str, str] | None = None) -> list[list[str]]:
    """One fold per hold-out group that contains at least one test-eligible site."""
    groups = radius_groups or p.groups
    elig = set(eligible_test_sites(p))
    folds: dict[str, list[str]] = {}
    for s in p.sites:
        folds.setdefault(groups[s], []).append(s)
    return [sorted(v) for _, v in sorted(folds.items()) if elig & set(v)]


def regroup(p: Panel, radius_m: float) -> dict[str, str]:
    """Larger hold-out groups for the 'withhold neighbours together' sensitivity."""
    import networkx as nx

    idx = range(p.S)
    xy = p.nodes.loc[: p.S - 1, ["x", "y"]].to_numpy()
    G = nx.Graph()
    G.add_nodes_from(idx)
    for i in idx:
        for j in idx:
            if i < j and np.hypot(*(xy[i] - xy[j])) < radius_m:
                G.add_edge(i, j)
    out = {}
    for comp in nx.connected_components(G):
        name = "+".join(sorted(p.sites[i] for i in comp))
        for i in comp:
            out[p.sites[i]] = name
    return out
