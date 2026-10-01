"""Unit tests for the pure parts of the pipeline (no downloaded data needed)."""

import numpy as np
import pandas as pd
import pytest

from zh_cycling import claims, config, dashboard
from zh_cycling.graph import knn_edges


def test_knn_edges_symmetric_and_k_nearest():
    rng = np.random.default_rng(1)
    xy = rng.uniform(0, 1000, size=(12, 2))
    T = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    src, dst, attr = knn_edges(T, k=3, tau_s=300.0)
    pairs = set(zip(src.tolist(), dst.tolist()))
    assert all((j, i) in pairs for i, j in pairs), "graph must be symmetric"
    for i in range(12):
        nearest = np.argsort(np.where(np.arange(12) == i, np.inf, T[i]))[:3]
        assert all((i, j) in pairs for j in nearest)
    assert np.all(attr[:, 1] <= 1) and np.all(attr[:, 1] > 0)


def test_knn_edges_respects_allowed_mask():
    T = np.array([[0, 1, 2, 3], [1, 0, 1, 2], [2, 1, 0, 1], [3, 2, 1, 0]], float)
    allowed = np.array([True, False, True, True])
    src, dst, _ = knn_edges(T, k=1, tau_s=300.0, allowed=allowed)
    assert 1 not in set(src.tolist()) | set(dst.tolist())


def _toy_panel(sites=("a", "b", "c"), years=(2012, 2024)):
    days = pd.date_range("2012-01-02", periods=28, freq="D")
    rows = []
    for s in sites:
        for y in years:
            for d in days:
                day = d.replace(year=y)
                rows.append({"site_id": s, "coverage_id": s + "#1", "year": y, "day": day,
                             "week": day.strftime("%G-%V"), "total": 100 * (2 if y == 2024 else 1), "corrected": 0.0})
    return pd.DataFrame(rows)


def test_resample_copies_are_distinct_and_week_blocks_kept():
    d = _toy_panel()
    b = claims._resample(d, ["a", "b", "c"], np.random.default_rng(0))
    assert b.site_id.str.contains("~").all()
    assert b.site_id.nunique() == 3
    assert set(b.week) <= set(d.week)


def test_composition_is_an_exact_identity(monkeypatch):
    sy = pd.DataFrame({
        "site_id": ["a", "b", "q", "a", "b", "n"], "year": [2012, 2012, 2012, 2024, 2024, 2024],
        "raw": [100, 200, 50, 180, 350, 600], "corrected": [100, 200, 50, 180, 350, 600], "days": [300] * 6})
    monkeypatch.setattr(claims, "site_years", lambda d, min_days=claims.MIN_DAYS: sy)
    c = claims.composition(None)
    assert c["leavers"] == ["q"]
    assert c["all"] == pytest.approx(c["stayers"] * c["mix"])
    assert c["stayers"] == pytest.approx((180 + 350) / (100 + 200))


def test_paired_bootstrap_identical_runs_is_zero():
    ts = pd.date_range("2025-01-01", periods=24 * 60, freq="h")
    a = pd.DataFrame({"site": "s", "ts_local": ts, "model": "ens", "observed": True,
                      "y": np.arange(len(ts)) % 50, "pred": 25.0})
    r = dashboard.paired_week_bootstrap(a, a.copy(), "ens", n=50)
    assert r["diff"] == 0 and r["lo"] == 0 and r["hi"] == 0 and r["n"] == len(ts)


def test_velonetz_factors_are_ordered():
    f = config.VELONETZ_FACTORS
    assert f[3] < f[2] < f[1] < f[0]


def test_official_vintage_values():
    assert claims.OFFICIAL_VELO_INDEX[2012] == 100.0
    assert claims.OFFICIAL_VELO_INDEX[2024] == pytest.approx(193.4)
    assert claims.THRESHOLDS[1] == claims.NEARLY_DOUBLED == 1.8


def test_fill_substitutes_and_rejects_unknown_keys():
    from zh_cycling import summary

    assert summary.fill("a {{x.y}} b {{ x.y }}", {"x.y": "1"}) == "a 1 b 1"
    with pytest.raises(KeyError):
        summary.fill("{{missing}}", {"x.y": "1"})


def test_templates_only_use_known_keys():
    """Every {{key}} in the paper and site templates must be a number key."""
    import re

    from zh_cycling import summary

    keys = set()
    for f in (config.ROOT / "paper" / "paper.src.md", config.ROOT / "site" / "index.html"):
        keys |= set(re.findall(r"\{\{\s*([\w.]+)\s*\}\}", f.read_text()))
    known_prefixes = ("claim.", "model.", "history.", "svg.")
    assert all(k.startswith(known_prefixes) for k in keys), sorted(keys)
    if (summary.CLAIM / "result.json").exists():
        nums = summary.numbers()
        assert {k for k in keys if not k.startswith("svg.")} <= set(nums), sorted(set(keys) - set(nums))
