"""Pipeline tests: news ingestion -> mandatory agent extraction -> report.

No heuristic extractor exists and no test calls Bedrock: a counting stub extractor
(``extract(article) -> dict``) stands in for ``agent_extract.StrandsExtractor`` and a stub
``ready_check`` stands in for the agent preflight.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import binary, cli, transform
from pipeline.agent_extract import (
    IMPACT_NOT_DISCLOSED,
    AgentUnavailable,
    DossierValidationError,
    NotAnIncident,
)
from pipeline.extract import REQUIRED_FIELDS, finalize_dossier, needs_agent
from pipeline.models import InsurgencyReport, Severity, Strike, Witness
from pipeline.sources import RawArticle, fetch_all
from pipeline.transform import (
    DISCARD_THRESHOLD,
    RECENCY_WINDOW_DAYS,
    ReportOutcome,
    build_report,
    extract_one,
    run,
    within_window,
)

REPORT_DATE = date(2026, 11, 14)
_FIXTURES = Path(__file__).resolve().parents[2] / "schema" / "fixtures"


def _agent_dossier(**kw) -> dict:
    base = {
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
    base.update(kw)
    return base


class StubExtractor:
    """Counts calls; fails for titles in ``fail_titles``; otherwise returns a dossier."""

    def __init__(self, fail_titles: set[str] | None = None, **dossier) -> None:
        self.fail_titles = fail_titles or set()
        self.dossier = dossier
        self.calls = 0

    def extract(self, article, **kwargs) -> dict:
        self.calls += 1
        if article.title in self.fail_titles:
            raise DossierValidationError(f"stub failure for {article.title}")
        return _agent_dossier(**self.dossier)


class ForbiddenExtractor:
    """An extractor that must never be called."""

    calls = 0

    def extract(self, article, **kwargs) -> dict:  # pragma: no cover - asserting it is unused
        type(self).calls += 1
        raise AssertionError(f"agent called for {article.title!r}")


def _ready(model_id=None, region=None) -> str:
    return model_id or "stub-model"


def _live(n: int, **kw) -> list[RawArticle]:
    """``n`` uncurated live-style articles (the agent must fill every field)."""
    return [
        RawArticle(
            witness="thehackernews",
            title=f"Hackers breach company {i}",
            summary=f"Company {i} confirmed a breach.",
            url=f"https://thehackernews.com/2026/11/hackers-breach-company-{i}.html",
            published=REPORT_DATE,
            **kw,
        )
        for i in range(1, n + 1)
    ]


# ---- Sources ---------------------------------------------------------------


def test_offline_fetch_returns_curated_incidents():
    articles = fetch_all(offline=True)
    assert articles, "offline curated incidents should yield articles"
    witnesses = {a.witness for a in articles}
    # The curated offline set covers these recognized outlets (each with a concrete link).
    assert {"bbc", "nyt", "thehackernews", "hackernoon"} <= witnesses
    assert any("Fridges in French supermarkets" in a.title for a in articles)


def test_every_curated_row_is_fully_pinned():
    # The committed demo snapshot stays reproducible only if no curated row needs the agent.
    for article in fetch_all(offline=True):
        assert not needs_agent(article), article.title


# ---- Precedence & skip guard -----------------------------------------------


def test_curated_overrides_win_field_by_field():
    art = RawArticle(
        witness="nyt",
        title="Hackers breach a city",
        summary="",
        url="https://www.nytimes.com/2026/11/13/us/city-hack.html",
        published=REPORT_DATE,
        overrides={"severity": "tremor", "prevention": "Curated ward", "location": "Curated"},
    )
    stub = StubExtractor()
    dossier = extract_one(art, stub)
    assert stub.calls == 1
    assert dossier["severity"] == "tremor"
    assert dossier["prevention"] == "Curated ward"
    assert dossier["location"] == "Curated"
    # Blanks are filled by the agent.
    assert dossier["attack_type"] == "ransomware"
    assert dossier["summary"] == "Agent summary of the incident."
    assert dossier["country"] == "DE"


def test_partial_curated_row_lets_agent_fill_only_blanks():
    art = RawArticle(
        witness="bbc",
        title="Hackers hit a hospital",
        summary="Curated summary.",
        url="https://www.bbc.com/news/articles/c123hospital",
        published=REPORT_DATE,
        country="FR",
        overrides={"attack_type": "ransomware", "impact": "Curated fallout"},
        curated=True,
    )
    stub = StubExtractor(country="GB", impact="Agent fallout", attack_type="ddos")
    dossier = extract_one(art, stub)
    assert stub.calls == 1
    assert dossier["country"] == "FR"
    assert dossier["summary"] == "Curated summary."
    assert dossier["impact"] == "Curated fallout"
    assert dossier["attack_type"] == "ransomware"
    assert dossier["data_affected"] == "Agent data hit"


def test_fully_curated_article_skips_the_agent():
    art = RawArticle(
        witness="bbc",
        title="Hackers hit a hospital",
        summary="Curated summary.",
        url="https://www.bbc.com/news/articles/c123hospital",
        published=REPORT_DATE,
        country="FR",
        overrides={
            "attack_type": "ransomware",
            "severity": "breach",
            "data_affected": "Records",
            "impact": "Curated fallout",
            "prevention": "Backups",
            "location": "Paris",
        },
        curated=True,
    )
    assert not needs_agent(art)
    dossier = extract_one(art, ForbiddenExtractor())
    assert REQUIRED_FIELDS <= dossier.keys()
    assert dossier["origin_country"] is None


def test_live_summary_is_not_treated_as_curated():
    # A live item's feed summary is raw input for the agent, never verified reporting.
    (art,) = _live(1, country="US")
    stub = StubExtractor()
    dossier = extract_one(art, stub)
    assert dossier["summary"] == "Agent summary of the incident."
    assert dossier["country"] == "DE"


# ---- finalize_dossier validation -------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"location": ""},
        {"attack_type": "unknown"},
        {"severity": "apocalypse"},
        {"country": "ZZ"},
        {"country": "QQ"},
    ],
)
def test_finalize_dossier_rejects_invalid_fields(bad):
    (art,) = _live(1)
    with pytest.raises(DossierValidationError):
        finalize_dossier(art, _agent_dossier(**bad))


def test_finalize_dossier_rejects_missing_fields():
    (art,) = _live(1)
    dossier = _agent_dossier()
    del dossier["prevention"]
    with pytest.raises(DossierValidationError, match="prevention"):
        finalize_dossier(art, dossier)
    with pytest.raises(DossierValidationError):
        finalize_dossier(art, None)


def test_agent_impact_repeating_curated_summary_is_replaced():
    art = RawArticle(
        witness="bbc",
        title="Hackers hit a hospital",
        summary="Hackers encrypted the hospital's systems. Care was delayed.",
        url="https://www.bbc.com/news/articles/c123hospital",
        published=REPORT_DATE,
        curated=True,
    )
    stub = StubExtractor(impact="Hackers encrypted the hospital's systems.")
    assert extract_one(art, stub)["impact"] == IMPACT_NOT_DISCLOSED


def test_curated_impact_is_never_replaced():
    art = RawArticle(
        witness="bbc",
        title="Hackers hit a hospital",
        summary="Hackers encrypted the hospital's systems.",
        url="https://www.bbc.com/news/articles/c123hospital",
        published=REPORT_DATE,
        overrides={"impact": "Hackers encrypted the hospital's systems."},
        curated=True,
    )
    dossier = extract_one(art, StubExtractor())
    assert dossier["impact"] == "Hackers encrypted the hospital's systems."


# ---- Discards and the batch threshold --------------------------------------


def test_build_report_requires_an_extractor():
    with pytest.raises(TypeError):
        build_report(_live(1), None, report_date=REPORT_DATE)


def test_single_failure_is_discarded_and_ids_stay_contiguous():
    articles = _live(10)
    stub = StubExtractor(fail_titles={"Hackers breach company 3"})
    outcome = build_report(articles, stub, report_date=REPORT_DATE)
    assert isinstance(outcome, ReportOutcome)
    assert stub.calls == 10  # one attempt each, no retries
    assert outcome.accepted is True
    assert (outcome.fetched, outcome.discarded, outcome.new) == (10, 1, 9)
    report = outcome.report
    assert len(report.strikes) == 9
    assert [s.id for s in report.strikes] == list(range(1, 10))
    assert "Hackers breach company 3" not in {s.title for s in report.strikes}


def test_three_of_ten_failures_reject_the_batch():
    stub = StubExtractor(fail_titles={f"Hackers breach company {i}" for i in (1, 5, 9)})
    outcome = build_report(_live(10), stub, report_date=REPORT_DATE)
    assert stub.calls == 10
    assert outcome.accepted is False
    assert (outcome.fetched, outcome.discarded, outcome.new) == (10, 3, 0)
    assert outcome.report.strikes == []


def test_two_of_ten_failures_still_publish():
    assert DISCARD_THRESHOLD == 0.20
    stub = StubExtractor(fail_titles={"Hackers breach company 2", "Hackers breach company 7"})
    outcome = build_report(_live(10), stub, report_date=REPORT_DATE)
    assert outcome.accepted is True
    assert [s.id for s in outcome.report.strikes] == list(range(1, 9))


def test_assemble_rejects_strictly_above_threshold():
    articles = _live(5)
    dossier = finalize_dossier(articles[0], _agent_dossier())
    one_of_five = [(a, None if i == 0 else dossier) for i, a in enumerate(articles)]
    outcome = transform.assemble(one_of_five, REPORT_DATE)
    assert outcome.accepted is True  # 20% is fine
    assert len(outcome.report.strikes) == 4
    two_of_five = [(a, None if i < 2 else dossier) for i, a in enumerate(articles)]
    rejected = transform.assemble(two_of_five, REPORT_DATE)
    assert rejected.accepted is False
    assert rejected.report.strikes == []


def test_zero_articles_publish_an_empty_report():
    outcome = transform.assemble([], REPORT_DATE)
    assert outcome.accepted is True
    assert outcome.report.strikes == []
    assert outcome.report.report_date == REPORT_DATE
    assert (outcome.fetched, outcome.discarded, outcome.new) == (0, 0, 0)
    assert build_report([], StubExtractor(), report_date=REPORT_DATE).report.strikes == []


class _VerdictExtractor(StubExtractor):
    """Rejects titles in ``non_incidents`` as the agent's ``is_incident: false``."""

    def __init__(self, non_incidents: set[str], **kw) -> None:
        super().__init__(**kw)
        self.non_incidents = non_incidents

    def extract(self, article, **kwargs) -> dict:
        if article.title in self.non_incidents:
            self.calls += 1
            raise NotAnIncident("stub verdict")
        return super().extract(article, **kwargs)


def test_non_incidents_are_skipped_without_counting_as_discards():
    # 3/10 rejected as non-incidents would reject the batch if they counted as discards.
    stub = _VerdictExtractor({f"Hackers breach company {i}" for i in (1, 5, 9)})
    outcome = build_report(_live(10), stub, report_date=REPORT_DATE)
    assert stub.calls == 10
    assert outcome.accepted is True
    assert outcome.fetched == 7
    assert [s.id for s in outcome.report.strikes] == list(range(1, 8))


def test_only_non_incidents_publish_an_empty_report():
    stub = _VerdictExtractor({f"Hackers breach company {i}" for i in (1, 2)})
    outcome = build_report(_live(2), stub, report_date=REPORT_DATE)
    assert outcome.accepted is True
    assert outcome.fetched == 0
    assert outcome.report.strikes == []


def test_agent_cannot_veto_a_curated_incident():
    [art] = _live(1, curated=True, country="FR")
    with pytest.raises(DossierValidationError):
        extract_one(art, _VerdictExtractor({art.title}))


# ---- End-to-end offline run ------------------------------------------------


def _offline_report(**kw):
    return run(
        offline=True,
        report_date=REPORT_DATE,
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
        **kw,
    ).report


def test_offline_run_makes_zero_agent_calls():
    stub = StubExtractor()
    outcome = run(offline=True, report_date=REPORT_DATE, ready_check=_ready, extractor=stub)
    assert stub.calls == 0
    assert outcome.accepted is True
    report = outcome.report
    assert len(report.strikes) == 5
    assert not any("SolarWinds" in s.title for s in report.strikes)
    assert not any("Fridges" in s.title for s in report.strikes)
    assert [s.id for s in report.strikes] == list(range(1, 6))
    for s in report.strikes:
        assert -90 <= s.lat <= 90 and -180 <= s.lon <= 180
        assert len(s.country) == 2
        assert s.title and s.data_affected and s.impact and s.prevention and s.url


def test_run_preflights_before_fetching(monkeypatch):
    fetched = []
    monkeypatch.setattr(transform, "fetch_all", lambda **kw: fetched.append(kw) or [])

    def failing_ready(*_):
        raise AgentUnavailable("no credentials")

    with pytest.raises(AgentUnavailable):
        run(offline=True, ready_check=failing_ready, extractor=StubExtractor())
    assert fetched == []


def test_bbc_reference_incident_comes_from_curated_reporting():
    # Published 2026-10-12: outside the 7-day window of 2026-11-14, so disable it.
    fridge = next(s for s in _offline_report(max_age_days=0).strikes if "Fridges" in s.title)
    assert fridge.witness is Witness.BBC
    assert fridge.country == "FR"
    assert fridge.severity is Severity.DOMINION
    assert fridge.attack_type == "operational-technology"
    assert "euros" in fridge.impact.lower()


def test_report_is_deterministic():
    r1, r2 = _offline_report(), _offline_report()
    assert [s.to_json() for s in r1.strikes] == [s.to_json() for s in r2.strikes]


def test_stats_sum_matches_total():
    stats = _offline_report().stats()
    assert sum(stats["by_severity"].values()) == stats["total"] == 5


def test_offline_run_reproduces_the_committed_snapshot():
    report = _offline_report()
    assert binary.encode(report) == (_FIXTURES / "snapshot.bin").read_bytes()
    committed = json.loads((_FIXTURES / "snapshot.json").read_text(encoding="utf-8"))
    produced = json.loads(json.dumps(report.to_json()))
    committed.pop("generated_at", None)
    produced.pop("generated_at", None)
    assert produced == committed


def test_offline_rerun_on_its_own_report_is_idempotent():
    # Every curated row is fully pinned, so it is rebuilt (not carried) at zero agent cost.
    first = _offline_report()
    second = _offline_report(previous=first)
    assert binary.encode(second) == binary.encode(first)


# ---- Recency window --------------------------------------------------------


def test_within_window_bounds():
    # Exactly on the edge (7 days before 2026-11-14) is kept; one day older is dropped.
    assert within_window(date(2026, 11, 7), REPORT_DATE, 7) is True
    assert within_window(date(2026, 11, 6), REPORT_DATE, 7) is False
    # Future-dated items are always kept.
    assert within_window(date(2026, 12, 1), REPORT_DATE, 7) is True
    # A disabled filter keeps everything, however old.
    assert within_window(date(2016, 2, 3), REPORT_DATE, 0) is True
    assert within_window(date(2016, 2, 3), REPORT_DATE, None) is True


def test_recency_filter_drops_old_incidents():
    recent = _offline_report()
    assert all(s.published >= date(2026, 11, 7) for s in recent.strikes)
    assert not any("SolarWinds" in s.title for s in recent.strikes)

    # Disabling the window brings the full curated history back (SolarWinds + Fridges).
    full = _offline_report(max_age_days=0)
    assert len(full.strikes) == len(recent.strikes) + 2
    assert any("SolarWinds" in s.title for s in full.strikes)
    assert any("Fridges" in s.title for s in full.strikes)


def test_default_window_is_seven_days():
    assert RECENCY_WINDOW_DAYS == 7


# ---- Rolling accumulation --------------------------------------------------


def _stored(i: int, published: date, url: str | None = None, **kw) -> Strike:
    """A strike as it would be stored in a previous report's snapshot.json."""
    fields = {
        "id": 100 + i,
        "lat": 10.0 + i,
        "lon": 20.0 + i,
        "origin_lat": 30.0 + i,
        "origin_lon": 40.0 + i,
        "severity": Severity.BREACH,
        "witness": Witness.NYT,
        "country": "US",
        "published": published,
        "title": f"Stored strike {i}",
        "location": f"Stored ground zero {i}",
        "data_affected": "Stored data hit",
        "impact": "Stored fallout",
        "prevention": "Stored ward",
        "summary": "Stored summary.",
        "url": url or f"https://www.nytimes.com/2026/10/01/us/stored-{i}.html",
        "attack_type": "data-breach",
    }
    fields.update(kw)
    return Strike(**fields)


def _previous(*strikes: Strike) -> InsurgencyReport:
    return InsurgencyReport(report_date=REPORT_DATE - timedelta(days=1), strikes=list(strikes))


def test_accumulation_keeps_the_window_and_drops_expired_strikes():
    previous = _previous(
        _stored(1, REPORT_DATE - timedelta(days=3)),
        _stored(2, REPORT_DATE - timedelta(days=8)),
        _stored(3, REPORT_DATE - timedelta(days=7)),
    )
    stub = StubExtractor()
    outcome = build_report(_live(1), stub, report_date=REPORT_DATE, previous=previous)
    assert outcome.accepted is True
    assert (outcome.new, outcome.carried, outcome.expired) == (1, 2, 1)
    strikes = outcome.report.strikes
    # Carried strikes come first, then the day's new ones; ids are renumbered 1..N.
    assert [s.title for s in strikes] == [
        "Stored strike 1",
        "Stored strike 3",
        "Hackers breach company 1",
    ]
    assert [s.id for s in strikes] == [1, 2, 3]
    assert outcome.report.report_date == REPORT_DATE


def test_already_processed_url_is_not_sent_to_the_agent_again():
    articles = _live(2)
    stored = _stored(1, REPORT_DATE - timedelta(days=2), url=articles[0].url)
    stub = StubExtractor()
    outcome = build_report(articles, stub, report_date=REPORT_DATE, previous=_previous(stored))
    assert stub.calls == 1  # only the genuinely new article
    assert (outcome.fetched, outcome.new, outcome.carried) == (1, 1, 1)
    reused, fresh = outcome.report.strikes
    # The stored dossier and coordinates are reused untouched; only the id changes.
    assert reused.id == 1
    assert reused.to_json() == {**stored.to_json(), "id": 1}
    assert fresh.id == 2 and fresh.url == articles[1].url


def test_previously_stored_urls_make_zero_agent_calls():
    articles = _live(3)
    previous = _previous(
        *(_stored(i, REPORT_DATE, url=a.url) for i, a in enumerate(articles, start=1))
    )
    stub = StubExtractor()
    outcome = build_report(articles, stub, report_date=REPORT_DATE, previous=previous)
    assert stub.calls == 0
    assert outcome.accepted is True
    assert (outcome.fetched, outcome.new, outcome.carried) == (0, 0, 3)


def test_duplicate_urls_in_one_batch_call_the_agent_once():
    [art] = _live(1)
    stub = StubExtractor()
    outcome = build_report([art, art, art], stub, report_date=REPORT_DATE)
    assert stub.calls == 1
    assert len(outcome.report.strikes) == 1


def test_curated_row_already_stored_is_rebuilt_from_curated_data():
    art = RawArticle(
        witness="bbc",
        title="Hackers hit a hospital",
        summary="Curated summary.",
        url="https://www.bbc.com/news/articles/c123hospital",
        published=REPORT_DATE,
        country="FR",
        overrides={
            "attack_type": "ransomware",
            "severity": "breach",
            "data_affected": "Records",
            "impact": "Edited curated fallout",
            "prevention": "Backups",
            "location": "Paris",
        },
        curated=True,
    )
    stored = _stored(1, REPORT_DATE, url=art.url, impact="Old fallout")
    outcome = build_report(
        [art], ForbiddenExtractor(), report_date=REPORT_DATE, previous=_previous(stored)
    )
    [strike] = outcome.report.strikes
    # A rebuild replaces the stored copy in place: carried, never fetched or new.
    assert (outcome.fetched, outcome.new, outcome.carried) == (0, 0, 1)
    assert strike.impact == "Edited curated fallout"
    assert strike.country == "FR"
    assert strike.id == 1


def _curated(i: int) -> RawArticle:
    return RawArticle(
        witness="bbc",
        title=f"Curated incident {i}",
        summary="Curated summary.",
        url=f"https://www.bbc.com/news/articles/c{i}curated",
        published=REPORT_DATE,
        country="FR",
        overrides={
            "attack_type": "ransomware",
            "severity": "breach",
            "data_affected": "Records",
            "impact": "Curated fallout",
            "prevention": "Backups",
            "location": "Paris",
        },
        curated=True,
    )


def test_curated_rebuilds_keep_their_position_and_do_not_dilute_the_discard_ratio():
    curated = _curated(1)
    previous = _previous(
        _stored(1, REPORT_DATE - timedelta(days=2)),
        _stored(2, REPORT_DATE, url=curated.url),
    )
    # 1 of 4 genuinely new articles fails (25%): counting the rebuilt row would make it
    # 1/5 = 20% and wrongly accept the batch.
    stub = StubExtractor(fail_titles={"Hackers breach company 1"})
    outcome = build_report([curated, *_live(4)], stub, report_date=REPORT_DATE, previous=previous)
    assert stub.calls == 4
    assert outcome.accepted is False
    assert (outcome.fetched, outcome.discarded, outcome.new) == (4, 1, 0)
    assert (outcome.carried, outcome.expired) == (2, 0)
    # The rebuilt row stays in its carried slot, built from the curated data.
    assert [(s.id, s.title) for s in outcome.report.strikes] == [
        (1, "Stored strike 1"),
        (2, "Curated incident 1"),
    ]


def test_offline_rerun_counts_curated_rows_as_carried():
    first = run(
        offline=True, report_date=REPORT_DATE, ready_check=_ready, extractor=ForbiddenExtractor()
    )
    second = run(
        offline=True,
        report_date=REPORT_DATE + timedelta(days=1),
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
        previous=first.report,
    )
    assert (first.fetched, first.new, first.carried) == (5, 5, 0)
    assert second.accepted is True
    assert (second.fetched, second.new, second.discarded) == (0, 0, 0)
    assert second.carried == len(second.report.strikes)


def test_previous_report_dated_after_the_report_date_is_refused():
    previous = InsurgencyReport(
        report_date=REPORT_DATE + timedelta(days=1),
        strikes=[_stored(1, REPORT_DATE)],
    )
    stub = StubExtractor()
    with pytest.raises(transform.PreviousSnapshotAhead):
        build_report(_live(2), stub, report_date=REPORT_DATE, previous=previous)
    assert stub.calls == 0  # refused before any agent call
    with pytest.raises(transform.PreviousSnapshotAhead):
        transform.assemble([], REPORT_DATE, previous=previous)
    assert issubclass(transform.PreviousSnapshotAhead, transform.PreviousSnapshotInvalid)
    # The same date (a rerun) is allowed.
    same_day = InsurgencyReport(report_date=REPORT_DATE, strikes=[_stored(1, REPORT_DATE)])
    assert transform.assemble([], REPORT_DATE, previous=same_day).accepted is True


def test_zero_new_articles_publish_the_accumulated_set():
    previous = _previous(_stored(1, REPORT_DATE - timedelta(days=3)))
    outcome = build_report([], StubExtractor(), report_date=REPORT_DATE, previous=previous)
    assert outcome.accepted is True
    assert [(s.id, s.title) for s in outcome.report.strikes] == [(1, "Stored strike 1")]
    empty = build_report([], StubExtractor(), report_date=REPORT_DATE, previous=_previous())
    assert empty.accepted is True
    assert empty.report.strikes == []


def test_rejected_batch_keeps_carried_strikes_and_drops_expired_ones():
    previous = _previous(
        _stored(1, REPORT_DATE - timedelta(days=5)),
        _stored(2, REPORT_DATE - timedelta(days=45)),
    )
    stub = StubExtractor(fail_titles={"Hackers breach company 1", "Hackers breach company 2"})
    outcome = build_report(_live(5), stub, report_date=REPORT_DATE, previous=previous)
    assert outcome.accepted is False
    assert (outcome.fetched, outcome.discarded, outcome.new) == (5, 2, 0)
    assert (outcome.carried, outcome.expired) == (1, 1)
    [kept] = outcome.report.strikes
    assert (kept.id, kept.title) == (1, "Stored strike 1")


def test_load_snapshot_json_rejects_invalid_content():
    for bad in (b"not json", b"[]", b'{"version": 3}', b'{"date": "2026-11-14"}'):
        with pytest.raises(transform.PreviousSnapshotInvalid):
            transform.load_snapshot_json(bad)
    report = _previous(_stored(1, REPORT_DATE))
    parsed = transform.load_snapshot_json(transform.encode_json(report))
    assert [s.to_json() for s in parsed.strikes] == [s.to_json() for s in report.strikes]


# ---- CLI -------------------------------------------------------------------


@pytest.fixture
def spy_fetch(monkeypatch):
    calls: list[dict] = []
    real = transform.fetch_all

    def spy(**kw):
        calls.append(kw)
        return real(**kw)

    monkeypatch.setattr(transform, "fetch_all", spy)
    return calls


def _read_strikes(out: Path) -> list[dict]:
    return json.loads((out / "snapshot.json").read_text(encoding="utf-8"))["strikes"]


def test_cli_exits_2_when_the_agent_is_unavailable(tmp_path, spy_fetch):
    def failing_ready(*_):
        raise AgentUnavailable("no credentials")

    code = cli.main(["--out", str(tmp_path), "--offline"], ready_check=failing_ready)
    assert code == cli.EXIT_AGENT_UNAVAILABLE == 2
    assert spy_fetch == []
    assert not (tmp_path / "snapshot.json").exists()


def test_cli_exits_3_and_writes_the_cleaned_report_when_the_batch_is_rejected(
    tmp_path, monkeypatch
):
    transform.write_artifacts(
        _previous(
            _stored(1, REPORT_DATE - timedelta(days=5)),
            _stored(2, REPORT_DATE - timedelta(days=40)),
        ),
        tmp_path,
    )
    monkeypatch.setattr(transform, "fetch_all", lambda **kw: _live(5))
    stub = StubExtractor(fail_titles={"Hackers breach company 1", "Hackers breach company 2"})
    code = cli.main(
        ["--out", str(tmp_path), "--date", "2026-11-14"], ready_check=_ready, extractor=stub
    )
    assert code == cli.EXIT_BATCH_REJECTED == 3
    assert [(s["id"], s["title"]) for s in _read_strikes(tmp_path)] == [(1, "Stored strike 1")]
    assert binary.decode((tmp_path / "snapshot.bin").read_bytes()).strikes[0].id == 1


def test_cli_writes_artifacts_on_success(tmp_path, spy_fetch):
    code = cli.main(
        ["--out", str(tmp_path), "--offline", "--date", "2026-11-14"],
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
    )
    assert code == 0
    assert (tmp_path / "snapshot.json").is_file()
    assert (tmp_path / "snapshot.bin").read_bytes() == (_FIXTURES / "snapshot.bin").read_bytes()


def test_cli_accumulates_onto_the_snapshot_in_out(tmp_path, spy_fetch):
    transform.write_artifacts(_previous(_stored(1, REPORT_DATE - timedelta(days=3))), tmp_path)
    code = cli.main(
        ["--out", str(tmp_path), "--offline", "--date", "2026-11-14"],
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
    )
    assert code == 0
    strikes = _read_strikes(tmp_path)
    assert [s["id"] for s in strikes] == list(range(1, 7))
    assert strikes[0]["title"] == "Stored strike 1"
    assert (strikes[0]["lat"], strikes[0]["lon"]) == (11.0, 21.0)


def test_cli_fresh_ignores_the_existing_snapshot(tmp_path, spy_fetch):
    transform.write_artifacts(_previous(_stored(1, REPORT_DATE - timedelta(days=3))), tmp_path)
    code = cli.main(
        ["--out", str(tmp_path), "--offline", "--date", "2026-11-14", "--fresh"],
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
    )
    assert code == 0
    assert (tmp_path / "snapshot.bin").read_bytes() == (_FIXTURES / "snapshot.bin").read_bytes()


def test_cli_exits_4_and_leaves_an_invalid_previous_snapshot_untouched(tmp_path, spy_fetch):
    (tmp_path / "snapshot.json").write_text("{corrupted", encoding="utf-8")
    code = cli.main(
        ["--out", str(tmp_path), "--offline", "--date", "2026-11-14"],
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
    )
    assert code == cli.EXIT_PREVIOUS_INVALID == 4
    assert (tmp_path / "snapshot.json").read_text(encoding="utf-8") == "{corrupted"
    assert not (tmp_path / "snapshot.bin").exists()
    assert spy_fetch == []


def test_cli_exits_4_when_the_previous_snapshot_is_newer_than_the_date(tmp_path, spy_fetch):
    ahead = InsurgencyReport(
        report_date=date(2026, 11, 20), strikes=[_stored(1, date(2026, 11, 19))]
    )
    transform.write_artifacts(ahead, tmp_path)
    before = (tmp_path / "snapshot.json").read_bytes()
    code = cli.main(
        ["--out", str(tmp_path), "--offline", "--date", "2026-11-14"],
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
    )
    assert code == cli.EXIT_PREVIOUS_INVALID == 4
    assert (tmp_path / "snapshot.json").read_bytes() == before
    assert spy_fetch == []


def test_cli_consecutive_runs_expire_a_strike_crossing_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(transform, "fetch_all", lambda **kw: [])
    previous = InsurgencyReport(
        report_date=date(2026, 11, 13),
        strikes=[
            _stored(1, date(2026, 11, 7)),  # exactly 7 days old on 2026-11-14
            _stored(2, date(2026, 11, 10)),
        ],
    )
    transform.write_artifacts(previous, tmp_path)
    args = ["--out", str(tmp_path)]
    kwargs = {"ready_check": _ready, "extractor": ForbiddenExtractor()}

    assert cli.main([*args, "--date", "2026-11-14"], **kwargs) == 0
    assert [s["title"] for s in _read_strikes(tmp_path)] == ["Stored strike 1", "Stored strike 2"]

    assert cli.main([*args, "--date", "2026-11-15"], **kwargs) == 0
    assert [(s["id"], s["title"]) for s in _read_strikes(tmp_path)] == [(1, "Stored strike 2")]


def test_cli_max_age_days_defaults_to_seven(tmp_path, monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(transform, "fetch_all", lambda **kw: seen.append(kw) or [])
    real_build = transform.build_report

    def spy_build(*args, **kwargs):
        seen.append(kwargs)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(transform, "build_report", spy_build)
    code = cli.main(
        ["--out", str(tmp_path), "--date", "2026-11-14"],
        ready_check=_ready,
        extractor=StubExtractor(),
    )
    assert code == 0
    assert seen[-1]["max_age_days"] == 7
    assert _read_strikes(tmp_path) == []


def test_cli_forwards_per_feed_limit(tmp_path, spy_fetch):
    cli.main(
        ["--out", str(tmp_path), "--offline", "--date", "2026-11-14", "--per-feed-limit", "7"],
        ready_check=_ready,
        extractor=ForbiddenExtractor(),
    )
    assert spy_fetch and spy_fetch[0]["per_feed_limit"] == 7


def test_cli_rejects_the_removed_agent_toggle(tmp_path):
    with pytest.raises(SystemExit) as info:
        cli.main(["--out", str(tmp_path), "--use-agent"], ready_check=_ready)
    assert info.value.code == 2
