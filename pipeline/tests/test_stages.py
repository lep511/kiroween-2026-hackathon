"""Step Functions stage handler tests, fully in memory.

``InMemoryStorage`` / ``InMemoryTimeline`` stand in for S3 / DynamoDB, a stub
``ready_check`` for the agent preflight, and a stub extractor for the Strands/Bedrock
agent. No test touches AWS, Bedrock, or the network.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from pipeline import binary, handler, stages, transform
from pipeline.agent_extract import AgentUnavailable, DossierValidationError, NotAnIncident
from pipeline.models import InsurgencyReport, Severity, Strike, Witness
from pipeline.sources import PER_FEED_LIMIT, RawArticle
from pipeline.stages import InMemoryStorage, InMemoryTimeline

REPORT_DATE = date(2026, 11, 14)
EXECUTION = "exec-0001"
ARTICLE_PREFIX = f"staging/{REPORT_DATE.isoformat()}/{EXECUTION}/articles"


def _article(i: int) -> RawArticle:
    return RawArticle(
        witness="thehackernews",
        title=f"Hackers breach company {i}",
        summary=f"Company {i} confirmed a breach.",
        url=f"https://thehackernews.com/2026/11/hackers-breach-company-{i}.html",
        published=REPORT_DATE,
    )


def _dossier() -> dict:
    return {
        "attack_type": "ransomware",
        "severity": "siege",
        "summary": "Agent summary of the incident.",
        "data_affected": "Agent data hit",
        "impact": "Agent fallout",
        "prevention": "Agent ward",
        "location": "Agent ground zero",
        "country": "DE",
        "origin_country": None,
    }


class StubExtractor:
    def __init__(
        self, fail_titles: set[str] | None = None, non_incidents: set[str] | None = None
    ) -> None:
        self.fail_titles = fail_titles or set()
        self.non_incidents = non_incidents or set()
        self.calls = 0

    def extract(self, article, **kwargs) -> dict:
        self.calls += 1
        if article.title in self.fail_titles:
            raise DossierValidationError(f"stub failure for {article.title}")
        if article.title in self.non_incidents:
            raise NotAnIncident(f"stub verdict for {article.title}")
        return _dossier()


def _fetcher(n: int):
    calls: list[dict] = []

    def fetch(report_date, **kwargs):
        calls.append({"report_date": report_date, **kwargs})
        return [_article(i) for i in range(1, n + 1)]

    fetch.calls = calls
    return fetch


def _stage(storage: InMemoryStorage, n: int) -> list[dict]:
    out = stages.fetch(
        {"report_date": REPORT_DATE.isoformat(), "execution": EXECUTION},
        storage=storage,
        fetcher=_fetcher(n),
    )
    return out["items"]


def _snapshot_keys(storage: InMemoryStorage) -> set[str]:
    return {k for k in storage.objects if k.startswith("snapshots/")}


def _stored(i: int, published: date, url: str | None = None) -> Strike:
    """A strike as stored in a previously published snapshot.json."""
    return Strike(
        id=100 + i,
        lat=10.0 + i,
        lon=20.0 + i,
        origin_lat=10.0 + i,
        origin_lon=20.0 + i,
        severity=Severity.BREACH,
        witness=Witness.NYT,
        country="US",
        published=published,
        title=f"Stored strike {i}",
        location="Stored ground zero",
        data_affected="Stored data hit",
        impact="Stored fallout",
        prevention="Stored ward",
        summary="Stored summary.",
        url=url or f"https://www.nytimes.com/2026/11/01/us/stored-{i}.html",
        attack_type="data-breach",
    )


def _seed_latest(storage: InMemoryStorage, *strikes: Strike) -> None:
    report = InsurgencyReport(report_date=REPORT_DATE - timedelta(days=1), strikes=list(strikes))
    storage.put(
        "snapshots/latest/snapshot.json",
        transform.encode_json(report).encode("utf-8"),
        "application/json",
        "max-age=300",
    )


def _assemble(storage, timeline, results, *, backfill=False):
    return stages.assemble(
        {
            "report_date": "2026-11-14",
            "execution": EXECUTION,
            "backfill": backfill,
            "results": results,
        },
        storage=storage,
        timeline=timeline,
    )


def _latest_strikes(storage: InMemoryStorage) -> list[dict]:
    return json.loads(storage.get("snapshots/latest/snapshot.json"))["strikes"]


# ---- End to end ------------------------------------------------------------


def test_stages_end_to_end_publish_the_report():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    extractor = StubExtractor()

    pre = stages.preflight(
        {"report_date": REPORT_DATE.isoformat()}, ready_check=lambda m, r: "stub-model"
    )
    assert pre["model_id"] == "stub-model"
    assert pre["report_date"] == "2026-11-14"
    assert pre["window_start"] == "2026-11-07"
    assert pre["window_end"] == "2026-11-14"

    fetched = stages.fetch(
        {
            "report_date": pre["report_date"],
            "window_start": pre["window_start"],
            "window_end": pre["window_end"],
            "backfill": False,
            "execution": EXECUTION,
        },
        storage=storage,
        fetcher=_fetcher(4),
    )
    assert fetched["report_date"] == "2026-11-14"
    assert fetched["window_start"] == "2026-11-07"
    assert fetched["window_end"] == "2026-11-14"
    assert fetched["execution"] == EXECUTION
    assert [i["key"] for i in fetched["items"]] == [
        f"{ARTICLE_PREFIX}/{n}.json" for n in range(1, 5)
    ]

    results = [
        stages.extract(
            {
                **item,
                "model_id": pre["model_id"],
                "window_start": pre["window_start"],
                "window_end": pre["window_end"],
            },
            storage=storage,
            extractor=extractor,
        )
        for item in fetched["items"]
    ]
    assert extractor.calls == 4
    assert all(r["status"] == "ok" for r in results)
    assert results[0]["dossier_key"] == (f"staging/2026-11-14/{EXECUTION}/dossiers/1.json")

    out = stages.assemble(
        {
            "report_date": "2026-11-14",
            "execution": EXECUTION,
            "backfill": False,
            "results": results,
        },
        storage=storage,
        timeline=timeline,
    )
    assert out["published"] is True
    assert out["accepted"] is True
    assert out["total"] == 4
    assert (out["new"], out["carried"], out["expired"]) == (4, 0, 0)
    assert (out["fetched"], out["discarded"], out["skipped"]) == (4, 0, 0)
    assert out["by_severity"]["siege"] == 4

    assert _snapshot_keys(storage) == {
        "snapshots/2026-11-14/snapshot.json",
        "snapshots/2026-11-14/snapshot.bin",
        "snapshots/latest/snapshot.json",
        "snapshots/latest/snapshot.bin",
        "snapshots/manifest.json",
    }
    body, content_type, cache = storage.objects["snapshots/latest/snapshot.json"]
    assert (content_type, cache) == ("application/json", "max-age=300")
    doc = json.loads(body)
    assert doc["date"] == "2026-11-14"
    assert [s["id"] for s in doc["strikes"]] == [1, 2, 3, 4]

    bin_body, bin_type, _ = storage.objects["snapshots/latest/snapshot.bin"]
    assert bin_type == "application/octet-stream"
    decoded = binary.decode(bin_body)
    assert [s.id for s in decoded.strikes] == [1, 2, 3, 4]
    assert storage.get("snapshots/2026-11-14/snapshot.bin") == bin_body

    run_items = [i for i in timeline.items if i["pk"].startswith("TIMELINE#")]
    [row] = run_items
    assert row["pk"] == "TIMELINE#2026-11"
    assert row["sk"] == "RUN#2026-11-14"
    assert row["status"] == "published"
    assert row["total"] == 4
    assert (row["new"], row["carried"], row["expired"], row["fetched"]) == (4, 0, 0, 4)
    country_items = [i for i in timeline.items if i["pk"].startswith("COUNTRY#")]
    assert len(country_items) >= 1
    assert sum(c["strikes"] for c in country_items) == 4
    latest = next(i for i in timeline.items if i["pk"] == "LATEST")
    assert latest == {"pk": "LATEST", "sk": "RUN", "date": "2026-11-14", "total": 4}


def test_assemble_publishes_when_discards_stay_within_threshold():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    items = _stage(storage, 5)
    extractor = StubExtractor(fail_titles={"Hackers breach company 2"})
    results = []
    for item in items:
        try:
            results.append(stages.extract(item, storage=storage, extractor=extractor))
        except DossierValidationError:
            results.append({"key": item["key"], "status": "discarded"})

    # 1/5 = 20% is not strictly greater than the threshold: publish.
    out = stages.assemble(
        {"report_date": "2026-11-14", "execution": EXECUTION, "results": results},
        storage=storage,
        timeline=timeline,
    )
    assert out["published"] is True
    assert out["total"] == 4
    assert out["discarded"] == 1
    run_row = next(i for i in timeline.items if i["pk"].startswith("TIMELINE#"))
    assert run_row["status"] == "published"
    assert run_row["discarded"] == 1


# ---- Individual stages -----------------------------------------------------


def test_preflight_propagates_agent_unavailable():
    def failing(model_id, region):
        raise AgentUnavailable("no credentials")

    with pytest.raises(AgentUnavailable):
        stages.preflight({}, ready_check=failing)


def test_preflight_passes_env_model_and_region(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("AGENT_REGION", "us-west-2")
    seen = []
    out = stages.preflight({}, ready_check=lambda m, r: seen.append((m, r)) or m)
    assert seen == [("global.anthropic.claude-sonnet-4-6", "us-west-2")]
    assert out["model_id"] == "global.anthropic.claude-sonnet-4-6"
    assert date.fromisoformat(out["report_date"])


def test_fetch_passes_per_feed_limit_and_offline(monkeypatch):
    monkeypatch.setenv("PER_FEED_LIMIT", "7")
    monkeypatch.setenv("OFFLINE", "1")
    fetcher = _fetcher(2)
    stages.fetch(
        {"report_date": "2026-11-14", "execution": EXECUTION},
        storage=InMemoryStorage(),
        fetcher=fetcher,
    )
    [call] = fetcher.calls
    assert call == {
        "report_date": REPORT_DATE,
        "offline": True,
        "per_feed_limit": 7,
        "known_urls": frozenset(),
    }


def test_fetch_excludes_articles_already_in_the_latest_report(monkeypatch):
    storage = InMemoryStorage()
    _seed_latest(storage, _stored(1, REPORT_DATE, url=_article(2).url))
    monkeypatch.setattr(transform, "fetch_all", lambda **kw: [_article(i) for i in (1, 2, 3)])
    out = stages.fetch({"report_date": "2026-11-14", "execution": EXECUTION}, storage=storage)
    staged = [RawArticle.from_json(json.loads(storage.get(i["key"]))) for i in out["items"]]
    assert [a.url for a in staged] == [_article(1).url, _article(3).url]
    assert [i["key"] for i in out["items"]] == [f"{ARTICLE_PREFIX}/{n}.json" for n in (1, 2)]


def _seed_ahead(storage: InMemoryStorage) -> bytes:
    ahead = InsurgencyReport(
        report_date=REPORT_DATE + timedelta(days=1), strikes=[_stored(1, REPORT_DATE)]
    )
    body = transform.encode_json(ahead).encode("utf-8")
    storage.put("snapshots/latest/snapshot.json", body, "application/json", "max-age=300")
    return body


def test_fetch_refuses_a_latest_report_newer_than_the_report_date():
    storage = InMemoryStorage()
    _seed_ahead(storage)
    fetcher = _fetcher(2)
    with pytest.raises(transform.PreviousSnapshotAhead):
        stages.fetch(
            {"report_date": "2026-11-14", "execution": EXECUTION},
            storage=storage,
            fetcher=fetcher,
        )
    assert fetcher.calls == []
    assert not any(k.startswith("staging/") for k in storage.objects)


def test_assemble_never_moves_latest_back_in_time():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    body = _seed_ahead(storage)
    with pytest.raises(transform.PreviousSnapshotAhead):
        _assemble(storage, timeline, [])
    assert _snapshot_keys(storage) == {"snapshots/latest/snapshot.json"}
    assert storage.get("snapshots/latest/snapshot.json") == body
    assert timeline.items == []


def test_fetch_with_everything_known_stages_nothing(monkeypatch):
    storage = InMemoryStorage()
    _seed_latest(storage, _stored(1, REPORT_DATE, url=_article(1).url))
    monkeypatch.setattr(transform, "fetch_all", lambda **kw: [_article(1)])
    out = stages.fetch({"report_date": "2026-11-14", "execution": EXECUTION}, storage=storage)
    assert out["items"] == []


def test_fetch_stages_round_trippable_articles():
    storage = InMemoryStorage()
    items = _stage(storage, 2)
    staged = RawArticle.from_json(json.loads(storage.get(items[1]["key"])))
    assert staged == _article(2)
    assert storage.objects[items[0]["key"]][1] == "application/json"


@pytest.mark.parametrize("execution", ["", "../escape", "a/b", "x" * 81])
def test_fetch_rejects_unsafe_execution_names(execution):
    with pytest.raises(ValueError):
        stages.fetch(
            {"report_date": "2026-11-14", "execution": execution},
            storage=InMemoryStorage(),
            fetcher=_fetcher(1),
        )


def test_extract_propagates_errors_and_writes_no_dossier():
    storage = InMemoryStorage()
    [item] = _stage(storage, 1)
    extractor = StubExtractor(fail_titles={"Hackers breach company 1"})
    with pytest.raises(DossierValidationError):
        stages.extract(item, storage=storage, extractor=extractor)
    assert extractor.calls == 1
    assert not any("/dossiers/" in k for k in storage.objects)


@pytest.mark.parametrize(
    "key",
    [
        "snapshots/latest/snapshot.json",
        "staging/2026-11-14/exec/dossiers/1.json",
        "staging/2026-11-14/exec/articles/../../x.json",
        "staging/2026-11-14/exec/articles/0.json",
    ],
)
def test_extract_rejects_keys_outside_staging(key):
    with pytest.raises(ValueError):
        stages.extract({"key": key}, storage=InMemoryStorage(), extractor=StubExtractor())


def test_assemble_merges_carried_and_new_strikes_with_consistent_ids():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    _seed_latest(
        storage,
        _stored(1, REPORT_DATE - timedelta(days=3)),
        _stored(2, REPORT_DATE - timedelta(days=31)),
    )
    items = _stage(storage, 2)
    results = [stages.extract(i, storage=storage, extractor=StubExtractor()) for i in items]
    out = _assemble(storage, timeline, results)
    assert out["accepted"] is True
    assert (out["total"], out["new"], out["carried"], out["expired"]) == (3, 2, 1, 1)

    strikes = _latest_strikes(storage)
    assert [s["id"] for s in strikes] == [1, 2, 3]
    assert [s["title"] for s in strikes] == [
        "Stored strike 1",
        "Hackers breach company 1",
        "Hackers breach company 2",
    ]
    # The carried strike keeps its stored coordinates.
    assert (strikes[0]["lat"], strikes[0]["lon"]) == (11.0, 21.0)
    decoded = binary.decode(storage.get("snapshots/latest/snapshot.bin"))
    assert [s.id for s in decoded.strikes] == [1, 2, 3]
    assert [round(s.lat, 4) for s in decoded.strikes] == [s["lat"] for s in strikes]
    assert storage.get("snapshots/2026-11-14/snapshot.json") == storage.get(
        "snapshots/latest/snapshot.json"
    )


def test_assemble_with_zero_results_publishes_the_accumulated_set():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    _seed_latest(storage, _stored(1, REPORT_DATE - timedelta(days=2)))
    out = _assemble(storage, timeline, [])
    assert out["published"] is True
    assert out["accepted"] is True
    assert (out["total"], out["carried"], out["fetched"]) == (1, 1, 0)
    assert _snapshot_keys(storage) == {
        "snapshots/2026-11-14/snapshot.json",
        "snapshots/2026-11-14/snapshot.bin",
        "snapshots/latest/snapshot.json",
        "snapshots/latest/snapshot.bin",
        "snapshots/manifest.json",
    }
    assert [(s["id"], s["title"]) for s in _latest_strikes(storage)] == [(1, "Stored strike 1")]
    run_items = [i for i in timeline.items if i["pk"].startswith("TIMELINE#")]
    assert [r["status"] for r in run_items] == ["published"]
    assert any(i["pk"].startswith("COUNTRY#") for i in timeline.items)
    assert any(i["pk"] == "LATEST" for i in timeline.items)


def test_assemble_first_run_with_zero_results_publishes_an_empty_report():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    out = _assemble(storage, timeline, [])
    assert (out["published"], out["accepted"], out["total"]) == (True, True, 0)
    assert _latest_strikes(storage) == []


def test_rejected_batch_publishes_the_cleaned_set_and_records_rejected():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    _seed_latest(
        storage,
        _stored(1, REPORT_DATE - timedelta(days=5)),
        _stored(2, REPORT_DATE - timedelta(days=40)),
    )
    items = _stage(storage, 4)
    results = [stages.extract(items[0], storage=storage, extractor=StubExtractor())]
    results += [{"key": i["key"], "status": "discarded", "error": "X"} for i in items[1:]]

    out = _assemble(storage, timeline, results)
    assert out == {
        "published": True,
        "accepted": False,
        "report_date": "2026-11-14",
        "total": 1,
        "by_severity": {"tremor": 0, "breach": 1, "siege": 0, "dominion": 0},
        "new": 0,
        "carried": 1,
        "expired": 1,
        "fetched": 4,
        "discarded": 3,
        "skipped": 0,
    }
    assert [(s["id"], s["title"]) for s in _latest_strikes(storage)] == [(1, "Stored strike 1")]
    assert binary.decode(storage.get("snapshots/latest/snapshot.bin")).strikes[0].id == 1

    run_items = [i for i in timeline.items if i["pk"].startswith("TIMELINE#")]
    [row] = run_items
    assert (row["pk"], row["sk"], row["status"]) == (
        "TIMELINE#2026-11",
        "RUN#2026-11-14",
        "rejected",
    )
    assert (row["discarded"], row["fetched"], row["total"]) == (3, 4, 1)
    assert not any(i["pk"] == "LATEST" for i in timeline.items)


def test_assemble_fails_on_an_invalid_latest_snapshot():
    storage = InMemoryStorage()
    storage.put("snapshots/latest/snapshot.json", b"{broken", "application/json")
    with pytest.raises(transform.PreviousSnapshotInvalid):
        _assemble(storage, InMemoryTimeline(), [])
    assert storage.get("snapshots/latest/snapshot.json") == b"{broken"
    assert "snapshots/2026-11-14/snapshot.json" not in storage.objects


def test_extract_skips_a_non_incident_without_raising():
    storage = InMemoryStorage()
    [item] = _stage(storage, 1)
    extractor = StubExtractor(non_incidents={"Hackers breach company 1"})
    out = stages.extract(item, storage=storage, extractor=extractor)
    assert out == {"key": item["key"], "status": "skipped"}
    assert not any("/dossiers/" in k for k in storage.objects)


def test_assemble_leaves_skipped_items_out_of_the_threshold():
    storage, timeline = InMemoryStorage(), InMemoryTimeline()
    items = _stage(storage, 5)
    extractor = StubExtractor(non_incidents={f"Hackers breach company {i}" for i in (1, 2, 3)})
    results = [stages.extract(i, storage=storage, extractor=extractor) for i in items]
    out = stages.assemble(
        {"report_date": "2026-11-14", "execution": EXECUTION, "results": results},
        storage=storage,
        timeline=timeline,
    )
    assert out["published"] is True
    assert (out["total"], out["discarded"], out["skipped"]) == (2, 0, 3)
    run_row = next(i for i in timeline.items if i["pk"].startswith("TIMELINE#"))
    assert run_row["skipped"] == 3


def test_rejected_rerun_never_replaces_a_published_day():
    timeline = InMemoryTimeline()
    published = {
        "pk": "TIMELINE#2026-11",
        "sk": "RUN#2026-11-14",
        "status": "published",
        "total": 4,
    }
    timeline.record(published)
    timeline.record({"pk": "TIMELINE#2026-11", "sk": "RUN#2026-11-14", "status": "rejected"})
    assert timeline.items == [published]
    # A later published rerun does replace the row, and other days are independent.
    timeline.record({**published, "total": 5})
    timeline.record({"pk": "TIMELINE#2026-11", "sk": "RUN#2026-11-15", "status": "rejected"})
    assert [(r["sk"], r["status"], r.get("total")) for r in timeline.items] == [
        ("RUN#2026-11-14", "published", 5),
        ("RUN#2026-11-15", "rejected", None),
    ]


def test_assemble_rejects_results_from_another_execution():
    storage = InMemoryStorage()
    items = _stage(storage, 1)
    with pytest.raises(ValueError):
        stages.assemble(
            {
                "report_date": "2026-11-14",
                "execution": "other-exec",
                "results": [{"key": items[0]["key"], "status": "discarded"}],
            },
            storage=storage,
            timeline=InMemoryTimeline(),
        )


# ---- Environment parsing and backends -------------------------------------


def test_per_feed_limit_env_valid_value(monkeypatch):
    monkeypatch.setenv("PER_FEED_LIMIT", "10")
    assert stages.positive_int_env("PER_FEED_LIMIT", PER_FEED_LIMIT) == 10


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "", "  ", "2.5"])
def test_per_feed_limit_env_invalid_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv("PER_FEED_LIMIT", raw)
    assert stages.positive_int_env("PER_FEED_LIMIT", PER_FEED_LIMIT) == 25


def test_per_feed_limit_env_unset_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("PER_FEED_LIMIT", raising=False)
    assert stages.positive_int_env("PER_FEED_LIMIT", PER_FEED_LIMIT) == 25


class _StubS3:
    def __init__(self) -> None:
        self.puts: list[dict] = []
        self.store: dict[str, bytes] = {}
        self.missing_code = "NoSuchKey"

    def put_object(self, **kwargs) -> None:
        self.puts.append(kwargs)
        self.store[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 keyword names
        if Key not in self.store:
            exc = RuntimeError("stub ClientError")
            exc.response = {"Error": {"Code": self.missing_code}}
            raise exc
        body = self.store[Key]

        class _Body:
            def read(self_inner):
                return body

        return {"Body": _Body()}


class _StubTable:
    def __init__(self, fail_code: str | None = None) -> None:
        self.items: list[dict] = []
        self.kwargs: list[dict] = []
        self.fail_code = fail_code

    def put_item(self, Item, **kwargs):  # noqa: N803 — boto3 keyword name
        self.kwargs.append(kwargs)
        if self.fail_code:
            exc = RuntimeError("stub ClientError")
            exc.response = {"Error": {"Code": self.fail_code}}
            raise exc
        self.items.append(Item)


def test_s3_storage_uses_bucket_content_type_and_cache_control():
    client = _StubS3()
    s3 = stages.S3Storage("bucket-1", client=client)
    s3.put("snapshots/latest/snapshot.bin", b"\x01", "application/octet-stream", "max-age=300")
    s3.put("staging/x.json", b"{}", "application/json")
    assert client.puts[0] == {
        "Bucket": "bucket-1",
        "Key": "snapshots/latest/snapshot.bin",
        "Body": b"\x01",
        "ContentType": "application/octet-stream",
        "CacheControl": "max-age=300",
    }
    assert "CacheControl" not in client.puts[1]
    assert s3.get("staging/x.json") == b"{}"


@pytest.mark.parametrize("code", ["NoSuchKey", "404"])
def test_s3_storage_get_optional_returns_none_for_a_missing_key(code):
    client = _StubS3()
    client.missing_code = code
    s3 = stages.S3Storage("bucket-1", client=client)
    assert s3.get_optional("snapshots/latest/snapshot.json") is None
    s3.put("snapshots/latest/snapshot.json", b"{}", "application/json")
    assert s3.get_optional("snapshots/latest/snapshot.json") == b"{}"


def test_s3_storage_get_optional_reraises_other_errors():
    client = _StubS3()
    client.missing_code = "AccessDenied"
    with pytest.raises(RuntimeError):
        stages.S3Storage("bucket-1", client=client).get_optional("snapshots/latest/x")


def test_in_memory_storage_get_optional():
    storage = InMemoryStorage()
    assert storage.get_optional("missing") is None
    storage.put("k", b"v", "text/plain")
    assert storage.get_optional("k") == b"v"


def test_dynamo_timeline_puts_items():
    table = _StubTable()
    stages.DynamoTimeline("timeline", table=table).record({"pk": "rebellion"})
    assert table.items == [{"pk": "rebellion"}]
    assert table.kwargs == [{}]  # published / other rows: unconditional put


def test_dynamo_timeline_rejected_row_is_conditional():
    table = _StubTable()
    row = {"pk": "TIMELINE#2026-11", "sk": "RUN#2026-11-14", "status": "rejected"}
    stages.DynamoTimeline("timeline", table=table).record(row)
    [kwargs] = table.kwargs
    assert kwargs["ConditionExpression"] == "attribute_not_exists(sk) OR #s <> :published"
    assert kwargs["ExpressionAttributeNames"] == {"#s": "status"}
    assert kwargs["ExpressionAttributeValues"] == {":published": "published"}


def test_dynamo_timeline_ignores_a_failed_condition_only():
    row = {"pk": "TIMELINE#2026-11", "sk": "RUN#2026-11-14", "status": "rejected"}
    table = _StubTable(fail_code="ConditionalCheckFailedException")
    stages.DynamoTimeline("timeline", table=table).record(row)  # swallowed
    with pytest.raises(RuntimeError):
        stages.DynamoTimeline("t", table=_StubTable(fail_code="AccessDenied")).record(row)


def test_default_storage_requires_bucket(monkeypatch):
    monkeypatch.delenv("SNAPSHOT_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        stages.extract({"key": f"{ARTICLE_PREFIX}/1.json"}, extractor=StubExtractor())


def test_handler_module_aliases_the_stages():
    assert handler.preflight is stages.preflight
    assert handler.fetch is stages.fetch
    assert handler.extract is stages.extract
    assert handler.assemble is stages.assemble
    assert not hasattr(handler, "run")
