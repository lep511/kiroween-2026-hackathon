"""Geolocation for Machine Strikes.

No IP lookups and no free-text place detection: the extraction agent (or curated
reporting) names each strike's ground-zero country as an ISO-3166 alpha-2 code. This
module only turns that code into a coordinate:

  * ``Geolocator.locate(cc, seed)`` — map an ISO country code to a representative
    coordinate (the country centroid), with only a tiny deterministic jitter keyed on
    ``seed`` so two strikes in the same country do not stack on a single pixel. The
    jitter is small enough that markers stay centered inside the country outline — the
    exact city is not modelled and does not matter.
  * ``country_display(cc)`` — the canonical display name for a code.

Everything is offline and needs no API keys or accounts.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

# Single source of truth for the world: ISO-3166 alpha-2 code -> (lat, lon) centroid
# and canonical display name. Shipped next to this module (``pipeline/countries.csv``)
# so the weekly Lambda carries it in its package. Keep the CSV committed — never gitignore
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

_DEFAULT = (0.0, 0.0)  # Null Island for unknown countries.


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
