"""Source-link integrity tests: links must always be the concrete article."""

from __future__ import annotations

from pipeline.sources import fetch_all, is_concrete_url, parse_rss

_KNOWN_WITNESSES = {"bbc", "wapo", "nyt", "thehackernews", "hackernoon", "other"}


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


def test_every_curated_incident_has_a_concrete_link():
    """The whole point: no generic/section links ever ship in a snapshot."""
    articles = fetch_all(offline=True)
    assert articles
    for a in articles:
        assert a.witness in _KNOWN_WITNESSES
        assert is_concrete_url(a.url), f"{a.witness}: {a.url!r} is not a concrete article"


def test_parse_rss_skips_section_links():
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Massive ransomware attack reported</title>
            <description>Systems down.</description>
            <link>https://news.example.com/technology</link></item>
    </channel></rss>"""
    assert parse_rss("nyt", xml) == []


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
