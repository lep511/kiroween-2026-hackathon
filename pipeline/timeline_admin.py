"""Operator commands for the Rebellion Timeline (DynamoDB) and the report manifest.

    python -m pipeline.timeline_admin migrate [--apply [--yes]]
    python -m pipeline.timeline_admin rebuild-manifest [--apply [--yes]]

``migrate`` prepares a table created before the sparse ``runs-by-date`` index: it adds
``kind`` and ``date`` to every run row that lacks them (so the index lists it) and
rebuilds the run row of every published report that has none, from its
``snapshots/{date}/snapshot.json`` (``status: "published"``, ``reconstructed: true``).
It is idempotent.

``rebuild-manifest`` rewrites ``snapshots/manifest.json`` from the timeline (the same
:func:`pipeline.stages.build_manifest` that Assemble uses) and invalidates it on
CloudFront. It never drops a date of the current manifest, never lists a date without a
published snapshot, and refuses to write while a state machine execution is running.

Both commands are read-only unless ``--apply`` is given; ``--apply`` asks for
confirmation unless ``--yes``. Names come from the CloudFormation stack outputs; the stack
is ``--stack``, else ``$STACK_NAME``, else the ``stack_name`` that ``sam deploy`` uses
(``infra/samconfig.toml``), else ``infra-kiro-hackathon``. ``--table`` and ``--bucket``
override the outputs. Exit codes: 0 done (or nothing to do), 1 refused, aborted, or stack
not found, 2 usage error.

``migrate`` reads the run rows with a one-off, filtered Scan. That is an admin-only
operation: no Lambda is allowed to Scan the table.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import stages, transform
from .models import InsurgencyReport

DEFAULT_STACK = "infra-kiro-hackathon"
SAMCONFIG = Path(__file__).resolve().parents[1] / "infra" / "samconfig.toml"
_SNAPSHOT_KEY_RE = re.compile(r"^snapshots/(\d{4}-\d{2}-\d{2})/snapshot\.(json|bin)$")


def default_stack(env: Mapping[str, str] | None = None, samconfig: Path | None = None) -> str:
    """``$STACK_NAME``, else the stack ``sam deploy`` targets, else :data:`DEFAULT_STACK`."""
    env = os.environ if env is None else env
    if env.get("STACK_NAME"):
        return env["STACK_NAME"]
    try:
        with open(samconfig or SAMCONFIG, "rb") as fh:
            name = tomllib.load(fh)["default"]["deploy"]["parameters"]["stack_name"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return DEFAULT_STACK
    return name if isinstance(name, str) and name else DEFAULT_STACK


class Aws:
    """Lazy boto3 clients; ``overrides`` (``{"s3": stub, "table": stub, ...}``) for tests."""

    def __init__(self, region: str | None = None, overrides: dict | None = None) -> None:
        self.region = region
        self.overrides = dict(overrides or {})
        self._cache: dict[str, object] = {}

    def client(self, name: str):
        if name in self.overrides:
            return self.overrides[name]
        if name not in self._cache:
            import boto3

            self._cache[name] = boto3.client(name, region_name=self.region)
        return self._cache[name]

    def table(self, table_name: str):
        if "table" in self.overrides:
            return self.overrides["table"]
        key = f"table:{table_name}"
        if key not in self._cache:
            import boto3

            dynamodb = boto3.resource("dynamodb", region_name=self.region)
            self._cache[key] = dynamodb.Table(table_name)
        return self._cache[key]


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def stack_outputs(aws: Aws, stack: str) -> dict[str, str]:
    try:
        response = aws.client("cloudformation").describe_stacks(StackName=stack)
    except Exception as exc:  # botocore ClientError; boto3 is imported lazily
        code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code")
        if code == "ValidationError":
            raise SystemExit(
                f"[admin] ERROR: stack {stack!r} does not exist; "
                "pass --stack NAME or set STACK_NAME"
            ) from exc
        raise
    outputs = response["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def scan_run_rows(table) -> list[dict]:
    """Every ``TIMELINE#…`` / ``RUN#…`` row (paginated, filtered Scan; admin only)."""
    kwargs = {
        "FilterExpression": "begins_with(pk, :timeline) AND begins_with(sk, :run)",
        "ExpressionAttributeValues": {":timeline": "TIMELINE#", ":run": "RUN#"},
    }
    rows: list[dict] = []
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        last = page.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    # Double-check on the client: only run rows are migrated.
    return [
        r
        for r in rows
        if str(r.get("pk", "")).startswith("TIMELINE#") and str(r.get("sk", "")).startswith("RUN#")
    ]


def published_dates(s3, bucket: str) -> list[str]:
    """Dated report prefixes in S3 that hold both ``snapshot.json`` and ``snapshot.bin``."""
    found: dict[str, set[str]] = {}
    kwargs = {"Bucket": bucket, "Prefix": "snapshots/"}
    while True:
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            match = _SNAPSHOT_KEY_RE.match(obj["Key"])
            if match:
                found.setdefault(match[1], set()).add(match[2])
        token = page.get("NextContinuationToken")
        if not token:
            break
        kwargs["ContinuationToken"] = token
    return sorted(d for d, kinds in found.items() if kinds == {"json", "bin"})


def read_published_report(s3, bucket: str, day: str) -> InsurgencyReport:
    key = f"snapshots/{day}/snapshot.json"
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    report = transform.load_snapshot_json(body)
    if report.report_date.isoformat() != day:
        raise ValueError(f"{key} is dated {report.report_date.isoformat()}, not {day}")
    return report


def _row_date(row: dict) -> str:
    return str(row["sk"]).removeprefix("RUN#")


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


@dataclass
class MigrationAction:
    """``op`` is ``"update"`` (add ``kind``/``date``) or ``"reconstruct"`` (new run row)."""

    op: str
    date: str
    key: dict = field(default_factory=dict)
    item: dict | None = None

    def describe(self) -> str:
        if self.op == "update":
            return f"add index keys {self.date}: kind={stages.RUN_KIND}, date={self.date}"
        total = (self.item or {}).get("total")
        return f"reconstruct    {self.date}: published run row from snapshot.json (total {total})"


def plan_migration(
    run_rows: list[dict],
    s3_dates: list[str],
    read_report: Callable[[str], InsurgencyReport],
) -> list[MigrationAction]:
    """The writes that make every published report a run row in the runs-by-date index."""
    actions: list[MigrationAction] = []
    row_dates = set()
    for row in run_rows:
        day = _row_date(row)
        row_dates.add(day)
        if row.get("kind") != stages.RUN_KIND or row.get("date") != day:
            actions.append(MigrationAction("update", day, key={"pk": row["pk"], "sk": row["sk"]}))
    for day in s3_dates:
        if day in row_dates:
            continue
        report = read_report(day)
        stats = report.stats()
        report_date = date.fromisoformat(day)
        item = {
            "pk": stages._timeline_pk(report_date),
            "sk": stages._run_sk(report_date),
            "kind": stages.RUN_KIND,
            "date": day,
            "status": "published",
            "total": stats["total"],
            "by_severity": stats["by_severity"],
            "generated_at": report.generated_at.isoformat(),
            "reconstructed": True,
        }
        actions.append(
            MigrationAction("reconstruct", day, key={"pk": item["pk"], "sk": item["sk"]}, item=item)
        )
    return sorted(actions, key=lambda a: (a.date, a.op))


def apply_migration(table, actions: list[MigrationAction]) -> None:
    for action in actions:
        if action.op == "update":
            table.update_item(
                Key=action.key,
                UpdateExpression="SET #k = :run, #d = :date",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeNames={"#k": "kind", "#d": "date"},
                ExpressionAttributeValues={":run": stages.RUN_KIND, ":date": action.date},
            )
        else:
            table.put_item(Item=action.item, ConditionExpression="attribute_not_exists(pk)")
        print(f"[migrate] done: {action.describe()}")


def cmd_migrate(args, aws: Aws, confirm: Callable[[str], bool]) -> int:
    names = _resolve(args, aws, need=("table", "bucket"))
    table = aws.table(names["table"])
    s3 = aws.client("s3")
    rows = scan_run_rows(table)
    dates = published_dates(s3, names["bucket"])
    print(f"[migrate] table:  {names['table']}")
    print(f"[migrate] bucket: {names['bucket']}")
    print(f"[migrate] run rows: {', '.join(sorted(_row_date(r) for r in rows)) or 'none'}")
    print(f"[migrate] published reports: {', '.join(dates) or 'none'}")
    actions = plan_migration(rows, dates, lambda d: read_published_report(s3, names["bucket"], d))
    if not actions:
        print("[migrate] nothing to migrate")
        return 0
    for action in actions:
        print(f"[migrate] plan: {action.describe()}")
    if not args.apply:
        print("[migrate] read-only: nothing written (use --apply to write)")
        return 0
    if not args.yes and not confirm(f"write {len(actions)} change(s) to {names['table']}?"):
        print("[migrate] aborted: nothing written")
        return 1
    apply_migration(table, actions)
    return 0


# ---------------------------------------------------------------------------
# rebuild-manifest
# ---------------------------------------------------------------------------


def _running_executions(aws: Aws, state_machine_arn: str) -> int:
    response = aws.client("stepfunctions").list_executions(
        stateMachineArn=state_machine_arn, statusFilter="RUNNING"
    )
    return len(response.get("executions", []))


def _distribution_id(aws: Aws, domain: str) -> str | None:
    cloudfront = aws.client("cloudfront")
    kwargs: dict = {}
    while True:
        listing = cloudfront.list_distributions(**kwargs)["DistributionList"]
        for dist in listing.get("Items", []):
            if dist["DomainName"] == domain:
                return dist["Id"]
        if not listing.get("IsTruncated"):
            return None
        kwargs["Marker"] = listing["NextMarker"]


def cmd_rebuild_manifest(args, aws: Aws, confirm: Callable[[str], bool]) -> int:
    names = _resolve(args, aws, need=("table", "bucket", "state_machine", "cdn"))
    s3 = aws.client("s3")
    storage = stages.S3Storage(names["bucket"], client=s3)
    timeline = stages.DynamoTimeline(names["table"], table=aws.table(names["table"]))

    current = stages._read_manifest(storage)
    current_dates = stages._manifest_dates(current)
    runs = timeline.list_runs()
    manifest, kept = stages.build_manifest(runs, current_dates)
    published = set(published_dates(s3, names["bucket"]))
    added = [d for d in manifest["dates"] if d not in current_dates]
    dropped = [d for d in current_dates if d not in manifest["dates"]]
    unpublished = [d for d in manifest["dates"] if d not in published]

    print(f"[manifest] bucket:  {names['bucket']}")
    print(f"[manifest] current: {', '.join(current_dates) or 'none'}")
    print(f"[manifest] target:  {', '.join(manifest['dates']) or 'none'}")
    print(f"[manifest] added:   {', '.join(added) or 'none'}")
    print(f"[manifest] kept without a timeline row: {', '.join(kept) or 'none'}")
    for run in manifest["runs"]:
        print(f"[manifest] run {run['date']}: {run['status']}, {run['total']} strike(s)")
    if dropped:  # build_manifest keeps every current date; never write if that breaks
        print(f"[manifest] ERROR: the target would drop {', '.join(dropped)}; refusing to write")
        return 1
    if unpublished:
        print(
            f"[manifest] ERROR: {', '.join(unpublished)} has no published snapshot; "
            "refusing to write"
        )
        return 1
    if manifest == current:
        print("[manifest] the production manifest is already up to date")
        return 0
    if not args.apply:
        print("[manifest] read-only: nothing written (use --apply to write)")
        return 0

    running = _running_executions(aws, names["state_machine"])
    if running:
        print(f"[manifest] ERROR: {running} state machine execution(s) running; retry later")
        return 1
    distribution = _distribution_id(aws, names["cdn"])
    if distribution is None:
        print(f"[manifest] ERROR: no CloudFront distribution for {names['cdn']}")
        return 1
    if not args.yes and not confirm(
        f"write s3://{names['bucket']}/{stages.MANIFEST_KEY} and invalidate it?"
    ):
        print("[manifest] aborted: nothing written")
        return 1

    stages._put_manifest(storage, manifest)
    print(f"[manifest] wrote s3://{names['bucket']}/{stages.MANIFEST_KEY}")
    invalidation = aws.client("cloudfront").create_invalidation(
        DistributionId=distribution,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": [f"/{stages.MANIFEST_KEY}"]},
            "CallerReference": f"rebuild-manifest-{time.time_ns()}",
        },
    )
    print(
        f"[manifest] CloudFront invalidation {invalidation['Invalidation']['Id']} "
        f"on {distribution} (/{stages.MANIFEST_KEY})"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_OUTPUTS = {
    "table": "TimelineTableName",
    "bucket": "SnapshotBucketName",
    "state_machine": "StateMachineArn",
    "cdn": "CdnDomain",
}


def _resolve(args, aws: Aws, need: tuple[str, ...]) -> dict[str, str]:
    names = {"table": args.table, "bucket": args.bucket}
    missing = [n for n in need if not names.get(n)]
    if missing:
        outputs = stack_outputs(aws, args.stack)
        for name in missing:
            value = outputs.get(_OUTPUTS[name])
            if not value:
                raise SystemExit(f"stack {args.stack} has no {_OUTPUTS[name]} output")
            names[name] = value
    return {n: names[n] for n in need}


def _ask(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def main(
    argv: list[str] | None = None,
    *,
    aws: Aws | None = None,
    confirm: Callable[[str], bool] = _ask,
) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.timeline_admin",
        description="Operator commands for the Rebellion Timeline and the report manifest.",
    )
    stack = default_stack()
    parser.add_argument("--stack", default=stack, help=f"CloudFormation stack (default: {stack})")
    parser.add_argument("--region", default=None, help="AWS region (default: environment)")
    parser.add_argument("--table", default=None, help="timeline table (default: stack output)")
    parser.add_argument("--bucket", default=None, help="snapshot bucket (default: stack output)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("migrate", "add kind/date to run rows and rebuild missing run rows"),
        ("rebuild-manifest", "rewrite snapshots/manifest.json from the timeline"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--apply", action="store_true", help="write (default: read-only)")
        cmd.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)
    if args.yes and not args.apply:
        parser.error("--yes only applies with --apply")

    aws = aws or Aws(region=args.region)
    if args.command == "migrate":
        return cmd_migrate(args, aws, confirm)
    return cmd_rebuild_manifest(args, aws, confirm)


if __name__ == "__main__":
    sys.exit(main())
