"""Parser tests against real report files (one day of each source, plus an older PSP layout)."""
import datetime as dt
from collections import defaultdict
from pathlib import Path

import pytest

from observatory import parse

FX = Path(__file__).parent / "fixtures"
D = dt.date(2026, 10, 12)


def test_sr2_reconciles_with_sr17():
    stations, units = parse.parse_sr2(FX / "sr02_2026-10-12.xls", D)
    fuels = parse.parse_sr17(FX / "sr17_2026-10-12.xls", D)
    cap, gen = defaultdict(float), defaultdict(float)
    for s in stations:
        cap[s["fuel"]] += s["capacity_mw"] or 0
        gen[s["fuel"]] += s["actual_mu"] or 0
    for f in fuels:
        if f["fuel"] == "HSD":
            continue
        assert cap[f["fuel"]] == pytest.approx(f["monitored_capacity_mw"], abs=1.0), f["fuel"]
        assert gen[f["fuel"]] == pytest.approx(f["actual_mu"], abs=0.5), f["fuel"]
    assert len({u["unit_id"] for u in units}) == len(units), "wrapped remark rows must be merged"
    assert all(s["state_code"] for s in stations)


def test_sr2_rejects_wrong_date():
    with pytest.raises(parse.FormatError):
        parse.parse_sr2(FX / "sr02_2026-10-12.xls", dt.date(2026, 10, 11))


def test_sr10_outages():
    rows = parse.parse_sr10(FX / "sr10_2026-10-12.xls", D)
    assert len(rows) > 50
    assert sum(r["planned_mw"] for r in rows) == pytest.approx(6138.5)
    assert sum(r["forced_major_mw"] for r in rows) == pytest.approx(4491.01)
    assert sum(r["forced_minor_mw"] for r in rows) == pytest.approx(19253.0)
    assert len({(r["unit_id"], r["outage_start"]) for r in rows}) == len(rows)


def test_re_report_no_double_counting():
    states, isgs = parse.parse_re(FX / "re_2026-10-12.xlsx", D)
    assert {s["fuel"] for s in states} == {"WIND", "SOLAR", "OTHER_RES"}
    assert len({(s["state_code"], s["fuel"]) for s in states}) == len(states)
    assert all(not r["station"].upper().endswith("REGION") for r in isgs)
    assert all(r["state_code"] for r in isgs)


@pytest.mark.parametrize("name,day", [("psp_2026-10-12.xls", D), ("psp_2026-03-15.xls", dt.date(2026, 3, 15))])
def test_psp_both_layouts(name, day):
    regions, mix, states, ts = parse.parse_psp(FX / name, day)
    ai = {r["source"]: r["gross_mu"] for r in mix if r["region"] == "All India"}
    parts = sum(v for k, v in ai.items() if k != "TOTAL")
    assert parts == pytest.approx(ai["TOTAL"], abs=1.0)
    assert len(states) >= 30
    assert len(ts) == 96
    assert next(r for r in regions if r["region"] == "All India")["evening_peak_shortage_mw"] is not None


def test_remc_availability():
    rows = parse.parse_remc(FX / "remc_2026-10-12.pdf", D)
    ai = {r["fuel"]: r for r in rows if r["section"] == "remc_regional" and r["scope_type"] == "all_india"}
    assert ai["SOLAR"]["installed_mw"] == 120330 and ai["SOLAR"]["available_mw"] == 114155
    assert ai["WIND"]["unavailable_mw"] == 56870 - 53637
    regions = [r for r in rows if r["section"] == "remc_regional" and r["scope_type"] == "region"]
    assert sum(r["installed_mw"] for r in regions if r["fuel"] == "SOLAR") == pytest.approx(ai["SOLAR"]["installed_mw"])
    assert all(r["scope_type"] != "other" for r in rows)


def test_grid_events():
    ev = parse.parse_grid_events(FX / "grid_events_2026-09.pdf", dt.date(2026, 9, 1))
    assert len(ev) > 40
    assert all(e["start"].startswith("2026-09") for e in ev)
    chugger = [e for e in ev if "Chugger" in e["summary"]]
    assert chugger and chugger[0]["involves_wind"] and chugger[0]["generation_loss_mw"] == 76
    assert "76.4 MW" in chugger[0]["summary"]
