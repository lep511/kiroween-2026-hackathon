"""Mandatory LLM extraction via **Strands Agents** (Amazon Bedrock).

The `Strands <https://strandsagents.com>`_ agent is the pipeline's **only** extractor: it
reads one reported cyberattack (headline + reported summary from a named outlet) and
returns a **structured incident dossier** — it classifies the attack, writes a faithful
summary, and completes every dossier field (data hit, fallout, severity, the ward,
ground zero, its country, and attacker origin).

Rules:

* **Mandatory.** Nothing runs without the agent. :func:`ensure_agent_ready` is the
  preflight every entry point (CLI, Step Functions) runs first; it raises
  :class:`AgentUnavailable` when the SDK, AWS credentials, or Bedrock model access are
  missing.
* **Strict.** :meth:`StrandsExtractor.extract` returns a complete, validated dossier or
  raises (:class:`DossierValidationError` or the underlying model error). It never
  silently degrades: the caller decides whether to retry (Step Functions) or discard
  (local CLI). The one non-failure exit is :class:`NotAnIncident`, raised when the agent
  reports ``is_incident: false``: that article is skipped, not discarded.
* **Curated overrides still win.** Hand-verified reporting overrides the agent field by
  field (see ``extract.finalize_dossier``); a fully curated incident skips the agent.
* **Country is always resolved.** The agent must name an ISO-3166 alpha-2 ground-zero
  country that exists in ``geolocate.COUNTRY_CENTROIDS``; placeholders such as ``ZZ``
  are validation errors, so no strike ever lands on Null Island.

``strands``/``pydantic``/``boto3`` are imported inside the functions that use them, so
the module imports cheaply and the tests can inject stub agents and clients.

Reference: https://strandsagents.com/docs/user-guide/ (Agents SDK, structured output).
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable
from functools import lru_cache
from typing import Literal

from .geolocate import COUNTRY_CENTROIDS
from .models import ATTACK_TYPES, Severity

# Severity labels the agent may assign, mirrored from the canonical enum so the two can
# never drift (``tremor`` -> ``breach`` -> ``siege`` -> ``dominion``).
SEVERITY_LABELS: tuple[str, ...] = tuple(s.label for s in Severity)

# Free-text dossier fields the agent must always fill (non-empty after stripping).
TEXT_FIELDS: tuple[str, ...] = ("summary", "data_affected", "impact", "prevention", "location")

# Every key a dossier dict may carry; the same keys a curated ``overrides`` block uses.
DOSSIER_FIELDS: tuple[str, ...] = (
    "attack_type",
    "severity",
    *TEXT_FIELDS,
    "country",
    "origin_country",
)

# Replacement for a fallout line that merely repeats the summary.
IMPACT_NOT_DISCLOSED = "Impact not disclosed."

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
# The agent runs on **Claude Sonnet 4.6** on Amazon Bedrock by default. To use a different
# model, change it in one of three ways (highest precedence first):
#   1. CLI flag:  python -m pipeline.cli --agent-model <bedrock-model-id>
#   2. Env var:   AGENT_MODEL_ID=<bedrock-model-id>   (local or the Lambda / SAM param)
#   3. Edit the DEFAULT_MODEL_ID constant below.
# The value is a Bedrock model / inference-profile id. The global profile routes across
# regions automatically.
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"

# Region the Strands SDK falls back to when neither --agent-region / AGENT_REGION nor the
# AWS environment names one; the preflight uses the same fallback so both agree.
FALLBACK_REGION = "us-west-2"

# Inference-profile id prefixes (cross-region routing) vs. plain foundation-model ids.
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.", "jp.", "au.", "ca.")

# Python modules the agent cannot run without.
REQUIRED_MODULES: tuple[str, ...] = ("strands", "pydantic", "boto3")

_SYSTEM_PROMPT = (
    "You are a cybersecurity incident analyst for a daily threat-intelligence globe. "
    "You are given one news item exactly as a recognized news outlet reported it "
    "(a headline and a short reported summary). Extract a faithful, structured dossier.\n\n"
    "Hard rules:\n"
    "- is_incident: true only if the item reports one concrete cyberattack, breach, or "
    "takedown that actually happened. Answer false for anything else (a newsletter, "
    "roundup, explainer, how-to, opinion, product or event announcement, or an outage "
    "that was not an attack). When false, the remaining fields are ignored: fill them "
    "with brief placeholders and never invent an incident.\n"
    "- Write every field in English, concise and factual.\n"
    "- Stay strictly faithful to what the outlet reported. Never invent figures, names, "
    "victims, or attribution that the report does not support; if a detail is unknown, "
    "describe it as not disclosed rather than guessing.\n"
    "- attack_type: choose the single best-fitting category from the allowed list.\n"
    "- severity: tremor (minor/advisory) < breach (confirmed compromise) < siege "
    "(large-scale or serious operational impact) < dominion (critical: national scale, "
    "critical infrastructure, or losses in the millions).\n"
    "- data_affected: the data or systems that were compromised.\n"
    "- impact: who or what was affected and the scale of the fallout. Do not repeat the "
    "summary; if the report gives no fallout, say it was not disclosed.\n"
    "- prevention: one concrete, actionable mitigation that would have blunted this "
    "specific attack (the defensive 'ward').\n"
    "- summary: one or two neutral sentences summarizing the incident.\n"
    "- location: a human-readable description of where the attack landed (ground zero).\n"
    "- country: the ISO-3166 alpha-2 code (uppercase) of ground zero, the victim's side. "
    "It is always required. Decide it with this order and stop at the first rule that "
    "applies: (1) the country the report states the attack hit; (2) the headquarters "
    "country of the named victim organization; (3) the headquarters country of the vendor "
    "of the vulnerable or abused product; (4) the most-affected country according to the "
    "report. Never use the attacker's origin or the outlet's country, and never answer "
    "with a placeholder such as ZZ or XX.\n"
    "- origin_country: the ISO-3166 alpha-2 code of the attacker's origin when the report "
    "attributes one, otherwise null."
)


class AgentUnavailable(RuntimeError):
    """The mandatory agent cannot run (missing SDK, AWS credentials, or model access)."""


class DossierValidationError(ValueError):
    """The agent's structured output is missing a field or carries an invalid value."""


class NotAnIncident(Exception):
    """The agent judged the item not to report a concrete cyber incident.

    Not a failure: the article is skipped (dropped without counting toward the discard
    threshold) and is never retried. A curated incident cannot be vetoed this way (see
    ``transform.extract_one``).
    """


@lru_cache(maxsize=1)
def _dossier_model() -> type:
    """Build (once) the Pydantic model describing the structured dossier.

    Defined lazily so this module imports without ``pydantic``. The ``Literal`` fields
    constrain the model to the project's attack taxonomy and severity tiers, which is
    exactly what Strands' structured output enforces on the response. Every field is
    required except ``origin_country`` (unattributed attacks are common). ``is_incident``
    gives the agent an honest way to reject a non-incident instead of fabricating one.
    """
    from pydantic import BaseModel, Field

    class StrikeDossier(BaseModel):
        """A faithful, structured dossier extracted from one reported cyberattack."""

        is_incident: bool = Field(
            description=(
                "True only if the item reports one concrete cyberattack, breach, or "
                "takedown that actually happened; false for anything else."
            )
        )
        attack_type: Literal[ATTACK_TYPES] = Field(  # type: ignore[valid-type]
            description="The single best-fitting attack category from the allowed list."
        )
        severity: Literal[SEVERITY_LABELS] = Field(  # type: ignore[valid-type]
            description="Threat tier: tremor < breach < siege < dominion."
        )
        summary: str = Field(description="One or two neutral sentences summarizing the incident.")
        data_affected: str = Field(description="The data or systems that were compromised.")
        impact: str = Field(description="Who/what was affected and the scale of the fallout.")
        prevention: str = Field(
            description="One concrete, actionable mitigation for this specific attack."
        )
        location: str = Field(description="Human-readable description of ground zero.")
        country: str = Field(
            description=(
                "ISO-3166 alpha-2 code (uppercase) of ground zero: stated country > victim "
                "HQ > vulnerable vendor HQ > most-affected country. Never the attacker's "
                "origin or the outlet's country; never ZZ/XX."
            )
        )
        origin_country: str | None = Field(
            default=None,
            description="ISO-3166 alpha-2 code of the attacker's origin, or null if unattributed.",
        )

    return StrikeDossier


def _resolve_output_model():
    """Return the structured-output model, or ``None`` if ``pydantic`` is unavailable.

    ``None`` only matters to dependency-free test stubs (which ignore the argument); a
    real run never gets here without pydantic because the preflight requires it.
    """
    try:
        return _dossier_model()
    except ImportError:
        return None


def build_agent(*, model_id: str | None = None, region: str | None = None):
    """Construct a Strands ``Agent`` backed by Amazon Bedrock (imports deferred).

    The model defaults to :data:`DEFAULT_MODEL_ID` (Claude Sonnet 4.6) unless ``model_id``
    is given. ``region`` is passed to :class:`strands.models.BedrockModel` only when
    provided; left unset, the SDK resolves it from the standard AWS environment.
    """
    from strands import Agent
    from strands.models import BedrockModel

    model_kwargs: dict = {"model_id": model_id or DEFAULT_MODEL_ID}
    if region:
        model_kwargs["region_name"] = region
    return Agent(model=BedrockModel(**model_kwargs), system_prompt=_SYSTEM_PROMPT)


def _build_prompt(
    article,
    *,
    window_start: str | None = None,
    window_end: str | None = None,
) -> str:
    """Render one article into the user turn handed to the agent."""
    window_line = ""
    if window_start and window_end:
        window_line = (
            f"\nReporting window: {window_start} to {window_end}. "
            "Focus on incidents that occurred within this date range.\n"
        )
    return (
        "A recognized news outlet reported the following item. Decide whether it is a "
        "concrete cyber incident and extract a faithful, structured incident dossier.\n"
        f"{window_line}\n"
        f"Outlet (witness): {article.witness}\n"
        f"Headline: {article.title}\n"
        f"Reported summary: {article.summary}"
    )


# ---------------------------------------------------------------------------
# Validation helpers (shared with extract.finalize_dossier)
# ---------------------------------------------------------------------------


def norm_country(value: object) -> str | None:
    """Return ``value`` as an uppercase ISO alpha-2 code known to the globe, else ``None``.

    Blanks, placeholders (``ZZ``/``XX``), malformed values, and codes missing from
    ``geolocate.COUNTRY_CENTROIDS`` all yield ``None``: a strike may only be placed on a
    country the globe can actually draw.
    """
    code = str(value or "").strip().upper()
    if len(code) == 2 and code.isalpha() and code not in {"ZZ", "XX"} and code in COUNTRY_CENTROIDS:
        return code
    return None


def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, and strip trailing punctuation for comparison."""
    return re.sub(r"\s+", " ", str(text or "").lower()).strip().rstrip(".!?;:,… ").strip()


def impact_duplicates_summary(summary: str, impact: str) -> bool:
    """True if ``impact`` repeats ``summary`` or just its first sentence."""
    imp = _normalize_text(impact)
    if not imp:
        return False
    first = re.split(r"(?<=[.!?])\s", str(summary or "").strip(), maxsplit=1)[0]
    return imp in {_normalize_text(summary), _normalize_text(first)}


def _to_overrides(dossier) -> dict:
    """Map a dossier object to an override-shaped dict, validating every field.

    Reads attributes defensively (``getattr``) so it works with both the Pydantic model
    and any duck-typed stand-in. Raises :class:`NotAnIncident` first if the agent set
    ``is_incident`` to false (a missing attribute counts as true), then
    :class:`DossierValidationError` on the first missing or invalid field; a returned
    dict is always complete and safe for ``extract.build_strike``. An ``impact`` that
    only repeats the summary is replaced with :data:`IMPACT_NOT_DISCLOSED`.
    """
    if not getattr(dossier, "is_incident", True):
        raise NotAnIncident("the agent judged this item not to be a concrete cyber incident")

    out: dict = {}

    attack_type = str(getattr(dossier, "attack_type", "") or "").strip()
    if attack_type not in ATTACK_TYPES:
        raise DossierValidationError(f"invalid attack_type: {attack_type!r}")
    out["attack_type"] = attack_type

    severity = str(getattr(dossier, "severity", "") or "").strip().lower()
    if severity not in SEVERITY_LABELS:
        raise DossierValidationError(f"invalid severity: {severity!r}")
    out["severity"] = severity

    for key in TEXT_FIELDS:
        value = str(getattr(dossier, key, "") or "").strip()
        if not value:
            raise DossierValidationError(f"empty field: {key}")
        out[key] = value

    raw_country = getattr(dossier, "country", None)
    country = norm_country(raw_country)
    if country is None:
        raise DossierValidationError(f"invalid ground-zero country: {raw_country!r}")
    out["country"] = country

    # Attribution is optional; an unusable code simply means "unattributed".
    out["origin_country"] = norm_country(getattr(dossier, "origin_country", None))

    if impact_duplicates_summary(out["summary"], out["impact"]):
        out["impact"] = IMPACT_NOT_DISCLOSED
    return out


class StrandsExtractor:
    """Extract a validated dossier from one raw article with a Strands/Bedrock agent.

    The agent is built lazily on first use; pass one in (``agent=``) to inject a stub in
    tests. :meth:`extract` raises on any failure so the orchestrator can retry (Step
    Functions) or discard (local CLI) the article.
    """

    def __init__(
        self,
        agent=None,
        *,
        model_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self._agent = agent
        # Resolve the model once: an explicit id wins, otherwise the Opus 4.8 default.
        self._model_id = model_id or DEFAULT_MODEL_ID
        self._region = region

    @property
    def model_id(self) -> str:
        return self._model_id

    def _ensure_agent(self):
        if self._agent is None:
            self._agent = build_agent(model_id=self._model_id, region=self._region)
        return self._agent

    def extract(
        self,
        article,
        *,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> dict:
        """Return a complete, validated dossier dict for ``article`` (raises on failure)."""
        agent = self._ensure_agent()
        prompt = _build_prompt(article, window_start=window_start, window_end=window_end)
        result = agent(prompt, structured_output_model=_resolve_output_model())
        dossier = getattr(result, "structured_output", None)
        if dossier is None:
            raise DossierValidationError("agent returned no structured output")
        return _to_overrides(dossier)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _is_inference_profile(model_id: str) -> bool:
    return model_id.startswith(_PROFILE_PREFIXES) or ":inference-profile/" in model_id


def ensure_agent_ready(
    model_id: str | None = None,
    region: str | None = None,
    *,
    sts_client=None,
    bedrock_client=None,
    required_modules: Iterable[str] = REQUIRED_MODULES,
) -> str:
    """Verify the mandatory agent can run, without spending any model tokens.

    Checks, in order: the SDK modules import; AWS credentials are valid
    (``sts:GetCallerIdentity``); and the Bedrock model or inference profile is visible to
    this account (``bedrock:GetInferenceProfile`` / ``bedrock:GetFoundationModel``).
    Returns the resolved model id. Raises :class:`AgentUnavailable` with an actionable
    message on the first failure. ``sts_client``/``bedrock_client`` may be injected (tests).
    """
    resolved = model_id or DEFAULT_MODEL_ID

    for name in required_modules:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            raise AgentUnavailable(
                f"required module {name!r} is not installed; run `pip install -e .` "
                "(strands-agents, pydantic, and boto3 are mandatory dependencies)"
            ) from exc

    if sts_client is None or bedrock_client is None:
        import boto3

        session = boto3.session.Session()
        effective_region = region or session.region_name or FALLBACK_REGION
        sts_client = sts_client or session.client("sts", region_name=effective_region)
        bedrock_client = bedrock_client or session.client("bedrock", region_name=effective_region)

    try:
        sts_client.get_caller_identity()
    except Exception as exc:  # noqa: BLE001 — any credential failure is fatal here
        raise AgentUnavailable(
            f"AWS credentials are missing or invalid ({exc}); configure credentials with "
            "Amazon Bedrock access before running the pipeline"
        ) from exc

    try:
        if _is_inference_profile(resolved):
            bedrock_client.get_inference_profile(inferenceProfileIdentifier=resolved)
        else:
            bedrock_client.get_foundation_model(modelIdentifier=resolved)
    except Exception as exc:  # noqa: BLE001 — model not found / access denied / wrong region
        raise AgentUnavailable(
            f"Bedrock model {resolved!r} is not available to this account/region ({exc}); "
            "check model access, --agent-model / AGENT_MODEL_ID, and --agent-region / "
            "AGENT_REGION"
        ) from exc

    return resolved
