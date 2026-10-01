"""Figures and tables for the preprint (paper/figures, paper/tables).

Everything is read from the pipeline outputs; nothing is recomputed here
except simple aggregations. Run after `claims`, the backtests and `history`.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config as C

OUT = C.ROOT / "outputs"
OUT6 = C.ROOT / "outputs_canton6"
CLAIM = OUT / "claims" / "c2_doubling"
FIG = C.ROOT / "paper" / "figures"
TAB = C.ROOT / "paper" / "tables"
INK, INK2, MUTED, GRID = "#111720", "#465263", "#6f7a8a", "#e3e7ee"
BLUE, GREY, ORANGE, AMBER, RED = "#2a78d6", "#97a1af", "#eb6834", "#b26a00", "#e34948"
RUNS = {
    "Network IDW (city)": (OUT / "backtest" / "blend", "idw"),
    "Gradient boosting (city)": (OUT / "backtest" / "blend", "gbt"),
    "Blend GBT+IDW (city)": (OUT / "backtest" / "blend", "ens"),
    "Poisson GLM (city)": (OUT / "backtest" / "sensor", "glm"),
    "GNN, sensor graph (city)": (OUT / "backtest" / "sensor", "gnn"),
    "GNN, intersection graph (city)": (OUT / "backtest" / "intersection", "gnn"),
    "Network IDW (+cantonal)": (OUT6 / "backtest" / "blend", "idw"),
    "Gradient boosting (+cantonal)": (OUT6 / "backtest" / "blend", "gbt"),
    "Blend GBT+IDW (+cantonal)": (OUT6 / "backtest" / "blend", "ens"),
    "Blend GBT+IDW (+cantonal, Velonetz cost)": (OUT6 / "backtest" / "blend_velonetz", "ens"),
}


def _style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight",
    })


def _save(fig, name: str):
    FIG.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"{name}.{ext}")
    plt.close(fig)


def fig_index():
    s = pd.read_csv(CLAIM / "index_series.csv", index_col="year")
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    for col, lab, c, ls, lw in [("official", "Official index (city)", INK, "-", 2.2),
                                ("median_corrected_all", "Median over all counters (reconstructed)", INK2, "--", 1.3),
                                ("fixed_panel_adjusted", "Same 8 counters, weather/calendar-adjusted", BLUE, "-", 2.2),
                                ("chain_linked", "Chain-linked over all counters", GREY, "-", 1.6),
                                ("mean_corrected_all", "Plain average over all counters", ORANGE, ":", 1.4)]:
        ax.plot(s.index, s[col], ls=ls, lw=lw, color=c, label=lab)
    ax.axhline(180, color=AMBER, ls="--", lw=1, label="180 = 'nearly doubled' threshold (pre-registered)")
    ax.set_ylabel("index, 2012 = 100")
    ax.set_xticks(range(2012, 2026, 2))
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, handlelength=2.6)
    ax.set_xlim(2011.6, 2025.4)
    _save(fig, "fig1_index")


def fig_bootstrap():
    R = json.loads((CLAIM / "result.json").read_text())
    fig, axes = plt.subplots(4, 1, figsize=(6.6, 5.6), sharex=True, gridspec_kw={"hspace": 0.75})
    bins = np.arange(1.2, 2.55, 0.025)
    for ax, k in zip(axes, ("S1", "S2", "S3", "S4")):
        b = np.load(CLAIM / f"bootstrap_{k}.npy")
        b = b[np.isfinite(b)]
        h, e = np.histogram(np.clip(b, 1.2, 2.5 - 1e-9), bins=bins)
        ax.bar(e[:-1], h, width=0.022, align="edge", color=[BLUE if x >= 1.8 else GREY for x in e[:-1]])
        sc = R["scenarios"][k]
        ax.axvline(sc["point"], color=INK, lw=1.6)
        ax.axvline(1.8, color=AMBER, ls="--", lw=1)
        ax.axvline(R["official_ratio"], color=INK2, ls=":", lw=1)
        ax.set_yticks([])
        ax.grid(False)
        ax.set_title(f"{k} · {sc['label']}   —   point ×{sc['point']:.2f}, P(≥ ×1.8) = {sc['p_ge_1.800']:.2f}",
                     loc="left", fontsize=7.6, color=INK, pad=4)
        ax.spines["left"].set_visible(False)
    axes[-1].set_xlabel("growth ratio 2012→2024 (bootstrap draws; dashed ×1.8, dotted official ×1.93)")
    _save(fig, "fig2_bootstrap")


def fig_andreasstrasse():
    q = pd.read_csv(CLAIM / "andreasstrasse_quarterly.csv")
    q["t"] = q.quarter.str[:4].astype(int) + (q.quarter.str[-1].astype(int) - 1) / 4
    q = q[q.t.between(2011, 2026)]
    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    gap = q.t.diff() > 0.3
    for _, seg in q.groupby(gap.cumsum()):
        ax.plot(seg.t, seg.ratio, color=BLUE, lw=1.8)
    for t in (2019 + 72 / 365, 2019 + 283 / 365):
        ax.axvline(t, color=INK2, ls="--", lw=0.9)
    ax.text(2019.85, 1.0, "device swap Oct 2019", fontsize=7.5, color=INK2)
    ax.set_ylabel("Andreasstrasse ÷ median counter")
    ax.set_ylim(0, 1.1)
    _save(fig, "fig3_andreasstrasse")


def fig_leaderboard():
    rows = []
    for lab, (path, m) in RUNS.items():
        p = pd.read_csv(path / "metrics_pooled.csv").set_index("model")
        if m in p.index:
            rows.append((lab, p.loc[m, "MAE"], "+cantonal" in lab))
    rows.sort(key=lambda r: r[1], reverse=True)
    fig, ax = plt.subplots(figsize=(6.6, 3.2))
    ax.barh([r[0] for r in rows], [r[1] for r in rows], color=[BLUE if r[2] else GREY for r in rows], height=0.6)
    for i, r in enumerate(rows):
        ax.text(r[1] + 0.3, i, f"{r[1]:.2f}", va="center", fontsize=7.5, color=INK)
    ax.set_xlabel("pooled hourly MAE on held-out sites, 2025 (passages/h)")
    ax.grid(axis="y", visible=False)
    _save(fig, "fig4_leaderboard")


def fig_history():
    h = pd.read_csv(OUT / "history" / "stable_panel_annual_index.csv")
    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    ax.fill_between(h.year, h.ci_lo, h.ci_hi, color=BLUE, alpha=0.15, lw=0)
    ax.plot(h.year, h.adjusted_index, color=BLUE, lw=2, marker="o", ms=3.5)
    ax.set_ylabel("adjusted index, 2017 = 1")
    _save(fig, "fig5_history")


def _md(df: pd.DataFrame, name: str, floatfmt=".2f"):
    TAB.mkdir(parents=True, exist_ok=True)
    (TAB / f"{name}.md").write_text(df.to_markdown(index=False, floatfmt=floatfmt) + "\n")


def tables():
    R = json.loads((CLAIM / "result.json").read_text())
    _md(pd.DataFrame([{"scenario": k, "description": v["label"], "point": v["point"], "CI 2.5%": v["ci95"][0], "CI 97.5%": v["ci95"][1],
                       "P(≥×1.5)": v["p_ge_1.500"], "P(≥×1.8)": v["p_ge_1.800"], "P(≥×1.934)": v["p_ge_1.934"], "draws": v["n"]}
                      for k, v in R["scenarios"].items()]), "tab1_scenarios")
    a = pd.read_csv(CLAIM / "anomaly_impacts.csv")
    _md(a[["group", "anomaly", "sites", "fixed_panel_ratio", "fixed_panel_change_pct", "city_median_if_excluded", "changes_nearly_doubled"]]
        .rename(columns={"fixed_panel_ratio": "same-8 ratio", "fixed_panel_change_pct": "change %",
                         "city_median_if_excluded": "city median if excluded", "changes_nearly_doubled": "changes verdict"}), "tab2_anomalies")
    rows = []
    for lab, (path, m) in RUNS.items():
        p = pd.read_csv(path / "metrics_pooled.csv").set_index("model")
        mc = pd.read_csv(path / "metrics_macro.csv").set_index("model")
        cv = pd.read_csv(path / "interval_coverage.csv").set_index("model")
        if m in p.index:
            rows.append({"model": lab, "pooled MAE": p.loc[m, "MAE"], "macro MAE": mc.loc[m, "MAE"], "WAPE": p.loc[m, "WAPE"],
                         "bias": p.loc[m, "bias"], "90% coverage": cv.loc[m, "90"]})
    _md(pd.DataFrame(rows).sort_values("pooled MAE"), "tab3_models")
    o = pd.read_csv(CLAIM / "official_reproduction.csv", index_col=0)
    rm = {c: float(np.sqrt(((o[c] - o.official) ** 2).mean())) for c in o.columns if c.startswith(("pooled", "mean_of", "median_of"))}
    _md(pd.DataFrame({"method": list(rm), "RMSE (index points)": list(rm.values()),
                      "2024 value": [o.loc[2024, c] for c in rm]}).sort_values("RMSE (index points)"), "tab4_reproduction", ".1f")


def assemble_paper() -> None:
    """paper/paper.src.md -> paper/paper.md (readable on GitHub) and
    paper/build/paper.md (pandoc input), with tables inlined and numbers filled."""
    import re
    import shutil

    from . import summary

    src = (C.ROOT / "paper" / "paper.src.md").read_text()
    src = re.sub(r"<!-- table: (\w+) -->", lambda m: (TAB / f"{m.group(1)}.md").read_text(), src)
    text = summary.fill(src)
    build = C.ROOT / "paper" / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "paper.md").write_text(text)
    shutil.copytree(FIG, build / "figures", dirs_exist_ok=True)

    # GitHub shows YAML front matter as a raw table: turn it into a title block
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    head, body = (m.group(1), text[m.end():]) if m else ("", text)
    title = re.search(r'^title:\s*"?(.*?)"?$', head, re.M)
    author = re.search(r'^author:\s*"?(.*?)"?$', head, re.M)
    date = re.search(r'^date:\s*"?(.*?)"?$', head, re.M)
    abstract = re.search(r"^abstract:\s*\|\n((?:  .*\n?)+)", head, re.M)
    body = re.sub(r"<!--.*?-->\n?", "", body, count=1, flags=re.S)  # drop the editing note
    gh = ["<!-- Generated by `zh-cycling figures` from paper.src.md. Edit that file, not this one. -->", ""]
    if title:
        gh += [f"# {title.group(1)}", ""]
    if author or date:
        gh += [f"*{' · '.join(x.group(1) for x in (author, date) if x)}*", ""]
    if abstract:
        gh += ["**Abstract.** " + " ".join(line.strip() for line in abstract.group(1).splitlines()), ""]
    # GitHub's parser can read _ and * inside $...$ as emphasis; use its robust math syntax
    body = re.sub(r"\$\$\s*\n(.*?)\n\s*\$\$", lambda m: "```math\n" + m.group(1).strip() + "\n```", body, flags=re.S)
    inline = lambda s: re.sub(r"(?<![$`])\$(?![$`])([^$\n]+?)\$(?![$`])", r"$`\1`$", s)
    body = inline(body)
    gh = [inline(line) for line in gh]
    body = re.sub(r"^# ", "## ", body, flags=re.M)
    body = re.sub(r"^## (\d+\.\d+ )", r"### \1", body, flags=re.M)
    (C.ROOT / "paper" / "paper.md").write_text("\n".join(gh) + body)
    print(f"  paper   -> paper/paper.md (GitHub), {build / 'paper.md'} (pandoc)")


def run():
    _style()
    fig_index()
    fig_bootstrap()
    fig_andreasstrasse()
    fig_leaderboard()
    fig_history()
    tables()
    print(f"  figures -> {FIG}\n  tables  -> {TAB}")
    assemble_paper()
