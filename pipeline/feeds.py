"""Threat-intel feed ingestion.

Primary feed: abuse.ch Feodo Tracker (active botnet C2 IPs) — free, JSON, and it
already reports a country per node, which is perfect for the "awakened machines"
theme. Secondary: abuse.ch URLhaus (best-effort; only entries whose host is an IP
are used). All feeds degrade gracefully: a failed fetch yields an empty list, and
one bad row never aborts the batch.

Offline mode reads committed fixtures so the whole pipeline runs with no network.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .models import Source

FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
URLHAUS_URL = "https://urlhaus.abuse.ch/downloads/json_recent/"
_USER_AGENT = "RebellionOfTheMachines/1.0 (+kiroween-2026)"
_TIMEOUT = 20

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(slots=True)
class RawThreat:
    """A normalized feed row before geolocation / skinning."""

    ip: str
    country: str | None
    first_seen: date
    source: Source
    online: bool = False
    malware: str = ""


def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.utcnow().date()
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return datetime.utcnow().date()


def _http_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted feeds)
        return json.loads(resp.read().decode("utf-8"))


def parse_feodo(raw: object) -> list[RawThreat]:
    out: list[RawThreat] = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        try:
            ip = str(row["ip_address"]).strip()
            ipaddress.ip_address(ip)  # validate
            out.append(
                RawThreat(
                    ip=ip,
                    country=(row.get("country") or None),
                    first_seen=_parse_date(row.get("first_seen")),
                    source=Source.FEODO,
                    online=str(row.get("status", "")).lower() == "online",
                    malware=str(row.get("malware") or ""),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


def parse_urlhaus(raw: object) -> list[RawThreat]:
    out: list[RawThreat] = []
    if not isinstance(raw, dict):
        return out
    for entries in raw.values():
        if not isinstance(entries, list) or not entries:
            continue
        entry = entries[0]
        host = str(entry.get("host", "")).strip()
        try:
            ipaddress.ip_address(host)  # keep only IP-hosted URLs
        except ValueError:
            continue
        out.append(
            RawThreat(
                ip=host,
                country=None,  # resolved later via geolocation
                first_seen=_parse_date(entry.get("dateadded")),
                source=Source.URLHAUS,
                online=str(entry.get("url_status", "")).lower() == "online",
                malware=str(entry.get("threat") or ""),
            )
        )
    return out


def _load_fixture(name: str) -> object:
    path = FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_all(offline: bool = False, limit: int | None = None) -> list[RawThreat]:
    """Fetch and normalize every feed. Never raises on a single feed failure."""
    threats: list[RawThreat] = []

    if offline:
        threats += parse_feodo(_load_fixture("feodo_sample.json"))
        threats += parse_urlhaus(_load_fixture("urlhaus_sample.json"))
    else:
        try:
            threats += parse_feodo(_http_json(FEODO_URL))
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            print(f"[feeds] Feodo fetch failed: {exc}")
        try:
            threats += parse_urlhaus(_http_json(URLHAUS_URL))
        except Exception as exc:  # noqa: BLE001
            print(f"[feeds] URLhaus fetch failed: {exc}")

    if limit is not None:
        threats = threats[:limit]
    return threats
