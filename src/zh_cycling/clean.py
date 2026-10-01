"""Build canonical tables: sites, counts_hourly, weather_hourly, calendar_hourly.

Conventions
-----------
* Counter timestamps (DATUM) are local Zurich wall-clock times marking the start
  of a 15-minute interval. Spring DST: the 02:00 hour is absent. Autumn DST: the
  repeated 02:00 hour appears as duplicate quarter-hour rows (checked in the
  2024 file: 2x rows for 02:00-02:45 on 27 Oct), so the aggregated hour holds
  two real hours. Those hours are flagged `dst_ambiguous` and never used as
  labels or inputs.
* We model hours in local wall-clock time (cycling follows local routines) and
  keep a `ts_utc` column for joining UTC sources.
* MeteoSwiss hourly stamps are UTC and mark the *end* of the interval.
* Zero counts are preserved. Missing quarter-hours are not zeros: an hour is
  `complete` only if all quarter-hours for every direction the device measures
  are present.
"""

from __future__ import annotations

import json

import duckdb
import geopandas as gpd
import holidays
import numpy as np
import pandas as pd

from . import config as C

# Sites whose counters cover only part of a cross-section (underpass vs.
# roadway at Langstrasse; single direction at Hofwiesenstrasse). Their
# coverage changed over time, so each device period is kept separately.
PARTIAL_SITES = {"VZS_LANN", "VZS_LANS", "VZS_LAFN", "VZS_LAFS", "VZS_HOFW"}


# --------------------------------------------------------------------------
# sites
# --------------------------------------------------------------------------
def build_sites() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return (device-period table, physical-site table)."""
    g = gpd.read_file(C.RAW / "sites.geojson").to_crs(C.CRS_CH)
    con = duckdb.connect()
    velo_ids = set(
        con.sql(
            f"select distinct FK_STANDORT from '{C.RAW / 'counts_all.parquet'}' where VELO_IN is not null"
        ).df()["FK_STANDORT"].astype(int)
    )
    # A device-period is a cycling counter if it has cycling data, regardless of
    # the metadata flag (pedestrian-only sensors are excluded this way).
    g = g[g["id1"].isin(velo_ids)].copy()
    missing = velo_ids - set(g["id1"])
    if missing:
        print(f"  ! {len(missing)} FK_STANDORT with cycling data but no location: {sorted(missing)}")

    def one_dir(v) -> bool:
        return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() in {"", "---"}

    dev = gpd.GeoDataFrame(
        {
            "standort_id": g["id1"].astype(int),
            "site_id": g["abkuerzung"],
            "device_id": g["fk_zaehler"],
            "name": g["bezeichnung"],
            "valid_from": pd.to_datetime(g["von"]),
            "valid_to": pd.to_datetime(g["bis"]),
            "status": g["status"],
            "dir_in": g["richtung_in"],
            "dir_out": g["richtung_out"],
            "single_direction": g["richtung_out"].map(one_dir),
            "coverage_type": np.where(g["abkuerzung"].isin(PARTIAL_SITES), "partial_cross_section", "full"),
            "correction_factor": g["korrekturfaktor"],
            "correction_source": "WFS view_eco_standorte.korrekturfaktor (city); reporting layer only",
        },
        geometry=g.geometry.values,
        crs=C.CRS_CH,
    ).sort_values(["site_id", "valid_from"])

    # Physical site = abbreviation; geometry = most recent device position.
    latest = dev.sort_values("valid_from").groupby("site_id").tail(1).set_index("site_id")
    spread = dev.groupby("site_id").geometry.apply(
        lambda s: float(s.distance(s.iloc[-1]).max()) if len(s) > 1 else 0.0
    )
    sites = gpd.GeoDataFrame(
        {
            "site_id": latest.index,
            "name": latest["name"].values,
            "coverage_type": latest["coverage_type"].values,
            "n_devices": dev.groupby("site_id").size().reindex(latest.index).values,
            "max_relocation_m": spread.reindex(latest.index).values,
        },
        geometry=latest.geometry.values,
        crs=C.CRS_CH,
    )
    sites["holdout_group"] = _cluster(sites, C.HOLDOUT_CLUSTER_M)
    return dev, sites.reset_index(drop=True)


def _cluster(sites: gpd.GeoDataFrame, radius: float) -> list[str]:
    """Single-linkage clusters of sites within `radius` metres -> group label."""
    import networkx as nx

    xy = np.c_[sites.geometry.x, sites.geometry.y]
    d = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    G = nx.Graph()
    G.add_nodes_from(range(len(sites)))
    G.add_edges_from(zip(*np.where((d < radius) & (d > 0))))
    label = {}
    for comp in nx.connected_components(G):
        name = "+".join(sorted(sites["site_id"].iloc[list(comp)]))
        for i in comp:
            label[i] = name
    return [label[i] for i in range(len(sites))]


# --------------------------------------------------------------------------
# counts
# --------------------------------------------------------------------------
def build_counts_hourly(dev: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    ids = ",".join(map(str, dev["standort_id"]))
    q = f"""
        select FK_STANDORT::int as standort_id,
               date_trunc('hour', strptime(DATUM, '%Y-%m-%dT%H:%M')) as ts_local,
               sum(VELO_IN)::int as raw_in, sum(VELO_OUT)::int as raw_out,
               count(VELO_IN)::int as n_q_in, count(VELO_OUT)::int as n_q_out
        from '{C.RAW / 'counts_all.parquet'}'
        where FK_STANDORT in ({ids})
        group by 1, 2
    """
    df = con.sql(q).df()
    has_out = con.sql(
        # a device measures the OUT direction if most of its rows carry it; a
        # handful of stray OUT values on one-directional devices are ignored
        f"select FK_STANDORT::int s, count(VELO_OUT) > 0.5 * count(*) h from '{C.RAW / 'counts_all.parquet'}' "
        f"where FK_STANDORT in ({ids}) group by 1"
    ).df().set_index("s")["h"]

    df = df.merge(dev[["standort_id", "site_id", "valid_from", "valid_to"]], on="standort_id", how="left")
    df["has_out"] = df["standort_id"].map(has_out).astype(bool)

    ts = pd.DatetimeIndex(df["ts_local"])
    loc = ts.tz_localize(C.TZ, ambiguous="NaT", nonexistent="NaT")
    df["dst_ambiguous"] = loc.isna() & _is_autumn_repeat(ts)
    df["dst_nonexistent"] = loc.isna() & ~df["dst_ambiguous"].to_numpy()
    df["ts_utc"] = ts.tz_localize(C.TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")

    expected = np.where(df["dst_ambiguous"], 8, 4)
    df["completeness"] = (
        np.minimum(df["n_q_in"], np.where(df["has_out"], df["n_q_out"], df["n_q_in"])) / expected
    ).clip(upper=1.0)
    df["complete"] = df["completeness"] >= 1.0
    df["raw_total"] = df["raw_in"] + np.where(df["has_out"], df["raw_out"].fillna(0), 0)
    df.loc[df["raw_in"].isna(), "raw_total"] = np.nan

    df["outside_validity"] = (df["ts_local"] < df["valid_from"].dt.floor("D")) | (
        df["valid_to"].notna() & (df["ts_local"] >= df["valid_to"].dt.floor("D") + pd.Timedelta(days=1))
    )
    df = df.sort_values(["standort_id", "ts_local"]).reset_index(drop=True)
    df["zero_run"] = _zero_runs(df, C.ZERO_RUN_HOURS)

    df["observed"] = (
        df["complete"] & ~df["dst_ambiguous"] & ~df["dst_nonexistent"] & ~df["zero_run"] & df["raw_total"].notna()
    )
    flags = []
    for col, name in [
        ("dst_ambiguous", "dst_ambiguous"),
        ("zero_run", "zero_run"),
        ("outside_validity", "outside_metadata_validity"),
    ]:
        flags.append(np.where(df[col], name, ""))
    flags.append(np.where(~df["complete"], "partial_hour", ""))
    df["quality_flags"] = ["|".join(f for f in fs if f) for fs in zip(*flags)]
    cols = [
        "site_id", "standort_id", "ts_local", "ts_utc", "raw_in", "raw_out", "raw_total", "has_out",
        "n_q_in", "n_q_out", "completeness", "complete", "dst_ambiguous", "zero_run",
        "outside_validity", "observed", "quality_flags",
    ]
    return df[cols]


def _is_autumn_repeat(ts: pd.DatetimeIndex) -> np.ndarray:
    """Local 02:00 hour on the last Sunday of October."""
    last_sun = (ts.month == 10) & (ts.dayofweek == 6) & (ts.day >= 25)
    return np.asarray(last_sun & (ts.hour == 2))


def _zero_runs(df: pd.DataFrame, min_len: int) -> np.ndarray:
    """Flag runs of >= min_len consecutive hours with zero total per device.
    Gaps break a run; long zero runs indicate a stuck/failed sensor."""
    z = (df["raw_total"] == 0).to_numpy()
    new_dev = df["standort_id"].ne(df["standort_id"].shift()).to_numpy()
    gap = (df["ts_local"].diff() != pd.Timedelta(hours=1)).to_numpy()
    brk = new_dev | gap | ~z | np.r_[True, ~z[:-1]]
    run_id = np.cumsum(brk)
    run_len = pd.Series(z.astype(int)).groupby(run_id).transform("sum").to_numpy()
    return z & (run_len >= min_len)


# --------------------------------------------------------------------------
# weather
# --------------------------------------------------------------------------
def build_weather_hourly() -> pd.DataFrame:
    frames = []
    for name in C.SOURCES:
        if name.startswith("ogd-smn_sma_h_") and (C.RAW / name).exists():
            frames.append(pd.read_csv(C.RAW / name, sep=";", encoding="latin1", low_memory=False))
    w = pd.concat(frames, ignore_index=True)
    w["ts_end_utc"] = pd.to_datetime(w["reference_timestamp"], format="%d.%m.%Y %H:%M", utc=True)
    w = w.drop_duplicates("ts_end_utc", keep="last")
    out = pd.DataFrame({"ts_utc": w["ts_end_utc"] - pd.Timedelta(hours=1)})  # interval start
    for src, dst in C.WEATHER_COLS.items():
        out[dst] = pd.to_numeric(w[src], errors="coerce").to_numpy()
    out["station"] = "SMA"
    out = out.sort_values("ts_utc").reset_index(drop=True)
    # fill short gaps (<= 3 h) only; longer gaps stay NaN and are reported
    full = pd.DataFrame({"ts_utc": pd.date_range(out.ts_utc.min(), out.ts_utc.max(), freq="h")})
    out = full.merge(out, on="ts_utc", how="left")
    num = list(C.WEATHER_COLS.values())
    out["weather_filled"] = out[num].isna().any(axis=1)
    out[num] = out[num].interpolate(limit=3, limit_area="inside")
    out["station"] = "SMA"
    return out


# --------------------------------------------------------------------------
# calendar
# --------------------------------------------------------------------------
def build_calendar(start="2009-01-01", end="2027-01-01") -> pd.DataFrame:
    ts = pd.date_range(start, end, freq="h", inclusive="left")
    cal = pd.DataFrame({"ts_local": ts})
    years = range(ts.year.min(), ts.year.max() + 1)
    ph = holidays.country_holidays("CH", subdiv="ZH", years=years)
    day = ts.normalize()
    cal["hour"] = ts.hour
    cal["dow"] = ts.dayofweek
    cal["month"] = ts.month
    cal["year"] = ts.year
    cal["public_holiday"] = np.array([d.date() in ph for d in day])

    sf = pd.read_csv(C.RAW / "schulferien.csv")
    sf["start"] = pd.to_datetime(sf["start_date"]).dt.tz_localize(None)
    sf["end"] = pd.to_datetime(sf["end_date"]).dt.tz_localize(None)
    sf["end"] = sf[["start", "end"]].max(axis=1).where(sf["end"] > sf["start"], sf["start"] + pd.Timedelta(days=1))
    school = np.zeros(len(ts), bool)
    local_free = np.zeros(len(ts), bool)
    for _, r in sf.iterrows():
        m = (ts >= r["start"]) & (ts < r["end"])
        s = str(r["summary"])
        if "ferien" in s.lower():
            school |= m
        elif "schulfrei" in s.lower():
            local_free |= m  # Sechseläuten, Knabenschiessen, bridge days
    cal["school_holiday"] = school
    cal["school_free_day"] = local_free
    cal["is_weekend"] = cal["dow"] >= 5
    cal["workday"] = ~cal["is_weekend"] & ~cal["public_holiday"]
    doy = ts.dayofyear.to_numpy()
    cal["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    cal["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    cal["peak"] = cal["workday"] & cal["hour"].isin([7, 8, 16, 17, 18])
    # daylight proxy: solar elevation at Zurich (47.37N, 8.54E), hour midpoint
    cal["sun_elev"] = _solar_elevation(ts + pd.Timedelta(minutes=30))
    return cal


def _solar_elevation(ts_local: pd.DatetimeIndex, lat=47.37, lon=8.54) -> np.ndarray:
    utc = ts_local.tz_localize(C.TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")
    doy = utc.dayofyear.to_numpy()
    hr = utc.hour.to_numpy() + utc.minute.to_numpy() / 60
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    ha = np.radians(15 * (hr - 12) + lon)
    la = np.radians(lat)
    return np.degrees(np.arcsin(np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha)))


# --------------------------------------------------------------------------
# quality summary
# --------------------------------------------------------------------------
def quality_summary(counts: pd.DataFrame, dev: pd.DataFrame) -> pd.DataFrame:
    g = counts.groupby("standort_id")
    q = pd.DataFrame(
        {
            "site_id": g["site_id"].first(),
            "first_hour": g["ts_local"].min(),
            "last_hour": g["ts_local"].max(),
            "hours_present": g.size(),
            "hours_observed": g["observed"].sum(),
            "partial_hours": g["complete"].apply(lambda s: int((~s).sum())),
            "dst_ambiguous_hours": g["dst_ambiguous"].sum(),
            "zero_run_hours": g["zero_run"].sum(),
            "outside_validity_hours": g["outside_validity"].sum(),
            "zero_hours_kept": g.apply(lambda d: int(((d.raw_total == 0) & d.observed).sum()), include_groups=False),
        }
    )
    span_h = (q["last_hour"] - q["first_hour"]).dt.total_seconds() / 3600 + 1
    q["coverage_of_span"] = (q["hours_observed"] / span_h).round(3)
    q = q.join(dev.set_index("standort_id")[["device_id", "coverage_type", "correction_factor"]])
    return q.reset_index()


# --------------------------------------------------------------------------
# cantonal counters (canton6 variant)
# --------------------------------------------------------------------------
CANTON_ID_OFFSET = 900_000  # keeps cantonal standort ids apart from city id1


def build_cantonal(city_sites: gpd.GeoDataFrame, ring_km: float):
    """Cantonal stations within `ring_km` of the area spanned by city counters
    active since 2021. Lanes are summed to a station total per local hour; an
    hour is complete only when every lane the station normally reports is
    present. Timestamps carry an explicit UTC offset, so the local wall-clock
    hour is taken from the string and UTC derived from the offset."""
    files = sorted(C.RAW.glob("cantonal_velo_*.csv"))
    if not files:
        raise FileNotFoundError("no cantonal files; run `zh-cycling download --cantonal`")
    con = duckdb.connect()
    src = "[" + ",".join(f"'{f}'" for f in files) + "]"
    st = con.sql(f"""
        select messstelle_id::int id, any_value(gemeinde_name) gem,
               any_value(messstelle_laengengrad_WGS84) lon, any_value(messstelle_breitengrad_WGS84) lat
        from read_csv({src}, union_by_name=true, types={{'zeit_von':'VARCHAR'}}) group by 1""").df()
    g = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=C.CRS_WGS).to_crs(C.CRS_CH)
    hull = city_sites.geometry.union_all().convex_hull
    g = g[g.geometry.distance(hull) <= ring_km * 1000].reset_index(drop=True)
    ids = ",".join(map(str, g.id))
    df = con.sql(f"""
        with lanes as (
            select messstelle_id::int id, strptime(substr(zeit_von, 1, 19), '%Y-%m-%dT%H:%M:%S') ts_local,
                   cast(substr(zeit_von, 20) as int) off_h, spur_richtung lane, anzahl_velos n
            from read_csv({src}, union_by_name=true, types={{'zeit_von':'VARCHAR'}})
            where messstelle_id in ({ids}))
        select id, ts_local, min(off_h) off_h, sum(n)::double raw_total,
               count(n)::int n_lanes_ok, count(distinct lane)::int n_lanes, count(*)::int n_rows
        from lanes group by 1, 2""").df()
    # The canton stamps every hour with a fixed +01 offset (CET all year; a
    # 02:00 hour exists on spring-forward day). Convert to UTC, then to Zurich
    # wall-clock time so hours line up with the city counters. The repeated
    # autumn hour then receives two UTC hours: summed and flagged, as for the city.
    expected = df.groupby("id").n_lanes.agg(lambda s: s.mode().iloc[0])
    df["ts_utc"] = (pd.to_datetime(df.ts_local) - pd.to_timedelta(df.off_h, unit="h")).dt.tz_localize("UTC")
    df["ts_local"] = df.ts_utc.dt.tz_convert(C.TZ).dt.tz_localize(None)
    df = df.groupby(["id", "ts_local"], as_index=False).agg(
        ts_utc=("ts_utc", "min"), raw_total=("raw_total", lambda s: s.sum(min_count=1)),
        n_lanes_ok=("n_lanes_ok", "sum"), n_utc=("ts_utc", "size"))
    df["expected_lanes"] = df.id.map(expected) * df.n_utc
    df["site_id"] = "KT_" + df.id.astype(str)
    df["standort_id"] = df.id + CANTON_ID_OFFSET
    df["dst_ambiguous"] = df.n_utc > 1
    df["completeness"] = (df.n_lanes_ok / df.expected_lanes).clip(upper=1.0)
    df["complete"] = df.completeness >= 1.0
    df.loc[df.n_lanes_ok == 0, "raw_total"] = np.nan
    df = df.sort_values(["standort_id", "ts_local"]).reset_index(drop=True)
    df["zero_run"] = _zero_runs(df, C.ZERO_RUN_HOURS)
    df["outside_validity"] = False
    df["observed"] = df.complete & ~df.dst_ambiguous & ~df.zero_run & df.raw_total.notna()
    df["quality_flags"] = np.where(df.dst_ambiguous, "dst_ambiguous", "")
    df.loc[df.zero_run, "quality_flags"] += "|zero_run"
    df.loc[~df.complete, "quality_flags"] += "|partial_hour"
    counts = pd.DataFrame({
        "site_id": df.site_id, "standort_id": df.standort_id, "ts_local": df.ts_local, "ts_utc": df.ts_utc,
        "raw_in": df.raw_total.astype("Int64"), "raw_out": pd.array([pd.NA] * len(df), dtype="Int64"),
        "raw_total": df.raw_total, "has_out": False, "n_q_in": df.n_lanes_ok, "n_q_out": 0,
        "completeness": df.completeness, "complete": df.complete, "dst_ambiguous": df.dst_ambiguous,
        "zero_run": df.zero_run, "outside_validity": df.outside_validity, "observed": df.observed,
        "quality_flags": df.quality_flags.str.strip("|"),
    })
    first = df.groupby("id").ts_local.min()
    dev = gpd.GeoDataFrame({
        "standort_id": g.id + CANTON_ID_OFFSET, "site_id": "KT_" + g.id.astype(str), "device_id": g.id.astype(str),
        "name": g.gem + " (Kanton " + g.id.astype(str) + ")", "valid_from": g.id.map(first).values,
        "valid_to": pd.NaT, "status": "aktuell", "dir_in": None, "dir_out": None, "single_direction": False,
        "coverage_type": "full", "correction_factor": 1.0,
        "correction_source": "canton: no correction factor published",
    }, geometry=g.geometry.values, crs=C.CRS_CH)
    sites = gpd.GeoDataFrame({
        "site_id": dev.site_id, "name": dev.name, "coverage_type": "full", "n_devices": 1,
        "max_relocation_m": 0.0, "holdout_group": dev.site_id, "source": "canton",
    }, geometry=dev.geometry.values, crs=C.CRS_CH)
    return dev, sites, counts


def run() -> None:
    C.PROCESSED.mkdir(parents=True, exist_ok=True)
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    print("Building sites ...")
    dev, sites = build_sites()
    sites["source"] = "city"
    dev.to_parquet(C.PROCESSED / "site_devices.parquet")
    sites.to_parquet(C.PROCESSED / "sites.parquet")
    print(f"  {len(dev)} cycling device-periods, {len(sites)} physical sites")

    print("Building counts_hourly ...")
    counts = build_counts_hourly(dev)
    sites["source"] = "city"
    if C.CANTON_RING_KM:
        print(f"Adding cantonal counters within {C.CANTON_RING_KM:g} km ...")
        active = set(counts.loc[(counts.ts_local >= C.PANEL_START) & counts.observed, "site_id"])
        kdev, ksites, kcounts = build_cantonal(sites[sites.site_id.isin(active)], C.CANTON_RING_KM)
        dev = pd.concat([dev, kdev], ignore_index=True)
        sites = pd.concat([sites, ksites], ignore_index=True)
        counts = pd.concat([counts, kcounts], ignore_index=True)
        dev.to_parquet(C.PROCESSED / "site_devices.parquet")
        sites.to_parquet(C.PROCESSED / "sites.parquet")
        print(f"  +{len(ksites)} cantonal stations, {kcounts.observed.mean():.1%} of their hours usable")
    counts.to_parquet(C.PROCESSED / "counts_hourly.parquet", index=False)
    print(f"  {len(counts):,} device-hours, {counts.observed.mean():.1%} usable")

    print("Building weather_hourly ...")
    w = build_weather_hourly()
    w.to_parquet(C.PROCESSED / "weather_hourly.parquet", index=False)
    print(f"  {w.ts_utc.min()} .. {w.ts_utc.max()}, {w.weather_filled.sum()} hours with gaps")

    print("Building calendar ...")
    build_calendar().to_parquet(C.PROCESSED / "calendar_hourly.parquet", index=False)

    q = quality_summary(counts, dev)
    q.to_csv(C.OUTPUTS / "data_quality.csv", index=False)
    summary = {
        "device_hours": int(len(counts)),
        "observed_share": round(float(counts.observed.mean()), 4),
        "partial_hours": int((~counts.complete).sum()),
        "dst_ambiguous_hours": int(counts.dst_ambiguous.sum()),
        "zero_run_hours": int(counts.zero_run.sum()),
        "outside_metadata_validity_hours": int(counts.outside_validity.sum()),
        "weather_gap_hours": int(w.weather_filled.sum()),
    }
    (C.OUTPUTS / "data_quality_summary.json").write_text(json.dumps(summary, indent=2))
    print("  quality:", summary)
