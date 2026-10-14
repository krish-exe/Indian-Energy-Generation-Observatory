"""Aggregates and metrics for the dashboard, computed only from the warehouse tables."""
from __future__ import annotations

import numpy as np
import pandas as pd

MIX_SERIES = ["WIND", "SOLAR", "HYDRO", "OTHER_RES", "NUCLEAR", "COAL", "GAS"]  # fixed stack order
MIX_LABEL = {"WIND": "Wind", "SOLAR": "Solar", "HYDRO": "Hydro (large)", "OTHER_RES": "Biomass & other RE",
             "NUCLEAR": "Nuclear", "COAL": "Coal & lignite", "GAS": "Gas, naphtha & diesel"}
GROUP_OF = {"WIND": "renewable", "SOLAR": "renewable", "HYDRO": "renewable", "OTHER_RES": "renewable",
            "NUCLEAR": "nuclear", "COAL": "non_renewable", "GAS": "non_renewable"}
CAUSES = ["planned", "forced_equipment", "fuel_supply", "commercial", "long_term_or_retired", "regulatory_or_other"]
REGIONS = ["Northern", "Western", "Southern", "Eastern", "North-Eastern"]


def _r(x, n=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), n)


def _col(df: pd.DataFrame, cols: list[str], n=2) -> dict:
    return {c: [_r(v, n) if isinstance(v, (int, float, np.floating, np.integer)) and not isinstance(v, bool)
                else (None if pd.isna(v) else v) for v in df[c].tolist()] for c in cols}


def all_india_mix(t) -> pd.DataFrame:
    """Daily all-India gross generation by source (Grid-India PSP). Wind and solar come from the PSP's
    section A; 'other RE' is the RES total minus wind and solar."""
    mix = t["grid_mix_daily"]
    ai = mix[mix.region == "All India"].pivot_table(index="date", columns="source", values="gross_mu")
    reg = t["grid_region_daily"]
    a = reg[reg.region == "All India"].set_index("date")
    df = pd.DataFrame(index=ai.index)
    df["WIND"] = a.wind_gen_mu.reindex(df.index).fillna(0)
    df["SOLAR"] = a.solar_gen_mu.reindex(df.index)
    df["HYDRO"] = ai.HYDRO
    df["OTHER_RES"] = ai.RES - df.WIND - df.SOLAR
    df["NUCLEAR"] = ai.NUCLEAR
    df["COAL"] = ai.COAL + ai.LIGNITE
    df["GAS"] = ai.GAS_NAPHTHA_DIESEL
    df["TOTAL"] = ai.TOTAL
    return df.reset_index()


def compute(t: dict[str, pd.DataFrame], cfg) -> dict:
    out: dict = {"window": [cfg.start.isoformat(), cfg.end.isoformat()]}
    mix = all_india_mix(t)
    mix["month"] = mix.date.str[:7]
    for g in ("renewable", "nuclear", "non_renewable"):
        mix[g] = mix[[s for s in MIX_SERIES if GROUP_OF[s] == g]].sum(axis=1)
    mix["re_share"] = mix.renewable / mix.TOTAL * 100
    mix["non_fossil_share"] = (mix.renewable + mix.nuclear) / mix.TOTAL * 100
    out["mix_daily"] = _col(mix, ["date"] + MIX_SERIES + ["TOTAL", "renewable", "nuclear", "non_renewable",
                                                          "re_share", "non_fossil_share"])
    mon = mix.groupby("month", as_index=False)[MIX_SERIES + ["TOTAL", "renewable", "nuclear", "non_renewable"]].sum()
    mon["days"] = mix.groupby("month").date.nunique().values
    mon["re_share"] = mon.renewable / mon.TOTAL * 100
    mon["non_fossil_share"] = (mon.renewable + mon.nuclear) / mon.TOTAL * 100
    out["mix_monthly"] = _col(mon, list(mon.columns))
    out["labels"] = MIX_LABEL

    # ---- regions
    m = t["grid_mix_daily"]
    m = m[m.region != "All India"].copy()
    m["src"] = m.source.replace({"LIGNITE": "COAL", "GAS_NAPHTHA_DIESEL": "GAS"})
    reg = m[m.src != "TOTAL"].pivot_table(index="region", columns="src", values="gross_mu", aggfunc="sum")
    reg = reg.reindex(REGIONS)
    reg["TOTAL"] = reg.sum(axis=1)
    reg["re_share"] = (reg.HYDRO + reg.RES) / reg.TOTAL * 100
    reg["non_fossil_share"] = (reg.HYDRO + reg.RES + reg.NUCLEAR) / reg.TOTAL * 100
    out["region_mix"] = _col(reg.reset_index(), ["region", "COAL", "GAS", "NUCLEAR", "HYDRO", "RES", "TOTAL",
                                                 "re_share", "non_fossil_share"])
    m["month"] = m.date.str[:7]
    rm = m[m.src != "TOTAL"].assign(re=lambda d: d.src.isin(["HYDRO", "RES"]) * d.gross_mu)
    rm = rm.groupby(["region", "month"]).agg(re=("re", "sum"), tot=("gross_mu", "sum")).reset_index()
    rm["re_share"] = rm.re / rm.tot * 100
    out["region_re_share_monthly"] = {
        "months": sorted(rm.month.unique()),
        "regions": REGIONS,
        "values": [[_r(rm[(rm.region == r) & (rm.month == mo)].re_share.sum(), 1) for mo in sorted(rm.month.unique())]
                   for r in REGIONS]}

    # ---- renewable sources compared (CEA RE report + CEA DGR hydro)
    core = t["generation_daily"]
    re_rows = core[core.record_type.isin(["re_station_isgs", "re_state_embedded"])]
    st = re_rows.groupby(["state", "fuel"]).actual_mu.sum().unstack(fill_value=0)
    hyd = core[(core.record_type == "conventional_station") & (core.fuel == "HYDRO")].groupby("state").actual_mu.sum()
    st["HYDRO"] = hyd.reindex(st.index).fillna(0)
    st = st.reindex(columns=["SOLAR", "WIND", "HYBRID", "OTHER_RES", "HYDRO"], fill_value=0)
    st["TOTAL"] = st.sum(axis=1)
    st = st.sort_values("TOTAL", ascending=False)
    st = st[st.TOTAL > 0]
    out["state_re"] = _col(st.reset_index(), ["state", "SOLAR", "WIND", "HYBRID", "OTHER_RES", "HYDRO", "TOTAL"], 1)

    # capacity factor by fuel and month (stations with known capacity, unflagged)
    cf = core[(core.capacity_mw > 0) & (core.quality_flag == "") & core.actual_mu.notna()].copy()
    cf["month"] = cf.date.str[:7]
    cf["fuelc"] = cf.fuel.replace({"LIGNITE": "LIGNITE", "NAPHTHA": "GAS", "DIESEL": "GAS"})
    cf = cf[cf.fuelc.isin(["COAL", "LIGNITE", "GAS", "NUCLEAR", "HYDRO", "SOLAR", "WIND"])]
    g = cf.groupby(["fuelc", "month"]).agg(gen=("actual_mu", "sum"), cap=("capacity_mw", "sum")).reset_index()
    g["cf"] = g.gen * 1000 / (g.cap * 24) * 100
    months = sorted(g.month.unique())
    fuels_cf = ["SOLAR", "WIND", "HYDRO", "NUCLEAR", "COAL", "LIGNITE", "GAS"]
    out["cf_monthly"] = {"months": months, "series": {
        f: [_r(g[(g.fuelc == f) & (g.month == mo)].cf.sum(), 1) if len(g[(g.fuelc == f) & (g.month == mo)]) else None
            for mo in months] for f in fuels_cf}}
    gy = cf.groupby("fuelc").agg(gen=("actual_mu", "sum"), cap=("capacity_mw", "sum"))
    out["cf_window"] = {f: _r(gy.loc[f].gen * 1000 / (gy.loc[f].cap * 24) * 100, 1) for f in fuels_cf if f in gy.index}

    # renewable station league table (ISGS solar/wind, >= 50 MW, reported >= 300 days)
    isg = cf[cf.record_type == "re_station_isgs"]
    lt = isg.groupby(["entity_id", "entity_name", "state", "fuel"]).agg(
        gen=("actual_mu", "sum"), capsum=("capacity_mw", "sum"), cap=("capacity_mw", "last"),
        days=("date", "nunique"), cv=("capacity_factor", lambda s: s.std() / s.mean() if s.mean() else np.nan)
    ).reset_index()
    lt = lt[(lt.cap >= 50) & (lt.days >= 300)]
    lt["cf"] = lt.gen * 1000 / (lt.capsum * 24) * 100
    league = []
    for f in ("SOLAR", "WIND"):
        sub = lt[lt.fuel == f].sort_values("cf", ascending=False)
        league.append({"fuel": f, "n": int(len(sub)),
                       "top": _col(sub.head(10), ["entity_name", "state", "cap", "cf", "days"], 1),
                       "median_cf": _r(sub.cf.median(), 1)})
    out["re_league"] = league

    # variability: coefficient of variation of daily all-India output, by month and overall
    var_src = ["SOLAR", "WIND", "HYDRO", "NUCLEAR", "COAL", "GAS"]
    vm = mix.groupby("month")[var_src].agg(lambda s: s.std() / s.mean() * 100)
    out["variability_monthly"] = {"months": list(vm.index), "series": {s: [_r(v, 1) for v in vm[s]] for s in var_src}}
    out["variability_window"] = {s: _r(mix[s].std() / mix[s].mean() * 100, 1) for s in var_src}
    dod = mix[var_src].pct_change().abs() * 100
    out["day_to_day_change_median_pct"] = {s: _r(dod[s].median(), 1) for s in var_src}
    ws = mix.WIND + mix.SOLAR
    out["complementarity"] = {
        "corr_wind_solar_daily": _r(mix.WIND.corr(mix.SOLAR), 2),
        "cv_wind": _r(mix.WIND.std() / mix.WIND.mean() * 100, 1),
        "cv_solar": _r(mix.SOLAR.std() / mix.SOLAR.mean() * 100, 1),
        "cv_wind_plus_solar": _r(ws.std() / ws.mean() * 100, 1),
        "monthly": _col(mon, ["month", "days", "WIND", "SOLAR", "HYDRO"], 1),
    }

    # ---- 15-minute profile: average day per month, and the peak-demand day
    ts = t["grid_15min"].copy()
    if len(ts):
        ts["month"] = ts.date.str[:7]
        cols = [c for c in ["solar_mw", "wind_mw", "hydro_mw", "others_mw", "nuclear_mw", "thermal_mw", "gas_mw",
                            "storage_gen_mw", "demand_met_mw"] if c in ts.columns]
        prof = ts.groupby(["month", "time"])[cols].mean().reset_index()
        out["profile_15min"] = {"times": sorted(ts.time.unique()), "cols": cols,
                                "months": {mo: {c: [_r(v, 0) for v in g[c]] for c in cols}
                                           for mo, g in prof.groupby("month")}}
        peak = ts.loc[ts.demand_met_mw.idxmax()]
        day = ts[ts.date == peak.date].sort_values("time")
        out["peak_day_15min"] = {"date": peak.date, "time": peak.time, "demand_mw": _r(peak.demand_met_mw, 0),
                                 **{c: [_r(v, 0) for v in day[c]] for c in cols}}

    # ---- program vs actual (CEA SR-17)
    f17 = t["fuel_daily"].copy()
    f17["month"] = f17.date.str[:7]
    f17 = f17[f17.fuel.isin(["COAL", "LIGNITE", "GAS", "NUCLEAR", "HYDRO"])]
    pa = f17.groupby(["fuel", "month"])[["program_mu", "actual_mu"]].sum().reset_index()
    pa["dev_pct"] = (pa.actual_mu - pa.program_mu) / pa.program_mu * 100
    out["program_vs_actual"] = {"months": months, "series": {
        f: [_r(pa[(pa.fuel == f) & (pa.month == mo)].dev_pct.sum(), 1) if len(pa[(pa.fuel == f) & (pa.month == mo)])
            else None for mo in months] for f in ["COAL", "LIGNITE", "GAS", "NUCLEAR", "HYDRO"]}}
    pw = f17.groupby("fuel")[["program_mu", "actual_mu"]].sum()
    out["program_vs_actual_window"] = {f: {"program": _r(r.program_mu, 0), "actual": _r(r.actual_mu, 0),
                                           "dev_pct": _r((r.actual_mu - r.program_mu) / r.program_mu * 100, 1)}
                                       for f, r in pw.iterrows()}

    # ---- outages (conventional, CEA SR-2 capacity under outage, all fuels incl. hydro)
    conv = core[core.record_type == "conventional_station"].copy()
    conv["fuelc"] = conv.fuel.replace({"NAPHTHA": "GAS", "DIESEL": "GAS"})
    conv = conv[conv.fuelc != "HYDRO_IMPORT"]
    ou = conv.groupby(["date", "fuelc"]).agg(out=("cap_under_outage_mw", "sum"), cap=("capacity_mw", "sum")).reset_index()
    ofuels = ["COAL", "LIGNITE", "GAS", "NUCLEAR", "HYDRO"]
    dates = sorted(ou.date.unique())
    piv_o = ou.pivot(index="date", columns="fuelc", values="out").reindex(dates)
    piv_c = ou.pivot(index="date", columns="fuelc", values="cap").reindex(dates)
    out["unavailable_daily"] = {"dates": dates,
                                "mw": {f: [_r(v, 0) for v in piv_o[f]] for f in ofuels},
                                "pct": {f: [_r(v, 1) for v in (piv_o[f] / piv_c[f] * 100)] for f in ofuels}}
    out["unavailable_window_pct"] = {f: _r(piv_o[f].sum() / piv_c[f].sum() * 100, 1) for f in ofuels}
    out["unavailable_window_mw"] = {f: _r(piv_o[f].mean(), 0) for f in ofuels}

    by_state = conv.groupby(["state", "fuelc"]).agg(out=("cap_under_outage_mw", "sum"), cap=("capacity_mw", "sum"))
    bs = by_state.groupby("state").sum()
    bs["pct"] = bs.out / bs.cap * 100
    bs["avg_mw"] = bs.out / len(dates)
    bs = bs[bs.cap > 0].sort_values("avg_mw", ascending=False)
    out["unavailable_by_state"] = _col(bs.reset_index(), ["state", "avg_mw", "pct"], 1)
    br = conv.groupby("region").agg(out=("cap_under_outage_mw", "sum"), cap=("capacity_mw", "sum")).reindex(REGIONS)
    out["unavailable_by_region"] = {"regions": REGIONS, "avg_mw": [_r(v, 0) for v in br.out / len(dates)],
                                    "pct": [_r(v, 1) for v in br.out / br.cap * 100]}

    snap = t["outage_snapshot"]
    sc = snap.groupby(["date", "cause_group"]).unavailable_mw.sum().unstack(fill_value=0).reindex(
        columns=CAUSES, fill_value=0).reindex(dates).fillna(0)
    out["outage_cause_daily"] = {"dates": dates, "series": {c: [_r(v, 0) for v in sc[c]] for c in CAUSES}}
    out["outage_cause_window_mw"] = {c: _r(sc[c].mean(), 0) for c in CAUSES}

    ev = t["outage_events"].copy()
    ev["in_window"] = ev.outage_start.fillna("") >= cfg.start.isoformat()
    forced = snap[snap.cause_group == "forced_equipment"]
    top = forced.groupby(["station_id", "station", "state"]).agg(
        mw_days=("unavailable_mw", "sum"), units=("unit_id", "nunique")).reset_index()
    top = top.sort_values("mw_days", ascending=False).head(15)
    out["top_forced_stations"] = _col(top, ["station", "state", "mw_days", "units"], 0)

    fe = ev[ev.in_window & (ev.cause_group == "forced_equipment")]
    rep = fe.groupby(["unit_id", "station", "unit_no", "state"]).agg(
        events=("event_id", "count"), cap=("unit_capacity_mw", "max"),
        med_h=("duration_h", "median")).reset_index().sort_values(["events", "cap"], ascending=False).head(15)
    out["repeat_failures"] = _col(rep, ["station", "unit_no", "state", "events", "cap", "med_h"], 1)
    out["forced_events_in_window"] = int(len(fe))
    out["units_with_forced_events"] = int(fe.unit_id.nunique())

    fe2 = fe.copy()
    fe2["reason_norm"] = fe2.reason.str.upper().str.replace(r"[^A-Z0-9 /&]", "", regex=True).str.replace(
        r"\s+", " ", regex=True).str.strip()
    rs = fe2.groupby("reason_norm").agg(events=("event_id", "count"), med_h=("duration_h", "median"),
                                        mw=("max_unavailable_mw", "sum")).reset_index()
    out["top_reasons"] = _col(rs.sort_values("events", ascending=False).head(15), ["reason_norm", "events", "med_h"], 1)

    obs = ev[ev.in_window & (ev.end_status == "observed") & ev.duration_h.notna()]
    bins = [0, 6, 24, 72, 168, 672, 1e9]
    labels = ["< 6 h", "6-24 h", "1-3 days", "3-7 days", "1-4 weeks", "> 4 weeks"]
    obs = obs.assign(bin=pd.cut(obs.duration_h, bins=bins, labels=labels, right=False))
    hist = obs.groupby(["bin", "cause_group"], observed=False).event_id.count().unstack(fill_value=0)
    out["duration_hist"] = {"bins": labels, "series": {c: [int(hist.loc[b, c]) if c in hist.columns else 0
                                                           for b in labels] for c in ["planned", "forced_equipment"]},
                            "n_observed": int(len(obs)),
                            "n_inferred": int((ev.in_window & (ev.end_status == "inferred")).sum()),
                            "n_ongoing": int((ev.in_window & (ev.end_status == "ongoing")).sum()),
                            "median_forced_h": _r(obs[obs.cause_group == "forced_equipment"].duration_h.median(), 1),
                            "median_planned_h": _r(obs[obs.cause_group == "planned"].duration_h.median(), 1)}

    ev_in = ev[ev.in_window].copy()
    ev_in["month"] = ev_in.outage_start.str[:7]
    em = ev_in.groupby(["month", "cause_group"]).event_id.count().unstack(fill_value=0).reindex(
        index=months, columns=CAUSES, fill_value=0)
    out["events_monthly"] = {"months": months, "series": {c: [int(v) for v in em[c]] for c in CAUSES}}

    cutoff = (pd.Timestamp(cfg.start) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    strand = ev[(ev.end_status == "ongoing") & (ev.outage_start.fillna("9999") < cutoff)].copy()
    strand = strand.sort_values("outage_start")
    out["stranded"] = {"n": int(len(strand)), "mw": _r(strand.unit_capacity_mw.fillna(strand.max_unavailable_mw).sum(), 0),
                       "rows": _col(strand, ["station", "unit_no", "state", "unit_capacity_mw", "outage_start",
                                             "cause_group", "reason"], 1)}

    coal = conv[(conv.fuelc == "COAL") & conv.coal_stock_days.notna() & (conv.capacity_mw > 0)].copy()
    coal["month"] = coal.date.str[:7]
    coal["w"] = coal.coal_stock_days * coal.capacity_mw
    cs = coal.groupby("month").agg(w=("w", "sum"), c=("capacity_mw", "sum"))
    fs = snap[snap.cause_group == "fuel_supply"].assign(month=lambda d: d.date.str[:7]).groupby(
        ["month", "date"]).unavailable_mw.sum().groupby("month").mean()
    out["coal_stock_vs_fuel_outage"] = {"months": months,
                                        "stock_days": [_r(cs.w.get(mo, np.nan) / cs.c.get(mo, np.nan), 1) for mo in months],
                                        "fuel_outage_mw": [_r(fs.get(mo, 0), 0) for mo in months]}

    # ---- supply & demand (Grid-India PSP)
    ss = t["state_supply_daily"]
    sst = ss.groupby("state").agg(shortage=("energy_shortage_mu", "sum"), energy=("energy_met_mu", "sum"),
                                  peak=("max_demand_met_mw", "max")).reset_index()
    sst["shortage_pct"] = sst.shortage / (sst.energy + sst.shortage) * 100
    out["state_shortage"] = _col(sst.sort_values("shortage", ascending=False), ["state", "shortage", "shortage_pct",
                                                                                "energy", "peak"], 2)
    ra = t["grid_region_daily"]
    ai = ra[ra.region == "All India"].copy()
    ai["month"] = ai.date.str[:7]
    out["demand_daily"] = _col(ai, ["date", "max_demand_met_mw", "energy_met_mu", "energy_shortage_mu",
                                    "evening_peak_shortage_mw", "gen_outage_total_mw"], 1)
    am = ai.groupby("month").agg(peak=("max_demand_met_mw", "max"), energy=("energy_met_mu", "sum"),
                                 shortage=("energy_shortage_mu", "sum"), gen_out=("gen_outage_total_mw", "mean"),
                                 eve_short=("evening_peak_shortage_mw", "mean")).reset_index()
    out["demand_monthly"] = _col(am, list(am.columns), 1)

    out.update(re_outage_metrics(t, out))

    # ---- coverage per source
    files = t["source_files"]
    cov = {}
    for (src, rep_), g2 in files.groupby(["source", "report"]):
        cov[f"{src}/{rep_}"] = {"ok": int((g2.status == "ok").sum()), "total": int(len(g2)),
                                "missing": sorted(g2[g2.status != "ok"].report_date.tolist())}
    gaps = t["data_gaps"]
    pf = gaps[gaps.kind == "parse_failed"] if len(gaps) else gaps
    out["coverage"] = {"files": cov, "parse_failed": pf.source_file_id.tolist() if len(pf) else []}
    out["validation"] = t["validation"].to_dict(orient="records")
    out["row_counts"] = {k: int(len(v)) for k, v in t.items()}
    return out


def re_outage_metrics(t: dict[str, pd.DataFrame], m: dict) -> dict:
    """Solar and wind: unavailable capacity (REMC), grid events, and zero-output episodes."""
    out: dict = {}
    ra = t.get("re_availability_daily", pd.DataFrame())
    if len(ra):
        reg = ra[ra.section == "remc_regional"]
        ai = reg[reg.scope_type == "all_india"].pivot_table(index="date", columns="fuel",
                                                              values=["unavailable_pct", "unavailable_mw", "installed_mw"])
        dates = list(ai.index)
        out["re_unavailable_daily"] = {
            "dates": dates,
            "pct": {f: [_r(v, 1) for v in ai["unavailable_pct"][f]] for f in ("SOLAR", "WIND")},
            "mw": {f: [_r(v, 0) for v in ai["unavailable_mw"][f]] for f in ("SOLAR", "WIND")},
            "installed": {f: [_r(v, 0) for v in ai["installed_mw"][f]] for f in ("SOLAR", "WIND")}}
        tot = reg[reg.scope_type == "all_india"].groupby("fuel")[["unavailable_mw", "installed_mw"]].sum()
        out["re_unavailable_window_pct"] = {f: _r(tot.loc[f].unavailable_mw / tot.loc[f].installed_mw * 100, 1)
                                            for f in tot.index}
        out["re_unavailable_window_mw"] = {f: _r(reg[(reg.scope_type == "all_india") & (reg.fuel == f)]
                                               .unavailable_mw.mean(), 0) for f in ("SOLAR", "WIND")}
        rg = reg[reg.scope_type == "region"].groupby(["scope", "fuel"])[["unavailable_mw", "installed_mw"]].sum()
        regions = [r for r in REGIONS if r in rg.index.get_level_values(0)]
        out["re_unavailable_by_region"] = {"regions": regions, "pct": {
            f: [_r(rg.loc[(r, f)].unavailable_mw / rg.loc[(r, f)].installed_mw * 100, 1) if (r, f) in rg.index else None
                for r in regions] for f in ("SOLAR", "WIND")}}
        stt = ra[(ra.section == "remc_state") & (ra.scope_type == "state")]
        sg = stt.groupby(["scope", "fuel"]).agg(un=("unavailable_mw", "mean"), inst=("installed_mw", "mean"),
                                                pct=("unavailable_pct", "mean")).reset_index()
        piv = sg.pivot(index="scope", columns="fuel", values=["un", "pct", "inst"]).fillna(0)
        piv["tot"] = piv["un"].sum(axis=1)
        piv = piv.sort_values("tot", ascending=False)
        out["re_unavailable_by_state"] = {
            "states": list(piv.index),
            "solar_mw": [_r(v, 0) for v in piv["un"].get("SOLAR", pd.Series(0, index=piv.index))],
            "wind_mw": [_r(v, 0) for v in piv["un"].get("WIND", pd.Series(0, index=piv.index))],
            "solar_pct": [_r(v, 1) for v in piv["pct"].get("SOLAR", pd.Series(0, index=piv.index))],
            "wind_pct": [_r(v, 1) for v in piv["pct"].get("WIND", pd.Series(0, index=piv.index))]}
        # all sources side by side: conventional (CEA capacity under outage) + solar/wind (REMC)
        cmp_ = {k: v for k, v in m.get("unavailable_window_pct", {}).items()}
        cmp_.update({k: v for k, v in out["re_unavailable_window_pct"].items()})
        out["unavailable_all_sources_pct"] = cmp_

    ge = t.get("grid_events", pd.DataFrame())
    if len(ge):
        g = ge[ge.involves_re].copy()
        g["mon"] = g.start.str[:7]
        months = sorted(ge.start.str[:7].unique())
        def kind(r):
            if r.involves_hybrid or (r.involves_solar and r.involves_wind):
                return "solar_and_wind"
            return "solar" if r.involves_solar else "wind" if r.involves_wind else "other_re"
        g["kind"] = g.apply(kind, axis=1)
        kinds = ["solar", "wind", "solar_and_wind", "other_re"]
        cnt = g.groupby(["mon", "kind"]).event_id.count().unstack(fill_value=0).reindex(index=months, columns=kinds, fill_value=0)
        loss = g.groupby("mon").generation_loss_mw.sum().reindex(months).fillna(0)
        out["re_events_monthly"] = {"months": months, "series": {k: [int(v) for v in cnt[k]] for k in kinds},
                                    "loss_mw": [_r(v, 0) for v in loss]}
        top = g.sort_values("generation_loss_mw", ascending=False).head(20)
        out["re_events_top"] = _col(top, ["event_id", "start", "end", "duration_h", "state", "category",
                                          "generation_loss_mw", "kind", "summary"], 1)
        bys = g.groupby("state").agg(events=("event_id", "count"), loss=("generation_loss_mw", "sum")).reset_index()
        out["re_events_by_state"] = _col(bys.sort_values("events", ascending=False), ["state", "events", "loss"], 0)
        out["re_events_summary"] = {"n_events": int(len(ge)), "n_re": int(len(g)),
                                    "loss_mw": _r(g.generation_loss_mw.sum(), 0),
                                    "median_h": _r(g.duration_h.median(), 2),
                                    "max_loss_mw": _r(g.generation_loss_mw.max(), 0),
                                    "max_event": (top.iloc[0][["start", "state", "summary"]].to_dict() if len(top) else None)}

    ep = t.get("re_zero_output_episodes", pd.DataFrame())
    if len(ep):
        bins = [1, 2, 3, 4, 8, 15, 31, 10_000]
        labels = ["1 day", "2 days", "3 days", "4-7 days", "1-2 weeks", "2-4 weeks", "> 4 weeks"]
        h = pd.cut(ep.days, bins=bins, labels=labels, right=False).value_counts().reindex(labels).fillna(0)
        st = ep.groupby(["entity_id", "station", "state"]).agg(episodes=("episode_id", "count"), days=("days", "sum"),
                                                               cap=("capacity_mw", "max")).reset_index()
        out["re_zero_output"] = {"n": int(len(ep)), "stations": int(ep.entity_id.nunique()),
                                 "station_days": int(ep.days.sum()), "median_days": _r(ep.days.median(), 0),
                                 "hist": {"bins": labels, "counts": [int(v) for v in h]},
                                 "top": _col(st.sort_values(["days", "cap"], ascending=False).head(15),
                                             ["station", "state", "cap", "episodes", "days"], 0)}
        ra = t.get("re_availability_daily", pd.DataFrame())
        isgs = t["generation_daily"]
        isgs = isgs[(isgs.record_type == "re_station_isgs") & (isgs.fuel == "SOLAR") & (isgs.capacity_mw > 0)]
        out["re_zero_output"]["station_days_total"] = int(len(isgs))
    return out
