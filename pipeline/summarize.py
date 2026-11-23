"""Weekly summary of an Insurgency Report (``summary.md``), written by Claude on Bedrock.

The Summarize stage (:func:`pipeline.stages.summarize`) runs right after Assemble. It reads
the ``snapshot.json`` that Assemble just published, asks a Strands agent on Amazon Bedrock
for a Markdown summary of the report's dossiers, and stores it next to the report as
``snapshots/{date}/summary.md``. The frontend's Summary button shows it.

The summary is factual, like the dossiers: it is built only from the report's data and is
never written in the machine-uprising voice. The model defaults to Claude Opus 4.6
(:data:`DEFAULT_SUMMARY_MODEL_ID`) and is overridden by the ``SUMMARY_MODEL_ID``
environment variable of the Lambda (SAM parameter ``SummaryModelId``).

``strands`` is imported lazily, so importing this module needs no SDK (tests rely on it).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date, timedelta

from .models import InsurgencyReport
from .transform import RECENCY_WINDOW_DAYS

DEFAULT_SUMMARY_MODEL_ID = "global.anthropic.claude-opus-4-6-v1"
SUMMARY_FILENAME = "summary.md"
SUMMARY_CONTENT_TYPE = "text/markdown; charset=utf-8"
# Output budget for one summary (about 1,500 words fit in well under half of it).
SUMMARY_MAX_TOKENS = 8192
# A summary longer than this is treated as a failure, not published.
MAX_SUMMARY_CHARS = 40_000

# The strike fields the model sees. Coordinates, ids for the binary, and URLs add tokens
# without helping the summary.
_PROMPT_FIELDS = (
    "title",
    "witness",
    "published",
    "location",
    "country",
    "attack_type",
    "severity",
    "summary",
    "data_affected",
    "impact",
    "prevention",
)

Summarizer = Callable[[str], str]


class SummaryError(RuntimeError):
    """The model returned no usable summary (empty, untitled, too long, or cut off)."""


def window_label(report_date: date, days: int = RECENCY_WINDOW_DAYS) -> str:
    """The report window as ``Nov 16-23, 2026`` (``Oct 28-Nov 4, 2026`` across months)."""
    start = report_date - timedelta(days=days)
    end = report_date
    if start.year != end.year:
        return f"{start:%b} {start.day}, {start.year}-{end:%b} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start:%b} {start.day}-{end:%b} {end.day}, {end.year}"
    return f"{start:%b} {start.day}-{end.day}, {end.year}"


def summary_title(report_date: date) -> str:
    return f"# Weekly Cyber Incident Summary ({window_label(report_date)})"


SYSTEM_PROMPT = """\
You write the weekly summary of a threat-intelligence feed that maps real cyberattacks \
reported by recognized news outlets. You receive the feed's report for one week: its \
counts and one JSON object per incident (the incident's dossier). Write the summary in \
English, in GitHub-flavored Markdown.

Hard rules:
- Use only facts present in the incident data. Never add incidents, numbers, names, \
CVEs, dates or attributions that the data does not contain. If a detail is missing, \
leave it out.
- Neutral, factual tone in plain English. No hype and no fictional framing.
- Output only the Markdown document: no preamble, no closing remarks, no code fences.

Structure:
1. The first line is exactly the title given in the request.
2. One short paragraph with the counts, for example: The feed logged **44 incidents** \
this week: 6 rated "dominion", 33 "siege" and 5 "breach". These are the feed's own \
severity labels. Leave out tiers with zero incidents. If several entries describe the \
same event (for example the same victim reported by more than one outlet), say so and \
give the approximate number of distinct incidents.
3. If the request says the week's batch was rejected, add one sentence saying that the \
week's newest reports were held back because too many failed processing, so the report \
repeats the incidents that are still within the window.
4. "## Key takeaways": 3 to 5 bullets, each starting with a bold lead-in sentence.
5. "## Biggest incidents": 2 to 4 short paragraphs about the most severe incidents. Each \
starts with the incident name in bold followed by its tier in parentheses, and ends with \
"Recommended defense:" and the incident's prevention.
6. Thematic sections, only those that have material, in this order: "## Supply chain and \
third-party compromises", "## Actively exploited vulnerabilities", "## Ransomware and \
extortion", "## Espionage and state-linked activity", "## Phishing, credential theft and \
malware", "## Other breaches and disruptions", "## Law enforcement wins". Use bullets that \
start with the bold name of the victim, product or campaign. Put each incident in at most \
one section and do not repeat the incidents already covered under Biggest incidents.
7. "## Common defensive themes": a numbered list of 4 to 6 short, concrete defenses drawn \
from the incidents' prevention fields.

Keep the whole summary under 1,500 words.
"""


def build_prompt(report: InsurgencyReport, *, accepted: bool = True) -> str:
    """The request for one report: title, window, counts, verdict, and the dossiers."""
    stats = report.stats()
    counts = ", ".join(f"{tier}: {n}" for tier, n in stats["by_severity"].items())
    start = report.report_date - timedelta(days=RECENCY_WINDOW_DAYS)
    lines = [
        f"Title: {summary_title(report.report_date)}",
        f"Report date: {report.report_date.isoformat()} "
        f"(window {start.isoformat()} to {report.report_date.isoformat()})",
        f"Incidents: {stats['total']} ({counts})",
        "Batch: "
        + (
            "accepted"
            if accepted
            else "rejected (more than 20% of the week's new articles failed processing, "
            "so none of them were added)"
        ),
        "",
        "Incident data (one JSON object per line):",
    ]
    for strike in report.strikes:
        doc = strike.to_json()
        lines.append(json.dumps({k: doc[k] for k in _PROMPT_FIELDS}, ensure_ascii=False))
    return "\n".join(lines)


_FENCE_RE = re.compile(r"^```(?:markdown|md)?[ \t]*\n(?P<body>.*)\n```$", re.DOTALL)


def finalize_summary(text: str, report_date: date) -> str:
    """Validate the model's Markdown and pin its title; raises :class:`SummaryError`."""
    body = (text or "").strip()
    fenced = _FENCE_RE.match(body)
    if fenced:
        body = fenced["body"].strip()
    if not body.startswith("# "):
        raise SummaryError("the summary does not start with a Markdown title")
    if len(body) > MAX_SUMMARY_CHARS:
        raise SummaryError(f"the summary is too long ({len(body)} characters)")
    _, _, rest = body.partition("\n")
    if not rest.strip():
        raise SummaryError("the summary has a title and nothing else")
    return f"{summary_title(report_date)}\n{rest.rstrip()}\n"


def empty_summary(report_date: date) -> str:
    """The summary of a report without incidents (no model call)."""
    return f"{summary_title(report_date)}\n\nThe feed logged no incidents in this window.\n"


def generate_summary(
    report: InsurgencyReport, summarizer: Summarizer, *, accepted: bool = True
) -> str:
    """``summary.md`` for ``report``; an empty report never reaches the model."""
    if not report.strikes:
        return empty_summary(report.report_date)
    raw = summarizer(build_prompt(report, accepted=accepted))
    return finalize_summary(raw, report.report_date)


class StrandsSummarizer:
    """Calls a Strands agent on Bedrock with :data:`SYSTEM_PROMPT` (one call per summary).

    Raises :class:`SummaryError` when the model stops before finishing (for example on
    the output token limit); model and network errors propagate.
    """

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        agent_factory: Callable[[], Callable] | None = None,
    ) -> None:
        self.model_id = model_id or DEFAULT_SUMMARY_MODEL_ID
        self.region = region
        self._agent_factory = agent_factory

    def _agent(self):
        if self._agent_factory is not None:
            return self._agent_factory()
        from strands import Agent
        from strands.models import BedrockModel

        model_kwargs: dict = {"model_id": self.model_id, "max_tokens": SUMMARY_MAX_TOKENS}
        if self.region:
            model_kwargs["region_name"] = self.region
        return Agent(
            model=BedrockModel(**model_kwargs),
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,  # do not stream the whole summary into the logs
        )

    def __call__(self, prompt: str) -> str:
        result = self._agent()(prompt)
        stop = getattr(result, "stop_reason", "end_turn")
        if stop != "end_turn":
            raise SummaryError(f"the model stopped before finishing ({stop})")
        return str(result)
