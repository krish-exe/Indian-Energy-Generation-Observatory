"""Rule-based findings: fixed templates filled from the metrics, so the same data gives the same text."""
from __future__ import annotations

import datetime as dt

import numpy as np

LBL = {"SOLAR": "solar", "WIND": "wind", "HYDRO": "large hydro", "NUCLEAR": "nuclear", "COAL": "coal",
       "LIGNITE": "lignite", "GAS": "gas", "OTHER_RES": "biomass & other RE"}
CAUSE_LBL = {"planned": "planned maintenance", "forced_equipment": "equipment failures",
             "fuel_supply": "fuel supply problems", "commercial": "commercial reasons (no schedule / reserve shutdown)",
             "long_term_or_retired": "long-term shutdown or retirement", "regulatory_or_other": "regulatory and other reasons"}


def _month(m: str) -> str:
    return dt.date.fromisoformat(m + "-01").strftime("%b %Y")


def _pct(x, n=1) -> str:
    return f"{x:.{n}f}%"


def build(m: dict) -> dict[str, list[dict]]:
    w0, w1 = (dt.date.fromisoformat(d).strftime("%d %b %Y") for d in m["window"])
    period = f"{w0} - {w1}"
    src = "Grid-India daily PSP reports"
    cea = "CEA Daily Generation Reports"
    ins: dict[str, list[dict]] = {k: [] for k in ["overview", "mix", "renewables", "outages", "supply"]}

    def add(page, text, source, caveat=None):
        ins[page].append({"text": text, "source": source, "period": period, "caveat": caveat})

    mon = m["mix_monthly"]
    tot = sum(mon["TOTAL"])
    ren, nuc, nonr = sum(mon["renewable"]), sum(mon["nuclear"]), sum(mon["non_renewable"])
    coal = sum(mon["COAL"])
    add("overview", f"Renewables, including large hydro, supplied {_pct(ren / tot * 100)} of India's gross electricity "
        f"generation ({tot / 1000:,.0f} TWh in total). Adding nuclear, non-fossil sources supplied "
        f"{_pct((ren + nuc) / tot * 100)}; coal and lignite alone supplied {_pct(coal / tot * 100)}.", src)
    shares = mon["re_share"]
    hi, lo = int(np.nanargmax(shares)), int(np.nanargmin(shares))
    add("mix", f"The renewable share was highest in {_month(mon['month'][hi])} ({_pct(shares[hi])}) and lowest in "
        f"{_month(mon['month'][lo])} ({_pct(shares[lo])}): a swing of {shares[hi] - shares[lo]:.1f} percentage points "
        f"within one year.", src, "Seasonal pattern from a single year; not a multi-year trend.")
    dm = m["demand_daily"]
    pk = int(np.nanargmax([v if v is not None else -1 for v in dm["max_demand_met_mw"]]))
    add("overview", f"Peak demand met reached {dm['max_demand_met_mw'][pk] / 1000:,.1f} GW on "
        f"{dt.date.fromisoformat(dm['date'][pk]).strftime('%d %b %Y')}.", src)

    rg = m["region_mix"]
    order = np.argsort(rg["re_share"])
    add("mix", f"{rg['region'][order[-1]]} region had the highest renewable share ({_pct(rg['re_share'][order[-1]])}); "
        f"{rg['region'][order[0]]} had the lowest ({_pct(rg['re_share'][order[0]])}).", src)
    if "peak_day_15min" in m:
        p = m["peak_day_15min"]
        times = m["profile_15min"]["times"]
        i_noon, i_eve = times.index("12:30") if "12:30" in times else 50, times.index("19:30") if "19:30" in times else 78
        add("mix", f"On the peak-demand day ({p['date']}), solar produced {p['solar_mw'][i_noon] / 1000:,.0f} GW at 12:30 "
            f"but {(p['solar_mw'][i_eve] or 0) / 1000:,.0f} GW at 19:30; thermal output rose from "
            f"{p['thermal_mw'][i_noon] / 1000:,.0f} GW to {p['thermal_mw'][i_eve] / 1000:,.0f} GW to cover the evening.",
            "Grid-India 15-minute SCADA data", "SCADA data can contain telemetry errors.")
    pv = m["program_vs_actual_window"]
    if "COAL" in pv:
        d = pv["COAL"]["dev_pct"]
        add("mix", f"Coal stations generated {abs(d):.1f}% {'more' if d >= 0 else 'less'} than CEA's programme for the "
            f"year; hydro was {abs(pv['HYDRO']['dev_pct']):.1f}% {'above' if pv['HYDRO']['dev_pct'] >= 0 else 'below'} programme.",
            cea)

    cfw = m["cf_window"]
    add("renewables", "Capacity factors over the year: " + ", ".join(
        f"{LBL[f]} {_pct(cfw[f])}" for f in ["SOLAR", "WIND", "HYDRO", "COAL", "NUCLEAR"] if f in cfw)
        + ". Solar and wind run below thermal plants because sun and wind are not always available, not because "
          "the plants fail.", f"{cea}; CEA Daily Renewable Generation Reports",
        "Solar and wind capacity factors use inter-state (ISGS) stations only; net generation.")
    cm = m["complementarity"]
    mo = cm["monthly"]
    per_day = [w / d for w, d in zip(mo["WIND"], mo["days"])]  # partial months at the window edges
    wmax = int(np.nanargmax(per_day)); wmin = int(np.nanargmin(per_day))
    add("renewables", f"Wind is the most seasonal source: in its best month ({_month(mo['month'][wmax])}) it produced "
        f"{per_day[wmax] / max(per_day[wmin], 1e-9):.1f}x as much per day as in its weakest "
        f"({_month(mo['month'][wmin])}).", src)
    corr = cm["corr_wind_solar_daily"]
    smooth = cm["cv_wind_plus_solar"] < min(cm["cv_wind"], cm["cv_solar"])
    add("renewables", f"Daily wind and solar output are {'negatively' if corr < 0 else 'positively'} correlated "
        f"(r = {corr:.2f}). Day-to-day variation of wind and solar combined is {_pct(cm['cv_wind_plus_solar'])} "
        f"(coefficient of variation), versus {_pct(cm['cv_wind'])} for wind and {_pct(cm['cv_solar'])} for solar alone"
        + (" - together they are steadier than either." if smooth else "."), src, "Correlation, not causation.")
    sr = m["state_re"]
    for f in ("SOLAR", "WIND"):
        vals = sr[f]
        i = int(np.argmax(vals))
        add("renewables", f"{sr['state'][i]} generated {_pct(vals[i] / sum(vals) * 100)} of India's reported {LBL[f]} output.",
            "CEA Daily Renewable Generation Reports", "Reported grid-connected generation; rooftop solar is not included.")

    up = m["unavailable_window_pct"]
    worst = max(up, key=lambda k: up[k] or 0)
    add("outages", "Average share of capacity unavailable over the year: " + ", ".join(
        f"{LBL[f]} {_pct(up[f])}" for f in ["COAL", "LIGNITE", "GAS", "NUCLEAR", "HYDRO"] if up.get(f) is not None)
        + f". {LBL[worst].capitalize()} lost the largest share.", cea,
        "Gas plants are often idle for lack of gas or schedule; that is reported as outage too.")
    cw = m["outage_cause_window_mw"]
    totc = sum(v or 0 for v in cw.values())
    top_c = max(cw, key=lambda k: cw[k] or 0)
    add("outages", f"Of the coal, lignite and nuclear capacity out on an average day ({totc / 1000:,.1f} GW), "
        f"{_pct(cw[top_c] / totc * 100, 0)} was down for {CAUSE_LBL[top_c]} and "
        f"{_pct((cw['fuel_supply'] + cw['commercial']) / totc * 100, 0)} for fuel or commercial reasons rather than "
        f"breakdowns.", f"{cea}, Sub-report 10")
    dh = m["duration_hist"]
    if m["top_reasons"]["reason_norm"]:
        add("outages", f"{m['forced_events_in_window']:,} equipment-failure outages started during the year across "
            f"{m['units_with_forced_events']:,} units. The most common cause was "
            f"'{m['top_reasons']['reason_norm'][0].lower()}' ({int(m['top_reasons']['events'][0])} events). Median repair "
            f"time for failures with a reported return was {dh['median_forced_h']:.0f} hours.", f"{cea}, Sub-report 10",
            "Durations only for outages whose return time was reported.")
    st = m["stranded"]
    if st["n"]:
        add("outages", f"{st['n']} units ({st['mw']:,.0f} MW) had been out for more than a year before the window "
            f"started and were still out at its end (no fuel agreement, awaiting scrapping, reserve shutdown).",
            f"{cea}, Sub-report 10")
    tf = m["top_forced_stations"]
    if tf["station"]:
        add("outages", f"{tf['station'][0]} ({tf['state'][0]}) lost the most capacity to equipment failures: "
            f"{tf['mw_days'][0]:,.0f} MW-days.", f"{cea}, Sub-report 10")

    remc = "Grid-India daily REMC reports"
    if "re_unavailable_window_pct" in m:
        rp, cp = m["re_unavailable_window_pct"], m.get("unavailable_window_pct", {})
        add("outages", f"Solar and wind: on an average day {_pct(rp.get('SOLAR', 0))} of monitored solar capacity "
            f"({m['re_unavailable_window_mw']['SOLAR'] / 1000:,.1f} GW) and {_pct(rp.get('WIND', 0))} of wind capacity "
            f"({m['re_unavailable_window_mw']['WIND'] / 1000:,.1f} GW) was not available, against "
            f"{_pct(cp.get('COAL', 0))} for coal.", remc,
            "Installed minus the day's maximum available capacity; a different measure from CEA's capacity under "
            "outage for thermal plants, so compare with care.")
    if "re_events_summary" in m:
        e = m["re_events_summary"]
        big = e["max_event"] or {}
        add("outages", f"{e['n_re']} of the {e['n_events']} grid disturbances in the year took solar, wind or other "
            f"renewable plants offline, losing {e['loss_mw']:,.0f} MW of generation in total. The largest "
            f"({big.get('state', '')}, {str(big.get('start', ''))[:10]}) cut {e['max_loss_mw']:,.0f} MW.",
            "Grid-India monthly grid disturbance reports",
            "Most of these are trips of the line or substation that carries the plant's power, not plant faults.")
    if "re_zero_output" in m:
        z = m["re_zero_output"]
        add("outages", f"Inter-state solar stations reported zero output on {z['station_days']:,} station-days "
            f"({_pct(z['station_days'] / z['station_days_total'] * 100)} of all station-days), in {z['n']:,} episodes "
            f"across {z['stations']} stations; the median episode lasted {z['median_days']:.0f} day(s).",
            "CEA Daily Renewable Generation Reports (derived)",
            "A proxy: a zero day can also be a reporting error. Stations that report zero on over 90% of days are excluded.")

    ss = m["state_shortage"]
    tot_s = sum(ss["shortage"]); tot_e = sum(ss["energy"])
    add("supply", f"Unmet demand totalled {tot_s:,.0f} MU, {_pct(tot_s / (tot_e + tot_s) * 100, 2)} of demand. "
        f"{ss['state'][0]} had the most ({ss['shortage'][0]:,.0f} MU).", src,
        "Unmet demand reported by states. It is not a measure of household power cuts.")
    dmn = m["demand_monthly"]
    if len(dmn["month"]) > 3:
        r = np.corrcoef(dmn["gen_out"], dmn["shortage"])[0, 1]
        add("supply", f"Month by month, average generation outage and unmet demand have a correlation of r = {r:.2f}.",
            src, "Correlation, not causation: a plant outage does not by itself cause a consumer power cut.")
    return ins
