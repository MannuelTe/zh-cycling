# Did cycling in Zurich nearly double?

[![ci](https://github.com/MannuelTe/zh-cycling/actions/workflows/ci.yml/badge.svg)](https://github.com/MannuelTe/zh-cycling/actions/workflows/ci.yml)

The City of Zurich says cycling "nearly doubled" between 2012 and 2024. This project checks that claim against the city's own open bike-counter data. It also tests how well cycling can be estimated at places where no counter exists.

- **Summary page:** https://mannuelte.github.io/zh-cycling/
- **Interactive dashboard:** https://mannuelte.github.io/zh-cycling/dashboard/
- **Preprint (draft):** [`paper/paper.md`](paper/paper.md)

## The claim

> «In der Stadt Zürich hat sich der Veloverkehr von 2012 bis 2024 beinahe verdoppelt.»

The city's traffic index puts 2024 at 193.4 (2012 = 100), meaning cycling grew by a factor of about 1.93. Before any estimate was made, "nearly doubled" was defined as growth of at least ×1.8 ([paper §3.3](paper/paper.md#33-test-definition-and-confidence-fixed-in-advance)).

## Findings

| | 2012 → 2024 |
|---|---|
| Official index | ×1.93 |
| Rebuilt from the open data | ×1.94 |
| Same 8 counters in both years, adjusted for weather and calendar (pre-registered) | **×1.90** (95% CI ×1.63–×2.37) |

- **The official number can be reproduced.** Rebuilding the index from the open data gives ×1.94 against the published ×1.93 ([§4.1](paper/paper.md#41-the-official-figure-is-reproducible)).
- **The growth holds up on a like-for-like comparison.** The counters that ran in both years show ×1.90 after adjusting for weather and calendar, above the ×1.8 threshold. Strong growth (at least ×1.5) is near-certain in every analysis ([§4.2](paper/paper.md#42-like-for-like-growth-and-confidence)).
- **The margin depends on one counter.** A device swap at Andreasstrasse in 2019 coincides with a jump in its counts. If that jump is a measurement artefact rather than real growth, the estimate drops to about ×1.73–×1.80 ([§4.3](paper/paper.md#43-one-counter-carries-the-margin)).
- **There are few long-running counters.** There were only 11 counters in 2012, so dropping any single one moves the city-style figure between ×1.53 and ×2.16 ([§4.4](paper/paper.md#44-composition-and-the-fragility-of-the-median)).
- **Roadworks, outages and the COVID years do not change the result** ([§4.3, anomaly table](paper/paper.md#43-one-counter-carries-the-margin)).

**Secondary question.** Can counts at an unmeasured street be estimated from the surrounding counters? Only roughly. The best model is off by about 45% hour by hour and about 40% on daily totals. A graph neural network did no better than simpler methods ([§5](paper/paper.md#5-secondary-analysis-reconstructing-counts-at-unmeasured-locations)).

## Conclusion

**Yes, the claim is defensible.** The open data are sparse: few counters reach back to 2012, and one device change carries much of the margin. Even so, the city's figure can be confidently replicated. Rebuilding it from the open data gives the same number. The pre-registered like-for-like analysis lands at ×1.90, above the "nearly doubled" threshold. Every analysis variant shows strong growth. The remaining uncertainty is about how close to "doubled" cycling got, not whether it grew substantially. The Tiefbauamt's records of the 2019 device change at Andreasstrasse would settle most of it ([§6](paper/paper.md#6-discussion)).

## How it was done

The paper describes the methods in [§3](paper/paper.md#3-methods) and the data in [§2](paper/paper.md#2-data). In short:

1. Rebuild the official index from raw counter data.
2. Compare only counters that existed in both years, and adjust for weather and holidays.
3. Use resampling to measure how confident one can be that growth reached ×1.8. The threshold and the main analysis were fixed before looking at the results.
4. List every known oddity (device swaps, roadworks, COVID) and check whether it changes the verdict.

Data sources, licences and data-handling notes are in [`DATA_SOURCES.md`](DATA_SOURCES.md).

## Reproduce

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12. Tested on an Apple M4 (24 GB).

```bash
uv sync
scripts/reproduce.sh          # all data, results, figures, dashboard and summary page (~3 h)
scripts/build_paper.sh        # preprint HTML/PDF (needs pandoc; PDF also needs tectonic)
```

Individual steps are listed by `uv run zh-cycling --help`. All random choices are seeded, so re-running reproduces the committed results exactly. Raw data and intermediate tables are not committed; the pipeline regenerates them.

## Repository layout

```
src/zh_cycling/     analysis pipeline
outputs/            committed results (city counters)
outputs_canton6/    committed results with cantonal counters as extra inputs
paper/              manuscript: paper.src.md (edit) -> paper.md (generated), figures, tables
site/, dashboard/   templates for the summary page and dashboard
docs/               GitHub Pages output (generated)
data/events/        dated log of infrastructure, policy and measurement events
tests/              unit tests
```

## Limitations

Counters measure bikes passing a point, not trips or people. Long-running counters are few. The city's correction factors are used as published. Nothing here explains *why* cycling grew. See [§6 of the paper](paper/paper.md#6-discussion).

## Troubleshooting

If the project lives in an iCloud-synced folder on macOS, iCloud may set the hidden flag on `.venv/.../*.pth` files and the package stops importing (`No module named 'zh_cycling'`). Fix with `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`, or keep the virtual environment outside iCloud.

## Licence and citation

Code: MIT ([`LICENSE`](LICENSE)). Manuscript, figures and summary-page text: CC BY 4.0 ([`paper/LICENSE.md`](paper/LICENSE.md)). Data keep their own licences ([`DATA_SOURCES.md`](DATA_SOURCES.md)). Citation metadata: [`CITATION.cff`](CITATION.cff).
