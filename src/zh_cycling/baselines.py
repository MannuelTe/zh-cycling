"""Non-graph-learning comparators, all given the same permitted information as
the GNN: contemporaneous counts at visible sites, weather, calendar and static
network covariates of the target location. No target-site calibration.

* ``idw``  : network-distance (cycling time) weighted mean of neighbour counts
* ``glm``  : pooled L2-regularised Poisson regression
* ``gbt``  : histogram gradient-boosted trees with Poisson loss
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .panel import Panel

TAUS = (180.0, 600.0)


def neighbour_features(p: Panel, t: int, visible: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Features for target site index `t` at hour indices `rows`, using only
    observations of `visible` sites (bool, length S; t itself is always excluded)."""
    vis = visible.copy()
    vis[t] = False
    A = p.M[rows][:, vis]
    Ls = np.nan_to_num(np.log1p(p.Y[rows][:, vis]))
    An = np.nan_to_num(Ls - p.devmean[rows][:, vis]) * A
    Tt = p.T[t, : p.S][vis]
    n_av = A.sum(1)
    city = np.where(n_av > 0, (A * Ls).sum(1) / np.maximum(n_av, 1), np.nan)
    out = [city]
    for tau in TAUS:
        w = np.exp(-Tt / tau)
        den = A @ w
        out.append(np.where(den > 1e-9, (A * Ls) @ w / np.maximum(den, 1e-12), city))
        out.append(np.log(den + 1e-6))
    w = np.exp(-Tt / TAUS[1])
    den = A @ w
    out.append(np.where(den > 1e-9, An @ w / np.maximum(den, 1e-12), 0.0))
    order = np.argsort(Tt)
    Ao = A[:, order]
    first = Ao.argmax(1)
    has = Ao.any(1)
    out.append(np.where(has, Ls[:, order][np.arange(len(rows)), first], city))
    out.append(np.where(has, Tt[order][first] / 60.0, 60.0))
    out.append(n_av.astype(float))
    F = np.column_stack(out)
    with np.errstate(all="ignore"):
        fill = np.nan_to_num(np.nanmean(F, 0))
    return np.where(np.isnan(F), fill, F)


def design(p: Panel, t: int, visible: np.ndarray, rows: np.ndarray) -> np.ndarray:
    nb = neighbour_features(p, t, visible, rows)
    hour = p.calendar.hour.to_numpy()[rows]
    return np.hstack([nb, p.glob[rows], np.repeat(p.static[t, :-1][None], len(rows), 0), np.eye(24)[hour][:, 1:]]).astype(np.float32)


def stack_rows(p: Panel, targets, visible, period_mask, max_rows=None, rng=None):
    X, y, site = [], [], []
    for t in targets:
        rows = np.where(period_mask & p.M[:, t])[0]
        if len(rows) == 0:
            continue
        X.append(design(p, t, visible, rows))
        y.append(p.Y[rows, t])
        site.append(np.full(len(rows), t))
    X, y, site = np.vstack(X), np.concatenate(y), np.concatenate(site)
    if max_rows and len(y) > max_rows:
        keep = (rng or np.random.default_rng(0)).choice(len(y), max_rows, replace=False)
        X, y, site = X[keep], y[keep], site[keep]
    return X, y, site


# --------------------------------------------------------------------------
def idw_predict(p: Panel, t: int, visible: np.ndarray, rows: np.ndarray, tau: float) -> np.ndarray:
    vis = visible.copy()
    vis[t] = False
    A = p.M[rows][:, vis]
    Yv = np.nan_to_num(p.Y[rows][:, vis])
    w = np.exp(-p.T[t, : p.S][vis] / tau)
    den = A @ w
    pred = (A * Yv) @ w / np.maximum(den, 1e-12)
    fallback = np.where(A.any(1), (A * Yv).sum(1) / np.maximum(A.sum(1), 1), 0.0)
    return np.where(den > 1e-12, pred, fallback)


IDW_GRID = [{"tau": 120.0}, {"tau": 300.0}, {"tau": 600.0}, {"tau": 1200.0}]
GLM_GRID = [{"alpha": 1e-4}, {"alpha": 1e-3}, {"alpha": 1e-2}]
GBT_GRID = [
    {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 200},
    {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 15, "min_samples_leaf": 1000},
]


def make_model(kind: str, params: dict):
    if kind == "glm":
        return make_pipeline(StandardScaler(), PoissonRegressor(alpha=params["alpha"], solver="newton-cholesky", max_iter=300))
    if kind == "gbt":
        return HistGradientBoostingRegressor(loss="poisson", l2_regularization=1.0, early_stopping=False, random_state=0, **params)
    raise ValueError(kind)
