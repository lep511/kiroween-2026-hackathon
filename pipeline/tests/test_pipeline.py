"""Pipeline tests: news ingestion -> extraction -> report (offline, deterministic)."""

from __future__ import annotations

from datetime import date

from pipeline.extract import (
    attribute_origin,
    classify_attack,
    classify_severity,
    detect_data,
)
from pipeline.geolocate import resolve_country
from pipeline.models import Severity, Witness
from pipeline.sources import RawArticle, fetch_all, parse_rss
from pipeline.transform import build_report, run

# ---- Sources ---------------------------------------------------------------


def test_offline_fetch_returns_curated_incidents():
    articles = fetch_all(offline=True)
    assert articles, "offline curated incidents should yield articles"
    witnesses = {a.witness for a in articles}
    # The curated offline set covers these recognized outlets (each with a concrete link).
    assert {"bbc", "cnn", "nyt", "thehackernews", "hackernoon"} <= witnesses
    # The user's reference article is present.
    assert any("Fridges in French supermarkets" in a.title for a in articles)


def test_rss_parser_keeps_only_cyber_items():
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Hackers breach a bank in a huge cyber attack</title>
            <description>Millions of records stolen.</description>
            <link>https://example.com/2026/11/bank-breach-millions</link>
            <pubDate>Sat, 14 Nov 2026 06:42:27 GMT</pubDate></item>
      <item><title>New smartphone announced</title>
            <description>A shiny gadget.</description>
            <link>https://example.com/2026/11/new-smartphone</link></item>
    </channel></rss>"""
    out = parse_rss("bbc", xml)
    assert len(out) == 1
    assert out[0].url == "https://example.com/2026/11/bank-breach-millions"
    assert out[0].published == date(2026, 11, 14)


# ---- Extraction heuristics -------------------------------------------------


def test_classify_attack_detects_ransomware():
    attack_type, prevention = classify_attack("a ransomware gang locked their systems")
    assert attack_type == "ransomware"
    assert "backup" in prevention.lower()


def test_classify_severity_tiers():
    assert classify_severity("millions of records stolen") is Severity.DOMINION
    assert classify_severity("attackers hacked the server") is Severity.SIEGE
    assert classify_severity("vendor warns of a flaw") is Severity.BREACH
    assert classify_severity("a quiet advisory about config") in (
        Severity.BREACH,
        Severity.TREMOR,
    )


def test_detect_data_and_origin():
    assert "health" in detect_data("hospital patient medical breach").lower()
    assert attribute_origin("north korean hackers stole crypto") == "KP"
    assert attribute_origin("russian group sandworm hit the grid") == "RU"
    assert attribute_origin("no attribution here") is None


def test_resolve_country_demonyms():
    assert resolve_country("French supermarkets hit") == "FR"
    assert resolve_country("Taiwanese users targeted") == "TW"
    assert resolve_country("North Korean operators") == "KP"


# ---- End-to-end report -----------------------------------------------------


def test_build_report_populates_strikes():
    report = run(offline=True, report_date=date(2026, 11, 14))
    assert report.report_date == date(2026, 11, 14)
    assert report.strikes

    ids = [s.id for s in report.strikes]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)  # unique, ordered ids

    for s in report.strikes:
        assert -90 <= s.lat <= 90 and -180 <= s.lon <= 180
        assert -90 <= s.origin_lat <= 90 and -180 <= s.origin_lon <= 180
        assert len(s.country) == 2
        # Every strike carries the full dossier the UI needs.
        assert s.title and s.data_affected and s.impact and s.prevention and s.url


def test_bbc_reference_incident_extracted_correctly():
    report = run(offline=True, report_date=date(2026, 11, 14))
    fridge = next(s for s in report.strikes if "Fridges" in s.title)
    assert fridge.witness is Witness.BBC
    assert fridge.country == "FR"
    assert fridge.severity is Severity.DOMINION
    assert fridge.attack_type == "operational-technology"
    assert "euros" in fridge.impact.lower()


def test_overrides_win_over_heuristics():
    art = RawArticle(
        witness="cnn",
        title="generic hack",
        summary="something happened",
        url="https://example.com",
        published=date(2026, 1, 1),
        country="US",
        overrides={"severity": "tremor", "prevention": "custom ward", "location": "Nowhere"},
    )
    report = build_report([art], report_date=date(2026, 1, 1))
    s = report.strikes[0]
    assert s.severity is Severity.TREMOR
    assert s.prevention == "custom ward"
    assert s.location == "Nowhere"


def test_report_is_deterministic():
    r1 = build_report(fetch_all(offline=True), report_date=date(2026, 11, 14))
    r2 = build_report(fetch_all(offline=True), report_date=date(2026, 11, 14))
    assert [s.to_json() for s in r1.strikes] == [s.to_json() for s in r2.strikes]


def test_stats_sum_matches_total():
    report = run(offline=True)
    stats = report.stats()
    assert sum(stats["by_severity"].values()) == stats["total"] == len(report.strikes)
