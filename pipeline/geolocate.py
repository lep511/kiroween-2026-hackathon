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

import hashlib
import re

# Representative lat/lon per ISO-3166 alpha-2 country (approximate centroids).
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "US": (39.8, -98.6),
    "CA": (56.1, -106.3),
    "MX": (23.6, -102.5),
    "BR": (-14.2, -51.9),
    "AR": (-38.4, -63.6),
    "CL": (-35.7, -71.5),
    "CO": (4.6, -74.3),
    "GB": (54.0, -2.0),
    "IE": (53.4, -8.2),
    "FR": (46.2, 2.2),
    "ES": (40.5, -3.7),
    "PT": (39.4, -8.2),
    "DE": (51.2, 10.4),
    "NL": (52.1, 5.3),
    "BE": (50.5, 4.5),
    "CH": (46.8, 8.2),
    "AT": (47.5, 14.6),
    "IT": (41.9, 12.6),
    "PL": (51.9, 19.1),
    "CZ": (49.8, 15.5),
    "SE": (60.1, 18.6),
    "NO": (60.5, 8.5),
    "FI": (61.9, 25.7),
    "DK": (56.3, 9.5),
    "RU": (61.5, 105.3),
    "UA": (48.4, 31.2),
    "TR": (38.9, 35.2),
    "RO": (45.9, 24.9),
    "GR": (39.1, 21.8),
    "BG": (42.7, 25.5),
    "CN": (35.9, 104.2),
    "JP": (36.2, 138.3),
    "KR": (35.9, 127.8),
    "KP": (40.3, 127.5),
    "IN": (20.6, 78.9),
    "ID": (-0.8, 113.9),
    "SG": (1.35, 103.8),
    "MY": (4.2, 101.9),
    "TH": (15.9, 100.9),
    "VN": (14.1, 108.3),
    "PH": (12.9, 121.8),
    "HK": (22.3, 114.2),
    "TW": (23.7, 120.9),
    "AU": (-25.3, 133.8),
    "NZ": (-40.9, 174.9),
    "ZA": (-30.6, 22.9),
    "NG": (9.1, 8.7),
    "EG": (26.8, 30.8),
    "KE": (-0.02, 37.9),
    "SA": (23.9, 45.1),
    "AE": (23.4, 53.8),
    "IL": (31.0, 34.9),
    "IR": (32.4, 53.7),
    "PK": (30.4, 69.3),
    "BD": (23.7, 90.4),
}

# Country name / demonym -> ISO alpha-2. Longest phrases first (see _NAME_PATTERNS).
COUNTRY_NAMES: dict[str, str] = {
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

# Built once: name phrases sorted longest-first so "north korea" wins over "korea".
_NAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (cc, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
    for name, cc in sorted(COUNTRY_NAMES.items(), key=lambda kv: -len(kv[0]))
]

_DEFAULT = (0.0, 0.0)  # Null Island for unknown countries.

# Canonical display names, indexed by ISO code (for the "location" field / UI).
CANONICAL_NAMES: dict[str, str] = {
    "US": "United States",
    "GB": "United Kingdom",
    "FR": "France",
    "DE": "Germany",
    "ES": "Spain",
    "PT": "Portugal",
    "IT": "Italy",
    "NL": "Netherlands",
    "BE": "Belgium",
    "CH": "Switzerland",
    "AT": "Austria",
    "PL": "Poland",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "DK": "Denmark",
    "IE": "Ireland",
    "RU": "Russia",
    "UA": "Ukraine",
    "TR": "Turkey",
    "GR": "Greece",
    "BG": "Bulgaria",
    "CZ": "Czechia",
    "RO": "Romania",
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "KP": "North Korea",
    "IN": "India",
    "ID": "Indonesia",
    "SG": "Singapore",
    "MY": "Malaysia",
    "TH": "Thailand",
    "VN": "Vietnam",
    "PH": "Philippines",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "AU": "Australia",
    "NZ": "New Zealand",
    "ZA": "South Africa",
    "NG": "Nigeria",
    "EG": "Egypt",
    "KE": "Kenya",
    "SA": "Saudi Arabia",
    "AE": "United Arab Emirates",
    "IL": "Israel",
    "IR": "Iran",
    "PK": "Pakistan",
    "BD": "Bangladesh",
    "CA": "Canada",
    "MX": "Mexico",
    "BR": "Brazil",
    "AR": "Argentina",
    "CL": "Chile",
    "CO": "Colombia",
}


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
