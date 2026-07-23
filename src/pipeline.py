"""End-to-end ingest -> delta -> report pipeline, used by both the CLI
(`make run`) and the eval harness so there's exactly one code path to keep
correct. Wrapped in a single top-level Trace per run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.canonical.model import Document
from src.config import CONFIG
from src.delta.engine import DeltaItem, compute_delta
from src.delta.report import write_report
from src.ingest.base import detect_and_ingest
from src.observability.logging import bind, get_logger
from src.observability.tracing import Trace, trace as trace_ctx

log = get_logger("pipeline")


def run_pair(path_a: str | Path, path_b: str | Path, pid_a: str, pid_b: str,
             out_dir: str | Path, rev_a: str = "A", rev_b: str = "B",
             llm_describe=None) -> tuple[Document, Document, list[DeltaItem], Path, Path]:
    with trace_ctx("delta_run") as t:
        rlog = bind(log, trace_id=t.trace_id, request_id=t.trace_id)
        with t.span("ingest_a", input={"path": str(path_a), "pid": pid_a}) as s:
            doc_a = detect_and_ingest(path_a, pid=pid_a, revision=rev_a)
            s.output = {"format": doc_a.format, "sheets": len(doc_a.sheets), "elements": doc_a.element_count()}
        with t.span("ingest_b", input={"path": str(path_b), "pid": pid_b}) as s:
            doc_b = detect_and_ingest(path_b, pid=pid_b, revision=rev_b)
            s.output = {"format": doc_b.format, "sheets": len(doc_b.sheets), "elements": doc_b.element_count()}

        with t.span("compute_delta") as s:
            items = compute_delta(
                doc_a, doc_b,
                match_min=CONFIG.delta_match_min,
                move_threshold=CONFIG.delta_move_threshold_px,
                llm_describe=llm_describe,
                trace=t,
            )
            s.output = {"total": len(items),
                        "added": sum(1 for i in items if i.kind == "added"),
                        "removed": sum(1 for i in items if i.kind == "removed"),
                        "modified": sum(1 for i in items if i.kind == "modified")}

        with t.span("write_report", input={"out_dir": str(out_dir)}) as s:
            json_path, md_path = write_report(doc_a, doc_b, items, Path(out_dir))
            s.output = {"json": str(json_path), "md": str(md_path)}

        rlog.info(f"delta run complete: {len(items)} items -> {out_dir}", extra={"stage": "done"})
        return doc_a, doc_b, items, json_path, md_path
