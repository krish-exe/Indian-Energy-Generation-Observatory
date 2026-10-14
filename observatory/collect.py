"""Download every report in the window from the official sources.

Each file lands in data/raw/<source>/<report>/<year>/<date>.<ext>. Every attempt, successful or not, is
written to data/manifest.csv with its URL, HTTP status, size and SHA-256. Without --fresh, a file already
on disk from an earlier run of this collector is reused (it was downloaded from the same URL).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import Config
from .http import PoliteSession

NPP_DGR = "https://npp.gov.in/public-reports/cea/daily/dgr/{dmy}/dgr{n}-{ymd}.xls"
CEA_RE = "https://gen-re.cea.gov.in/public/uploads/dailyReport/excel/Report-{ymd}.xlsx"
GI_API = "https://webapi.grid-india.in/api/v1/file"
GI_CDN = "https://webcdn.grid-india.in/"

MAGIC = {".xls": b"\xd0\xcf\x11\xe0", ".xlsx": b"PK\x03\x04", ".pdf": b"%PDF"}
MANIFEST_FIELDS = ["source", "report", "report_date", "url", "local_path", "status", "http_status",
                   "bytes", "sha256", "fetched_at", "note"]


@dataclass
class Target:
    source: str
    report: str
    report_date: dt.date
    url: str
    path: Path


@dataclass
class Record:
    source: str
    report: str
    report_date: str
    url: str
    local_path: str
    status: str          # ok | missing | invalid | error
    http_status: int
    bytes: int
    sha256: str
    fetched_at: str
    note: str = ""


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def npp_targets(cfg: Config) -> list[Target]:
    out = []
    for d in cfg.dates():
        for n in cfg.dgr_reports:
            url = NPP_DGR.format(dmy=d.strftime("%d-%m-%Y"), n=n, ymd=d.isoformat())
            out.append(Target("npp_dgr", f"sr{n:02d}", d, url,
                              cfg.raw_dir / "npp_dgr" / f"sr{n:02d}" / str(d.year) / f"{d}.xls"))
    return out


def re_targets(cfg: Config) -> list[Target]:
    return [Target("cea_re_daily", "daily_re", d, CEA_RE.format(ymd=d.isoformat()),
                   cfg.raw_dir / "cea_re_daily" / "daily_re" / str(d.year) / f"{d}.xlsx")
            for d in cfg.dates()]


def _fy(d: dt.date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"], start=1)}


def _psp_date(title: str):
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", title, re.I)
    return dt.date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _remc_date(title: str):
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})_NLDC_REMC", title, re.I)
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _gd_month(title: str):
    """GD_GI_Jan_2026, GD_GI_April_25, GD_GI_September_2026 -> first day of that month."""
    m = re.search(r"GD_GI_([A-Za-z]+)_(\d{2,4})", title, re.I)
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        return None
    y = int(m.group(2))
    return dt.date(y + 2000 if y < 100 else y, _MONTHS[m.group(1)[:3].lower()], 1)


# (source, report, Grid-India file type, title -> report date, file extension, cadence)
GRID_INDIA = [
    ("grid_india_psp", "psp", "DAILY_PSP_REPORT", _psp_date, ".xls", "daily"),
    ("grid_india_remc", "remc", "DAILY_VRE_REPORT", _remc_date, ".pdf", "daily"),
    ("grid_india_gd", "grid_events", "MONTHLY_GRID_DISTURBANCE", _gd_month, ".pdf", "monthly"),
]


def grid_india_targets(cfg: Config, http: PoliteSession, spec) -> tuple[list[Target], list[str]]:
    """Grid-India file names carry random suffixes, so the listing API is the only way to find them.
    Files are filed under their upload month (a day's report the next day, a month's report up to two
    months later), so the listing runs past the window. When a period has several uploads (revisions),
    the last one wins."""
    source, report, ftype, to_date, ext, cadence = spec
    months, d = [], cfg.start.replace(day=1)
    stop = (cfg.end.replace(day=1) + dt.timedelta(days=95)).replace(day=1)
    while d <= stop:
        # Grid-India sometimes files a period under the previous financial year (e.g. the March 2026 grid
        # events report sits under 2025-26 / 04), so both candidate years are listed.
        prev = f"{int(_fy(d)[:4]) - 1}-{_fy(d)[2:4]}"
        months += [(_fy(d), f"{d.month:02d}"), (prev, f"{d.month:02d}")]
        d = (d + dt.timedelta(days=32)).replace(day=1)
    if cadence == "daily":
        wanted = cfg.dates()
    else:
        wanted, m = [], cfg.start.replace(day=1)
        while m <= cfg.end.replace(day=1):
            wanted.append(m)
            m = (m + dt.timedelta(days=32)).replace(day=1)

    listing_dir = cfg.raw_dir / source / "_listing"
    listing_dir.mkdir(parents=True, exist_ok=True)
    best: dict[dt.date, dict] = {}
    for fy, mm in months:
        resp = http.post(GI_API, json={"_source": "grdw", "_type": ftype, "_fileDate": fy, "_month": mm})
        resp.raise_for_status()
        rows = resp.json().get("retData") or []
        (listing_dir / f"{fy}_{mm}.json").write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")
        for r in rows:
            day = to_date(r.get("Title_") or "")
            if day is None or day not in wanted or not str(r.get("FilePath", "")).lower().endswith(ext):
                continue
            stamp = dt.datetime.strptime(r.get("ModifiedOn") or r["CreatedOn"], "%d-%m-%Y %H:%M")
            if day not in best or (stamp, r["Id"]) > best[day]["_key"]:
                best[day] = {**r, "_key": (stamp, r["Id"])}
    targets = [Target(source, report, day, GI_CDN + best[day]["FilePath"],
                      cfg.raw_dir / source / report / str(day.year) / f"{day}{ext}")
               for day in sorted(best)]
    return targets, [w.isoformat() for w in wanted if w not in best]


def _fetch(t: Target, http: PoliteSession, fresh: bool) -> Record:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rel = t.path.as_posix()
    if t.path.exists() and not fresh:
        return Record(t.source, t.report, t.report_date.isoformat(), t.url, rel, "ok", 200,
                      t.path.stat().st_size, _sha256(t.path), now, "cached")
    try:
        resp = http.get(t.url)
    except Exception as exc:  # network failure after retries
        return Record(t.source, t.report, t.report_date.isoformat(), t.url, rel, "error", 0, 0, "", now,
                      str(exc)[:200])
    if resp.status_code == 404:
        return Record(t.source, t.report, t.report_date.isoformat(), t.url, rel, "missing", 404, 0, "", now)
    body = resp.content
    if resp.status_code != 200 or not body.startswith(MAGIC[t.path.suffix]):
        return Record(t.source, t.report, t.report_date.isoformat(), t.url, rel, "invalid",
                      resp.status_code, len(body), "", now, resp.headers.get("content-type", ""))
    t.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = t.path.with_suffix(t.path.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(t.path)
    return Record(t.source, t.report, t.report_date.isoformat(), t.url, rel, "ok", 200, len(body),
                  hashlib.sha256(body).hexdigest(), now)


def collect(cfg: Config, fresh: bool = False, log=print) -> list[Record]:
    http = PoliteSession(cfg.user_agent, cfg.min_interval_s, cfg.timeout_s, cfg.retries)
    groups = {"npp_dgr": npp_targets(cfg), "cea_re_daily": re_targets(cfg)}
    unlisted = {}
    for spec in GRID_INDIA:
        groups[spec[0]], unlisted[spec] = grid_india_targets(cfg, http, spec)
    log("targets: " + ", ".join(f"{k}={len(v)}" for k, v in groups.items())
        + " (not in Grid-India listing: " + ", ".join(f"{s[1]}={len(u)}" for s, u in unlisted.items()) + ")")

    def run(name: str) -> list[Record]:
        recs = []
        for i, t in enumerate(groups[name], 1):
            recs.append(_fetch(t, http, fresh))
            if i % 100 == 0 or i == len(groups[name]):
                bad = sum(r.status != "ok" for r in recs)
                log(f"  {name}: {i}/{len(groups[name])} done, {bad} not ok")
        return recs

    # One worker per host; each host is still rate limited on its own.
    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        results = list(pool.map(run, groups))
    records = [r for group in results for r in group]
    for spec, missing in unlisted.items():
        for day in missing:
            records.append(Record(spec[0], spec[1], day, GI_API, "", "missing", 0, 0, "",
                                  dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                  "not in Grid-India listing"))
    records.sort(key=lambda r: (r.source, r.report, r.report_date))

    cfg.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg.manifest_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for r in records:
            row = asdict(r)
            row["local_path"] = Path(row["local_path"]).relative_to(cfg.data_dir).as_posix() \
                if row["local_path"] else ""
            w.writerow(row)
    ok = sum(r.status == "ok" for r in records)
    log(f"manifest: {ok}/{len(records)} files ok -> {cfg.manifest_path}")
    return records
