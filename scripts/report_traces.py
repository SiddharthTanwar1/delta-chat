"""`make metrics` -- reads traces/traces.jsonl and prints the inspectable
metrics surface the observability requirement asks for: latency
percentiles, total tokens/cost, delta counts, retrieval hit stats, and any
failed spans (never silently swallowed).
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.config import CONFIG

console = Console()


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round(p / 100 * (len(values) - 1)))))
    return values[k]


def main():
    path = CONFIG.traces_dir / "traces.jsonl"
    if not path.exists():
        console.print(f"[yellow]No traces yet at {path} -- run `make run` or `make chat` first.[/yellow]")
        return

    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not records:
        console.print("[yellow]traces.jsonl is empty.[/yellow]")
        return

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_kind[r["kind"]].append(r)

    total_spans = sum(len(r["spans"]) for r in records)
    console.print(f"\n[bold]Observability summary[/bold] -- {len(records)} traces, "
                  f"{total_spans} total spans across all traces\n")

    t1 = Table(title="Latency by request kind")
    t1.add_column("kind"); t1.add_column("count", justify="right")
    t1.add_column("p50 ms", justify="right"); t1.add_column("p95 ms", justify="right")
    t1.add_column("errors", justify="right")
    for kind, recs in by_kind.items():
        durs = [r["duration_ms"] for r in recs]
        errs = sum(1 for r in recs if r["status"] == "error")
        t1.add_row(kind, str(len(recs)), f"{_pct(durs,50):.1f}", f"{_pct(durs,95):.1f}",
                    f"[red]{errs}[/red]" if errs else "0")
    console.print(t1)

    total_in_tok = total_out_tok = 0
    total_cost = 0.0
    n_llm_calls = 0
    for r in records:
        for span in r["spans"]:
            out = span.get("output")
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except Exception:
                    out = None
            if isinstance(out, dict) and "cost_usd" in out:
                n_llm_calls += 1
                total_in_tok += out.get("input_tokens", 0)
                total_out_tok += out.get("output_tokens", 0)
                total_cost += out.get("cost_usd", 0.0)

    t2 = Table(title="LLM telemetry")
    t2.add_column("metric"); t2.add_column("value", justify="right")
    t2.add_row("LLM calls", str(n_llm_calls))
    t2.add_row("input tokens", str(total_in_tok))
    t2.add_row("output tokens", str(total_out_tok))
    t2.add_row("est. cost (USD)", f"${total_cost:.5f}")
    console.print(t2)

    # delta counts observed across delta_run traces
    delta_counts = Counter()
    for r in by_kind.get("delta_run", []):
        for span in r["spans"]:
            if span["name"] == "compute_delta":
                out = span.get("output")
                if isinstance(out, str):
                    try:
                        out = json.loads(out)
                    except Exception:
                        out = {}
                if isinstance(out, dict):
                    for k in ("added", "removed", "modified"):
                        delta_counts[k] += out.get(k, 0)
    if delta_counts:
        t3 = Table(title="Delta counts (cumulative across delta_run traces)")
        t3.add_column("kind"); t3.add_column("count", justify="right")
        for k, v in delta_counts.items():
            t3.add_row(k, str(v))
        console.print(t3)

    # retrieval hit stats
    retrieval_sizes = []
    for r in by_kind.get("chat_turn", []):
        for span in r["spans"]:
            if span["name"] == "retrieve":
                out = span.get("output")
                if isinstance(out, str):
                    try:
                        out = json.loads(out)
                    except Exception:
                        out = {}
                if isinstance(out, dict):
                    retrieval_sizes.append(out.get("n_chunks", 0))
    if retrieval_sizes:
        console.print(f"\nRetrieval hit stats: avg {statistics.mean(retrieval_sizes):.1f} chunks/query, "
                       f"{sum(1 for s in retrieval_sizes if s == 0)} zero-hit queries out of {len(retrieval_sizes)}")

    # failure visibility
    failed_spans = [(r["trace_id"], s) for r in records for s in r["spans"] if s["status"] == "error"]
    if failed_spans:
        console.print(f"\n[red]{len(failed_spans)} failed span(s):[/red]")
        for trace_id, s in failed_spans[:10]:
            console.print(f"  trace={trace_id} span={s['name']}: {s['error'].splitlines()[0]}")
    else:
        console.print("\n[green]No failed spans recorded.[/green]")


if __name__ == "__main__":
    main()
