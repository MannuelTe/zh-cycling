#!/usr/bin/env bash
# Build the preprint PDF/HTML from paper/paper.src.md.
# Needs pandoc (https://pandoc.org) and, for PDF, a LaTeX engine (e.g. tectonic).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run zh-cycling figures            # figures, tables, paper/build/paper.md
cd paper/build
pandoc paper.md -s -o paper.html --embed-resources --mathml
if command -v tectonic >/dev/null; then
  pandoc paper.md -o paper.pdf --pdf-engine=tectonic -V geometry:margin=2.5cm -V fontsize=10pt
fi
echo "built paper/build/paper.{html,pdf}"
