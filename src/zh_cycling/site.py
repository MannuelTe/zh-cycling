"""Summary landing page (docs/index.html) for GitHub Pages.

site/index.html holds the prose; every number is a {{key}} filled from the
pipeline outputs via `summary.numbers()`. The Andreasstrasse chart is drawn
here as static SVG so the page works without JavaScript.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import summary

TEMPLATE = C.ROOT / "site" / "index.html"
DOCS = C.ROOT / "docs"


def andreasstrasse_svg(w: int = 560, h: int = 230) -> str:
    q = pd.read_csv(summary.CLAIM / "andreasstrasse_quarterly.csv")
    q["t"] = q.quarter.str[:4].astype(int) + (q.quarter.str[-1].astype(int) - 1) / 4
    q = q[q.t.between(2011, 2025.9)]
    m = dict(l=34, r=10, t=12, b=22)
    x = lambda t: m["l"] + (t - 2011) / 15 * (w - m["l"] - m["r"])
    y = lambda v: h - m["b"] - v / 1.1 * (h - m["t"] - m["b"])
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Andreasstrasse traffic relative to the median counter, 2011 to 2025">']
    for v in (0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{m["l"]}" x2="{w - m["r"]}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--rule)"/>'
                     f'<text x="{m["l"] - 6}" y="{y(v) + 3:.1f}" text-anchor="end">{v:.2f}</text>')
    for yr in (2012, 2015, 2018, 2021, 2024):
        parts.append(f'<text x="{x(yr):.1f}" y="{h - 6}" text-anchor="middle">{yr}</text>')
    for t in (2019 + 72 / 365, 2019 + 283 / 365):
        parts.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{m["t"]}" y2="{h - m["b"]}" stroke="var(--ink2)" stroke-dasharray="3 3"/>')
    d, prev = "", None
    for r in q.itertuples():
        d += ("M" if prev is None or r.t - prev > 0.3 else "L") + f"{x(r.t):.1f},{y(r.ratio):.1f}"
        prev = r.t
    pre = q[(q.t >= 2017) & (q.t < 2019.2)].ratio
    post = q[(q.t >= 2020) & (q.t < 2022)].ratio
    a0, a1 = float(np.exp(np.log(pre).mean())), float(np.exp(np.log(post).mean()))
    parts += [f'<path d="{d}" fill="none" stroke="var(--zh)" stroke-width="2.2" stroke-linejoin="round"/>',
              f'<line x1="{x(2017):.1f}" x2="{x(2019.2):.1f}" y1="{y(a0):.1f}" y2="{y(a0):.1f}" stroke="var(--ink)" stroke-width="1.6"/>',
              f'<line x1="{x(2020):.1f}" x2="{x(2022):.1f}" y1="{y(a1):.1f}" y2="{y(a1):.1f}" stroke="var(--ink)" stroke-width="1.6"/>',
              f'<text x="{x(2022) + 6:.1f}" y="{y(a1) + 4:.1f}" style="fill:var(--ink)">×{a1 / a0:.2f} step</text>',
              "</svg>"]
    return "".join(parts)


def build() -> None:
    nums = summary.numbers()
    nums["svg.andr"] = andreasstrasse_svg()
    html = summary.fill(TEMPLATE.read_text(), nums)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(html)
    (DOCS / ".nojekyll").write_text("")
    print(f"  site: {DOCS / 'index.html'}")
