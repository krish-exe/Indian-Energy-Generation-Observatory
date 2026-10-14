"""Parsers for each official report. Every parser checks the report's own title and date and raises
FormatError if the layout is not the one it knows, so format drift fails loudly instead of guessing."""
from __future__ import annotations

import datetime as dt
import re

import openpyxl
import xlrd

from . import reference as ref


class FormatError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def _num(v):
    if v is None or v == "" or v == "-":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\s+", " ", str(v)).strip()


_DT_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M")


def _datetime(v, datemode: int = 0) -> str | None:
    """Excel serial or 'dd/mm/yyyy hh:mm' text -> ISO 'YYYY-MM-DDTHH:MM'."""
    if v is None or v == "":
        return None
    if isinstance(v, float):
        return xlrd.xldate_as_datetime(v, datemode).strftime("%Y-%m-%dT%H:%M")
    s = _txt(v)
    for f in _DT_FORMATS:
        try:
            return dt.datetime.strptime(s, f).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    return None


def _row(sh, r):
    return [sh.cell_value(r, c) for c in range(sh.ncols)]


def _find_col(header_rows: list[list], *needles: str) -> int:
    for row in header_rows:
        for c, v in enumerate(row):
            t = _txt(v).upper()
            if all(n in t for n in needles):
                return c
    raise FormatError(f"header column {needles} not found")


def _check_date(found: dt.date, expected: dt.date, what: str) -> None:
    if found != expected:
        raise FormatError(f"{what}: file is for {found}, expected {expected}")


# ---------------------------------------------------------------- CEA DGR sub-report 2

def parse_sr2(path, date: dt.date):
    """Region > state > sector > type > station > unit generation. Returns (stations, units)."""
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    title = _txt(sh.cell_value(1, 0)).upper()
    if "UNIT WISE GENERATION REPORT" not in title:
        raise FormatError(f"SR-2 title not recognised: {title[:80]}")
    m = re.search(r"(\d{2}/\d{2}/\d{4})", title)
    if not m:
        raise FormatError("SR-2 date missing from title")
    _check_date(dt.datetime.strptime(m.group(1), "%d/%m/%Y").date(), date, "SR-2")

    hdr = [_row(sh, r) for r in range(2, 5)]
    c_cap = _find_col(hdr, "MONITORED")
    c_prog = _find_col(hdr, "TODAY'S", "PROGRAM")
    c_act = _find_col(hdr, "TODAY'S", "ACTUAL")
    c_ytd = _find_col(hdr, "APRIL 1")
    c_coal = _find_col(hdr, "COAL STOCK")
    c_out = _find_col(hdr, "CAP. UNDER")
    c_odate = _find_col(hdr, "OUTAGE DATE")
    c_sync = _find_col(hdr, "EXPECTED DATE")
    c_rem = _find_col(hdr, "REMARKS")

    def first_label(row, lo=1, hi=7):
        for c in range(lo, min(hi, len(row))):
            t = _txt(row[c])
            if t:
                return t
        return ""

    labels = [_txt(sh.cell_value(r, 0)) for r in range(sh.nrows)]

    def next_label(r):
        for k in range(r + 1, sh.nrows):
            if labels[k]:
                return labels[k].upper()
        return ""

    stations, units = [], []
    region = state_raw = sector = ptype = ""
    station = None
    for r in range(5, sh.nrows):
        a = labels[r]
        if not a:
            continue
        au = a.upper()
        row = _row(sh, r)
        if au.startswith(("REGION TOTAL", "STATE TOTAL")) or au.startswith("HTTPS://"):
            continue
        if au.startswith("SECTOR:"):
            sector = first_label(row)
            continue
        if au.startswith("TYPE:"):
            ptype = first_label(row)
            continue
        if au == "UNIT":
            if station is None:
                raise FormatError(f"SR-2 row {r}: unit row before any station")
            unit_no = first_label(row, 1, c_cap)
            prev = units[-1] if units else None
            if (prev and prev["station_id"] == station["station_id"] and prev["unit_no"] == unit_no
                    and prev["capacity_mw"] == _num(row[c_cap]) and prev["actual_mu"] == _num(row[c_act])):
                # A long remark wraps onto a repeated unit row: merge the text, keep one record.
                extra = _txt(row[c_rem])
                if extra and extra not in prev["remarks"]:
                    prev["remarks"] = f"{prev['remarks']} {extra}".strip()
                continue
            units.append({
                "date": date.isoformat(), "station_id": station["station_id"], "station": station["station"],
                "unit_no": unit_no, "unit_id": f"{station['station_id']}-u{ref.slug(unit_no)}",
                "region": station["region"], "state": station["state"], "state_code": station["state_code"],
                "sector": station["sector"], "fuel": station["fuel"],
                "capacity_mw": _num(row[c_cap]), "program_mu": _num(row[c_prog]), "actual_mu": _num(row[c_act]),
                "ytd_program_mu": _num(row[c_ytd]), "ytd_actual_mu": _num(row[c_ytd + 1]),
                "cap_under_outage_mw": _num(row[c_out]),
                "outage_start": _datetime(row[c_odate], wb.datemode), "sync_time": _datetime(row[c_sync], wb.datemode),
                "remarks": _txt(row[c_rem]),
            })
            station["n_units"] += 1
            continue
        if _num(row[c_cap]) is None:
            nxt = next_label(r)
            if nxt.startswith("REGION TOTAL"):
                region = ref.REGIONS.get(au, a.title())
                state_raw = sector = ptype = ""
            elif nxt.startswith("STATE TOTAL"):
                state_raw = a
                sector = ptype = ""
            continue
        prev = stations[-1] if stations else None
        if (prev and prev["station"] == a and prev["capacity_mw"] == _num(row[c_cap])
                and prev["actual_mu"] == _num(row[c_act])):
            extra = _txt(row[c_rem])  # wrapped remark repeated the station row
            if extra and extra not in prev["remarks"]:
                prev["remarks"] = f"{prev['remarks']} {extra}".strip()
            continue
        st = ref.state(state_raw)
        code, sname = (st[0], st[1]) if st else ("", state_raw.title())
        fuel = ref.fuel_for(ptype, a, region)
        station = {
            "date": date.isoformat(), "station_id": ref.slug(code or sname, a), "station": a,
            "region": region, "state": sname, "state_code": code, "sector": sector.title(),
            "plant_type": ptype, "fuel": fuel, "category": ref.CATEGORY.get(fuel, "unknown"),
            "capacity_mw": _num(row[c_cap]), "program_mu": _num(row[c_prog]), "actual_mu": _num(row[c_act]),
            "ytd_program_mu": _num(row[c_ytd]), "ytd_actual_mu": _num(row[c_ytd + 1]),
            "coal_stock_days": _num(row[c_coal]), "cap_under_outage_mw": _num(row[c_out]),
            "outage_start": _datetime(row[c_odate], wb.datemode), "sync_time": _datetime(row[c_sync], wb.datemode),
            "remarks": _txt(row[c_rem]), "n_units": 0,
        }
        stations.append(station)
    if len(stations) < 100:
        raise FormatError(f"SR-2: only {len(stations)} stations parsed")
    return stations, units


# ---------------------------------------------------------------- CEA DGR sub-report 10

def parse_sr10(path, date: dt.date):
    """Daily maintenance (outage) report for coal, lignite and nuclear units."""
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    top = " ".join(_txt(sh.cell_value(r, c)) for r in range(0, 4) for c in range(sh.ncols)).upper()
    if "DAILY MAINTENANCE REPORT" not in top:
        raise FormatError("SR-10 title not recognised")
    m = re.search(r"(\d{2}-\d{2}-\d{4})", top)
    if m:
        _check_date(dt.datetime.strptime(m.group(1), "%d-%m-%Y").date(), date, "SR-10")
    hdr_r = next(r for r in range(sh.nrows) if "POWER STATION" in _txt(sh.cell_value(r, 3)).upper()
                 or any("POWER STATION" in _txt(v).upper() for v in _row(sh, r)))
    hdr = [_row(sh, hdr_r)]
    c_state = _find_col(hdr, "STATE")
    c_stn = _find_col(hdr, "POWER STATION")
    c_unit = _find_col(hdr, "UNIT")
    c_plan = _find_col(hdr, "PLANNED")
    c_fmaj = _find_col(hdr, "FORCED", "MAJOR")
    c_fmin = _find_col(hdr, "FORCED", "MINOR")
    c_oth = _find_col(hdr, "OTHERS")
    c_start = _find_col(hdr, "DATE& TIME") if any("DATE& TIME" in _txt(v).upper() for v in hdr[0]) \
        else _find_col(hdr, "DATE", "MAINTENANCE")
    c_ret = _find_col(hdr, "EXPECTED")
    c_why = _find_col(hdr, "REASON")

    out, region = [], ""
    for r in range(hdr_r + 1, sh.nrows):
        row = _row(sh, r)
        a, stn = _txt(row[c_state]), _txt(row[c_stn])
        if not a and not stn:
            continue
        au = a.upper()
        if au in ref.REGIONS or au.replace(" ", "-") in ("NORTH-EASTERN",):
            region = ref.REGIONS.get(au, a)
            continue
        if au.startswith("TOTAL") or not stn or au in ("1",):
            continue
        st = ref.state(a)
        code, sname = (st[0], st[1]) if st else ("", a)
        unit_no = _txt(row[c_unit])
        sid = ref.slug(code or sname, stn)
        start = _datetime(row[c_start], wb.datemode)
        prev = out[-1] if out else None
        mws = tuple(_num(row[c]) or 0.0 for c in (c_plan, c_fmaj, c_fmin, c_oth))
        ret = _datetime(row[c_ret], wb.datemode)
        same_values = prev is not None and mws == (prev["planned_mw"], prev["forced_major_mw"],
                                                   prev["forced_minor_mw"], prev["other_mw"]) \
            and ret == prev["return_time"] and (sum(mws) > 0 or ret is not None)
        if prev and prev["unit_no"] == unit_no and prev["outage_start"] == start and prev["state"] == sname \
                and (prev["station_id"] == sid or same_values):
            # A row split across a page break: the name and reason continue on the next row.
            if prev["station_id"] != sid and stn not in prev["station"]:
                prev["station"] = f"{prev['station']} {stn}"
                prev["station_id"] = ref.slug(code or sname, prev["station"])
                prev["unit_id"] = f"{prev['station_id']}-u{ref.slug(unit_no)}"
            extra = _txt(row[c_why])
            if extra and extra not in prev["reason"]:
                prev["reason"] = f"{prev['reason']} {extra}".strip()
            continue
        out.append({
            "date": date.isoformat(), "region": region, "state": sname, "state_code": code,
            "station": stn, "station_id": sid, "unit_no": unit_no, "unit_id": f"{sid}-u{ref.slug(unit_no)}",
            "planned_mw": _num(row[c_plan]) or 0.0, "forced_major_mw": _num(row[c_fmaj]) or 0.0,
            "forced_minor_mw": _num(row[c_fmin]) or 0.0, "other_mw": _num(row[c_oth]) or 0.0,
            "outage_start": start, "return_time": _datetime(row[c_ret], wb.datemode),
            "reason": _txt(row[c_why]),
        })
    return out


# ---------------------------------------------------------------- CEA DGR sub-report 17

_SR17_FUEL = {"COAL": "COAL", "LIGNITE": "LIGNITE", "NATURAL GAS": "GAS", "DIESEL": "DIESEL",
              "HIGH SPEED DIESEL": "HSD", "NAPTHA": "NAPHTHA", "NAPHTHA": "NAPHTHA", "NUCLEAR": "NUCLEAR",
              "HYDRO": "HYDRO", "BHUTAN IMP.": "HYDRO_IMPORT"}


def parse_sr17(path, date: dt.date):
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    title = " ".join(_txt(sh.cell_value(r, c)) for r in range(0, 5) for c in range(sh.ncols)).upper()
    if "FUEL WISE GENERATION" not in title:
        raise FormatError("SR-17 title not recognised")
    m = re.search(r"(\d{2}-[A-Z]{3}-\d{4})", title)
    if m:
        _check_date(dt.datetime.strptime(m.group(1).title(), "%d-%b-%Y").date(), date, "SR-17")
    out = []
    for r in range(sh.nrows):
        row = _row(sh, r)
        label = next((_txt(v).upper() for v in row[:4] if _txt(v)), "")
        if label in _SR17_FUEL and _num(row[4]) is not None:
            vals = [_num(v) for v in row[4:11]]
            out.append({"date": date.isoformat(), "fuel": _SR17_FUEL[label],
                        "monitored_capacity_mw": vals[0], "program_mu": vals[1], "actual_mu": vals[2],
                        "mtd_program_mu": vals[3], "mtd_actual_mu": vals[4],
                        "ytd_program_mu": vals[5], "ytd_actual_mu": vals[6]})
    if len(out) < 6:
        raise FormatError(f"SR-17: only {len(out)} fuel rows")
    return out


# ---------------------------------------------------------------- CEA daily renewable report

def _re_sheet_date(ws_rows) -> dt.date | None:
    for row in ws_rows[:8]:
        for v in row:
            if isinstance(v, dt.datetime):
                return v.date()
            t = _txt(v)
            for f in ("%d-%B-%y", "%d-%b-%y", "%d-%B-%Y", "%d-%m-%Y"):
                try:
                    return dt.datetime.strptime(t, f).date()
                except ValueError:
                    pass
    return None


def parse_re(path, date: dt.date):
    """Returns (state_rows, isgs_rows). State values are state-embedded RE; ISGS are inter-state
    connected stations. The report's 'Generation' sheet equals the two together and is not used."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if not {"ISGS", "State-Wise"} <= set(wb.sheetnames):
        raise FormatError(f"RE sheets missing: {wb.sheetnames}")

    rows = [list(r) for r in wb["State-Wise"].iter_rows(values_only=True)]
    found = _re_sheet_date(rows)
    if found:
        _check_date(found, date, "RE State-Wise")
    hdr_i = next(i for i, r in enumerate(rows) if any("Wind" in _txt(v) for v in r))
    hdr = [_txt(v).upper() for v in rows[hdr_i]]
    c_wind = next(i for i, t in enumerate(hdr) if "WIND" in t)
    c_solar = next(i for i, t in enumerate(hdr) if "SOLAR" in t)
    c_oth = next(i for i, t in enumerate(hdr) if "OTHER" in t)
    states = []
    for r in rows[hdr_i + 1:]:
        name = _txt(r[0])
        if not name or "REGION" in name.upper() or "ALL INDIA" in name.upper() or "TOTAL" in name.upper():
            continue
        st = ref.state(name)
        if st is None:
            continue
        for fuel, c in (("WIND", c_wind), ("SOLAR", c_solar), ("OTHER_RES", c_oth)):
            states.append({"date": date.isoformat(), "state_code": st[0], "state": st[1], "region": st[2],
                           "fuel": fuel, "actual_mu": _num(r[c])})
    if len(states) < 60:
        raise FormatError(f"RE State-Wise: only {len(states)} rows")
    # The report still lists Daman & Diu and Dadra & Nagar Haveli separately; they are one UT since 2020.
    merged: dict[tuple, dict] = {}
    for x in states:
        k = (x["state_code"], x["fuel"])
        if k in merged:
            a, b = merged[k]["actual_mu"], x["actual_mu"]
            merged[k]["actual_mu"] = None if a is None and b is None else (a or 0.0) + (b or 0.0)
        else:
            merged[k] = dict(x)
    states = list(merged.values())

    rows = [list(r) for r in wb["ISGS"].iter_rows(values_only=True)]
    found = _re_sheet_date(rows)
    if found:
        _check_date(found, date, "RE ISGS")
    hdr_i = next(i for i, r in enumerate(rows) if _txt(r[0]).upper() == "STATION")
    hdr = [_txt(v).upper() for v in rows[hdr_i]]
    c_state = next(i for i, t in enumerate(hdr) if "STATE" in t)
    c_sector = next(i for i, t in enumerate(hdr) if "SECTOR" in t)
    c_owner = next(i for i, t in enumerate(hdr) if "OWNER" in t)
    c_type = next(i for i, t in enumerate(hdr) if t == "TYPE")
    c_cap = next(i for i, t in enumerate(hdr) if "CAPACITY" in t)
    c_gen = next(i for i, t in enumerate(hdr) if "ACTUAL" in t)
    isgs, seen = [], {}
    for r in rows[hdr_i + 2:]:
        name = _txt(r[0])
        if (not name or name.upper().startswith(("TOTAL", "GRAND")) or "REGION" in name.upper()
                or _num(r[c_cap]) is None):
            continue
        st = ref.state(_txt(r[c_state]))
        code, sname, region = st if st else ("", _txt(r[c_state]), "")
        rtype = _txt(r[c_type]).upper()
        fuel = {"SOLAR": "SOLAR", "WIND": "WIND", "HYBRID": "HYBRID"}.get(rtype, "OTHER_RES")
        sid = ref.slug("re", code or sname, name)
        seen[sid] = seen.get(sid, 0) + 1
        if seen[sid] > 1:  # same name listed twice in one day: keep both, in report order
            sid = f"{sid}-{seen[sid]}"
        isgs.append({"date": date.isoformat(), "station_id": sid, "station": name, "state_code": code,
                     "state": sname, "region": region, "sector": _txt(r[c_sector]).title(),
                     "owner": _txt(r[c_owner]), "re_type": _txt(r[c_type]), "fuel": fuel,
                     "capacity_mw": _num(r[c_cap]), "actual_mu": _num(r[c_gen])})
    if len(isgs) < 50:
        raise FormatError(f"RE ISGS: only {len(isgs)} rows")
    return states, isgs


# ---------------------------------------------------------------- Grid-India daily PSP

_PSP_REGIONS = ["Northern", "Western", "Southern", "Eastern", "North-Eastern", "All India"]
_PSP_A = {
    "DEMAND MET (MW) DURING EVENING": "evening_peak_demand_met_mw",
    "DEMAND MET DURING EVENING": "evening_peak_demand_met_mw",
    "PEAK SHORTAGE (MW)": "evening_peak_shortage_mw",
    "SHORATGE (MW) DURING EVENING": "evening_peak_shortage_mw",
    "SHORTAGE (MW) DURING EVENING": "evening_peak_shortage_mw",
    "ENERGY MET": "energy_met_mu",
    "HYDRO GEN": "hydro_gen_mu",
    "WIND GEN": "wind_gen_mu",
    "SOLAR GEN": "solar_gen_mu",
    "ENERGY SHORTAGE": "energy_shortage_mu",
    "MAXIMUM DEMAND MET DURING THE DAY": "max_demand_met_mw",
    "TIME OF MAXIMUM DEMAND MET": "time_of_max_demand",
}
_PSP_G = {"COAL": "COAL", "LIGNITE": "LIGNITE", "HYDRO": "HYDRO", "NUCLEAR": "NUCLEAR",
          "GAS, NAPTHA & DIESEL": "GAS_NAPHTHA_DIESEL", "RES (WIND, SOLAR, BIOMASS & OTHERS)": "RES",
          "TOTAL": "TOTAL"}
_TS_COLS = [  # (output name, header must contain, header must not contain)
    ("frequency_hz", "FREQUENCY", None), ("demand_met_mw", "DEMAND", "NET"),
    ("storage_demand_mw", "STORAGE DEMAND", None), ("nuclear_mw", "NUCLEAR", None),
    ("wind_mw", "WIND", None), ("solar_mw", "SOLAR", None), ("hydro_mw", "HYDRO", None),
    ("gas_mw", "GAS", None), ("thermal_mw", "THERMAL", None),
    ("storage_gen_mw", "STORAGE", "DEMAND"), ("others_mw", "OTHERS", None),
    ("net_demand_met_mw", "NET DEMAND", None), ("total_generation_mw", "TOTAL GENERATION", None),
    ("net_transnational_mw", "TRANSNATIONAL", None),
]


def _section(sh, prefix: str, start: int = 0) -> int:
    for r in range(start, sh.nrows):
        if _txt(sh.cell_value(r, 0)).upper().startswith(prefix):
            return r
    raise FormatError(f"PSP section '{prefix}' not found")


def parse_psp(path, date: dt.date):
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    rep = None
    for r in range(0, 8):  # the value to the right of the "Date of Reporting:" label
        row = _row(sh, r)
        for c, v in enumerate(row):
            if "DATE OF REPORTING" in _txt(v).upper():
                for w in row[c + 1:]:
                    if isinstance(w, float) and w > 40000:
                        rep = xlrd.xldate_as_datetime(w, wb.datemode).date()
                    elif re.match(r"\d{2}-[A-Za-z]{3}-\d{4}$", _txt(w)):
                        rep = dt.datetime.strptime(_txt(w), "%d-%b-%Y").date()
                    if rep:
                        break
        if rep:
            break
    if rep is None:
        raise FormatError("PSP reporting date not found")
    _check_date(rep - dt.timedelta(days=1), date, "PSP")
    d = date.isoformat()

    # A. region summary
    ra = _section(sh, "A. POWER SUPPLY")
    regions = {r: {"date": d, "region": r} for r in _PSP_REGIONS}
    rb = _section(sh, "B.", ra)
    for r in range(ra + 2, rb):
        label = _txt(sh.cell_value(r, 0)).upper().replace(" ", "")  # spacing varies between editions
        key = next((v for k, v in _PSP_A.items() if label.startswith(k.replace(" ", ""))), None)
        if not key:
            continue
        for i, reg in enumerate(_PSP_REGIONS):
            v = sh.cell_value(r, 2 + i)
            if key == "time_of_max_demand":
                regions[reg][key] = _txt(v) if not isinstance(v, float) else \
                    (dt.datetime.min + dt.timedelta(days=v)).strftime("%H:%M")
            else:
                regions[reg][key] = _num(v)

    # F. generation outage by sector and region
    rf = _section(sh, "F. GENERATION OUTAGE")
    for r in range(rf + 2, rf + 5):
        label = _txt(sh.cell_value(r, 0)).upper()
        key = {"CENTRAL SECTOR": "gen_outage_central_mw", "STATE SECTOR": "gen_outage_state_mw",
               "TOTAL": "gen_outage_total_mw"}.get(label)
        if key:
            for i, reg in enumerate(_PSP_REGIONS):
                regions[reg][key] = _num(sh.cell_value(r, 2 + i))

    # G. source-wise gross generation
    rg = _section(sh, "G. SOURCEWISE")
    mix = []
    for r in range(rg + 2, rg + 10):
        label = _txt(sh.cell_value(r, 0)).upper()
        src = _PSP_G.get(label)
        if not src:
            continue
        for i, reg in enumerate(_PSP_REGIONS):
            mix.append({"date": d, "region": reg, "source": src, "gross_mu": _num(sh.cell_value(r, 2 + i))})
    if len(mix) < 36:
        raise FormatError(f"PSP section G: {len(mix)} cells")

    # C. state supply position
    rc = _section(sh, "C. POWER SUPPLY POSITION")
    rd = _section(sh, "D.", rc)
    states = []
    for r in range(rc + 3, rd):
        name = _txt(sh.cell_value(r, 1))
        st = ref.state(name) if name else None
        if not st:
            continue
        row = _row(sh, r)
        states.append({"date": d, "state_code": st[0], "state": st[1], "region": st[2], "psp_name": name,
                       "max_demand_met_mw": _num(row[2]), "shortage_at_max_demand_mw": _num(row[3]),
                       "energy_met_mu": _num(row[4]), "drawal_schedule_mu": _num(row[5]),
                       "od_ud_mu": _num(row[6]), "energy_shortage_mu": _num(row[8])})
    if len(states) < 25:
        raise FormatError(f"PSP section C: only {len(states)} states")

    # 15-minute SCADA series
    ts = []
    if "TimeSeries" in wb.sheet_names():
        t = wb.sheet_by_name("TimeSeries")
        hr = next(r for r in range(t.nrows) if _txt(t.cell_value(r, 0)).upper() == "TIME")
        heads = [_txt(t.cell_value(hr, c)).upper() for c in range(t.ncols)]
        cols = {}
        for name, must, mustnot in _TS_COLS:
            for c, h in enumerate(heads):
                if c in cols.values():
                    continue
                if must in h and (mustnot is None or mustnot not in h):
                    cols[name] = c
                    break
        for r in range(hr + 1, t.nrows):
            v = t.cell_value(r, 0)
            if isinstance(v, float):
                hhmm = (dt.datetime.min + dt.timedelta(days=v)).strftime("%H:%M")
            else:
                s = _txt(v)
                if not re.match(r"^\d{1,2}:\d{2}$", s):
                    continue
                hhmm = f"{int(s.split(':')[0]):02d}:{s.split(':')[1]}"
            rec = {"date": d, "time": hhmm}
            for name, c in cols.items():
                rec[name] = _num(t.cell_value(r, c))
            ts.append(rec)
    return list(regions.values()), mix, states, ts


# ---------------------------------------------------------------- Grid-India daily REMC (VRE) report

_REMC_SECTIONS = [  # (marker in the section title row, section key); most specific first
    ("non remc intra", "non_remc_state"), ("non remc ists", "non_remc_ists"), ("non remc regional", "non_remc_regional"),
    ("remc monitored intra state", "remc_state"), ("remc monitored ists", "remc_ists"),
    ("remc monitored profile", "remc_regional"),
]
_REGION_CODES = {"NR": "Northern", "WR": "Western", "SR": "Southern", "ER": "Eastern", "NER": "North-Eastern"}


def _remc_scope(label: str) -> tuple[str, str]:
    label = label.split("/")[-1].strip() if "/" in label else label.strip()
    if label.upper() == "TOTAL":
        return "all_india", "All India"
    if label.upper() in _REGION_CODES:
        return "region", _REGION_CODES[label.upper()]
    st = ref.state(label)
    return ("state", st[1]) if st else ("other", label)


def parse_remc(path, date: dt.date):
    """Solar and wind installed vs maximum available capacity by region and state (REMC report).
    Installed minus available is capacity that was not available on that day."""
    import pdfplumber
    out: list[dict] = []
    with pdfplumber.open(path) as pdf:
        head = (pdf.pages[0].extract_text() or "")
        up = head.upper()
        if "REMC" not in up and "RENEWABLE ENERGY MANGEMENT" not in up and "RENEWABLE ENERGY MANAGEMENT" not in up:
            raise FormatError("REMC title not recognised")
        m = re.search(r"Report for\s*:?\s*(\d{2}-[A-Za-z]{3}-\d{2,4})", head)
        if m:
            fmt = "%d-%b-%y" if len(m.group(1)) == 9 else "%d-%b-%Y"
            try:
                found = dt.datetime.strptime(m.group(1), fmt).date()
            except ValueError:  # typo in the report's own date (e.g. "22-Nov-225"): rely on the listing title
                found = None
            if found:
                _check_date(found, date, "REMC")
        section = None
        block: list[list[str]] = []

        def flush():
            if block and section:
                scope_type, scope = _remc_scope(next((r[0] for r in block if r[0]), ""))
                for row in block:
                    res = row[1].upper()
                    fuel = None if "TOTAL" in res else "WIND" if "WIND" in res else "SOLAR" if "SOLAR" in res else None
                    inst, avail = _num(row[2]), _num(row[3])
                    if not fuel or inst is None:
                        continue
                    out.append({
                        "date": date.isoformat(), "section": section, "scope_type": scope_type, "scope": scope,
                        "fuel": fuel, "installed_mw": inst, "available_mw": avail,
                        "unavailable_mw": (inst - avail) if avail is not None else None,
                        "unavailable_pct": ((inst - avail) / inst * 100) if (avail is not None and inst) else None,
                        "max_generation_mw": _num(row[4]), "schedule_mu": _num(row[8]),
                        "actual_mu": _num(row[9]), "cuf_pct": _num(row[11])})
            block.clear()

        for page in pdf.pages[:3]:
            for table in page.extract_tables():
                for raw in table:
                    row = [re.sub(r"\s+", " ", (c or "")).strip() for c in raw] + [""] * 12
                    joined = " ".join(row).lower()
                    hit = next((k for marker, k in _REMC_SECTIONS if marker in joined), None)
                    if hit and not any(_num(c) is not None for c in row[2:6]):
                        flush()
                        section = hit
                        continue
                    res = row[1].upper()
                    if "WIND" in res and "TOTAL" not in res:  # every block starts with its wind row
                        flush()
                        block.append(row)
                    elif block:
                        block.append(row)
                        if "TOTAL" in res:
                            flush()
                flush()
    if not any(r["section"] == "remc_regional" for r in out):
        raise FormatError(f"REMC: regional profile not found ({len(out)} rows)")
    return out


# ---------------------------------------------------------------- Grid-India monthly grid disturbance report

_GD_HEAD = re.compile(
    r"^(\d+)\s+(GD-\d|GI-\d|Near\s*Miss(?:\s+Incident)?)\s+(.+?)\s+(\d{2}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s+"
    r"(?:(\d{2}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s+(\d+:\d{2})\s+)?([\d.]+|-)?\s*([\d.]+|-)?", re.I)
_GD_SPLIT = re.compile(r"\n(?=\d+\s+(?:GD-\d|GI-\d|Near\s*Miss))", re.I)
_LOSS_SENT = re.compile(  # the sentence stating how much generation was lost; keeps "76.4 MW" whole
    r"(?:[^.]|\.\d)*(?:generation loss|loss of generation|drop of|MW lost|lost due to)(?:[^.]|\.\d)*\.?", re.I)
_LIGATURES = {"\u0000": "", "Ɵ": "ti", "Ō": "ft", "ﬁ": "fi", "ﬀ": "ff", "ﬂ": "fl"}


def _event_summary(body: str, loss) -> str:
    """The report's sentence on generation loss; otherwise the first sentence naming a plant type."""
    if loss:
        return loss.group(0).strip()[:400]
    sent = re.search(r"(?:[^.]|\.\d)*\b(?:solar|wind|RE|renewable|plant)\b(?:[^.]|\.\d)*\.?", body, re.I)
    return (sent.group(0) if sent else body[:300]).strip()[:400]


def parse_grid_events(path, month: dt.date):
    """Every grid disturbance / incident in Grid-India's monthly report, flagged when it involves solar,
    wind or other renewable plants (from the event narrative)."""
    import pypdf
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)
    for a, b in _LIGATURES.items():
        text = text.replace(a, b)
    out = []
    for seq, part in enumerate(_GD_SPLIT.split("\n" + text)[1:], 1):
        m = _GD_HEAD.match(re.sub(r"\s+", " ", part[:300]))
        if not m:
            continue
        start = dt.datetime.strptime(f"{m.group(4)} {m.group(5)}", "%d-%m-%Y %H:%M")
        if (start.year, start.month) != (month.year, month.month):
            continue  # a numbered line inside a narrative, not an event row
        end = dt.datetime.strptime(f"{m.group(6)} {m.group(7)}", "%d-%m-%Y %H:%M") if m.group(6) else None
        body = re.sub(r"\s+", " ", part).strip()
        body = re.sub(r"\b(approx|appx|apprx)\.", r"\1", body, flags=re.I)  # an abbreviation, not a sentence end
        solar = bool(re.search(r"\bsolar\b", part, re.I))
        wind = bool(re.search(r"\bwind\b", part, re.I))
        hybrid = bool(re.search(r"\bhybrid\b", part, re.I))
        bess = bool(re.search(r"\bBESS\b", part))
        re_other = bool(re.search(r"\bRE\b|renewable|RE generat", part))
        loss = _LOSS_SENT.search(body)
        st = ref.state(m.group(3).strip())
        out.append({
            "month": month.strftime("%Y-%m"), "seq": seq, "category": re.sub(r"\s+", " ", m.group(2)).upper(),
            "state": st[1] if st else m.group(3).strip(), "state_code": st[0] if st else "",
            "region": st[2] if st else "",
            "start": start.strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M") if end else None,
            "duration_h": round((end - start).total_seconds() / 3600, 2) if end else None,
            "generation_loss_mw": _num(m.group(9)), "load_loss_mw": _num(m.group(10)),
            "involves_solar": solar, "involves_wind": wind, "involves_hybrid": hybrid, "involves_bess": bess,
            "involves_re": solar or wind or hybrid or re_other,
            "summary": _event_summary(body, loss),
            "narrative": body[:1500],
        })
    if not out:
        raise FormatError("grid events: no event rows found")
    return out
