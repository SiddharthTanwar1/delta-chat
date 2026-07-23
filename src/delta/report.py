"""Renders a DeltaItem list as both a machine-parseable JSON artifact and a
human-readable Markdown report. Both are first-class retrievable sources for
chat -- each item's `id` (e.g. D-014) is the citation anchor.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from src.canonical.model import Document
from src.delta.engine import DeltaItem


def build_report_json(doc_a: Document, doc_b: Document, items: list[DeltaItem]) -> dict:
    counts = defaultdict(int)
    for it in items:
        counts[it.kind] += 1
    return {
        "pid_a": doc_a.pid, "pid_b": doc_b.pid,
        "revision_a": doc_a.revision, "revision_b": doc_b.revision,
        "format_a": doc_a.format, "format_b": doc_b.format,
        "counts": dict(counts),
        "total": len(items),
        "items": [it.to_dict() for it in items],
    }


def build_report_markdown(doc_a: Document, doc_b: Document, items: list[DeltaItem]) -> str:
    counts = defaultdict(int)
    for it in items:
        counts[it.kind] += 1

    lines = [
        f"# Delta Report: {doc_a.pid} ({doc_a.revision}) → {doc_b.pid} ({doc_b.revision})",
        "",
        f"- Format: `{doc_a.format}` → `{doc_b.format}`",
        f"- **{counts.get('added', 0)} added**, **{counts.get('removed', 0)} removed**, "
        f"**{counts.get('modified', 0)} modified** ({len(items)} total changes)",
        "",
    ]

    by_sheet: dict[int, list[DeltaItem]] = defaultdict(list)
    for it in items:
        by_sheet[it.sheet].append(it)

    for sheet_idx in sorted(by_sheet):
        sheet_items = by_sheet[sheet_idx]
        label = sheet_items[0].sheet_label or f"Sheet {sheet_idx}"
        lines.append(f"## {label} (sheet {sheet_idx})")
        lines.append("")
        for kind in ("modified", "added", "removed"):
            group = [it for it in sheet_items if it.kind == kind]
            if not group:
                continue
            lines.append(f"### {kind.capitalize()} ({len(group)})")
            for it in sorted(group, key=lambda x: -x.confidence):
                flag = " _(LLM-assisted description)_" if it.llm_assisted else ""
                lines.append(f"- **[{it.id}]** {it.description} "
                              f"— type: `{it.element_type}`, confidence: {it.confidence:.2f}{flag}")
            lines.append("")

    return "\n".join(lines)


def write_report(doc_a: Document, doc_b: Document, items: list[DeltaItem], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "delta.json"
    md_path = out_dir / "delta.md"
    json_path.write_text(json.dumps(build_report_json(doc_a, doc_b, items), indent=2))
    md_path.write_text(build_report_markdown(doc_a, doc_b, items))
    return json_path, md_path
