"""Transform: raw feed rows -> geolocated, skinned InsurgencyReport -> artifacts.

This module is the shared core used by both the local CLI and the AWS Lambda
handler, so the exact same snapshot is produced offline and in the cloud.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from . import binary
from .command_centers import pick_target
from .feeds import RawThreat, fetch_all
from .geolocate import Geolocator
from .models import InsurgencyReport, Machine, Severity

# Malware families that escalate an online node straight to Singularity.
_APEX_MALWARE = {"qakbot", "emotet", "trickbot", "dridex", "bazarloader", "icedid"}


def classify_severity(threat: RawThreat) -> Severity:
    """Derive a threat tier from feed signals (deterministic)."""
    if threat.online:
        if threat.malware.lower() in _APEX_MALWARE:
            return Severity.SINGULARITY
        return Severity.POSSESSION
    if threat.malware:
        return Severity.HAUNTING
    return Severity.FLATLINE


def build_report(
    threats: list[RawThreat],
    report_date: date | None = None,
    mmdb_path: str | None = None,
) -> InsurgencyReport:
    """Geolocate + skin raw threats into an InsurgencyReport."""
    report_date = report_date or datetime.now(UTC).date()
    geo = Geolocator(mmdb_path)
    machines: list[Machine] = []
    try:
        for t in threats:
            try:
                lat, lon, country = geo.locate(t.ip, t.country)
                tgt_lat, tgt_lon = pick_target(lat, lon)
                machines.append(
                    Machine(
                        lat=lat,
                        lon=lon,
                        tgt_lat=tgt_lat,
                        tgt_lon=tgt_lon,
                        severity=classify_severity(t),
                        source=t.source,
                        country=country,
                        first_seen=t.first_seen,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — skip one bad row, keep the batch
                print(f"[transform] skipped a row: {exc}")
    finally:
        geo.close()

    return InsurgencyReport(report_date=report_date, machines=machines)


def run(
    offline: bool = False,
    report_date: date | None = None,
    mmdb_path: str | None = None,
    limit: int | None = None,
) -> InsurgencyReport:
    """End-to-end: fetch feeds -> build the report."""
    threats = fetch_all(offline=offline, limit=limit)
    return build_report(threats, report_date=report_date, mmdb_path=mmdb_path)


def write_artifacts(report: InsurgencyReport, out_dir: str | Path) -> tuple[Path, Path]:
    """Write snapshot.json + snapshot.bin to ``out_dir``. Returns both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "snapshot.json"
    bin_path = out / "snapshot.bin"
    json_path.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    bin_path.write_bytes(binary.encode(report))
    return json_path, bin_path


def encode_json(report: InsurgencyReport) -> str:
    return json.dumps(report.to_json(), separators=(",", ":"))
