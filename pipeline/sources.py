"""News-source ingestion: recognized outlets -> normalized RawArticle rows.

Recognized witnesses (RSS, free, no key):
  * BBC News            — technology feed
  * The Washington Post — technology feed
  * The New York Times  — technology feed
  * CNN                 — technology feed
  * The Hacker News     — security feed (the richest for pure cyber incidents)
  * HackerNoon          — cybersecurity tag feed (community tech reporting)

Only items whose title/summary look like a cyberattack/breach are kept. All feeds
degrade gracefully: a failed fetch yields an empty list and one bad row never aborts
the batch.

Offline mode reads a committed, hand-verified set of real incidents
(``fixtures/curated_incidents.json``) so the whole pipeline runs with no network and
produces a reproducible snapshot. Each curated row may pin fields via ``overrides``.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
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
    ("cnn", "http://rss.cnn.com/rss/edition_technology.rss"),
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
)


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


def parse_rss(witness: str, data: bytes, limit: int = 8) -> list[RawArticle]:
    """Parse RSS 2.0 or Atom bytes into cyber-incident RawArticles."""
    out: list[RawArticle] = []
    try:
        root = _xml_fromstring(data)  # noqa: S314 - defusedxml preferred; stdlib only as fallback
    except ET.ParseError:
        return out

    items = [e for e in root.iter() if _tag(e) in ("item", "entry")]
    for item in items:
        fields: dict[str, str] = {}
        link = ""
        for child in item:
            name = _tag(child)
            if name == "link":
                link = (child.get("href") or child.text or "").strip() or link
            elif name in ("title", "description", "summary", "pubDate", "published", "updated"):
                fields.setdefault(name, (child.text or "").strip())

        title = _clean(fields.get("title"))
        summary = _clean(fields.get("description") or fields.get("summary"))
        if not title or not _looks_like_cyber(title, summary):
            continue
        published = _parse_date(
            fields.get("pubDate") or fields.get("published") or fields.get("updated")
        )
        out.append(
            RawArticle(
                witness=witness,
                title=title,
                summary=summary,
                url=link,
                published=published,
            )
        )
        if len(out) >= limit:
            break
    return out


def load_curated() -> list[RawArticle]:
    """Load the committed, hand-verified real incidents (offline source of truth)."""
    rows = json.loads(CURATED.read_text(encoding="utf-8"))
    out: list[RawArticle] = []
    for row in rows:
        try:
            out.append(
                RawArticle(
                    witness=str(row["witness"]),
                    title=str(row["title"]),
                    summary=str(row.get("summary", "")),
                    url=str(row.get("url", "")),
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
