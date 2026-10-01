#!/usr/bin/env bash
# Reproduce every result, figure and page in this repository.
# Tested on an Apple M4 (24 GB). Total run time about 3 h; the GNN backtests
# take most of it. Steps are cached, so an interrupted run resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
z() { uv run zh-cycling "$@"; }

# 1. data (about 1 GB raw) and network graphs (Overpass, a few minutes each)
z download --cantonal
z clean
z --variant canton6 clean
z graph
z --variant canton6 graph

# 2. reconstruction backtests, test year 2025, one fold per hold-out group
z backtest --models idw,glm,gbt,gnn --gnn-graph sensor --tag sensor              # ~1 h
z backtest --models idw,glm,gbt,gnn --gnn-graph intersection --tag intersection  # ~1 h
z backtest --models idw,gbt,ens --tag blend                                      # ~15 min
z --variant canton6 backtest --models idw,gbt,ens --tag blend                    # ~15 min
z --variant canton6 --cost velonetz backtest --models idw,gbt,ens --tag blend_velonetz

# 3. descriptive history and claim checks
z history
z claims --boot 1000                                                             # ~15 min

# 4. paper figures and tables, dashboard, summary page
z figures
z dashboard
z site
