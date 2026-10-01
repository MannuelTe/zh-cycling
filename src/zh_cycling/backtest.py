"""Held-out-site backtest (spatial reconstruction, test year 2025).

For every hold-out group G (sites within 150 m of each other, i.e. the same
cross-section, or a larger radius for the sensitivity run):

1. G's sites are removed everywhere: no labels, no inputs, no scaling, not in
   the training graph. (Their static network covariates are public geometry
   and remain available.)
2. The remaining sites are split into training sites and validation sites
   (~25% of groups, drawn per fold). Models are fitted on training sites in
   2021-2023; hyper-parameters / early stopping use the validation sites in
   2024 with the validation sites hidden. Prediction intervals come from those
   validation residuals.
3. Baselines are refitted on training + validation sites (still <= 2023);
   the GNN is refitted for the selected number of epochs.
4. G's 2025 hourly counts are reconstructed from contemporaneous observations
   at the remaining sites.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import torch

from . import baselines as B
from . import config as C
from . import gnn
from .panel import Panel, build_panel, eligible_test_sites, holdout_folds, regroup

PI_LEVELS = (0.8, 0.9)
ENS_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)  # weight on gbt; rest on idw


def _device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _val_split(p: Panel, remaining: list[str], groups: dict[str, str], fold_i: int) -> tuple[list[str], list[str]]:
    va_mask = p.period(C.TRAIN_END, C.VAL_END)
    # validation mirrors the test domain: only city groups are drawn; cantonal
    # stations always stay training sites
    grp = sorted({groups[s] for s in remaining if p.source[s] == "city"})
    has_val = [g for g in grp if any(p.M[va_mask, p.sites.index(s)].sum() >= C.MIN_TEST_HOURS for s in remaining if groups[s] == g)]
    rng = np.random.default_rng(C.SEED + fold_i)
    n_val = max(2, round(0.25 * len(has_val)))
    val_groups = set(rng.choice(has_val, n_val, replace=False))
    val = [s for s in remaining if groups[s] in val_groups]
    train = [s for s in remaining if groups[s] not in val_groups]
    return train, val


def _mask(p: Panel, sites) -> np.ndarray:
    m = np.zeros(p.S, bool)
    m[[p.sites.index(s) for s in sites]] = True
    return m


def _pi_quantiles(y: np.ndarray, pred: np.ndarray) -> dict:
    r = np.log1p(y) - np.log1p(np.clip(pred, 0, None))
    q = {}
    for lev in PI_LEVELS:
        a = (1 - lev) / 2
        q[lev] = (float(np.quantile(r, a)), float(np.quantile(r, 1 - a)))
    return q


def _frame(p, site, rows, pred, model, fold, q):
    t = p.sites.index(site)
    df = pd.DataFrame({"fold": fold, "site": site, "model": model, "ts_local": p.hours[rows],
                       "y": p.Y[rows, t], "observed": p.M[rows, t], "pred": pred})
    for lev, (lo, hi) in q.items():
        base = np.log1p(np.clip(pred, 0, None))
        df[f"lo{int(lev * 100)}"] = np.expm1(np.clip(base + lo, 0, None))
        df[f"hi{int(lev * 100)}"] = np.expm1(np.clip(base + hi, 0, None))
    return df


def run(models=("idw", "glm", "gbt", "gnn"), gnn_graph="sensor", holdout_radius: float | None = None,
        folds_only: list[int] | None = None, gnn_refit: bool = True, max_rows: int = 300_000,
        tag: str | None = None) -> pd.DataFrame:
    p = build_panel()
    groups = regroup(p, holdout_radius) if holdout_radius else p.groups
    folds = holdout_folds(p, groups)
    elig = set(eligible_test_sites(p))
    tag = tag or f"{gnn_graph}" + (f"_r{int(holdout_radius)}" if holdout_radius else "")
    out_dir = C.OUTPUTS / "backtest" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    device = _device()
    print(f"Backtest '{tag}': {len(folds)} folds, models={models}, device={device}")

    test_mask = p.period(C.VAL_END, C.TEST_END)
    tr_mask = p.period(C.PANEL_START, C.TRAIN_END)
    va_mask = p.period(C.TRAIN_END, C.VAL_END)
    rng = np.random.default_rng(C.SEED)
    all_preds, sel_log = [], []

    for fi, E in enumerate(folds):
        if folds_only and fi not in folds_only:
            continue
        fpath = out_dir / f"fold_{fi:02d}.parquet"
        if fpath.exists():
            print(f"[{fi + 1}/{len(folds)}] {E} cached")
            all_preds.append(pd.read_parquet(fpath))
            continue
        t0 = time.time()
        remaining = [s for s in p.sites if s not in E]
        train_s, val_s = _val_split(p, remaining, groups, fi)
        test_s = [s for s in E if s in elig]
        print(f"[{fi + 1}/{len(folds)}] hold out {E}; test {test_s}; val {val_s}")
        vis_inner = _mask(p, train_s)  # E and validation sites unseen
        vis_final = _mask(p, remaining)
        test_rows = np.where(test_mask)[0]
        fold_preds = []
        val_pred, val_y = {}, {}
        info = {"fold": fi, "holdout": E, "test": test_s, "val": val_s}

        if "idw" in models:
            best = None
            for prm in B.IDW_GRID:
                ys, ps = [], []
                for v in val_s:
                    t = p.sites.index(v)
                    rows = np.where(va_mask & p.M[:, t])[0]
                    pr = B.idw_predict(p, t, vis_inner, rows, prm["tau"])
                    ys.append(p.Y[rows, t])
                    ps.append(pr)
                y_, p_ = np.concatenate(ys), np.concatenate(ps)
                mae = np.abs(y_ - p_).mean()
                if best is None or mae < best[0]:
                    best = (mae, prm, _pi_quantiles(y_, p_), y_, p_)
            info["idw"] = {"params": best[1], "val_mae": best[0]}
            val_pred["idw"], val_y["idw"] = best[4], best[3]
            for s in test_s:
                t = p.sites.index(s)
                fold_preds.append(_frame(p, s, test_rows, B.idw_predict(p, t, vis_final, test_rows, best[1]["tau"]), "idw", fi, best[2]))

        for kind in [m for m in ("glm", "gbt") if m in models]:
            Xtr, ytr, _ = B.stack_rows(p, [p.sites.index(s) for s in train_s], vis_inner, tr_mask, max_rows, rng)
            Xva, yva, _ = B.stack_rows(p, [p.sites.index(s) for s in val_s], vis_inner, va_mask)
            grid = B.GLM_GRID if kind == "glm" else B.GBT_GRID
            best = None
            for prm in grid:
                m = B.make_model(kind, prm).fit(Xtr, ytr)
                pv = np.clip(m.predict(Xva), 0, None)
                mae = np.abs(yva - pv).mean()
                if best is None or mae < best[0]:
                    best = (mae, prm, _pi_quantiles(yva, pv), pv)
            info[kind] = {"params": best[1], "val_mae": best[0]}
            val_pred[kind], val_y[kind] = best[3], yva
            Xall, yall, _ = B.stack_rows(p, [p.sites.index(s) for s in remaining], vis_final, tr_mask, max_rows, rng)
            m = B.make_model(kind, best[1]).fit(Xall, yall)
            for s in test_s:
                t = p.sites.index(s)
                pr = np.clip(m.predict(B.design(p, t, vis_final, test_rows)), 0, None)
                fold_preds.append(_frame(p, s, test_rows, pr, kind, fi, best[2]))

        if "ens" in models:
            # Pre-registered blend of gbt and idw: the weight is chosen on the
            # 2024 validation sites only (inner models that never saw them),
            # then frozen and applied to the 2025 test predictions.
            assert np.array_equal(val_y["gbt"], val_y["idw"]), "validation rows must align"
            best = None
            for w in ENS_WEIGHTS:
                pv = w * val_pred["gbt"] + (1 - w) * val_pred["idw"]
                mae = np.abs(val_y["gbt"] - pv).mean()
                if best is None or mae < best[0]:
                    best = (mae, w, _pi_quantiles(val_y["gbt"], pv))
            info["ens"] = {"params": {"w_gbt": best[1]}, "val_mae": best[0]}
            byk = {(f.model.iloc[0], f.site.iloc[0]): f for f in fold_preds}
            for s in test_s:
                pr = best[1] * byk["gbt", s].pred.to_numpy() + (1 - best[1]) * byk["idw", s].pred.to_numpy()
                fold_preds.append(_frame(p, s, test_rows, pr, "ens", fi, best[2]))

        if "gnn" in models:
            cfg = gnn.GNNConfig(graph=gnn_graph, device=device)
            model, view, tinfo = gnn.train(p, cfg, set(E), train_s, val_s, verbose=False)
            vp = gnn.predict(model, p, cfg, view, val_s, C.TRAIN_END, C.VAL_END)
            vp["y"] = [p.Y[r, p.sites.index(s)] for r, s in zip(vp.row, vp.site)]
            vp = vp[np.isfinite(vp.y)]
            q = _pi_quantiles(vp.y.to_numpy(), vp.pred.to_numpy())
            info["gnn"] = {"best_epoch": tinfo["best_epoch"], "val_mae": float(np.abs(vp.y - vp.pred).mean()),
                           "val_mae_log": tinfo["best_val"]}
            if gnn_refit:
                model, view, _ = gnn.train(p, cfg, set(E), train_s + val_s, [], fixed_epochs=tinfo["best_epoch"], verbose=False)
            tp = gnn.predict(model, p, cfg, view, test_s, C.VAL_END, C.TEST_END)
            for s in test_s:
                d = tp[tp.site == s].sort_values("row")
                full = pd.Series(np.nan, index=test_rows)
                full.loc[d.row.to_numpy()] = d.pred.to_numpy()
                fold_preds.append(_frame(p, s, test_rows, full.to_numpy(), "gnn", fi, q))

        df = pd.concat(fold_preds, ignore_index=True)
        df.to_parquet(fpath)
        all_preds.append(df)
        info["seconds"] = round(time.time() - t0, 1)
        sel_log.append(info)
        vm = {k: round(v["val_mae"], 2) for k, v in info.items() if isinstance(v, dict) and "val_mae" in v}
        print(f"    val MAE {vm}  ({info['seconds']}s)", flush=True)
        with open(out_dir / "selection_log.jsonl", "a") as f:
            f.write(json.dumps(info, default=str) + "\n")

    preds = pd.concat(all_preds, ignore_index=True)
    preds.to_parquet(out_dir / "predictions.parquet")
    return preds
