# Did cycling in Zurich nearly double?

[![ci](https://github.com/MannuelTe/zh-cycling/actions/workflows/ci.yml/badge.svg)](https://github.com/MannuelTe/zh-cycling/actions/workflows/ci.yml)

Checking the City of Zurich's claim that cycling "nearly doubled" between 2012 and 2024 against its own open bike-counter data, and testing how well cycling can be estimated where no counter exists.

- **Summary page:** https://mannuelte.github.io/zh-cycling/
- **Interactive dashboard:** https://mannuelte.github.io/zh-cycling/dashboard/
- **Preprint (draft):** [`paper/paper.md`](paper/paper.md)

## Findings

**Claim:** «In der Stadt Zürich hat sich der Veloverkehr von 2012 bis 2024 beinahe verdoppelt.» The city's traffic index puts 2024 at 193.4 (2012 = 100). It averages all counters active in each year.

| | 2012 → 2024 |
|---|---|
| Official index | ×1.93 |
| Reconstructed from open data (median over counters) | ×1.94 |
| Same 8 counters, weather- and calendar-adjusted (pre-registered) | **×1.90** (95% CI ×1.63–×2.37) |
| Same, with two 2019 device swaps treated as measurement breaks | ×1.73 |
| Chain-linked over all counters | ×1.52 |

- **Strong growth is not in doubt.** P(growth ≥ ×1.5) ≈ 1.0 in every same-counter scenario.
- **"Nearly doubled" (≥ ×1.8, fixed in advance) is plausible but not established.** Confidence 0.72 under the pre-registered analysis, 0.21–0.72 across four reasonable analysis choices.
- **One counter carries the margin.** Andreasstrasse's level steps up about ×1.5 relative to other counters at a device swap in October 2019. Treated as real growth: ×1.90; treated as a measurement change: ×1.73–×1.80. The open data cannot tell which.
- **The official figure is less precise than it looks.** With 11 counters in 2012, dropping any single one moves the city-style median between ×1.53 and ×2.16.
- **Changing counters inflate a plain average** (×2.14 = ×1.75 same counters × ×1.22 counter mix). The city's median is far less exposed.
- **Ruled out:** roadworks and outages (about −1%) and COVID years (+2.5% if dropped) do not change the verdict.

**Secondary question: estimating counts at an unmeasured location.** Each city counter is hidden in turn and its 2025 hourly counts rebuilt from the others. The best model (validation-weighted blend of gradient boosting and network-distance IDW, with 29 cantonal stations as extra inputs) reaches 31.1 passages/h MAE, 45% hourly and 42% daily-total WAPE, and runs about 15% low. An inductive graph neural network was 5.6–7.2 passages/h worse than gradient boosting and was not selected. Routing edges along the planned Velonetz did not help.

## Reproduce

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12. Tested on an Apple M4 (24 GB).

```bash
uv sync
scripts/reproduce.sh          # all data, results, figures, dashboard and summary page (~3 h)
scripts/build_paper.sh        # preprint HTML/PDF (needs pandoc; PDF also needs tectonic)
```

Individual steps (`uv run zh-cycling --help`):

| Command | Produces | Time |
|---|---|---|
| `download --cantonal` | `data/raw/` + `manifest.json` (URL, SHA-256, retrieval time) | ~5 min |
| `clean`, `--variant canton6 clean` | canonical Parquet tables in `data/processed*/` | ~2 min |
| `graph`, `--variant canton6 graph` | OSM network, model graphs, cycling-time matrices, edge routes (travel-time and Velonetz cost) | ~3 min each |
| `backtest --tag …` | held-out-site backtest, metrics, report in `outputs*/backtest/<tag>/` | 15 min – 1 h |
| `history` | weather-adjusted index on stable counters | ~1 min |
| `claims` | claim-2 reconstruction, scenarios, bootstrap, anomaly inventory in `outputs/claims/c2_doubling/` | ~15 min |
| `figures` | `paper/figures/`, `paper/tables/`, `paper/paper.md` (filled from `paper.src.md`) | <1 min |
| `dashboard` | `docs/dashboard/index.html` | ~1 min |
| `site` | `docs/index.html` | seconds |

Global options: `--variant canton6` adds cantonal counters within 6 km as input-only sites; `--cost velonetz` scales edge travel times by the planned-network rank.

All random choices are seeded (`config.SEED`); re-running reproduces the committed results exactly.

## Repository layout

```
src/zh_cycling/     pipeline (download, clean, graph, panel, baselines, gnn, backtest,
                    evaluate, history, claims, figures, dashboard, site, summary)
outputs/            committed results: metrics, reports, claim analysis (city variant)
outputs_canton6/    committed results with cantonal inputs
paper/              manuscript: paper.src.md (edit) -> paper.md (generated), figures, tables
site/               summary-page template; numbers are filled from the outputs
dashboard/          dashboard template
docs/               GitHub Pages: summary page and dashboard (generated)
data/events/        dated event ledger (infrastructure, policy, measurement)
notes/              original research plan
tests/              unit tests for the pure parts of the pipeline
```

Raw data, caches, processed tables and per-hour predictions are not committed; the pipeline regenerates them.

## Methods in brief

- **Claim check.** Daily totals per counter (complete days only), joined to MeteoSwiss weather and the Zurich calendar. Poisson GLM with year effects, coverage-period fixed effects (device periods sharing a correction factor) and weather/calendar covariates. Confidence from a two-stage cluster bootstrap (counters, then ISO-week blocks). The threshold and the primary scenario were fixed before any estimate.
- **Reconstruction backtest.** One fold per hold-out group (sites within 150 m are withheld together), training 2021–2023, validation 2024 on separate hidden sites, test 2025. Model selection, blend weights and interval calibration use validation only. The GNN is selected only if it beats the best baseline on validation, its 95% week-block CI on test is below zero and it wins on at least half the sites.

Details and limitations: [`paper/paper.md`](paper/paper.md).

## Technical notes on the data

- `FK_STANDORT` in the counts is the location layer's `id1`, one **device period**. A physical site is the `abkuerzung` (e.g. `VZS_HOFW`, four device periods). The all-years Parquet has no `FK_ZAEHLER` column.
- **Correction factors** come from the location layer (`korrekturfaktor`) and differ between device periods of the same site, so device periods are kept distinct.
- **Autumn DST:** the repeated 02:00 hour appears as duplicate quarter-hour rows, which the publisher does not combine. They are summed, flagged and excluded from evaluation.
- **Directions:** a device counts as two-directional only if most rows carry `VELO_OUT`.
- **MeteoSwiss** hourly stamps are UTC and mark the end of the interval; they are shifted to interval start.
- **Cantonal counters** use different sensors and site types. They enter only as inputs and training sites, flagged by source, and are never scored.
- **Network:** OSM bicycle-permitted ways plus footways with explicit bicycle access; contraflow restored for one-way streets open to bikes (~4,200 edges). It is the current network for all years.

## Limitations

Counters measure passages at a cross-section, not trips or people, and long-running counters are few. Correction factors are used as published. The reconstruction uses today's street network for all years and a flat 16 km/h cycling speed (no gradient). Nothing here identifies why cycling changed.

## Troubleshooting

If the project lives in an iCloud-synced folder on macOS, iCloud may set the hidden flag on `.venv/.../*.pth` files and the package stops importing (`No module named 'zh_cycling'`). Fix with `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`, or keep the virtual environment outside iCloud.

## Licence and citation

Code: MIT ([`LICENSE`](LICENSE)). Manuscript, figures and summary-page text: CC BY 4.0 ([`paper/LICENSE.md`](paper/LICENSE.md)). Data keep their own licences ([`DATA_SOURCES.md`](DATA_SOURCES.md)). Citation metadata: [`CITATION.cff`](CITATION.cff).
