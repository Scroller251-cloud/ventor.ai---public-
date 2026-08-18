from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from evidence_checker import check_urls


@dataclass
class FinalVerdict:
    status: str
    selected_mentor: str | None
    confidence: float
    scores: dict
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    claims: dict[str, list[str]] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


_STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "that", "the", "their", "this", "to", "use", "with", "you", "your", "before", "after", "than", "then", "when", "while"}
_SYNONYMS = {"check": "validate", "checking": "validate", "checked": "validate", "verifies": "validate", "verify": "validate", "verified": "validate", "validating": "validate", "validation": "validate", "doing": "perform", "performed": "perform", "expensive": "costly"}
_NEGATION = {"not", "never", "no", "without", "avoid", "cannot", "can't", "dont", "don't"}


def _tokens(text: str) -> set[str]:
    return {_SYNONYMS.get(t, t) for t in re.findall(r"[a-z0-9][a-z0-9'_-]*", text.lower()) if t not in _STOPWORDS and len(t) > 2}


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _claims(answer: str) -> list[str]:
    text = (answer or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            raw = data.get("claims")
            if isinstance(raw, list):
                values = [str(x).strip() for x in raw if str(x).strip()]
                if values:
                    return values[:12]
            if data.get("lesson"):
                return [str(data["lesson"]).strip()]
            if data.get("answer"):
                text = str(data["answer"])
    except Exception:
        pass
    parts = re.split(r"(?<=[.!?])\s+|\n+|^[-*]\s+", text)
    claims = []
    for part in parts:
        part = re.sub(r"^\s*\d+[.)]\s*", "", part).strip()
        if len(part) >= 18 and part not in claims:
            claims.append(part)
    return claims[:12]


def _polarity(text: str) -> int:
    return -1 if _tokens(text) & _NEGATION else 1


def _contradicts(a: str, b: str) -> bool:
    similarity = _similarity(a, b)
    if similarity < 0.55:
        return False
    if _polarity(a) != _polarity(b):
        return True
    nums_a = set(re.findall(r"\b\d+(?:\.\d+)?\b", a))
    nums_b = set(re.findall(r"\b\d+(?:\.\d+)?\b", b))
    return bool(nums_a and nums_b and nums_a.isdisjoint(nums_b) and similarity >= 0.72)


class CriticVerifier:
    def __init__(self, mentors=None, min_agreement: float = 0.55, min_confidence: float = 0.68):
        self.mentors = list(mentors or [])
        self.min_agreement = min_agreement
        self.min_confidence = min_confidence

    async def verify(self, prompt, candidates):
        usable = [c for c in candidates if (getattr(c, "answer", None) or getattr(c, "text", "")).strip()]
        if len(usable) < 2:
            return FinalVerdict("insufficient_evidence", None, 0.0, {}, ["Verification requires at least two independent usable mentor candidates."], ["A single model cannot independently verify its own answer."])
        claims_by_mentor = {c.mentor: _claims(getattr(c, "answer", None) or getattr(c, "text", "")) for c in usable}
        evidence = {c.mentor: (await check_urls(getattr(c, "answer", None) or getattr(c, "text", ""))).__dict__ for c in usable}
        pairwise, contradictions = [], []
        for i, left in enumerate(usable):
            for right in usable[i + 1:]:
                for a in claims_by_mentor[left.mentor]:
                    for b in claims_by_mentor[right.mentor]:
                        sim = _similarity(a, b)
                        if sim >= self.min_agreement:
                            pairwise.append((left.mentor, right.mentor, sim, a, b))
                        if _contradicts(a, b):
                            contradictions.append((left.mentor, right.mentor, a, b))
        scores = {}
        for candidate in usable:
            own_claims = claims_by_mentor[candidate.mentor]
            supports = [sim for left, right, sim, _, _ in pairwise if candidate.mentor in (left, right)]
            agreement = max(supports, default=0.0)
            try:
                parsed = json.loads(getattr(candidate, "answer", None) or getattr(candidate, "text", ""))
            except Exception:
                parsed = {}
            stated = max(0.0, min(1.0, float(parsed.get("confidence", 0.0)))) if isinstance(parsed, dict) else 0.0
            evidence_urls = int(evidence[candidate.mentor].get("valid_syntax", 0))
            score = min(1.0, 0.35 + 0.40 * agreement + 0.15 * stated + min(0.10, evidence_urls * 0.05) + min(0.10, len(own_claims) * 0.025))
            scores[candidate.mentor] = {"score": round(score, 3), "agreement": round(agreement, 3), "stated_confidence": round(stated, 3), "claim_count": len(own_claims), "valid_evidence_urls": evidence_urls}
        best = max(usable, key=lambda c: scores[c.mentor]["score"])
        best_score = scores[best.mentor]["score"]
        overall_agreement = max((x[2] for x in pairwise), default=0.0)
        reasons = [f"Compared {len(usable)} independent mentor candidates at claim level."]
        risks = []
        if pairwise:
            reasons.append(f"Strongest cross-mentor claim agreement: {overall_agreement:.2f}.")
        else:
            risks.append("Mentor claims did not reach the minimum agreement threshold.")
        if contradictions:
            risks.append(f"Detected {len(contradictions)} potentially contradictory claim pair(s).")
        if any(evidence[m].get("valid_syntax", 0) for m in evidence):
            reasons.append("Cited evidence passed URL syntax validation; source truth was not assumed from syntax alone.")
        if contradictions or overall_agreement < self.min_agreement or best_score < self.min_confidence:
            return FinalVerdict("needs_review", None, round(min(best_score, 0.67 if not contradictions else 0.60), 3), scores, reasons, risks, claims_by_mentor, evidence)
        reasons.append(f"{best.mentor} supplied the highest independently supported claim set.")
        return FinalVerdict("verified", best.mentor, round(best_score, 3), scores, reasons, risks, claims_by_mentor, evidence)


def extract_lesson_from_answer(answer: str):
    try:
        data = json.loads(answer)
        if isinstance(data, dict) and data.get("lesson"):
            return str(data["lesson"]).strip(), float(data.get("confidence", 0.0))
    except Exception:
        pass
    text = answer.strip()
    return (text, 0.0) if text else (None, 0.0)
