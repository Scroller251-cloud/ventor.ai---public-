from __future__ import annotations

import time
from threading import Lock


class LearningLoop:
    def __init__(self):
        self.proposals = []
        self._lock = Lock()

    def propose_upgrade(self, title, files, impact, risks, benchmark, rollback):
        proposal = {"id": f"upgrade-{time.time_ns()}", "title": title, "files": list(files), "impact": impact, "risks": list(risks), "benchmark": dict(benchmark), "rollback": rollback, "status": "awaiting_owner_approval", "owner_approval_required": True, "executed": False}
        with self._lock:
            self.proposals.append(proposal)
        return proposal
