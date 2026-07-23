"""Interactive grounded chat over two PIDs + their delta report.

Usage:
    python -m src.chat.cli --pair native_pdf
    python -m src.chat.cli --pid-a path/to/A.pdf --pid-b path/to/B.pdf

CLI chosen over a web UI to keep the reproducible-run bar low (no server,
no browser needed) while still satisfying "CLI, API, or minimal web UI --
your call" from the assignment.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex
from src.chat.llm import AnthropicClient
from src.config import CONFIG
from src.observability.logging import bind, get_logger
from src.observability.tracing import trace as trace_ctx
from src.pipeline import run_pair

log = get_logger("chat.cli")


def _resolve_pair(pair: str) -> tuple[Path, Path]:
    base = CONFIG.data_dir / pair
    a = glob.glob(str(base / "A.*"))
    b = glob.glob(str(base / "B.*"))
    if not a or not b:
        raise SystemExit(f"No sample pair found at {base} (expected A.* and B.*)")
    return Path(a[0]), Path(b[0])


def main(argv=None):
    p = argparse.ArgumentParser(description="Grounded chat over two PIDs + delta report")
    p.add_argument("--pair", help="Sample pair name under data/samples/ (e.g. native_pdf, scanned_pdf, dxf)")
    p.add_argument("--pid-a", help="Path to revision A")
    p.add_argument("--pid-b", help="Path to revision B")
    p.add_argument("--ask", help="Ask one question non-interactively and exit (for scripting/eval)")
    p.add_argument("--out-dir", default=None, help="Where to write the delta report")
    args = p.parse_args(argv)

    if args.pair:
        path_a, path_b = _resolve_pair(args.pair)
        pid_a, pid_b = f"{args.pair}-A", f"{args.pair}-B"
        out_dir = args.out_dir or (CONFIG.root / "reports" / args.pair)
    elif args.pid_a and args.pid_b:
        path_a, path_b = Path(args.pid_a), Path(args.pid_b)
        pid_a, pid_b = path_a.stem, path_b.stem
        out_dir = args.out_dir or (CONFIG.root / "reports" / "adhoc")
    else:
        raise SystemExit("Provide either --pair NAME or both --pid-a and --pid-b")

    print(f"Ingesting {path_a.name} + {path_b.name} and computing delta...", file=sys.stderr)
    doc_a, doc_b, items, json_path, md_path = run_pair(path_a, path_b, pid_a, pid_b, out_dir)
    print(f"Delta report: {md_path} ({len(items)} changes)", file=sys.stderr)

    index = RetrievalIndex(doc_a, doc_b, items)
    llm = AnthropicClient()

    def ask(question: str):
        with trace_ctx("chat_turn") as t:
            rlog = bind(log, trace_id=t.trace_id)
            result = answer_question(question, index, llm, top_k=CONFIG.chat_top_k, trace=t)
            rlog.info("chat turn complete", extra={
                "stage": "answer", "grounded": result.grounded,
                "citations_valid": len(result.citations_valid),
                "citations_invalid": len(result.citations_invalid),
                "cost_usd": result.llm_cost_usd,
            })
        print(f"\n{result.text}\n")
        if result.citations_invalid:
            print(f"  [warning: {len(result.citations_invalid)} ungrounded citation(s) removed]",
                  file=sys.stderr)
        print(f"  (sources considered: {[c.source_id for c in result.retrieved]}, "
              f"cost: ${result.llm_cost_usd:.5f})", file=sys.stderr)

    if args.ask:
        ask(args.ask)
        return

    print("Grounded chat ready. Ask about either revision or what changed. Ctrl-D to exit.\n")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        ask(question)


if __name__ == "__main__":
    main()
