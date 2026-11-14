"""Dossier assembly: curated reporting + agent extraction -> structured Machine Strike.

There is no heuristic extractor. Every field of a strike's dossier comes from one of two
sources, highest precedence first:

1. **Curated reporting** — a committed, hand-verified incident's ``overrides`` block plus
   its curated ``country`` and ``summary`` (``sources.load_curated``).
2. **The Strands/Bedrock agent** (``agent_extract.StrandsExtractor``), which is mandatory
   and fills every field curated reporting left blank.

A fully curated incident never calls the agent (:func:`needs_agent`), which keeps the
committed demo snapshot reproducible. :func:`finalize_dossier` validates the merged
result; :func:`build_strike` turns it into a positioned :class:`~models.Strike`.
"""

from __future__ import annotations

from .agent_extract import (
    IMPACT_NOT_DISCLOSED,
    SEVERITY_LABELS,
    TEXT_FIELDS,
    DossierValidationError,
    impact_duplicates_summary,
    norm_country,
)
from .geolocate import Geolocator
from .models import ATTACK_TYPES, Severity, Strike, Witness

# Fields a dossier must carry before it can become a strike. ``origin_country`` is
# optional: unknown attribution collapses the assault vector onto ground zero.
REQUIRED_FIELDS: frozenset[str] = frozenset({"attack_type", "severity", "country", *TEXT_FIELDS})


def curated_fields(article) -> dict:
    """Return the dossier fields hand-verified reporting pins for ``article``.

    That is the ``overrides`` block plus, for curated rows only, the curated ``country``
    and ``summary`` columns. A live RSS item contributes nothing here: its feed summary is
    raw input for the agent, not verified reporting.
    """
    pinned = {k: v for k, v in dict(article.overrides or {}).items() if v not in (None, "")}
    if getattr(article, "curated", False):
        if article.country and "country" not in pinned:
            pinned["country"] = article.country
        if (article.summary or "").strip() and "summary" not in pinned:
            pinned["summary"] = article.summary.strip()
    return pinned


def needs_agent(article) -> bool:
    """True unless curated reporting already pins every required dossier field."""
    return not REQUIRED_FIELDS.issubset(curated_fields(article))


def finalize_dossier(article, agent_dossier: dict | None) -> dict:
    """Merge the agent's dossier under curated reporting and validate the result.

    Curated values win field by field. Raises :class:`DossierValidationError` if any
    required field is missing or invalid (unknown attack type, bad severity, a country
    the globe cannot place). An agent-supplied ``impact`` that repeats the final summary
    becomes :data:`IMPACT_NOT_DISCLOSED`; a curated ``impact`` is never touched.
    """
    curated = curated_fields(article)
    merged = {**(agent_dossier or {}), **curated}

    missing = sorted(f for f in REQUIRED_FIELDS if not str(merged.get(f) or "").strip())
    if missing:
        raise DossierValidationError(f"dossier missing fields: {', '.join(missing)}")
    if merged["attack_type"] not in ATTACK_TYPES:
        raise DossierValidationError(f"invalid attack_type: {merged['attack_type']!r}")
    severity = str(merged["severity"]).strip().lower()
    if severity not in SEVERITY_LABELS:
        raise DossierValidationError(f"invalid severity: {merged['severity']!r}")
    country = norm_country(merged["country"])
    if country is None:
        raise DossierValidationError(f"invalid ground-zero country: {merged['country']!r}")

    out = {f: str(merged[f]).strip() for f in TEXT_FIELDS}
    out.update(
        attack_type=merged["attack_type"],
        severity=severity,
        country=country,
        origin_country=norm_country(merged.get("origin_country")),
    )
    if "impact" not in curated and impact_duplicates_summary(out["summary"], out["impact"]):
        out["impact"] = IMPACT_NOT_DISCLOSED
    return out


def build_strike(article, dossier: dict, idx: int, geo: Geolocator) -> Strike:
    """Turn one article and its finalized dossier into a positioned Strike.

    ``dossier`` must come from :func:`finalize_dossier`. ``idx`` is the strike id and,
    with the title, seeds the tiny deterministic jitter that keeps co-located markers
    apart; assign it only after discards so ids stay contiguous.
    """
    seed = f"{idx}:{article.title}"
    country = dossier["country"]
    lat, lon = geo.locate(country, seed=seed)

    origin_cc = dossier.get("origin_country")
    if origin_cc:
        origin_lat, origin_lon = geo.locate(origin_cc, seed=f"origin:{seed}")
    else:
        origin_lat, origin_lon = lat, lon  # unknown attribution -> arc collapses

    return Strike(
        id=idx,
        lat=lat,
        lon=lon,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        severity=Severity.from_label(dossier["severity"]),
        witness=Witness.from_label(article.witness),
        country=country,
        published=article.published,
        title=article.title,
        location=dossier["location"],
        data_affected=dossier["data_affected"],
        impact=dossier["impact"],
        prevention=dossier["prevention"],
        summary=dossier["summary"],
        url=article.url,
        attack_type=dossier["attack_type"],
    )
