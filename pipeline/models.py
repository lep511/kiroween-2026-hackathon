"""Core domain model + the Halloween narrative skin.

A **Machine Strike** is one real cyberattack reported by a recognized news outlet
(the "witness"). Terminology follows .kiro/steering/narrative-tone.md:

  reported cyberattack / breach -> "Machine Strike"
  news outlet that reported it  -> "Witness"
  severity tiers                -> Tremor -> Breach -> Siege -> Dominion
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import IntEnum

UNIX_EPOCH = date(1970, 1, 1)

# Canonical attack taxonomy. The Strands agent must classify every incident into exactly
# one of these (enforced by its structured-output schema), and curated overrides use the
# same labels. There is no "unknown" bucket: an unclassifiable incident is discarded.
ATTACK_TYPES: tuple[str, ...] = (
    "ransomware",
    "supply-chain",
    "credential-theft",
    "phishing",
    "deepfake-social-engineering",
    "crypto-theft",
    "ddos",
    "vulnerability-exploit",
    "operational-technology",
    "espionage",
    "data-breach",
)


class Severity(IntEnum):
    """Threat tiers, low to high. Values are the on-wire binary encoding."""

    TREMOR = 0
    BREACH = 1
    SIEGE = 2
    DOMINION = 3

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_label(cls, label: str) -> Severity:
        return cls[label.upper()]


class Witness(IntEnum):
    """Which outlet reported the strike. Values are the on-wire binary encoding."""

    BBC = 0
    WAPO = 1
    NYT = 2
    THEHACKERNEWS = 3
    HACKERNOON = 4
    OTHER = 5
    BLEEPINGCOMPUTER = 6
    THERECORD = 7

    @property
    def label(self) -> str:
        return self.name.lower()

    @property
    def display(self) -> str:
        return _WITNESS_DISPLAY[self]

    @classmethod
    def from_label(cls, label: str) -> Witness:
        key = (label or "other").strip().upper().replace(" ", "")
        return cls.__members__.get(key, cls.OTHER)


_WITNESS_DISPLAY: dict[Witness, str] = {
    Witness.BBC: "BBC News",
    Witness.WAPO: "The Washington Post",
    Witness.NYT: "The New York Times",
    Witness.THEHACKERNEWS: "The Hacker News",
    Witness.HACKERNOON: "HackerNoon",
    Witness.OTHER: "Other outlet",
    Witness.BLEEPINGCOMPUTER: "BleepingComputer",
    Witness.THERECORD: "The Record",
}


def days_since_epoch(d: date) -> int:
    """Whole days between the Unix epoch and ``d`` (used in the binary snapshot)."""
    return (d - UNIX_EPOCH).days


def date_from_days(days: int) -> date:
    from datetime import timedelta

    return UNIX_EPOCH + timedelta(days=int(days))


@dataclass(slots=True)
class Strike:
    """A single Machine Strike (one reported cyberattack for this report).

    ``lat``/``lon`` mark **ground zero** (where the attack landed); ``origin_*`` is the
    attributed attacker origin (equal to ground zero when attribution is unknown). The
    binary snapshot stores only the numeric/positional fields plus ``id``; the rich text
    (``title`` … ``url``) lives in the JSON snapshot, joined back by ``id``.
    """

    id: int
    lat: float
    lon: float
    origin_lat: float
    origin_lon: float
    severity: Severity
    witness: Witness
    country: str  # ISO-3166 alpha-2, uppercase
    published: date
    # Rich dossier (JSON only).
    title: str = ""
    location: str = ""
    data_affected: str = ""
    impact: str = ""
    prevention: str = ""
    summary: str = ""
    url: str = ""
    attack_type: str = "unknown"

    def __post_init__(self) -> None:
        self.country = (self.country or "ZZ").upper()[:2].ljust(2, "Z")

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "lat": round(self.lat, 4),
            "lon": round(self.lon, 4),
            "origin_lat": round(self.origin_lat, 4),
            "origin_lon": round(self.origin_lon, 4),
            "severity": self.severity.label,
            "witness": self.witness.label,
            "country": self.country,
            "published": self.published.isoformat(),
            "title": self.title,
            "location": self.location,
            "data_affected": self.data_affected,
            "impact": self.impact,
            "prevention": self.prevention,
            "summary": self.summary,
            "url": self.url,
            "attack_type": self.attack_type,
        }

    @classmethod
    def from_json(cls, d: dict) -> Strike:
        return cls(
            id=int(d["id"]),
            lat=float(d["lat"]),
            lon=float(d["lon"]),
            origin_lat=float(d["origin_lat"]),
            origin_lon=float(d["origin_lon"]),
            severity=Severity.from_label(d["severity"]),
            witness=Witness.from_label(d["witness"]),
            country=d["country"],
            published=date.fromisoformat(d["published"]),
            title=d.get("title", ""),
            location=d.get("location", ""),
            data_affected=d.get("data_affected", ""),
            impact=d.get("impact", ""),
            prevention=d.get("prevention", ""),
            summary=d.get("summary", ""),
            url=d.get("url", ""),
            attack_type=d.get("attack_type", "unknown"),
        )


@dataclass(slots=True)
class InsurgencyReport:
    """A full weekly snapshot of the uprising: the Machine Strikes of a rolling 7-day window."""

    report_date: date
    strikes: list[Strike] = field(default_factory=list)
    generated_at: datetime | None = None
    version: int = 2

    def __post_init__(self) -> None:
        if self.generated_at is None:
            self.generated_at = datetime.now(UTC)

    def stats(self) -> dict:
        by_severity = {s.label: 0 for s in Severity}
        for s in self.strikes:
            by_severity[s.severity.label] += 1
        return {"total": len(self.strikes), "by_severity": by_severity}

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "date": self.report_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "stats": self.stats(),
            "strikes": [s.to_json() for s in self.strikes],
        }

    @classmethod
    def from_json(cls, d: dict) -> InsurgencyReport:
        return cls(
            report_date=date.fromisoformat(d["date"]),
            strikes=[Strike.from_json(s) for s in d["strikes"]],
            generated_at=datetime.fromisoformat(d["generated_at"]),
            version=int(d.get("version", 2)),
        )
