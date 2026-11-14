"""Geolocation tests: countries.csv coverage + coordinate compatibility.

These assert properties over the *entire* loaded dataset, so they double as a guard
that ``pipeline/countries.csv`` ships with the package and stays byte-compatible with
the binary snapshot (f32 lat/lon + 2-byte ASCII country code).
"""

from __future__ import annotations

from datetime import date

from pipeline.binary import encode
from pipeline.geolocate import (
    CANONICAL_NAMES,
    COUNTRY_CENTROIDS,
    Geolocator,
    country_display,
)
from pipeline.models import InsurgencyReport, Severity, Strike, Witness

# ---- Coverage --------------------------------------------------------------


def test_countries_csv_loaded_with_broad_coverage():
    # The CSV is the single source of truth for the world; if packaging ever drops it
    # this collapses to a handful of entries and the test fails loudly.
    assert len(COUNTRY_CENTROIDS) >= 200
    assert COUNTRY_CENTROIDS.keys() == CANONICAL_NAMES.keys()


def test_every_code_and_coordinate_is_binary_compatible():
    for cc, (lat, lon) in COUNTRY_CENTROIDS.items():
        # Country code must be exactly two ASCII upper-case letters: the binary record
        # encodes it into two ASCII bytes (see binary.py / schema/binary-layout.md).
        assert len(cc) == 2 and cc.isascii() and cc.isupper()
        assert cc.encode("ascii")  # never raises for a valid record
        # Coordinates must fit the f32 lat/lon slots and the globe's valid range.
        assert -90.0 <= lat <= 90.0
        assert -180.0 <= lon <= 180.0


def test_display_name_round_trips_for_every_country():
    for cc, name in CANONICAL_NAMES.items():
        assert country_display(cc) == name
    assert country_display("ZZ") == "ZZ"  # unknown fallback is unchanged
    assert country_display("") == "Unknown"


# ---- Geolocator ------------------------------------------------------------


def test_locate_jitter_stays_small_and_deterministic():
    geo = Geolocator()
    base = geo.centroid("FR")
    lat, lon = geo.locate("FR", seed="x")
    # Jitter keeps the marker within ~1 degree of the centroid (inside the outline).
    assert abs(lat - base[0]) <= 1.0 and abs(lon - base[1]) <= 1.0
    assert geo.locate("FR", seed="x") == (lat, lon)  # deterministic for a given seed
    assert geo.locate("FR", seed="x", jitter=False) == base


def test_unknown_country_falls_back_to_null_island():
    assert Geolocator().centroid("ZZ") == (0.0, 0.0)


def test_all_centroids_encode_into_a_binary_snapshot():
    # Exhaustive check that every country produces an encodable strike record.
    strikes = [
        Strike(
            id=i,
            lat=lat,
            lon=lon,
            origin_lat=lat,
            origin_lon=lon,
            severity=Severity.SIEGE,
            witness=Witness.BBC,
            country=cc,
            published=date(2026, 11, 14),
        )
        for i, (cc, (lat, lon)) in enumerate(COUNTRY_CENTROIDS.items(), start=1)
    ]
    report = InsurgencyReport(report_date=date(2026, 11, 14), strikes=strikes)
    blob = encode(report)  # must not raise for any country code / coordinate
    assert len(blob) > 0
