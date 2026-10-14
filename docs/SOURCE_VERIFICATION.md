# Source verification: Indian Energy Generation Observatory

Checked 2026-10-14 against live sites, with sample files downloaded and opened. "Verified" below means
I fetched the file and read its contents, not just found a link to it.

## Verdict in one paragraph

The idea is feasible on official data, and CEA is a sound primary source. But the idea assumes one
CEA feed covers every energy source, and that is not true. CEA's daily generation report covers
**conventional plants only** (coal, lignite, gas, diesel, naphtha, nuclear, large hydro, Bhutan
imports). Solar, wind and biomass come from a **separate CEA portal** that only goes back to
**30 June 2024**. **No official source publishes unit outages for solar or wind**, so the
"outage rate: renewable vs non-renewable" comparison cannot be done as written. The fix is to
use Grid-India's daily Power Supply Position (PSP) report, which is official, covers all sources on
one consistent gross basis and goes back to 2013. It should be the source for the generation mix,
with CEA kept for station- and unit-level detail and for outages.

## Sources checked

| # | Source | Publisher | What it gives | Format | Archive depth (verified) | Access |
|---|---|---|---|---|---|---|
| 1 | Daily Generation Report (DGR), 17 sub-reports | CEA (OPM Division), served from **National Power Portal** `npp.gov.in` | Conventional generation by region/state/sector/fuel/station/unit; program vs actual; outages | XLS (JasperReports BIFF) + PDF | **2018-04-01 → today**, with gaps (e.g. Apr–May 2020 missing) | Fixed URL pattern, plain HTTP GET |
| 2 | Daily Renewable Generation Report | CEA (Renewable Project Monitoring Div.), `gen-re.cea.gov.in` | Wind / solar / other RES by state; station-level for ISGS-connected RE | XLSX + PDF | **2024-06-30 → today**, 781 reports (some days missing) | Fixed URL pattern |
| 3 | Monthly Renewable Generation Report | CEA, `cea.nic.in` | Monthly RE generation | **PDF only** | **Apr 2016 → Aug 2026** | UUID links in an HTML listing |
| 4 | Monthly Installed Capacity Report | CEA, `cea.nic.in` | Installed capacity by state and source, RE included | **PDF only** | **Jan 2017 → Aug 2026** (plus Mar 2014–16) | UUID links |
| 5 | Monthly generation, "18-column" actual and tentative | CEA via NPP | Monthly conventional generation (20 sub-reports) | XLS + PDF | **~Sep 2019 → Aug 2026** | Fixed URL pattern |
| 6 | Daily PSP Report | **Grid-India / NLDC** (Govt. of India enterprise, formerly POSOCO) | All-India and regional **gross** generation by source **including RES**; generation outage MW; state demand met and **energy shortage**; 15-min SCADA generation by source | XLS + PDF | **FY 2013-14 → today** (listing API) | JSON API `webapi.grid-india.in/api/v1/file` (filenames carry random suffixes, so they must be looked up through the API) |
| 7 | RE Curtailment, Tripping, Monthly Grid Disturbance reports | Grid-India | Context for RE availability and grid events | PDF | Not checked in depth | Same API |

URLs and patterns:

- DGR: `https://npp.gov.in/public-reports/cea/daily/dgr/{DD-MM-YYYY}/dgr{N}-{YYYY-MM-DD}.xls`
  (`cea.nic.in/reports/external/daily-generation` redirects to `npp.gov.in/publishedReports`)
- Daily RE: `https://gen-re.cea.gov.in/public/uploads/dailyReport/excel/Report-{YYYY-MM-DD}.xlsx`
- Monthly gen: `https://npp.gov.in/public-reports/cea/monthly/generation/18_col_act/{YYYY}/{MON}/18_col_act-{N}_{YYYY}-{MON}.xls`
- PSP listing: `POST webapi.grid-india.in/api/v1/file` with `{"_source":"grdw","_type":"DAILY_PSP_REPORT","_fileDate":"2026-27","_month":"10"}`.
  The files are then served from `https://webcdn.grid-india.in/{FilePath}`. The old `report.grid-india.in` host did not respond.

## DGR sub-reports (from the 12-10-2026 listing)

| No. | Title | Use for us |
|---|---|---|
| 1 | All India / Region-wise generation overview | Totals cross-check |
| **2** | Region / State / Sector / Type / **Station / Unit**-wise generation | **Core**: unit capacity, program MU, actual MU, capacity under outage, outage time, sync time, remarks |
| 3, 4 | All-India summary; region/utility summary | Cross-check |
| 5 | Region-wise availability (>25 MW) | Availability context |
| 6 | Hydro reservoir | Hydro context |
| 7 | Daily Outage Report (Hydro units) | **Listed, but no file on 12-10-2026** |
| 8, 9 | NTPC overview and stations | Not needed (subset of 2) |
| **10** | Daily Outage Report (Coal, Lignite, Nuclear) | **Core outage table** |
| 10A | Daily Outage Report (other than Coal/Lignite/Nuclear) | **Listed, but no file on 12-10-2026** |
| 11 | Outage of units ≥500 MW | Subset of 10 |
| 12–15 | Out >15 days; out >1 year; recommissioned; went out of grid | Event validation |
| 16 | Capacity utilisation | Cross-check |
| **17** | Category-wise, fuel-wise generation | **Core daily fuel mix (conventional)** |

## What a real file contains

**Sub-Report 17 (12-Oct-2026).** Coal, lignite, natural gas, diesel, HSD, naphtha, nuclear, hydro and Bhutan
import, each with monitored capacity (MW) plus program and actual MU for the day, the month to date and the
year to date. Monitored capacity totals **313,364 MW**. There is no solar or wind row.

**Sub-Report 10 (12-10-2026), 8 pages.** One row per unit, with these columns:
- state, station, unit no.
- MW split into **Planned / Forced (Major) / Forced (Minor) / Others**
- outage start (date and time)
- expected or actual sync time
- free-text reason

That day's totals were 6,138 MW planned, 4,491 MW forced-major and 19,253 MW forced-minor. Some details matter
for parsing:
- The sync time is filled in only for units that **returned that day**. Those rows show 0 MW.
- The report includes very old, never-ended outages, for example "No Fuel Supply Agreement" since 2012,
  "Unit likely to be scrapped", "Reserve shutdown" since 2016 and a nuclear unit out since 2004.
- Some rows are **commercial, not technical**. Examples are "RSD/LOW SCHEDULE" (reserve shutdown or low
  schedule) and "COAL SHORTAGE".

**Sub-Report 2, 2018 vs 2026.** The column headers are identical:
- monitored capacity, today's program and actual
- April-to-date program and actual
- coal stock in days
- capacity under outage, outage date, expected/sync date, remarks

The layout is hierarchical (region → state → sector → type → station → unit), so the parser has to
track state as it reads rows. The format has stayed the same for 8 years, which makes a backfill realistic.

**Daily RE (12-10-2026).** The workbook has three sheets: `Generation` (all-India), `ISGS` (per station, with
operational MW) and `State-Wise`. The state values are **net** MU. The `Generation` sheet already equals
State-Wise + ISGS. For example, Rajasthan solar is 228 = 49 (state) + ISGS stations. **Summing the sheets
double-counts.**

**PSP (12-10-2026).** It contains:
- source-wise gross generation per region: coal 3,941 MU, lignite 90, hydro 469, nuclear 192, gas 111,
  RES 905, total 5,708. RES share is 15.9% and non-fossil share 27.5%.
- generation outage MW (central and state sectors): 37,821 MW
- state demand met and energy shortage (MU)
- a 96-interval all-India SCADA table by source

The report itself lists several caveats:
- "Limited visibility of embedded solar".
- Behind-the-meter and rooftop generation are excluded.
- The data is subject to telemetry errors.

## Claims in the idea, checked

| Claim in the idea | Status | Notes |
|---|---|---|
| CEA publishes daily and monthly generation | ✅ Verified | Daily since 2018-04 (NPP), monthly XLS since ~2019-09, monthly RE PDF since 2016-04 |
| Covers "solar, wind, hydro, coal, lignite, gas, nuclear" | ⚠️ **Partly** | The DGR is conventional only. RE is in a separate report, daily only from 2024-06-30. Before that, use PSP (daily, gross, regional) or monthly RE PDFs |
| Station-level "where available" | ✅ Conventional, unit-level · ⚠️ RE | RE stations only for ISGS-connected plants. State-embedded RE is state totals only |
| Installed capacity | ✅ Conventional (monitored MW per unit, daily) · ⚠️ RE | RE capacity by state comes only from the monthly **PDF** report, so it needs PDF table extraction |
| Outage records with station, capacity, status, start/end | ✅ Conventional | Start time always present. End time only on the day the unit returns. Reports are **daily snapshots**, so events have to be reconstructed |
| Outage rate for renewables | ⚠️ **No unit-level list, but proxies exist** (revised 2026-10-14, see below) | No official per-unit outage list for solar or wind. Grid-India publishes daily unavailable RE capacity (REMC) and event-level RE plant trips (monthly grid disturbance reports). Hydro outages are available via Sub-Report 2 |
| "Planned generation" for shortfall | ✅ Conventional | "Program" MU daily, MTD and YTD. ❌ Not in the daily RE report |
| Region / state mapping | ✅ | Every report is grouped by region and state |
| Consumer interruption data (SAIFI/SAIDI) | ⚠️ **No consistent national official dataset** | See below |
| "Some reports exclude renewables" (risk table) | ✅ Correct, and it is the main risk | Plus a gross vs net mismatch (DGR and PSP are gross, daily RE is net) |

## Solar and wind outages (follow-up check, 2026-10-14)

I checked every candidate source after the first pass:
- **Grid-India daily REMC report** (`DAILY_VRE_REPORT`, PDF, archive from FY 2024-25). Each day it gives solar and
  wind **installed vs maximum available capacity** by region, for inter-state plants, and for 8 RE-rich states. It
  also gives curtailment by pooling station, with reasons. Installed minus available is a daily unavailable-capacity
  measure. It is aggregate, not per plant.
- **Grid-India monthly grid disturbance reports** (`MONTHLY_GRID_DISTURBANCE`, PDF, archive from 2016-17). Every
  disturbance is listed with start, end, MW of generation lost and a narrative naming the plants (for example
  "Generation loss of 76.4 MW occurred at Chugger (SITAC) Wind Power Plant due to loss of evacuation path").
  In Oct 2025 – Sep 2026, about 114 of 532 events involved solar or wind plants. These are **event-level RE plant
  outages**, mostly caused by trips of the evacuation line or substation, not faults inside the plant.
- **Grid-India tripping report** (one-off PDFs such as the Khavda RE complex event of 13 May 2026). These are scanned
  images, so they were not used.
- **RLDC generation outage reports** (for example SRLDC `unit` daily PDF). These cover thermal, nuclear and hydro units
  only, with no solar or wind. The WRLDC tripping portal timed out, and the SRLDC tripping reports need a login.
- **CEA daily RE report (ISGS sheet).** There is no outage column. A whole day of zero output at a solar station,
  however, is a strong sign it was unavailable. That is used as a **derived proxy**, labelled as such.

Data quality note: 25 REMC files are titled for one date but contain another day's report. The parser's date check
rejects them, and they are listed in `data_gaps`.

## Consumer supply layer: what exists

- **Grid-India PSP: state-wise energy shortage (MU) and peak shortage (MW), daily since 2013.** This is official
  and consistent. It measures unmet demand at state level, the closest national proxy for load-shedding.
  It is not SAIFI or SAIDI.
- **CEA reliability indices (SAIFI/SAIDI by discom).** CEA published these for some years (e.g. 2016-17), with
  many "data not furnished" entries. I did not find a current edition.
- **REC Consumer Service Rating of DISCOMs (CSRD).** Annual. It uses SAIFI and hours of supply in its scoring,
  but the underlying outage data is not published.
- **Discom and SERC Standards-of-Performance filings** (e.g. Tata Power Mumbai monthly SAIDI/SAIFI). These are
  real, but each state uses different definitions. A 2025 review found only 17 of 36 discoms report
  SAIFI/SAIDI, and they calculate them inconsistently.
- **National Feeder Monitoring System (REC/MoP).** It covers about 2.5 lakh feeders. I could not confirm it
  is publicly accessible.

Recommendation: make the consumer layer PSP state shortage only, labelled "unmet demand", not
"interruptions". Treat SAIFI/SAIDI as an optional, state-by-state add-on later.

## Not yet verified (to be settled in Phase 0 of the plan)

1. Whether DGR Sub-Reports 7 and 10A existed historically, and whether the hydro and gas outage columns in Sub-Report 2 are complete.
2. Whether PSP XLS exists for older years. The 2013 entries are listed as PDF, and the date the 15-min table first appears is unknown.
3. How far the format drifts across 2018–2026. I compared one date at each end only.
4. Licence and reuse terms for NPP, CEA and Grid-India files. Grid-India says its data is "as is". The data.gov.in GODL licence may not cover these sites.
5. Whether these sites can be reached from cloud CI (GitHub Actions runs on US servers). `report.grid-india.in` failed even from here.
6. How revisions show up. DGR has a "Report Version" field, and NPP regenerated the 12-Oct files on 13-Oct.

## References

- CEA daily generation (redirects to NPP): https://cea.nic.in/reports/external/daily-generation?lang=en → https://npp.gov.in/publishedReports
- NPP DGR archive (date picker): https://npp.gov.in/dgrReports
- CEA daily RE portal: https://gen-re.cea.gov.in/reports
- CEA monthly RE generation: https://cea.nic.in/reports/dashboardView?headingId=107&subHeadingId=1003&subSubHeadingId=10068&lang=en
- CEA installed capacity: https://cea.nic.in/reports/dashboardView?headingId=107&subHeadingId=1003&subSubHeadingId=10014&lang=en
- Grid-India daily PSP: https://grid-india.in/en/reports/daily-psp-report
- CEA OPM page (outage data submission manual): https://cea.nic.in/old/opm.html
- India Data Portal, Daily Power Outage dataset (compiled from NPP): https://ckandev.indiadataportal.com/dataset/power/resource/abd6d0f5-b948-4c2e-9ca8-459721ee888d
- LEAP Journal, review of discom outage reporting (2025): https://blog.theleapjournal.org/2025/09/a-review-of-outage-reporting-by-indian.html
- CEA reliability indices 2016-17: https://cea.nic.in/wp-content/uploads/2020/04/rel_ind-2017.pdf
- REC CSRD coverage: https://powerline.net.in/2022/11/11/consumer-services-rating-of-discoms-csrd-report-rec/
- NFMS launch coverage: https://www.energetica-india.net/news/union-minister-manohar-lal-inaugurates-nfms-control-centre-at-recs-headquarters
