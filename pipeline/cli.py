"""Local CLI entry point.

Examples:
    python -m pipeline.cli --out ./sample --offline      # curated real incidents
    python -m pipeline.cli --out ./sample                # live RSS from news outlets
"""

from __future__ import annotations

import argparse
from datetime import date

from .transform import RECENCY_WINDOW_DAYS, run, write_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="Generate a daily Insurgency Report snapshot (JSON + binary) of "
        "real cyberattacks reported by recognized news outlets.",
    )
    parser.add_argument("--out", default="./sample", help="output directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use the committed curated incidents instead of live news RSS feeds",
    )
    parser.add_argument("--date", help="report date YYYY-MM-DD (default: today, UTC)")
    parser.add_argument("--limit", type=int, help="cap the number of strikes")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=RECENCY_WINDOW_DAYS,
        help="drop incidents older than N days before the report date "
        f"(default: {RECENCY_WINDOW_DAYS}; 0 disables the filter)",
    )
    args = parser.parse_args(argv)

    report_date = date.fromisoformat(args.date) if args.date else None
    report = run(
        offline=args.offline,
        report_date=report_date,
        limit=args.limit,
        max_age_days=args.max_age_days,
    )
    json_path, bin_path = write_artifacts(report, args.out)

    stats = report.stats()
    print("=== Insurgency Report generated ===")
    print(f"  date        : {report.report_date.isoformat()}")
    print(f"  strikes     : {stats['total']}")
    print(f"  by severity : {stats['by_severity']}")
    print(f"  json        : {json_path}")
    print(f"  binary      : {bin_path} ({bin_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
