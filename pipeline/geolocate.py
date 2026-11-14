"""Geolocation.

Two modes:
  * GeoLite2 (optional): precise IP -> lat/lon if a MaxMind .mmdb is provided.
  * Country centroid (default, fully offline): map an ISO country code to a
    representative coordinate, with a small deterministic jitter so many machines
    from the same country do not stack on a single pixel.

The country-centroid mode needs no API keys or accounts, which keeps the demo
runnable offline. Feodo Tracker already reports a country per node, so this is
accurate at country resolution without any external calls.
"""

from __future__ import annotations

import hashlib

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

_DEFAULT = (0.0, 0.0)  # Null Island for unknown countries.


def _jitter(seed: str, spread: float = 3.0) -> tuple[float, float]:
    """Deterministic small lat/lon offset derived from ``seed``."""
    # Non-cryptographic: only used to spread co-located points deterministically.
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    dlat = (h[0] / 255.0 - 0.5) * 2 * spread
    dlon = (h[1] / 255.0 - 0.5) * 2 * spread
    return dlat, dlon


class Geolocator:
    """Resolve an IP + country hint to (lat, lon, country)."""

    def __init__(self, mmdb_path: str | None = None) -> None:
        self._reader = None
        if mmdb_path:
            try:  # geoip2 is optional; absence just falls back to centroids.
                import geoip2.database  # type: ignore

                self._reader = geoip2.database.Reader(mmdb_path)
            except Exception:
                self._reader = None

    def locate(self, ip: str, country: str | None = None) -> tuple[float, float, str]:
        if self._reader is not None:
            try:
                r = self._reader.city(ip)
                if r.location.latitude is not None:
                    cc = (r.country.iso_code or country or "ZZ").upper()
                    return float(r.location.latitude), float(r.location.longitude), cc
            except Exception:  # noqa: S110 — intentionally fall through to centroid
                pass

        cc = (country or "ZZ").upper()
        base_lat, base_lon = COUNTRY_CENTROIDS.get(cc, _DEFAULT)
        dlat, dlon = _jitter(ip or cc)
        return base_lat + dlat, base_lon + dlon, cc

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
