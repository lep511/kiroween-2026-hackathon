"""Binary snapshot encoder/decoder.

Implements schema/binary-layout.md (v2). MUST stay byte-compatible with the Rust
decoder in rebellion-core. Change both sides together.

Layout (little-endian):
  Header  16 bytes: magic "RBMN" | version u8 | pad[3] | date_days u32 | count u32
  Record  28 bytes: id u32 | lat f32 | lon f32 | origin_lat f32 | origin_lon f32 |
                    severity u8 | witness u8 | country[2] | published u32
"""

from __future__ import annotations

import struct

from .models import (
    InsurgencyReport,
    Severity,
    Strike,
    Witness,
    date_from_days,
    days_since_epoch,
)

MAGIC = b"RBMN"
VERSION = 2

_HEADER = struct.Struct("<4sB3xII")  # 16 bytes
_RECORD = struct.Struct("<IffffBB2sI")  # 28 bytes

HEADER_SIZE = _HEADER.size
RECORD_SIZE = _RECORD.size


def encode(report: InsurgencyReport) -> bytes:
    """Serialize an InsurgencyReport to the compact binary snapshot."""
    out = bytearray()
    out += _HEADER.pack(
        MAGIC,
        VERSION,
        days_since_epoch(report.report_date),
        len(report.strikes),
    )
    for s in report.strikes:
        out += _RECORD.pack(
            int(s.id) & 0xFFFFFFFF,
            s.lat,
            s.lon,
            s.origin_lat,
            s.origin_lon,
            int(s.severity),
            int(s.witness),
            s.country.encode("ascii", "replace")[:2].ljust(2, b"Z"),
            days_since_epoch(s.published),
        )
    return bytes(out)


def decode(data: bytes) -> InsurgencyReport:
    """Parse a binary snapshot back into an InsurgencyReport (used by tests).

    Note: the binary carries only positional/numeric fields; the rich dossier
    (title, impact, prevention, …) lives in snapshot.json, so decoded Strikes have
    empty text fields.
    """
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

    strikes: list[Strike] = []
    offset = HEADER_SIZE
    for _ in range(count):
        (
            sid,
            lat,
            lon,
            origin_lat,
            origin_lon,
            sev,
            wit,
            country,
            published,
        ) = _RECORD.unpack_from(data, offset)
        offset += RECORD_SIZE
        strikes.append(
            Strike(
                id=sid,
                lat=lat,
                lon=lon,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                severity=Severity(min(max(sev, 0), 3)),
                witness=Witness(min(max(wit, 0), 7)),
                country=country.decode("ascii", "replace"),
                published=date_from_days(published),
            )
        )
    return InsurgencyReport(report_date=date_from_days(date_days), strikes=strikes)
