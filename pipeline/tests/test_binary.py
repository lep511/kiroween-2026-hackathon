"""Binary snapshot round-trip + layout tests (must match schema/binary-layout.md)."""

from __future__ import annotations

from datetime import date

from pipeline import binary
from pipeline.models import InsurgencyReport, Machine, Severity, Source


def _sample_report() -> InsurgencyReport:
    machines = [
        Machine(
            10.0, 20.0, 51.5, -0.1, Severity.SINGULARITY, Source.FEODO, "RU", date(2026, 10, 2)
        ),
        Machine(
            -33.9, 18.4, 1.35, 103.8, Severity.FLATLINE, Source.URLHAUS, "ZA", date(2026, 5, 20)
        ),
    ]
    return InsurgencyReport(report_date=date(2026, 11, 14), machines=machines)


def test_header_and_record_sizes_match_contract():
    assert binary.HEADER_SIZE == 16
    assert binary.RECORD_SIZE == 24


def test_file_size_formula():
    report = _sample_report()
    blob = binary.encode(report)
    assert len(blob) == binary.HEADER_SIZE + binary.RECORD_SIZE * len(report.machines)


def test_magic_and_version_prefix():
    blob = binary.encode(_sample_report())
    assert blob[:4] == b"RBMN"
    assert blob[4] == 1


def test_round_trip_preserves_fields():
    report = _sample_report()
    decoded = binary.decode(binary.encode(report))

    assert decoded.report_date == report.report_date
    assert len(decoded.machines) == len(report.machines)

    a, b = report.machines[0], decoded.machines[0]
    assert abs(a.lat - b.lat) < 1e-3
    assert abs(a.lon - b.lon) < 1e-3
    assert b.severity is Severity.SINGULARITY
    assert b.source is Source.FEODO
    assert b.country == "RU"
    assert b.first_seen == a.first_seen


def test_decode_rejects_bad_magic():
    blob = bytearray(binary.encode(_sample_report()))
    blob[0:4] = b"XXXX"
    try:
        binary.decode(bytes(blob))
    except ValueError as exc:
        assert "magic" in str(exc)
    else:
        raise AssertionError("expected ValueError for bad magic")
