"""Curated reference data (versioned in reference/). These are the only inputs not taken from the sources."""
from __future__ import annotations

import csv
import re
from functools import lru_cache

from .config import ROOT

REF = ROOT / "reference"

REGIONS = {
    "NORTHERN": "Northern", "WESTERN": "Western", "SOUTHERN": "Southern", "EASTERN": "Eastern",
    "NORTH EASTERN": "North-Eastern", "NORTH-EASTERN": "North-Eastern", "NORTHEASTERN": "North-Eastern",
    "NR": "Northern", "WR": "Western", "SR": "Southern", "ER": "Eastern", "NER": "North-Eastern",
    "BHUTAN IMP.": "Import",
}

# Energy-source category used throughout. Large hydro counts as renewable (the project's definition);
# nuclear is kept separate; Bhutan hydro imports are kept out of domestic totals.
CATEGORY = {
    "COAL": "non_renewable", "LIGNITE": "non_renewable", "GAS": "non_renewable",
    "DIESEL": "non_renewable", "NAPHTHA": "non_renewable",
    "NUCLEAR": "nuclear",
    "HYDRO": "renewable", "SOLAR": "renewable", "WIND": "renewable", "HYBRID": "renewable",
    "OTHER_RES": "renewable",
    "HYDRO_IMPORT": "import",
}


def norm_key(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s).replace("​", "")).strip().upper()
    return s


@lru_cache(maxsize=1)
def _states() -> dict[str, tuple[str, str, str]]:
    out = {}
    with (REF / "states.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rec = (row["state_code"], row["state"], row["region"])
            out[norm_key(row["state"])] = rec
            for a in row["aliases"].split("|"):
                if a:
                    out[norm_key(a)] = rec
    return out


def state(name: str) -> tuple[str, str, str] | None:
    """(code, canonical name, region) or None when the name is not a known state."""
    key = norm_key(name)
    # Bilingual labels in the CEA RE report: "हरियाणा / Haryana"
    if "/" in key:
        key = norm_key(key.split("/")[-1])
    return _states().get(key)


@lru_cache(maxsize=1)
def lignite_patterns() -> list[re.Pattern]:
    with (REF / "lignite_stations.csv").open(encoding="utf-8") as fh:
        return [re.compile(r["pattern"], re.I) for r in csv.DictReader(fh)]


@lru_cache(maxsize=1)
def naphtha_patterns() -> list[re.Pattern]:
    with (REF / "naphtha_stations.csv").open(encoding="utf-8") as fh:
        return [re.compile(r["pattern"], re.I) for r in csv.DictReader(fh)]


def fuel_for(type_label: str, station: str, region: str) -> str:
    """Map a CEA DGR plant 'TYPE' plus station name to a fuel."""
    if region == "Import":
        return "HYDRO_IMPORT"
    t = norm_key(type_label)
    if t == "HYDRO":
        return "HYDRO"
    if t == "NUCLEAR":
        return "NUCLEAR"
    if t == "THER (DG)":
        return "DIESEL"
    if t == "THER (GT)":
        return "NAPHTHA" if any(p.search(station) for p in naphtha_patterns()) else "GAS"
    if t == "THERMAL":
        return "LIGNITE" if any(p.search(station) for p in lignite_patterns()) else "COAL"
    return "UNKNOWN"


def slug(*parts: str) -> str:
    s = "-".join(norm_key(p) for p in parts if p)
    return re.sub(r"[^A-Z0-9]+", "-", s).strip("-").lower()
