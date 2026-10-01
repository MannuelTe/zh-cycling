"""Headline numbers shared by the paper and the summary page.

`numbers()` reads the pipeline outputs and returns a flat dict of formatted
values. Text templates reference them as {{key}}; `fill()` substitutes them
and fails loudly on unknown keys, so prose can never drift from the results.
"""

from __future__ import annotations

import json
import re

import pandas as pd

from . import config as C

OUT = C.ROOT / "outputs"
OUT6 = C.ROOT / "outputs_canton6"
CLAIM = OUT / "claims" / "c2_doubling"


def _pooled(path, model):
    return pd.read_csv(path / "metrics_pooled.csv").set_index("model").loc[model]


def numbers() -> dict[str, str]:
    R = json.loads((CLAIM / "result.json").read_text())
    S = R["scenarios"]
    comp = R["composition"]
    loo_city = pd.read_csv(CLAIM / "city_median_loo.csv", index_col=0).iloc[:, 0]
    loo_fp = R["fixed_panel_leave_one_out"]
    an = pd.read_csv(CLAIM / "anomaly_impacts.csv")
    andr = an[an.anomaly.str.startswith("Andreasstrasse")].iloc[0]
    hist = pd.read_csv(OUT / "history" / "stable_panel_annual_index.csv").set_index("year")

    cb, c6, vn = OUT / "backtest" / "blend", OUT6 / "backtest" / "blend", OUT6 / "backtest" / "blend_velonetz"
    gnn_s = _pooled(OUT / "backtest" / "sensor", "gnn")
    gnn_i = _pooled(OUT / "backtest" / "intersection", "gnn")
    gbt_s = _pooled(OUT / "backtest" / "sensor", "gbt")
    ens_c, ens_6, ens_v = _pooled(cb, "ens"), _pooled(c6, "ens"), _pooled(vn, "ens")
    daily6 = pd.read_csv(c6 / "metrics_daily_totals.csv").set_index("model").loc["ens"]
    cov6 = pd.read_csv(c6 / "interval_coverage.csv").set_index("model").loc["ens"]
    covc = pd.read_csv(cb / "interval_coverage.csv").set_index("model").loc["ens"]

    x = lambda v, d=2: f"×{v:.{d}f}"
    p = lambda v, d=2: f"{v:.{d}f}"
    pct = lambda v, d=0: f"{100 * v:.{d}f}%"
    n = {
        # claim 2
        "claim.official_ratio": x(R["official_ratio"]),
        "claim.official_2024": "193.4",
        "claim.city_median": x(R["city_style_median_ratio"]),
        "claim.threshold": x(1.8, 1),
        "claim.confidence": p(R["confidence"]),
        "claim.conf_lo": p(R["confidence_range_across_scenarios"][0]),
        "claim.conf_hi": p(R["confidence_range_across_scenarios"][1]),
        "claim.n_panel": str(len(R["fixed_panel_sites"])),
        "claim.n_2012": str(comp["n_base"]),
        "claim.n_2024": str(comp["n_target"]),
        "claim.unadjusted": x(R["fixed_panel_unadjusted_ratio"]),
        "claim.loo_fp_lo": x(min(loo_fp.values())),
        "claim.loo_fp_hi": x(max(loo_fp.values())),
        "claim.without_andr": x(loo_fp["VZS_ANDR"]),
        "claim.andr_break": x(andr.fixed_panel_ratio),
        "claim.loo_city_lo": x(loo_city.min()),
        "claim.loo_city_hi": x(loo_city.max()),
        "claim.mix_all": x(comp["all"]),
        "claim.mix_stayers": x(comp["stayers"]),
        "claim.mix_factor": x(comp["mix"]),
        "claim.best_rmse": p(min(R["reproduction_rmse_index_points"].values()), 1),
    }
    for k, v in S.items():
        n[f"claim.{k}.point"] = x(v["point"])
        n[f"claim.{k}.ci_lo"] = x(v["ci95"][0])
        n[f"claim.{k}.ci_hi"] = x(v["ci95"][1])
        n[f"claim.{k}.p18"] = p(v["p_ge_1.800"])
        n[f"claim.{k}.p15"] = p(v["p_ge_1.500"])
    n.update({
        # reconstruction model
        "model.mae_c6": p(ens_6.MAE, 1),
        "model.mae_city": p(ens_c.MAE, 1),
        "model.mae_velonetz": p(ens_v.MAE, 1),
        "model.wape_c6": pct(ens_6.WAPE),
        "model.daily_wape_c6": pct(daily6.WAPE),
        "model.bias_pct": pct(abs(ens_6.bias) / ens_6.mean_obs),  # estimates run low by this share
        "model.cov90_c6": pct(cov6["90"]),
        "model.cov90_city": pct(covc["90"]),
        "model.gnn_gap_lo": p(min(gnn_s.MAE, gnn_i.MAE) - gbt_s.MAE, 1),
        "model.gnn_gap_hi": p(max(gnn_s.MAE, gnn_i.MAE) - gbt_s.MAE, 1),
        "model.mean_obs": p(ens_6.mean_obs, 0),
        # history
        "history.index_2025": p(hist.loc[2025, "adjusted_index"]),
        "history.index_2021": p(hist.loc[2021, "adjusted_index"]),
        "history.index_2020": p(hist.loc[2020, "adjusted_index"]),
    })
    return n


def fill(text: str, nums: dict[str, str] | None = None) -> str:
    nums = numbers() if nums is None else nums
    keys = set(re.findall(r"\{\{\s*([\w.]+)\s*\}\}", text))
    missing = keys - set(nums)
    if missing:
        raise KeyError(f"unknown number keys in template: {sorted(missing)}")
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", lambda m: nums[m.group(1)], text)


if __name__ == "__main__":  # pragma: no cover
    for k, v in numbers().items():
        print(f"{k:28s} {v}")
