# Zurich cycling counts: coding-agent handoff

Prepared 30 September 2026. Status: researched implementation plan; no model has been trained or backtest run. Dataset descriptions and API documentation were checked; bulk files and live routing responses still need ingestion and inspection.

## Objective and scope

Estimate hourly bicycle passages at an unobserved Zurich counter using other counters, weather, calendar variables and the cycling network. Start with spatial reconstruction using contemporaneous observations at other sites; future forecasting is a separate experiment. Use an inductive graph neural network (GNN), benchmarked against simpler ML methods. Counter readings measure passages at a cross-section, not unique cyclists, journeys or origin-destination flows.

Start with city counters in 2021–2025; use earlier years for historical analysis. Add compatible cantonal counters after auditing their definitions and coverage. More nodes may help the GNN, but city and cantonal sensor technologies and site types differ.

## 1. Data inventory and access

| Source | Confirmed availability | Implementation use |
|---|---|---|
| [City counter observations](https://data.stadt-zuerich.ch/dataset/ted_taz_verkehrszaehlungen_werte_fussgaenger_velo) | 2009 onward; direction-specific 15-minute counts; annual CSVs and all-years Parquet; daily updates; CC0 | Primary supervised labels. Fields documented: FK_ZAEHLER, FK_STANDORT, DATUM, VELO_IN, VELO_OUT, FUSS_IN, FUSS_OUT, OST, NORD. |
| [City counter locations](https://data.stadt-zuerich.ch/dataset/geo_standorte_der_automatischen_fuss__und_velozaehlungen) | CSV, GeoPackage, GeoJSON and WFS; projected GIS data in EPSG:2056 | Site geometry and direction/coverage metadata. FK_STANDORT references location ID1; verify actual files. |
| [Cantonal cycling counters](https://www.zh.ch/de/mobilitaet/veloverkehr/veloverkehrsplanung/datenrundlagen-veloverkehr.html) | Network started in 2016; 97 active stations in 2025. Published [2024](https://datenkatalog.statistik.zh.ch/datasets/3062%40tiefbauamt-kanton-zuerich/distributions/6778) and [2025](https://datenkatalog.statistik.zh.ch/datasets/3062%40tiefbauamt-kanton-zuerich/distributions/6779) distributions contain hourly CSV data | Broader training geography. Check documentation for identifiers, quality flags, directions, weather, date coverage and overlap with city sites before merging. Do not assume every station existed throughout the period. |
| [swissTLM3D](https://www.swisstopo.admin.ch/en/landscape-model-swisstlm3d) | National roads/tracks, buildings, land cover and public transport features; GeoPackage and other vector formats | Authoritative geometry/context; elevation/slope can use swissALTI3D. Routing restrictions and cycle facilities require supplementary attributes. |
| [Federal STAC API](https://docs.geo.admin.ch/download-data/stac-api/overview.html) | File-based geodata discovery/download through https://data.geo.admin.ch/api/stac/v1/ | Download relevant assets rather than extracting a network from map images. WMS is for display; WFS/GeoJSON/vector files supply analysable features. |
| [City Velonetzplanung](https://data.stadt-zuerich.ch/dataset/geo_velonetzplanung) | Network and implementation-segment layers, including VIEW_VELONETZ and VIEW_GS_UMSETZUNGSSTRECKEN | Route classifications and project geometry. Planning status does not prove a facility was operational historically; metadata alone is not a dated construction archive. |
| [MeteoSwiss weather](https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations) | Historical hourly observations via STAC collection ch.meteoschweiz.ogd-smn | Temperature, precipitation, wind and sunshine; select nearby stations by coverage. Add Zurich holidays, school breaks and calendar features. |

Create these canonical tables:

- `sites`: source, physical_site_id, device_id, geometry, valid_from/to, coverage type, direction mapping, correction provenance.
- `counts_hourly`: site_id, timestamp, raw_in/out, completeness, quality flags, observation mask; corrected estimates stored separately.
- `nodes` / `edges`: node type and covariates; directed endpoints, geometry, distance, routing time, gradient, facility attributes, valid_from/to, graph version.
- `weather_hourly` and `events`: meteorological covariates; separately dated infrastructure, sensor-definition and policy/context records with source URLs.

Cleaning requirements: group by physical site, not device alone (devices can move); exclude pedestrian-only sensors; preserve zero counts and distinguish them from missing intervals. Aggregate four valid quarter-hours to an hour, flag partial hours rather than treating them as complete. Counter timestamps are local, with special daylight-saving behaviour: spring has a missing hour; autumn's repeated hour is combined by the publisher. Preserve this provenance and exclude ambiguous hours from headline hourly evaluation. Normalise other timestamps using Europe/Zurich/UTC consistently.

Predict raw recorded passages first. Apply documented manual correction factors only in a separate reporting layer. Langstrasse and Hofwiesenstrasse can cover partial cross-sections; sensor-coverage changes must create distinct validity periods. The linked legacy correction PDF currently fails to resolve, so retrieving the current factors is an explicit ingestion task.

## 2. Graph and GNN approach

Use [openrouteservice](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/) with `cycling-regular`: `POST /v2/directions/cycling-regular/geojson` for routes and `POST /v2/matrix/cycling-regular` for distance/time matrices. Supply longitude/latitude in EPSG:4326; calculate GIS distances in EPSG:2056. Use an API key supplied through the environment, respect current request limits and cache responses with profile, parameters and retrieval/build metadata. This plan does not claim the API has already been executed.

Build a bicycle-permitted street graph from OSM, checked against official GIS. Preserve cycle contraflow, access restrictions and grade-separated crossings. Snap each counter to its actual measured segment and insert a sensor node. Retain important intersections, bridges, tunnel portals and route junctions; simplify intermediate geometry-only nodes. Select additional crossings by network connectivity/betweenness and destinations, not by using the held-out counts. These are candidate important crossings, not measured popular ones.

Physical edges represent adjoining cycle-network segments. ORS matrices can define a separate sensor-neighbour graph, e.g. the nearest 3–5 sensors by cycling time, with weights exp(-time/tau). Do not confuse an all-pairs route with a direct street edge; split route geometries at retained junctions. An ablation should compare this sensor graph with the fuller intersection graph.

Recommended model: a small inductive, edge-aware message-passing network plus a temporal convolution/GRU, inspired by [IGNNK](https://ojs.aaai.org/index.php/AAAI/article/view/16575). Use shared weights, no learned site-ID embeddings. Inputs: masked counts and availability flags over 24–168 hours, weather/calendar variables, network centrality, gradient and facility context. Predict nonnegative hourly passages at sensor/query nodes; initially predict combined directions, then separate directions if metadata supports consistent mapping. Unmeasured intersection nodes have covariates and no labels, never artificial zero labels. Their predictions are exploratory until externally validated.

Train by withholding complete sensor histories within input windows and applying loss only to the withheld valid labels. Use MAE on log1p counts initially, with raw-scale reporting. Tune model size and graph sparsity using training/validation sites. The small city network makes a GNN advantage uncertain; evaluate rather than assume it.

## 3. Historical infrastructure, behaviour and politics

Build an event ledger with publication date, effective/opening date, type, actor, affected geometry, source and confidence. Separate physical changes, measurement changes, observed behaviour, votes/strategy decisions and political claims.

Verified starting records:

- **2015:** CHF 120 million cycling framework credit. Annual Bauprogramm Velo reports document expenditure and delivered measures; [2024 reporting](https://www.stadt-zuerich.ch/de/aktuell/medienmitteilungen/2024/09/schritt-fuer-schritt-zur-velostadt-jaehrlicher-bericht-zur-velofoerderung-liegt-vor.html) records four kilometres of marked priority routes. Extract actual segment completion dates from reports/project pages.
- **27 September 2020 / March 2021:** approval of the safe-cycle-routes initiative, followed by [Velostrategie 2030](https://www.stadt-zuerich.ch/de/aktuell/medienmitteilungen/2021/03/210319a.html). Record these as policy events, not construction dates.
- **2021 / March 2022, Langstrasse:** new on-road cycle lanes, followed by expanded counter coverage. The city reports about 23% of passages shifted to the roadway. This is both a behavioural and a measurement-definition issue.
- **March 2023, Baslerstrasse/Bullingerstrasse:** priority route opened; the city reports roughly 40% higher weekday counts in 2023 than 2022. This is an observed comparison, not a causal estimate. Both examples: [city counter analysis](https://www.stadt-zuerich.ch/artikel/de/statistik-und-daten/automatische-zaehlungen-des-veloverkehrs.html).
- **22 May 2025:** [Stadttunnel opened](https://www.stadt-zuerich.ch/de/aktuell/medienmitteilungen/2025/05/eroeffnung-stadttunnel.html), changing connectivity beneath HB. Brander frames it as a cycling milestone; Baumer emphasises public-transport access. Treat these as attributed political statements.
- **Implementation debate:** [city November 2025 report](https://www.stadt-zuerich.ch/de/aktuell/medienmitteilungen/2025/11/velofoerderung-nimmt-weiter-fahrt-auf.html) reports 4.3 km of marked priority routes; a [2026 Green Party statement](https://gruenezuerich.ch/blog/fraktionserklaerungen/einen-gang-hoeher-schalten-velovorzugsrouten-konsequent-umsetzen) criticises slow delivery and through-traffic. Preserve dates and definitions; do not reconcile differing kilometre claims by silently treating them as equivalent.

Measure behavioural changes using a stable-site panel, weather-adjusted counts, weekday/weekend and peak/off-peak shares. Add pandemic periods, roadworks and sensor changes as confounders. Historical topology must use archived network snapshots or documented edits; today's router includes facilities absent in earlier years. If historic topology cannot be reconstructed, label the experiment as static-current-network reconstruction and restrict claims. Politics belongs in the contextual timeline initially, not an automatic sentiment-to-demand predictor. Counter interpolation alone cannot identify induced cycling or the causal effect of a new route.

## 4. Held-out-counter backtest

1. Freeze eligible sites, data-quality rules and temporal splits before fitting. Suggested split: training through 2023, validation in 2024, final test in 2025, if coverage is sufficient. Otherwise select earlier/later contiguous blocks providing a full seasonal test cycle. For historical evaluation, version topology or state the static-graph limitation.
2. Hold out one **entire physical site**: every device, both directions, all years, input lags and derived aggregates. Never use its labels for fitting, scaling, graph correlations, feature selection or hyperparameter tuning. Use separate validation sites. Repeat across all eligible city sites.
3. Retain the street connection and public geometry; remove the measurement signal. For a strict unseen-site test, exclude the sensor node during training and insert it as an unobserved query node only at inference. Road/junction topology remains intact.
4. Estimate its 2025 hourly counts from permitted observations at other sites. This is retrospective reconstruction using contemporaneous neighbouring counts, not a future forecast. If desired, run a second causal-time forecast using only past data and available weather forecasts.
5. Compare a network-distance weighted baseline, a pooled regularised count regression and gradient-boosted trees against the GNN. All methods get the same permitted information and no target-site calibration. Keep a validation-tuned model-selection protocol; never tune on final held-out-site results.
6. Report per-site MAE, RMSE, mean bias and WAPE; macro-average across sites as well as aggregate results. Avoid headline MAPE because zeros are common. Break down winter/summer, weekday/weekend, peak/off-peak and intervention periods. Include daily totals, measured-vs-estimated plots and a map of site errors.
7. Estimate uncertainty using validation residuals, report empirical coverage of prediction intervals, and use week-block bootstrap intervals for model comparisons. Repeat spatial tests by withholding neighbouring sites together; test sensitivity to graph choice and cantonal-data inclusion.

## Deliverables and decision rule

Produce reproducible download/clean/graph/train/evaluate commands, cached source manifests, a data-quality summary, an attributed event ledger, held-out predictions and a concise results report. Use Python, GeoPandas/PyProj, NetworkX, Parquet/DuckDB, scikit-learn/gradient boosting and PyTorch Geometric or DGL; choose and pin library versions during implementation.

Build ingestion and baselines first, then the GNN. Select the GNN only if it improves validation performance and retains a consistent advantage in locked held-out-site tests. Report failures and difficult sites. No performance numbers are available yet. The first validated product is a counter-estimation map; route-change simulation requires additional behavioural/causal modelling.