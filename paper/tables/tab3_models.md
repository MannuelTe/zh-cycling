| model                                    |   pooled MAE |   macro MAE |   WAPE |   bias |   90% coverage |
|:-----------------------------------------|-------------:|------------:|-------:|-------:|---------------:|
| Blend GBT+IDW (+cantonal)                |        31.14 |       30.49 |   0.45 | -10.18 |           0.84 |
| Blend GBT+IDW (+cantonal, Velonetz cost) |        31.15 |       30.44 |   0.45 |  -8.91 |           0.84 |
| Gradient boosting (+cantonal)            |        33.07 |       32.43 |   0.48 |  -9.59 |           0.85 |
| Blend GBT+IDW (city)                     |        33.25 |       32.51 |   0.48 | -11.98 |           0.77 |
| Network IDW (+cantonal)                  |        33.43 |       32.23 |   0.49 |  -9.56 |           0.77 |
| Gradient boosting (city)                 |        35.22 |       34.45 |   0.51 | -15.79 |           0.80 |
| Network IDW (city)                       |        35.45 |       34.63 |   0.52 |   0.53 |           0.77 |
| GNN, intersection graph (city)           |        38.61 |       37.00 |   0.56 | -17.61 |           0.80 |
| Poisson GLM (city)                       |        39.06 |       38.01 |   0.57 | -30.93 |           0.74 |
| GNN, sensor graph (city)                 |        40.22 |       39.05 |   0.59 | -15.60 |           0.83 |
