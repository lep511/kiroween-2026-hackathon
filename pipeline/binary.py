"""Binary snapshot encoder/decoder.

Implements schema/binary-layout.md. MUST stay byte-compatible with the Rust
decoder in rebellion-core. Change both sides together.

Layout (little-endian):
  Header  16 bytes: magic "RBMN" | version u8 | pad[3] | date_days u32 | count u32
  Record  24 bytes: lat f32 | lon f32 | tgt_lat f32 | tgt_lon f32 |
                    severity u8 | source u8 | country[2] | first_seen u32
"""

from __future__ import annotations

import struct

from .models import (
    InsurgencyReport,
    Machine,
    Severity,
    Source,
    date_from_days,
    days_since_epoch,
)

MAGIC = b"RBMN"
VERSION = 1

_HEADER = struct.Struct("<4sB3xII")  # 16 bytes
_RECORD = struct.Struct("<ffffBB2sI")  # 24 bytes

HEADER_SIZE = _HEADER.size
RECORD_SIZE = _RECORD.size


def encode(report: InsurgencyReport) -> bytes:
    """Serialize an InsurgencyReport to the compact binary snapshot."""
    out = bytearray()
    out += _HEADER.pack(
        MAGIC,
        VERSION,
        days_since_epoch(report.report_date),
        len(report.machines),
    )
    for m in report.machines:
        out += _RECORD.pack(
            m.lat,
            m.lon,
            m.tgt_lat,
            m.tgt_lon,
            int(m.severity),
            int(m.source),
            m.country.encode("ascii", "replace")[:2].ljust(2, b"Z"),
            days_since_epoch(m.first_seen),
        )
    return bytes(out)


def decode(data: bytes) -> InsurgencyReport:
    """Parse a binary snapshot back into an InsurgencyReport (used by tests)."""
    if len(data) < HEADER_SIZE:
        raise ValueError("snapshot too short for header")
    magic, version, date_days, count = _HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported version: {version}")
    expected = HEADER_SIZE + RECORD_SIZE * count
    if len(data) != expected:
        raise ValueError(f"expected {expected} bytes, got {len(data)}")

    machines: list[Machine] = []
    offset = HEADER_SIZE
    for _ in range(count):
        lat, lon, tgt_lat, tgt_lon, sev, src, country, first_seen = _RECORD.unpack_from(
            data, offset
        )
        offset += RECORD_SIZE
        machines.append(
            Machine(
                lat=lat,
                lon=lon,
                tgt_lat=tgt_lat,
                tgt_lon=tgt_lon,
                severity=Severity(min(max(sev, 0), 3)),
                source=Source(min(max(src, 0), 2)),
                country=country.decode("ascii", "replace"),
                first_seen=date_from_days(first_seen),
            )
        )
    return InsurgencyReport(report_date=date_from_days(date_days), machines=machines)
