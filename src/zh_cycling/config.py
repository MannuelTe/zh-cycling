"""Paths, source URLs and frozen experiment settings.

Everything that defines the backtest (eligible years, splits, quality rules)
lives here so it is fixed before any model is fitted.
"""

from __future__ import annotations

import os
from pathlib import Path

# Data variant: "city" (default) or "canton6" = city counters plus cantonal
# counters within CANTON_RING_KM of the city counter area. Set via
# `zh-cycling --variant ...` (exported as ZHC_VARIANT before modules load).
VARIANT = os.environ.get("ZHC_VARIANT", "city")
CANTON_RING_KM = {"city": None, "canton6": 6.0}[VARIANT]

# Edge cost model: "time" (length / constant speed) or "velonetz" (travel time
# scaled by the planned-network rank of each OSM edge). Set via
# `zh-cycling --cost ...` (exported as ZHC_COST). Both are built by `graph`;
# the models read the matrices and edge files carrying COST_SUFFIX.
COST = os.environ.get("ZHC_COST", "time")
COST_SUFFIX = "" if COST == "time" else f"_{COST}"

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
PROCESSED = DATA / ("processed" if VARIANT == "city" else f"processed_{VARIANT}")
EVENTS_DIR = DATA / "events"
OUTPUTS = ROOT / ("outputs" if VARIANT == "city" else f"outputs_{VARIANT}")

TZ = "Europe/Zurich"
CRS_CH = "EPSG:2056"
CRS_WGS = "EPSG:4326"

# --------------------------------------------------------------------------
# Sources (checked 2026-09-30). Every download is recorded in RAW/manifest.json.
# --------------------------------------------------------------------------
_WFS_SITES = "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/Standorte_der_automatischen_Fuss__und_Velozaehlungen"
_WFS_VELONETZ = "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/Velonetzplanung"
_WFS_GETFEATURE = "?SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0&OUTPUTFORMAT=GeoJSON&SRSNAME=EPSG:2056&TYPENAME="
_METEO = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn"

SOURCES: dict[str, dict] = {
    "counts_all.parquet": {
        "url": "https://data.stadt-zuerich.ch/dataset/ted_taz_verkehrszaehlungen_werte_fussgaenger_velo/download/verkehrszaehlungen_werte_fussgaenger_velo_alle_jahre.parquet",
        "dataset": "https://data.stadt-zuerich.ch/dataset/ted_taz_verkehrszaehlungen_werte_fussgaenger_velo",
        "licence": "CC0",
    },
    "sites.geojson": {
        "url": _WFS_SITES + _WFS_GETFEATURE + "view_eco_standorte",
        "dataset": "https://data.stadt-zuerich.ch/dataset/geo_standorte_der_automatischen_fuss__und_velozaehlungen",
        "licence": "CC0",
    },
    "view_velonetz.geojson": {
        "url": _WFS_VELONETZ + _WFS_GETFEATURE + "view_velonetz",
        "dataset": "https://data.stadt-zuerich.ch/dataset/geo_velonetzplanung",
        "licence": "CC0",
    },
    "view_gs_umsetzungsstrecken.geojson": {
        "url": _WFS_VELONETZ + _WFS_GETFEATURE + "view_gs_umsetzungsstrecken",
        "dataset": "https://data.stadt-zuerich.ch/dataset/geo_velonetzplanung",
        "licence": "CC0",
    },
    # City traffic-development index (claim 2); "Daten herunterladen" on
    # stadt-zuerich.ch/de/politik-und-verwaltung/statistik-und-daten/daten/mobilitaet.html
    "VER100T1001_Verkehrsentwicklung.xlsx": {
        "url": "https://www.stadt-zuerich.ch/content/dam/web/de/politik-verwaltung/statistik-und-daten/daten/mobilitaet/VER100T1001_Verkehrsentwicklung.xlsx",
        "dataset": "https://www.stadt-zuerich.ch/de/politik-und-verwaltung/statistik-und-daten/daten/mobilitaet.html",
        "licence": "Statistik Stadt Zürich (open data, attribution)",
    },
    "schulferien.csv": {
        "url": "https://data.stadt-zuerich.ch/dataset/ssd_schulferien/download/schulferien.csv",
        "dataset": "https://data.stadt-zuerich.ch/dataset/ssd_schulferien",
        "licence": "CC0",
    },
    # MeteoSwiss SwissMetNet, Zürich/Fluntern (SMA). Hourly timestamps are UTC
    # and mark the END of the interval (opendatadocs.meteoswiss.ch/general/download).
    "ogd-smn_sma_h_historical_2020-2029.csv": {
        "url": f"{_METEO}/sma/ogd-smn_sma_h_historical_2020-2029.csv",
        "dataset": "https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations",
        "licence": "MeteoSwiss OGD (attribution)",
    },
    "ogd-smn_sma_h_historical_2010-2019.csv": {
        "url": f"{_METEO}/sma/ogd-smn_sma_h_historical_2010-2019.csv",
        "dataset": "https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations",
        "licence": "MeteoSwiss OGD (attribution)",
    },
    "ogd-smn_sma_h_recent.csv": {
        "url": f"{_METEO}/sma/ogd-smn_sma_h_recent.csv",
        "dataset": "https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations",
        "licence": "MeteoSwiss OGD (attribution)",
    },
}

# Canton Zurich cycling network/infrastructure (OGD WFS). Coverage stops at
# the city boundary; the city's Velonetz covers the inside. Combined in graph.py.
_WFS_ZH = ("https://maps.zh.ch/wfs/OGDZHWFS?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
           "&OUTPUTFORMAT=geojson&SRSNAME=EPSG:2056&TYPENAMES=ms:")
for _layer in ("ogd-0408_giszhpub_ogd_velo_alltag_netz_l_m", "ogd-0075_afv_gv_radwege_l", "ogd-0075_afv_gv_radstreifen_l"):
    SOURCES[f"kt_{_layer}.geojson"] = {
        "url": _WFS_ZH + _layer,
        "dataset": "https://opendata.swiss/de/dataset/veloinfrastruktur-radwege-und-radstreifen",
        "licence": "OGD Kanton Zürich",
    }

# Cantonal counters: audited (zh-cycling audit-cantonal); merged only in the
# canton6 variant, as input/training sites flagged with a sensor-type column.
# Catalogue: https://datenkatalog.statistik.zh.ch/datasets/3062%40tiefbauamt-kanton-zuerich
CANTONAL_DISTRIBUTIONS = {
    2021: "https://www.web.statistik.zh.ch/ogd/daten/ressourcen/KTZH_00003062_00006775.csv",
    2022: "https://www.web.statistik.zh.ch/ogd/daten/ressourcen/KTZH_00003062_00006776.csv",
    2023: "https://www.web.statistik.zh.ch/ogd/daten/ressourcen/KTZH_00003062_00006777.csv",
    2024: "https://www.web.statistik.zh.ch/ogd/daten/ressourcen/KTZH_00003062_00006778.csv",
    2025: "https://www.web.statistik.zh.ch/ogd/daten/ressourcen/KTZH_00003062_00006779.csv",
}

# --------------------------------------------------------------------------
# Frozen experiment definition
# --------------------------------------------------------------------------
PANEL_START = "2021-01-01"
PANEL_END = "2026-01-01"  # exclusive
TRAIN_END = "2024-01-01"  # train: 2021-2023
VAL_END = "2025-01-01"  # validation: 2024
TEST_END = "2026-01-01"  # test: 2025

# a site is test-eligible if it has at least this many valid hours in the test year
MIN_TEST_HOURS = 2000
# sites closer than this (m) form one hold-out group (same cross-section,
# e.g. Langstrasse roadway + underpass, Hardbrücke north + south side)
HOLDOUT_CLUSTER_M = 150.0
# runs of consecutive zero hours at least this long are flagged as suspect
ZERO_RUN_HOURS = 48

WEATHER_COLS = {
    "tre200h0": "temp_c",
    "rre150h0": "precip_mm",
    "fkl010h0": "wind_ms",
    "sre000h0": "sunshine_min",
    "ure200h0": "rel_humidity",
}

CYCLING_SPEED_KMH = 16.0
# Velonetz generalised cost (frozen before any velonetz-cost backtest):
# cost = travel_time * factor[rank]; rank 3 = Vorzugsroute / Velobahn,
# 2 = Hauptnetz / Hauptverbindung, 1 = Basisnetz / Nebenverbindung, 0 = off-network.
# An OSM edge takes the highest rank r for which >= VELONETZ_MIN_SHARE of
# points sampled every VELONETZ_SAMPLE_M lie within VELONETZ_MATCH_M of a rank->=r line.
VELONETZ_FACTORS = {3: 0.8, 2: 0.9, 1: 1.0, 0: 1.2}
VELONETZ_MATCH_M = 15.0
VELONETZ_MIN_SHARE = 0.6
VELONETZ_SAMPLE_M = 10.0
SEED = 20260930
