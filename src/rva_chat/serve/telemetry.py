"""In-memory request counters for /metrics, and a privacy-conscious query log.

Per docs/PLAN.md §8: "log queries without IPs or identifiers; make the log
opt-out-able and rotate it." No IP, no user-agent, no cookie/session id is ever
written here — only what's needed to debug retrieval quality later: the query
text, which entities matched, whether the answer passed the grounded-check, and
latency. Rotation is by calendar day (one file per day) rather than a logging
framework, since that's all a single low-traffic box needs.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import threading
import time


@dataclasses.dataclass
class Counters:
    requests_total: int = 0
    refusals_total: int = 0
    ungrounded_dropped_total: int = 0
    llm_errors_total: int = 0
    total_latency_ms: float = 0.0

    def record(self, *, latency_ms: float, refused: bool, dropped: bool, llm_error: bool) -> None:
        self.requests_total += 1
        self.total_latency_ms += latency_ms
        if refused:
            self.refusals_total += 1
        if dropped:
            self.ungrounded_dropped_total += 1
        if llm_error:
            self.llm_errors_total += 1

    def snapshot(self) -> dict:
        avg = self.total_latency_ms / self.requests_total if self.requests_total else 0.0
        return {
            "requests_total": self.requests_total,
            "refusals_total": self.refusals_total,
            "ungrounded_dropped_total": self.ungrounded_dropped_total,
            "llm_errors_total": self.llm_errors_total,
            "avg_latency_ms": round(avg, 1),
        }


class QueryLog:
    """Appends one JSON line per query to logs/queries-YYYY-MM-DD.jsonl.

    Call `log()` with `skip=True` (wired to a `no_log` request flag in the UI)
    to honor the opt-out without special-casing callers — they always call
    `log()`, this just decides whether anything is written.
    """

    def __init__(self, log_dir: pathlib.Path):
        self.log_dir = log_dir
        self._lock = threading.Lock()

    def log(
        self,
        *,
        query: str,
        matched_entity_ids: list[str],
        grounded: bool | None,
        latency_ms: float,
        skip: bool = False,
    ) -> None:
        if skip:
            return
        entry = {
            "ts": time.time(),
            "query": query,
            "matched_entity_ids": matched_entity_ids,
            "grounded": grounded,
            "latency_ms": round(latency_ms, 1),
        }
        self.log_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.date.today().isoformat()
        path = self.log_dir / f"queries-{day}.jsonl"
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
