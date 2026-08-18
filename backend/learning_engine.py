"""Verified mentor learning with durable, append-only audit records."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass
class MentorObservation:
    mentor: str
    model: str
    answer: str
    latency_ms: int = 0
    evidence: list[str] | None = None


@dataclass
class Lesson:
    id: str
    task: str
    lesson: str
    source_mentors: list[str]
    verification: dict[str, Any]
    confidence: float
    created_at: float


@dataclass
class CandidateImprovement:
    id: str
    title: str
    rationale: str
    lesson_ids: list[str]
    benchmark: dict[str, Any]
    impact: dict[str, Any]
    risks: list[str]
    rollback: str
    status: str
    owner_approval_required: bool
    created_at: float


class VerifiedLearningEngine:
    """Persistent learning that never modifies or approves core code."""

    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parent.parent) / "data"
        self.root.mkdir(parents=True, exist_ok=True)
        self.observations = self.root / "mentor_observations.jsonl"
        self.lessons = self.root / "verified_lessons.jsonl"
        self.candidates = self.root / "candidate_improvements.jsonl"
        self._lock = Lock()
        self._lesson_cache: list[dict[str, Any]] | None = None

    def _append_many(self, path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)

    def record_observations(self, task: str, observations) -> list[dict[str, Any]]:
        rows = [{"ts": time.time(), "task": task, **(asdict(o) if hasattr(o, "__dataclass_fields__") else dict(o))} for o in observations]
        self._append_many(self.observations, rows)
        return rows

    def extract_lesson(self, task, observations, verdict, lesson_text, confidence=None):
        if verdict.get("status") != "verified" or not lesson_text or not lesson_text.strip():
            return None
        mentors = sorted({str(x.mentor if hasattr(x, "mentor") else x.get("mentor")) for x in observations})
        conf = float(confidence if confidence is not None else verdict.get("confidence", 0.0))
        lesson = Lesson(
            hashlib.sha256((task + lesson_text + "|".join(mentors)).encode()).hexdigest()[:16],
            task, lesson_text.strip(), mentors, {"verdict": verdict}, max(0.0, min(1.0, conf)), time.time()
        )
        row = asdict(lesson)
        self._append_many(self.lessons, [row])
        self._lesson_cache = None
        return row

    def propose_candidate(self, title, rationale, lesson_ids, benchmark, impact, risks, rollback):
        cid = hashlib.sha256((title + json.dumps(benchmark, sort_keys=True) + str(time.time_ns())).encode()).hexdigest()[:16]
        candidate = CandidateImprovement(cid, title, rationale, list(lesson_ids), dict(benchmark), dict(impact), list(risks), rollback,
                                         "awaiting_owner_approval", True, time.time())
        row = asdict(candidate)
        self._append_many(self.candidates, [row])
        return row

    def recent_lessons(self, limit: int = 8) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        if self._lesson_cache is None:
            if not self.lessons.exists():
                self._lesson_cache = []
            else:
                rows = []
                with self.lessons.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                self._lesson_cache = rows
        return self._lesson_cache[-limit:]

    def learning_context(self, limit: int = 8) -> str:
        return "\n\n".join(
            f"Verified Ventor lesson: {row['lesson']} (confidence {row.get('confidence', 0):.2f})"
            for row in self.recent_lessons(limit)
        )

    @staticmethod
    def _count(path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("rb") as handle:
            return sum(1 for _ in handle)

    def snapshot(self) -> dict[str, Any]:
        return {
            "observations": self._count(self.observations),
            "verified_lessons": self._count(self.lessons),
            "candidate_improvements": self._count(self.candidates),
            "owner_gate": "external_immutable",
            "auto_apply": False,
        }
