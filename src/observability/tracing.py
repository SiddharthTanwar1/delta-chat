"""Homegrown tracer: no external service/account needed, works fully offline,
keeps `make run` / `make eval` self-contained (see README for the trade-off
vs. OpenTelemetry/Langfuse). Each top-level request gets a Trace with nested
Spans; every span records timing, input/output summaries, and status. Traces
are written as JSON per-trace files and appended to a JSONL log for the
aggregate metrics view (`make metrics`).
"""
from __future__ import annotations

import json
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from src.config import CONFIG


def _trunc(obj: Any, limit: int = 800) -> Any:
    """Summarize a value for trace storage without bloating trace files."""
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + f"...<{len(s) - limit} more chars>"


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    start_ts: float = field(default_factory=time.time)
    end_ts: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "ok"
    input: Any = None
    output: Any = None
    meta: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class Trace:
    """One end-to-end request (ingest run / delta run / chat turn)."""

    def __init__(self, kind: str, request_id: Optional[str] = None):
        self.kind = kind
        self.trace_id = request_id or uuid.uuid4().hex[:12]
        self.spans: list[Span] = []
        self.start_ts = time.time()

    @contextmanager
    def span(self, name: str, input: Any = None, **meta):
        s = Span(name=name, trace_id=self.trace_id, input=_trunc(input), meta=meta)
        try:
            yield s
            s.status = "ok"
        except Exception as e:
            s.status = "error"
            s.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}"
            raise
        finally:
            s.end_ts = time.time()
            s.duration_ms = round((s.end_ts - s.start_ts) * 1000, 2)
            s.output = _trunc(s.output)
            self.spans.append(s)

    def finish(self) -> dict:
        end_ts = time.time()
        record = {
            "trace_id": self.trace_id,
            "kind": self.kind,
            "start_ts": self.start_ts,
            "end_ts": end_ts,
            "duration_ms": round((end_ts - self.start_ts) * 1000, 2),
            "status": "error" if any(s.status == "error" for s in self.spans) else "ok",
            "spans": [s.to_dict() for s in self.spans],
        }
        CONFIG.traces_dir.mkdir(parents=True, exist_ok=True)
        (CONFIG.traces_dir / f"{self.trace_id}.json").write_text(json.dumps(record, indent=2, default=str))
        with (CONFIG.traces_dir / "traces.jsonl").open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return record


@contextmanager
def trace(kind: str, request_id: Optional[str] = None):
    t = Trace(kind, request_id=request_id)
    try:
        yield t
    finally:
        t.finish()
