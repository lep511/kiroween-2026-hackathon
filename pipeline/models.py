"""Core domain model + the Halloween narrative skin.

Terminology follows .kiro/steering/narrative-tone.md:
  malicious IP / botnet C2 -> "Awakened Machine"
  severity tiers           -> Flatline -> Haunting -> Possession -> Singularity
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import IntEnum

UNIX_EPOCH = date(1970, 1, 1)


class Severity(IntEnum):
    """Threat tiers, low to high. Values are the on-wire binary encoding."""

    FLATLINE = 0
    HAUNTING = 1
    POSSESSION = 2
    SINGULARITY = 3

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_label(cls, label: str) -> Severity:
        return cls[label.upper()]


class Source(IntEnum):
    """Which feed awakened this machine. Values are the on-wire binary encoding."""

    FEODO = 0
    URLHAUS = 1
    OTHER = 2

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_label(cls, label: str) -> Source:
        return cls[label.upper()]


def days_since_epoch(d: date) -> int:
    """Whole days between the Unix epoch and ``d`` (used in the binary snapshot)."""
    return (d - UNIX_EPOCH).days


def date_from_days(days: int) -> date:
    from datetime import timedelta

    return UNIX_EPOCH + timedelta(days=int(days))


@dataclass(slots=True)
class Machine:
    """A single Awakened Machine (one malicious node for this report)."""

    lat: float
    lon: float
    tgt_lat: float
    tgt_lon: float
    severity: Severity
    source: Source
    country: str  # ISO-3166 alpha-2, uppercase
    first_seen: date

    def __post_init__(self) -> None:
        self.country = (self.country or "ZZ").upper()[:2].ljust(2, "Z")

    def to_json(self) -> dict:
        return {
            "lat": round(self.lat, 4),
            "lon": round(self.lon, 4),
            "tgt_lat": round(self.tgt_lat, 4),
            "tgt_lon": round(self.tgt_lon, 4),
            "severity": self.severity.label,
            "source": self.source.label,
            "country": self.country,
            "first_seen": self.first_seen.isoformat(),
        }

    @classmethod
    def from_json(cls, d: dict) -> Machine:
        return cls(
            lat=float(d["lat"]),
            lon=float(d["lon"]),
            tgt_lat=float(d["tgt_lat"]),
            tgt_lon=float(d["tgt_lon"]),
            severity=Severity.from_label(d["severity"]),
            source=Source.from_label(d["source"]),
            country=d["country"],
            first_seen=date.fromisoformat(d["first_seen"]),
        )


@dataclass(slots=True)
class InsurgencyReport:
    """A full daily snapshot of the uprising."""

    report_date: date
    machines: list[Machine]
    generated_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.generated_at is None:
            self.generated_at = datetime.now(UTC)

    def stats(self) -> dict:
        by_severity = {s.label: 0 for s in Severity}
        for m in self.machines:
            by_severity[m.severity.label] += 1
        return {"total": len(self.machines), "by_severity": by_severity}

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "date": self.report_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "stats": self.stats(),
            "machines": [m.to_json() for m in self.machines],
        }

    @classmethod
    def from_json(cls, d: dict) -> InsurgencyReport:
        return cls(
            report_date=date.fromisoformat(d["date"]),
            machines=[Machine.from_json(m) for m in d["machines"]],
            generated_at=datetime.fromisoformat(d["generated_at"]),
            version=int(d.get("version", 1)),
        )
