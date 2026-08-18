from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.critic_verifier import CriticVerifier, _claims, _contradicts, _similarity


@dataclass
class Candidate:
    mentor: str
    answer: str


def verify(candidates: list[Candidate]):
    return asyncio.run(CriticVerifier().verify("test prompt", candidates))


def test_claim_extraction_supports_structured_claims():
    claims = _claims('{"claims": ["SQLite WAL improves concurrent write behavior.", "Batching reduces transaction overhead."]}')
    assert claims == [
        "SQLite WAL improves concurrent write behavior.",
        "Batching reduces transaction overhead.",
    ]


def test_similarity_detects_shared_claim_content():
    score = _similarity(
        "SQLite WAL improves concurrent write behavior.",
        "SQLite WAL can improve concurrent write performance.",
    )
    assert score >= 0.55


def test_contradiction_detection_catches_negation():
    assert _contradicts(
        "SQLite WAL improves concurrent write behavior.",
        "SQLite WAL does not improve concurrent write behavior.",
    )


def test_single_candidate_is_not_verified():
    verdict = verify([Candidate("qwen", "SQLite uses a write-ahead log for concurrency.")])
    assert verdict.status == "insufficient_evidence"
    assert verdict.selected_mentor is None
    assert verdict.confidence == 0.0


def test_agreeing_independent_candidates_can_verify():
    answer_a = '{"claims":["SQLite WAL improves concurrent write behavior."],"confidence":0.9}'
    answer_b = '{"claims":["SQLite WAL improves concurrent write behavior."],"confidence":0.9}'

    verdict = verify([Candidate("qwen", answer_a), Candidate("gemma", answer_b)])

    assert verdict.status == "verified"
    assert verdict.selected_mentor in {"qwen", "gemma"}
    assert verdict.confidence >= 0.68
    assert verdict.scores["qwen"]["agreement"] >= 0.55
    assert verdict.scores["gemma"]["agreement"] >= 0.55


def test_contradictory_candidates_require_review():
    answer_a = '{"claims":["SQLite WAL improves concurrent write behavior."],"confidence":0.95}'
    answer_b = '{"claims":["SQLite WAL does not improve concurrent write behavior."],"confidence":0.95}'

    verdict = verify([Candidate("qwen", answer_a), Candidate("gemma", answer_b)])

    assert verdict.status == "needs_review"
    assert verdict.selected_mentor is None
    assert verdict.confidence <= 0.60
    assert any("contradictory" in risk for risk in verdict.risks)


def test_valid_url_is_recorded_but_not_treated_as_fact_proof():
    answer = (
        '{"claims":["SQLite WAL improves concurrent write behavior."],'
        '"confidence":0.9,"evidence":"https://example.com/reference"}'
    )
    verdict = verify([Candidate("qwen", answer), Candidate("gemma", answer)])

    assert verdict.status == "verified"
    assert verdict.evidence["qwen"]["valid_syntax"] == 1
    assert verdict.evidence["gemma"]["valid_syntax"] == 1
    assert any("syntax" in reason for reason in verdict.reasons)
