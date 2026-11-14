"""Deterministic heuristic extractor: article text -> structured Machine Strike.

Given a reported cyberattack (headline + summary) this derives the fields the project
cares about — **attack type, data affected, impact, severity, prevention, and attributed
origin** — using keyword signatures and a mitigation playbook. It is fully deterministic
(no network, no model), so the offline snapshot is reproducible and the tests are stable.

Curated incidents may pin any field via ``overrides`` (see ``sources.RawArticle``); those
always win over the heuristic, so verified reporting is never overwritten by a guess. The
heuristic is what lets the *live* RSS path still produce a usable strike on its own.
"""

from __future__ import annotations

import re

from .geolocate import Geolocator, country_display, resolve_country
from .models import Severity, Strike, Witness

# ---------------------------------------------------------------------------
# Attack type -> standard, educational mitigation ("the ward"). Order matters:
# the first signature whose any-keyword matches wins.
# ---------------------------------------------------------------------------
_ATTACK_SIGNATURES: list[tuple[str, tuple[str, ...], str]] = [
    (
        "ransomware",
        ("ransomware", "ransom", "encrypted their", "locked their systems"),
        "Keep offline, tested backups; patch internet-facing systems; enforce MFA and "
        "segment networks to stop lateral movement.",
    ),
    (
        "supply-chain",
        (
            "supply chain",
            "supply-chain",
            "third-party",
            "vendor",
            "dependency",
            "npm package",
            "implant",
        ),
        "Vet and pin third-party code; verify signatures/SBOMs; isolate build systems; "
        "tightly scope vendor access.",
    ),
    (
        "credential-theft",
        (
            "2fa",
            "mfa code",
            "sms code",
            "stolen logins",
            "credential",
            "password",
            "intercept sms",
            "session token",
        ),
        "Adopt phishing-resistant (FIDO2) MFA instead of SMS; watch for impossible-travel "
        "logins; rotate exposed secrets immediately.",
    ),
    (
        "phishing",
        ("phishing", "spear-phishing", "fake email", "lure", "business email compromise"),
        "Train staff to spot lures; enforce phishing-resistant MFA; filter inbound mail and "
        "sandbox attachments.",
    ),
    (
        "deepfake-social-engineering",
        ("deepfake", "deep fake", "impersonat", "video call", "voice clone", "social engineering"),
        "Verify high-value requests out-of-band; train staff on deepfake voice/video; require "
        "dual authorization for transfers.",
    ),
    (
        "crypto-theft",
        ("crypto", "cryptocurrency", "bitcoin", "wallet", "recovery phrase", "exchange hack"),
        "Use hardware wallets from trusted sources; verify firmware; segregate signing keys; "
        "treat unsolicited 'support' contact as hostile.",
    ),
    (
        "ddos",
        (
            "ddos",
            "denial of service",
            "knocked offline",
            "flood of traffic",
            "overwhelmed with traffic",
        ),
        "Front services with a scrubbing CDN/WAF; rate-limit; provision burst capacity and a "
        "rehearsed incident runbook.",
    ),
    (
        "vulnerability-exploit",
        (
            "zero-day",
            "zero day",
            "exploit",
            "flaw",
            "vulnerabilit",
            "rce",
            "backdoor",
            "patch",
            "cve-",
        ),
        "Patch fast on disclosure; apply virtual patching/WAF rules; segment and monitor the "
        "affected systems for exploitation.",
    ),
    (
        "operational-technology",
        (
            "refriger",
            "industrial",
            "scada",
            "ics",
            "control system",
            "iot",
            "sensor",
            "power grid",
            "water",
        ),
        "Segment OT/IoT networks from corporate IT; disable default remote maintenance; monitor "
        "industrial controllers for anomalies.",
    ),
    (
        "espionage",
        ("spy", "espionage", "surveillance", "apt", "state-sponsored", "nation-state"),
        "Assume-breach monitoring; segment crown-jewel systems; hunt for living-off-the-land "
        "activity; keep edge devices patched.",
    ),
    (
        "data-breach",
        (
            "breach",
            "data leak",
            "exposed",
            "stolen data",
            "database",
            "hacked",
            "cyber attack",
            "cyberattack",
        ),
        "Encrypt data at rest; apply least-privilege access; monitor for abnormal exfiltration; "
        "patch exposed services.",
    ),
]

_DEFAULT_PREVENTION = (
    "Patch promptly, enforce phishing-resistant MFA, segment networks, and keep offline, "
    "tested backups."
)

# Data/asset signatures -> label fragment.
_DATA_SIGNATURES: list[tuple[tuple[str, ...], str]] = [
    (("health", "medical", "patient", "hospital"), "health/medical records"),
    (("payment", "card", "bank", "financial"), "payment & financial data"),
    (("crypto", "wallet", "bitcoin", "recovery phrase"), "cryptocurrency / wallet keys"),
    (
        ("password", "credential", "login", "logins", "2fa", "session token"),
        "credentials & login secrets",
    ),
    (("government", "classified", "military", "defence", "defense"), "government/classified data"),
    (
        ("source code", "intellectual property", "trade secret"),
        "source code / intellectual property",
    ),
    (("personal", "customer", "identity", "records", "pii"), "personal/customer records"),
    (("email", "messages", "sms", "communications"), "communications & messages"),
]

# Sector signatures -> label (for the impact line).
_SECTOR_SIGNATURES: list[tuple[tuple[str, ...], str]] = [
    (("hospital", "health", "patient", "medical"), "healthcare"),
    (("bank", "financial", "payment", "card"), "financial services"),
    (("government", "public sector", "ministry", "agency"), "government"),
    (("supermarket", "retail", "store", "shop"), "retail"),
    (("telecom", "network operator", "sms", "mobile"), "telecommunications"),
    (("power", "energy", "grid", "water", "utility"), "critical infrastructure"),
    (("school", "university", "education", "student"), "education"),
    (("crypto", "exchange", "wallet"), "cryptocurrency users"),
]

# Attacker attribution -> origin ISO code.
_ACTOR_ORIGINS: list[tuple[tuple[str, ...], str]] = [
    (("north korea", "north korean", "lazarus", "kimsuky"), "KP"),
    (("russia", "russian", "sandworm", "fancy bear", "fsb"), "RU"),
    (("china", "chinese", "volt typhoon", "salt typhoon"), "CN"),
    (("iran", "iranian"), "IR"),
]

# Severity escalators (any match bumps toward Dominion).
_APEX_KEYWORDS = (
    "millions",
    "billions",
    "hundreds of",
    "thousands of",
    "national",
    "critical",
    "hospital",
    "power grid",
    "government",
    "ransom",
    "shut down",
    "crippled",
)
_HIGH_KEYWORDS = ("breach", "stolen", "hacked", "compromis", "seized", "backdoor", "infect")
_LOW_KEYWORDS = ("warns", "patch", "advisory", "flaw", "vulnerabilit", "could", "potential")


def _text(article) -> str:
    return f"{article.title}. {article.summary}".lower()


def classify_attack(text: str) -> tuple[str, str]:
    """Return (attack_type, prevention) from the article text."""
    for attack_type, keywords, prevention in _ATTACK_SIGNATURES:
        if any(k in text for k in keywords):
            return attack_type, prevention
    return "unknown", _DEFAULT_PREVENTION


def detect_data(text: str) -> str:
    hits = [label for keys, label in _DATA_SIGNATURES if any(k in text for k in keys)]
    if not hits:
        return "Systems and data at the targeted organisation (specifics not disclosed)."
    # De-duplicate preserving order.
    seen: list[str] = []
    for h in hits:
        if h not in seen:
            seen.append(h)
    return "; ".join(seen[:3]).capitalize()


def detect_sectors(text: str) -> list[str]:
    hits: list[str] = []
    for keys, label in _SECTOR_SIGNATURES:
        if any(k in text for k in keys) and label not in hits:
            hits.append(label)
    return hits


def _scale_phrase(text: str) -> str:
    m = re.search(r"(hundreds|thousands|millions|billions|tens of thousands)\s+of\s+([a-z]+)", text)
    if m:
        return f"{m.group(1)} of {m.group(2)}"
    m = re.search(r"([\d.,]+)\s*(million|billion|thousand)\b", text)
    if m:
        return f"{m.group(1)} {m.group(2)} affected"
    return ""


def synth_impact(article, text: str) -> str:
    sectors = detect_sectors(text)
    scale = _scale_phrase(text)
    parts: list[str] = []
    if sectors:
        parts.append("Hit " + ", ".join(sectors[:3]))
    if scale:
        parts.append(scale)
    if parts:
        return "; ".join(parts).capitalize() + "."
    first_sentence = re.split(r"(?<=[.!?])\s", article.summary.strip(), maxsplit=1)[0]
    return first_sentence or "Impact under assessment."


def classify_severity(text: str) -> Severity:
    if any(k in text for k in _APEX_KEYWORDS):
        return Severity.DOMINION
    if any(k in text for k in _HIGH_KEYWORDS):
        return Severity.SIEGE
    if any(k in text for k in _LOW_KEYWORDS):
        return Severity.BREACH
    return Severity.TREMOR


def attribute_origin(text: str) -> str | None:
    for keywords, cc in _ACTOR_ORIGINS:
        if any(k in text for k in keywords):
            return cc
    return None


def build_strike(article, idx: int, geo: Geolocator) -> Strike:
    """Turn one RawArticle into a fully-populated Strike (overrides win over heuristics)."""
    ov = article.overrides or {}
    text = _text(article)

    attack_type = ov.get("attack_type") or classify_attack(text)[0]
    prevention = ov.get("prevention") or classify_attack(text)[1]

    country = (ov.get("country") or article.country or resolve_country(text) or "ZZ").upper()
    severity = Severity.from_label(ov["severity"]) if "severity" in ov else classify_severity(text)
    data_affected = ov.get("data_affected") or detect_data(text)
    impact = ov.get("impact") or synth_impact(article, text)
    location = ov.get("location") or country_display(country)
    summary = ov.get("summary") or (article.summary.strip() or article.title)

    seed = f"{idx}:{article.title}"
    lat, lon = geo.locate(country, seed=seed)

    origin_cc = ov.get("origin_country") or attribute_origin(text)
    if origin_cc:
        origin_lat, origin_lon = geo.locate(origin_cc, seed=f"origin:{seed}")
    else:
        origin_lat, origin_lon = lat, lon  # unknown attribution -> arc collapses

    return Strike(
        id=idx,
        lat=lat,
        lon=lon,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        severity=severity,
        witness=Witness.from_label(article.witness),
        country=country,
        published=article.published,
        title=article.title,
        location=location,
        data_affected=data_affected,
        impact=impact,
        prevention=prevention,
        summary=summary,
        url=article.url,
        attack_type=attack_type,
    )
