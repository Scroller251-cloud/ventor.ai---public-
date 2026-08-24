from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from critic_verifier import _claims, _similarity


@dataclass
class Candidate:
    mentor: str
    model: str
    answer: str
    latency_ms: int = 0
    evidence: list[str] = field(default_factory=list)


@dataclass
class DebateResult:
    id: str
    prompt: str
    candidates: list[Candidate]
    disagreements: list[str]
    status: str
    created_at: float
    claim_matrix: dict = field(default_factory=dict)


class DebateEngine:
    def __init__(self, *mentors, learning=None):
        self.mentors = list(mentors)
        self.learning = learning

    async def run(self, prompt: str, candidates: list[Candidate] | None = None):
        candidates = list(candidates or [])
        disagreements = []
        claim_matrix = {candidate.mentor: _claims(candidate.answer) for candidate in candidates}
        for i, left in enumerate(candidates):
            for right in candidates[i + 1:]:
                best = max((_similarity(a, b) for a in claim_matrix[left.mentor] for b in claim_matrix[right.mentor]), default=0.0)
                if best < 0.55:
                    disagreements.append(f"{left.mentor} and {right.mentor} have no strongly overlapping claim (best similarity {best:.2f}).")
                elif best < 0.75:
                    disagreements.append(f"{left.mentor} and {right.mentor} partially agree but differ in claim detail (best similarity {best:.2f}).")
        digest = hashlib.sha256((prompt + "".join(c.answer for c in candidates)).encode()).hexdigest()[:16]
        return DebateResult(digest, prompt, candidates, disagreements, "claims_compared" if candidates else "no_candidates", time.time(), claim_matrix)
