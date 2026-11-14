"""AWS Lambda entry point (invoked daily by EventBridge).

Fetches live news RSS, builds today's Insurgency Report of Machine Strikes, writes
snapshot.json + snapshot.bin to S3, and appends a summary row to the Rebellion Timeline
table in DynamoDB. Environment variables:

    SNAPSHOT_BUCKET   S3 bucket for snapshots (required in cloud)
    TIMELINE_TABLE    DynamoDB table name (optional)
    OFFLINE           if "1", use curated incidents instead of live feeds (optional)
    USE_AGENT         if "1", enrich incidents with a Strands/Bedrock agent (optional)
    AGENT_MODEL_ID    Bedrock model id for the agent (optional; default Claude Opus 4.8)
    AGENT_REGION      AWS region for the agent (optional; AWS environment otherwise)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from . import binary
from .transform import encode_json, run


def _publish_s3(bucket: str, report, json_body: str, bin_body: bytes) -> None:
    import boto3  # imported lazily so local/offline runs need no AWS SDK

    s3 = boto3.client("s3")
    date_key = report.report_date.isoformat()
    for key in (f"snapshots/{date_key}/snapshot.json", "snapshots/latest/snapshot.json"):
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json_body.encode("utf-8"),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
    for key in (f"snapshots/{date_key}/snapshot.bin", "snapshots/latest/snapshot.bin"):
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=bin_body,
            ContentType="application/octet-stream",
            CacheControl="max-age=300",
        )


def _record_timeline(table_name: str, report) -> None:
    import boto3

    table = boto3.resource("dynamodb").Table(table_name)
    stats = report.stats()
    table.put_item(
        Item={
            "pk": "rebellion",
            "date": report.report_date.isoformat(),
            "total": stats["total"],
            "by_severity": stats["by_severity"],
            "generated_at": datetime.now(UTC).isoformat(),
        }
    )


def handler(event: dict | None = None, context: object | None = None) -> dict:
    bucket = os.environ.get("SNAPSHOT_BUCKET")
    table_name = os.environ.get("TIMELINE_TABLE")
    offline = os.environ.get("OFFLINE") == "1"
    use_agent = os.environ.get("USE_AGENT") == "1"
    agent_model = os.environ.get("AGENT_MODEL_ID")
    agent_region = os.environ.get("AGENT_REGION")

    report = run(
        offline=offline,
        use_agent=use_agent,
        agent_model=agent_model,
        agent_region=agent_region,
    )
    json_body = encode_json(report)
    bin_body = binary.encode(report)

    if bucket:
        _publish_s3(bucket, report, json_body, bin_body)
    if table_name:
        _record_timeline(table_name, report)

    stats = report.stats()
    print(f"[handler] {report.report_date} -> {stats['total']} machine strikes reported")
    return {
        "date": report.report_date.isoformat(),
        "total": stats["total"],
        "by_severity": stats["by_severity"],
        "bytes": len(bin_body),
    }
