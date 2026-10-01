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
