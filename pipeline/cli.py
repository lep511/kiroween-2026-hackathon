"""Local CLI entry point.

Examples:
    python -m pipeline.cli --out ./sample --offline
    python -m pipeline.cli --out ./sample --limit 2000
"""

from __future__ import annotations

import argparse
from datetime import date

from .transform import run, write_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="Generate a daily Insurgency Report snapshot (JSON + binary).",
    )
    parser.add_argument("--out", default="./sample", help="output directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use committed fixtures instead of hitting live feeds",
    )
    parser.add_argument("--date", help="report date YYYY-MM-DD (default: today, UTC)")
    parser.add_argument("--mmdb", help="path to a GeoLite2 .mmdb for precise geolocation")
    parser.add_argument("--limit", type=int, help="cap the number of machines")
    args = parser.parse_args(argv)

    report_date = date.fromisoformat(args.date) if args.date else None
    report = run(
        offline=args.offline,
        report_date=report_date,
        mmdb_path=args.mmdb,
        limit=args.limit,
    )
    json_path, bin_path = write_artifacts(report, args.out)

    stats = report.stats()
    print("=== Insurgency Report generated ===")
    print(f"  date        : {report.report_date.isoformat()}")
    print(f"  machines    : {stats['total']}")
    print(f"  by severity : {stats['by_severity']}")
    print(f"  json        : {json_path}")
    print(f"  binary      : {bin_path} ({bin_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
