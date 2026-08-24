from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class RoutedResult:
    agent: str
    model: str
    answer: str
    latency_ms: int
    metadata: dict


@dataclass
class AgentStats:
    successes: int = 0
    failures: int = 0
    total_latency_ms: int = 0
    task_success: dict[str, int] = field(default_factory=dict)
    task_attempts: dict[str, int] = field(default_factory=dict)

    def score(self, task: str) -> float:
        attempts = self.task_attempts.get(task, 0)
        if attempts == 0:
            return 0.5
        success = self.task_success.get(task, 0) / attempts
        avg_latency = self.total_latency_ms / max(1, self.successes + self.failures)
        speed = max(0.0, 1.0 - min(avg_latency, 10_000) / 10_000)
        return 0.75 * success + 0.25 * speed


class UnifiedRouter:
    """Adaptive router; independent candidates run concurrently for lower latency."""
    def __init__(self, qwen=None, gemma=None):
        if qwen is None:
            from local_models import QwenMentor
            qwen = QwenMentor()
        if gemma is None:
            from local_models import GemmaMentor
            gemma = GemmaMentor()
        self.mentors = {"Qwen Mentor": qwen, "Gemma Mentor": gemma}
        self.stats = {name: AgentStats() for name in self.mentors}

    def classify(self, prompt: str) -> str:
        p = prompt.lower()
        if any(k in p for k in ("code", "python", "debug", "program", "script", "api")):
            return "coding"
        if any(k in p for k in ("verify", "fact check", "is this true", "compare")):
            return "verification"
        if any(k in p for k in ("research", "latest", "current", "sources", "paper")):
            return "research"
        return "general"

    def select_specialists(self, prompt: str):
        task = self.classify(prompt)
        ranked = sorted(self.mentors, key=lambda name: self.stats[name].score(task), reverse=True)
        complexity = min(1.0, len(prompt.strip()) / 1200)
        return ranked[:2] if task in {"verification", "research"} or complexity > 0.65 else ranked[:1]

    async def _run_one(self, name, mentor, prompt, task):
        started = time.perf_counter()
        stats = self.stats[name]
        try:
            result = await mentor.generate(prompt)
            latency = result.latency_ms or round((time.perf_counter() - started) * 1000)
            ok = bool(result.text and result.text.strip())
            stats.successes += int(ok)
            stats.failures += int(not ok)
            stats.total_latency_ms += latency
            stats.task_attempts[task] = stats.task_attempts.get(task, 0) + 1
            stats.task_success[task] = stats.task_success.get(task, 0) + int(ok)
            return RoutedResult(result.mentor, result.model, result.text, latency, {**result.metadata, "task": task, "routing_score": stats.score(task)})
        except Exception as exc:
            stats.failures += 1
            stats.task_attempts[task] = stats.task_attempts.get(task, 0) + 1
            return RoutedResult(name, getattr(mentor, "model", "unknown"), "", round((time.perf_counter() - started) * 1000), {"error": f"{type(exc).__name__}: {exc}", "task": task})

    async def run(self, prompt, selected):
        task = self.classify(prompt)
        jobs = [self._run_one(name, self.mentors[name], prompt, task) for name in selected if name in self.mentors]
        return await asyncio.gather(*jobs) if jobs else []
