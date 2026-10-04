# Data sources and licences

No third-party data are committed to this repository. `zh-cycling download`
fetches them and records URL, SHA-256, size and retrieval time in
`data/raw/manifest.json`. Derived results in `outputs/` and the figures in
`paper/` contain aggregates of these data.

| Data | Publisher | Licence | Used for |
|---|---|---|---|
| Automatic pedestrian and bicycle counts, all years (Parquet) | Stadt Zürich, Tiefbauamt — [data.stadt-zuerich.ch](https://data.stadt-zuerich.ch/dataset/ted_taz_verkehrszaehlungen_werte_fussgaenger_velo) | CC0 | counts, labels |
| Counter locations and correction factors (WFS `view_eco_standorte`) | Stadt Zürich — [dataset](https://data.stadt-zuerich.ch/dataset/geo_standorte_der_automatischen_fuss__und_velozaehlungen) | CC0 | sites, devices, correction factors |
| Velonetz planning layers (`view_velonetz`, `view_gs_umsetzungsstrecken`) | Stadt Zürich — [dataset](https://data.stadt-zuerich.ch/dataset/geo_velonetzplanung) | CC0 | network rank, Velonetz edge cost |
| School holidays | Stadt Zürich — [dataset](https://data.stadt-zuerich.ch/dataset/ssd_schulferien) | CC0 | calendar |
| Indexed traffic development since 2012 (VER100T1001) | Statistik Stadt Zürich / Tiefbauamt — [mobility data](https://www.stadt-zuerich.ch/de/politik-und-verwaltung/statistik-und-daten/daten/mobilitaet.html) | open data, attribution | the official index tested in claim 2 (vintage of 27.07.2026) |
| Hourly weather, Zürich/Fluntern (SMA) | MeteoSwiss SwissMetNet — [open data](https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations) | MeteoSwiss OGD, attribution | weather adjustment |
| Cantonal bicycle counters 2021–2025 | Kanton Zürich, Tiefbauamt — [catalogue](https://datenkatalog.statistik.zh.ch/datasets/3062%40tiefbauamt-kanton-zuerich) | OGD Kanton Zürich | extra inputs (canton6 variant) |
| Cantonal everyday cycling network, cycle paths and lanes | Kanton Zürich — [opendata.swiss](https://opendata.swiss/de/dataset/veloinfrastruktur-radwege-und-radstreifen) | OGD Kanton Zürich | network rank outside the city |
| OpenStreetMap bicycle network (Overpass, current snapshot) | © OpenStreetMap contributors | ODbL 1.0 | cycling network, routes |
| Public holidays | `holidays` Python package (CH-ZH) | MIT | calendar |

Map views in the dashboard are drawn from OpenStreetMap data: © OpenStreetMap
contributors, available under the Open Database License.

## Technical notes on the data

- `FK_STANDORT` in the counts is the location layer's `id1`, one **device period**. A physical site is the `abkuerzung` (e.g. `VZS_HOFW`, four device periods). The all-years Parquet has no `FK_ZAEHLER` column.
- **Correction factors** come from the location layer (`korrekturfaktor`) and differ between device periods of the same site, so device periods are kept distinct.
- **Autumn DST:** the repeated 02:00 hour appears as duplicate quarter-hour rows, which the publisher does not combine. They are summed, flagged and excluded from evaluation.
- **Directions:** a device counts as two-directional only if most rows carry `VELO_OUT`.
- **MeteoSwiss** hourly stamps are UTC and mark the end of the interval; they are shifted to interval start.
- **Cantonal counters** use different sensors and site types. They enter only as inputs and training sites, flagged by source, and are never scored.
- **Network:** OSM bicycle-permitted ways plus footways with explicit bicycle access; contraflow restored for one-way streets open to bikes (~4,200 edges). It is the current network for all years.
