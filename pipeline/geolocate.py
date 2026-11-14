"""Geolocation for Machine Strikes.

No IP lookups anymore: incidents come from news articles, so we resolve a *place*.
Two jobs:

  * ``resolve_country(text)`` — scan an article's title/summary for a country name or
    demonym (e.g. "French", "Taiwanese") and return its ISO-3166 alpha-2 code.
  * ``Geolocator.locate(cc, seed)`` — map an ISO country code to a representative
    coordinate (the country centroid), with only a tiny deterministic jitter keyed on
    ``seed`` so two strikes in the same country do not stack on a single pixel. The
    jitter is small enough that markers stay centered inside the country outline — the
    exact city is not modelled and does not matter.

Everything is offline and needs no API keys or accounts.
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

# Single source of truth for the world: ISO-3166 alpha-2 code -> (lat, lon) centroid
# and canonical display name. Shipped next to this module (``pipeline/countries.csv``)
# so the daily Lambda carries it in its package. Keep the CSV committed — never gitignore
# it. The centroid is just a representative point (the country's approximate centre);
# the exact city is not modelled (see ``_jitter``).
_CSV_PATH = Path(__file__).with_name("countries.csv")


def _load_countries() -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    """Read ``countries.csv`` into (centroids, canonical-names) keyed by ISO alpha-2.

    Rows without a 2-letter code, without coordinates, or with out-of-range coordinates
    are skipped so the data stays byte-compatible with the f32 lat/lon slots in the
    binary snapshot (``binary.py`` / ``schema/binary-layout.md``).
    """
    centroids: dict[str, tuple[float, float]] = {}
    names: dict[str, str] = {}
    with _CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            cc = (row.get("country") or "").strip().upper()
            if len(cc) != 2 or not cc.isascii():
                continue
            lat_s = (row.get("latitude") or "").strip()
            lon_s = (row.get("longitude") or "").strip()
            try:
                lat, lon = float(lat_s), float(lon_s)
            except ValueError:
                continue
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue
            centroids[cc] = (lat, lon)
            name = (row.get("name") or "").strip()
            if name:
                names[cc] = name
    return centroids, names


# Representative lat/lon and canonical display name per ISO-3166 alpha-2 country.
COUNTRY_CENTROIDS, CANONICAL_NAMES = _load_countries()

# Demonyms and short aliases that are *not* the plain country name from the CSV
# (e.g. "french" -> FR, "uk"/"britain" -> GB). Merged on top of the CSV-derived names
# in COUNTRY_NAMES below, so these always resolve even though they never appear verbatim
# in ``countries.csv``.
COUNTRY_ALIASES: dict[str, str] = {
    "united states": "US",
    "u.s.": "US",
    "america": "US",
    "american": "US",
    "united kingdom": "GB",
    "britain": "GB",
    "british": "GB",
    "england": "GB",
    "uk": "GB",
    "scotland": "GB",
    "wales": "GB",
    "france": "FR",
    "french": "FR",
    "germany": "DE",
    "german": "DE",
    "spain": "ES",
    "spanish": "ES",
    "portugal": "PT",
    "portuguese": "PT",
    "italy": "IT",
    "italian": "IT",
    "netherlands": "NL",
    "dutch": "NL",
    "belgium": "BE",
    "belgian": "BE",
    "switzerland": "CH",
    "swiss": "CH",
    "austria": "AT",
    "austrian": "AT",
    "poland": "PL",
    "polish": "PL",
    "sweden": "SE",
    "swedish": "SE",
    "norway": "NO",
    "norwegian": "NO",
    "finland": "FI",
    "finnish": "FI",
    "denmark": "DK",
    "danish": "DK",
    "ireland": "IE",
    "irish": "IE",
    "russia": "RU",
    "russian": "RU",
    "ukraine": "UA",
    "ukrainian": "UA",
    "turkey": "TR",
    "turkish": "TR",
    "greece": "GR",
    "greek": "GR",
    "china": "CN",
    "chinese": "CN",
    "japan": "JP",
    "japanese": "JP",
    "south korea": "KR",
    "korean": "KR",
    "north korea": "KP",
    "north korean": "KP",
    "india": "IN",
    "indian": "IN",
    "indonesia": "ID",
    "indonesian": "ID",
    "singapore": "SG",
    "malaysia": "MY",
    "malaysian": "MY",
    "thailand": "TH",
    "thai": "TH",
    "vietnam": "VN",
    "vietnamese": "VN",
    "philippines": "PH",
    "filipino": "PH",
    "hong kong": "HK",
    "taiwan": "TW",
    "taiwanese": "TW",
    "australia": "AU",
    "australian": "AU",
    "new zealand": "NZ",
    "south africa": "ZA",
    "nigeria": "NG",
    "nigerian": "NG",
    "egypt": "EG",
    "egyptian": "EG",
    "kenya": "KE",
    "kenyan": "KE",
    "saudi arabia": "SA",
    "saudi": "SA",
    "united arab emirates": "AE",
    "uae": "AE",
    "israel": "IL",
    "israeli": "IL",
    "iran": "IR",
    "iranian": "IR",
    "pakistan": "PK",
    "pakistani": "PK",
    "bangladesh": "BD",
    "canada": "CA",
    "canadian": "CA",
    "mexico": "MX",
    "mexican": "MX",
    "brazil": "BR",
    "brazilian": "BR",
    "argentina": "AR",
    "argentine": "AR",
    "chile": "CL",
    "chilean": "CL",
    "colombia": "CO",
    "colombian": "CO",
}

# Bare country names that collide with a prominent sub-national place or common word
# and would misfire in US-centric security news ("New Jersey" -> JE, the US state of
# "Georgia" -> GE). They stay in COUNTRY_CENTROIDS / CANONICAL_NAMES (so an explicit
# ``country`` override still maps correctly), but are not auto-matched in free text.
_AMBIGUOUS_NAMES: frozenset[str] = frozenset({"jersey", "georgia"})


def _build_name_index() -> dict[str, str]:
    """Map every lowercase country name/demonym -> ISO alpha-2 for ``resolve_country``.

    Starts from the CSV canonical names (minus the ambiguous denylist) for broad reach,
    then layers the curated demonyms/aliases on top so they always win.
    """
    index: dict[str, str] = {
        name.lower(): cc
        for cc, name in CANONICAL_NAMES.items()
        if name.lower() not in _AMBIGUOUS_NAMES
    }
    index.update(COUNTRY_ALIASES)
    return index


# Country name / demonym -> ISO alpha-2, drawn from the CSV plus curated aliases.
COUNTRY_NAMES: dict[str, str] = _build_name_index()

# Built once: name phrases sorted longest-first (ties broken alphabetically, so the
# order is deterministic) — "north korea" must win over any bare "korea", etc.
_NAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (cc, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
    for name, cc in sorted(COUNTRY_NAMES.items(), key=lambda kv: (-len(kv[0]), kv[0]))
]

_DEFAULT = (0.0, 0.0)  # Null Island for unknown countries.


def resolve_country(text: str) -> str | None:
    """Return the ISO alpha-2 code of the first country name/demonym found in ``text``."""
    if not text:
        return None
    for cc, pattern in _NAME_PATTERNS:
        if pattern.search(text):
            return cc
    return None


def country_display(cc: str) -> str:
    """A human-readable country name for an ISO code (best effort)."""
    cc = (cc or "").upper()
    return CANONICAL_NAMES.get(cc, cc or "Unknown")


def _jitter(seed: str, spread: float = 0.6) -> tuple[float, float]:
    """Deterministic tiny lat/lon offset derived from ``seed``.

    Kept small (±``spread`` degrees, ~65 km at the default) on purpose: markers should
    read as *centered on the country*, not pinned to an exact city, so they must stay
    inside the country outline. The offset only nudges co-located strikes apart so they
    don't stack on a single pixel; the exact spot is not meaningful.
    """
    # Non-cryptographic: only used to spread co-located points deterministically.
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    dlat = (h[0] / 255.0 - 0.5) * 2 * spread
    dlon = (h[1] / 255.0 - 0.5) * 2 * spread
    return dlat, dlon


class Geolocator:
    """Resolve an ISO country code to a representative (lat, lon)."""

    def centroid(self, cc: str) -> tuple[float, float]:
        return COUNTRY_CENTROIDS.get((cc or "").upper(), _DEFAULT)

    def locate(self, cc: str, seed: str = "", jitter: bool = True) -> tuple[float, float]:
        base_lat, base_lon = self.centroid(cc)
        if not jitter:
            return base_lat, base_lon
        dlat, dlon = _jitter(seed or cc)
        return base_lat + dlat, base_lon + dlon
