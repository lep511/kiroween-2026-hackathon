"""News-source ingestion: recognized outlets -> normalized RawArticle rows.

Recognized witnesses (RSS, free, no key):
  * BBC News            — technology feed
  * The Washington Post — technology feed
  * The New York Times  — technology feed
  * The Hacker News     — security feed (the richest for pure cyber incidents)
  * HackerNoon          — cybersecurity tag feed (community tech reporting)

Only items whose title/summary look like a cyberattack/breach AND whose link points at a
**concrete article** (never a section/landing page) are kept. All feeds degrade
gracefully: a failed fetch yields an empty list and one bad row never aborts the batch.
Feeds with slightly malformed XML (e.g. undeclared namespace prefixes) fall back to a
lenient regex parse instead of being dropped.

Offline mode reads a committed, hand-verified set of real incidents
(``fixtures/curated_incidents.json``) so the whole pipeline runs with no network and
produces a reproducible snapshot. Each curated row carries a concrete article URL and may
pin fields via ``overrides``.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

try:  # defusedxml hardens parsing of untrusted RSS against XML-bomb attacks.
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - fallback when defusedxml is absent
    from xml.etree.ElementTree import fromstring as _xml_fromstring  # noqa: S314

_USER_AGENT = "RebellionOfTheMachines/2.0 (+kiroween-2026)"
_TIMEOUT = 20

FIXTURES = Path(__file__).parent / "fixtures"
CURATED = FIXTURES / "curated_incidents.json"

# (witness_label, rss_url)
FEEDS: list[tuple[str, str]] = [
    ("bbc", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("thehackernews", "https://feeds.feedburner.com/TheHackersNews"),
    ("nyt", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
    ("wapo", "https://feeds.washingtonpost.com/rss/business/technology"),
    ("hackernoon", "https://hackernoon.com/tagged/cybersecurity/feed"),
]

# A story only becomes a Machine Strike if it reads like a cyber incident.
_CYBER_KEYWORDS = (
    "cyber",
    "hack",
    "hacker",
    "breach",
    "ransomware",
    "malware",
    "phishing",
    "ddos",
    "exploit",
    "vulnerabilit",
    "data leak",
    "stolen",
    "spyware",
    "backdoor",
    "zero-day",
    "zero day",
    "credential",
    "botnet",
    "scam",
    "intrusion",
    "deepfake",
    "compromis",
    "espionage",
    "attack",
    "heist",
)

# Path segments that are sections/landing pages, never a concrete article.
_SECTION_SEGMENTS = {
    "",
    "news",
    "technology",
    "tech",
    "business",
    "cybersecurity",
    "security",
    "section",
    "tag",
    "tagged",
    "topics",
    "topic",
    "world",
    "politics",
    "feed",
    "rss",
    "latest",
    "category",
    "author",
    "sounds",
    "live",
    "video",
}


def is_concrete_url(url: str) -> bool:
    """True only for a link that points at a specific article, not a section page.

    An article's final path segment is "slug-like": it contains a hyphen, a dot, or a
    digit (e.g. ``colonial-ransomware-attack-explainer`` or ``...stole.html``). Bare
    domains and section pages (``/technology``, ``/tagged/cybersecurity``) are rejected.
    """
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    segments = [s for s in p.path.split("/") if s]
    if not segments:
        return False
    last = segments[-1].lower()
    if last in _SECTION_SEGMENTS:
        return False
    return ("-" in last) or ("." in last) or any(c.isdigit() for c in last)


@dataclass(slots=True)
class RawArticle:
    """A normalized article row before extraction/skinning."""

    witness: str
    title: str
    summary: str
    url: str
    published: date
    country: str | None = None
    overrides: dict = field(default_factory=dict)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = unescape(text)
    # Strip any leftover HTML tags from descriptions.
    out, depth = [], 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return " ".join("".join(out).split())


def _parse_date(value: str | None) -> date:
    if value:
        try:
            dt = parsedate_to_datetime(value)
            if dt is not None:
                return dt.date()
        except (TypeError, ValueError):
            pass
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    return datetime.now(UTC).date()


def _looks_like_cyber(title: str, summary: str) -> bool:
    blob = f"{title} {summary}".lower()
    return any(k in blob for k in _CYBER_KEYWORDS)


def _http_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted feeds)
        return resp.read()


def _tag(elem: ET.Element) -> str:
    """Local tag name without XML namespace."""
    return elem.tag.rsplit("}", 1)[-1]


def _emit(witness: str, title: str, summary: str, link: str, when: str | None) -> RawArticle | None:
    """Build a RawArticle if it is a concrete cyber-incident link, else None."""
    title = _clean(title)
    summary = _clean(summary)
    link = (link or "").strip()
    if not title or not is_concrete_url(link) or not _looks_like_cyber(title, summary):
        return None
    return RawArticle(
        witness=witness, title=title, summary=summary, url=link, published=_parse_date(when)
    )


def _parse_rss_xml(witness: str, data: bytes, limit: int) -> list[RawArticle]:
    root = _xml_fromstring(data)  # noqa: S314 - defusedxml preferred; stdlib only as fallback
    out: list[RawArticle] = []
    for item in (e for e in root.iter() if _tag(e) in ("item", "entry")):
        fields: dict[str, str] = {}
        link = ""
        for child in item:
            name = _tag(child)
            if name == "link":
                link = (child.get("href") or child.text or "").strip() or link
            elif name in ("title", "description", "summary", "pubDate", "published", "updated"):
                fields.setdefault(name, (child.text or "").strip())
        art = _emit(
            witness,
            fields.get("title", ""),
            fields.get("description") or fields.get("summary") or "",
            link,
            fields.get("pubDate") or fields.get("published") or fields.get("updated"),
        )
        if art:
            out.append(art)
        if len(out) >= limit:
            break
    return out


_ITEM_RE = re.compile(r"<(?:item|entry)\b.*?</(?:item|entry)>", re.DOTALL | re.IGNORECASE)


def _field_re(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    val = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.DOTALL)
    return val.strip()


def _parse_rss_regex(witness: str, data: bytes, limit: int) -> list[RawArticle]:
    """Lenient fallback for feeds whose XML is malformed (bad namespaces, etc.)."""
    text = data.decode("utf-8", "replace")
    out: list[RawArticle] = []
    for block in _ITEM_RE.findall(text):
        link = _field_re(block, "link")
        if not link:  # Atom-style <link href="...">
            m = re.search(r'<link\b[^>]*href="([^"]+)"', block, re.IGNORECASE)
            link = m.group(1) if m else ""
        art = _emit(
            witness,
            _field_re(block, "title"),
            _field_re(block, "description") or _field_re(block, "summary"),
            link,
            _field_re(block, "pubDate")
            or _field_re(block, "published")
            or _field_re(block, "updated"),
        )
        if art:
            out.append(art)
        if len(out) >= limit:
            break
    return out


def parse_rss(witness: str, data: bytes, limit: int = 8) -> list[RawArticle]:
    """Parse RSS 2.0 or Atom bytes into concrete cyber-incident RawArticles."""
    try:
        return _parse_rss_xml(witness, data, limit)
    except ET.ParseError:
        # Some feeds (e.g. HackerNoon) ship undeclared namespace prefixes that strict
        # parsers reject; fall back to a tolerant regex scan rather than dropping them.
        return _parse_rss_regex(witness, data, limit)


def load_curated() -> list[RawArticle]:
    """Load the committed, hand-verified real incidents (offline source of truth)."""
    rows = json.loads(CURATED.read_text(encoding="utf-8"))
    out: list[RawArticle] = []
    for row in rows:
        try:
            url = str(row.get("url", ""))
            if not is_concrete_url(url):
                raise ValueError(f"non-concrete URL: {url!r}")
            out.append(
                RawArticle(
                    witness=str(row["witness"]),
                    title=str(row["title"]),
                    summary=str(row.get("summary", "")),
                    url=url,
                    published=_parse_date(str(row.get("published", ""))),
                    country=row.get("country"),
                    overrides=dict(row.get("overrides", {})),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            print(f"[sources] skipped a curated row: {exc}")
    return out


def fetch_all(offline: bool = False, limit: int | None = None) -> list[RawArticle]:
    """Fetch and normalize every source. Never raises on a single feed failure."""
    if offline:
        articles = load_curated()
    else:
        articles = []
        for witness, url in FEEDS:
            try:
                articles += parse_rss(witness, _http_bytes(url))
            except Exception as exc:  # noqa: BLE001 — degrade gracefully per feed
                print(f"[sources] {witness} fetch failed: {exc}")

    if limit is not None:
        articles = articles[:limit]
    return articles
