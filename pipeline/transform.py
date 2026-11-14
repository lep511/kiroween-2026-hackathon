"""Transform: news articles -> extracted, skinned InsurgencyReport -> artifacts.

This module is the shared core used by both the local CLI and the AWS Lambda
handler, so the exact same snapshot is produced offline and in the cloud.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from . import binary
from .extract import build_strike
from .geolocate import Geolocator
from .models import InsurgencyReport, Strike
from .sources import RawArticle, fetch_all


def build_report(
    articles: list[RawArticle],
    report_date: date | None = None,
) -> InsurgencyReport:
    """Extract + skin raw articles into an InsurgencyReport of Machine Strikes."""
    report_date = report_date or datetime.now(UTC).date()
    geo = Geolocator()
    strikes: list[Strike] = []
    for idx, article in enumerate(articles, start=1):
        try:
            strikes.append(build_strike(article, idx, geo))
        except Exception as exc:  # noqa: BLE001 — skip one bad row, keep the batch
            print(f"[transform] skipped an article: {exc}")
    return InsurgencyReport(report_date=report_date, strikes=strikes)


def run(
    offline: bool = False,
    report_date: date | None = None,
    limit: int | None = None,
) -> InsurgencyReport:
    """End-to-end: fetch news sources -> build the report."""
    articles = fetch_all(offline=offline, limit=limit)
    return build_report(articles, report_date=report_date)


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
