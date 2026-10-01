"""Descriptive historical analysis on a stable-site panel.

Weather- and calendar-adjusted annual indices (Poisson GLM on daily totals
with site fixed effects), weekday/weekend and peak shares, and per-site
adjusted annual levels, overlaid with the event ledger. These are
*descriptive* comparisons: counter interpolation cannot identify induced
cycling or the causal effect of a route. Device swaps and coverage changes
are handled by using device-period fixed effects in the per-site model.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from . import config as cfg

START_YEAR, END_YEAR = 2017, 2025
MIN_DAYS_PER_YEAR = 250


def daily_panel() -> pd.DataFrame:
    c = pd.read_parquet(cfg.PROCESSED / "counts_hourly.parquet",
                        columns=["site_id", "standort_id", "ts_local", "raw_total", "observed"])
    c = c[(c.ts_local.dt.year >= START_YEAR) & (c.ts_local.dt.year <= END_YEAR)]
    c["day"] = c.ts_local.dt.normalize()
    cal = pd.read_parquet(cfg.PROCESSED / "calendar_hourly.parquet")
    c = c.merge(cal[["ts_local", "peak"]], on="ts_local", how="left")
    c["peak_count"] = np.where(c.peak, c.raw_total, 0)
    g = c.groupby(["site_id", "standort_id", "day"]).agg(
        total=("raw_total", "sum"), peak_total=("peak_count", "sum"), n_obs=("observed", "sum"), n=("observed", "size"))
    # full days only (23/25 h on DST days are excluded rather than rescaled)
    d = g[(g.n_obs == 24) & (g.n == 24)].reset_index()

    w = pd.read_parquet(cfg.PROCESSED / "weather_hourly.parquet")
    w["day"] = w.ts_utc.dt.tz_convert(cfg.TZ).dt.tz_localize(None).dt.normalize()
    wd = w.groupby("day").agg(temp=("temp_c", "mean"), precip=("precip_mm", "sum"), sun=("sunshine_min", "sum"))
    cd = cal.assign(day=cal.ts_local.dt.normalize()).groupby("day").agg(
        dow=("dow", "first"), holiday=("public_holiday", "max"), school=("school_holiday", "max"), month=("month", "first"))
    d = d.merge(wd, on="day").merge(cd, on="day")
    d["year"] = d.day.dt.year
    d["weekend"] = (d.dow >= 5) | d.holiday
    return d


def stable_sites(d: pd.DataFrame) -> list[str]:
    days = d.groupby(["site_id", "year"]).size().unstack(fill_value=0)
    years = list(range(START_YEAR, END_YEAR + 1))
    days = days.reindex(columns=years, fill_value=0)
    return list(days.index[(days >= MIN_DAYS_PER_YEAR).all(axis=1)])


def run() -> None:
    out = cfg.OUTPUTS / "history"
    out.mkdir(parents=True, exist_ok=True)
    d = daily_panel()
    stable = stable_sites(d)
    print(f"  stable panel {START_YEAR}-{END_YEAR} (>= {MIN_DAYS_PER_YEAR} full days each year): {stable}")
    formula = ("total ~ C(year) + C(standort_id) + temp + I(temp**2) + np.log1p(precip) + sun + C(dow) "
               "+ holiday + school + C(month)")
    res = {}
    if stable:
        s = d[d.site_id.isin(stable)]
        m = smf.glm(formula, s, family=sm.families.Poisson()).fit(cov_type="HC1")
        yrs = sorted(s.year.unique())
        idx = [1.0] + [np.exp(m.params[f"C(year)[T.{y}]"]) for y in yrs[1:]]
        ci = [(1.0, 1.0)] + [tuple(np.exp(m.conf_int().loc[f"C(year)[T.{y}]"])) for y in yrs[1:]]
        res = pd.DataFrame({"year": yrs, "adjusted_index": idx, "ci_lo": [c[0] for c in ci], "ci_hi": [c[1] for c in ci]})
        res.to_csv(out / "stable_panel_annual_index.csv", index=False)
        shares = s.groupby("year").apply(lambda g: pd.Series({
            "weekend_share_of_daily_mean": g[g.weekend].total.mean() / g.total.mean(),
            "peak_share": g.peak_total.sum() / g.total.sum(),
        }), include_groups=False)
        shares.to_csv(out / "stable_panel_shares.csv")

    # per-site adjusted annual levels (device-period fixed effects absorb swaps)
    rows = []
    for site, g in d.groupby("site_id"):
        yrs = g.groupby("year").size()
        yrs = yrs[yrs >= 120].index
        g = g[g.year.isin(yrs)]
        if g.year.nunique() < 2:
            continue
        f = formula if g.standort_id.nunique() > 1 else formula.replace(" + C(standort_id)", "")
        try:
            m = smf.glm(f, g, family=sm.families.Poisson()).fit()
        except Exception:
            continue
        base = sorted(g.year.unique())[0]
        for y in sorted(g.year.unique()):
            rows.append({"site": site, "year": y, "index_vs_first_year": 1.0 if y == base else float(np.exp(m.params.get(f"C(year)[T.{y}]", np.nan))),
                         "base_year": base, "n_days": int((g.year == y).sum()),
                         "devices": g.standort_id.nunique()})
    per_site = pd.DataFrame(rows)
    per_site.to_csv(out / "per_site_adjusted_annual_index.csv", index=False)

    ev = pd.read_csv(cfg.EVENTS_DIR / "events.csv")
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
    if len(res):
        ax = axes[0]
        ax.errorbar(res.year, res.adjusted_index, yerr=[res.adjusted_index - res.ci_lo, res.ci_hi - res.adjusted_index],
                    marker="o", capsize=3)
        ax.axhline(1, color="grey", lw=0.5)
        ax.set_title(f"Stable-site panel ({len(stable)} sites): weather/calendar-adjusted annual index")
        for _, e in ev[ev.type.isin(["physical", "policy"])].iterrows():
            yr = str(e.effective_date)[:4]
            if yr.isdigit() and START_YEAR <= int(yr) <= END_YEAR:
                ax.axvline(int(yr), color="#d62728", lw=0.6, alpha=0.5)
                ax.text(int(yr), ax.get_ylim()[1], e.event_id, fontsize=7, rotation=90, va="top")
    ax = axes[1]
    for site, g in per_site.groupby("site"):
        if g.year.nunique() >= 3:
            ax.plot(g.year, g.index_vs_first_year, marker=".", lw=1, label=site.replace("VZS_", ""))
    ax.set_yscale("log")
    ax.set_title("Per-site adjusted annual level vs first year (log)")
    ax.legend(fontsize=6, ncol=3)
    fig.tight_layout()
    fig.savefig(out / "history.png", dpi=110)
    plt.close(fig)

    lines = ["# Historical counts: descriptive stable-panel analysis", "",
             "Weather- and calendar-adjusted Poisson GLM on full-day totals. Descriptive only: "
             "no causal claims about routes or induced cycling. Static-current-network caveat does not apply "
             "here (no network used). Pandemic periods are not modelled separately; read 2020-2021 with care.", "",
             f"Stable sites ({START_YEAR}-{END_YEAR}, >= {MIN_DAYS_PER_YEAR} full days/year): {', '.join(stable) or 'none'}", ""]
    if len(res):
        lines += ["## Adjusted annual index (first year = 1)", res.round(3).to_markdown(index=False), "",
                  "## Shares", shares.round(3).to_markdown(), ""]
    for sid in ["VZS_BASL", "VZS_LANN", "VZS_LANS", "VZS_LAFN", "VZS_LAFS"]:
        g = per_site[per_site.site == sid]
        if len(g):
            lines += [f"### {sid}", g.round(3).to_markdown(index=False), ""]
    lines += ["![history](history.png)", ""]
    (out / "history.md").write_text("\n".join(lines))
    print(f"  wrote {out / 'history.md'}")
