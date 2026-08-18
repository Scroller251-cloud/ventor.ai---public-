from __future__ import annotations

import asyncio

from .critic_verifier import CriticVerifier, extract_lesson_from_answer
from .debate_engine import Candidate, DebateEngine
from .learning_engine import MentorObservation, VerifiedLearningEngine


class MentorLearningPipeline:
    def __init__(self, mentors, debate=None, verifier=None, engine=None):
        self.mentors = list(mentors)
        self.debate = debate or DebateEngine(*self.mentors)
        self.verifier = verifier or CriticVerifier(self.mentors)
        self.engine = engine or VerifiedLearningEngine()

    async def _call(self, mentor, task: str):
        return await mentor.generate(
            task,
            system=("You are an independent mentor for Ventor. Analyze independently. "
                    "Do not assume another mentor is correct. Return useful reasoning and, "
                    "when appropriate, a concise lesson Ventor could learn."),
        )

    async def learn(self, task: str):
        observations: list[MentorObservation] = []
        candidates: list[Candidate] = []
        results = await asyncio.gather(*(self._call(m, task) for m in self.mentors), return_exceptions=True)
        for mentor, result in zip(self.mentors, results):
            if isinstance(result, Exception):
                observations.append(MentorObservation(getattr(mentor, "mentor", type(mentor).__name__), getattr(mentor, "model", "unknown"),
                                                      f"ERROR: {type(result).__name__}: {result}"))
                continue
            observations.append(MentorObservation(result.mentor, result.model, result.text, result.latency_ms, []))
            candidates.append(Candidate(result.mentor, result.model, result.text, result.latency_ms, []))

        self.engine.record_observations(task, observations)
        if not candidates:
            return {"status": "insufficient_evidence", "lesson": None, "observations": [o.__dict__ for o in observations], "debate": None, "verdict": None}

        debate_result = await self.debate.run(task, candidates)
        verdict = await self.verifier.verify(task, debate_result.candidates)
        lesson = None
        if verdict.status == "verified":
            selected = next((c for c in debate_result.candidates if c.mentor == verdict.selected_mentor), None)
            if selected:
                lesson_text, parsed_conf = extract_lesson_from_answer(selected.answer)
                if lesson_text:
                    lesson = self.engine.extract_lesson(task, observations, {
                        "status": verdict.status, "confidence": verdict.confidence,
                        "selected_mentor": verdict.selected_mentor, "scores": verdict.scores,
                        "reasons": verdict.reasons, "risks": verdict.risks,
                    }, lesson_text, max(float(verdict.confidence), float(parsed_conf or 0.0)))
        return {
            "status": verdict.status,
            "lesson": lesson,
            "observations": [o.__dict__ for o in observations],
            "debate": {"id": debate_result.id, "disagreements": debate_result.disagreements, "status": debate_result.status},
            "verdict": verdict.__dict__,
        }
