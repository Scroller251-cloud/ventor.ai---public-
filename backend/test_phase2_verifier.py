import asyncio
from types import SimpleNamespace

from backend.critic_verifier import CriticVerifier
from backend.debate_engine import DebateEngine


def candidate(name, answer):
    return SimpleNamespace(mentor=name, model=name, answer=answer)


def test_single_candidate_cannot_be_verified():
    async def run():
        result = await CriticVerifier().verify("task", [candidate("qwen", "Use validation before execution.")])
        assert result.status == "insufficient_evidence"
        assert result.selected_mentor is None
    asyncio.run(run())


def test_agreeing_candidates_can_be_verified():
    async def run():
        answers = [
            '{"claims":["Validate capability permissions before execution."],"lesson":"Validate capability permissions before execution.","confidence":0.9}',
            '{"claims":["Validate capability permissions before executing actions."],"lesson":"Validate capability permissions before execution.","confidence":0.9}',
        ]
        result = await CriticVerifier().verify("risky actions", [candidate("qwen", answers[0]), candidate("gemma", answers[1])])
        assert result.status == "verified"
        assert result.selected_mentor in {"qwen", "gemma"}
        assert result.claims
    asyncio.run(run())


def test_conflicting_numeric_claims_require_review():
    async def run():
        answers = ['{"claims":["The timeout should be 10 seconds."],"confidence":0.9}', '{"claims":["The timeout should be 30 seconds."],"confidence":0.9}']
        result = await CriticVerifier().verify("timeout", [candidate("qwen", answers[0]), candidate("gemma", answers[1])])
        assert result.status == "needs_review"
        assert result.selected_mentor is None
        assert result.risks
    asyncio.run(run())


def test_debate_exposes_claim_level_disagreement():
    async def run():
        result = await DebateEngine().run("task", [candidate("qwen", "Validate permissions before execution."), candidate("gemma", "Execute immediately without checking permissions.")])
        assert result.status == "claims_compared"
        assert result.claim_matrix["qwen"]
        assert result.disagreements
    asyncio.run(run())
