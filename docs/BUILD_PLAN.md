# Build plan: Indian Energy Generation Observatory

> **Status (2026-10-14): built.** See the [README](../README.md) for the delivered system. Departures from this plan,
> all agreed or forced by the data:
> - The window is pinned to one year (13 Oct 2025 – 12 Oct 2026), sized to the ~300k-record target
>   (332,025 core records). There is no multi-year backfill.
> - Reproducing old versions is out of scope. `refresh` always rebuilds from what the sources serve today.
> - Grid-India PSP is used for the generation mix. CEA is used for stations, units, programme and outages.
> - Phase 8 extensions (monthly PDF extraction, RE curtailment, SAIFI/SAIDI) are not built.
> - No daily scheduler is installed yet. `python -m observatory refresh` is the single command to schedule.

Based on [SOURCE_VERIFICATION.md](SOURCE_VERIFICATION.md). The plan keeps the idea's goals and changes
three things the source check forced:

1. **Two primary sources, each for its own job.** Grid-India PSP is the source for the all-India and
   regional generation **mix**: it is gross throughout, includes RE, and goes back to 2013. CEA is the
   source for **station and unit** generation, program vs actual, and **outages**.
2. **No outage-rate comparison for solar or wind.** No official data exists for it. Renewables are
   compared on capacity factor, variability and (later) curtailment. Unit availability is compared
   across thermal, nuclear and hydro only.
3. **The consumer layer is "unmet demand" (PSP state shortage)**, not SAIFI/SAIDI. Those stay an
   optional add-on.

## The finished project

The final stage has three parts, all in one repository:

1. **`observatory`, a reproducible pipeline (Python CLI).** One command downloads every input file
   from the official sources (NPP, gen-re.cea.gov.in, Grid-India, cea.nic.in), checks each file's
   hash, parses it, merges and derives the tables, and writes the final dataset. It never reads from
   a local database or a previous build. Given the same release manifest, it produces byte-identical
   output. See [Reproducible rebuild](#reproducible-rebuild).
2. **The dataset.** Versioned releases (e.g. `v2026.10`) contain:
   - the normalised tables and derived metric tables, as Parquet and CSV, plus Excel workbooks
   - a data dictionary and methodology notes
   - the manifest listing the official URL and SHA-256 of every source file used
   - checksums of every output file
3. **The dashboard.** A static website (no server) that reads the released dataset in the browser.
   It shows charts and plain-language findings, and every view can be downloaded as Excel or CSV.
   See [Phase 7](#phase-7-dashboard).

A daily scheduled job keeps the dataset current. Each run fetches new reports, re-checks the last 7
days for revisions, rebuilds, and publishes the dashboard data.

## Architecture

```
 sources.yaml ──► collector ──► raw/ (immutable files + manifest) ──► parsers ──► staging (parquet)
                     │                                                    │
                     └── gap & revision detector                validators ──► warehouse (DuckDB/parquet)
                                                                                     │
                                                       reference data (stations, aliases, capacity)
                                                                                     │
                                                             metrics ──► published dataset + dashboard
```

**Stack:** these are technical calls, and nothing gets installed until you approve it.
- **Python 3.11** pipeline: `httpx` (fetching), `xlrd` (the legacy `.xls` that DGR and PSP use),
  `openpyxl` (RE `.xlsx`), `pdfplumber` (monthly PDFs, a later phase), `polars` or `pandas`, `duckdb`,
  `pydantic` (validation), `pytest`.
- **Storage:** raw files plus a manifest on **D:** (about 3–4 GB for the full backfill). Normalised tables
  as **Parquet**, queried with **DuckDB**. That is light on 8 GB RAM and needs no server.
- **Dashboard:** a static site that reads Parquet through **DuckDB-WASM** in the browser, hosted on
  GitHub Pages. There is no backend to run. Visual direction is your call.
- **Scheduling:** a daily job. Where it runs depends on Phase 0 finding 5 (can the Indian government
  sites be reached from GitHub Actions?). The fallback is Windows Task Scheduler on this laptop.

## Repository layout

```
pipeline/
  sources.yaml          # every report: URL pattern / API, cadence, first available date, parser
  collect/              # npp.py, gen_re.py, grid_india.py, cea_site.py
  parse/                # dgr_sr2.py, dgr_sr10.py, dgr_sr17.py, re_daily.py, psp.py, ...
  validate/             # schema + cross-report checks
  reference/            # station master, alias resolution, capacity
  events/               # outage event reconstruction
  metrics/
  insights/             # rule-based findings text, computed from metric tables
  export/               # parquet / csv / xlsx writers (deterministic settings)
  cli.py                # observatory rebuild | refresh | collect | parse | validate | build | export
releases/{version}/manifest.lock.json   # source URLs + SHA-256 + parser versions + output checksums
requirements.lock       # pinned dependency versions with hashes
data/                   # gitignored; points at D:\... via config
  raw/{source}/{report}/{YYYY}/{file}
  manifest.parquet
  warehouse/*.parquet
reference/              # versioned CSVs: stations.csv, station_aliases.csv, reason_classes.csv, states.csv
docs/                   # data dictionary, methodology, source notes
dashboard/
tests/fixtures/         # one real sample file per report per format era
```

## Data model (core tables)

| Table | Grain | From |
|---|---|---|
| `source_file` | one downloaded file | collector: url, fetched_at, sha256, bytes, http status, report_code, report_date, parser_version, `supersedes` |
| `data_gap` | source × report × date | collector: 404, empty or unparseable files, with a reason. **Never filled with estimates** |
| `gen_unit_daily` | date × station × unit | DGR SR-2: monitored MW, program MU, actual MU, cap under outage, file_id |
| `gen_fuel_daily` | date × fuel | DGR SR-17 (conventional, gross) |
| `re_state_daily` | date × state × source | Daily RE `State-Wise` sheet (net, state-embedded) |
| `re_station_daily` | date × station | Daily RE `ISGS` sheet (operational MW, net MU) |
| `grid_mix_daily` | date × region × source | PSP section G (gross, includes RES) |
| `grid_mix_15min` | timestamp × source | PSP SCADA table (once its start date is known) |
| `state_supply_daily` | date × state | PSP section C: max demand met, shortage MW, energy met, energy shortage |
| `outage_snapshot` | date × station × unit | DGR SR-10 (+ SR-2 outage columns for hydro and gas): MW by planned / forced-major / forced-minor / other, start, sync, raw reason |
| `outage_event` | one outage of one unit | reconstructed: start, end (or open), `end_observed`, max MW, reason class, days seen |
| `capacity_monthly` | month × state × source | CEA installed-capacity PDF (later phase) |
| `station` / `station_alias` | station | curated master: canonical name, state, region, fuel, sector, owner, plus every raw spelling seen |

Each fact row carries `file_id`, so any number can be traced back to the original file and URL.

## Rules the pipeline enforces

- **Raw files are immutable.** A re-download with a different hash becomes a new `source_file` with
  `supersedes` set. The revision replaces the old values for that report-date, and is never added
  alongside them as a second observation.
- **Dates are reporting dates.** A file for date D downloaded on D+1 is still D. Revisions are detected by
  re-fetching the last 7 days and comparing hashes.
- **Missing stays missing.** A 404 or an unparseable file goes into `data_gap`. Metrics report coverage
  instead of interpolating.
- **One basis per comparison.** Gross and net are never mixed in a single share or total. Every table has a
  `basis` column.
- **No double-counting.** For daily RE, use `State-Wise` + `ISGS` and never the `Generation` sheet on top of them.
  For CEA conventional + CEA RE, hydro comes only from the DGR. (Need to check: does the RE report's
  "others" include small hydro?)
- **Format drift fails loudly.** Each parser checks its header signature. An unknown layout stops that
  report and raises an alert instead of guessing.
- **Polite fetching.** About 1 request per second, a descriptive User-Agent, retry with backoff.

## Reproducible rebuild

**The two commands:**

```
observatory refresh                                   # pull the latest from official sources → new version
observatory rebuild --manifest releases/v2026.10/manifest.lock.json [--fresh]
```

**What `rebuild` does:**
1. Reads the manifest, which lists every source file by official URL and expected SHA-256, plus the
   parser and code version.
2. Downloads each file from its official URL. With `--fresh`, any local download cache is ignored and
   everything comes straight from the sources. Without it, cached files are reused only if their hash
   matches the manifest. A full fresh rebuild takes about 7 hours at polite request rates.
3. Verifies every hash, runs the same parsers, merges, derives the metrics, and writes all outputs.
4. Compares the output checksums with the manifest and reports PASS or the exact files that differ.

**What makes the output byte-identical:**
- Pinned Python version and `requirements.lock`.
- Stable row ordering on every table.
- Fixed Parquet and XLSX writer settings, with no build timestamps written into files.
- No randomness and no network-dependent logic beyond the listed URLs.

**The only non-source inputs are curated mapping files in `reference/`** (station aliases, reason
classes, state codes). They are versioned code, documented, and recorded in the manifest. Every
merge and transformation is in code. Nothing is edited by hand in the data.

**Honest limit: the government sites can revise or delete files.** If a file's hash no longer matches,
or it returns 404, `rebuild` stops and names exactly which reports changed. It does not silently build a
different dataset. Two ways around that:
- `refresh` always works from whatever the sources serve today, and produces a new version.
- To make old versions rebuildable forever, the raw files would also need archiving, which depends on
  the licence check in Phase 0.

## Metrics (as the data actually supports them)

| Metric | Definition | Scope / caveat |
|---|---|---|
| Generation share | source MU / total MU | From **PSP gross**, daily, by region, since 2013. CEA-based shares only within one basis |
| Capacity factor | actual MU ÷ (MW × 24 h / 1000) | Conventional: per unit or station, using monitored MW (daily). RE: per ISGS station (daily, from 2024-06); per state using monthly installed MW. **Caveat:** rooftop and behind-the-meter capacity is in installed MW but not in grid generation, so state RE capacity factors read low. Use grid-scale capacity where it can be separated |
| Output variability | CV and day-over-day change of daily output normalised by capacity, computed within month or season | Shows resource variability. It is **not** reported as unreliability |
| Capacity unavailability | Σ outage MW ÷ monitored MW, daily | Thermal, nuclear, hydro only. Split planned / forced / fuel / commercial |
| Unit outage rate | unavailable unit-hours ÷ observed unit-hours | From reconstructed events. Only events with an observed end count toward duration stats. Open events are reported separately |
| Generation shortfall | program MU − actual MU | Conventional only (daily, MTD, YTD) |
| Unmet demand | PSP energy shortage MU, peak shortage MW | State level. Labelled as unmet demand, **not** consumer interruptions |

**Outage reason classes**, kept in a curated `reasons.csv` that maps raw text to a class:
- `planned`
- `forced_equipment`
- `fuel_supply` (coal shortage, no FSA)
- `commercial` (RSD/low schedule, reserve shutdown)
- `long_term_or_retired` (likely to be scrapped, out for over a year)
- `regulatory_or_other`

This is how the pipeline keeps "the unit broke" separate from "the unit wasn't needed". That is the idea's key rule, applied to thermal plants.

## Phases

### Phase 0: Spikes (first; go/no-go on the open questions)
1. Approve and install the Python dependencies. Parse one real file for each core report (SR-2, SR-10, SR-17, daily RE, PSP).
2. **Format-drift sample:** download about 40 dates spread across 2018–2026 (and PSP back to 2013). Group them by header signature and record the format eras.
3. Settle the open questions: SR-7 and SR-10A history, hydro outage completeness in SR-2, PSP XLS availability by year, when the 15-min table starts, and whether RE "others" includes small hydro.
4. Test whether NPP, gen-re and Grid-India can be reached from GitHub Actions, then decide where the schedule runs.
5. Check licence and terms for reuse and redistribution, to decide whether raw files can be republished or only derived data.

**Exit:** a short note listing each format era and the decisions taken. Parsers for all core reports work on the samples.

### Phase 1: Collector and raw archive
- Build the `sources.yaml` registry, one collector per source (NPP URL pattern, gen-re URL pattern, Grid-India listing API, CEA HTML listing), the manifest, hashing, revision detection and the gap log.
- CLI: `collect --source npp --date 2026-10-12`, `collect --since 7d`.

### Phase 2: Parsers and validation
- Stateful parser for SR-2 (region → state → sector → type → station → unit). Flat parsers for SR-10/17, RE and PSP.
- Validators:
  - sums match the report's own totals (SR-2 vs SR-17, PSP regional vs All-India)
  - units and ranges are plausible (capacity factor between 0 and 1.05)
  - dates are consistent
- Fixtures and tests for each format era found in Phase 0.

### Phase 3: Reference data
- Station master and alias table, bootstrapped from SR-2 station names and capacities, then curated. ISGS RE names are messy (e.g. "PVT LDT" typos).
- Reason-class mapping. State and region code table, which has to handle the J&K/Ladakh split and the DNH & DD merger.

### Phase 4: Outage event reconstruction
- Link daily snapshots by (station, unit, outage start). Close an event when a sync time appears, or when the unit disappears from the list (the end time is then marked inferred-window, not exact).
- Treat data gaps as "unknown", never as "available".
- Cross-check against SR-12 to SR-15 (out >15 days, recommissioned, went out).

### Phase 5: Backfill
- DGR from 2018-04-01, daily RE from 2024-06-30, PSP from 2013-04. That is about 25k requests, roughly 7 hours at 1 req/s, resumable.
- Coverage report by source and year.

### Phase 6: Metrics, insights and the published dataset
- Metric tables plus `docs/data_dictionary.md` and `docs/methodology.md`, which state the caveats above.
- **Insights engine:** rule-based, deterministic findings computed from the metric tables, not written
  by an AI model. Example: "Renewables supplied 15.9% of gross generation on 12 Oct 2026, up from X% a
  year earlier." Each finding carries:
  - the period and source it covers
  - its caveat, where one applies
  - a "correlation, not causation" label wherever two series are compared
- **Exports:**
  - Parquet and CSV for every table.
  - **Excel workbooks.** Each one has the data sheets plus a `README`, a `dictionary` sheet and a
    `sources` sheet (URLs and hashes).
  - Excel caps a sheet at 1,048,576 rows. The unit-level daily table (about 5 M rows) is therefore
    split **one workbook per year**. Aggregated tables fit in a single workbook.
- `rebuild` and `refresh` from the section above, with a manifest and checksums for every release.
- Publish versioned releases on GitHub Releases, or wherever Phase 0 licensing allows.

### Phase 7: Dashboard

A static site that reads the release files in the browser (DuckDB-WASM). Each page has charts, a
short "what this shows" findings panel from the insights engine, a coverage strip (which dates have
data), and a **Download this view** button (Excel / CSV) that exports exactly the filtered data on
screen.

**1. Overview**
- Headline numbers for the latest day, month and year: total generation, renewable share,
  non-fossil share, peak demand, unavailable capacity, unmet demand.
- Year-on-year change for each, plus the top findings this week.

**2. Sustainable vs unsustainable**
- Share over time, renewable / fossil / nuclear (stacked area, daily → monthly → yearly toggle).
- Annual generation by group (bars), and the non-fossil share trend.
- Renewable share by region and by state (map + ranked bars).
- Seasonality heatmap (month × year of renewable share).
- A day in the grid: 15-min generation by source, showing solar midday and the evening ramp met by
  coal and hydro (from the PSP SCADA table).
- Program vs actual by fuel: who over- or under-delivers against plan.

**3. Comparing sustainable sources (solar, wind, hydro, biomass and others, nuclear shown alongside)**
- Generation trend per source, and the gap between capacity growth and generation growth.
- Capacity factor by source, by state and over the seasons (monsoon wind and hydro peaks, solar dips).
- Variability: day-to-day swing per source, with the note that variability is not unreliability.
- Complementarity: how solar and wind (and hydro) offset each other through the year (correlation).
- Station league table for ISGS-connected solar and wind plants (capacity factor, consistency).
- Where renewables are generated: state concentration (e.g. Rajasthan and Gujarat's share of solar).

**4. Outages and availability (thermal, nuclear, hydro)**
- Unavailable MW over time, split by fuel and by reason (planned / forced equipment / fuel supply /
  commercial / long-term).
- Unavailable capacity as a share of capacity, by fuel: which sources lose the most to outages.
- Outages by region and state (map), and top stations by forced-outage MW-days.
- Outage duration distribution and repeat failures (units that trip again and again).
- Most common causes (tube leakage, flame failure, etc.) and how they change over time.
- Seasonal pattern of outages (planned maintenance before summer peak vs forced outages in peak).
- Stranded capacity: units out more than a year, units with no fuel agreement.
- Fuel link: coal stock days vs fuel-supply outages (both reported in SR-2).
- Panel stating that solar and wind unit outages are not published by any official source.

**5. Supply and demand**
- Peak demand met, energy met and unmet demand by state.
- Shortage at solar hours vs non-solar hours.
- Unmet demand next to generation outages (shown side by side, labelled as correlation only).

**6. Station explorer**
- Search any station: location, fuel, capacity, generation history, capacity factor, program vs
  actual, outage timeline, and links to the source files behind each number.

**7. Data & downloads**
- Full dataset catalogue, with each table in Parquet / CSV / Excel, the data dictionary, a coverage
  calendar (gaps per source), the release manifest, and how to run `observatory rebuild` yourself.

**8. Methodology**
- Sources, definitions, gross vs net, what is and isn't measured, and known data issues.

Look and feel: your direction.

### Phase 8 (optional): Extensions
- Monthly RE and installed-capacity PDF extraction, for RE capacity factors before 2024 and for capacity by state.
- Grid-India RE curtailment, to give renewables an "availability" story.
- SAIFI/SAIDI for the states whose regulators publish usable series.

## Risks, updated

| Risk | Handling |
|---|---|
| RE daily history only from mid-2024 | PSP covers the RE mix from 2013 (regional, gross). Monthly RE PDFs from 2016 in Phase 8 |
| Gross vs net mismatch | `basis` column. Shares computed within one basis only |
| Outage reports are snapshots, not events | Phase 4 reconstruction. Durations only when an end is observed |
| Commercial and fuel outages mistaken for failures | Reason classes. Forced-equipment shown separately |
| Station name inconsistency | Curated alias table. Unresolved names flagged, never auto-merged |
| Format drift / site redesign | Header signatures, fail loudly, fixtures for each era |
| Government sites blocking cloud runners | Phase 0 test. Local scheduler fallback |
| Licence limits on redistributing raw files | Phase 0 check. If needed, publish derived data plus source URLs and hashes only |

## Decisions I need from you

1. **Source roles:** OK to make Grid-India PSP the source for the generation mix (CEA stays primary for stations and outages)? This changes the idea's "CEA primary" wording.
2. **History depth:** unit-level from 2018-04 is fixed by CEA. Should the mix go back to 2013 via PSP, or start in 2018 to match?
3. **Install approval** for the Phase 0 Python packages listed above.
