---
title: "Did cycling in Zurich nearly double? Checking a city claim against its own open counter data"
author: "Manuel Trachsler"
date: "October 2026 · preprint, not peer reviewed"
abstract: |
  The City of Zurich reports that cycling "nearly doubled" between 2012 and 2024,
  based on an index that averages all bicycle counters active in each year. We
  rebuild that index from the city's open counter data and re-estimate growth
  like-for-like on the {{claim.n_panel}} counters that operated in both years,
  adjusting for weather and calendar. The official figure ({{claim.official_ratio}})
  is reproducible ({{claim.city_median}} with a median over counters), and strong
  growth is not in doubt. Whether it reaches "nearly doubled" (≥ {{claim.threshold}},
  fixed before estimation) depends on how one device change in 2019 is treated: the
  pre-registered estimate is {{claim.S1.point}} (95% CI {{claim.S1.ci_lo}}–{{claim.S1.ci_hi}}),
  giving a confidence of {{claim.confidence}}, with a range of {{claim.conf_lo}}–{{claim.conf_hi}}
  across four analysis choices. A secondary analysis shows that hourly counts at an
  unmeasured location can be reconstructed from the other counters only to about
  {{model.wape_c6}} weighted absolute error.
---

<!--
DRAFT. Every double-brace placeholder is filled from the pipeline outputs by `zh-cycling figures`,
which writes paper/build/paper.md; `scripts/build_paper.sh` then runs pandoc.
Run `python -m zh_cycling.summary` to list all available keys.
Table markers (an HTML comment reading 'table: name') are replaced by paper/tables/name.md.
-->

# 1. Introduction

- Public cycling statistics are used to justify infrastructure spending; Zurich's
  index is cited by the city and by advocacy groups (Pro Velo, Nov 2025).
- The index averages whatever counters exist each year. Counters were added,
  replaced and moved, so growth and network composition are mixed.
- Questions: (i) can the published figure be reproduced from open data,
  (ii) how much of it survives a like-for-like comparison, (iii) how confident
  can one be that cycling "nearly doubled".

# 2. Data

- City counter observations 2009–2026 (15-minute, both directions), device and
  correction-factor metadata, MeteoSwiss hourly weather, calendar. See
  `DATA_SOURCES.md`.
- Counters in the city index: {{claim.n_2012}} in 2012, {{claim.n_2024}} in 2024
  (sites with ≥ 250 complete days).
- Cleaning: physical site vs device period, autumn DST duplicates, partial hours,
  zero runs (README, "Data findings").

# 3. Methods

## 3.1 Reproducing the official index
Several plausible aggregation rules over all counters; root-mean-square
difference from the official series 2012–2025 (best {{claim.best_rmse}} index points).

<!-- table: tab4_reproduction -->

## 3.2 Like-for-like growth
Poisson GLM on daily totals with year effects, coverage-period fixed effects
(device periods sharing a correction factor) and weather/calendar covariates.
Four scenarios (Table 1). Uncertainty: two-stage cluster bootstrap over sites
and ISO-week blocks.

## 3.3 Test definition, fixed in advance
"Nearly doubled" ⇔ true 2012→2024 ratio ≥ {{claim.threshold}}. Confidence =
share of bootstrap draws at or above the threshold under scenario S1.

## 3.4 Anomaly inventory
Device-swap step test against the median of other counters; year-to-year level
jumps relative to the median counter; grouped by cause (A measurement breaks,
B temporary disruptions, C city-wide events, D real local change, E counter mix).

# 4. Results

## 4.1 The official figure is reproducible
![Official index and four reconstructions.](figures/fig1_index.png)

## 4.2 Like-for-like growth and confidence
The same {{claim.n_panel}} counters grew {{claim.unadjusted}} unadjusted and
{{claim.S1.point}} adjusted. Strong growth is robust (P(≥ ×1.5) = {{claim.S1.p15}}).

<!-- table: tab1_scenarios -->

![Bootstrap distributions by scenario.](figures/fig2_bootstrap.png)

## 4.3 One counter carries the margin
Leaving one counter out gives {{claim.loo_fp_lo}}–{{claim.loo_fp_hi}}; without
Andreasstrasse {{claim.without_andr}}. Treating its October 2019 device swap as a
break gives {{claim.andr_break}}.

![Andreasstrasse relative to the median counter.](figures/fig3_andreasstrasse.png)

<!-- table: tab2_anomalies -->

## 4.4 Composition and the fragility of the median
A plain average over all counters would show {{claim.mix_all}} = {{claim.mix_stayers}}
(stayers) × {{claim.mix_factor}} (counter mix). The city's median is far less
exposed, but with {{claim.n_2012}} counters in 2012, dropping any one moves it
between {{claim.loo_city_lo}} and {{claim.loo_city_hi}}.

# 5. Secondary analysis: reconstructing counts at unmeasured locations

Held-out-site backtest, test year 2025. Best model: a validation-weighted blend
of gradient boosting and network-distance IDW, with 29 cantonal stations as extra
inputs: pooled hourly MAE {{model.mae_c6}} passages/h (city-only {{model.mae_city}}),
daily-total WAPE {{model.daily_wape_c6}}, 90% interval coverage {{model.cov90_c6}}.
An inductive GNN was {{model.gnn_gap_lo}}–{{model.gnn_gap_hi}} passages/h worse
than gradient boosting and was not selected. Routing along the planned Velonetz
did not help the blend ({{model.mae_velonetz}}).

<!-- table: tab3_models -->

![Model comparison.](figures/fig4_leaderboard.png)

# 6. Discussion

- The city's number is defensible as a headline, but its precision is lower than
  one decimal suggests, and the like-for-like evidence supports "up about
  three-quarters to nine-tenths" more firmly than "nearly doubled".
- One question to the Tiefbauamt would resolve most of the range: whether the
  Andreasstrasse device change in October 2019 altered what is counted.
- Limitations: few long-running counters; correction factors taken as published;
  counters measure passages at a cross-section, not trips or people; static
  current network for the secondary analysis.

![Weather-adjusted index on seven stable counters, 2017 = 1.](figures/fig5_history.png)

# Data and code availability

Code (MIT), outputs and this manuscript (CC BY 4.0):
https://github.com/MannuelTe/zh-cycling. All results are regenerated by
`scripts/reproduce.sh`.
