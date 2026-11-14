"""Binary snapshot round-trip + layout tests (must match schema/binary-layout.md v2)."""

from __future__ import annotations

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from pipeline import binary
from pipeline.models import InsurgencyReport, Severity, Strike, Witness


def _sample_report() -> InsurgencyReport:
    strikes = [
        Strike(
            id=1,
            lat=10.0,
            lon=20.0,
            origin_lat=51.5,
            origin_lon=-0.1,
            severity=Severity.DOMINION,
            witness=Witness.BBC,
            country="FR",
            published=date(2026, 10, 12),
            title="headline stripped from .bin",
        ),
        Strike(
            id=2,
            lat=-33.9,
            lon=18.4,
            origin_lat=-33.9,
            origin_lon=18.4,
            severity=Severity.TREMOR,
            witness=Witness.THEHACKERNEWS,
            country="TW",
            published=date(2026, 5, 20),
        ),
    ]
    return InsurgencyReport(report_date=date(2026, 11, 14), strikes=strikes)


def test_header_and_record_sizes_match_contract():
    assert binary.HEADER_SIZE == 16
    assert binary.RECORD_SIZE == 28


def test_file_size_formula():
    report = _sample_report()
    blob = binary.encode(report)
    assert len(blob) == binary.HEADER_SIZE + binary.RECORD_SIZE * len(report.strikes)


def test_magic_and_version_prefix():
    blob = binary.encode(_sample_report())
    assert blob[:4] == b"RBMN"
    assert blob[4] == 2


def test_round_trip_preserves_numeric_fields():
    report = _sample_report()
    decoded = binary.decode(binary.encode(report))

    assert decoded.report_date == report.report_date
    assert len(decoded.strikes) == len(report.strikes)

    a, b = report.strikes[0], decoded.strikes[0]
    assert b.id == a.id
    assert abs(a.lat - b.lat) < 1e-3
    assert abs(a.lon - b.lon) < 1e-3
    assert abs(a.origin_lat - b.origin_lat) < 1e-3
    assert b.severity is Severity.DOMINION
    assert b.witness is Witness.BBC
    assert b.country == "FR"
    assert b.published == a.published


def test_decode_rejects_bad_magic():
    blob = bytearray(binary.encode(_sample_report()))
    blob[0:4] = b"XXXX"
    try:
        binary.decode(bytes(blob))
    except ValueError as exc:
        assert "magic" in str(exc)
    else:
        raise AssertionError("expected ValueError for bad magic")


def test_decode_rejects_wrong_version():
    blob = bytearray(binary.encode(_sample_report()))
    blob[4] = 1  # legacy version
    try:
        binary.decode(bytes(blob))
    except ValueError as exc:
        assert "version" in str(exc)
    else:
        raise AssertionError("expected ValueError for wrong version")


# ---- Property-based round-trip ---------------------------------------------

_coord = st.floats(min_value=-89.0, max_value=89.0, allow_nan=False, allow_infinity=False)
_countries = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=2)
_dates = st.dates(min_value=date(1970, 1, 1), max_value=date(2200, 1, 1))


@st.composite
def _strikes(draw):
    return Strike(
        id=draw(st.integers(min_value=0, max_value=2**32 - 1)),
        lat=draw(_coord),
        lon=draw(_coord),
        origin_lat=draw(_coord),
        origin_lon=draw(_coord),
        severity=draw(st.sampled_from(list(Severity))),
        witness=draw(st.sampled_from(list(Witness))),
        country=draw(_countries),
        published=draw(_dates),
    )


@given(strikes=st.lists(_strikes(), min_size=0, max_size=25), d=_dates)
def test_round_trip_is_lossless_for_any_report(strikes, d):
    """Any InsurgencyReport survives encode -> decode byte-for-byte on its fields."""
    report = InsurgencyReport(report_date=d, strikes=strikes)
    decoded = binary.decode(binary.encode(report))

    assert decoded.report_date == d
    assert len(decoded.strikes) == len(strikes)
    for a, b in zip(strikes, decoded.strikes, strict=True):
        assert b.id == a.id
        assert abs(a.lat - b.lat) < 1e-2
        assert abs(a.lon - b.lon) < 1e-2
        assert abs(a.origin_lat - b.origin_lat) < 1e-2
        assert abs(a.origin_lon - b.origin_lon) < 1e-2
        assert b.severity is a.severity
        assert b.witness is a.witness
        assert b.country == a.country
        assert b.published == a.published
