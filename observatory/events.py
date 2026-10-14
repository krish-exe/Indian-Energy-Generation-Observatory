"""Outage reason classes and outage-event reconstruction from CEA's daily outage snapshots (SR-10).

SR-10 is a daily list of units that are out. It is a snapshot, not an event log, so events are stitched
together by (unit, outage start time). An event's end is:
  observed  - the report gave a sync/return time
  inferred  - the unit dropped off the list between two reports without a return time; the end is only
              known to lie in that interval, so no exact duration is claimed
  ongoing   - still out on the last report in the window (right-censored)
"""
from __future__ import annotations

import csv
import datetime as dt
import re

import pandas as pd

from .config import Config
from .reference import REF

_FMT = "%Y-%m-%dT%H:%M"


def _patterns() -> list[tuple[re.Pattern, str]]:
    with (REF / "outage_reasons.csv").open(encoding="utf-8") as fh:
        return [(re.compile(r["pattern"], re.I), r["reason_class"]) for r in csv.DictReader(fh)]


def classify_reasons(sr10: pd.DataFrame) -> pd.DataFrame:
    if sr10.empty:
        return sr10
    pats = _patterns()
    df = sr10.copy()

    def text_class(reason: str) -> str:
        for p, c in pats:
            if p.search(reason or ""):
                return c
        return "forced_equipment" if reason else "unspecified"

    df["reason_class"] = df.reason.map(text_class)
    mw = df[["planned_mw", "forced_major_mw", "forced_minor_mw", "other_mw"]]
    df["unavailable_mw"] = mw.sum(axis=1)
    kind = mw.idxmax(axis=1).str.replace("_mw", "", regex=False)
    df["outage_type"] = kind.where(df.unavailable_mw > 0, "returned_same_day")

    # cause_group: text classes that are not equipment faults win; otherwise CEA's planned/forced column.
    def group(row) -> str:
        if row.reason_class in ("commercial", "fuel_supply", "long_term_or_retired", "regulatory_or_other"):
            return row.reason_class
        if row.outage_type == "planned" or row.reason_class == "planned":
            return "planned"
        return "forced_equipment"

    df["cause_group"] = df.apply(group, axis=1)
    return df


def build_events(snap: pd.DataFrame, units: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    cols = ["event_id", "unit_id", "station_id", "station", "unit_no", "state_code", "state", "region",
            "fuel", "unit_capacity_mw", "outage_start", "end_status", "end_time", "end_window_lower",
            "end_window_upper", "duration_h", "first_seen", "last_seen", "days_listed", "max_unavailable_mw",
            "outage_type", "cause_group", "reason", "started_before_window", "unavailable_hours_in_window"]
    if snap.empty:
        return pd.DataFrame(columns=cols)
    report_days = sorted(snap.date.unique())
    next_day = {d: report_days[i + 1] if i + 1 < len(report_days) else None for i, d in enumerate(report_days)}
    win_start = dt.datetime.combine(cfg.start, dt.time())
    win_end = dt.datetime.combine(cfg.end + dt.timedelta(days=1), dt.time())

    unit_info = units.drop_duplicates("unit_id", keep="last").set_index("unit_id")[["capacity_mw", "fuel"]] \
        if len(units) else pd.DataFrame(columns=["capacity_mw", "fuel"])
    cap_by_day = {(u, d): c for u, d, c in zip(units.unit_id, units.date, units.capacity_mw)} \
        if len(units) else {}

    s = snap.copy()
    s["start_key"] = s.outage_start.fillna("first_seen:" + s.date)
    out = []
    for (unit_id, start_key), g in s.sort_values(["date"], kind="mergesort").groupby(
            ["unit_id", "start_key"], sort=True):
        first, last = g.date.iloc[0], g.date.iloc[-1]
        start = dt.datetime.strptime(g.outage_start.iloc[0], _FMT) if g.outage_start.iloc[0] else None
        returns = g.return_time.dropna()
        end_time = end_lo = end_hi = None
        if len(returns):
            status, end_time = "observed", dt.datetime.strptime(returns.iloc[-1], _FMT)
        elif next_day[last] is not None:
            status = "inferred"
            end_lo = dt.datetime.combine(dt.date.fromisoformat(last), dt.time()) + dt.timedelta(days=1)
            end_hi = dt.datetime.combine(dt.date.fromisoformat(next_day[last]), dt.time()) + dt.timedelta(days=1)
        else:
            status = "ongoing"
        duration = (end_time - start).total_seconds() / 3600 if (status == "observed" and start) else None
        if duration is not None and duration < 0:
            duration = None
        # hours unavailable inside the window (lower bound when the end is only inferred)
        seg_start = max(start, win_start) if start else dt.datetime.combine(dt.date.fromisoformat(first), dt.time())
        seg_end = end_time or end_lo or win_end
        hours = max(0.0, (min(seg_end, win_end) - seg_start).total_seconds() / 3600)
        cap = cap_by_day.get((unit_id, first))
        if cap is None or pd.isna(cap):
            cap = unit_info.capacity_mw.get(unit_id) if unit_id in unit_info.index else None
        nonzero = g[g.unavailable_mw > 0]
        last_row = g.iloc[-1]
        out.append({
            "unit_id": unit_id, "station_id": last_row.station_id, "station": last_row.station,
            "unit_no": last_row.unit_no, "state_code": last_row.state_code, "state": last_row.state,
            "region": last_row.region,
            "fuel": unit_info.fuel.get(unit_id) if unit_id in unit_info.index else None,
            "unit_capacity_mw": cap, "outage_start": start.strftime(_FMT) if start else None,
            "end_status": status, "end_time": end_time.strftime(_FMT) if end_time else None,
            "end_window_lower": end_lo.strftime(_FMT) if end_lo else None,
            "end_window_upper": end_hi.strftime(_FMT) if end_hi else None,
            "duration_h": round(duration, 2) if duration is not None else None,
            "first_seen": first, "last_seen": last, "days_listed": int(g.date.nunique()),
            "max_unavailable_mw": float(g.unavailable_mw.max()),
            "outage_type": (nonzero.outage_type.mode().iloc[0] if len(nonzero) else "returned_same_day"),
            "cause_group": last_row.cause_group, "reason": last_row.reason,
            "started_before_window": bool(start and start < win_start),
            "unavailable_hours_in_window": round(hours, 2),
        })
    ev = pd.DataFrame(out)
    ev = ev.sort_values(["outage_start", "unit_id"], kind="mergesort", na_position="first").reset_index(drop=True)
    ev.insert(0, "event_id", [f"E{i:06d}" for i in range(1, len(ev) + 1)])
    return ev[cols]
