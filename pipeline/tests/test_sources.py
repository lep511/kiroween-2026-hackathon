"""Source tests: concrete article links, per-feed limits, and the non-incident filter."""

from __future__ import annotations

import json
from datetime import date

import pytest

from pipeline import sources
from pipeline.sources import (
    CURATED,
    FEEDS,
    PER_FEED_LIMIT,
    RawArticle,
    fetch_all,
    is_concrete_url,
    is_reportable_incident,
    load_curated,
    non_incident_reason,
    parse_rss,
)

_KNOWN_WITNESSES = {"bbc", "wapo", "nyt", "thehackernews", "hackernoon", "other"}

_CURATED_ROWS = json.loads(CURATED.read_text(encoding="utf-8"))

# ---- Concrete article links ------------------------------------------------


def test_is_concrete_url_accepts_articles():
    for url in [
        "https://www.bbc.com/news/articles/crq5nzxv9q4yo",
        "https://www.washingtonpost.com/technology/2026/11/13/colonial-ransomware-explainer/",
        "https://www.nytimes.com/2020/12/13/us/politics/russian-hackers-us-government.html",
        "https://thehackernews.com/2026/11/fbi-says-north-korean-hackers-stole.html",
        "https://hackernoon.com/how-fake-job-interviews-helped-hackers-pull-off-a-heist",
    ]:
        assert is_concrete_url(url), url


def test_is_concrete_url_rejects_generic():
    for url in [
        "https://thehackernews.com/",
        "https://www.washingtonpost.com/business/tech",
        "https://www.nytimes.com/section/technology",
        "https://www.washingtonpost.com/technology/",
        "https://hackernoon.com/tagged/cybersecurity",
        "https://www.bbc.com/news/technology",
        "not-a-url",
        "",
    ]:
        assert not is_concrete_url(url), url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bbc.co.uk/sounds/play/w3ct8jys",
        "https://www.nytimes.com/2026/11/13/podcasts/the-daily/ransomware-hospital.html",
        "https://example.com/podcast/episode-42-ransomware",
        "https://www.bbc.com/news/videos/c0k4ld9m2e1o",
        "https://www.washingtonpost.com/video/tech/hackers-breach-bank/2026/11/13/abc-123/",
        "https://www.bbc.com/news/live/c9wpm2xk5e3t",
        "https://example.com/audio/2026/11/breach-briefing",
        "https://example.com/newsletter/2026-11-13-weekly-breach",
        "https://example.com/newsletters/2026/11/ransomware-digest",
        "https://thehackernews.com/webinar/identity-blind-spots-2026",
        "https://example.com/webinars/2026/close-soc-gaps",
    ],
)
def test_is_concrete_url_rejects_non_article_segments_anywhere(url):
    assert not is_concrete_url(url)


@pytest.mark.parametrize("row", _CURATED_ROWS, ids=lambda r: r["url"])
def test_every_curated_url_is_accepted(row):
    """Regression guard: the stricter segment rules must not reject a curated link."""
    assert is_concrete_url(row["url"])


def test_every_curated_incident_has_a_concrete_link():
    """The whole point: no generic/section links ever ship in a snapshot."""
    articles = fetch_all(offline=True)
    assert articles
    for a in articles:
        assert a.witness in _KNOWN_WITNESSES
        assert is_concrete_url(a.url), f"{a.witness}: {a.url!r} is not a concrete article"


# ---- RSS parsing -----------------------------------------------------------


def test_parse_rss_skips_section_links():
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Massive ransomware attack reported</title>
            <description>Systems down.</description>
            <link>https://news.example.com/technology</link></item>
    </channel></rss>"""
    assert parse_rss("nyt", xml) == []


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
    assert out[0].curated is False


def test_parse_rss_regex_fallback_on_malformed_xml():
    # <content:encoded> uses an undeclared namespace prefix -> strict XML parse fails;
    # the lenient regex fallback must still recover the concrete cyber item.
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item>
        <title>Bank hit by a major data breach</title>
        <description>Millions of records stolen.</description>
        <link>https://news.example.com/2026/11/bank-data-breach</link>
        <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate>
        <content:encoded>undeclared prefix explodes strict parsers</content:encoded>
      </item>
    </channel></rss>"""
    out = parse_rss("hackernoon", xml)
    assert len(out) == 1
    assert out[0].url == "https://news.example.com/2026/11/bank-data-breach"


# ---- Per-feed limit --------------------------------------------------------


def _synthetic_feed(n: int) -> bytes:
    items = "".join(f"""<item><title>Hackers breach retailer number {i} in ransomware attack</title>
              <description>Customer records were stolen.</description>
              <link>https://news.example.com/2026/11/retailer-{i}-ransomware-breach</link>
              <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>""" for i in range(n))
    return f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'.encode()


def _count_by_witness(articles: list[RawArticle]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for a in articles:
        counts[a.witness] = counts.get(a.witness, 0) + 1
    return counts


@pytest.fixture
def forty_item_feeds(monkeypatch):
    calls: list[str] = []

    def fake_http_bytes(url: str) -> bytes:
        calls.append(url)
        return _synthetic_feed(40)

    monkeypatch.setattr(sources, "_http_bytes", fake_http_bytes)
    return calls


def test_per_feed_limit_defaults_to_25(forty_item_feeds):
    assert PER_FEED_LIMIT == 25
    articles = fetch_all(offline=False)
    assert len(forty_item_feeds) == len(FEEDS)
    assert _count_by_witness(articles) == {w: 25 for w, _ in FEEDS}


def test_per_feed_limit_is_configurable(forty_item_feeds):
    articles = fetch_all(offline=False, per_feed_limit=7)
    assert _count_by_witness(articles) == {w: 7 for w, _ in FEEDS}


def test_global_limit_still_caps_the_total(forty_item_feeds):
    assert len(fetch_all(offline=False, limit=12, per_feed_limit=10)) == 12


# ---- Non-incident filter ---------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Tech Life",
        "The HackerNoon Newsletter: Is AI Coming for Your Job? (11/13/2026)",
        "The HackerNoon Newsletter: The Ransomware Gangs Rewriting the Rules (11/12/2026)",
        "The HackerNoon Newsletter: How Hackers Breach Your Cloud (11/11/2026)",
        "Webinar: See How Identity Blind Spots Put Your SOC at Risk and How to Close Them",
        "Microsoft Says Outage Disrupting Outlook Is Improving",
        "What Is Web Cache Deception and How Can Attackers Exploit It?",
        "How Visual Programming Could Solve Three Major AI Cybersecurity Problems",
    ],
)
def test_non_incidents_are_rejected(title):
    assert not is_reportable_incident(title, "")


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("Kiroween hackathon winners announced", "Developers attack the leaderboard at HackerNoon"),
        ("Top 10 cybersecurity startups to watch", "Startups that promise to stop breaches."),
        ("How Hackers Steal Your Passwords", "Hackers steal passwords in many ways."),
        ("HackerNoon launches a new writing contest", "Writers attack the prompt."),
    ],
)
def test_substrings_and_explainers_are_not_incidents(title, summary):
    # Word-boundary matching: "hackathon" / "HackerNoon" are not "hack"; second-person
    # how-tos and listicles are explainers, not reported incidents.
    assert not is_reportable_incident(title, summary)


@pytest.mark.parametrize(
    "title",
    [
        "Operation Endgame Takes Down Gootloader, CastleRAT and StealC Servers, "
        "Seizes 6.4M Stolen Logins",
        "SilentAir Hijacks Asian Telecom Networks to Intercept SMS 2FA Codes and Spy on "
        "Taiwanese Users",
        "SilentAir Malware Hijacks Telecom Core Networks to Steal SMS One-Time Codes",
    ],
)
def test_real_incident_headlines_are_accepted(title):
    assert is_reportable_incident(title, "")


@pytest.mark.parametrize("row", _CURATED_ROWS, ids=lambda r: r["title"][:40])
def test_every_curated_title_reads_as_an_incident(row):
    assert is_reportable_incident(row["title"], row.get("summary", ""))


def test_rss_drops_non_incident_items():
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>The HackerNoon Newsletter: Hackers Breach Your Cloud (11/11/2026)</title>
            <description>Ransomware, breaches and more.</description>
            <link>https://hackernoon.com/the-hackernoon-newsletter-11-11-2026</link></item>
    </channel></rss>"""
    assert parse_rss("hackernoon", xml) == []


def _one_item_feed(title: str, summary: str) -> bytes:
    return f"""<?xml version="1.0"?><rss><channel>
      <item><title>{title}</title><description>{summary}</description>
            <link>https://news.example.com/2026/11/some-story-123</link></item>
    </channel></rss>""".encode()


@pytest.mark.parametrize(
    ("title", "summary", "reason"),
    [
        (
            "Top ransomware gangs to watch",
            "Gangs that breached hospitals.",
            r"non-incident title pattern: \bto watch\b",
        ),
        (
            "Airline outage grounds flights",
            "The carrier ruled out a cyberattack after systems were compromised.",
            "reporting rules out an attack",
        ),
        ("New smartphone announced", "A shiny gadget.", "no cyber keyword"),
        (
            "Cybersecurity budgets grow in 2026",
            "Spending on cyber defense is rising.",
            "no incident signal",
        ),
    ],
)
def test_filtered_rss_item_is_logged_with_its_reason(capsys, title, summary, reason):
    assert non_incident_reason(title, summary) == reason
    assert not is_reportable_incident(title, summary)
    assert parse_rss("bbc", _one_item_feed(title, summary)) == []
    assert capsys.readouterr().out.strip() == f"[sources] filtered (bbc): {title} ({reason})"


def test_accepted_rss_item_logs_no_filter_line(capsys):
    title = "Hackers breach a bank in a huge cyber attack"
    assert non_incident_reason(title, "Millions of records stolen.") is None
    assert len(parse_rss("bbc", _one_item_feed(title, "Millions of records stolen."))) == 1
    assert "[sources] filtered" not in capsys.readouterr().out


def test_section_links_are_not_logged_as_filtered(capsys):
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Top ransomware gangs to watch</title>
            <link>https://news.example.com/technology</link></item>
    </channel></rss>"""
    assert parse_rss("nyt", xml) == []
    assert capsys.readouterr().out == ""


def test_load_curated_does_not_apply_the_incident_filter(monkeypatch):
    monkeypatch.setattr(sources, "is_reportable_incident", lambda *_: False)
    rows = load_curated()
    assert len(rows) == len(_CURATED_ROWS) == 7
    assert all(r.curated for r in rows)


# ---- RawArticle serialization ----------------------------------------------


def test_raw_article_json_round_trip():
    article = RawArticle(
        witness="thehackernews",
        title="Hackers breach a bank",
        summary="Records stolen.",
        url="https://thehackernews.com/2026/11/hackers-breach-bank.html",
        published=date(2026, 11, 13),
        country="US",
        overrides={"severity": "siege"},
        curated=True,
    )
    payload = json.loads(json.dumps(article.to_json()))
    assert RawArticle.from_json(payload) == article
