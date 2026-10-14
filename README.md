# Indian Energy Generation Observatory

An automated dataset and dashboard of India's electricity generation by source and of generating-unit
outages, built **only from official reports**:

- **Central Electricity Authority (CEA):** Daily Generation Report via
  [npp.gov.in](https://npp.gov.in/publishedReports), and the Daily Renewable Generation Report via
  [gen-re.cea.gov.in](https://gen-re.cea.gov.in/reports).
- **Grid Controller of India (Grid-India):** daily Power Supply Position report, daily REMC (renewable)
  report and monthly grid disturbance reports via [grid-india.in](https://grid-india.in/en/reports/daily-psp-report).

The current release covers **13 Oct 2025 – 12 Oct 2026** (365 days, one full seasonal cycle).

| Table | Rows | What it is |
|---|---:|---|
| `generation_daily` (core) | 332,025 | One record per station (or state-level renewable total) per day, every energy source |
| `unit_daily` | 248,988 | Thermal and nuclear unit-level generation and outage status |
| `outage_snapshot` | 53,905 | CEA's daily list of coal, lignite and nuclear units under outage, with cause class |
| `outage_events` | 7,374 | Outage events reconstructed from the daily snapshots |
| `grid_15min` | 34,942 | 15-minute all-India generation by source (Grid-India SCADA) |
| `grid_mix_daily` | 15,288 | Source-wise gross generation by region, renewables included |
| `state_supply_daily` | 12,376 | State peak demand, energy met and unmet demand |
| `re_availability_daily` | 19,033 | Solar and wind installed vs maximum available capacity by region and state (Grid-India REMC) |
| `grid_events` | 521 | Every grid disturbance with start, end, MW lost; `involves_re` marks those that took solar/wind plants offline |
| `re_zero_output_episodes` | 740 | Runs of zero-output days at inter-state solar stations (derived proxy) |
| `fuel_daily`, `grid_region_daily`, `entities`, `source_files`, `data_gaps`, `validation` | | Official totals, region summaries, station list, provenance, gaps, checks |

Column-by-column descriptions: [docs/data_dictionary.md](docs/data_dictionary.md).
Source research and plan: [docs/SOURCE_VERIFICATION.md](docs/SOURCE_VERIFICATION.md), [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).

## Rebuild everything from the official sources

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock      # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m observatory refresh --fresh
```

`refresh` runs the whole pipeline:

1. **collect.** Downloads every report in the window set in `observatory.yaml` (about 1,825 files, roughly
   15 minutes) straight from the sources. Each attempt is logged in `data/manifest.csv` with its URL,
   HTTP status, size and SHA-256. `--fresh` ignores anything downloaded before. Without it, files already
   fetched by an earlier run are reused.
2. **build.** Parses every file, validates and merges, and writes the tables to `data/warehouse/*.parquet`.
3. **export.** Writes the published dataset to `dashboard/data/downloads/` (Excel, zipped CSV and Parquet
   for every table) plus the dashboard's data files and `release_manifest.json` (every input URL and hash,
   every output checksum).

The pipeline never reads anything except the official files and the small curated mapping files in
`reference/` (state names, lignite and naphtha station patterns, outage-reason classes). Row order and
file writers are fixed, so the same input files always produce byte-identical outputs.

To change the period (and so the record count), edit `window` in `observatory.yaml`, or pass
`--start/--end`. CEA's unit-level archive starts 2018-04-01; its daily renewable report starts 2024-06-30.

## Dashboard

```bash
.venv/Scripts/python -m http.server 8765 -d dashboard
```

Then open http://localhost:8765. The dashboard is a static site (no server code). The chart and Excel
libraries are bundled in `dashboard/assets/vendor/`, so it also works offline or on GitHub Pages.

| Page | What it shows |
|---|---|
| Overview | Headline numbers, findings, generation mix, renewable / nuclear / fossil shares |
| Sustainable vs fossil | Daily shares, region comparison, region × month heatmap, a typical 15-minute day, actual vs programme |
| Renewables compared | Solar, wind, hydro, biomass: monthly output, capacity factors, seasonality, day-to-day variability, wind-solar complementarity, top states and stations |
| Outages | Unavailable capacity by fuel, causes, regions, worst stations, durations, common failure causes, repeat failures, stranded units, coal stocks |
| Supply & demand | Peak demand, unmet demand by day and state, generation outage |
| Station explorer | Any station's generation vs plan, capacity out and outage events |
| Data & downloads | Every table as Excel / CSV / Parquet, coverage, validation checks |
| Methodology | Definitions and limits |

Every chart has a **Table** view and **Download Excel / CSV** buttons that export exactly the data shown.
Findings are generated from fixed rules applied to the numbers (`observatory/insights.py`), so the same
data always gives the same text.

## Validation (current release)

| Check | Result |
|---|---|
| Station totals vs CEA's own fuel totals (capacity, generation) | 100% of date × fuel totals match (max difference 0.0 MW / 0.00 MU) |
| Grid-India regions sum to All-India | 99.7% within 1 MU |
| Outage rows matched to a unit in the same day's generation report | 99.99% (7 of 53,905 unmatched) |
| Coverage | CEA DGR 365/365 days for each sub-report · CEA RE 362/365 · Grid-India 364/365 |
| Capacity factor > 1.05 | 1.6% of records, flagged in `quality_flag`, kept as published |

Gaps are reports the sources never published (four days), plus one renewable file in a different layout.
They are listed in `data_gaps` and are never estimated.

## What this does not measure

- No official source lists outages of individual **solar or wind** units. The dataset uses the three closest
  official measures instead: REMC unavailable capacity (aggregate by region/state), grid-disturbance events that
  took renewable plants offline (event level, mostly evacuation-line trips), and zero-output days at
  inter-state solar stations (derived from CEA, clearly labelled as a proxy).
- A generating-unit outage is **not a consumer power cut**. "Unmet demand" is energy shortage reported by
  states, not household interruption indices (SAIFI/SAIDI).
- Rooftop and behind-the-meter solar is not in grid generation data.
- CEA's renewable report is **net** generation; CEA's conventional report and Grid-India are **gross**.
  Shares use Grid-India's gross figures only, and the `basis` column marks every record.

## Layout

```
observatory/        pipeline package (collect, parse, build, events, validate, metrics, insights, export, cli)
observatory.yaml    window and source settings
reference/          curated mapping files (the only non-source inputs)
tests/              parser tests on real report files (tests/fixtures)
dashboard/          static dashboard; dashboard/data is generated by `export`
docs/               source verification, plan, data dictionary
data/               raw downloads, manifest, warehouse (git-ignored, rebuilt by `refresh`)
```
