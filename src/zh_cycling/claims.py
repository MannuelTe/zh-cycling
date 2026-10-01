"""Reconstruct the city's published cycling claims from the open counter data.

Claim 2 ("cycling nearly doubled 2012-2024"): the city's indexed traffic
development (VER100T1001, table T_1 "Stadtgebiet", 2012 = 100) uses the
average daily traffic over *all* city cycling counters active in each year,
so the counter set changes over time. This module

1. tries to reproduce the official index from the open counts (method check),
2. re-estimates growth like-for-like: a fixed panel of sites observed in both
   2012 and 2024, and a chain-linked index over consecutive-year panels, both
   adjusted for weather and calendar (Poisson GLM on daily totals),
3. turns the estimates into a confidence number with a two-stage cluster
   bootstrap (sites, then ISO-week blocks), under four scenarios,
4. inventories anomalies (device swaps, level jumps, disruptions) and measures
   how much each moves the 2012->2024 ratio.

Test definition, fixed before any estimate was computed: "nearly doubled"
means a true 2012->2024 growth ratio of at least NEARLY_DOUBLED. The headline
confidence is P(ratio >= NEARLY_DOUBLED) for the fixed panel on raw counts
with coverage-period fixed effects (scenario S1).

All outputs go to OUTPUTS/claims/c2_doubling/. Run with the default ("city")
variant: cantonal stations are not part of the city's index.
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from . import config as cfg

# Official values as published in VER100T1001_Verkehrsentwicklung.xlsx, sheet
# "Stadtgebiet", row "Veloverkehr" (Statistik Stadt Zürich, file created
# 27.07.2026, source Tiefbauamt). The analysis uses this vintage; if the
# downloaded workbook differs, a warning is printed and the vintage is kept.
OFFICIAL_VELO_INDEX = {
    2012: 100.0, 2013: 101.0, 2014: 114.6, 2015: 128.5, 2016: 126.8, 2017: 136.2, 2018: 150.3,
    2019: 156.6, 2020: 169.9, 2021: 163.5, 2022: 184.4, 2023: 188.0, 2024: 193.4, 2025: 207.6,
}
OFFICIAL_XLSX = "VER100T1001_Verkehrsentwicklung.xlsx"
BASE, TARGET = 2012, 2024
NEARLY_DOUBLED = 1.8
THRESHOLDS = (1.5, NEARLY_DOUBLED, OFFICIAL_VELO_INDEX[TARGET] / 100)
MIN_DAYS = 250
N_BOOT = 1000
# Device swaps treated as level breaks in scenario S3. The swap-step test
# (device_swap_steps.csv) puts HOFW 2019-03-14 at x1.31 relative to the other
# sites. ANDR 2019-10-11 follows a 7-month outage and cannot be tested
# directly; its level relative to the median counter steps up about x1.5
# across the swap while its direction split and daily profile are unchanged.
FLAGGED_BREAKS = {"VZS_HOFW": ["2019-03-14"], "VZS_ANDR": ["2019-10-11"]}
# Site-years with temporary disruptions (roadworks / outages that revert).
DISRUPTED_SITE_YEARS = [("VZS_SIHL", 2020), ("VZS_SIHL", 2021), ("VZS_MYTH", 2022), ("VZS_SCHE", 2019), ("VZS_BINZ", 2022)]
COVARIATES = "temp + I(temp**2) + np.log1p(precip) + sun + C(dow) + holiday + school + C(month)"
STEP_FLAG = 1.25  # relative level change flagged as a jump (x1.25 or 1/1.25)


def out_dir():
    p = cfg.OUTPUTS / "claims" / "c2_doubling"
    p.mkdir(parents=True, exist_ok=True)
    return p


def official_index() -> dict[int, float]:
    """Official index from the downloaded workbook, checked against the vintage."""
    path = cfg.RAW / OFFICIAL_XLSX
    if not path.exists():
        print(f"  ! {OFFICIAL_XLSX} not downloaded; using the recorded vintage")
        return dict(OFFICIAL_VELO_INDEX)
    df = pd.read_excel(path, sheet_name="Stadtgebiet", header=None)
    head = df.index[df.iloc[:, 0].astype(str).str.strip() == "Verkehr"][0]
    row = df.index[df.iloc[:, 0].astype(str).str.strip() == "Veloverkehr"][0]
    years = df.iloc[head, 1:].dropna().astype(int).tolist()
    vals = df.iloc[row, 1:1 + len(years)].astype(float).tolist()
    live = dict(zip(years, vals))
    diff = {y: (live.get(y), v) for y, v in OFFICIAL_VELO_INDEX.items() if live.get(y) is None or abs(live[y] - v) > 0.05}
    if diff:
        print(f"  ! official workbook differs from the analysed vintage: {diff}")
    return dict(OFFICIAL_VELO_INDEX)


def daily_panel(start: int = 2011, end: int = 2025, breaks: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """Full-day totals per site with weather, calendar, correction factor and
    coverage period (consecutive device periods sharing a correction factor)."""
    c = pd.read_parquet(cfg.PROCESSED / "counts_hourly.parquet",
                        columns=["site_id", "standort_id", "ts_local", "raw_total", "observed"])
    c = c[(c.ts_local.dt.year >= start) & (c.ts_local.dt.year <= end)]
    c["day"] = c.ts_local.dt.normalize()
    g = c.groupby(["site_id", "standort_id", "day"]).agg(
        total=("raw_total", "sum"), n_obs=("observed", "sum"), n=("observed", "size")).reset_index()
    d = g[(g.n_obs == 24) & (g.n == 24)].drop(columns=["n_obs", "n"])

    dev = pd.read_parquet(cfg.PROCESSED / "site_devices.parquet").sort_values(["site_id", "valid_from"])
    dev["cf"] = dev.correction_factor.fillna(1.0)
    dev["period"] = dev.groupby("site_id").cf.transform(lambda s: (s != s.shift()).cumsum())
    dev["coverage_id"] = dev.site_id + "#" + dev.period.astype(str)
    d = d.merge(dev[["standort_id", "cf", "coverage_id"]], on="standort_id", how="left")
    d["corrected"] = d.total * d.cf

    w = pd.read_parquet(cfg.PROCESSED / "weather_hourly.parquet")
    w["day"] = w.ts_utc.dt.tz_convert(cfg.TZ).dt.tz_localize(None).dt.normalize()
    wd = w.groupby("day").agg(temp=("temp_c", "mean"), precip=("precip_mm", "sum"), sun=("sunshine_min", "sum"))
    cal = pd.read_parquet(cfg.PROCESSED / "calendar_hourly.parquet")
    cd = cal.assign(day=cal.ts_local.dt.normalize()).groupby("day").agg(
        dow=("dow", "first"), holiday=("public_holiday", "max"), school=("school_holiday", "max"), month=("month", "first"))
    d = d.merge(wd, on="day").merge(cd, on="day")
    d["year"] = d.day.dt.year
    d["week"] = d.day.dt.strftime("%G-%V")
    for site, dates in (breaks or {}).items():
        k = sum((d.day >= pd.Timestamp(x)).astype(int) for x in dates)
        d.loc[d.site_id == site, "coverage_id"] += "|b" + k[d.site_id == site].astype(str)
    return d


def site_years(d: pd.DataFrame, min_days: int = MIN_DAYS) -> pd.DataFrame:
    sy = d.groupby(["site_id", "year"]).agg(raw=("total", "mean"), corrected=("corrected", "mean"),
                                           days=("total", "size")).reset_index()
    return sy[sy.days >= min_days]


# --------------------------------------------------------------------------
# 1. method check: can the official index be reproduced?
# --------------------------------------------------------------------------
def official_variants(d: pd.DataFrame, official: dict[int, float]) -> pd.DataFrame:
    yrs = sorted(official)
    d = d[d.year.isin(yrs)]
    sy_all = site_years(d, 1).set_index(["site_id", "year"])
    sy = site_years(d).set_index(["site_id", "year"])
    out = pd.DataFrame(index=yrs)
    out["official"] = [official[y] for y in yrs]
    out["pooled_site_days_raw"] = d.groupby("year").total.mean()
    out["pooled_site_days_corrected"] = d.groupby("year").corrected.mean()
    for name, t in (("", sy_all), ("_250d", sy)):
        for col in ("raw", "corrected"):
            out[f"mean_of_site_means_{col}{name}"] = t.groupby("year")[col].mean()
            out[f"median_of_site_means_{col}{name}"] = t.groupby("year")[col].median()
    out["n_sites"] = sy_all.groupby("year").size()
    out["n_sites_250d"] = sy.groupby("year").size()
    for col in out.columns:
        if col.startswith(("pooled", "mean_of", "median_of")):
            out[col] = 100 * out[col] / out.loc[BASE, col]
    return out


# --------------------------------------------------------------------------
# 2. like-for-like estimates
# --------------------------------------------------------------------------
def _year_effects(df: pd.DataFrame, y: str, fe: str) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = smf.glm(f"{y} ~ C(year) + C({fe}) + {COVARIATES}", df, family=sm.families.Poisson()).fit()
    yrs = sorted(df.year.unique())
    return pd.Series({yr: (0.0 if yr == yrs[0] else m.params.get(f"C(year)[T.{yr}]", np.nan)) for yr in yrs})


def _year_ratio(df: pd.DataFrame, y: str, fe: str, a: int, b: int) -> float:
    e = _year_effects(df, y, fe)
    return float(np.exp(e[b] - e[a]))


def fixed_panel_sites(d: pd.DataFrame) -> list[str]:
    days = d.groupby(["site_id", "year"]).size().unstack(fill_value=0)
    return sorted(days.index[(days.get(BASE, 0) >= MIN_DAYS) & (days.get(TARGET, 0) >= MIN_DAYS)])


def fixed_panel(d: pd.DataFrame, sites: list[str], corrected: bool, end: int = TARGET) -> float:
    s = d[d.site_id.isin(sites) & d.year.between(BASE, end)]
    if corrected:
        return _year_ratio(s.assign(y=s.corrected.round()), "y", "site_id", BASE, TARGET)
    return _year_ratio(s, "total", "coverage_id", BASE, TARGET)


def fixed_panel_series(d: pd.DataFrame, sites: list[str], end: int = 2025) -> pd.Series:
    """Adjusted annual index of the fixed panel (fit over BASE..end)."""
    s = d[d.site_id.isin(sites) & d.year.between(BASE, end)]
    e = _year_effects(s, "total", "coverage_id")
    return np.exp(e - e[BASE])


def chain_linked(d: pd.DataFrame, sites=None) -> tuple[float, pd.DataFrame]:
    """Product of consecutive-year adjusted ratios over sites with >= MIN_DAYS
    full days in both years (coverage-period fixed effects, raw counts). Years
    in which a site has an outage drop it from the adjacent links."""
    days = d.groupby(["site_id", "year"]).size().unstack(fill_value=0)
    steps, ratio = [], 1.0
    for a in range(BASE, TARGET):
        ok = days.index[(days.get(a, 0) >= MIN_DAYS) & (days.get(a + 1, 0) >= MIN_DAYS)]
        if sites is not None:
            ok = [s for s in ok if s in set(sites)]
        if len(ok) == 0:
            raise ValueError(f"no sites for {a}->{a + 1}")
        s = d[d.site_id.isin(ok) & d.year.isin([a, a + 1])]
        r = _year_ratio(s, "total", "coverage_id", a, a + 1)
        ratio *= r
        steps.append({"from": a, "to": a + 1, "n_sites": len(ok), "ratio": r, "cumulative": ratio})
    return ratio, pd.DataFrame(steps)


def _resample(d: pd.DataFrame, sites: list[str], rng: np.random.Generator) -> pd.DataFrame:
    """Two-stage cluster bootstrap: sites with replacement, then ISO-week blocks."""
    parts = []
    for k, s in enumerate(rng.choice(sites, size=len(sites), replace=True)):
        q = d[d.site_id == s]
        parts.append(q.assign(site_id=f"{s}~{k}", coverage_id=q.coverage_id + f"~{k}"))
    b = pd.concat(parts)
    weeks = b.week.unique()
    pick = pd.Series(rng.choice(weeks, size=len(weeks), replace=True)).value_counts()
    return b.merge(pick.rename("w").rename_axis("week").reset_index(), on="week").loc[lambda x: x.index.repeat(x.w)]


def bootstrap_fixed(d: pd.DataFrame, sites: list[str], corrected: bool, n: int = N_BOOT, seed: int = cfg.SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    s = d[d.site_id.isin(sites) & d.year.between(BASE, TARGET)]
    out = []
    for i in range(n):
        b = _resample(s, sites, rng)
        try:
            out.append(_year_ratio(b.assign(y=b.corrected.round()), "y", "site_id", BASE, TARGET) if corrected
                       else _year_ratio(b, "total", "coverage_id", BASE, TARGET))
        except Exception:  # degenerate draw (e.g. singular design); kept as NaN and reported
            out.append(np.nan)
        if (i + 1) % 100 == 0:
            print(f"    bootstrap {i + 1}/{n}")
    return np.array(out)


def bootstrap_chain(d: pd.DataFrame, n: int, seed: int = cfg.SEED + 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sites = sorted(d.site_id.unique())
    out = []
    for i in range(n):
        try:
            out.append(chain_linked(_resample(d, sites, rng))[0])
        except Exception:  # a resample with no site in some year
            out.append(np.nan)
        if (i + 1) % 50 == 0:
            print(f"    chain bootstrap {i + 1}/{n}")
    return np.array(out)


# --------------------------------------------------------------------------
# 3. anomalies
# --------------------------------------------------------------------------
def device_swap_steps(d: pd.DataFrame, window_days: int = 120) -> pd.DataFrame:
    """Level change at each device swap relative to the median change of all
    other sites over the same windows (difference in log daily totals)."""
    dev = pd.read_parquet(cfg.PROCESSED / "site_devices.parquet").sort_values(["site_id", "valid_from"])
    lg = d.assign(l=np.log1p(d.total))
    rows = []
    for s, q in dev.groupby("site_id"):
        q = q.reset_index(drop=True)
        for i in range(1, len(q)):
            t = q.valid_from[i]
            lo, hi = t - pd.Timedelta(days=window_days), t + pd.Timedelta(days=window_days)
            me = lg[lg.site_id == s]
            sb, sa = me[(me.day >= lo) & (me.day < t)], me[(me.day >= t) & (me.day < hi)]
            if len(sb) < 30 or len(sa) < 30:
                rows.append({"site": s, "swap": t.date(), "device": q.device_id[i], "cf_before": q.correction_factor[i - 1],
                             "cf_after": q.correction_factor[i], "step_x": np.nan, "testable": False})
                continue
            oth = lg[lg.site_id != s]
            ob = oth[(oth.day >= lo) & (oth.day < t)].groupby("site_id").l.mean()
            oa = oth[(oth.day >= t) & (oth.day < hi)].groupby("site_id").l.mean()
            common = ob.index.intersection(oa.index)
            rel = (sa.l.mean() - sb.l.mean()) - np.median(oa[common] - ob[common])
            rows.append({"site": s, "swap": t.date(), "device": q.device_id[i], "cf_before": q.correction_factor[i - 1],
                         "cf_after": q.correction_factor[i], "step_x": float(np.exp(rel)), "testable": True})
    return pd.DataFrame(rows)


def level_jumps(d: pd.DataFrame, min_days: int = 150) -> pd.DataFrame:
    """Year-to-year jumps in each site's level relative to the median site."""
    sy = site_years(d, min_days)
    L = np.log(sy.pivot(index="site_id", columns="year", values="raw"))
    rel = L - L.median()
    rows = []
    for s in rel.index:
        r = rel.loc[s].dropna()
        yrs = list(r.index)
        for a, b in zip(yrs[:-1], yrs[1:]):
            step = r[b] - r[a]
            if abs(step) > np.log(STEP_FLAG):
                nxt = [y for y in yrs if y > b][:1]
                rows.append({"site": s, "from": a, "to": b, "rel_step_x": float(np.exp(step)),
                             "reverts_next_year": bool(nxt) and abs(r[nxt[0]] - r[a]) < np.log(1.15)})
    return pd.DataFrame(rows)


def anomaly_impacts(d: pd.DataFrame, sites: list[str]) -> pd.DataFrame:
    """Effect of handling each anomaly differently on the S1 ratio and on the
    city-style median ratio. Groups: A measurement breaks, B temporary
    disruptions, C city-wide events, D real local change, E counter mix."""
    base = fixed_panel(d, sites, False)
    sy = site_years(d)

    def med(excl=()):
        q = sy[~sy.site_id.isin(excl)]
        return float(q[q.year == TARGET].corrected.median() / q[q.year == BASE].corrected.median())

    def drop(df, pairs):
        m = np.zeros(len(df), bool)
        for s, y in pairs:
            m |= ((df.site_id == s) & (df.year == y)).to_numpy()
        return df[~m]

    flat = d.assign(coverage_id=d.site_id)
    rows = [
        ("A", "Andreasstrasse device swap Oct 2019 as a break", "VZS_ANDR", "new device model after a 7-month outage; level about x1.5 vs median counter",
         fixed_panel(daily_panel(breaks={"VZS_ANDR": FLAGGED_BREAKS["VZS_ANDR"]}), sites, False), med(["VZS_ANDR"])),
        ("A", "Hofwiesenstrasse device swap Mar 2019 as a break", "VZS_HOFW", "level x1.31 vs other counters at the swap",
         fixed_panel(daily_panel(breaks={"VZS_HOFW": FLAGGED_BREAKS["VZS_HOFW"]}), sites, False), med(["VZS_HOFW"])),
        ("A", "Both 2019 swaps as breaks (scenario S3)", "VZS_ANDR, VZS_HOFW", "",
         fixed_panel(daily_panel(breaks=FLAGGED_BREAKS), sites, False), np.nan),
        ("A", "Correction-factor changes not split into periods", "VZS_MUEH 2023, VZS_MYTH 2022, VZS_SIHL 2022", "handling choice",
         fixed_panel(flat, sites, False), np.nan),
        ("A", "Device or factor steps at counters added later", "VZS_SCHU, VZS_LIMC, VZS_BUCH, VZS_TOED, VZS_HARN", "not in the fixed panel",
         np.nan, med(["VZS_SCHU", "VZS_LIMC", "VZS_BUCH", "VZS_TOED", "VZS_HARN"])),
        ("B", "Roadworks and outage years dropped", ", ".join(f"{s} {y}" for s, y in DISRUPTED_SITE_YEARS), "dips that revert",
         fixed_panel(drop(d, DISRUPTED_SITE_YEARS), sites, False), np.nan),
        ("C", "COVID years 2020-21 dropped", "all", "surge then partial reversal",
         fixed_panel(d[~d.year.isin([2020, 2021])], sites, False), np.nan),
        ("D", "Gradual ramps treated as breaks (wrong in principle)", "VZS_ANDR 2014-16, VZS_MUEH 2014-15", "growth concentrated at few counters",
         fixed_panel(daily_panel(breaks={"VZS_ANDR": ["2014-04-01", "2015-04-01", FLAGGED_BREAKS["VZS_ANDR"][0]],
                                         "VZS_MUEH": ["2015-01-01"]}), sites, False), np.nan),
        ("D", "Documented route effects excluded", "VZS_BASL, VZS_LANN, VZS_LANS, VZS_LAFN, VZS_LAFS", "priority route 2023; shift to roadway 2022",
         np.nan, med(["VZS_BASL", "VZS_LANN", "VZS_LANS", "VZS_LAFN", "VZS_LAFS"])),
        ("D", "Unexplained persistent step without device change excluded", "VZS_TALS", "x2.4 in 2022",
         np.nan, med(["VZS_TALS"])),
    ]
    out = pd.DataFrame(rows, columns=["group", "anomaly", "sites", "mechanism", "fixed_panel_ratio", "city_median_if_excluded"])
    out["fixed_panel_change_pct"] = 100 * (out.fixed_panel_ratio / base - 1)

    def verdict(r):
        if np.isfinite(r.fixed_panel_ratio):
            crosses = (r.fixed_panel_ratio >= NEARLY_DOUBLED) != (base >= NEARLY_DOUBLED) or abs(r.fixed_panel_ratio - NEARLY_DOUBLED) < 0.01
            return "yes" if crosses else "no"
        return "city-style figure only"
    out["changes_nearly_doubled"] = out.apply(verdict, axis=1)
    return out, base, med()


def composition(d: pd.DataFrame) -> dict:
    """Exact split of the plain all-counter mean ratio into stayers x counter mix."""
    sy = site_years(d)
    a = sy[sy.year == BASE].set_index("site_id").corrected
    b = sy[sy.year == TARGET].set_index("site_id").corrected
    st = a.index.intersection(b.index)
    return {"all": float(b.mean() / a.mean()), "stayers": float(b[st].mean() / a[st].mean()),
            "mix": float((b.mean() / b[st].mean()) / (a.mean() / a[st].mean())),
            "leavers": list(a.drop(st).index), "leavers_mean_base": float(a.drop(st).mean()),
            "stayers_mean_base": float(a[st].mean()), "entrants_mean_target": float(b.drop(st).mean()),
            "stayers_mean_target": float(b[st].mean()), "n_base": int(len(a)), "n_target": int(len(b))}


def city_median_loo(d: pd.DataFrame) -> pd.Series:
    sy = site_years(d)
    out = {}
    for x in sorted(sy[sy.year.isin([BASE, TARGET])].site_id.unique()):
        q = sy[sy.site_id != x]
        out[x] = float(q[q.year == TARGET].corrected.median() / q[q.year == BASE].corrected.median())
    return pd.Series(out, name="median_ratio_without_site")


def relative_quarterly(d: pd.DataFrame, site: str = "VZS_ANDR") -> pd.DataFrame:
    q = d.day.dt.to_period("Q")
    s = d[d.site_id == site].groupby(q[d.site_id == site]).total.mean()
    med = d.groupby(["site_id", q]).total.mean().groupby(level=1).median()
    out = pd.DataFrame({"site": s, "median_counter": med.reindex(s.index)})
    out["ratio"] = out.site / out.median_counter
    out.index = out.index.astype(str)
    return out.rename_axis("quarter")


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def _summ(b: np.ndarray) -> dict:
    f = b[np.isfinite(b)]
    return {"n": int(len(f)), "failed": int(len(b) - len(f)), "median": float(np.median(f)),
            "ci95": [float(np.percentile(f, 2.5)), float(np.percentile(f, 97.5))],
            **{f"p_ge_{x:.3f}": float((f >= x).mean()) for x in THRESHOLDS}}


def run(n_boot: int = N_BOOT) -> dict:
    if cfg.VARIANT != "city":
        raise SystemExit("claims: run with the default city variant (the city's index uses city counters only)")
    out = out_dir()
    official = official_index()
    d = daily_panel()

    print("  [1] reproducing the official index ...")
    ov = official_variants(d, official)
    ov.to_csv(out / "official_reproduction.csv")
    fit = {c: float(np.sqrt(((ov[c] - ov.official) ** 2).mean())) for c in ov.columns if c.startswith(("pooled", "mean_of", "median_of"))}

    print("  [2] like-for-like estimates ...")
    sites = fixed_panel_sites(d)
    s = d[d.site_id.isin(sites)]
    per_site = (s[s.year == TARGET].groupby("site_id").total.mean() / s[s.year == BASE].groupby("site_id").total.mean()).rename("ratio_raw_unadjusted")
    per_site.to_csv(out / "fixed_panel_per_site.csv")
    unadj = float(s[s.year == TARGET].groupby("site_id").total.mean().sum() / s[s.year == BASE].groupby("site_id").total.mean().sum())
    loo = {x: fixed_panel(d, [y for y in sites if y != x], corrected=False) for x in sites}
    db = daily_panel(breaks=FLAGGED_BREAKS)
    chain, steps = chain_linked(d)
    steps.to_csv(out / "chain_linked_steps.csv", index=False)
    sy = site_years(d)
    series = pd.DataFrame({
        "official": pd.Series(official),
        "fixed_panel_adjusted": 100 * fixed_panel_series(d, sites),
        "median_corrected_all": 100 * sy.groupby("year").corrected.median() / sy[sy.year == BASE].corrected.median(),
        "mean_corrected_all": 100 * sy.groupby("year").corrected.mean() / sy[sy.year == BASE].corrected.mean(),
        "chain_linked": 100 * pd.Series({BASE: 1.0, **dict(zip(steps.to, steps.cumulative))}),
        "n_counters": sy.groupby("year").size(),
    }).loc[BASE:]
    series.rename_axis("year").to_csv(out / "index_series.csv")

    print("  [3] anomalies ...")
    device_swap_steps(d).to_csv(out / "device_swap_steps.csv", index=False)
    level_jumps(d[d.year <= TARGET]).to_csv(out / "level_jumps.csv", index=False)
    an, base_ratio, base_med = anomaly_impacts(d, sites)
    an.to_csv(out / "anomaly_impacts.csv", index=False)
    comp = composition(d)
    city_median_loo(d).to_csv(out / "city_median_loo.csv")
    relative_quarterly(d).to_csv(out / "andreasstrasse_quarterly.csv")

    scen = {
        "S1": ("Same counters, raw counts, coverage-period effects (pre-registered)", fixed_panel(d, sites, False),
               lambda n: bootstrap_fixed(d, sites, False, n)),
        "S2": ("Same counters, counts × city correction factors", fixed_panel(d, sites, True),
               lambda n: bootstrap_fixed(d, sites, True, n, cfg.SEED + 1)),
        "S3": ("Same counters, two 2019 device swaps as breaks", fixed_panel(db, sites, False),
               lambda n: bootstrap_fixed(db, sites, False, n, cfg.SEED + 3)),
        "S4": ("Chain-linked over all counters, outage years skipped", chain, lambda n: bootstrap_chain(d, n)),
    }
    res_s = {}
    for k, (label, est, boot) in scen.items():
        n = n_boot if k == "S1" else max(100, n_boot // 2)
        print(f"  [4] {k} {label}: point {est:.3f}; bootstrap {n} draws (sites x week blocks) ...")
        b = boot(n)
        np.save(out / f"bootstrap_{k}.npy", b)
        res_s[k] = {"label": label, "point": est, **_summ(b)}

    key = f"p_ge_{NEARLY_DOUBLED:.3f}"
    res = {
        "claim": "Veloverkehr in der Stadt Zürich hat sich 2012-2024 beinahe verdoppelt (official index 2024 = 193.4)",
        "test": f"true growth ratio {BASE}->{TARGET} >= {NEARLY_DOUBLED} (fixed before estimation)",
        "official_ratio": official[TARGET] / 100,
        "reproduction_rmse_index_points": fit,
        "best_reproduction": min(fit, key=fit.get),
        "city_style_median_ratio": base_med,
        "fixed_panel_sites": sites,
        "fixed_panel_unadjusted_ratio": unadj,
        "fixed_panel_leave_one_out": loo,
        "flagged_breaks": FLAGGED_BREAKS,
        "composition": comp,
        "scenarios": res_s,
        "confidence": res_s["S1"][key],
        "confidence_range_across_scenarios": [min(v[key] for v in res_s.values()), max(v[key] for v in res_s.values())],
    }
    (out / "result.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"  confidence P(ratio >= {NEARLY_DOUBLED}) = {res['confidence']:.3f} "
          f"(range {res['confidence_range_across_scenarios'][0]:.2f}-{res['confidence_range_across_scenarios'][1]:.2f})")
    return res
