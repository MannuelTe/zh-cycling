"""Build the interactive results dashboard (docs/dashboard/index.html).

Collects the outputs of the claim check, the backtests (city and canton6
variants, both edge-cost models) and the network graphs into compact JSON,
injects them into dashboard/template.html and writes a self-contained page
that GitHub Pages serves from docs/dashboard/.

Expected inputs (produced by scripts/reproduce.sh):
  outputs/backtest/{sensor,intersection,blend}/          city variant
  outputs_canton6/backtest/{blend,blend_velonetz}/       canton6 variant
  outputs/claims/c2_doubling/                            claim 2
  outputs/history/                                       stable-panel index
  data/processed{,_canton6}/                             graph tables
  data/cache/osm_bike_<version>_canton6.graphml          OSM network
"""

from __future__ import annotations

import base64
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkb

from . import config as C

OUT = C.ROOT / "outputs"
OUT6 = C.ROOT / "outputs_canton6"
RUNS = {
    "city_s": OUT / "backtest" / "sensor",
    "city_i": OUT / "backtest" / "intersection",
    "city_b": OUT / "backtest" / "blend",
    "c6_b": OUT6 / "backtest" / "blend",
    "c6_vn": OUT6 / "backtest" / "blend_velonetz",
}
PROC = {"city": C.DATA / "processed", "c6": C.DATA / "processed_canton6"}
TEMPLATE = C.ROOT / "dashboard" / "template.html"
TARGET = C.ROOT / "docs" / "dashboard" / "index.html"
# integer grid for compact geometry: metres east/north of this origin, Q m per unit
X0, Y0, Q = 2665000, 1235000, 2.0
N_PAIRED_BOOT = 2000


def _rec(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.round(4).to_json(orient="records"))


def _b64(coords: np.ndarray) -> str:
    q = np.round((np.asarray(coords) - [X0, Y0]) / Q).astype("<i2")
    return base64.b64encode(q.ravel().tobytes()).decode()


def paired_week_bootstrap(a: pd.DataFrame, b: pd.DataFrame, model: str, n: int = N_PAIRED_BOOT, seed: int = 0) -> dict:
    """Paired week-block bootstrap of the pooled hourly MAE change (b minus a)
    on identical scored site-hours; also counts sites where b is better."""
    cols = ["site", "ts_local", "y", "pred"]
    x = a[(a.model == model) & a.observed & a.y.notna()][cols]
    y = b[(b.model == model) & b.observed & b.y.notna()][cols[:2] + ["pred"]]
    j = x.merge(y, on=["site", "ts_local"], suffixes=("_a", "_b"))
    j["d"] = (j.pred_b - j.y).abs() - (j.pred_a - j.y).abs()
    j["w"] = j.ts_local.dt.isocalendar().week.astype(int)
    g = j.groupby("w").d.agg(["sum", "size"])
    S, N = g["sum"].to_numpy(), g["size"].to_numpy()
    rng = np.random.default_rng(seed)
    bs = [S[i].sum() / N[i].sum() for i in (rng.integers(0, len(S), len(S)) for _ in range(n))]
    per_site = j.groupby("site").d.mean()
    return {"n": int(len(j)), "diff": float(j.d.mean()), "lo": float(np.percentile(bs, 2.5)),
            "hi": float(np.percentile(bs, 97.5)), "wins": int((per_site < 0).sum())}


def _breakdown(path) -> list[dict]:
    df = pd.read_csv(path, header=[0, 1], index_col=0)
    out = []
    for idx, row in df.iterrows():
        if row.isna().all():
            continue
        out.append({"group": str(idx), **{f"{m}_{mod}": round(float(row[(m, mod)]), 3) for (m, mod) in df.columns}})
    return out


def backtest_data() -> dict:
    D: dict = {k: {} for k in ("pooled", "macro", "daily", "cov", "persite", "boot", "val")}
    for run, path in RUNS.items():
        D["pooled"][run] = _rec(pd.read_csv(path / "metrics_pooled.csv"))
        D["macro"][run] = _rec(pd.read_csv(path / "metrics_macro.csv"))
        D["daily"][run] = _rec(pd.read_csv(path / "metrics_daily_totals.csv"))
        D["cov"][run] = _rec(pd.read_csv(path / "interval_coverage.csv"))
        D["persite"][run] = _rec(pd.read_csv(path / "metrics_per_site.csv"))
        D["boot"][run] = _rec(pd.read_csv(path / "bootstrap_vs_best_baseline.csv"))
        log = [json.loads(line) for line in open(path / "selection_log.jsonl")]
        D["val"][run] = {m: round(float(np.mean([r[m]["val_mae"] for r in log])), 2)
                         for m in ("idw", "glm", "gbt", "gnn", "ens") if m in log[0]}
    D["breakdown"] = {run: {b: _breakdown(RUNS[run] / f"metrics_by_{b}.csv") for b in ("season", "daytype", "peak", "stadttunnel")}
                      for run in ("city_b", "c6_b")}

    sites = pd.read_parquet(PROC["c6"] / "sites.parquet")
    D["sites"] = []
    for _, r in sites.iterrows():
        g = wkb.loads(r.geometry)
        D["sites"].append({"id": r.site_id, "name": r["name"], "src": r.source, "x": round(g.x), "y": round(g.y), "group": r.holdout_group})

    preds = {run: pd.read_parquet(RUNS[run] / "predictions.parquet") for run in ("city_b", "c6_b", "c6_vn")}
    series: dict = {}
    for run in ("city_b", "c6_b"):
        p = preds[run][preds[run].model == "ens"].copy()
        p["d"] = p.ts_local.dt.strftime("%Y-%m-%d")
        g = p.groupby(["site", "d"]).agg(y=("y", "sum"), pred=("pred", "sum"), n=("y", "size")).reset_index()
        g = g[g.n == 24]
        for s, gg in g.groupby("site"):
            e = series.setdefault(s, {})
            e["d"], e["y"] = list(gg.d), [int(v) for v in gg.y.round()]
            e[run] = dict(zip(gg.d, gg.pred.round().astype(int)))
    for e in series.values():
        for run in ("city_b", "c6_b"):
            e[run] = [int(e[run].get(d, -1)) for d in e["d"]]
    D["series"] = series
    D["vboot"] = {m: paired_week_bootstrap(preds["city_b"], preds["c6_b"], m) for m in ("idw", "gbt", "ens")}
    D["vnboot"] = {m: paired_week_bootstrap(preds["c6_b"], preds["c6_vn"], m) for m in ("idw", "gbt", "ens")}
    D["history"] = _rec(pd.read_csv(OUT / "history" / "stable_panel_annual_index.csv"))
    D["shares"] = _rec(pd.read_csv(OUT / "history" / "stable_panel_shares.csv"))
    return D


def network_data() -> dict:
    import osmnx as ox
    from shapely.geometry import LineString

    from .graph import GRAPH_VERSION

    G = ox.load_graphml(C.CACHE / f"osm_bike_{GRAPH_VERSION}_canton6.graphml",
                        edge_dtypes={"facility": int, "travel_time": float, "length": float})
    seen, parts, km = set(), {0: [], 1: []}, {0: 0.0, 1: 0.0}
    for u, v, _k, d in G.edges(keys=True, data=True):
        key = (min(u, v), max(u, v))
        if key in seen:
            continue
        seen.add(key)
        g = d.get("geometry") or LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])
        c = np.round((np.asarray(g.simplify(4).coords) - [X0, Y0]) / Q).astype(int)
        f = int(d.get("facility", 0))
        km[f] += d["length"]
        parts[f].append(c)
    out = {"origin": [X0, Y0, Q], "km": {k: round(v / 1000) for k, v in km.items()}}
    for f, L in parts.items():
        arr: list[int] = []
        for c in L:
            arr.append(len(c))
            arr.extend(c.ravel().tolist())
        out[f"net{f}"] = base64.b64encode(np.array(arr, "<i2").tobytes()).decode()
    return out


def graph_data() -> tuple[dict, dict]:
    graph, routes = {}, {}
    for tag, proc in PROC.items():
        n = gpd.read_parquet(proc / "nodes.parquet")
        z = np.load(proc / "travel_time.npz", allow_pickle=True)
        zv = np.load(proc / "travel_time_velonetz.npz", allow_pickle=True)
        ids = list(z["node_id"])
        si = [i for i, x in enumerate(ids) if not str(x).startswith("J")]
        s = pd.read_parquet(proc / "sites.parquet")
        grp = dict(zip(s.site_id, s.holdout_group))
        e = gpd.read_parquet(proc / "edges_intersection.parquet")
        edges, seen = [], set()
        for r in e.itertuples():
            k = tuple(sorted([r.src, r.dst]))
            if k in seen:
                continue
            seen.add(k)
            edges.append({"a": r.src, "b": r.dst, "tt": round(r.travel_time_s / 60, 1),
                          "c": np.asarray(r.geometry.simplify(25).coords).round().astype(int).ravel().tolist()})
        tmin = lambda M: [[None if not np.isfinite(x) else round(float(x) / 60, 1) for x in row] for row in M[np.ix_(si, si)]]
        sens = [ids[i] for i in si]
        graph[tag] = {
            "nodes": [{"id": r.node_id, "t": r.node_type, "x": round(r.x), "y": round(r.y), "bw": round(float(r.betweenness), 5),
                       "vn": float(r.velonetz_rank) if pd.notna(r.velonetz_rank) else None,
                       "fac": round(float(r.facility_share_500m), 2), "can": int(r.canton)} for r in n.itertuples()],
            "edges": edges, "sens": sens, "T": tmin(z["T"]), "grp": {k: grp.get(k, k) for k in sens},
        }
        routes[tag] = {"Tv": tmin(zv["T"]), "sens": sens}
        for cost, sfx in (("time", ""), ("velonetz", "_velonetz")):
            for kind in ("sensor", "intersection"):
                rows, seen = [], set()
                for r in gpd.read_parquet(proc / f"edges_{kind}{sfx}.parquet").itertuples():
                    k = tuple(sorted([r.src, r.dst]))
                    if k in seen or r.geometry is None:
                        continue
                    seen.add(k)
                    rows.append({"a": k[0], "b": k[1], "tt": round(r.travel_time_s / 60, 2), "c": round(r.cost_s / 60, 2),
                                 "km": round(r.distance_m / 1000, 2), "fs": round(r.facility_share, 2),
                                 "vn": [round(getattr(r, f"vn{i}_share"), 2) for i in range(4)],
                                 "g": _b64(np.asarray(r.geometry.simplify(6).coords))})
                routes[tag][f"{kind}_{cost}"] = rows
    return graph, routes


def claims_data() -> dict:
    o = OUT / "claims" / "c2_doubling"
    R = json.loads((o / "result.json").read_text())
    ser = pd.read_csv(o / "index_series.csv", index_col="year")
    col = lambda c: {int(y): (None if pd.isna(v) else float(v) / 100) for y, v in ser[c].items()}
    aq = pd.read_csv(o / "andreasstrasse_quarterly.csv")
    aq = aq[aq.quarter.str[:4].astype(int).between(2011, 2025)]
    return {
        "official": {int(y): float(v) for y, v in ser.official.dropna().items()},
        "fp": col("fixed_panel_adjusted"), "median": col("median_corrected_all"), "mean": col("mean_corrected_all"),
        "chain": col("chain_linked"), "nsites": {int(y): int(v) for y, v in ser.n_counters.items()},
        "boot": {k: [round(float(x), 4) for x in np.load(o / f"bootstrap_{k}.npy") if np.isfinite(x)] for k in ("S1", "S2", "S3", "S4")},
        "scen": R["scenarios"], "confidence": R["confidence"], "crange": R["confidence_range_across_scenarios"],
        "loo_fp": R["fixed_panel_leave_one_out"],
        "loo_city": pd.read_csv(o / "city_median_loo.csv", index_col=0).iloc[:, 0].to_dict(),
        "per_site": pd.read_csv(o / "fixed_panel_per_site.csv", index_col=0).iloc[:, 0].round(3).to_dict(),
        "anom": json.loads(pd.read_csv(o / "anomaly_impacts.csv").to_json(orient="records")),
        "comp": R["composition"], "city_median": R["city_style_median_ratio"],
        "andr_q": [{"q": r.quarter, "andr": round(r.site), "med": round(r.median_counter)} for r in aq.itertuples()],
    }


def build() -> None:
    blobs = {"/*DATA*/": backtest_data(), "/*NET*/": network_data()}
    blobs["/*GRAPH*/"], blobs["/*ROUTES*/"] = graph_data()
    blobs["/*CLAIMS*/"] = claims_data()
    html = TEMPLATE.read_text()
    for key, val in blobs.items():
        assert key in html, f"placeholder {key} missing from template"
        html = html.replace(key, json.dumps(val, separators=(",", ":"), ensure_ascii=False))
    page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>html{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
            "</head><body>\n" + html + "\n</body></html>\n")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(page)
    print(f"  dashboard: {TARGET} ({TARGET.stat().st_size / 1e6:.1f} MB)")
