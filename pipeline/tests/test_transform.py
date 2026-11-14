"""Transform + feed parsing tests (offline, deterministic)."""

from __future__ import annotations

from datetime import date

from pipeline.feeds import RawThreat, fetch_all
from pipeline.models import Severity, Source
from pipeline.transform import build_report, classify_severity, run


def test_offline_fetch_returns_threats():
    threats = fetch_all(offline=True)
    assert threats, "offline fixtures should yield threats"
    # The domain-hosted URLhaus entry (evil.example.com) must be dropped.
    assert all(t.ip != "evil.example.com" for t in threats)


def test_severity_classification_rules():
    online_apex = RawThreat("1.1.1.1", "US", date(2026, 1, 1), Source.FEODO, True, "QakBot")
    online_plain = RawThreat("1.1.1.2", "US", date(2026, 1, 1), Source.FEODO, True, "")
    offline_malware = RawThreat("1.1.1.3", "US", date(2026, 1, 1), Source.FEODO, False, "Dridex")
    offline_plain = RawThreat("1.1.1.4", "US", date(2026, 1, 1), Source.FEODO, False, "")

    assert classify_severity(online_apex) is Severity.SINGULARITY
    assert classify_severity(online_plain) is Severity.POSSESSION
    assert classify_severity(offline_malware) is Severity.HAUNTING
    assert classify_severity(offline_plain) is Severity.FLATLINE


def test_build_report_geolocates_and_targets():
    report = run(offline=True, report_date=date(2026, 11, 14))
    assert report.report_date == date(2026, 11, 14)
    assert report.machines

    for m in report.machines:
        assert -90 <= m.lat <= 90
        assert -180 <= m.lon <= 180
        assert -90 <= m.tgt_lat <= 90
        assert -180 <= m.tgt_lon <= 180
        assert len(m.country) == 2


def test_report_is_deterministic():
    # The machine set must be stable across runs; only generated_at may differ.
    r1 = build_report(fetch_all(offline=True), report_date=date(2026, 11, 14))
    r2 = build_report(fetch_all(offline=True), report_date=date(2026, 11, 14))
    assert [m.to_json() for m in r1.machines] == [m.to_json() for m in r2.machines]
    assert r1.report_date == r2.report_date


def test_stats_sum_matches_total():
    report = run(offline=True)
    stats = report.stats()
    assert sum(stats["by_severity"].values()) == stats["total"] == len(report.machines)
