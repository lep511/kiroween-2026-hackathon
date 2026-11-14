"""Tests for the optional Strands/Bedrock enrichment path (``agent_extract``).

These never touch the network or AWS: a stub agent stands in for the real Strands
``Agent``, returning a duck-typed ``structured_output`` object. They verify the
override mapping/sanitization, the curated-overrides-win precedence, the skip guard for
fully-curated incidents, and graceful degradation to the heuristic on failure.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from types import SimpleNamespace

import pytest

from pipeline.agent_extract import (
    ATTACK_TYPES,
    DEFAULT_MODEL_ID,
    SEVERITY_LABELS,
    StrandsExtractor,
    _to_overrides,
    make_extractor,
)
from pipeline.extract import build_strike
from pipeline.geolocate import Geolocator
from pipeline.models import Severity, Witness
from pipeline.sources import RawArticle


def _dossier(**overrides) -> SimpleNamespace:
    """A fully-populated stand-in for the Pydantic dossier the agent would return."""
    base = {
        "attack_type": "ransomware",
        "severity": "siege",
        "summary": "A ransomware gang encrypted a hospital's systems.",
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


# ---- Field mapping & sanitization ------------------------------------------


def test_to_overrides_maps_clean_fields():
    out = _to_overrides(_dossier(origin_country="KP"))
    assert out["attack_type"] == "ransomware"
    assert out["severity"] == "siege"
    assert out["country"] == "DE"  # lower-case input is upper-cased
    assert out["origin_country"] == "KP"
    assert out["data_affected"] and out["impact"] and out["prevention"]


def test_to_overrides_drops_invalid_values():
    out = _to_overrides(
        _dossier(
            attack_type="unknown",  # fallback category -> let the heuristic decide
            severity="apocalyptic",  # not a real tier -> dropped
            country="ZZ",  # placeholder -> dropped
            origin_country="",  # blank -> dropped
            location="   ",  # whitespace -> dropped
        )
    )
    assert "attack_type" not in out
    assert "severity" not in out
    assert "country" not in out
    assert "origin_country" not in out
    assert "location" not in out


# ---- Extractor behavior ----------------------------------------------------


def test_enrich_returns_overrides():
    agent = _StubAgent(_dossier())
    out = StrandsExtractor(agent=agent).enrich(_article())
    assert agent.calls == 1
    assert out["attack_type"] == "ransomware"
    assert out["country"] == "DE"


def test_enrich_degrades_to_empty_on_error():
    agent = _StubAgent(raises=RuntimeError("no bedrock credentials"))
    assert StrandsExtractor(agent=agent).enrich(_article()) == {}


def test_enrich_handles_missing_structured_output():
    class _NoOutput:
        def __call__(self, prompt, structured_output_model=None):
            return SimpleNamespace(structured_output=None)

    assert StrandsExtractor(agent=_NoOutput()).enrich(_article()) == {}


# ---- Precedence inside build_strike ----------------------------------------


def test_agent_fills_gaps_when_no_curated_overrides():
    agent = _StubAgent(_dossier(origin_country="KP"))
    strike = build_strike(
        _article(), idx=1, geo=Geolocator(), extractor=StrandsExtractor(agent=agent)
    )
    assert agent.calls == 1
    assert strike.attack_type == "ransomware"
    assert strike.severity is Severity.SIEGE
    assert strike.country == "DE"
    assert strike.data_affected and strike.impact and strike.prevention
    # An attributed origin produces a non-collapsed assault vector.
    assert (strike.origin_lat, strike.origin_lon) != (strike.lat, strike.lon)


def test_curated_overrides_win_and_skip_agent():
    # A fully-curated incident (all core fields pinned) must not call the agent at all,
    # and its hand-verified values must survive.
    agent = _StubAgent(_dossier(severity="tremor", prevention="agent ward"))
    article = _article(
        overrides={
            "attack_type": "supply-chain",
            "severity": "dominion",
            "data_affected": "curated data",
            "impact": "curated impact",
            "prevention": "curated ward",
            "location": "Curated City",
        }
    )
    strike = build_strike(article, idx=1, geo=Geolocator(), extractor=StrandsExtractor(agent=agent))
    assert agent.calls == 0
    assert strike.attack_type == "supply-chain"
    assert strike.severity is Severity.DOMINION
    assert strike.prevention == "curated ward"
    assert strike.location == "Curated City"


def test_partial_overrides_let_agent_fill_the_rest():
    # Only a couple of fields are curated -> the agent is consulted, but curated values
    # still take precedence over the agent's for the fields they cover.
    agent = _StubAgent(_dossier(severity="tremor"))
    article = _article(overrides={"severity": "dominion", "location": "Curated City"})
    strike = build_strike(article, idx=1, geo=Geolocator(), extractor=StrandsExtractor(agent=agent))
    assert agent.calls == 1
    assert strike.severity is Severity.DOMINION  # curated wins over the agent's "tremor"
    assert strike.location == "Curated City"  # curated wins
    assert strike.attack_type == "ransomware"  # agent filled this gap
    assert strike.data_affected == "Patient records and clinical systems"  # agent gap-fill


def test_build_strike_without_extractor_is_pure_heuristic():
    # No extractor -> identical to the historical deterministic behavior.
    article = _article(title="A ransomware gang locked their systems")
    strike = build_strike(article, idx=1, geo=Geolocator(), extractor=None)
    assert strike.attack_type == "ransomware"
    assert strike.witness is Witness.BBC


# ---- Factory & constant invariants -----------------------------------------


def test_make_extractor_toggle():
    assert make_extractor(False) is None
    assert isinstance(make_extractor(True), StrandsExtractor)


def test_default_model_is_opus_4_8():
    assert DEFAULT_MODEL_ID == "us.anthropic.claude-opus-4-8"
    # Unset -> Opus 4.8 default; an explicit id overrides it.
    assert make_extractor(True)._model_id == DEFAULT_MODEL_ID
    assert StrandsExtractor()._model_id == DEFAULT_MODEL_ID
    assert StrandsExtractor(model_id="global.anthropic.claude-opus-4-8")._model_id == (
        "global.anthropic.claude-opus-4-8"
    )


def test_severity_labels_mirror_enum():
    assert SEVERITY_LABELS == tuple(s.label for s in Severity)


def test_attack_types_cover_taxonomy_and_unknown():
    assert "unknown" in ATTACK_TYPES
    assert "ransomware" in ATTACK_TYPES and "supply-chain" in ATTACK_TYPES
    assert len(set(ATTACK_TYPES)) == len(ATTACK_TYPES)  # no duplicates


# ---- Structured-output schema (only when pydantic is installed) ------------


@pytest.mark.skipif(importlib.util.find_spec("pydantic") is None, reason="pydantic not installed")
def test_dossier_model_builds_and_validates():
    from pipeline.agent_extract import _dossier_model

    model = _dossier_model()
    good = model(
        attack_type="ransomware",
        severity="siege",
        summary="s",
        data_affected="d",
        impact="i",
        prevention="p",
        location="l",
        country="DE",
    )
    assert good.origin_country is None
    assert _to_overrides(good)["severity"] == "siege"

    from pydantic import ValidationError

    # The Literal fields reject values outside the project's taxonomy / severity tiers.
    with pytest.raises(ValidationError):
        model(
            attack_type="not-a-category",
            severity="siege",
            summary="s",
            data_affected="d",
            impact="i",
            prevention="p",
            location="l",
            country="DE",
        )
