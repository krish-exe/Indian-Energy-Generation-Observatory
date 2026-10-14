from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    start: dt.date
    end: dt.date
    data_dir: Path
    dashboard_data_dir: Path
    user_agent: str
    min_interval_s: float
    timeout_s: float
    retries: int
    dgr_reports: tuple[int, ...]

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def warehouse_dir(self) -> Path:
        return self.data_dir / "warehouse"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.csv"

    def dates(self) -> list[dt.date]:
        n = (self.end - self.start).days
        return [self.start + dt.timedelta(days=i) for i in range(n + 1)]


def load(path: Path | None = None, start: str | None = None, end: str | None = None) -> Config:
    raw = yaml.safe_load((path or ROOT / "observatory.yaml").read_text(encoding="utf-8"))
    w = raw["window"]
    s = dt.date.fromisoformat(str(start or w["start"]))
    e = dt.date.fromisoformat(str(end or w["end"]))
    if e < s:
        raise ValueError(f"window end {e} is before start {s}")
    return Config(
        start=s,
        end=e,
        data_dir=ROOT / raw["paths"]["data"],
        dashboard_data_dir=ROOT / raw["paths"]["dashboard_data"],
        user_agent=raw["http"]["user_agent"],
        min_interval_s=float(raw["http"]["min_interval_s"]),
        timeout_s=float(raw["http"]["timeout_s"]),
        retries=int(raw["http"]["retries"]),
        dgr_reports=tuple(raw["sources"]["npp_dgr"]["reports"]),
    )
