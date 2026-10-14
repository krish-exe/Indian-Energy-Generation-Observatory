"""Cross-checks between reports. Results go into the `validation` table; nothing is silently corrected."""
from __future__ import annotations

import pandas as pd

from .config import Config

CORE_TARGET = 300_000


def _check(name, status, detail, value=None):
    return {"check": name, "status": status, "detail": detail, "value": value}


def validate(t: dict[str, pd.DataFrame], cfg: Config) -> pd.DataFrame:
    out = []
    core = t["generation_daily"]
    n_days = len(cfg.dates())

    out.append(_check("core_record_count", "pass" if len(core) >= CORE_TARGET else "warn",
                      f"generation_daily has {len(core):,} records (target {CORE_TARGET:,})", len(core)))
    dup = core.duplicated(["date", "entity_id"]).sum()
    out.append(_check("core_unique_keys", "pass" if dup == 0 else "fail",
                      f"{dup} duplicate (date, entity_id) keys", int(dup)))

    # SR-2 station totals must reproduce CEA's own SR-17 fuel totals
    conv = core[core.record_type == "conventional_station"].copy()
    conv["fuel17"] = conv.fuel.replace({"HYDRO_IMPORT": "HYDRO_IMPORT"})
    agg = conv.groupby(["date", "fuel17"], as_index=False)[["capacity_mw", "actual_mu"]].sum()
    f17 = t["fuel_daily"].rename(columns={"fuel": "fuel17"})
    j = agg.merge(f17, on=["date", "fuel17"], how="inner")
    if len(j):
        cap_diff = (j.capacity_mw - j.monitored_capacity_mw).abs()
        gen_diff = (j.actual_mu_x - j.actual_mu_y).abs()
        cap_ok = (cap_diff <= 1.0).mean()
        gen_ok = (gen_diff <= 0.5).mean()
        out.append(_check("sr2_vs_sr17_capacity", "pass" if cap_ok >= 0.99 else "warn",
                          f"{cap_ok:.1%} of date x fuel capacity totals within 1 MW of SR-17 "
                          f"(max diff {cap_diff.max():.1f} MW)", round(float(cap_ok), 4)))
        out.append(_check("sr2_vs_sr17_generation", "pass" if gen_ok >= 0.99 else "warn",
                          f"{gen_ok:.1%} of date x fuel generation totals within 0.5 MU of SR-17 "
                          f"(max diff {gen_diff.max():.2f} MU)", round(float(gen_ok), 4)))

    # PSP: regions add up to All India
    mix = t["grid_mix_daily"]
    if len(mix):
        p = mix.pivot_table(index=["date", "source"], columns="region", values="gross_mu", aggfunc="sum")
        regs = [c for c in p.columns if c != "All India"]
        diff = (p[regs].sum(axis=1) - p["All India"]).abs()
        ok = (diff <= 1.0).mean()
        out.append(_check("psp_regions_sum_to_all_india", "pass" if ok >= 0.99 else "warn",
                          f"{ok:.1%} of date x source rows within 1 MU (max diff {diff.max():.2f})",
                          round(float(ok), 4)))

    # SR-10 outage rows should match SR-2 units of the same day
    snap, units = t["outage_snapshot"], t["unit_daily"]
    if len(snap):
        keys = set(zip(units.date, units.unit_id))
        hit = pd.Series([(d, u) in keys for d, u in zip(snap.date, snap.unit_id)]).mean()
        out.append(_check("sr10_units_found_in_sr2", "pass" if hit >= 0.95 else "warn",
                          f"{hit:.1%} of outage rows match a unit in SR-2 on the same day", round(float(hit), 4)))

    # REMC: regional rows add up to the report's own all-India total
    ra = t.get("re_availability_daily")
    if ra is not None and len(ra):
        reg = ra[ra.section == "remc_regional"]
        a = reg[reg.scope_type == "region"].groupby(["date", "fuel"]).installed_mw.sum()
        b = reg[reg.scope_type == "all_india"].set_index(["date", "fuel"]).installed_mw
        j = pd.concat([a, b], axis=1, keys=["regions", "all_india"]).dropna()
        ok = ((j.regions - j.all_india).abs() <= 1).mean() if len(j) else 0
        out.append(_check("remc_regions_sum_to_all_india", "pass" if ok >= 0.99 else "warn",
                          f"{ok:.1%} of date x fuel installed-capacity totals match the report's all-India row",
                          round(float(ok), 4)))
        neg = int((ra.unavailable_mw < 0).sum())
        out.append(_check("remc_available_not_above_installed", "pass" if neg == 0 else "warn",
                          f"{neg} rows where available capacity exceeds installed (kept as published)", neg))

    # coverage per source
    files = t["source_files"]
    for (src, rep), g in files.groupby(["source", "report"]):
        okd = (g.status == "ok").sum()
        unit = "months" if rep == "grid_events" else "days"
        expected = len(g) if rep == "grid_events" else n_days
        out.append(_check(f"coverage_{src}_{rep}", "pass" if okd == expected else "warn",
                          f"{okd}/{expected} {unit} downloaded", int(okd)))
    gaps = t["data_gaps"]
    pf = (gaps.kind == "parse_failed").sum() if len(gaps) else 0
    out.append(_check("parse_failures", "pass" if pf == 0 else "warn", f"{pf} files failed to parse", int(pf)))

    cf = core.capacity_factor
    high = int((cf > 1.05).sum())
    out.append(_check("capacity_factor_plausible", "pass" if high == 0 else "warn",
                      f"{high} records with capacity factor > 1.05 (kept as reported, flagged)", high))
    unknown_state = int((core.state_code.fillna("") == "").sum())
    out.append(_check("records_with_state", "pass" if unknown_state == 0 else "warn",
                      f"{unknown_state} records without a recognised state", unknown_state))
    return pd.DataFrame(out)
