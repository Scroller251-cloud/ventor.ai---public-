from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class RoutedResult:
    agent: str
    model: str
    answer: str
    latency_ms: int
    metadata: dict


class UnifiedRouter:
    def __init__(self, qwen=None, gemma=None):
        if qwen is None:
            from local_models import QwenMentor
            qwen = QwenMentor()
        if gemma is None:
            from local_models import GemmaMentor
            gemma = GemmaMentor()
        self.mentors = {"Qwen Mentor": qwen, "Gemma Mentor": gemma}

    def select_specialists(self, prompt: str) -> list[str]:
        return ["Qwen Mentor", "Gemma Mentor"]

    async def _run_one(self, prompt: str, name: str) -> RoutedResult | None:
        mentor = self.mentors.get(name)
        if mentor is None:
            return None
        try:
            result = await mentor.generate(prompt)
            return RoutedResult(result.mentor, result.model, result.text, result.latency_ms, result.metadata)
        except Exception as exc:
            return RoutedResult(name, getattr(mentor, "model", "unknown"), "", 0,
                                {"error": f"{type(exc).__name__}: {exc}"})

    async def run(self, prompt: str, selected: list[str]) -> list[RoutedResult]:
        names = list(dict.fromkeys(selected))
        results = await asyncio.gather(*(self._run_one(prompt, name) for name in names))
        return [r for r in results if r is not None]
