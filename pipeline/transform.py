"""Transform: news articles -> agent-extracted, skinned InsurgencyReport -> artifacts.

This module is the shared core used by both the local CLI and the Step Functions stage
handlers (``stages.py``), so the exact same snapshot logic runs locally and in the cloud.
The Insurgency Report is a **rolling 7-day window**: each run starts from the previously
published report, adds the day's new strikes, and drops every strike that expired.

* :func:`fetch_articles` — fetch sources, apply the recency window, and (optionally) drop
  articles already in the previous report (:func:`drop_known`), before any agent call.
* :func:`extract_one` — produce one validated dossier (curated > agent); **raises** on
  failure so the orchestrator decides: Step Functions retries, the local CLI discards.
  ``NotAnIncident`` means "skip", never retry or discard.
* :func:`assemble` — merge the previous report's unexpired strikes with the day's new
  ones (left out when too many were discarded), rebuild fully curated stored rows in
  place, renumber ids contiguously, and return a :class:`ReportOutcome`. It never raises
  for an empty day, but refuses a previous report dated after the report date
  (:class:`PreviousSnapshotAhead`), so the latest report never moves back in time.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import binary
from .extract import build_strike, finalize_dossier, needs_agent
from .geolocate import Geolocator
from .models import InsurgencyReport, Strike
from .sources import PER_FEED_LIMIT, RawArticle, fetch_all

# The Insurgency Report is a rolling window of accumulated strikes: a strike published
# more than this many days before the report date is dropped (exactly 7 days old is
# kept, matching ``within_window``). It applies to the live feeds, the curated offline
# set, and the strikes carried over from the previous report. Curated rows are never
# deleted; they simply fall outside a recent report's window.
RECENCY_WINDOW_DAYS = 7

# The day's new strikes are only added if at most this share of the day's new articles
# was discarded (strictly greater rejects the batch). A rejected batch still publishes
# the accumulated report, cleaned of expired strikes. Applies to the cloud and the CLI.
DISCARD_THRESHOLD = 0.20


class PreviousSnapshotInvalid(ValueError):
    """The previous ``snapshot.json`` exists but cannot be read; never overwrite it."""


class PreviousSnapshotAhead(PreviousSnapshotInvalid):
    """The previous report is dated after this run's report date; never move it back."""


def check_report_order(previous: InsurgencyReport | None, report_date: date) -> None:
    """Raise :class:`PreviousSnapshotAhead` if ``previous`` is newer than ``report_date``.

    A backfill or manual run with an older date would otherwise overwrite the latest
    report with an older-dated one that still holds the newer strikes. The same date
    (a rerun) is allowed.
    """
    if previous is not None and previous.report_date > report_date:
        raise PreviousSnapshotAhead(
            f"previous snapshot.json is dated {previous.report_date.isoformat()}, after the "
            f"report date {report_date.isoformat()}; refusing to move the report back in time"
        )


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    """The assembled report plus the counts of one accumulation run.

    ``fetched`` = new (non-skipped) articles handed to assembly; ``accepted`` = the batch
    stayed within :data:`DISCARD_THRESHOLD` (always true for zero articles); ``new`` =
    strikes added from this batch (0 when rejected); ``carried`` = previous strikes kept,
    including fully curated ones rebuilt in place (they are never counted as fetched or
    new); ``expired`` = previous strikes dropped by the window.
    """

    report: InsurgencyReport
    accepted: bool
    fetched: int
    discarded: int
    new: int
    carried: int
    expired: int


def within_window(published: date, report_date: date, max_age_days: int | None) -> bool:
    """True if ``published`` is recent enough (or ``max_age_days`` disables the filter).

    Future-dated items (published on/after the report date) are always kept — they are,
    if anything, the freshest news — so only articles older than the window are dropped.
    """
    if max_age_days is None or max_age_days <= 0:
        return True
    return published >= report_date - timedelta(days=max_age_days)


def filter_recent(
    articles: Sequence[RawArticle], report_date: date, max_age_days: int | None
) -> list[RawArticle]:
    """Keep only articles inside the recency window (logs how many were dropped)."""
    recent = [a for a in articles if within_window(a.published, report_date, max_age_days)]
    dropped = len(articles) - len(recent)
    if dropped:
        print(f"[transform] dropped {dropped} incident(s) older than {max_age_days}d")
    return recent


def drop_known(
    articles: Sequence[RawArticle], known_urls: Iterable[str] | None
) -> list[RawArticle]:
    """Drop already-processed articles and duplicate URLs, before any extraction.

    An article whose ``url`` is in ``known_urls`` (the previous report) is dropped, so its
    stored strike is reused and the agent is never called for it again. A fully curated
    row is the exception: it is rebuilt from the curated data at zero agent cost, so a
    curated edit stays authoritative (curated overrides > agent). Within the batch, the
    first occurrence of a URL wins.

    Only stored strikes are remembered. An article the agent skipped as a non-incident,
    a discarded one, and every article of a rejected batch reach the agent again on the
    next run while they stay in a feed (accepted cost, bounded by feed retention and
    :data:`~pipeline.sources.PER_FEED_LIMIT`; the deterministic filter runs first).
    """
    known = set(known_urls or ())
    seen: set[str] = set()
    kept: list[RawArticle] = []
    reused = duplicates = 0
    for article in articles:
        if article.url in seen:
            duplicates += 1
            continue
        seen.add(article.url)
        if article.url in known and needs_agent(article):
            reused += 1
            continue
        kept.append(article)
    if reused:
        print(f"[transform] reused {reused} already-processed article(s)")
    if duplicates:
        print(f"[transform] dropped {duplicates} duplicate article URL(s)")
    return kept


def fetch_articles(
    report_date: date,
    offline: bool = False,
    limit: int | None = None,
    max_age_days: int | None = RECENCY_WINDOW_DAYS,
    per_feed_limit: int = PER_FEED_LIMIT,
    known_urls: Iterable[str] | None = None,
) -> list[RawArticle]:
    """Fetch every source and keep the new articles that belong in ``report_date``'s report.

    ``known_urls`` (the previous report's strike URLs) are dropped via :func:`drop_known`.
    """
    articles = fetch_all(offline=offline, limit=limit, per_feed_limit=per_feed_limit)
    return drop_known(filter_recent(articles, report_date, max_age_days), known_urls)


def extract_one(article: RawArticle, extractor) -> dict:
    """Return the validated dossier for one article (curated reporting > agent).

    The agent is skipped for a fully curated incident. Raises on any agent or validation
    failure; the caller decides whether to retry or discard. Raises ``NotAnIncident``
    when the agent rejects a live item (the caller skips it). The agent cannot veto a
    curated incident: that verdict is a ``DossierValidationError`` (discard) instead.
    """
    from .agent_extract import DossierValidationError, NotAnIncident

    try:
        agent_dossier = extractor.extract(article) if needs_agent(article) else None
    except NotAnIncident as exc:
        if article.curated:
            raise DossierValidationError(
                f"agent rejected a curated incident as a non-incident: {exc}"
            ) from exc
        raise
    return finalize_dossier(article, agent_dossier)


def assemble(
    results: Sequence[tuple[RawArticle, dict | None]],
    report_date: date,
    previous: InsurgencyReport | None = None,
    max_age_days: int | None = RECENCY_WINDOW_DAYS,
) -> ReportOutcome:
    """Merge ``previous`` with the day's ``(article, dossier-or-None)`` pairs.

    ``None`` means discarded; skipped non-incidents must not be passed in. A pair whose
    URL is already stored in ``previous`` (inside the window) is a fully curated row being
    rebuilt: it replaces its stored copy in place, counts as carried, and never counts
    toward ``fetched``, ``new``, or the discard ratio (a failed rebuild keeps the stored
    copy). Every other pair belongs to the day's batch. If more than
    :data:`DISCARD_THRESHOLD` of the batch was discarded, it is rejected and none of its
    strikes are added. Either way the previous report's strikes inside the window are
    carried over and expired ones are dropped. Carried strikes come first and keep their
    stored coordinates and dossier; only their id changes. Fresh and rebuilt strikes are
    geolocated with their final id, so ``snapshot.json`` and ``snapshot.bin`` share
    contiguous ids 1..N. Never raises for zero articles: the accumulated (possibly empty)
    report is returned. Raises :class:`PreviousSnapshotAhead` if ``previous`` is dated
    after ``report_date``.
    """
    check_report_order(previous, report_date)

    in_window: list[Strike] = []
    expired = 0
    for strike in previous.strikes if previous is not None else []:
        if within_window(strike.published, report_date, max_age_days):
            in_window.append(strike)
        else:
            expired += 1
    if expired:
        print(f"[transform] expired {expired} strike(s) older than {max_age_days}d")
    stored_urls = {strike.url for strike in in_window}

    rebuilt: dict[str, tuple[RawArticle, dict]] = {}
    batch: list[tuple[RawArticle, dict | None]] = []
    for article, dossier in results:
        if article.url not in stored_urls:
            batch.append((article, dossier))
        elif dossier is None:
            print(f"[transform] rebuild failed, keeping the stored strike: {article.url}")
        else:
            rebuilt.setdefault(article.url, (article, dossier))
    if rebuilt:
        print(f"[transform] rebuilt {len(rebuilt)} curated strike(s) in place")

    fetched = len(batch)
    kept = [(a, d) for a, d in batch if d is not None]
    discarded = fetched - len(kept)
    accepted = fetched == 0 or discarded / fetched <= DISCARD_THRESHOLD
    if discarded:
        print(f"[transform] discarded {discarded}/{fetched} article(s) after extraction failures")
    if not accepted:
        print(
            f"[transform] batch rejected: {discarded}/{fetched} discarded exceeds "
            f"{DISCARD_THRESHOLD:.0%}; publishing the accumulated report without the new strikes"
        )
    fresh = kept if accepted else []

    geo = Geolocator()
    strikes: list[Strike] = []
    for idx, strike in enumerate(in_window, start=1):
        if strike.url in rebuilt:
            article, dossier = rebuilt[strike.url]
            strikes.append(build_strike(article, dossier, idx, geo))
        else:
            strikes.append(dataclasses.replace(strike, id=idx))
    strikes += [
        build_strike(article, dossier, idx, geo)
        for idx, (article, dossier) in enumerate(fresh, start=len(strikes) + 1)
    ]
    return ReportOutcome(
        report=InsurgencyReport(report_date=report_date, strikes=strikes),
        accepted=accepted,
        fetched=fetched,
        discarded=discarded,
        new=len(fresh),
        carried=len(in_window),
        expired=expired,
    )


def build_report(
    articles: Sequence[RawArticle],
    extractor,
    report_date: date | None = None,
    max_age_days: int | None = RECENCY_WINDOW_DAYS,
    previous: InsurgencyReport | None = None,
) -> ReportOutcome:
    """Extract and assemble a report locally: one attempt per article, no retries.

    ``extractor`` (an ``agent_extract.StrandsExtractor`` or a test stub) is mandatory.
    Articles already in ``previous`` are dropped before extraction (:func:`drop_known`).
    An article whose extraction fails is discarded immediately; one the agent rejects as
    a non-incident is skipped (it does not count toward the threshold).
    """
    from .agent_extract import NotAnIncident

    if extractor is None:
        raise TypeError("build_report requires an extractor: the agent is mandatory")
    report_date = report_date or datetime.now(UTC).date()
    check_report_order(previous, report_date)  # before any agent call
    known = {s.url for s in previous.strikes} if previous is not None else set()
    results: list[tuple[RawArticle, dict | None]] = []
    for article in drop_known(filter_recent(articles, report_date, max_age_days), known):
        try:
            results.append((article, extract_one(article, extractor)))
        except NotAnIncident:
            print(f"[transform] skipped a non-incident: {article.url}")
        except Exception as exc:  # noqa: BLE001 — discard this article, keep the batch
            print(f"[transform] discarded {article.url}: {exc}")
            results.append((article, None))
    return assemble(results, report_date, previous=previous, max_age_days=max_age_days)


def run(
    offline: bool = False,
    report_date: date | None = None,
    limit: int | None = None,
    max_age_days: int | None = RECENCY_WINDOW_DAYS,
    per_feed_limit: int = PER_FEED_LIMIT,
    agent_model: str | None = None,
    agent_region: str | None = None,
    extractor=None,
    ready_check: Callable[..., str] | None = None,
    previous: InsurgencyReport | None = None,
) -> ReportOutcome:
    """End-to-end local run: preflight the agent -> fetch -> extract -> assemble.

    The agent preflight (``agent_extract.ensure_agent_ready``) always runs first, even
    offline, and raises ``AgentUnavailable`` before any feed is read. ``previous`` is the
    last published report to accumulate onto (``None`` starts a fresh report).
    ``extractor`` and ``ready_check`` may be injected (tests); otherwise a Strands/Bedrock
    extractor is built.
    """
    from .agent_extract import StrandsExtractor, ensure_agent_ready

    check = ready_check or ensure_agent_ready
    model_id = check(agent_model, agent_region)
    if extractor is None:
        extractor = StrandsExtractor(model_id=model_id, region=agent_region)

    report_date = report_date or datetime.now(UTC).date()
    articles = fetch_all(offline=offline, limit=limit, per_feed_limit=per_feed_limit)
    return build_report(
        articles, extractor, report_date=report_date, max_age_days=max_age_days, previous=previous
    )


def load_snapshot_json(data: str | bytes) -> InsurgencyReport:
    """Parse a published ``snapshot.json``; raises :class:`PreviousSnapshotInvalid`."""
    try:
        doc = json.loads(data)
        if not isinstance(doc, dict) or int(doc.get("version", 2)) != 2:
            raise ValueError("not a version 2 Insurgency Report")
        return InsurgencyReport.from_json(doc)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PreviousSnapshotInvalid(f"previous snapshot.json is invalid: {exc}") from exc


def read_previous(out_dir: str | Path) -> InsurgencyReport | None:
    """Read ``out_dir/snapshot.json`` as the previous report (``None`` if it is missing).

    An unreadable or invalid file raises :class:`PreviousSnapshotInvalid` instead of
    being silently replaced, so accumulated strikes are never lost.
    """
    path = Path(out_dir) / "snapshot.json"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PreviousSnapshotInvalid(f"cannot read {path}: {exc}") from exc
    return load_snapshot_json(data)


def write_artifacts(report: InsurgencyReport, out_dir: str | Path) -> tuple[Path, Path]:
    """Write snapshot.json + snapshot.bin to ``out_dir``. Returns both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "snapshot.json"
    bin_path = out / "snapshot.bin"
    json_path.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    bin_path.write_bytes(binary.encode(report))
    return json_path, bin_path


def encode_json(report: InsurgencyReport) -> str:
    return json.dumps(report.to_json(), separators=(",", ":"))
