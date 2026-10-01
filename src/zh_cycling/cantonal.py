"""Audit of the cantonal cycling counters (not merged into training).

Checks identifiers, directions/lanes, timestamp format, coverage and whether
stations fall inside the city (possible overlap with city counters). Merging
is a later, explicit decision: technology and site types differ from the city.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from . import config as C


def audit() -> None:
    files = sorted(C.RAW.glob("cantonal_velo_*.csv"))
    if not files:
        print("  no cantonal files; run `zh-cycling download --cantonal` first")
        return
    df = pd.concat([pd.read_csv(f, low_memory=False) for f in files], ignore_index=True)
    df["ts"] = pd.to_datetime(df.zeit_von, utc=True, format="ISO8601")
    st = df.groupby("messstelle_id").agg(
        gemeinde=("gemeinde_name", "first"), lon=("messstelle_laengengrad_WGS84", "first"),
        lat=("messstelle_breitengrad_WGS84", "first"), first=("ts", "min"), last=("ts", "max"),
        rows=("ts", "size"), lanes=("spur_richtung", "nunique"), lane_names=("spur_richtung", lambda s: "|".join(sorted(map(str, s.unique())))),
        missing_counts=("anzahl_velos", lambda s: int(s.isna().sum())), zero_share=("anzahl_velos", lambda s: float((s == 0).mean())),
    ).reset_index()
    g = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=C.CRS_WGS).to_crs(C.CRS_CH)
    city = gpd.read_parquet(C.PROCESSED / "sites.parquet")
    near = gpd.sjoin_nearest(g, city[["site_id", "geometry"]], distance_col="dist_to_city_counter_m")
    st = near.drop(columns=["geometry", "index_right"]).drop_duplicates("messstelle_id")
    st["in_city_of_zurich"] = st.gemeinde.str.contains("Zürich", na=False)
    out = C.OUTPUTS / "cantonal_audit.csv"
    st.to_csv(out, index=False)
    dup = df.duplicated(["messstelle_id", "spur_richtung", "zeit_von"]).sum()
    print(f"  {len(st)} cantonal stations, {len(df):,} rows, {dup} duplicate station-lane-hours; "
          f"{int(st.in_city_of_zurich.sum())} inside Zurich city; "
          f"{int((st.dist_to_city_counter_m < 200).sum())} within 200 m of a city counter -> {out}")
