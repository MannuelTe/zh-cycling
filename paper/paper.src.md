---
title: "Did cycling in Zurich nearly double? Checking a city claim against its own open counter data"
author: "Manuel Trachsler"
date: "October 2026 · preprint, not peer reviewed"
abstract: |
  The City of Zurich reports that cycling "nearly doubled" between 2012 and 2024,
  based on an index that averages all bicycle counters active in each year. We
  rebuild that index from the city's open counter data and re-estimate growth
  like-for-like on the {{claim.n_panel}} counters that operated in both years,
  adjusting for weather and calendar. The official figure ($\times {{claim.official_ratio_n}}$)
  is reproducible ($\times {{claim.city_median_n}}$ with a median over counters), and strong
  growth is not in doubt. Whether it reaches "nearly doubled" ($r \geq {{claim.threshold_n}}$,
  fixed before estimation) depends on how one device change in 2019 is treated: the
  pre-registered estimate is $\hat r = {{claim.S1.point_n}}$ (95% CI {{claim.S1.ci_lo_n}}–{{claim.S1.ci_hi_n}}),
  giving a confidence of $\hat p = {{claim.confidence}}$, with a range of {{claim.conf_lo}}–{{claim.conf_hi}}
  across four analysis choices. A secondary analysis shows that hourly counts at an
  unmeasured location can be reconstructed from the other counters only to about
  {{model.wape_c6}} weighted absolute error.
---

<!--
DRAFT. Every double-brace placeholder is filled from the pipeline outputs by `zh-cycling figures`,
which writes paper/paper.md (GitHub) and paper/build/paper.md; `scripts/build_paper.sh` then runs pandoc.
Run `python -m zh_cycling.summary` to list all available keys; keys ending in _n are plain numbers for use in math.
Table markers (an HTML comment reading 'table: name') are replaced by paper/tables/name.md.
Math: inline $...$ and display $$...$$ render both on GitHub and in pandoc.
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
  (sites with at least 250 complete days).
- Cleaning: physical site vs device period, autumn DST duplicates, partial hours,
  zero runs (README, "Technical notes on the data").

# 3. Methods

## 3.1 Reproducing the official index

Let $\bar y_{st}$ be the mean daily count of counter $s$ in year $t$, and $S_t$ the
set of counters active in year $t$. We compare several aggregation rules with the
official index $I_t$, for example the median rule

$$
\hat I_t = 100 \cdot \frac{\mathrm{median}_{s \in S_t} \bar y_{st}}{\mathrm{median}_{s \in S_{2012}} \bar y_{s,2012}},
$$

by the root-mean-square difference over 2012–2025 (best: {{claim.best_rmse}} index points).

<!-- table: tab4_reproduction -->

## 3.2 Like-for-like growth

For the {{claim.n_panel}} counters observed in both 2012 and 2024, the daily total
$y_{sd}$ of counter $s$ on day $d$ is modelled as

$$
y_{sd} \sim \mathrm{Poisson}(\mu_{sd}), \qquad
\log \mu_{sd} = \alpha_{c(s,d)} + \gamma_{t(d)} + \mathbf{x}_d^{\top} \beta,
$$

where $c(s,d)$ is the coverage period (consecutive device periods sharing a
correction factor), $t(d)$ the year and $\mathbf{x}_d$ the weather and calendar
covariates (temperature and its square, $\log(1+\text{precipitation})$, sunshine,
weekday, public and school holidays, month). The growth ratio is

$$
r = \exp\left(\gamma_{2024} - \gamma_{2012}\right).
$$

The chain-linked variant multiplies consecutive-year ratios, each fitted on the
counters observed in both years:
$r^{\text{chain}} = \prod_{t=2012}^{2023} \exp\left(\hat\gamma^{(t)}_{t+1} - \hat\gamma^{(t)}_{t}\right)$.
Table 1 lists the four scenarios.

## 3.3 Test definition and confidence, fixed in advance

"Nearly doubled" is defined as $r \geq {{claim.threshold_n}}$. Uncertainty comes from a
two-stage cluster bootstrap: resample counters with replacement, then ISO-week
blocks, and refit. With $B = {{claim.n_boot}}$ draws $r^{\ast}_1, \dots, r^{\ast}_B$ under
the pre-registered scenario S1, the reported confidence is

$$
\hat p = \frac{1}{B} \sum_{b=1}^{B} \mathbf{1}\left[ r^{\ast}_b \geq {{claim.threshold_n}} \right].
$$

## 3.4 Anomaly inventory

For a device swap at counter $s$ on date $\tau$, the step relative to the other
counters is

$$
\Delta_s = \left( \overline{\log y}_{s}^{\,\text{after}} - \overline{\log y}_{s}^{\,\text{before}} \right)
- \mathrm{median}_{s' \neq s} \left( \overline{\log y}_{s'}^{\,\text{after}} - \overline{\log y}_{s'}^{\,\text{before}} \right),
$$

using 120-day windows on either side of $\tau$; we report $e^{\Delta_s}$. Year-to-year
jumps of a counter's level relative to the median counter beyond a factor of 1.25
are flagged. Anomalies are grouped by cause: A measurement breaks, B temporary
disruptions, C city-wide events, D real local change, E counter mix.

# 4. Results

## 4.1 The official figure is reproducible

![Official index and four reconstructions.](figures/fig1_index.png)

## 4.2 Like-for-like growth and confidence

The same {{claim.n_panel}} counters grew $\times {{claim.unadjusted_n}}$ unadjusted and
$\hat r = {{claim.S1.point_n}}$ adjusted. Strong growth is robust:
$P(r \geq 1.5) = {{claim.S1.p15}}$, while $\hat p = P(r \geq {{claim.threshold_n}}) = {{claim.S1.p18}}$.

<!-- table: tab1_scenarios -->

![Bootstrap distributions by scenario.](figures/fig2_bootstrap.png)

## 4.3 One counter carries the margin

Leaving one counter out gives $\hat r \in [{{claim.loo_fp_lo_n}}, {{claim.loo_fp_hi_n}}]$;
without Andreasstrasse $\hat r = {{claim.without_andr_n}}$. Treating its October 2019
device swap as a break gives $\hat r = {{claim.andr_break_n}}$.

![Andreasstrasse relative to the median counter.](figures/fig3_andreasstrasse.png)

<!-- table: tab2_anomalies -->

## 4.4 Composition and the fragility of the median

For a plain average over all counters, the growth ratio splits exactly into
like-for-like growth and a counter-mix term ("stay" = counters active in both years):

$$
\frac{\bar y^{\,\text{all}}_{2024}}{\bar y^{\,\text{all}}_{2012}}
= \underbrace{\frac{\bar y^{\,\text{stay}}_{2024}}{\bar y^{\,\text{stay}}_{2012}}}_{\text{same counters}}
\times \underbrace{\frac{\bar y^{\,\text{all}}_{2024} / \bar y^{\,\text{stay}}_{2024}}{\bar y^{\,\text{all}}_{2012} / \bar y^{\,\text{stay}}_{2012}}}_{\text{counter mix}},
\qquad {{claim.mix_all_n}} = {{claim.mix_stayers_n}} \times {{claim.mix_factor_n}}.
$$

The city's median is far less exposed to composition, but with {{claim.n_2012}}
counters in 2012, dropping any one moves it between $\times {{claim.loo_city_lo_n}}$
and $\times {{claim.loo_city_hi_n}}$.

# 5. Secondary analysis: reconstructing counts at unmeasured locations

Held-out-site backtest, test year 2025. Errors are reported as
$\text{MAE} = \frac{1}{n}\sum_i |y_i - \hat y_i|$ and
$\text{WAPE} = \sum_i |y_i - \hat y_i| \,/\, \sum_i y_i$ over held-out site-hours.
The best model is a validation-weighted blend of gradient boosting and
network-distance IDW, $\hat y = w\,\hat y^{\text{GBT}} + (1-w)\,\hat y^{\text{IDW}}$ with
$w$ chosen per fold on validation sites, using 29 cantonal stations as extra
inputs: pooled hourly MAE {{model.mae_c6}} passages/h (city-only {{model.mae_city}}),
daily-total WAPE {{model.daily_wape_c6}}, 90% interval coverage {{model.cov90_c6}}.
An inductive GNN was {{model.gnn_gap_lo}}–{{model.gnn_gap_hi}} passages/h worse than
gradient boosting and was not selected. Routing along the planned Velonetz did not
help the blend (MAE {{model.mae_velonetz}}).

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
