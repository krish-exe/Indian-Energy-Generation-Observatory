"""Write the published dataset (Excel, CSV, Parquet) and the dashboard's data files.

All writers use fixed settings (no build timestamps, sorted rows, fixed zip dates) so the same warehouse
gives byte-identical outputs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import shutil
import zipfile

import pandas as pd
import xlsxwriter

from . import insights as insights_mod
from . import metrics as metrics_mod
from .config import ROOT, Config
from .dictionary import COLUMNS, TABLES

PUBLISHED = ["generation_daily", "unit_daily", "outage_snapshot", "outage_events", "fuel_daily",
             "grid_region_daily", "grid_mix_daily", "state_supply_daily", "grid_15min",
             "re_availability_daily", "grid_events", "re_zero_output_episodes", "entities",
             "source_files", "data_gaps", "validation"]
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def load(cfg: Config) -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_parquet(p) for p in sorted(cfg.warehouse_dir.glob("*.parquet"))}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def write_xlsx(name: str, df: pd.DataFrame, path, cfg: Config) -> None:
    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True, "strings_to_formulas": False,
                                         "strings_to_urls": False})
    wb.set_properties({"title": f"Indian Energy Generation Observatory - {name}",
                       "created": dt.datetime.combine(cfg.end, dt.time()), "author": "observatory pipeline"})
    bold = wb.add_format({"bold": True})
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    datef = wb.add_format({"num_format": "yyyy-mm-dd"})
    about = wb.add_worksheet("about")
    about.set_column(0, 0, 28)
    about.set_column(1, 1, 110)
    rows = [("Table", name), ("Description", TABLES.get(name, "")),
            ("Period", f"{cfg.start} to {cfg.end}"), ("Rows", f"{len(df):,}"),
            ("Sources", "Central Electricity Authority (npp.gov.in, gen-re.cea.gov.in); Grid Controller of India "
                        "(grid-india.in). Every value traces to a file in source_files via source_file_id."),
            ("Rebuild", "python -m observatory refresh  (see README)"), ("", ""), ("Column", "Meaning")]
    for i, (k, v) in enumerate(rows):
        about.write(i, 0, k, bold if k else None)
        about.write(i, 1, v, wrap)
    for j, c in enumerate(df.columns, start=len(rows)):
        about.write(j, 0, c)
        about.write(j, 1, COLUMNS.get(c, ""), wrap)
    ws = wb.add_worksheet("data")
    date_cols = {i for i, c in enumerate(df.columns) if c in ("date", "first_date", "last_date", "first_seen",
                                                                 "last_seen", "report_date")}
    for j, c in enumerate(df.columns):
        ws.write(0, j, c, bold)
    for i, row in enumerate(df.itertuples(index=False, name=None), start=1):
        for j, v in enumerate(row):
            v = _clean(v)
            if v is None or v == "":
                continue
            if j in date_cols and isinstance(v, str) and len(v) == 10:
                ws.write_datetime(i, j, dt.datetime.strptime(v, "%Y-%m-%d"), datef)
            elif isinstance(v, (bool,)):
                ws.write_boolean(i, j, v)
            elif hasattr(v, "item"):
                ws.write(i, j, v.item())
            else:
                ws.write(i, j, v)
    ws.freeze_panes(1, 0)
    wb.close()


def write_csv_zip(name: str, df: pd.DataFrame, path) -> None:
    data = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
    info = zipfile.ZipInfo(f"{name}.csv", date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(info, data)


def _json(obj, path) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _nan_to_none(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _nan_to_none(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_nan_to_none(v) for v in o]
    if hasattr(o, "item"):
        return _nan_to_none(o.item())
    return o


def entity_files(t: dict[str, pd.DataFrame], out_dir) -> list[dict]:
    """One small JSON per station for the station explorer (loaded on demand)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    core = t["generation_daily"]
    ev = t["outage_events"]
    ev_by = {k: g for k, g in ev.groupby("station_id")}
    zep = t.get("re_zero_output_episodes")
    zep_by = {k: g for k, g in zep.groupby("entity_id")} if zep is not None and len(zep) else {}
    index = []
    ent = t["entities"].set_index("entity_id")
    for eid, g in core.groupby("entity_id", sort=True):
        e = ent.loc[eid]
        rec = {"id": eid, "name": e.entity_name, "type": e.record_type, "state": e.state, "region": e.region,
               "fuel": e.fuel, "sector": e.sector, "owner": e.owner, "capacity_mw": _clean(e.latest_capacity_mw),
               "days": int(e.days_reported)}
        index.append(rec)
        g = g.sort_values("date")
        series = {c: [_clean(v) for v in g[c].tolist()] for c in
                  ["date", "capacity_mw", "program_mu", "actual_mu", "cap_under_outage_mw", "capacity_factor",
                   "coal_stock_days", "source_file_id"]}
        events = []
        if eid in ev_by:
            for r in ev_by[eid].itertuples(index=False):
                events.append({"unit": r.unit_no, "start": r.outage_start, "end": r.end_time,
                               "end_status": r.end_status, "last_seen": r.last_seen, "mw": _clean(r.max_unavailable_mw),
                               "cause": r.cause_group, "reason": r.reason, "duration_h": _clean(r.duration_h)})
        zeros = [{"first": r.first_date, "last": r.last_date, "days": int(r.days)}
                 for r in zep_by[eid].itertuples(index=False)] if eid in zep_by else []
        _json(_nan_to_none({**rec, "series": series, "events": events, "zero_episodes": zeros}), out_dir / f"{eid}.json")
    return index


def export(cfg: Config, log=print) -> None:
    t = load(cfg)
    dash = cfg.dashboard_data_dir
    dl = dash / "downloads"
    dl.mkdir(parents=True, exist_ok=True)

    log("metrics + insights")
    m = _nan_to_none(metrics_mod.compute(t, cfg))
    ins = insights_mod.build(m)
    _json(m, dash / "metrics.json")
    _json(ins, dash / "insights.json")

    log("station files")
    index = entity_files(t, dash / "entities")
    _json(_nan_to_none(index), dash / "entities.json")

    catalog = []
    for name in PUBLISHED:
        df = t[name]
        log(f"  {name}: {len(df):,} rows")
        files = {}
        if len(df) <= 1_000_000:
            write_xlsx(name, df, dl / f"{name}.xlsx", cfg)
            files["xlsx"] = f"{name}.xlsx"
        write_csv_zip(name, df, dl / f"{name}.csv.zip")
        files["csv"] = f"{name}.csv.zip"
        shutil.copyfile(cfg.warehouse_dir / f"{name}.parquet", dl / f"{name}.parquet")
        files["parquet"] = f"{name}.parquet"
        catalog.append({"table": name, "description": TABLES.get(name, ""), "rows": int(len(df)),
                        "columns": [{"name": c, "description": COLUMNS.get(c, "")} for c in df.columns],
                        "files": {k: {"path": v, "bytes": (dl / v).stat().st_size} for k, v in files.items()}})
    _json(catalog, dash / "catalog.json")

    # release manifest: inputs (URL + hash) and output checksums
    outputs = {}
    for p in sorted(dl.iterdir()):
        outputs[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    src = t["source_files"]
    manifest = {"window": [cfg.start.isoformat(), cfg.end.isoformat()],
                "inputs": src[src.status == "ok"][["source_file_id", "url", "sha256"]].to_dict(orient="records"),
                "outputs": outputs, "row_counts": {k: int(len(v)) for k, v in t.items()}}
    _json(manifest, dash / "release_manifest.json")
    write_dictionary_md(t)
    log(f"exported to {dash}")


def write_dictionary_md(t) -> None:
    lines = ["# Data dictionary", "", "Generated by `python -m observatory export`. Every table is in "
             "`dashboard/data/downloads/` as Excel (.xlsx), zipped CSV and Parquet.", ""]
    for name in PUBLISHED:
        df = t[name]
        lines += [f"## `{name}` ({len(df):,} rows)", "", TABLES.get(name, ""), "", "| Column | Meaning |", "|---|---|"]
        lines += [f"| `{c}` | {COLUMNS.get(c, '')} |" for c in df.columns]
        lines.append("")
    (ROOT / "docs" / "data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")
