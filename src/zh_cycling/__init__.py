"""Zurich cycling counts: held-out-counter reconstruction with baselines and an inductive GNN."""

from __future__ import annotations

import argparse
import os

# memory/threads: keep BLAS from oversubscribing a shared laptop
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def main() -> None:
    ap = argparse.ArgumentParser(prog="zh-cycling", description=__doc__)
    ap.add_argument("--variant", choices=["city", "canton6"], default=None,
                    help="canton6: add cantonal counters within 6 km as input/training sites "
                         "(separate data/processed_canton6 and outputs_canton6)")
    ap.add_argument("--cost", choices=["time", "velonetz"], default=None,
                    help="edge cost the models read: time (default) or velonetz "
                         "(travel time scaled by planned-network rank; see config.VELONETZ_FACTORS)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch raw sources (+ manifest)")
    d.add_argument("--force", action="store_true")
    d.add_argument("--cantonal", action="store_true", help="also fetch cantonal 2024/2025 counters")
    sub.add_parser("clean", help="build sites / counts_hourly / weather / calendar tables")
    g = sub.add_parser("graph", help="build OSM cycling graph, snap sensors, node covariates")
    g.add_argument("--router", choices=["osm", "ors"], default="osm",
                   help="ors: sensor travel times from openrouteservice (needs ORS_API_KEY)")
    b = sub.add_parser("backtest", help="held-out-site backtest (2025)")
    b.add_argument("--models", default="idw,glm,gbt,gnn")
    b.add_argument("--gnn-graph", choices=["sensor", "intersection"], default="sensor")
    b.add_argument("--holdout-radius", type=float, default=None,
                   help="withhold all sites within this many metres together (sensitivity)")
    b.add_argument("--folds", default=None, help="comma-separated fold indices (default: all)")
    b.add_argument("--no-gnn-refit", action="store_true")
    b.add_argument("--tag", default=None)
    e = sub.add_parser("evaluate", help="metrics, plots and report for a backtest tag")
    e.add_argument("--tag", default="sensor")
    sub.add_parser("history", help="descriptive stable-panel analysis + event ledger plot")
    sub.add_parser("audit-cantonal", help="audit cantonal counters (not merged)")
    cl = sub.add_parser("claims", help="reconstruct the city's published cycling claims")
    cl.add_argument("--boot", type=int, default=1000, help="bootstrap draws")
    sub.add_parser("figures", help="paper figures and tables (paper/figures, paper/tables)")
    sub.add_parser("dashboard", help="interactive dashboard (docs/dashboard/index.html)")
    sub.add_parser("site", help="summary landing page (docs/index.html)")
    a = sub.add_parser("all", help="download, clean, graph, backtest, evaluate, history")
    a.add_argument("--quick", action="store_true", help="3 folds only, for a fast end-to-end check")
    args = ap.parse_args()
    if args.variant:  # must happen before any module imports config
        os.environ["ZHC_VARIANT"] = args.variant
    if args.cost:
        os.environ["ZHC_COST"] = args.cost

    if args.cmd in ("download", "all"):
        from . import download

        download.download_all(force=getattr(args, "force", False), cantonal=getattr(args, "cantonal", False))
    if args.cmd in ("clean", "all"):
        from . import clean

        clean.run()
    if args.cmd in ("graph", "all"):
        from . import graph

        graph.build(router=getattr(args, "router", "osm"))
    if args.cmd == "backtest":
        from . import backtest, evaluate

        tag = args.tag or args.gnn_graph + (f"_r{int(args.holdout_radius)}" if args.holdout_radius else "") \
            + ("" if os.environ.get("ZHC_COST", "time") == "time" else "_" + os.environ["ZHC_COST"])
        backtest.run(models=tuple(args.models.split(",")), gnn_graph=args.gnn_graph,
                     holdout_radius=args.holdout_radius,
                     folds_only=[int(x) for x in args.folds.split(",")] if args.folds else None,
                     gnn_refit=not args.no_gnn_refit, tag=tag)
        evaluate.run(tag)
        from . import config

        print(f"report: {config.OUTPUTS / 'backtest' / tag / 'report.md'}")
    if args.cmd == "all":
        from . import backtest, evaluate

        tag = "quick" if args.quick else "sensor"
        backtest.run(folds_only=[0, 1, 2] if args.quick else None, tag=tag)
        evaluate.run(tag)
    if args.cmd == "evaluate":
        from . import evaluate

        evaluate.run(args.tag)
        from . import config

        print(f"report: {config.OUTPUTS / 'backtest' / args.tag / 'report.md'}")
    if args.cmd in ("history", "all"):
        from . import history

        history.run()
    if args.cmd == "claims":
        from . import claims

        claims.run(n_boot=args.boot)
    if args.cmd == "figures":
        from . import figures

        figures.run()
    if args.cmd == "dashboard":
        from . import dashboard

        dashboard.build()
    if args.cmd == "site":
        from . import site

        site.build()
    if args.cmd == "audit-cantonal":
        from . import cantonal

        cantonal.audit()
