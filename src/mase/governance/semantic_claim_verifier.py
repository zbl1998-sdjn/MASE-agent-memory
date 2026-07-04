"""Deterministic semantic claim verifier PoC.

This module adds a white-box L2 verifier on top of exact span matching.  It uses
small, inspectable synonym tables and canonical claim normalization; it does not
call an LLM and does not treat embeddings as truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .evidence_pack import EvidencePack
from .retrieval import _norm

SUPPORTED = "supported"
CONTRADICTED = "contradicted"
UNKNOWN = "unknown"

_PREDICATE_ALIASES: dict[str, tuple[str, ...]] = {
    "owner": ("owner", "owns", "owned by", "负责人", "归属", "负责"),
    "lead": ("lead", "leader", "负责人", "带头"),
    "budget": ("budget", "spending cap", "limit", "预算", "上限"),
    "deadline": ("deadline", "due", "target date", "截止", "期限"),
    "status": ("status", "state", "当前状态", "状态"),
}


@dataclass(frozen=True)
class SemanticClaim:
    """A normalized fact claim derived from an Evidence Pack entry."""

    fact_id: str
    predicate: str
    object_value: str
    aliases: tuple[str, ...]


def verify_semantic_claims(answer: str, pack: EvidencePack) -> dict[str, Any]:
    """Verify paraphrased answer claims against an Evidence Pack.

    Returns sentence-level judgments.  The verifier is conservative: if a
    sentence appears to discuss a known predicate but lacks a supported object,
    it is marked ``unknown`` rather than accepted.
    """
    claims = tuple(_claims_from_pack(pack))
    judgments: list[dict[str, Any]] = []
    for index, sentence in enumerate(_sentences(answer)):
        normalized = _norm(sentence)
        supported = [claim for claim in claims if _object_supported(claim, normalized)]
        predicate_claims = [claim for claim in claims if _mentions_predicate(claim, normalized)]
        if supported:
            judgments.append(
                {
                    "sentence_index": index,
                    "text": sentence,
                    "status": SUPPORTED,
                    "fact_ids": [claim.fact_id for claim in supported],
                    "reason": "normalized object and predicate/value context matched evidence pack",
                }
            )
        elif predicate_claims and _has_foreign_value(normalized, predicate_claims):
            judgments.append(
                {
                    "sentence_index": index,
                    "text": sentence,
                    "status": CONTRADICTED,
                    "fact_ids": [claim.fact_id for claim in predicate_claims],
                    "reason": "sentence mentions a governed predicate with a different value",
                }
            )
        elif predicate_claims:
            judgments.append(
                {
                    "sentence_index": index,
                    "text": sentence,
                    "status": UNKNOWN,
                    "fact_ids": [claim.fact_id for claim in predicate_claims],
                    "reason": "sentence mentions governed predicate but no supported value",
                }
            )
    return {
        "verdict": _summary_verdict(judgments),
        "judgments": judgments,
        "claim_count": len(claims),
        "checked_sentence_count": len(judgments),
    }


def _claims_from_pack(pack: EvidencePack) -> list[SemanticClaim]:
    claims: list[SemanticClaim] = []
    for entry in pack.verified:
        parsed = _parse_claim(str(entry.get("claim") or ""))
        if parsed is None:
            continue
        predicate, value = parsed
        claims.append(
            SemanticClaim(
                fact_id=str(entry.get("fact_id") or ""),
                predicate=predicate,
                object_value=value,
                aliases=_aliases_for(predicate),
            )
        )
    return claims


def _parse_claim(claim: str) -> tuple[str, str] | None:
    if "=" not in claim:
        return None
    left, value = claim.split("=", 1)
    predicate = left.split(".")[-1].strip()
    value = value.strip()
    if not predicate or not value:
        return None
    return predicate, value


def _aliases_for(predicate: str) -> tuple[str, ...]:
    normalized = predicate.strip().lower()
    aliases = [normalized]
    for key, values in _PREDICATE_ALIASES.items():
        if key in normalized or normalized in key:
            aliases.extend(values)
    return tuple(dict.fromkeys(_norm(item) for item in aliases if item.strip()))


def _object_supported(claim: SemanticClaim, normalized_sentence: str) -> bool:
    object_norm = _norm(claim.object_value)
    if not object_norm or object_norm not in normalized_sentence:
        return False
    return _mentions_predicate(claim, normalized_sentence) or len(object_norm) >= 3


def _mentions_predicate(claim: SemanticClaim, normalized_sentence: str) -> bool:
    return any(alias and alias in normalized_sentence for alias in claim.aliases)


def _has_foreign_value(normalized_sentence: str, claims: list[SemanticClaim]) -> bool:
    supported_values = {_norm(claim.object_value) for claim in claims}
    if any(value and value in normalized_sentence for value in supported_values):
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", normalized_sentence)
    alias_tokens = {alias for claim in claims for alias in claim.aliases}
    candidate_values = [token for token in tokens if token not in alias_tokens]
    return bool(candidate_values)


def _summary_verdict(judgments: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in judgments}
    if CONTRADICTED in statuses:
        return "refuse"
    if UNKNOWN in statuses:
        return "revise"
    return "pass"


def _sentences(answer: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?。!?])\s*", answer) if part.strip()]
    return parts or ([answer.strip()] if answer.strip() else [])
