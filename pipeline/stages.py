"""AWS Step Functions stage handlers for the weekly Insurgency Report.

The state machine (``infra/statemachine/rebellion.asl.json``) runs these Lambda handlers.
The Insurgency Report accumulates a rolling 30-day window on top of the previously
published ``snapshots/latest/snapshot.json``:

1. :func:`preflight` — verify the mandatory Strands/Bedrock agent can run; any
   ``AgentUnavailable`` fails the execution before a single feed is read.
2. :func:`fetch` — fetch the news feeds, drop every article whose URL is already in the
   latest report (it is never staged nor sent to the agent again), and stage one JSON
   object per new article under ``staging/{date}/{execution}/articles/{n}.json``.
3. :func:`extract` — run once per article inside a Map state: extract its dossier and
   stage it under ``.../dossiers/{n}.json``. Exceptions propagate on purpose so the Map
   Retry (3 attempts in total) and Catch (``status: "discarded"``) apply. An item the
   agent rejects as a non-incident returns ``status: "skipped"`` instead.
4. :func:`assemble` — join the Map results (skipped items are left out), merge them with
   the latest report's unexpired strikes, and **always** publish ``snapshot.json`` +
   ``snapshot.bin`` to ``snapshots/{date}/`` and ``snapshots/latest/``. If more than 20%
   of the day's articles were discarded the batch is rejected: its new strikes are left
   out, but the accumulated report is still published without expired strikes. The day
   is recorded in the Rebellion Timeline (``status: "published"`` or ``"rejected"``); a
   rejected rerun never replaces a day already recorded as published.

Neither Fetch nor Assemble accepts a latest report dated after the run's report date
(``transform.PreviousSnapshotAhead`` fails the execution), so a backfill or manual run
with an older date never moves ``snapshots/latest/`` back in time. Overlapping
executions are not serialized: the later Assemble wins and the other execution's new
strikes reappear on a later run while they stay in the feeds. That is accepted for a
daily schedule; avoid starting a manual execution while the scheduled one is running.

Environment variables:

    SNAPSHOT_BUCKET   S3 bucket for staging objects and snapshots (required in cloud)
    TIMELINE_TABLE    DynamoDB table for the Rebellion Timeline (optional)
    OFFLINE           if "1", read the curated incidents instead of live feeds
    PER_FEED_LIMIT    max items kept per news feed (positive int; default 25)
    AGENT_MODEL_ID    Bedrock model id for the agent (default Claude Sonnet 4.6)
    AGENT_REGION      AWS region for the agent (default: the AWS environment)
    BEDROCK_TOKEN_SECRET_ARN  Secrets Manager ARN for the bearer token (optional)

Every handler accepts keyword injections (``storage=``, ``timeline=``, ``extractor=``,
``ready_check=``, ``fetcher=``) so tests run fully in memory, without AWS or Bedrock.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from . import binary, transform
from .models import InsurgencyReport
from .sources import PER_FEED_LIMIT, RawArticle


def _timeline_pk(report_date: date) -> str:
    return f"TIMELINE#{report_date.strftime('%Y-%m')}"


def _run_sk(report_date: date) -> str:
    return f"RUN#{report_date.isoformat()}"


def _country_pk(country: str) -> str:
    return f"COUNTRY#{country}"


LATEST_PK = "LATEST"
LATEST_SK = "RUN"
CACHE_CONTROL = "max-age=300"
LATEST_JSON_KEY = "snapshots/latest/snapshot.json"
MANIFEST_KEY = "snapshots/manifest.json"
_MISSING_KEY_CODES = frozenset({"NoSuchKey", "404"})

# Staging keys are built here and echoed back by Step Functions; anything else is rejected
# so a crafted event cannot make a stage read or write outside its own staging prefix.
_EXECUTION_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ARTICLE_KEY_RE = re.compile(
    r"^staging/(?P<date>\d{4}-\d{2}-\d{2})/(?P<execution>[A-Za-z0-9_-]{1,80})"
    r"/articles/(?P<n>[1-9]\d*)\.json$"
)


# ---------------------------------------------------------------------------
# Storage and Rebellion Timeline backends
# ---------------------------------------------------------------------------


class Storage(Protocol):
    def put(
        self, key: str, body: bytes, content_type: str, cache_control: str | None = None
    ) -> None: ...

    def get(self, key: str) -> bytes: ...

    def get_optional(self, key: str) -> bytes | None: ...


class S3Storage:
    """Object storage on S3 (boto3 is imported lazily, on first use)."""

    def __init__(self, bucket: str, client=None) -> None:
        self.bucket = bucket
        self._client = client

    def _s3(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def put(
        self, key: str, body: bytes, content_type: str, cache_control: str | None = None
    ) -> None:
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": body, "ContentType": content_type}
        if cache_control:
            kwargs["CacheControl"] = cache_control
        self._s3().put_object(**kwargs)

    def get(self, key: str) -> bytes:
        return self._s3().get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def get_optional(self, key: str) -> bytes | None:
        """Like :meth:`get`, but ``None`` when the key does not exist (first run)."""
        try:
            return self.get(key)
        except Exception as exc:  # botocore ClientError; boto3 is imported lazily
            code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code")
            if code in _MISSING_KEY_CODES:
                return None
            raise


class InMemoryStorage:
    """Dict-backed storage for tests; ``objects`` maps key -> (body, content_type, cache)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str | None]] = {}

    def put(
        self, key: str, body: bytes, content_type: str, cache_control: str | None = None
    ) -> None:
        self.objects[key] = (bytes(body), content_type, cache_control)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]

    def get_optional(self, key: str) -> bytes | None:
        entry = self.objects.get(key)
        return entry[0] if entry is not None else None


class Timeline(Protocol):
    def record(self, item: dict) -> None: ...

    def put(self, item: dict) -> None: ...


def _keeps_published_row(existing: dict | None, item: dict) -> bool:
    """True if ``item`` must not replace ``existing``: a rejected rerun never overwrites a
    day already recorded as published."""
    return (
        item.get("status") == "rejected"
        and existing is not None
        and existing.get("status") == "published"
    )


class DynamoTimeline:
    """Single-table Rebellion Timeline in DynamoDB (boto3 imported lazily).

    Entity types (``pk`` / ``sk``):
    - ``TIMELINE#YYYY-MM`` / ``RUN#YYYY-MM-DD`` — run record (one per execution)
    - ``COUNTRY#XX`` / ``RUN#YYYY-MM-DD`` — per-country stats for that run
    - ``LATEST`` / ``RUN`` — pointer to the most recent successful run

    A published run record is always written; a rejected one uses a conditional put so it
    never replaces a day already recorded as published. Country and latest items are
    unconditional (:meth:`put`).
    """

    def __init__(self, table_name: str, table=None) -> None:
        self.table_name = table_name
        self._table = table

    def _get_table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def put(self, item: dict) -> None:
        self._get_table().put_item(Item=item)

    def record(self, item: dict) -> None:
        table = self._get_table()
        if item.get("status") != "rejected":
            table.put_item(Item=item)
            return
        try:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(sk) OR #s <> :published",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":published": "published"},
            )
        except Exception as exc:  # noqa: BLE001 (botocore ClientError; boto3 is lazy)
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code != "ConditionalCheckFailedException":
                raise
            print(f"[timeline] {item.get('sk')} already published; rejected run not recorded")


class InMemoryTimeline:
    """Timeline for tests with the same single-table semantics as DynamoDB."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def _upsert(self, item: dict) -> None:
        key = (item.get("pk"), item.get("sk"))
        for i, existing in enumerate(self.items):
            if (existing.get("pk"), existing.get("sk")) == key:
                self.items[i] = dict(item)
                return
        self.items.append(dict(item))

    def put(self, item: dict) -> None:
        self._upsert(item)

    def record(self, item: dict) -> None:
        key = (item.get("pk"), item.get("sk"))
        for i, existing in enumerate(self.items):
            if (existing.get("pk"), existing.get("sk")) == key:
                if not _keeps_published_row(existing, item):
                    self.items[i] = dict(item)
                return
        self.items.append(dict(item))


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def positive_int_env(name: str, default: int) -> int:
    """Read a positive int from ``name``; missing, empty, invalid, or <= 0 -> ``default``."""
    raw = (os.environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or None


def _default_storage() -> Storage:
    bucket = _env("SNAPSHOT_BUCKET")
    if not bucket:
        raise RuntimeError("SNAPSHOT_BUCKET is not set")
    return S3Storage(bucket)


def _default_timeline() -> Timeline | None:
    table = _env("TIMELINE_TABLE")
    return DynamoTimeline(table) if table else None


def _report_date(value: object) -> date:
    return date.fromisoformat(str(value)) if value else datetime.now(UTC).date()


def _parse_article_key(key: object) -> re.Match:
    match = _ARTICLE_KEY_RE.match(str(key))
    if match is None:
        raise ValueError(f"not a staged article key: {key!r}")
    return match


def _dossier_key(article_key: str) -> str:
    head, _, name = article_key.rpartition("/articles/")
    return f"{head}/dossiers/{name}"


def _put_json(storage: Storage, key: str, payload: dict) -> None:
    storage.put(key, json.dumps(payload).encode("utf-8"), "application/json")


def _get_json(storage: Storage, key: str) -> dict:
    return json.loads(storage.get(key).decode("utf-8"))


def _load_latest(storage: Storage) -> InsurgencyReport | None:
    """The latest published report, or ``None`` before the first run.

    Invalid content raises ``transform.PreviousSnapshotInvalid`` so the execution fails
    instead of overwriting the accumulated report.
    """
    data = storage.get_optional(LATEST_JSON_KEY)
    return transform.load_snapshot_json(data) if data is not None else None


# ---------------------------------------------------------------------------
# Secrets Manager → env var bridge
# ---------------------------------------------------------------------------


def _load_bearer_token() -> None:
    """Read the Bedrock bearer token from Secrets Manager and set it as an env var.

    Skipped when ``BEDROCK_TOKEN_SECRET_ARN`` is not set (local/test runs).
    """
    secret_arn = _env("BEDROCK_TOKEN_SECRET_ARN")
    if not secret_arn or os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        return
    import boto3

    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_arn)
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = resp["SecretString"]


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------


def _compute_window(report_date: date) -> tuple[date, date]:
    """Return (window_start, window_end) for a 7-day rolling window ending on report_date."""
    return report_date - timedelta(days=7), report_date


def preflight(
    event: dict | None = None,
    context: object | None = None,
    *,
    ready_check: Callable[..., str] | None = None,
) -> dict:
    """Fail fast unless the agent can run.

    Returns ``{model_id, report_date, window_start, window_end}``.
    """
    from .agent_extract import ensure_agent_ready

    _load_bearer_token()
    event = event or {}
    check = ready_check or ensure_agent_ready
    model_id = check(_env("AGENT_MODEL_ID"), _env("AGENT_REGION"))
    report_date = _report_date(event.get("report_date"))
    window_start, window_end = _compute_window(report_date)
    # Backfill mode: write only to snapshots/{date}/, never touch
    # snapshots/latest/. Auto-detected when report_date is before today,
    # or forced via {"backfill": true} in the input event.
    today = datetime.now(UTC).date()
    backfill = bool(event.get("backfill")) or report_date < today
    mode = "backfill" if backfill else "current"
    print(
        f"[preflight] agent ready ({model_id}); report date {report_date}; "
        f"window {window_start} to {window_end}; mode {mode}"
    )
    return {
        "model_id": model_id,
        "report_date": report_date.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "backfill": backfill,
    }


def fetch(
    event: dict,
    context: object | None = None,
    *,
    storage: Storage | None = None,
    fetcher: Callable[..., list[RawArticle]] | None = None,
) -> dict:
    """Fetch the feeds and stage each new article.

    Returns ``{items, report_date, window_start, window_end, execution}``.

    Articles whose URL is already in ``snapshots/latest/`` are dropped before staging. A
    latest report dated after ``report_date`` raises ``transform.PreviousSnapshotAhead``
    before any feed is read, so a backfill never moves ``snapshots/latest/`` back in time.
    The date window (window_start, window_end) is received from Preflight; articles
    outside this window are filtered out.
    """
    report_date = _report_date(event.get("report_date"))
    raw_ws = event.get("window_start")
    window_start = (
        date.fromisoformat(raw_ws) if raw_ws else report_date - timedelta(days=7)
    )
    raw_we = event.get("window_end")
    window_end = date.fromisoformat(raw_we) if raw_we else report_date
    execution = str(event.get("execution") or "")
    if not _EXECUTION_RE.match(execution):
        raise ValueError(f"invalid execution name: {execution!r}")
    backfill = bool(event.get("backfill"))
    storage = storage or _default_storage()
    fetch_fn = fetcher or transform.fetch_articles

    if backfill:
        known_urls: frozenset[str] = frozenset()
    else:
        latest = _load_latest(storage)
        transform.check_report_order(latest, report_date)
        known_urls = frozenset(
            s.url for s in latest.strikes
        ) if latest is not None else frozenset()
    articles = fetch_fn(
        report_date,
        offline=_env("OFFLINE") == "1",
        per_feed_limit=positive_int_env("PER_FEED_LIMIT", PER_FEED_LIMIT),
        known_urls=known_urls,
    )
    prefix = f"staging/{report_date.isoformat()}/{execution}/articles"
    items = []
    for n, article in enumerate(articles, start=1):
        key = f"{prefix}/{n}.json"
        _put_json(storage, key, article.to_json())
        items.append({"key": key})
    print(
        f"[fetch] staged {len(items)} article(s) under {prefix}/ "
        f"(window {window_start} to {window_end})"
    )
    return {
        "items": items,
        "report_date": report_date.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "backfill": backfill,
        "execution": execution,
    }


def extract(
    event: dict,
    context: object | None = None,
    *,
    storage: Storage | None = None,
    extractor=None,
) -> dict:
    """Extract one staged article's dossier; returns ``{key, dossier_key, status: "ok"}``.

    Does not catch extraction errors: they propagate so Step Functions retries the
    article and, after the last attempt, the Map Catch marks it ``discarded``. The one
    exception is the agent's ``NotAnIncident`` verdict, which returns
    ``{key, status: "skipped"}`` (no retry, no dossier, not counted as a discard).
    The date window (window_start, window_end) is forwarded to the extractor so the
    agent knows which reporting period to focus on.
    """
    from .agent_extract import NotAnIncident

    _load_bearer_token()
    key = _parse_article_key(event.get("key")).group(0)
    window_start = event.get("window_start")
    window_end = event.get("window_end")
    storage = storage or _default_storage()
    if extractor is None:
        from .agent_extract import DEFAULT_MODEL_ID, StrandsExtractor

        model_id = event.get("model_id") or _env("AGENT_MODEL_ID") or DEFAULT_MODEL_ID
        extractor = StrandsExtractor(model_id=model_id, region=_env("AGENT_REGION"))

    article = RawArticle.from_json(_get_json(storage, key))
    try:
        dossier = transform.extract_one(
            article, extractor,
            window_start=window_start, window_end=window_end,
        )
    except NotAnIncident:
        print(f"[extract] skipped a non-incident: {article.url}")
        return {"key": key, "status": "skipped"}
    dossier_key = _dossier_key(key)
    _put_json(storage, dossier_key, dossier)
    return {"key": key, "dossier_key": dossier_key, "status": "ok"}


def _update_manifest(storage: Storage, date_key: str) -> None:
    """Read the existing manifest, add the new date, and write it back."""
    existing: list[str] = []
    raw = storage.get_optional(MANIFEST_KEY)
    if raw is not None:
        data = json.loads(raw)
        existing = data.get("dates", [])
    dates = sorted(set(existing) | {date_key})
    body = json.dumps({"dates": dates}).encode("utf-8")
    storage.put(MANIFEST_KEY, body, "application/json", CACHE_CONTROL)


def assemble(
    event: dict,
    context: object | None = None,
    *,
    storage: Storage | None = None,
    timeline: Timeline | None = None,
) -> dict:
    """Join the Map results, merge them with the latest report, and always publish.

    Returns ``{published: True, accepted, report_date, total, by_severity, new, carried,
    expired, fetched, discarded, skipped}``; ``accepted`` is false when the day's batch
    was rejected (more than 20% discarded) and its new strikes were left out.
    """
    report_date = _report_date(event.get("report_date"))
    execution = str(event.get("execution") or "")
    storage = storage or _default_storage()
    timeline = timeline if timeline is not None else _default_timeline()

    staged = []
    for result in event.get("results") or []:
        match = _parse_article_key(result.get("key"))
        if match["date"] != report_date.isoformat() or match["execution"] != execution:
            raise ValueError(f"result key outside this execution: {match.group(0)!r}")
        staged.append((int(match["n"]), match.group(0), result))
    staged.sort(key=lambda row: row[0])

    pairs: list[tuple[RawArticle, dict | None]] = []
    skipped = 0
    for _, key, result in staged:
        status = result.get("status")
        if status == "skipped":
            skipped += 1
            continue
        article = RawArticle.from_json(_get_json(storage, key))
        dossier = _get_json(storage, _dossier_key(key)) if status == "ok" else None
        pairs.append((article, dossier))

    backfill = bool(event.get("backfill"))
    generated_at = datetime.now(UTC).isoformat()
    date_key = report_date.isoformat()
    previous = None if backfill else _load_latest(storage)
    outcome = transform.assemble(pairs, report_date, previous=previous)
    report = outcome.report

    json_body = transform.encode_json(report).encode("utf-8")
    bin_body = binary.encode(report)
    json_keys = [f"snapshots/{date_key}/snapshot.json"]
    bin_keys = [f"snapshots/{date_key}/snapshot.bin"]
    if not backfill:
        json_keys.append(LATEST_JSON_KEY)
        bin_keys.append("snapshots/latest/snapshot.bin")
    for key in json_keys:
        storage.put(key, json_body, "application/json", CACHE_CONTROL)
    for key in bin_keys:
        storage.put(key, bin_body, "application/octet-stream", CACHE_CONTROL)

    _update_manifest(storage, date_key)

    stats = report.stats()
    counts = {
        "new": outcome.new,
        "carried": outcome.carried,
        "expired": outcome.expired,
        "fetched": outcome.fetched,
        "discarded": outcome.discarded,
        "skipped": skipped,
    }
    if timeline is not None:
        run_sk = _run_sk(report_date)
        timeline.record(
            {
                "pk": _timeline_pk(report_date),
                "sk": run_sk,
                "status": "published" if outcome.accepted else "rejected",
                "total": stats["total"],
                "by_severity": stats["by_severity"],
                **counts,
                "generated_at": generated_at,
            }
        )
        country_counts: dict[str, dict[str, int]] = {}
        for strike in report.strikes:
            cc = country_counts.setdefault(
                strike.country, {"strikes": 0, "tremor": 0, "breach": 0, "siege": 0, "dominion": 0}
            )
            cc["strikes"] += 1
            cc[strike.severity.label] += 1
        for country, cc in country_counts.items():
            timeline.put(
                {
                    "pk": _country_pk(country),
                    "sk": run_sk,
                    "strikes": cc["strikes"],
                    "by_severity": {k: v for k, v in cc.items() if k != "strikes"},
                }
            )
        if outcome.accepted and not backfill:
            timeline.put(
                {"pk": LATEST_PK, "sk": LATEST_SK, "date": date_key, "total": stats["total"]}
            )
    verdict = "" if outcome.accepted else " (batch rejected: no new strikes added)"
    print(f"[assemble] {date_key} -> {stats['total']} machine strikes reported{verdict}")
    return {
        "published": True,
        "accepted": outcome.accepted,
        "report_date": date_key,
        "total": stats["total"],
        "by_severity": stats["by_severity"],
        **counts,
    }
