"""Metrics, bootstrap comparisons, plots and the results report."""

from __future__ import annotations

import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config as C

MODEL_ORDER = ["idw", "glm", "gbt", "ens", "gnn"]
STADTTUNNEL_OPEN = pd.Timestamp("2025-05-22")


def _metrics(g: pd.DataFrame) -> pd.Series:
    e = g.pred - g.y
    return pd.Series({
        "n": len(g),
        "MAE": e.abs().mean(),
        "RMSE": np.sqrt((e**2).mean()),
        "bias": e.mean(),
        "WAPE": e.abs().sum() / max(g.y.sum(), 1e-9),
        "mean_obs": g.y.mean(),
    })


def evaluation_rows(preds: pd.DataFrame) -> pd.DataFrame:
    """Headline evaluation set: complete, non-DST-ambiguous, non-flagged hours
    (the `observed` mask) with a prediction from the model."""
    d = preds[preds.observed & preds.pred.notna()].copy()
    ts = d.ts_local
    cal = pd.read_parquet(C.PROCESSED / "calendar_hourly.parquet", columns=["ts_local", "workday", "peak"])
    d = d.merge(cal, on="ts_local", how="left")
    d["season"] = np.select([ts.dt.month.isin([12, 1, 2]).to_numpy(), ts.dt.month.isin([6, 7, 8]).to_numpy()],
                            ["winter", "summer"], "spring/autumn")
    d["daytype"] = np.where(d.workday, "workday", "weekend/holiday")
    d["peak"] = np.where(d.peak, "peak", "off-peak")
    d["stadttunnel"] = np.where(d.ts_local >= STADTTUNNEL_OPEN, "after 22 May 2025", "before")
    return d


def summarise(preds: pd.DataFrame, out_dir) -> dict:
    d = evaluation_rows(preds)
    models = [m for m in MODEL_ORDER if m in d.model.unique()]
    # only compare on hours where every model has a prediction
    key = ["site", "ts_local"]
    common = d.groupby(key).model.nunique() == len(models)
    d = d.set_index(key).loc[common[common].index].reset_index()

    per_site = d.groupby(["model", "site"]).apply(_metrics, include_groups=False).reset_index()
    macro = per_site.groupby("model")[["MAE", "RMSE", "bias", "WAPE"]].mean().reindex(models)
    pooled = d.groupby("model").apply(_metrics, include_groups=False).reindex(models)
    breakdown = {
        col: d.groupby([col, "model"]).apply(_metrics, include_groups=False)[["MAE", "WAPE", "bias"]].unstack("model")
        for col in ["season", "daytype", "peak", "stadttunnel"]
    }
    # daily totals on days with all 24 hours evaluated
    d["day"] = d.ts_local.dt.normalize()
    day = d.groupby(["model", "site", "day"]).agg(y=("y", "sum"), pred=("pred", "sum"), n=("y", "size"))
    day = day[day.n == 24].reset_index()
    daily = day.groupby("model").apply(_metrics, include_groups=False).reindex(models)
    cov = {}
    for lev in (80, 90):
        cov[lev] = d.groupby("model").apply(lambda g: ((g.y >= g[f"lo{lev}"]) & (g.y <= g[f"hi{lev}"])).mean(),
                                            include_groups=False).reindex(models)
    boot = block_bootstrap(d, models)

    out_dir.mkdir(parents=True, exist_ok=True)
    per_site.to_csv(out_dir / "metrics_per_site.csv", index=False)
    pooled.to_csv(out_dir / "metrics_pooled.csv")
    macro.to_csv(out_dir / "metrics_macro.csv")
    daily.to_csv(out_dir / "metrics_daily_totals.csv")
    for k, v in breakdown.items():
        v.to_csv(out_dir / f"metrics_by_{k}.csv")
    pd.DataFrame(cov).to_csv(out_dir / "interval_coverage.csv")
    boot.to_csv(out_dir / "bootstrap_vs_best_baseline.csv", index=False)
    _plots(d, day, per_site, models, out_dir)
    return {"per_site": per_site, "macro": macro, "pooled": pooled, "daily": daily,
            "breakdown": breakdown, "coverage": cov, "bootstrap": boot, "models": models}


def block_bootstrap(d: pd.DataFrame, models, n_boot: int = 1000, seed: int = C.SEED) -> pd.DataFrame:
    """Week-block bootstrap of pooled-MAE differences (model - reference).
    Reference = each other model; weeks are resampled with replacement."""
    rng = np.random.default_rng(seed)
    d = d.assign(week=d.ts_local.dt.isocalendar().week.astype(int), ae=(d.pred - d.y).abs())
    wk = d.pivot_table(index="week", columns="model", values="ae", aggfunc="sum")
    n = d[d.model == models[0]].groupby("week").size().reindex(wk.index)
    rows = []
    W = len(wk)
    idx = rng.integers(0, W, size=(n_boot, W))
    for a in models:
        for b in models:
            if a >= b:
                continue
            diff_w = (wk[a] - wk[b]).to_numpy()
            nn = n.to_numpy()
            est = diff_w.sum() / nn.sum()
            bs = diff_w[idx].sum(1) / nn[idx].sum(1)
            rows.append({"model_a": a, "model_b": b, "mae_diff_a_minus_b": est,
                         "ci95_lo": np.quantile(bs, 0.025), "ci95_hi": np.quantile(bs, 0.975)})
    return pd.DataFrame(rows)


def _plots(d, day, per_site, models, out_dir):
    colors = dict(zip(MODEL_ORDER, ["#8c8c8c", "#4c78a8", "#f58518", "#b279a2", "#54a24b"]))
    # measured vs estimated daily totals, small multiples
    sites = sorted(day.site.unique())
    ncol = 4
    nrow = int(np.ceil(len(sites) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 2.4 * nrow), sharex=True)
    for ax, s in zip(axes.flat, sites):
        g = day[day.site == s]
        obs = g[g.model == models[0]].sort_values("day")
        ax.plot(obs.day, obs.y, color="black", lw=1, label="measured")
        for m in models:
            gm = g[g.model == m].sort_values("day")
            ax.plot(gm.day, gm.pred, color=colors[m], lw=0.8, alpha=0.85, label=m)
        ax.set_title(s, fontsize=9)
        ax.tick_params(labelsize=7)
    for ax in list(axes.flat)[len(sites):]:
        ax.axis("off")
    axes.flat[0].legend(fontsize=7)
    fig.suptitle("2025 daily totals at held-out sites: measured vs reconstructed", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_dir / "daily_measured_vs_estimated.png", dpi=110)
    plt.close(fig)

    # per-site WAPE bars
    pv = per_site.pivot(index="site", columns="model", values="WAPE")[models]
    ax = pv.plot.bar(figsize=(12, 4), color=[colors[m] for m in models], width=0.8)
    ax.set_ylabel("WAPE (hourly)")
    ax.set_title("Per-site hourly WAPE, 2025, held-out sites")
    plt.tight_layout()
    plt.savefig(out_dir / "per_site_wape.png", dpi=110)
    plt.close()

    # map of site errors for the best model by macro WAPE
    best = pv.mean().idxmin()
    nodes = gpd.read_parquet(C.PROCESSED / "nodes.parquet")
    nodes = nodes[nodes.node_type == "sensor"].set_index("node_id")
    velonetz = gpd.read_file(C.RAW / "view_velonetz.geojson").to_crs(C.CRS_CH)
    fig, ax = plt.subplots(figsize=(8, 8))
    velonetz.plot(ax=ax, color="#cccccc", lw=0.5)
    velonetz[velonetz.kategorie == "Vorzugsroute"].plot(ax=ax, color="#9ecae1", lw=1)
    g = nodes.loc[pv.index]
    sc = ax.scatter(g.geometry.x, g.geometry.y, c=pv[best].values, cmap="viridis_r", s=90, edgecolor="k", zorder=3)
    for s, row in g.iterrows():
        ax.annotate(s.replace("VZS_", ""), (row.geometry.x, row.geometry.y), fontsize=7, xytext=(4, 4), textcoords="offset points")
    plt.colorbar(sc, ax=ax, shrink=0.6, label=f"hourly WAPE ({best})")
    ax.set_title(f"Held-out-site error map, 2025 ({best}); lines: Velonetz (blue = Vorzugsroute)")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(out_dir / "site_error_map.png", dpi=110)
    plt.close(fig)


def _fmt(df: pd.DataFrame, digits=2) -> str:
    return df.round(digits).to_markdown()


def write_report(res: dict, out_dir, tag: str, sel_log_path) -> str:
    models = res["models"]
    sel = [json.loads(line) for line in open(sel_log_path)] if sel_log_path.exists() else []
    val = pd.DataFrame([{m: s[m]["val_mae"] for m in models if m in s} for s in sel])
    val_mean = val.mean() if len(val) else pd.Series(dtype=float)
    boot = res["bootstrap"]
    ps = res["per_site"].pivot(index="site", columns="model", values="MAE")
    baselines = [m for m in models if m != "gnn"]
    lines = [f"# Held-out-counter backtest: `{tag}`", ""]
    lines += [
        "Retrospective **spatial reconstruction** of 2025 hourly bicycle passages at each held-out city "
        "counter from contemporaneous counts at the other counters, weather, calendar and network covariates. "
        "Raw recorded passages (no correction factors). Static current OSM network. Not a forecast.", "",
        f"Folds: {len(sel)} hold-out groups; evaluation hours: complete, non-DST-ambiguous, non-flagged; "
        "all models compared on identical site-hours.", "",
        "## Aggregate (pooled over all held-out site-hours)", _fmt(res["pooled"]), "",
        "## Macro average across sites", _fmt(res["macro"]), "",
        "## Daily totals (days with 24 evaluated hours)", _fmt(res["daily"]), "",
        "## Validation (2024, validation sites) MAE, mean over folds", _fmt(val_mean.to_frame("val_MAE")), "",
        "## Prediction-interval coverage (intervals from validation residuals)",
        _fmt(pd.DataFrame(res["coverage"]).rename(columns=lambda c: f"nominal {c}%"), 3), "",
        "## Week-block bootstrap of pooled MAE differences (95% CI)", _fmt(boot.set_index(["model_a", "model_b"])), "",
    ]
    for k, v in res["breakdown"].items():
        lines += [f"## By {k}", _fmt(v), ""]
    lines += ["## Per-site hourly MAE", _fmt(ps[models]), ""]

    if "gnn" in models and baselines:
        best_val_base = val_mean[baselines].idxmin() if len(val_mean) else baselines[0]
        row = boot[((boot.model_a == "gnn") & (boot.model_b == best_val_base)) |
                   ((boot.model_b == "gnn") & (boot.model_a == best_val_base))].iloc[0]
        sign = 1 if row.model_a == "gnn" else -1
        diff, lo, hi = sign * row.mae_diff_a_minus_b, *(sorted([sign * row.ci95_lo, sign * row.ci95_hi]))
        wins = int((ps["gnn"] < ps[best_val_base]).sum())
        val_better = len(val_mean) and val_mean["gnn"] < val_mean[best_val_base]
        test_better = hi < 0
        consistent = wins >= 0.5 * len(ps)
        verdict = "SELECT GNN" if (val_better and test_better and consistent) else "DO NOT SELECT GNN (keep best baseline)"
        lines += [
            "## Decision rule", "",
            f"Best baseline by validation MAE: **{best_val_base}**.",
            f"- GNN better on validation: {bool(val_better)} (GNN {val_mean.get('gnn', np.nan):.2f} vs {val_mean.get(best_val_base, np.nan):.2f})",
            f"- GNN - {best_val_base} pooled test MAE: {diff:+.2f} (95% week-block CI {lo:+.2f} .. {hi:+.2f})",
            f"- GNN wins on {wins}/{len(ps)} held-out sites",
            f"- **Verdict: {verdict}**", "",
        ]
    worst = ps.min(axis=1).sort_values(ascending=False).head(5)
    lines += ["## Difficult sites (highest best-model MAE)", _fmt(worst.to_frame("best MAE")), ""]
    lines += ["![daily](daily_measured_vs_estimated.png)", "", "![wape](per_site_wape.png)", "",
              "![map](site_error_map.png)", ""]
    text = "\n".join(lines)
    (out_dir / "report.md").write_text(text)
    return text


def run(tag: str) -> str:
    out = C.OUTPUTS / "backtest" / tag
    preds = pd.read_parquet(out / "predictions.parquet")
    res = summarise(preds, out)
    corrected_layer(preds, out)
    return write_report(res, out, tag, out / "selection_log.jsonl")


def corrected_layer(preds: pd.DataFrame, out_dir) -> None:
    """Reporting layer only: apply the city's documented correction factor of
    the device active at each hour to both measured and estimated values."""
    dev = pd.read_parquet(C.PROCESSED / "site_devices.parquet")
    counts = pd.read_parquet(C.PROCESSED / "counts_hourly.parquet", columns=["site_id", "standort_id", "ts_local"])
    counts = counts[counts.ts_local >= preds.ts_local.min()]
    f = counts.merge(dev[["standort_id", "correction_factor"]], on="standort_id")
    f = f.rename(columns={"site_id": "site"})[["site", "ts_local", "correction_factor"]]
    c = preds.merge(f, on=["site", "ts_local"], how="left")
    c["y_corrected"] = c.y * c.correction_factor
    c["pred_corrected"] = c.pred * c.correction_factor
    c[["fold", "site", "model", "ts_local", "correction_factor", "y_corrected", "pred_corrected"]].to_parquet(
        out_dir / "predictions_corrected_reporting_layer.parquet")
