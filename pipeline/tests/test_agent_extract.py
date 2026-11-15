"""Tests for the mandatory Strands/Bedrock extraction agent (``agent_extract``).

These never touch the network or AWS: a stub agent stands in for the real Strands
``Agent`` (returning a duck-typed ``structured_output`` object), and stub STS/Bedrock
clients stand in for boto3 in the preflight. They verify the strict dossier contract
(mapping, validation errors, impact dedupe) and :func:`ensure_agent_ready`.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from types import SimpleNamespace

import pytest

from pipeline.agent_extract import (
    _SYSTEM_PROMPT,
    DEFAULT_MODEL_ID,
    IMPACT_NOT_DISCLOSED,
    SEVERITY_LABELS,
    AgentUnavailable,
    DossierValidationError,
    NotAnIncident,
    StrandsExtractor,
    _to_overrides,
    ensure_agent_ready,
    impact_duplicates_summary,
    norm_country,
)
from pipeline.models import ATTACK_TYPES, Severity
from pipeline.sources import RawArticle


def _dossier(**overrides) -> SimpleNamespace:
    """A fully populated stand-in for the Pydantic dossier the agent would return."""
    base = {
        "is_incident": True,
        "attack_type": "ransomware",
        "severity": "siege",
        "summary": "A ransomware gang encrypted a hospital's systems. Surgeries were delayed.",
        "data_affected": "Patient records and clinical systems",
        "impact": "Hospital operations disrupted for days",
        "prevention": "Keep offline, tested backups and enforce MFA.",
        "location": "Berlin, Germany",
        "country": "de",
        "origin_country": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _StubAgent:
    """Minimal stand-in for a Strands ``Agent``: records calls, returns a fixed dossier."""

    def __init__(self, dossier=None, *, raises: Exception | None = None) -> None:
        self._dossier = dossier
        self._raises = raises
        self.calls = 0

    def __call__(self, prompt, structured_output_model=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(structured_output=self._dossier)


def _article(**kw) -> RawArticle:
    defaults = dict(
        witness="bbc",
        title="Hackers hit a hospital",
        summary="Systems were encrypted.",
        url="https://example.com/2026/11/hospital-hack",
        published=date(2026, 11, 14),
    )
    defaults.update(kw)
    return RawArticle(**defaults)


# ---- Mapping ---------------------------------------------------------------


def test_extract_maps_a_valid_dossier():
    agent = _StubAgent(_dossier(severity="SIEGE", origin_country="ru"))
    out = StrandsExtractor(agent=agent).extract(_article())
    assert agent.calls == 1
    assert out == {
        "attack_type": "ransomware",
        "severity": "siege",
        "summary": "A ransomware gang encrypted a hospital's systems. Surgeries were delayed.",
        "data_affected": "Patient records and clinical systems",
        "impact": "Hospital operations disrupted for days",
        "prevention": "Keep offline, tested backups and enforce MFA.",
        "location": "Berlin, Germany",
        "country": "DE",
        "origin_country": "RU",
    }


@pytest.mark.parametrize("origin", [None, "", "ZZ", "XX", "QQ"])
def test_unusable_origin_means_unattributed(origin):
    assert _to_overrides(_dossier(origin_country=origin))["origin_country"] is None


# ---- Validation errors -----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"country": "ZZ"},
        {"country": "xx"},
        {"country": "QQ"},
        {"country": ""},
        {"country": None},
        {"country": "DEU"},
        {"summary": ""},
        {"data_affected": "   "},
        {"impact": None},
        {"prevention": ""},
        {"location": ""},
        {"attack_type": "unknown"},
        {"attack_type": "alien-invasion"},
        {"severity": "apocalypse"},
        {"severity": ""},
    ],
)
def test_invalid_dossier_raises(bad):
    with pytest.raises(DossierValidationError):
        StrandsExtractor(agent=_StubAgent(_dossier(**bad))).extract(_article())


def test_missing_structured_output_raises():
    with pytest.raises(DossierValidationError):
        StrandsExtractor(agent=_StubAgent(None)).extract(_article())


def test_non_incident_verdict_raises_not_an_incident():
    # Even with otherwise-invalid fields, the verdict wins: no validation error.
    agent = _StubAgent(_dossier(is_incident=False, attack_type="unknown", country="ZZ"))
    with pytest.raises(NotAnIncident):
        StrandsExtractor(agent=agent).extract(_article())
    assert not issubclass(NotAnIncident, DossierValidationError)


def test_prompt_offers_the_non_incident_exit():
    assert "is_incident" in _SYSTEM_PROMPT


def test_agent_errors_propagate():
    agent = _StubAgent(raises=RuntimeError("throttled"))
    with pytest.raises(RuntimeError, match="throttled"):
        StrandsExtractor(agent=agent).extract(_article())


def test_norm_country_requires_a_known_code():
    assert norm_country(" fr ") == "FR"
    for value in ("ZZ", "XX", "QQ", "", None, "FRA", "1A"):
        assert norm_country(value) is None


# ---- Impact dedupe (R7) ----------------------------------------------------


@pytest.mark.parametrize(
    "impact",
    [
        "A ransomware gang encrypted a hospital's systems. Surgeries were delayed.",
        "a ransomware gang   encrypted a hospital's SYSTEMS. surgeries were delayed!",
        "A ransomware gang encrypted a hospital's systems.",
        "  a RANSOMWARE gang encrypted a hospital's systems  ",
    ],
)
def test_impact_repeating_the_summary_is_not_disclosed(impact):
    out = StrandsExtractor(agent=_StubAgent(_dossier(impact=impact))).extract(_article())
    assert out["impact"] == IMPACT_NOT_DISCLOSED


def test_distinct_impact_is_kept():
    assert not impact_duplicates_summary("Hackers hit a bank.", "Two million customers.")
    assert not impact_duplicates_summary("Hackers hit a bank.", "")


# ---- Configuration mirrors -------------------------------------------------


def test_default_model_is_sonnet_4_6():
    assert DEFAULT_MODEL_ID == "global.anthropic.claude-sonnet-4-6"
    assert StrandsExtractor(agent=_StubAgent()).model_id == DEFAULT_MODEL_ID
    assert StrandsExtractor(agent=_StubAgent(), model_id="x.y").model_id == "x.y"


def test_severity_labels_mirror_enum():
    assert SEVERITY_LABELS == tuple(s.label for s in Severity)


def test_attack_types_have_no_unknown():
    assert "unknown" not in ATTACK_TYPES
    assert len(ATTACK_TYPES) == len(set(ATTACK_TYPES)) == 11


@pytest.mark.skipif(importlib.util.find_spec("pydantic") is None, reason="pydantic not installed")
def test_dossier_model_requires_every_field_but_origin():
    from pydantic import ValidationError

    from pipeline.agent_extract import _dossier_model

    model = _dossier_model()
    fields = model.model_fields
    assert not fields["origin_country"].is_required()
    assert all(f.is_required() for name, f in fields.items() if name != "origin_country")

    full = vars(_dossier(country="DE"))
    assert model(**full).origin_country is None
    assert model(**{**full, "is_incident": False}).is_incident is False
    with pytest.raises(ValidationError):
        model(**{k: v for k, v in full.items() if k != "is_incident"})
    with pytest.raises(ValidationError):
        model(**{**full, "attack_type": "unknown"})
    with pytest.raises(ValidationError):
        model(**{k: v for k, v in full.items() if k != "country"})


# ---- Preflight -------------------------------------------------------------


class _StubSts:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.calls = 0

    def get_caller_identity(self):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return {"Account": "123456789012"}


class _StubBedrock:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.profiles: list[str] = []
        self.models: list[str] = []

    def get_inference_profile(self, *, inferenceProfileIdentifier):  # noqa: N803
        self.profiles.append(inferenceProfileIdentifier)
        if self._raises is not None:
            raise self._raises
        return {"status": "ACTIVE"}

    def get_foundation_model(self, *, modelIdentifier):  # noqa: N803
        self.models.append(modelIdentifier)
        if self._raises is not None:
            raise self._raises
        return {"modelDetails": {"modelId": modelIdentifier}}


def test_preflight_accepts_an_inference_profile():
    sts, bedrock = _StubSts(), _StubBedrock()
    resolved = ensure_agent_ready(sts_client=sts, bedrock_client=bedrock, required_modules=())
    assert resolved == DEFAULT_MODEL_ID
    assert sts.calls == 1
    assert bedrock.profiles == [DEFAULT_MODEL_ID] and bedrock.models == []


def test_preflight_accepts_a_foundation_model():
    bedrock = _StubBedrock()
    model = "anthropic.claude-opus-4-8"
    resolved = ensure_agent_ready(
        model, "us-west-2", sts_client=_StubSts(), bedrock_client=bedrock, required_modules=()
    )
    assert resolved == model
    assert bedrock.models == [model] and bedrock.profiles == []


def test_preflight_fails_without_credentials():
    from botocore.exceptions import NoCredentialsError

    for exc in (NoCredentialsError(), Exception("InvalidClientTokenId")):
        bedrock = _StubBedrock()
        with pytest.raises(AgentUnavailable, match="credentials"):
            ensure_agent_ready(
                sts_client=_StubSts(raises=exc), bedrock_client=bedrock, required_modules=()
            )
        assert bedrock.profiles == []  # never reaches the model check


def test_preflight_fails_when_model_is_not_found():
    bedrock = _StubBedrock(raises=Exception("ResourceNotFoundException: model not found"))
    with pytest.raises(AgentUnavailable, match="not available"):
        ensure_agent_ready(sts_client=_StubSts(), bedrock_client=bedrock, required_modules=())


def test_preflight_fails_when_a_module_is_missing():
    sts = _StubSts()
    with pytest.raises(AgentUnavailable, match="not installed"):
        ensure_agent_ready(
            sts_client=sts,
            bedrock_client=_StubBedrock(),
            required_modules=("definitely_not_a_real_module_xyz",),
        )
    assert sts.calls == 0
