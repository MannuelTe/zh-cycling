"""Cycling network graph: OSM bicycle-permitted streets, sensor snapping,
network covariates, and the two model graphs.

* ``sensor`` graph   : counters only, k nearest by cycling time, w = exp(-t/tau)
* ``intersection``   : counters + candidate important junctions (chosen by
                       network betweenness, never by counts), connected by the
                       OSM network contracted onto the retained nodes.

Limitation (recorded in graph_meta.json): this is the *current* OSM network.
Historical topology is not reconstructed, so all experiments are
"static-current-network reconstruction".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString

from . import config as C

GRAPH_VERSION = "osm-current-v1"
N_JUNCTIONS = 80
SENSOR_PATH_K = 10  # routes stored per sensor for the sensor graph (k=5 plus hold-out slack)
JUNCTION_SPACING_M = 400.0
BETWEENNESS_SAMPLES = 500
# Zürich HB, approximate LV95 position of the main concourse
HB_XY = (2683190.0, 1247970.0)

_BIKE_FILTERS = [
    # public ways cyclists may use (osmnx 'bike' filter, minus footways)
    '["highway"]["area"!~"yes"]["highway"!~"abandoned|bus_guideway|construction|corridor|elevator|'
    'escalator|footway|motor|no|planned|platform|proposed|raceway|razed|steps|pedestrian|bridleway"]'
    '["bicycle"!~"no"]["service"!~"private"]["access"!~"private|no"]',
    # footways / pedestrian zones where cycling is explicitly allowed
    '["highway"~"footway|pedestrian|bridleway|path"]["bicycle"~"yes|designated|permissive"]',
]
_EXTRA_TAGS = [
    "oneway:bicycle", "cycleway", "cycleway:left", "cycleway:right", "cycleway:both",
    "bicycle", "bridge", "tunnel", "surface", "maxspeed",
]
_ROAD_RANK = {
    "trunk": 5, "trunk_link": 5, "primary": 4, "primary_link": 4, "secondary": 3,
    "secondary_link": 3, "tertiary": 2, "tertiary_link": 2, "unclassified": 1,
    "residential": 1, "living_street": 0, "service": 0, "cycleway": -1, "path": -1,
    "track": -1, "footway": -1, "pedestrian": -1, "bridleway": -1,
}


def _first(v):
    return v[0] if isinstance(v, list) else v


def _has_facility(d: dict) -> bool:
    hw = str(_first(d.get("highway", "")))
    if hw == "cycleway" or str(_first(d.get("bicycle", ""))) == "designated":
        return True
    for k in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both"):
        v = str(_first(d.get(k, "")))
        if v and v not in {"no", "none", "nan", "separate", "shared_lane"}:
            return True
    return False


def _contraflow(d: dict) -> bool:
    if str(d.get("oneway:bicycle", "")) == "no":
        return True
    return any(str(d.get(k, "")).startswith("opposite") for k in ("cycleway", "cycleway:left", "cycleway:right"))


# --------------------------------------------------------------------------
# OSM network
# --------------------------------------------------------------------------
def load_osm(sites: gpd.GeoDataFrame, buffer_m: float = 2500.0) -> nx.MultiDiGraph:
    cache = C.CACHE / f"osm_bike_{GRAPH_VERSION}_{C.VARIANT}.graphml"
    if cache.exists():
        print("  cached OSM graph")
        return ox.load_graphml(cache, edge_dtypes={"facility": int, "travel_time": float, "length": float})
    C.CACHE.mkdir(parents=True, exist_ok=True)
    poly = sites.geometry.union_all().convex_hull.buffer(buffer_m)
    poly_wgs = gpd.GeoSeries([poly], crs=C.CRS_CH).to_crs(C.CRS_WGS).iloc[0]
    ox.settings.useful_tags_way = list(dict.fromkeys(ox.settings.useful_tags_way + _EXTRA_TAGS))
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(C.CACHE / "osmnx")
    print("  downloading OSM bicycle network (Overpass) ...")
    G = ox.graph_from_polygon(poly_wgs, custom_filter=_BIKE_FILTERS, simplify=False, retain_all=False)
    # contraflow cycling: one-way streets open to bicycles in both directions
    added = 0
    for u, v, _k, d in list(G.edges(keys=True, data=True)):
        if d.get("oneway") and _contraflow(d) and not G.has_edge(v, u):
            G.add_edge(v, u, **{**d, "reversed": True, "contraflow": True})
            added += 1
    print(f"  added {added} contraflow edges")
    G = ox.simplify_graph(G, edge_attrs_differ=["highway", "bridge", "tunnel"])
    G = ox.project_graph(G, to_crs=C.CRS_CH)
    for _, _, d in G.edges(data=True):
        d["facility"] = int(_has_facility(d))
        d["travel_time"] = float(d["length"]) / (C.CYCLING_SPEED_KMH / 3.6)
    ox.save_graphml(G, cache)
    return G


def _csr(G: nx.MultiDiGraph, nodes: list, weight: str = "travel_time") -> sparse.csr_matrix:
    idx = {n: i for i, n in enumerate(nodes)}
    best: dict[tuple[int, int], float] = {}
    for u, v, d in G.edges(data=True):
        key = (idx[u], idx[v])
        t = d[weight]
        if t < best.get(key, np.inf):
            best[key] = t
    r, c = zip(*best.keys())
    return sparse.csr_matrix((list(best.values()), (r, c)), shape=(len(nodes), len(nodes)))


def _planned_network() -> gpd.GeoDataFrame:
    """One planned-network hierarchy for city and canton. The city's Velonetz
    stops at the city boundary and the canton's Alltagsnetz Velo covers only
    outside it, so the two are complementary. Ranks: 3 = city Vorzugsroute /
    canton Velobahn, 2 = Hauptnetz / Hauptverbindung, 1 = Basisnetz /
    Nebenverbindung or leisure link. Canton: existing links only (planned
    links and variants excluded)."""
    city = gpd.read_file(C.RAW / "view_velonetz.geojson").to_crs(C.CRS_CH)
    city["rank"] = city["kategorie"].map({"Vorzugsroute": 3, "Hauptnetz": 2, "Basisnetz": 1}).fillna(0)
    parts = [city[["rank", "geometry"]]]
    kt_path = C.RAW / "kt_ogd-0408_giszhpub_ogd_velo_alltag_netz_l_m.geojson"
    if kt_path.exists():
        kt = gpd.read_file(kt_path).to_crs(C.CRS_CH)
        kt = kt[kt.planungstyp.isin(["bestehend", "bei Ersatz aufzuhebend"])]
        kt["rank"] = kt.routentyp.map({"Velobahn": 3, "Hauptverbindung": 2, "Nebenverbindung": 1,
                                       "Zusätzliche Freizeitverbindung": 1}).fillna(0)
        parts.append(kt[["rank", "geometry"]])
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=C.CRS_CH)


def _velonetz_cost(G: nx.MultiDiGraph, planned: gpd.GeoDataFrame) -> dict[int, float]:
    """Conflate the planned network onto OSM edges and set ``vn_rank`` and
    ``cost_velonetz`` (seconds) on every edge. Points are sampled along each
    edge; the edge takes the highest rank r for which at least
    VELONETZ_MIN_SHARE of its points lie within VELONETZ_MATCH_M of a planned
    line of rank >= r. Returns km of (undirected) OSM edge per rank."""
    import shapely

    keys, geoms = [], []
    seen: dict[tuple, int] = {}
    for u, v, k, d in G.edges(keys=True, data=True):
        und = (min(u, v), max(u, v), k)
        if und in seen:
            continue
        seen[und] = len(keys)
        keys.append(und)
        geoms.append(d.get("geometry") or LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])]))
    geoms = np.array(geoms, dtype=object)
    lens = shapely.length(geoms)
    n_pts = np.maximum(2, np.ceil(lens / C.VELONETZ_SAMPLE_M).astype(int) + 1)
    owner = np.repeat(np.arange(len(geoms)), n_pts)
    frac = np.concatenate([np.linspace(0, 1, n) for n in n_pts])
    pts = shapely.line_interpolate_point(geoms[owner], frac, normalized=True)
    hit = gpd.sjoin(gpd.GeoDataFrame(geometry=pts, crs=C.CRS_CH), planned[["rank", "geometry"]],
                    predicate="dwithin", distance=C.VELONETZ_MATCH_M, how="left")
    pt_rank = hit.groupby(level=0)["rank"].max().fillna(0).to_numpy()
    rank = np.zeros(len(geoms), int)
    for r in (1, 2, 3):
        share = np.bincount(owner, weights=(pt_rank >= r).astype(float), minlength=len(geoms)) / n_pts
        rank[share >= C.VELONETZ_MIN_SHARE] = r
    for u, v, k, d in G.edges(keys=True, data=True):
        r = int(rank[seen[(min(u, v), max(u, v), k)]])
        d["vn_rank"] = r
        d["cost_velonetz"] = d["travel_time"] * C.VELONETZ_FACTORS[r]
    return {r: float(lens[rank == r].sum() / 1000) for r in (0, 1, 2, 3)}


# --------------------------------------------------------------------------
# main build
# --------------------------------------------------------------------------
def build(router: str = "osm") -> None:
    sites = gpd.read_parquet(C.PROCESSED / "sites.parquet")
    G = load_osm(sites)
    nodes = list(G.nodes)
    nidx = {n: i for i, n in enumerate(nodes)}
    xy = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in nodes])
    print(f"  network: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    # ---- snap sensors to their measured segment ----------------------------
    u, v, k = zip(*ox.distance.nearest_edges(G, sites.geometry.x.values, sites.geometry.y.values))
    snap = []
    for i, (a, b, kk) in enumerate(zip(u, v, k)):
        p = sites.geometry.iloc[i]
        d = G.edges[a, b, kk]
        geom = d.get("geometry") or LineString([(G.nodes[a]["x"], G.nodes[a]["y"]), (G.nodes[b]["x"], G.nodes[b]["y"])])
        da = np.hypot(G.nodes[a]["x"] - p.x, G.nodes[a]["y"] - p.y)
        db = np.hypot(G.nodes[b]["x"] - p.x, G.nodes[b]["y"] - p.y)
        snap.append(
            {
                "site_id": sites.site_id.iloc[i],
                "osm_u": a, "osm_v": b, "osm_node": a if da <= db else b,
                "snap_dist_m": float(geom.distance(p)),
                "highway": str(_first(d.get("highway"))),
                "facility": int(d["facility"]),
                "bridge": int(str(_first(d.get("bridge", ""))) not in {"", "nan", "no", "None"}),
                "tunnel": int(str(_first(d.get("tunnel", ""))) not in {"", "nan", "no", "None"}),
            }
        )
    snap = pd.DataFrame(snap)

    # ---- betweenness (sampled, undirected, by travel time) -----------------
    print("  sampled edge betweenness ...")
    Gu = nx.Graph()
    for a, b, d in G.edges(data=True):
        if not Gu.has_edge(a, b) or d["travel_time"] < Gu[a][b]["travel_time"]:
            Gu.add_edge(a, b, travel_time=d["travel_time"])
    ebc = nx.edge_betweenness_centrality(Gu, k=BETWEENNESS_SAMPLES, weight="travel_time", seed=C.SEED)
    ebc = {frozenset(e): val for e, val in ebc.items()}
    node_bc = pd.Series(0.0, index=nodes)
    for e, val in ebc.items():
        for n in e:
            node_bc[n] += val / 2
    snap["betweenness"] = [ebc.get(frozenset((a, b)), 0.0) for a, b in zip(snap.osm_u, snap.osm_v)]

    # ---- candidate important junctions (topology only, no counts) ----------
    deg = dict(Gu.degree())
    cand = node_bc[[n for n in nodes if deg[n] >= 3]].sort_values(ascending=False)
    hull = sites.geometry.union_all().convex_hull.buffer(1000)
    sensor_xy = np.c_[sites.geometry.x, sites.geometry.y]
    chosen: list = []
    for n in cand.index:
        p = xy[nidx[n]]
        if not hull.contains(gpd.points_from_xy([p[0]], [p[1]])[0]):
            continue
        if np.min(np.hypot(*(sensor_xy - p).T)) < 150:
            continue
        if chosen and np.min(np.hypot(*(xy[[nidx[c] for c in chosen]] - p).T)) < JUNCTION_SPACING_M:
            continue
        chosen.append(n)
        if len(chosen) >= N_JUNCTIONS:
            break

    # ---- node table ---------------------------------------------------------
    velonetz = _planned_network()
    edge_len = np.array([d["length"] for _, _, d in G.edges(data=True)])
    edge_mid = np.array(
        [((G.nodes[a]["x"] + G.nodes[b]["x"]) / 2, (G.nodes[a]["y"] + G.nodes[b]["y"]) / 2) for a, b in G.edges()]
    )

    rows = []
    for _, s in snap.iterrows():
        rows.append({"node_id": s.site_id, "node_type": "sensor", "site_id": s.site_id, **s.drop("site_id").to_dict()})
    for n in chosen:
        inc = [d for _, _, d in G.edges(n, data=True)]
        best = max(inc, key=lambda d: _ROAD_RANK.get(str(_first(d.get("highway"))), 0))
        rows.append(
            {
                "node_id": f"J{n}", "node_type": "junction", "site_id": None, "osm_node": n,
                "osm_u": n, "osm_v": n, "snap_dist_m": 0.0,
                "highway": str(_first(best.get("highway"))),
                "facility": int(any(d["facility"] for d in inc)),
                "bridge": 0, "tunnel": 0, "betweenness": float(node_bc[n]),
            }
        )
    nt = pd.DataFrame(rows)
    pxy = xy[[nidx[n] for n in nt.osm_node]]
    nt["x"], nt["y"] = pxy[:, 0], pxy[:, 1]
    nt.loc[nt.node_type == "sensor", "x"] = sites.geometry.x.values
    nt.loc[nt.node_type == "sensor", "y"] = sites.geometry.y.values
    geom = gpd.points_from_xy(nt.x, nt.y, crs=C.CRS_CH)
    near = gpd.sjoin_nearest(
        gpd.GeoDataFrame(nt[["node_id"]], geometry=geom), velonetz[["rank", "geometry"]],
        max_distance=25, how="left",
    )
    nt["velonetz_rank"] = near.groupby(level=0)["rank"].max().fillna(0).values
    nt["road_rank"] = nt["highway"].map(_ROAD_RANK).fillna(0)
    nt["dist_hb_km"] = np.hypot(nt.x - HB_XY[0], nt.y - HB_XY[1]) / 1000
    nt["log_betweenness"] = np.log10(nt["betweenness"] + 1e-6)
    d2 = np.hypot(*(edge_mid[None, :, :] - nt[["x", "y"]].to_numpy()[:, None, :]).transpose(2, 0, 1))
    nt["bike_km_500m"] = ((d2 < 500) * edge_len[None, :]).sum(1) / 1000
    nt["facility_share_500m"] = (
        ((d2 < 500) * edge_len[None, :] * np.array([d["facility"] for _, _, d in G.edges(data=True)])[None, :]).sum(1)
        / 1000 / nt["bike_km_500m"].clip(lower=1e-3)
    )
    src_map = dict(zip(sites.site_id, sites.get("source", pd.Series("city", index=sites.index))))
    nt["canton"] = nt.site_id.map(src_map).eq("canton").astype(float)
    nt["graph_version"] = GRAPH_VERSION

    # ---- planned-network rank on every OSM edge (for the velonetz cost) ----
    print("  conflating Velonetz onto OSM edges ...")
    vn_km = _velonetz_cost(G, velonetz)
    print("  OSM km by Velonetz rank: " + ", ".join(f"{r}: {km:,.0f}" for r, km in vn_km.items()))

    C.PROCESSED.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(nt.drop(columns=["osm_u", "osm_v"]), geometry=geom).to_parquet(C.PROCESSED / "nodes.parquet")
    src = np.array([nidx[n] for n in nt.osm_node])
    sens = (nt.node_type == "sensor").to_numpy()
    for cost, weight in (("time", "travel_time"), ("velonetz", "cost_velonetz")):
        sfx = "" if cost == "time" else f"_{cost}"
        print(f"  [{cost}] cost matrices ...")
        A = _csr(G, nodes, weight)
        D = dijkstra(A, directed=True, indices=src)  # (R, Nosm) seconds of cost
        T = D[:, src]
        T = np.where(np.isfinite(T), T, np.nan)
        Tsym = np.nanmean(np.stack([T, T.T]), axis=0)  # symmetric cost
        if router == "ors" and cost == "time":
            from . import ors

            Tors = ors.duration_matrix(nt.loc[sens, ["x", "y"]].to_numpy())
            Tsym[np.ix_(sens, sens)] = (Tors + Tors.T) / 2

        # contracted network adjacency among retained nodes
        adj = _contracted_adjacency(A, src, cutoff=900.0)
        edges = pd.DataFrame([{"src": nt.node_id[i], "dst": nt.node_id[j], "cost_s": t} for i, j, t in adj])
        edges = _attach_edge_paths(edges, nt, G, nodes, A, src, weight)

        # sensor-graph candidate edges with their actual routes: each sensor to
        # its SENSOR_PATH_K nearest sensors by this cost (covers the kNN graph
        # after any hold-out group is removed)
        si = np.where(sens)[0]
        pairs = set()
        for i in si:
            order = [j for j in si[np.argsort(Tsym[i, si])] if j != i and np.isfinite(Tsym[i, j])]
            for j in order[:SENSOR_PATH_K]:
                pairs.add((min(i, j), max(i, j)))
        sp = pd.DataFrame([{"src": nt.node_id[i], "dst": nt.node_id[j], "cost_s": float(Tsym[i, j])} for i, j in sorted(pairs)])
        sp = _attach_edge_paths(sp, nt, G, nodes, A, src, weight)

        edges.to_parquet(C.PROCESSED / f"edges_intersection{sfx}.parquet")
        sp.to_parquet(C.PROCESSED / f"edges_sensor{sfx}.parquet")
        np.savez(C.PROCESSED / f"travel_time{sfx}.npz", node_id=nt.node_id.to_numpy(), T=Tsym)

    meta = {
        "graph_version": GRAPH_VERSION,
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "osmnx_version": ox.__version__,
        "source": "OpenStreetMap via Overpass (current snapshot); ODbL",
        "router": router,
        "speed_kmh": C.CYCLING_SPEED_KMH,
        "n_osm_nodes": G.number_of_nodes(), "n_osm_edges": G.number_of_edges(),
        "n_sensors": int((nt.node_type == "sensor").sum()), "n_junctions": len(chosen),
        "n_intersection_edges": len(edges),
        "cost_models": {"time": "length / speed_kmh",
                        "velonetz": {"factors": C.VELONETZ_FACTORS, "match_m": C.VELONETZ_MATCH_M,
                                     "min_share": C.VELONETZ_MIN_SHARE, "osm_km_by_rank": vn_km}},
        "limitations": [
            "static current network: facilities that opened recently (e.g. Stadttunnel, 2025) are present for all years",
            "no elevation/gradient (swissALTI3D not yet ingested); travel time = length / constant speed",
            "junctions chosen by sampled betweenness; they are candidate, not measured, crossings",
        ],
        "max_snap_dist_m": float(snap.snap_dist_m.max()),
    }
    (C.PROCESSED / "graph_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"  {meta['n_sensors']} sensors, {meta['n_junctions']} junctions, {len(edges)} contracted edges; "
          f"max snap {meta['max_snap_dist_m']:.1f} m")


def _contracted_adjacency(A: sparse.csr_matrix, src: np.ndarray, cutoff: float):
    """Contract the OSM network onto the retained nodes via network-Voronoi
    cells: every OSM node joins its nearest retained node (by cycling time);
    two retained nodes are adjacent when an OSM edge links their cells.
    Edge cost = shortest cycling time between the two retained nodes."""
    D, _, cell = dijkstra(A, directed=False, indices=src, min_only=True, return_predecessors=True)
    pos = {s: i for i, s in enumerate(src)}
    lab = np.array([pos.get(c, -1) for c in cell])
    coo = A.tocoo()
    a, b = lab[coo.row], lab[coo.col]
    ok = (a >= 0) & (b >= 0) & (a != b)
    pairs = sorted({(int(i), int(j)) for i, j in zip(a[ok], b[ok])} | {(int(j), int(i)) for i, j in zip(a[ok], b[ok])})
    Dfull = dijkstra(A, directed=True, indices=src)[:, src]
    return [(i, j, float(Dfull[i, j])) for i, j in pairs if Dfull[i, j] <= cutoff]


def _attach_edge_paths(edges, nt, G, nodes, A, src, weight: str = "travel_time"):
    """Route geometry for each edge, following the least-``weight`` OSM path:
    length, actual travel time, facility share and the share of the route on
    each Velonetz rank."""
    idx_of = dict(zip(nt.node_id, src))
    D, P = dijkstra(A, directed=True, indices=np.unique(src), return_predecessors=True)
    row = {s: i for i, s in enumerate(np.unique(src))}
    geoms, lens, times, fac, vn = [], [], [], [], []
    for s_id, d_id in zip(edges.src, edges.dst):
        s, t = idx_of[s_id], idx_of[d_id]
        path = [t]
        while path[-1] != s and P[row[s], path[-1]] >= 0:
            path.append(P[row[s], path[-1]])
        path = path[::-1]
        pts, L, Tt, F = [], 0.0, 0.0, 0.0
        R = np.zeros(4)
        for a, b in zip(path[:-1], path[1:]):
            ed = min(G.get_edge_data(nodes[a], nodes[b]).values(), key=lambda e: e[weight])
            g = ed.get("geometry")
            pts.extend(list(g.coords) if g is not None else [(G.nodes[nodes[a]]["x"], G.nodes[nodes[a]]["y"])])
            L += ed["length"]
            Tt += ed["travel_time"]
            F += ed["length"] * ed["facility"]
            R[int(ed.get("vn_rank", 0))] += ed["length"]
        pts.append((G.nodes[nodes[path[-1]]]["x"], G.nodes[nodes[path[-1]]]["y"]))
        geoms.append(LineString(pts) if len(pts) > 1 else None)
        lens.append(L)
        times.append(Tt)
        fac.append(F / L if L else 0.0)
        vn.append(R / L if L else R)
    vn = np.array(vn).reshape(-1, 4)
    edges = edges.assign(distance_m=lens, travel_time_s=times, facility_share=fac,
                         vn0_share=vn[:, 0], vn1_share=vn[:, 1], vn2_share=vn[:, 2], vn3_share=vn[:, 3],
                         valid_from=None, valid_to=None, graph_version=GRAPH_VERSION)
    return gpd.GeoDataFrame(edges, geometry=geoms, crs=C.CRS_CH)


# --------------------------------------------------------------------------
# helpers used by models
# --------------------------------------------------------------------------
def load_travel_time() -> tuple[list[str], np.ndarray]:
    z = np.load(C.PROCESSED / f"travel_time{C.COST_SUFFIX}.npz", allow_pickle=True)
    return list(z["node_id"]), z["T"]


def knn_edges(T: np.ndarray, k: int, tau_s: float, allowed: np.ndarray | None = None):
    """Symmetric kNN edge list over the node subset `allowed` (bool mask).
    Returns (src, dst, [travel_time_min, weight]) with indices into T."""
    n = T.shape[0]
    allowed = np.ones(n, bool) if allowed is None else allowed
    M = np.where(np.isfinite(T), T, 1e9).copy()
    M[:, ~allowed] = 1e9
    np.fill_diagonal(M, 1e9)
    pairs = set()
    for i in np.where(allowed)[0]:
        for j in np.argsort(M[i])[:k]:
            if M[i, j] < 1e9:
                pairs.add((i, j))
                pairs.add((j, i))
    src, dst = map(np.array, zip(*sorted(pairs)))
    t = T[src, dst]
    return src, dst, np.c_[t / 60.0, np.exp(-t / tau_s)]
