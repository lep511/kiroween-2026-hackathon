"""Tests for the weekly summary (``pipeline.summarize`` and ``stages.summarize``).

A stub summarizer stands in for the Strands agent: no test calls Bedrock.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from pipeline import handler, stages, transform
from pipeline import summarize as summary
from pipeline.models import InsurgencyReport, Severity, Strike, Witness
from pipeline.stages import InMemoryStorage

REPORT_DATE = date(2026, 11, 23)
SNAPSHOT_KEY = "snapshots/2026-11-23/snapshot.json"
SUMMARY_KEY = "snapshots/2026-11-23/summary.md"
TITLE = "# Weekly Cyber Incident Summary (Nov 16-23, 2026)"


def _strike(i: int, severity: Severity = Severity.SIEGE) -> Strike:
    return Strike(
        id=i,
        lat=1.0,
        lon=2.0,
        origin_lat=1.0,
        origin_lon=2.0,
        severity=severity,
        witness=Witness.BLEEPINGCOMPUTER,
        country="US",
        published=date(2026, 11, 20),
        title=f"Vendor {i} breached",
        location=f"Vendor {i} HQ",
        data_affected=f"Customer records {i}",
        impact=f"{i}00 customers",
        prevention=f"Rotate keys {i}",
        summary=f"Attackers breached vendor {i}.",
        url=f"https://www.bleepingcomputer.com/news/security/vendor-{i}-breached/",
        attack_type="data-breach",
    )


def _report(*strikes: Strike) -> InsurgencyReport:
    return InsurgencyReport(report_date=REPORT_DATE, strikes=list(strikes))


def _storage(report: InsurgencyReport) -> InMemoryStorage:
    storage = InMemoryStorage()
    storage.put(
        f"snapshots/{report.report_date.isoformat()}/snapshot.json",
        transform.encode_json(report).encode("utf-8"),
        "application/json",
    )
    return storage


class StubSummarizer:
    def __init__(self, reply: str = f"{TITLE}\n\nThe feed logged **2 incidents**.\n") -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


# ---- Title and window -------------------------------------------------------------


@pytest.mark.parametrize(
    ("report_date", "label"),
    [
        (date(2026, 11, 23), "Nov 16-23, 2026"),
        (date(2026, 11, 19), "Nov 12-19, 2026"),  # matches the committed summaries
        (date(2026, 11, 17), "Nov 10-17, 2026"),
        (date(2026, 11, 4), "Oct 28-Nov 4, 2026"),
        (date(2027, 1, 4), "Dec 28, 2026-Jan 4, 2027"),
    ],
)
def test_window_label(report_date, label):
    assert summary.window_label(report_date) == label
    assert summary.summary_title(report_date) == f"# Weekly Cyber Incident Summary ({label})"


# ---- Prompt -----------------------------------------------------------------------


def test_prompt_carries_the_title_counts_and_dossiers_only():
    prompt = summary.build_prompt(_report(_strike(1), _strike(2, Severity.DOMINION)))
    assert f"Title: {TITLE}" in prompt
    assert "window 2026-11-16 to 2026-11-23" in prompt
    assert "Incidents: 2 (tremor: 0, breach: 0, siege: 1, dominion: 1)" in prompt
    assert "Batch: accepted" in prompt
    dossiers = [json.loads(line) for line in prompt.splitlines() if line.startswith("{")]
    assert [d["title"] for d in dossiers] == ["Vendor 1 breached", "Vendor 2 breached"]
    assert dossiers[1]["severity"] == "dominion"
    assert dossiers[0]["prevention"] == "Rotate keys 1"
    assert set(dossiers[0]) == set(summary._PROMPT_FIELDS)
    assert "bleepingcomputer.com/news" not in prompt  # no URLs, no coordinates
    assert '"lat"' not in prompt


def test_prompt_states_a_rejected_batch():
    prompt = summary.build_prompt(_report(_strike(1)), accepted=False)
    assert "Batch: rejected" in prompt


def test_system_prompt_keeps_the_summary_factual():
    for rule in ("Use only facts present in the incident data", "no fictional framing"):
        assert rule in summary.SYSTEM_PROMPT
    for section in ("## Key takeaways", "## Biggest incidents", "## Common defensive themes"):
        assert section in summary.SYSTEM_PROMPT


# ---- Output validation ------------------------------------------------------------


def test_finalize_pins_the_title_and_strips_a_code_fence():
    raw = "```markdown\n# Some other title\n\nBody text.\n```"
    assert summary.finalize_summary(raw, REPORT_DATE) == f"{TITLE}\n\nBody text.\n"
    assert summary.finalize_summary(f"  {TITLE}\nBody.\n\n\n", REPORT_DATE) == f"{TITLE}\nBody.\n"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "Here is the summary:\n# Title\nBody",
        "## Second-level title\nBody",
        "# Title only",
        "# Title\n\n   \n",
        "# Title\n" + "x" * summary.MAX_SUMMARY_CHARS,
    ],
)
def test_finalize_rejects_unusable_output(raw):
    with pytest.raises(summary.SummaryError):
        summary.finalize_summary(raw, REPORT_DATE)


def test_an_empty_report_never_reaches_the_model():
    stub = StubSummarizer()
    text = summary.generate_summary(_report(), stub)
    assert text == f"{TITLE}\n\nThe feed logged no incidents in this window.\n"
    assert stub.prompts == []


# ---- Strands summarizer -----------------------------------------------------------


class _Result:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason

    def __str__(self) -> str:
        return self.text


def test_strands_summarizer_returns_the_text_and_defaults_to_opus_4_6():
    calls: list[str] = []

    def agent(prompt):
        calls.append(prompt)
        return _Result(f"{TITLE}\nBody\n")

    summarizer = summary.StrandsSummarizer(agent_factory=lambda: agent)
    assert summarizer.model_id == "global.anthropic.claude-opus-4-6-v1"
    assert summarizer("the prompt") == f"{TITLE}\nBody\n"
    assert calls == ["the prompt"]
    assert summary.StrandsSummarizer(model_id="x.anthropic.other").model_id == "x.anthropic.other"


def test_strands_summarizer_rejects_a_truncated_answer():
    summarizer = summary.StrandsSummarizer(
        agent_factory=lambda: lambda prompt: _Result(f"{TITLE}\nBody cut", "max_tokens")
    )
    with pytest.raises(summary.SummaryError, match="max_tokens"):
        summarizer("the prompt")


# ---- Lambda stage -----------------------------------------------------------------


def test_summarize_writes_summary_md_next_to_the_report(monkeypatch):
    monkeypatch.setenv("SUMMARY_MODEL_ID", "global.anthropic.claude-opus-4-6-v1")
    storage = _storage(_report(_strike(1), _strike(2)))
    stub = StubSummarizer()
    out = stages.summarize(
        {"report_date": "2026-11-23", "accepted": True, "total": 2},
        storage=storage,
        summarizer=stub,
    )
    body, content_type, cache = storage.objects[SUMMARY_KEY]
    assert body.decode("utf-8") == f"{TITLE}\n\nThe feed logged **2 incidents**.\n"
    assert (content_type, cache) == ("text/markdown; charset=utf-8", "max-age=300")
    assert out == {
        "summary_key": SUMMARY_KEY,
        "chars": len(body.decode("utf-8")),
        "model_id": "global.anthropic.claude-opus-4-6-v1",
    }
    [prompt] = stub.prompts
    assert "Batch: accepted" in prompt
    # Only the dated summary is written: latest/ never gets one.
    assert set(storage.objects) == {SNAPSHOT_KEY, SUMMARY_KEY}


def test_summarize_reports_the_configured_model(monkeypatch):
    monkeypatch.setenv("SUMMARY_MODEL_ID", "us.anthropic.claude-opus-4-8")
    storage = _storage(_report(_strike(1)))
    out = stages.summarize(
        {"report_date": "2026-11-23"}, storage=storage, summarizer=StubSummarizer()
    )
    assert out["model_id"] == "us.anthropic.claude-opus-4-8"
    monkeypatch.delenv("SUMMARY_MODEL_ID")
    out = stages.summarize(
        {"report_date": "2026-11-23"}, storage=storage, summarizer=StubSummarizer()
    )
    assert out["model_id"] == summary.DEFAULT_SUMMARY_MODEL_ID


def test_summarize_tells_the_model_about_a_rejected_batch():
    storage = _storage(_report(_strike(1)))
    stub = StubSummarizer()
    stages.summarize(
        {"report_date": "2026-11-23", "accepted": False}, storage=storage, summarizer=stub
    )
    assert "Batch: rejected" in stub.prompts[0]


def test_summarize_propagates_a_bad_answer_and_writes_nothing():
    storage = _storage(_report(_strike(1)))
    with pytest.raises(summary.SummaryError):
        stages.summarize(
            {"report_date": "2026-11-23"}, storage=storage, summarizer=StubSummarizer("no title")
        )
    assert SUMMARY_KEY not in storage.objects


def test_summarize_needs_a_published_report_of_that_date():
    with pytest.raises(ValueError, match="report_date"):
        stages.summarize({}, storage=InMemoryStorage(), summarizer=StubSummarizer())
    with pytest.raises(ValueError):
        stages.summarize({"report_date": "../latest"}, storage=InMemoryStorage())
    with pytest.raises(KeyError):  # nothing published for that date
        stages.summarize(
            {"report_date": "2026-11-23"}, storage=InMemoryStorage(), summarizer=StubSummarizer()
        )
    storage = InMemoryStorage()
    other = InsurgencyReport(report_date=date(2026, 11, 19), strikes=[_strike(1)])
    storage.put(SNAPSHOT_KEY, transform.encode_json(other).encode("utf-8"), "application/json")
    with pytest.raises(ValueError, match="dated 2026-11-19"):
        stages.summarize(
            {"report_date": "2026-11-23"}, storage=storage, summarizer=StubSummarizer()
        )


def test_handler_exports_summarize():
    assert handler.summarize is stages.summarize
