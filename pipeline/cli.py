"""Local CLI entry point.

The Strands/Bedrock agent is mandatory: the CLI runs the agent preflight first and exits
with code 2 if the SDK, AWS credentials, or Bedrock model access are missing — even in
``--offline`` mode.

The Insurgency Report accumulates a rolling 7-day window: the CLI reads the previous
``snapshot.json`` in ``--out`` (unless ``--fresh``), adds the day's new articles (an
already-processed URL is reused, never sent to the agent again), drops strikes older than
``--max-age-days``, and writes the result. Locally an extraction failure discards that
article (no retries). Exit codes:

    0  the day's batch was accepted and the report was written
    2  the extraction agent is unavailable (nothing read, nothing written)
    3  more than 20% of the day's articles were discarded: the new strikes were not
       added, but the accumulated report (minus expired strikes) was still written
    4  the previous snapshot.json in --out is invalid or dated after --date
       (nothing written)

Examples:
    python -m pipeline.cli --out ./sample --offline      # curated real incidents
    python -m pipeline.cli --out ./sample                # live RSS from news outlets
    python -m pipeline.cli --out ./sample --fresh        # ignore the existing snapshot
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .agent_extract import DEFAULT_MODEL_ID, AgentUnavailable
from .sources import PER_FEED_LIMIT
from .transform import (
    RECENCY_WINDOW_DAYS,
    PreviousSnapshotInvalid,
    check_report_order,
    read_previous,
    run,
    write_artifacts,
)

EXIT_AGENT_UNAVAILABLE = 2
EXIT_BATCH_REJECTED = 3
EXIT_PREVIOUS_INVALID = 4


def _positive_int(value: str) -> int:
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


def _update_local_manifest(snapshots_dir: Path, date_key: str) -> None:
    """Add the date to the local manifest.json in the snapshots directory."""
    manifest_path = snapshots_dir / "manifest.json"
    existing: list[str] = []
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        existing = data.get("dates", [])
    dates = sorted(set(existing) | {date_key})
    manifest_path.write_text(json.dumps({"dates": dates}) + "\n")


def main(argv: list[str] | None = None, **run_kwargs) -> int:
    """Run the CLI. ``run_kwargs`` are forwarded to ``transform.run`` (test injection)."""
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="Generate the rolling 7-day Insurgency Report snapshot (JSON + binary) "
        "of real cyberattacks reported by recognized news outlets. Requires the Strands "
        "agent on Amazon Bedrock (AWS credentials + model access).",
    )
    parser.add_argument("--out", default="./sample", help="output directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use the committed curated incidents instead of live news RSS feeds",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="ignore the existing snapshot.json in --out instead of accumulating onto it",
    )
    parser.add_argument("--date", help="report date YYYY-MM-DD (default: today, UTC)")
    parser.add_argument("--limit", type=int, help="cap the total number of articles")
    parser.add_argument(
        "--per-feed-limit",
        type=_positive_int,
        default=PER_FEED_LIMIT,
        help=f"cap the articles kept from each live feed (default: {PER_FEED_LIMIT})",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=RECENCY_WINDOW_DAYS,
        help="drop strikes published more than N days before the report date "
        f"(default: {RECENCY_WINDOW_DAYS}; 0 disables)",
    )
    parser.add_argument(
        "--agent-model",
        help=f"Bedrock model id for the extraction agent (default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--agent-region",
        help="AWS region for the agent (default: resolved from the AWS environment)",
    )
    args = parser.parse_args(argv)

    report_date = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    try:
        previous = None if args.fresh else read_previous(args.out)
        check_report_order(previous, report_date)
    except PreviousSnapshotInvalid as exc:
        print(f"[cli] {exc}; nothing written (use --fresh to start over)", file=sys.stderr)
        return EXIT_PREVIOUS_INVALID

    try:
        outcome = run(
            offline=args.offline,
            report_date=report_date,
            limit=args.limit,
            max_age_days=args.max_age_days,
            per_feed_limit=args.per_feed_limit,
            agent_model=args.agent_model,
            agent_region=args.agent_region,
            previous=previous,
            **run_kwargs,
        )
    except AgentUnavailable as exc:
        print(f"[cli] the extraction agent is unavailable: {exc}", file=sys.stderr)
        return EXIT_AGENT_UNAVAILABLE

    report = outcome.report
    json_path, bin_path = write_artifacts(report, args.out)
    _update_local_manifest(Path(args.out).parent, report.report_date.isoformat())

    stats = report.stats()
    print("=== Insurgency Report generated ===")
    print(f"  date        : {report.report_date.isoformat()}")
    print(f"  strikes     : {stats['total']}")
    print(f"  by severity : {stats['by_severity']}")
    print(f"  new         : {outcome.new}")
    print(f"  carried     : {outcome.carried}")
    print(f"  expired     : {outcome.expired}")
    print(f"  discarded   : {outcome.discarded}/{outcome.fetched}")
    print(f"  json        : {json_path}")
    print(f"  binary      : {bin_path} ({bin_path.stat().st_size} bytes)")
    if not outcome.accepted:
        print(
            "[cli] batch rejected: more than 20% of the day's articles were discarded; "
            "the accumulated report was written without the new strikes",
            file=sys.stderr,
        )
        return EXIT_BATCH_REJECTED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
