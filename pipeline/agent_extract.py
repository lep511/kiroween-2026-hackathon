"""Optional LLM enrichment via **Strands Agents** (Amazon Bedrock).

This is the project's AI "seam": on top of the deterministic heuristic extractor
(``extract.py``), an opt-in `Strands <https://strandsagents.com>`_ agent reads one
reported cyberattack (headline + reported summary from a named outlet) and returns a
**structured incident dossier** — it classifies the attack into a category, writes a
faithful summary, and completes every dossier field (data hit, fallout, severity, the
ward, ground zero, and attacker origin).

Design rules that keep the rest of the pipeline reproducible:

* **Opt-in only.** The agent runs when ``use_agent`` is set (CLI ``--use-agent`` /
  Lambda ``USE_AGENT=1``). The default pipeline, the offline snapshot, and the test
  suite stay fully deterministic and need no model, network, or AWS account.
* **Curated overrides still win.** Hand-verified reporting always overrides the agent;
  the agent only fills fields a curated incident left blank (see ``extract.build_strike``).
* **Graceful degradation.** Any failure — missing SDK, no Bedrock credentials, a model
  error — makes :meth:`StrandsExtractor.enrich` return ``{}`` so the deterministic
  heuristic transparently takes over. One bad row never aborts the batch.

The heavy imports (``strands``, ``pydantic``) are deferred into the functions that need
them, so importing this module costs nothing when the agent is disabled.

Reference: https://strandsagents.com/docs/user-guide/ (Agents SDK, structured output).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from .extract import ATTACK_TYPES
from .models import Severity

# Severity labels the agent may assign, mirrored from the canonical enum so the two can
# never drift (``tremor`` -> ``breach`` -> ``siege`` -> ``dominion``).
SEVERITY_LABELS: tuple[str, ...] = tuple(s.label for s in Severity)

# Override-shaped fields the agent is allowed to contribute to a strike. These are the
# exact keys ``extract.build_strike`` reads, so an enriched dict plugs in like a curated
# ``overrides`` block (with curated reporting always taking precedence).
ENRICHABLE_FIELDS: tuple[str, ...] = (
    "attack_type",
    "severity",
    "summary",
    "data_affected",
    "impact",
    "prevention",
    "location",
    "country",
    "origin_country",
)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
# The agent runs on **Claude Opus 4.8** on Amazon Bedrock by default. To use a different
# model, change it in one of three ways (highest precedence first):
#   1. CLI flag:  python -m pipeline.cli --use-agent --agent-model <bedrock-model-id>
#   2. Env var:   AGENT_MODEL_ID=<bedrock-model-id>   (local or the AWS Lambda / SAM param)
#   3. Edit the DEFAULT_MODEL_ID constant below.
# The value is a Bedrock model / inference-profile id. "us.anthropic.claude-opus-4-8" is the
# US cross-region inference profile (needs a US region such as us-west-2); the global
# profile "global.anthropic.claude-opus-4-8" is an alternative that routes across regions.
DEFAULT_MODEL_ID = "us.anthropic.claude-opus-4-8"

# Region is left unset so the Strands SDK resolves it from the standard AWS environment
# (defaults to a US region, which the "us.*" inference profile above requires); override
# with --agent-region / AGENT_REGION. Sampling settings (e.g. temperature) are left to the
# model/Bedrock defaults.

_SYSTEM_PROMPT = (
    "You are a cybersecurity incident analyst for a daily threat-intelligence globe. "
    "You are given one real cyberattack exactly as a recognized news outlet reported it "
    "(a headline and a short reported summary). Extract a faithful, structured dossier.\n\n"
    "Hard rules:\n"
    "- Write every field in English, concise and factual.\n"
    "- Stay strictly faithful to what the outlet reported. Never invent figures, names, "
    "victims, or attribution that the report does not support; if a detail is unknown, "
    "describe it as not disclosed rather than guessing.\n"
    "- attack_type: choose the single best-fitting category from the allowed list.\n"
    "- severity: tremor (minor/advisory) < breach (confirmed compromise) < siege "
    "(large-scale or serious operational impact) < dominion (critical: national scale, "
    "critical infrastructure, or losses in the millions).\n"
    "- data_affected: the data or systems that were compromised.\n"
    "- impact: who or what was affected and the scale of the fallout.\n"
    "- prevention: one concrete, actionable mitigation that would have blunted this "
    "specific attack (the defensive 'ward').\n"
    "- summary: one or two neutral sentences summarizing the incident.\n"
    "- location: a human-readable description of where the attack landed (ground zero).\n"
    "- country: the ISO-3166 alpha-2 code (uppercase) of ground zero.\n"
    "- origin_country: the ISO-3166 alpha-2 code of the attacker's origin when the report "
    "attributes one, otherwise null."
)


@lru_cache(maxsize=1)
def _dossier_model() -> type:
    """Build (once) the Pydantic model describing the structured dossier.

    Defined lazily so this module imports without ``pydantic`` installed; the schema's
    ``Literal`` fields constrain the model to the project's attack taxonomy and severity
    tiers, which is exactly what Strands' structured output enforces on the response.
    """
    from pydantic import BaseModel, Field

    class StrikeDossier(BaseModel):
        """A faithful, structured dossier extracted from one reported cyberattack."""

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
        country: str = Field(description="ISO-3166 alpha-2 code (uppercase) of ground zero.")
        origin_country: str | None = Field(
            default=None,
            description="ISO-3166 alpha-2 code of the attacker's origin, or null if unattributed.",
        )

    return StrikeDossier


def _resolve_output_model():
    """Return the structured-output model, or ``None`` if ``pydantic`` is unavailable.

    In production ``pydantic`` ships with ``strands-agents``, so the model is always
    present when the agent is; returning ``None`` only matters to dependency-free test
    stubs (which ignore the argument) and still degrades safely for a real agent.
    """
    try:
        return _dossier_model()
    except ImportError:
        return None


def build_agent(*, model_id: str | None = None, region: str | None = None):
    """Construct a Strands ``Agent`` backed by Amazon Bedrock (imports deferred).

    The model defaults to :data:`DEFAULT_MODEL_ID` (Claude Opus 4.8) unless ``model_id`` is
    given. ``region`` is passed to :class:`strands.models.BedrockModel` only when provided;
    left unset, the SDK resolves it from the standard AWS environment.
    """
    from strands import Agent
    from strands.models import BedrockModel

    model_kwargs: dict = {"model_id": model_id or DEFAULT_MODEL_ID}
    if region:
        model_kwargs["region_name"] = region
    return Agent(model=BedrockModel(**model_kwargs), system_prompt=_SYSTEM_PROMPT)


def _build_prompt(article) -> str:
    """Render one article into the user turn handed to the agent."""
    return (
        "A recognized news outlet reported the following cyberattack. "
        "Extract a faithful, structured incident dossier.\n\n"
        f"Outlet (witness): {article.witness}\n"
        f"Headline: {article.title}\n"
        f"Reported summary: {article.summary}"
    )


def _norm_cc(value: object) -> str | None:
    """Normalize a model-supplied country code to a clean ISO alpha-2, or ``None``.

    Rejects blanks and the common "unknown" placeholders so a vague answer degrades to
    heuristic country resolution instead of pinning the strike to a bogus code.
    """
    code = str(value or "").strip().upper()
    if len(code) == 2 and code.isalpha() and code not in {"ZZ", "XX"}:
        return code
    return None


def _to_overrides(dossier) -> dict:
    """Map a dossier object to an override-shaped dict, sanitizing every field.

    Reads attributes defensively (``getattr``) so it works with both the Pydantic model
    and any duck-typed stand-in, and only emits values that are safe for
    ``extract.build_strike`` to consume (valid severity label, known attack type, real
    country codes, non-empty text).
    """
    out: dict = {}

    attack_type = str(getattr(dossier, "attack_type", "") or "").strip()
    if attack_type in ATTACK_TYPES and attack_type != "unknown":
        out["attack_type"] = attack_type

    severity = str(getattr(dossier, "severity", "") or "").strip().lower()
    if severity in SEVERITY_LABELS:
        out["severity"] = severity

    for key in ("summary", "data_affected", "impact", "prevention", "location"):
        value = str(getattr(dossier, key, "") or "").strip()
        if value:
            out[key] = value

    country = _norm_cc(getattr(dossier, "country", None))
    if country:
        out["country"] = country

    origin = _norm_cc(getattr(dossier, "origin_country", None))
    if origin:
        out["origin_country"] = origin

    return out


class StrandsExtractor:
    """Enrich raw articles into dossier overrides with a Strands/Bedrock agent.

    The agent is built lazily on first use; pass one in (``agent=``) to inject a stub in
    tests. :meth:`enrich` never raises — on any failure it returns ``{}`` so the caller
    falls back to the deterministic heuristic.
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

    def _ensure_agent(self):
        if self._agent is None:
            self._agent = build_agent(model_id=self._model_id, region=self._region)
        return self._agent

    def enrich(self, article) -> dict:
        """Return override-shaped dossier fields for ``article`` (``{}`` on any failure)."""
        try:
            agent = self._ensure_agent()
            result = agent(_build_prompt(article), structured_output_model=_resolve_output_model())
            dossier = getattr(result, "structured_output", None)
            if dossier is None:
                return {}
            return _to_overrides(dossier)
        except Exception as exc:  # noqa: BLE001 — degrade to the heuristic on any failure
            print(f"[agent] enrichment failed, falling back to heuristic: {exc}")
            return {}


def make_extractor(
    enabled: bool,
    *,
    model_id: str | None = None,
    region: str | None = None,
) -> StrandsExtractor | None:
    """Return a :class:`StrandsExtractor` when ``enabled``, else ``None`` (heuristic only)."""
    if not enabled:
        return None
    return StrandsExtractor(model_id=model_id, region=region)
