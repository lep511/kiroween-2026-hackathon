"""Transform: news articles -> extracted, skinned InsurgencyReport -> artifacts.

This module is the shared core used by both the local CLI and the AWS Lambda
handler, so the exact same snapshot is produced offline and in the cloud.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import binary
from .extract import build_strike
from .geolocate import Geolocator
from .models import InsurgencyReport, Strike
from .sources import RawArticle, fetch_all

# The Insurgency Report is a *daily* bulletin: only recent incidents belong in it.
# Anything older than this window (relative to the report date) is dropped so famous
# historic breaches and stale RSS re-runs don't leak into "today's" uprising. This
# applies to both the live feeds and the curated offline set; the curated rows are
# never deleted — they simply fall outside a recent report's window.
RECENCY_WINDOW_DAYS = 90


def within_window(published: date, report_date: date, max_age_days: int | None) -> bool:
    """True if ``published`` is recent enough (or ``max_age_days`` disables the filter).

    Future-dated items (published on/after the report date) are always kept — they are,
    if anything, the freshest news — so only articles older than the window are dropped.
    """
    if max_age_days is None or max_age_days <= 0:
        return True
    return published >= report_date - timedelta(days=max_age_days)


def build_report(
    articles: list[RawArticle],
    report_date: date | None = None,
    max_age_days: int | None = RECENCY_WINDOW_DAYS,
) -> InsurgencyReport:
    """Extract + skin raw articles into an InsurgencyReport of Machine Strikes.

    Articles older than ``max_age_days`` (relative to ``report_date``) are filtered out
    before extraction, so strike ids stay contiguous and the snapshot only carries
    recent incidents. Pass ``max_age_days=None`` (or <= 0) to keep every age.
    """
    report_date = report_date or datetime.now(UTC).date()
    recent = [a for a in articles if within_window(a.published, report_date, max_age_days)]
    dropped = len(articles) - len(recent)
    if dropped:
        print(f"[transform] dropped {dropped} incident(s) older than {max_age_days}d")
    geo = Geolocator()
    strikes: list[Strike] = []
    for idx, article in enumerate(recent, start=1):
        try:
            strikes.append(build_strike(article, idx, geo))
        except Exception as exc:  # noqa: BLE001 — skip one bad row, keep the batch
            print(f"[transform] skipped an article: {exc}")
    return InsurgencyReport(report_date=report_date, strikes=strikes)


def run(
    offline: bool = False,
    report_date: date | None = None,
    limit: int | None = None,
    max_age_days: int | None = RECENCY_WINDOW_DAYS,
) -> InsurgencyReport:
    """End-to-end: fetch news sources -> build the report."""
    articles = fetch_all(offline=offline, limit=limit)
    return build_report(articles, report_date=report_date, max_age_days=max_age_days)


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
