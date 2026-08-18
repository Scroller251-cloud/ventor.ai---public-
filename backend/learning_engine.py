from __future__ import annotations

import hashlib
import json
import time
from collections import deque
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
    """Append-only, evidence-gated learning with bounded read amplification."""
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parent.parent) / "data"
        self.root.mkdir(parents=True, exist_ok=True)
        self.observations = self.root / "mentor_observations.jsonl"
        self.lessons = self.root / "verified_lessons.jsonl"
        self.candidates = self.root / "candidate_improvements.jsonl"
        self._lock = Lock()
        self._counts = {"observations": 0, "verified_lessons": 0, "candidate_improvements": 0}
        self._recent = deque(maxlen=64)
        self._load_index()

    def _load_index(self):
        for key, path in (("observations", self.observations), ("verified_lessons", self.lessons), ("candidate_improvements", self.candidates)):
            if not path.exists():
                continue
            recent = deque(maxlen=64)
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    self._counts[key] += 1
                    if key == "verified_lessons":
                        try:
                            recent.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            if key == "verified_lessons":
                self._recent = recent

    def _append(self, path, obj):
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

    def record_observations(self, task, observations):
        rows = []
        for o in observations:
            row = {"ts": time.time(), "task": task, **(asdict(o) if hasattr(o, "__dataclass_fields__") else dict(o))}
            self._append(self.observations, row)
            with self._lock:
                self._counts["observations"] += 1
            rows.append(row)
        return rows

    def extract_lesson(self, task, observations, verdict, lesson_text, confidence=None):
        if verdict.get("status") != "verified" or not lesson_text or not lesson_text.strip():
            return None
        mentors = sorted({str(x.mentor if hasattr(x, "mentor") else x.get("mentor")) for x in observations})
        conf = float(confidence if confidence is not None else verdict.get("confidence", 0.0))
        lid = hashlib.sha256((task + lesson_text + "|".join(mentors)).encode()).hexdigest()[:16]
        lesson = Lesson(lid, task, lesson_text.strip(), mentors, {"verdict": verdict}, max(0.0, min(1.0, conf)), time.time())
        row = asdict(lesson)
        self._append(self.lessons, row)
        with self._lock:
            self._counts["verified_lessons"] += 1
            self._recent.append(row)
        return row

    def propose_candidate(self, title, rationale, lesson_ids, benchmark, impact, risks, rollback):
        cid = hashlib.sha256((title + json.dumps(benchmark, sort_keys=True) + str(time.time_ns())).encode()).hexdigest()[:16]
        candidate = CandidateImprovement(cid, title, rationale, list(lesson_ids), dict(benchmark), dict(impact), list(risks), rollback, "awaiting_owner_approval", True, time.time())
        row = asdict(candidate)
        self._append(self.candidates, row)
        with self._lock:
            self._counts["candidate_improvements"] += 1
        return row

    def recent_lessons(self, limit=8):
        return list(self._recent)[-max(1, min(int(limit), 64)):]

    def learning_context(self, limit=8):
        return "\n\n".join(f"Verified Ventor lesson: {x['lesson']} (confidence {x.get('confidence', 0):.2f})" for x in self.recent_lessons(limit))

    def snapshot(self):
        with self._lock:
            return {**self._counts, "owner_gate": "external_immutable", "auto_apply": False}
