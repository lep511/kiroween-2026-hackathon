"""News-source ingestion: recognized outlets -> normalized RawArticle rows.

Recognized witnesses (RSS, free, no key):
  * BBC News            — technology feed
  * The Washington Post — technology feed
  * The New York Times  — technology feed
  * The Hacker News     — security feed (the richest for pure cyber incidents)
  * HackerNoon          — cybersecurity tag feed (community tech reporting)

Only items that read like one concrete reported incident (``is_reportable_incident``: no
newsletters, webinars, explainers, opinion, or outages) AND whose link points at a
**concrete article** (never a section/landing page or audio/video page) are kept. All feeds degrade
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

# ``hack`` as a whole word (hack, hacks, hacked, hacker(s), hacking); never "hackathon"
# or "HackerNoon".
_HACK = r"\bhack(?:s|ed|ers?|ing)?\b"

# A story only becomes a Machine Strike if it reads like a cyber incident. Every term is
# matched on word boundaries (a trailing open stem such as ``compromis`` covers its
# inflections) so substrings inside unrelated words never count.
_CYBER_KEYWORDS: re.Pattern[str] = re.compile(
    "|".join(
        (
            r"\bcyber",
            _HACK,
            r"\bbreach",
            r"\bransomware\b",
            r"\bmalware\b",
            r"\bphishing\b",
            r"\bddos\b",
            r"\bexploit",
            r"\bvulnerabilit",
            r"\bdata leaks?\b",
            r"\bstolen\b",
            r"\bspyware\b",
            r"\bbackdoor",
            r"\bzero[- ]day\b",
            r"\bcredentials?\b",
            r"\bbotnets?\b",
            r"\bscam",
            r"\bintrusions?\b",
            r"\bdeepfakes?\b",
            r"\bcompromis",
            r"\bespionage\b",
            r"\battack(?:s|ed|ers?)?\b",
            r"\bheists?\b",
            r"\bhijack",
            r"\bimplants?\b",
            r"\bexfiltrat",
        )
    ),
    re.IGNORECASE,
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

# Path segments that mark a non-article medium (audio, video, live blogs, newsletters,
# webinars) wherever they appear in the path, e.g. ``/sounds/play/w3ct8jys``.
_NON_ARTICLE_SEGMENTS = frozenset(
    {
        "sounds",
        "podcast",
        "podcasts",
        "video",
        "videos",
        "live",
        "audio",
        "newsletter",
        "newsletters",
        "webinar",
        "webinars",
    }
)

# Default cap on items kept per feed (``fetch_all``); override with ``--per-feed-limit``
# (CLI) or ``PER_FEED_LIMIT`` (Lambda).
PER_FEED_LIMIT = 25

# Titles that are never a single reported incident: newsletters, roundups, webinars,
# podcasts, explainers, how-tos, opinion, and benchmarks.
_NON_INCIDENT_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^the hackernoon newsletter",
        r"\bnewsletter\b",
        r"^webinar\b|\bwebinar:",
        r"\bpodcast\b",
        r"^threatsday\b",
        r"\bweekly recap\b",
        r"^(what|how|why) (is|are|to|could|can|do)\b",
        r"^(what|how|why)\b.*\byou(?:r)?\b",  # second-person explainers
        r"^top \d+\b",
        r"\bto watch\b",
        r"\bexplained\b",
        r"\bopinion\b",
        r"\bguide to\b",
        r"\bbenchmark\b",
    )
)

# Reporting that explicitly rules a cyberattack out (e.g. an outage) is not a strike.
_NEGATED_INCIDENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brul(?:e|ed|es|ing) out (?:a |any )?cyber",
        r"\bnot (?:a |the result of a )?cyber-?attack\b",
        r"\bno (?:sign|evidence) of (?:a )?cyber",
    )
)

# Concrete evidence that something was actually attacked, breached, or taken down
# (word-boundary matched, like ``_CYBER_KEYWORDS``).
_INCIDENT_SIGNALS: re.Pattern[str] = re.compile(
    "|".join(
        (
            r"\bbreach",
            r"\bransomware\b",
            _HACK,
            r"\bhijack",
            r"\bstolen\b",
            r"\bstole\b",
            r"\bsteal(?:s|ing)?\b",
            r"\bthefts?\b",
            r"\bheists?\b",
            r"\bleak(?:s|ed)?\b",
            r"\bcompromis",
            r"\bexfiltrat",
            r"\bddos\b",
            r"\bmalware\b",
            r"\btrojans?\b",
            r"\bspyware\b",
            r"\bbackdoor",
            r"\bimplants?\b",
            r"\bwipers?\b",
            r"\bbotnets?\b",
            r"\bzero[- ]day\b",
            r"\bexploited\b",
            r"\bextort",
            r"\bespionage\b",
            r"\bsabotag",
            r"\bintrusions?\b",
            r"\bcyber[- ]?attacks?\b",
            r"\btakedowns?\b",
            r"\btakes? down\b",
            r"\bseiz",
            r"\barrested\b",
            r"\bdismantled\b",
        )
    ),
    re.IGNORECASE,
)


def is_concrete_url(url: str) -> bool:
    """True only for a link that points at a specific article, not a section page.

    An article's final path segment is "slug-like": it contains a hyphen, a dot, or a
    digit (e.g. ``colonial-ransomware-attack-explainer`` or ``...stole.html``). Bare
    domains and section pages (``/technology``, ``/tagged/cybersecurity``) are rejected,
    and so is any path containing a non-article medium segment (``/sounds/...``,
    ``/video/...``, ``/podcasts/...``) anywhere along it.
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
    if any(s.lower() in _NON_ARTICLE_SEGMENTS for s in segments):
        return False
    last = segments[-1].lower()
    if last in _SECTION_SEGMENTS:
        return False
    return ("-" in last) or ("." in last) or any(c.isdigit() for c in last)


@dataclass(slots=True)
class RawArticle:
    """A normalized article row before extraction/skinning.

    ``curated`` marks a committed, hand-verified incident (``load_curated``): its
    ``country``, ``summary``, and ``overrides`` count as verified reporting and win over
    the agent. A live RSS item is never curated.
    """

    witness: str
    title: str
    summary: str
    url: str
    published: date
    country: str | None = None
    overrides: dict = field(default_factory=dict)
    curated: bool = False

    def to_json(self) -> dict:
        """JSON-safe form (used to stage articles between Step Functions states)."""
        return {
            "witness": self.witness,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published": self.published.isoformat(),
            "country": self.country,
            "overrides": dict(self.overrides),
            "curated": self.curated,
        }

    @classmethod
    def from_json(cls, d: dict) -> RawArticle:
        return cls(
            witness=str(d["witness"]),
            title=str(d["title"]),
            summary=str(d.get("summary", "")),
            url=str(d["url"]),
            published=date.fromisoformat(str(d["published"])),
            country=d.get("country"),
            overrides=dict(d.get("overrides") or {}),
            curated=bool(d.get("curated", False)),
        )


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
    return _CYBER_KEYWORDS.search(f"{title} {summary}") is not None


def non_incident_reason(title: str, summary: str) -> str | None:
    """Why a live feed item is not one concrete, reported cyber incident (None if it is).

    Checks, in order: a title matching the non-incident deny-list, reporting that rules an
    attack out, the lack of any cyber keyword, and the lack of a concrete incident signal.
    Every term is matched on word boundaries (so "hackathon" or "HackerNoon" never count
    as a hack).
    """
    for pattern in _NON_INCIDENT_TITLE_PATTERNS:
        if pattern.search(title):
            return f"non-incident title pattern: {pattern.pattern}"
    blob = f"{title} {summary}"
    if any(p.search(blob) for p in _NEGATED_INCIDENT_PATTERNS):
        return "reporting rules out an attack"
    if not _looks_like_cyber(title, summary):
        return "no cyber keyword"
    if _INCIDENT_SIGNALS.search(blob) is None:
        return "no incident signal"
    return None


def is_reportable_incident(title: str, summary: str) -> bool:
    """True if a live feed item reads like one concrete, reported cyber incident.

    Deterministic gate applied before any agent call, so no Bedrock tokens are spent on
    newsletters, webinars, explainers, opinion, or outages. See ``non_incident_reason``
    for the rules and the reason reported for each rejection.
    """
    return non_incident_reason(title, summary) is None


def _http_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted feeds)
        return resp.read()


def _tag(elem: ET.Element) -> str:
    """Local tag name without XML namespace."""
    return elem.tag.rsplit("}", 1)[-1]


def _emit(witness: str, title: str, summary: str, link: str, when: str | None) -> RawArticle | None:
    """Build a RawArticle if it is a concrete cyber-incident link, else None.

    An article link dropped by the deterministic incident filter is logged with its
    witness, title, and reason so the filter can be audited from the run logs.
    """
    title = _clean(title)
    summary = _clean(summary)
    link = (link or "").strip()
    if not title or not is_concrete_url(link):
        return None
    reason = non_incident_reason(title, summary)
    if reason is not None:
        print(f"[sources] filtered ({witness}): {title} ({reason})")
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


def parse_rss(witness: str, data: bytes, limit: int = PER_FEED_LIMIT) -> list[RawArticle]:
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
                    curated=True,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            print(f"[sources] skipped a curated row: {exc}")
    return out


def fetch_all(
    offline: bool = False,
    limit: int | None = None,
    per_feed_limit: int = PER_FEED_LIMIT,
) -> list[RawArticle]:
    """Fetch and normalize every source. Never raises on a single feed failure.

    ``per_feed_limit`` caps the items kept from each live feed; ``limit`` caps the
    combined total (both live and offline).
    """
    if offline:
        articles = load_curated()
    else:
        articles = []
        for witness, url in FEEDS:
            try:
                articles += parse_rss(witness, _http_bytes(url), limit=per_feed_limit)
            except Exception as exc:  # noqa: BLE001 — degrade gracefully per feed
                print(f"[sources] {witness} fetch failed: {exc}")

    if limit is not None:
        articles = articles[:limit]
    return articles
