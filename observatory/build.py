"""Parse every downloaded file listed in the manifest and build the warehouse tables (Parquet).

Nothing here reads anything except data/manifest.csv, the raw files it lists, and reference/*.csv.
Row order is fixed (sorted keys) so the same inputs always give the same tables.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from . import parse
from .config import Config
from .events import build_events, classify_reasons
from .validate import validate

PARSERS = {
    ("npp_dgr", "sr02"): "sr2", ("npp_dgr", "sr10"): "sr10", ("npp_dgr", "sr17"): "sr17",
    ("cea_re_daily", "daily_re"): "re", ("grid_india_psp", "psp"): "psp",
    ("grid_india_remc", "remc"): "remc", ("grid_india_gd", "grid_events"): "gd",
}
SOURCE_LABEL = {
    "sr2": "CEA Daily Generation Report, Sub-report 2 (via npp.gov.in)",
    "re": "CEA Daily Renewable Generation Report (gen-re.cea.gov.in)",
}


def _file_id(row) -> str:
    return f"{row.source}/{row.report}/{row.report_date}"


def _sort(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return df.sort_values(keys, kind="mergesort").reset_index(drop=True) if len(df) else df


def zero_output_episodes(core: pd.DataFrame) -> pd.DataFrame:
    """Runs of consecutive report days on which an inter-state solar station reported zero generation.
    A solar plant produces something on every day it is available, so a zero day means it was out (or its
    evacuation was). This is a proxy derived from CEA's reports, not an official outage record. Stations
    that report zero on more than 90% of days are treated as not reporting and left out."""
    cols = ["episode_id", "entity_id", "station", "state_code", "state", "region", "fuel", "capacity_mw",
            "first_date", "last_date", "days", "ongoing_at_window_end", "source_file_ids"]
    s = core[(core.record_type == "re_station_isgs") & (core.fuel == "SOLAR") & (core.capacity_mw > 0)]
    if s.empty:
        return pd.DataFrame(columns=cols)
    report_days = sorted(s.date.unique())
    nxt = {d: report_days[i + 1] if i + 1 < len(report_days) else None for i, d in enumerate(report_days)}
    share = s.groupby("entity_id").actual_mu.apply(lambda x: (x == 0).mean())
    s = s[s.entity_id.isin(share[share <= 0.9].index)].sort_values(["entity_id", "date"], kind="mergesort")
    out = []
    for eid, g in s.groupby("entity_id", sort=True):
        run = []
        for r in g.itertuples(index=False):
            if r.actual_mu == 0 and (not run or nxt[run[-1].date] == r.date):
                run.append(r)
                continue
            if run:
                out.append(run)
            run = [r] if r.actual_mu == 0 else []
        if run:
            out.append(run)
    rows = [{"entity_id": run[0].entity_id, "station": run[0].entity_name, "state_code": run[0].state_code,
             "state": run[0].state, "region": run[0].region, "fuel": run[0].fuel,
             "capacity_mw": max(x.capacity_mw for x in run), "first_date": run[0].date, "last_date": run[-1].date,
             "days": len(run), "ongoing_at_window_end": run[-1].date == report_days[-1],
             "source_file_ids": ";".join(x.source_file_id for x in run[:3]) + (";..." if len(run) > 3 else "")}
            for run in out]
    ep = pd.DataFrame(rows, columns=cols[1:]).sort_values(["first_date", "entity_id"], kind="mergesort")
    ep.insert(0, "episode_id", [f"Z{i:05d}" for i in range(1, len(ep) + 1)])
    return ep.reset_index(drop=True)


def build(cfg: Config, log=print) -> dict[str, pd.DataFrame]:
    manifest = pd.read_csv(cfg.manifest_path, dtype=str, keep_default_na=False)
    rows: dict[str, list] = {k: [] for k in ["stations", "units", "sr10", "sr17", "re_state", "re_isgs",
                                             "psp_region", "psp_mix", "psp_state", "psp_ts", "remc", "gd"]}
    issues = []
    ok = manifest[manifest.status == "ok"]
    log(f"parsing {len(ok)} files")
    for i, r in enumerate(ok.itertuples(index=False), 1):
        kind = PARSERS[(r.source, r.report)]
        path = cfg.data_dir / r.local_path
        d = dt.date.fromisoformat(r.report_date)
        fid = _file_id(r)
        try:
            if kind == "sr2":
                st, un = parse.parse_sr2(path, d)
                for x in st: x["source_file_id"] = fid
                for x in un: x["source_file_id"] = fid
                rows["stations"] += st
                rows["units"] += un
            elif kind == "sr10":
                out = parse.parse_sr10(path, d)
                for x in out: x["source_file_id"] = fid
                rows["sr10"] += out
            elif kind == "sr17":
                out = parse.parse_sr17(path, d)
                for x in out: x["source_file_id"] = fid
                rows["sr17"] += out
            elif kind == "re":
                s, g = parse.parse_re(path, d)
                for x in s + g: x["source_file_id"] = fid
                rows["re_state"] += s
                rows["re_isgs"] += g
            elif kind == "psp":
                a, m, s, ts = parse.parse_psp(path, d)
                for x in a + m + s + ts: x["source_file_id"] = fid
                rows["psp_region"] += a
                rows["psp_mix"] += m
                rows["psp_state"] += s
                rows["psp_ts"] += ts
            elif kind == "remc":
                out = parse.parse_remc(path, d)
                for x in out: x["source_file_id"] = fid
                rows["remc"] += out
            elif kind == "gd":
                out = parse.parse_grid_events(path, d)
                for x in out: x["source_file_id"] = fid
                rows["gd"] += out
        except Exception as exc:  # recorded, never silently dropped
            issues.append({"source_file_id": fid, "report_date": r.report_date, "error_type": type(exc).__name__,
                           "message": str(exc)[:300]})
        if i % 300 == 0:
            log(f"  parsed {i}/{len(ok)}")

    df = {k: pd.DataFrame(v) for k, v in rows.items()}
    t: dict[str, pd.DataFrame] = {}

    # ---- core table: one record per entity per day, all energy sources
    st = df["stations"]
    conv = pd.DataFrame({
        "date": st.date, "record_type": "conventional_station", "entity_id": st.station_id,
        "entity_name": st.station, "region": st.region, "state_code": st.state_code, "state": st.state,
        "sector": st.sector, "owner": "", "fuel": st.fuel, "category": st.category,
        "capacity_mw": st.capacity_mw, "program_mu": st.program_mu, "actual_mu": st.actual_mu,
        "cap_under_outage_mw": st.cap_under_outage_mw, "coal_stock_days": st.coal_stock_days,
        "basis": "gross", "source_file_id": st.source_file_id,
    })
    g = df["re_isgs"]
    from .reference import CATEGORY
    isgs = pd.DataFrame({
        "date": g.date, "record_type": "re_station_isgs", "entity_id": g.station_id, "entity_name": g.station,
        "region": g.region, "state_code": g.state_code, "state": g.state, "sector": g.sector, "owner": g.owner,
        "fuel": g.fuel, "category": g.fuel.map(CATEGORY), "capacity_mw": g.capacity_mw, "program_mu": None,
        "actual_mu": g.actual_mu, "cap_under_outage_mw": None, "coal_stock_days": None,
        "basis": "net", "source_file_id": g.source_file_id,
    })
    s = df["re_state"]
    embedded = pd.DataFrame({
        "date": s.date, "record_type": "re_state_embedded", "entity_id": "state-" + s.state_code.str.lower()
        + "-" + s.fuel.str.lower(), "entity_name": s.state + " (state-embedded " + s.fuel.str.lower() + ")",
        "region": s.region, "state_code": s.state_code, "state": s.state, "sector": "State-embedded",
        "owner": "", "fuel": s.fuel, "category": "renewable", "capacity_mw": None, "program_mu": None,
        "actual_mu": s.actual_mu, "cap_under_outage_mw": None, "coal_stock_days": None,
        "basis": "net", "source_file_id": s.source_file_id,
    })
    core = pd.concat([conv, isgs, embedded], ignore_index=True)
    cap = core.capacity_mw.where(core.capacity_mw > 0)
    core["capacity_factor"] = (core.actual_mu * 1000 / (cap * 24)).round(4)
    # Values are kept exactly as reported; implausible ones are flagged, not altered.
    core["quality_flag"] = ""
    core.loc[core.capacity_factor > 1.05, "quality_flag"] = "capacity_factor_above_1.05"
    core.loc[core.actual_mu < 0, "quality_flag"] = "negative_generation"
    t["generation_daily"] = _sort(core, ["date", "record_type", "entity_id"])
    t["generation_daily"].insert(0, "record_id", range(1, len(t["generation_daily"]) + 1))

    u = df["units"].copy()
    u["capacity_factor"] = (u.actual_mu * 1000 / (u.capacity_mw.where(u.capacity_mw > 0) * 24)).round(4)
    t["unit_daily"] = _sort(u, ["date", "unit_id"])

    # ---- outages
    sr10 = classify_reasons(df["sr10"])
    t["outage_snapshot"] = _sort(sr10, ["date", "unit_id", "outage_start"])
    t["outage_events"] = build_events(t["outage_snapshot"], t["unit_daily"], cfg)

    # ---- official totals and grid tables
    t["fuel_daily"] = _sort(df["sr17"], ["date", "fuel"])
    t["grid_region_daily"] = _sort(df["psp_region"], ["date", "region"])
    t["grid_mix_daily"] = _sort(df["psp_mix"], ["date", "region", "source"])
    t["state_supply_daily"] = _sort(df["psp_state"], ["date", "state_code"])
    t["grid_15min"] = _sort(df["psp_ts"], ["date", "time"])

    # ---- solar and wind availability (no official unit-level outage list exists for them)
    t["re_availability_daily"] = _sort(df["remc"], ["date", "section", "scope_type", "scope", "fuel"])
    gd = df["gd"]
    if len(gd):
        gd = gd[(gd.start >= cfg.start.isoformat()) & (gd.start < (cfg.end + dt.timedelta(days=1)).isoformat())]
        gd = _sort(gd, ["start", "month", "seq"])
        gd.insert(0, "event_id", [f"G{i:05d}" for i in range(1, len(gd) + 1)])
    t["grid_events"] = gd
    t["re_zero_output_episodes"] = zero_output_episodes(t["generation_daily"])

    # ---- station master (latest attributes seen in the window)
    master = core.sort_values(["date"], kind="mergesort").groupby("entity_id", as_index=False).agg(
        entity_name=("entity_name", "last"), record_type=("record_type", "last"), region=("region", "last"),
        state_code=("state_code", "last"), state=("state", "last"), sector=("sector", "last"),
        owner=("owner", "last"), fuel=("fuel", "last"), category=("category", "last"),
        latest_capacity_mw=("capacity_mw", "last"), first_date=("date", "min"), last_date=("date", "max"),
        days_reported=("date", "nunique"))
    t["entities"] = _sort(master, ["entity_id"])

    # ---- provenance
    m = manifest.copy()
    m.insert(0, "source_file_id", m.source + "/" + m.report + "/" + m.report_date)
    t["source_files"] = _sort(m, ["source_file_id"])
    gaps = m[m.status != "ok"][["source_file_id", "source", "report", "report_date", "status", "http_status", "note"]]
    iss = pd.DataFrame(issues, columns=["source_file_id", "report_date", "error_type", "message"])
    t["data_gaps"] = _sort(pd.concat([gaps.assign(kind="not_downloaded"),
                                      iss.assign(kind="parse_failed", status="parse_failed")],
                                     ignore_index=True), ["source_file_id"])

    t["validation"] = validate(t, cfg)

    cfg.warehouse_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in t.items():
        frame.to_parquet(cfg.warehouse_dir / f"{name}.parquet", index=False, compression="zstd")
    summary = {name: len(frame) for name, frame in t.items()}
    (cfg.warehouse_dir / "_summary.json").write_text(json.dumps(
        {"window": [cfg.start.isoformat(), cfg.end.isoformat()], "rows": summary}, indent=1), encoding="utf-8")
    log("tables: " + ", ".join(f"{k}={v:,}" for k, v in summary.items()))
    if issues:
        log(f"parse issues: {len(issues)} (see data_gaps)")
    return t
