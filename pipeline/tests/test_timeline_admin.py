"""Tests for ``pipeline.timeline_admin`` with stub boto3 clients (no AWS calls)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pipeline import timeline_admin, transform
from pipeline.models import InsurgencyReport

BUCKET = "bucket-1"
TABLE = "timeline-1"
STATE_MACHINE = "arn:aws:states:us-east-1:111111111111:stateMachine:rebellion"
CDN = "d123.cloudfront.net"
PUBLISHED = ["2026-11-05", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-19"]
WITH_ROWS = ["2026-11-05", "2026-11-16", "2026-11-17", "2026-11-19"]
TOTALS = {"2026-11-05": 26, "2026-11-15": 0, "2026-11-16": 27, "2026-11-17": 36, "2026-11-19": 44}


class _ClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class StubTable:
    """DynamoDB Table resource with the calls the admin commands make."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = [dict(r) for r in rows]
        self.writes: list[tuple[str, dict]] = []

    def _find(self, key: dict) -> dict | None:
        return next((r for r in self.rows if (r["pk"], r["sk"]) == (key["pk"], key["sk"])), None)

    def scan(self, **kwargs):
        assert "begins_with(pk, :timeline)" in kwargs["FilterExpression"]
        # Unfiltered on purpose: the command must filter run rows on the client too.
        start = kwargs.get("ExclusiveStartKey", {}).get("offset", 0)
        page = self.rows[start : start + 3]
        out = {"Items": [dict(r) for r in page]}
        if start + 3 < len(self.rows):
            out["LastEvaluatedKey"] = {"offset": start + 3}
        return out

    def update_item(self, **kwargs):
        self.writes.append(("update", kwargs))
        row = self._find(kwargs["Key"])
        if row is None:
            raise _ClientError("ConditionalCheckFailedException")
        values = kwargs["ExpressionAttributeValues"]
        row["kind"], row["date"] = values[":run"], values[":date"]

    def put_item(self, Item, **kwargs):  # noqa: N803 — boto3 keyword name
        self.writes.append(("put", {"Item": Item, **kwargs}))
        if self._find(Item) is not None:
            raise _ClientError("ConditionalCheckFailedException")
        self.rows.append(dict(Item))

    def query(self, **kwargs):
        assert kwargs["IndexName"] == "runs-by-date"
        items = [
            {k: r[k] for k in ("pk", "sk", "kind", "date", "status", "total") if k in r}
            for r in self.rows
            if r.get("kind") == "RUN" and r.get("date")
        ]
        return {"Items": items}


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


class StubS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.puts: list[dict] = []

    def list_objects_v2(self, **kwargs):
        keys = sorted(k for k in self.objects if k.startswith(kwargs["Prefix"]))
        start = int(kwargs.get("ContinuationToken") or 0)
        out = {"Contents": [{"Key": k} for k in keys[start : start + 4]]}
        if start + 4 < len(keys):
            out["NextContinuationToken"] = str(start + 4)
        return out

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 keyword names
        assert Bucket == BUCKET
        if Key not in self.objects:
            raise _ClientError("NoSuchKey")
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]


class StubStepFunctions:
    def __init__(self, running: int = 0) -> None:
        self.running = running

    def list_executions(self, stateMachineArn, statusFilter):  # noqa: N803
        assert (stateMachineArn, statusFilter) == (STATE_MACHINE, "RUNNING")
        return {"executions": [{"name": f"e{i}"} for i in range(self.running)]}


class StubCloudFront:
    def __init__(self) -> None:
        self.invalidations: list[dict] = []

    def list_distributions(self, **kwargs):
        if "Marker" not in kwargs:
            return {
                "DistributionList": {
                    "Items": [{"Id": "OTHER", "DomainName": "other.cloudfront.net"}],
                    "IsTruncated": True,
                    "NextMarker": "page-2",
                }
            }
        return {"DistributionList": {"Items": [{"Id": "EDIST", "DomainName": CDN}]}}

    def create_invalidation(self, **kwargs):
        self.invalidations.append(kwargs)
        return {"Invalidation": {"Id": "I123"}}


class StubCloudFormation:
    def describe_stacks(self, StackName):  # noqa: N803 — boto3 keyword name
        assert StackName == "infra-kiro-hackathon"
        outputs = {
            "TimelineTableName": TABLE,
            "SnapshotBucketName": BUCKET,
            "StateMachineArn": STATE_MACHINE,
            "CdnDomain": CDN,
        }
        return {
            "Stacks": [
                {"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in outputs.items()]}
            ]
        }


def _snapshot(day: str) -> bytes:
    report = InsurgencyReport(
        report_date=date.fromisoformat(day),
        strikes=[],
        generated_at=datetime(2026, 11, 15, 22, 20, tzinfo=UTC),
    )
    return transform.encode_json(report).encode()


def _production_like():
    """The table and bucket as found in production before the migration."""
    rows = []
    for day in WITH_ROWS:
        rows.append(
            {
                "pk": "TIMELINE#2026-11",
                "sk": f"RUN#{day}",
                "status": "published",
                "total": Decimal(TOTALS[day]),
                "generated_at": f"{day}T13:00:00+00:00",
            }
        )
        rows.append({"pk": "COUNTRY#US", "sk": f"RUN#{day}", "strikes": Decimal(3)})
    rows.append({"pk": "LATEST", "sk": "RUN", "date": "2026-11-19", "total": Decimal(44)})
    objects = {
        "snapshots/latest/snapshot.json": b"{}",
        "snapshots/latest/snapshot.bin": b"",
        "snapshots/2026-11-17/summary.md": b"# summary",
        "snapshots/2026-11-20/snapshot.json": b"{}",  # incomplete: no .bin
        "snapshots/manifest.json": json.dumps({"dates": PUBLISHED}).encode(),
    }
    for day in PUBLISHED:
        objects[f"snapshots/{day}/snapshot.json"] = _snapshot(day)
        objects[f"snapshots/{day}/snapshot.bin"] = b"RBMN"
    return StubTable(rows), StubS3(objects)


def _aws(table, s3, running: int = 0):
    cloudfront = StubCloudFront()
    aws = timeline_admin.Aws(
        overrides={
            "table": table,
            "s3": s3,
            "stepfunctions": StubStepFunctions(running),
            "cloudfront": cloudfront,
            "cloudformation": StubCloudFormation(),
        }
    )
    return aws, cloudfront


def _never(question: str) -> bool:
    raise AssertionError(f"unexpected prompt: {question}")


@pytest.fixture(autouse=True)
def _stack_name(monkeypatch):
    # Keep the tests independent of the developer's infra/samconfig.toml.
    monkeypatch.setenv("STACK_NAME", "infra-kiro-hackathon")


# ---- stack resolution -----------------------------------------------------------


def test_default_stack_prefers_env_then_samconfig(tmp_path):
    samconfig = tmp_path / "samconfig.toml"
    samconfig.write_text(
        'version = 0.1\n[default.deploy.parameters]\nstack_name = "infra-kiro-hackathon-v2"\n'
    )
    assert timeline_admin.default_stack({"STACK_NAME": "mine"}, samconfig) == "mine"
    assert timeline_admin.default_stack({}, samconfig) == "infra-kiro-hackathon-v2"
    assert timeline_admin.default_stack({"STACK_NAME": ""}, samconfig) == "infra-kiro-hackathon-v2"


def test_default_stack_falls_back_without_a_usable_samconfig(tmp_path):
    missing = tmp_path / "missing.toml"
    assert timeline_admin.default_stack({}, missing) == "infra-kiro-hackathon"
    broken = tmp_path / "broken.toml"
    broken.write_text("stack_name = [")
    assert timeline_admin.default_stack({}, broken) == "infra-kiro-hackathon"
    no_stack = tmp_path / "no-stack.toml"
    no_stack.write_text('[default.global.parameters]\nregion = "us-east-1"\n')
    assert timeline_admin.default_stack({}, no_stack) == "infra-kiro-hackathon"


def test_an_unknown_stack_is_a_clear_error_not_a_traceback():
    class _NoStack:
        def describe_stacks(self, StackName):  # noqa: N803 — boto3 keyword name
            raise _ClientError("ValidationError")

    aws = timeline_admin.Aws(overrides={"cloudformation": _NoStack()})
    with pytest.raises(SystemExit) as exc:
        timeline_admin.main(["--stack", "gone", "migrate"], aws=aws, confirm=_never)
    assert "stack 'gone' does not exist" in str(exc.value)
    assert "--stack NAME or set STACK_NAME" in str(exc.value)


# ---- migrate ----------------------------------------------------------------


def test_published_dates_need_both_artifacts():
    _, s3 = _production_like()
    assert timeline_admin.published_dates(s3, BUCKET) == PUBLISHED


def test_migration_plan_for_production_updates_four_rows_and_rebuilds_one():
    table, s3 = _production_like()
    rows = timeline_admin.scan_run_rows(table)
    assert sorted(r["sk"] for r in rows) == [f"RUN#{d}" for d in WITH_ROWS]
    actions = timeline_admin.plan_migration(
        rows,
        timeline_admin.published_dates(s3, BUCKET),
        lambda d: timeline_admin.read_published_report(s3, BUCKET, d),
    )
    assert [(a.op, a.date) for a in actions] == [
        ("update", "2026-11-05"),
        ("reconstruct", "2026-11-15"),
        ("update", "2026-11-16"),
        ("update", "2026-11-17"),
        ("update", "2026-11-19"),
    ]
    rebuilt = actions[1].item
    assert rebuilt == {
        "pk": "TIMELINE#2026-11",
        "sk": "RUN#2026-11-15",
        "kind": "RUN",
        "date": "2026-11-15",
        "status": "published",
        "total": 0,
        "by_severity": {"tremor": 0, "breach": 0, "siege": 0, "dominion": 0},
        "generated_at": "2026-11-15T22:20:00+00:00",
        "reconstructed": True,
    }


def test_migrate_is_read_only_by_default(capsys):
    table, s3 = _production_like()
    aws, _ = _aws(table, s3)
    assert timeline_admin.main(["migrate"], aws=aws, confirm=_never) == 0
    assert table.writes == []
    out = capsys.readouterr().out
    assert "read-only: nothing written" in out
    assert out.count("[migrate] plan:") == 5


def test_migrate_apply_writes_conditionally_and_is_idempotent(capsys):
    table, s3 = _production_like()
    aws, _ = _aws(table, s3)
    assert timeline_admin.main(["migrate", "--apply", "--yes"], aws=aws, confirm=_never) == 0
    updates = [kw for op, kw in table.writes if op == "update"]
    puts = [kw for op, kw in table.writes if op == "put"]
    assert len(updates) == 4 and len(puts) == 1
    for kw in updates:
        assert kw["ConditionExpression"] == "attribute_exists(pk)"
        assert kw["UpdateExpression"] == "SET #k = :run, #d = :date"
        assert kw["ExpressionAttributeNames"] == {"#k": "kind", "#d": "date"}
        assert kw["ExpressionAttributeValues"][":date"] == kw["Key"]["sk"].removeprefix("RUN#")
    assert puts[0]["ConditionExpression"] == "attribute_not_exists(pk)"
    # The sparse index now lists every published report; country and LATEST rows stay out.
    listed = [r["date"] for r in table.query(IndexName="runs-by-date")["Items"]]
    assert sorted(listed) == PUBLISHED
    assert not any("kind" in r for r in table.rows if not r["pk"].startswith("TIMELINE#"))

    table.writes.clear()
    capsys.readouterr()
    assert timeline_admin.main(["migrate", "--apply", "--yes"], aws=aws, confirm=_never) == 0
    assert table.writes == []
    assert "nothing to migrate" in capsys.readouterr().out


def test_migrate_apply_asks_before_writing():
    table, s3 = _production_like()
    aws, _ = _aws(table, s3)
    questions: list[str] = []

    def decline(question: str) -> bool:
        questions.append(question)
        return False

    assert timeline_admin.main(["migrate", "--apply"], aws=aws, confirm=decline) == 1
    assert table.writes == []
    assert questions == [f"write 5 change(s) to {TABLE}?"]
    assert timeline_admin.main(["migrate", "--apply"], aws=aws, confirm=lambda q: True) == 0
    assert len(table.writes) == 5


def test_migrate_refuses_a_snapshot_dated_elsewhere():
    table, s3 = _production_like()
    s3.objects["snapshots/2026-11-15/snapshot.json"] = _snapshot("2026-11-14")
    aws, _ = _aws(table, s3)
    with pytest.raises(ValueError, match="dated 2026-11-14"):
        timeline_admin.main(["migrate"], aws=aws, confirm=_never)


def test_yes_requires_apply():
    with pytest.raises(SystemExit):
        timeline_admin.main(["migrate", "--yes"], aws=timeline_admin.Aws(overrides={}))


# ---- rebuild-manifest ---------------------------------------------------------


def _migrated():
    table, s3 = _production_like()
    timeline_admin.apply_migration(
        table,
        timeline_admin.plan_migration(
            timeline_admin.scan_run_rows(table),
            PUBLISHED,
            lambda d: timeline_admin.read_published_report(s3, BUCKET, d),
        ),
    )
    table.writes.clear()
    return table, s3


def _expected_manifest() -> dict:
    return {
        "dates": PUBLISHED,
        "runs": [{"date": d, "status": "published", "total": TOTALS[d]} for d in PUBLISHED],
    }


def test_rebuild_manifest_is_read_only_by_default(capsys):
    table, s3 = _migrated()
    aws, cloudfront = _aws(table, s3)
    assert timeline_admin.main(["rebuild-manifest"], aws=aws, confirm=_never) == 0
    assert s3.puts == [] and cloudfront.invalidations == []
    out = capsys.readouterr().out
    assert "read-only: nothing written" in out
    assert "run 2026-11-19: published, 44 strike(s)" in out


def test_rebuild_manifest_apply_writes_and_invalidates():
    table, s3 = _migrated()
    aws, cloudfront = _aws(table, s3)
    assert timeline_admin.main(["rebuild-manifest", "--apply", "--yes"], aws=aws) == 0
    [put] = s3.puts
    assert put["Bucket"] == BUCKET
    assert put["Key"] == "snapshots/manifest.json"
    assert (put["ContentType"], put["CacheControl"]) == ("application/json", "max-age=300")
    assert json.loads(put["Body"]) == _expected_manifest()
    [invalidation] = cloudfront.invalidations
    assert invalidation["DistributionId"] == "EDIST"
    assert invalidation["InvalidationBatch"]["Paths"] == {
        "Quantity": 1,
        "Items": ["/snapshots/manifest.json"],
    }
    # A second run has nothing to do.
    assert timeline_admin.main(["rebuild-manifest", "--apply", "--yes"], aws=aws) == 0
    assert len(s3.puts) == 1


def test_rebuild_manifest_refuses_while_an_execution_runs(capsys):
    table, s3 = _migrated()
    aws, cloudfront = _aws(table, s3, running=1)
    assert timeline_admin.main(["rebuild-manifest", "--apply", "--yes"], aws=aws) == 1
    assert s3.puts == [] and cloudfront.invalidations == []
    assert "1 state machine execution(s) running" in capsys.readouterr().out


def test_rebuild_manifest_never_drops_a_date_without_a_row(capsys):
    table, s3 = _production_like()  # not migrated: the index is still empty
    aws, _ = _aws(table, s3)
    assert timeline_admin.main(["rebuild-manifest", "--apply", "--yes"], aws=aws) == 0
    written = json.loads(s3.puts[0]["Body"])
    assert written == {"dates": PUBLISHED, "runs": []}
    assert f"kept without a timeline row: {', '.join(PUBLISHED)}" in capsys.readouterr().out


def test_rebuild_manifest_refuses_a_date_without_a_published_snapshot(capsys):
    table, s3 = _migrated()
    del s3.objects["snapshots/2026-11-16/snapshot.bin"]
    aws, _ = _aws(table, s3)
    assert timeline_admin.main(["rebuild-manifest", "--apply", "--yes"], aws=aws) == 1
    assert s3.puts == []
    assert "2026-11-16 has no published snapshot" in capsys.readouterr().out
