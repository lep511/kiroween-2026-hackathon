"""Local command line for the Insurgency Report pipeline.

Runs on your machine what the weekly cloud run does in Step Functions (Fetch, Extract,
Assemble), without Lambda, S3 or DynamoDB. It builds the rolling 7-day Insurgency Report
and writes ``snapshot.json`` and ``snapshot.bin`` to ``--out``. It is also how the
committed demo fixture is regenerated: ``--out ./frontend/public/snapshots/latest
--offline --fresh --date 2026-11-14``.

A run goes through these steps, in order:

1. Read the previous report, ``snapshot.json`` in ``--out`` (skipped with ``--fresh``).
   An invalid file, or one dated after ``--date``, exits with code 4 before anything
   else runs.
2. Preflight the Strands agent on Amazon Bedrock. The agent is mandatory, even with
   ``--offline``: a missing SDK, missing AWS credentials, or no access to the model exits
   with code 2 before any feed is read.
3. Read the articles: the live news RSS feeds, or the curated incidents in
   ``pipeline/fixtures/curated_incidents.json`` with ``--offline``. An article whose URL
   is already in the previous report never reaches the agent: its stored strike is
   carried over (a fully curated row is rebuilt from the curated data instead).
4. Extract a dossier for each new article with the agent. Locally a failed extraction
   discards the article at once (no retries); a non-incident is skipped.
5. Assemble the report: drop strikes published more than ``--max-age-days`` days before
   the report date, renumber ids ``1..N`` (carried strikes first), and apply the discard
   threshold.
6. Write ``snapshot.json`` and ``snapshot.bin`` to ``--out`` and print the counts.
7. Only with ``--summary``: write ``summary.md`` to ``--out``, the weekly Markdown summary
   of the report, as the Summarize stage does in the cloud (``pipeline/summarize.py``,
   Claude Opus 4.6 by default: ``--summary-model``, else ``SUMMARY_MODEL_ID``). It is one
   model call, none for a report without strikes, and runs for a rejected batch too. A
   failed summary prints a warning, writes no ``summary.md`` and leaves the exit code
   unchanged: the report is already written. ``--summary`` is refused when ``--out`` is a
   folder named ``latest``, since a summary under ``latest/`` goes stale.

The CLI writes only those files. It never touches ``manifest.json``, the dated archive
folders or the Rebellion Timeline: production writes them (Assemble and Summarize), and
``cd frontend && npm run sync-snapshots`` refreshes the committed copy of the archive.

Exit codes:

    0  the day's batch was accepted and the report was written
    2  the extraction agent is unavailable (no feed read, nothing written)
    3  more than 20% of the day's new articles were discarded: the new strikes were not
       added, but the accumulated report (minus expired strikes) was still written
    4  the previous snapshot.json in --out is invalid or dated after --date
       (checked before the preflight; nothing written)

Examples:
    python -m pipeline.cli --out ./sample --offline      # curated real incidents
    python -m pipeline.cli --out ./sample                # live RSS from news outlets
    python -m pipeline.cli --out ./sample --fresh        # ignore the existing snapshot
    python -m pipeline.cli --out ./sample --summary      # also write summary.md
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .agent_extract import DEFAULT_MODEL_ID, AgentUnavailable
from .models import InsurgencyReport
from .sources import PER_FEED_LIMIT
from .summarize import (
    DEFAULT_SUMMARY_MODEL_ID,
    SUMMARY_FILENAME,
    StrandsSummarizer,
    Summarizer,
    generate_summary,
)
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


def _write_summary(
    report: InsurgencyReport,
    out: Path,
    *,
    accepted: bool,
    summarizer: Summarizer | None,
    model_id: str,
    region: str | None,
) -> None:
    """Write ``summary.md`` to ``out`` (step 7); a failure only prints a warning."""
    summarizer = summarizer or StrandsSummarizer(model_id=model_id, region=region)
    try:
        text = generate_summary(report, summarizer, accepted=accepted)
    except Exception as exc:  # noqa: BLE001 - a failed summary never fails the run
        print(
            f"[cli] summary failed ({type(exc).__name__}: {exc}); "
            f"the report was written without {SUMMARY_FILENAME}",
            file=sys.stderr,
        )
        return
    path = out / SUMMARY_FILENAME
    path.write_text(text, encoding="utf-8")
    print(f"  summary     : {path} ({len(text)} characters, {model_id})")


def main(
    argv: list[str] | None = None, *, summarizer: Summarizer | None = None, **run_kwargs
) -> int:
    """Run the CLI and return its exit code (see the module docstring).

    ``argv`` defaults to ``sys.argv[1:]``. ``summarizer`` replaces the Bedrock summarizer
    of ``--summary``. ``run_kwargs`` are forwarded to ``transform.run``; tests use them to
    inject ``extractor`` and ``ready_check``.
    """
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="Generate the rolling 7-day Insurgency Report snapshot (JSON + binary) "
        "of real cyberattacks reported by recognized news outlets. Requires the Strands "
        "agent on Amazon Bedrock (AWS credentials + model access), even with --offline. "
        "Writes only snapshot.json and snapshot.bin in --out, plus summary.md with "
        "--summary.",
        epilog="exit codes: 0 batch accepted; 2 extraction agent unavailable; 3 batch "
        "rejected (more than 20% discarded), report still written without the new "
        "strikes; 4 previous snapshot.json invalid or dated after --date. A failed "
        "--summary prints a warning and leaves the exit code unchanged.",
    )
    parser.add_argument(
        "--out",
        default="./sample",
        help="directory for snapshot.json and snapshot.bin; the snapshot.json already "
        "there is the previous report unless --fresh (default: ./sample)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use the committed curated incidents (pipeline/fixtures/curated_incidents.json) "
        "instead of live news RSS feeds; the agent preflight still runs",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="ignore the existing snapshot.json in --out instead of accumulating onto it",
    )
    parser.add_argument(
        "--date",
        help="report date YYYY-MM-DD (default: today, UTC); without --fresh it must not "
        "be earlier than the date of the previous report",
    )
    parser.add_argument(
        "--limit", type=int, help="cap the total number of articles read (default: no cap)"
    )
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
        help="Bedrock model id for the extraction agent (default: AGENT_MODEL_ID, "
        f"else {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--agent-region",
        help="AWS region for the agent (default: AGENT_REGION, else the AWS environment)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help=f"also write {SUMMARY_FILENAME} in --out: the weekly Markdown summary of the "
        "report by Claude on Bedrock (one model call, none for an empty report); refused "
        "when --out is a folder named latest",
    )
    parser.add_argument(
        "--summary-model",
        help="Bedrock model id for --summary (default: SUMMARY_MODEL_ID, else "
        f"{DEFAULT_SUMMARY_MODEL_ID}); the region is --agent-region",
    )
    args = parser.parse_args(argv)
    if args.summary_model and not args.summary:
        parser.error("--summary-model needs --summary")
    if args.summary and Path(args.out).resolve().name == "latest":
        parser.error(
            f"--summary would write {SUMMARY_FILENAME} under latest/, which never holds "
            "one (it would go stale); pick another --out"
        )

    # Step 1: the previous report and the date order are checked before the preflight.
    report_date = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    try:
        previous = None if args.fresh else read_previous(args.out)
        check_report_order(previous, report_date)
    except PreviousSnapshotInvalid as exc:
        print(f"[cli] {exc}; nothing written (use --fresh to start over)", file=sys.stderr)
        return EXIT_PREVIOUS_INVALID

    # Steps 2-5: preflight, fetch, extract and assemble (transform.run).
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

    # Step 6: write the two artifacts and print the counts.
    report = outcome.report
    json_path, bin_path = write_artifacts(report, args.out)

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

    # Step 7 (--summary only): summary.md next to the report.
    if args.summary:
        _write_summary(
            report,
            Path(args.out),
            accepted=outcome.accepted,
            summarizer=summarizer,
            model_id=args.summary_model
            or (os.environ.get("SUMMARY_MODEL_ID") or "").strip()
            or DEFAULT_SUMMARY_MODEL_ID,
            region=args.agent_region,
        )
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
