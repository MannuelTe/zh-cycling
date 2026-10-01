# Held-out-counter backtest: `sensor`

Retrospective **spatial reconstruction** of 2025 hourly bicycle passages at each held-out city counter from contemporaneous counts at the other counters, weather, calendar and network covariates. Raw recorded passages (no correction factors). Static current OSM network. Not a forecast.

Folds: 20 hold-out groups; evaluation hours: complete, non-DST-ambiguous, non-flagged; all models compared on identical site-hours.

## Aggregate (pooled over all held-out site-hours)
| model   |      n |   MAE |   RMSE |   bias |   WAPE |   mean_obs |
|:--------|-------:|------:|-------:|-------:|-------:|-----------:|
| idw     | 184263 | 35.45 |  55.92 |   0.53 |   0.52 |      68.73 |
| glm     | 184263 | 39.06 |  66.05 | -30.93 |   0.57 |      68.73 |
| gbt     | 184263 | 33    |  56.64 | -16.56 |   0.48 |      68.73 |
| gnn     | 184263 | 40.22 |  65.88 | -15.6  |   0.59 |      68.73 |

## Macro average across sites
| model   |   MAE |   RMSE |   bias |   WAPE |
|:--------|------:|-------:|-------:|-------:|
| idw     | 34.63 |  51.05 |   1.17 |   0.73 |
| glm     | 38.01 |  55.58 | -30.4  |   0.56 |
| gbt     | 32.45 |  47.71 | -17.12 |   0.56 |
| gnn     | 39.05 |  58.72 | -16.11 |   0.67 |

## Daily totals (days with 24 evaluated hours)
| model   |    n |    MAE |    RMSE |    bias |   WAPE |   mean_obs |
|:--------|-----:|-------:|--------:|--------:|-------:|-----------:|
| idw     | 7627 | 807.75 | 1014.82 |   13.09 |   0.49 |    1651.59 |
| glm     | 7627 | 909.77 | 1210.32 | -743.04 |   0.55 |    1651.59 |
| gbt     | 7627 | 725.99 | 1027.47 | -398.01 |   0.44 |    1651.59 |
| gnn     | 7627 | 892.01 | 1142.53 | -374.41 |   0.54 |    1651.59 |

## Validation (2024, validation sites) MAE, mean over folds
|     |   val_MAE |
|:----|----------:|
| idw |     32.46 |
| glm |     35.63 |
| gbt |     30.54 |
| gnn |     33.98 |

## Prediction-interval coverage (intervals from validation residuals)
| model   |   nominal 80% |   nominal 90% |
|:--------|--------------:|--------------:|
| idw     |         0.681 |         0.775 |
| glm     |         0.659 |         0.744 |
| gbt     |         0.715 |         0.804 |
| gnn     |         0.715 |         0.829 |

## Week-block bootstrap of pooled MAE differences (95% CI)
|                |   mae_diff_a_minus_b |   ci95_lo |   ci95_hi |
|:---------------|---------------------:|----------:|----------:|
| ('glm', 'idw') |                 3.61 |      2.83 |      4.48 |
| ('glm', 'gnn') |                -1.17 |     -1.66 |     -0.68 |
| ('gbt', 'idw') |                -2.45 |     -3.16 |     -1.75 |
| ('gbt', 'glm') |                -6.06 |     -6.81 |     -5.42 |
| ('gbt', 'gnn') |                -7.23 |     -7.89 |     -6.59 |
| ('gnn', 'idw') |                 4.78 |      4.19 |      5.45 |

## By season
| season        |   ('MAE', 'gbt') |   ('MAE', 'glm') |   ('MAE', 'gnn') |   ('MAE', 'idw') |   ('WAPE', 'gbt') |   ('WAPE', 'glm') |   ('WAPE', 'gnn') |   ('WAPE', 'idw') |   ('bias', 'gbt') |   ('bias', 'glm') |   ('bias', 'gnn') |   ('bias', 'idw') |
|:--------------|-----------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|
| spring/autumn |            33.47 |            40.51 |            41    |            35.68 |              0.47 |              0.57 |              0.58 |              0.51 |            -16.86 |            -31.69 |            -15.83 |             -0.66 |
| summer        |            41.43 |            47.82 |            50.73 |            45.88 |              0.48 |              0.55 |              0.59 |              0.53 |            -22.04 |            -38.98 |            -20.81 |              3.69 |
| winter        |            23.23 |            27.06 |            27.69 |            24.05 |              0.5  |              0.58 |              0.59 |              0.52 |            -10.22 |            -21.02 |             -9.69 |             -0.47 |

## By daytype
| daytype         |   ('MAE', 'gbt') |   ('MAE', 'glm') |   ('MAE', 'gnn') |   ('MAE', 'idw') |   ('WAPE', 'gbt') |   ('WAPE', 'glm') |   ('WAPE', 'gnn') |   ('WAPE', 'idw') |   ('bias', 'gbt') |   ('bias', 'glm') |   ('bias', 'gnn') |   ('bias', 'idw') |
|:----------------|-----------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|
| weekend/holiday |            25.23 |            28.21 |            29.03 |            28.82 |              0.52 |              0.59 |              0.6  |              0.6  |            -12.26 |            -21.77 |            -10.66 |              1.12 |
| workday         |            36.49 |            43.93 |            45.25 |            38.43 |              0.47 |              0.56 |              0.58 |              0.49 |            -18.49 |            -35.05 |            -17.82 |              0.27 |

## By peak
| peak     |   ('MAE', 'gbt') |   ('MAE', 'glm') |   ('MAE', 'gnn') |   ('MAE', 'idw') |   ('WAPE', 'gbt') |   ('WAPE', 'glm') |   ('WAPE', 'gnn') |   ('WAPE', 'idw') |   ('bias', 'gbt') |   ('bias', 'glm') |   ('bias', 'gnn') |   ('bias', 'idw') |
|:---------|-----------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|
| off-peak |            25.8  |            29.69 |            31.01 |            28.43 |              0.5  |              0.57 |              0.6  |              0.55 |            -13.03 |            -23.33 |             -8.85 |              0.63 |
| peak     |            75.88 |            94.86 |            95.13 |            77.27 |              0.45 |              0.56 |              0.56 |              0.45 |            -37.54 |            -76.21 |            -55.78 |             -0.03 |

## By stadttunnel
| stadttunnel       |   ('MAE', 'gbt') |   ('MAE', 'glm') |   ('MAE', 'gnn') |   ('MAE', 'idw') |   ('WAPE', 'gbt') |   ('WAPE', 'glm') |   ('WAPE', 'gnn') |   ('WAPE', 'idw') |   ('bias', 'gbt') |   ('bias', 'glm') |   ('bias', 'gnn') |   ('bias', 'idw') |
|:------------------|-----------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|
| after 22 May 2025 |            36.1  |            42.56 |            43.88 |            38    |              0.48 |              0.57 |              0.59 |              0.51 |            -18.89 |            -35.99 |            -17.44 |              2.51 |
| before            |            28.05 |            33.48 |            34.4  |            31.37 |              0.48 |              0.57 |              0.58 |              0.53 |            -12.85 |            -22.86 |            -12.67 |             -2.61 |

## Per-site hourly MAE
| site     |   idw |    glm |   gbt |   gnn |
|:---------|------:|-------:|------:|------:|
| VZS_ANDR | 31.43 |  21.69 | 10.37 | 13.58 |
| VZS_BASL | 27.68 |  34.51 | 25.63 | 16.87 |
| VZS_BER2 | 20.64 |  37.98 | 23.24 | 20.94 |
| VZS_BUCH | 14.26 |  46.41 | 23.32 | 42.18 |
| VZS_HARN | 19.39 |  12.2  | 12.25 | 42.7  |
| VZS_HARS | 39.88 |  74.64 | 57.35 | 39.82 |
| VZS_HOFW | 30.38 |  20.3  | 17.09 | 23.72 |
| VZS_LAFN | 25.51 |  12.78 |  8.9  | 25.81 |
| VZS_LAFS | 35.24 |  21.29 | 29.78 | 35.78 |
| VZS_LANN | 78.33 | 110.18 | 92.89 | 87.13 |
| VZS_LANS | 56.03 |  67.11 | 59.18 | 56.9  |
| VZS_LIMC | 36.96 |  62.94 | 20.88 | 61.5  |
| VZS_LUXG | 34.64 |  14.56 | 13.88 | 23.32 |
| VZS_MILI | 49.26 |  26.06 | 40    | 39.05 |
| VZS_MUEH | 20.57 |  42.84 | 31.23 | 49.85 |
| VZS_MYTH | 38.77 |  42.26 | 27.66 | 42.08 |
| VZS_SCHE | 22.05 |  26.97 | 23.74 | 34.62 |
| VZS_SCHU | 14.14 |  11.91 | 11.31 | 11.83 |
| VZS_SIHL | 22.32 |  51.78 | 43.27 | 67.09 |
| VZS_TALS | 32    |  14.92 | 12.86 | 28.95 |
| VZS_TANN | 38.54 |  14.29 |  9.16 |  9.5  |
| VZS_TOED | 59.81 |  14.56 | 39.16 | 35.91 |
| VZS_TUNN | 23.69 |  60.35 | 60.53 | 62.87 |
| VZS_TUNS | 59.65 |  69.71 | 85.22 | 65.21 |

## Decision rule

Best baseline by validation MAE: **gbt**.
- GNN better on validation: False (GNN 33.98 vs 30.54)
- GNN - gbt pooled test MAE: +7.23 (95% week-block CI +6.59 .. +7.89)
- GNN wins on 8/24 held-out sites
- **Verdict: DO NOT SELECT GNN (keep best baseline)**

## Difficult sites (highest best-model MAE)
| site     |   best MAE |
|:---------|-----------:|
| VZS_LANN |      78.33 |
| VZS_TUNS |      59.65 |
| VZS_LANS |      56.03 |
| VZS_HARS |      39.82 |
| VZS_MYTH |      27.66 |

![daily](daily_measured_vs_estimated.png)

![wape](per_site_wape.png)

![map](site_error_map.png)
