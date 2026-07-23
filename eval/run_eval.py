"""`make eval` -- runs the full pipeline against every labeled dataset pair
and prints a scorecard: delta P/R/F1 (deterministic) and chat correctness +
groundedness (LLM-judge + a deterministic citation-validity/keyword
cross-check). Writes eval/results/latest.json and diffs against the
previous run so a regression is visible run-over-run. Always includes a
candid failure table -- misses and low-scoring answers are printed, not
hidden.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex
from src.chat.llm import AnthropicClient
from src.config import CONFIG
from src.pipeline import run_pair
from eval.metrics import keyword_correctness, llm_judge_correctness, score_delta

console = Console()
RESULTS_DIR = CONFIG.eval_dir / "results"


def discover_pairs() -> list[str]:
    ds = CONFIG.eval_dir / "datasets"
    return sorted(p.name for p in ds.iterdir() if (p / "expected_delta.json").exists())


def _sample_files(pair: str) -> tuple[Path, Path]:
    base = CONFIG.data_dir / pair
    import glob
    a = glob.glob(str(base / "A.*")); b = glob.glob(str(base / "B.*"))
    if not a or not b:
        raise FileNotFoundError(f"No sample files for pair '{pair}' under {base}")
    return Path(a[0]), Path(b[0])


def run_eval(pairs: list[str], use_llm: bool) -> dict:
    llm = None
    if use_llm:
        try:
            llm = AnthropicClient()
        except ValueError as e:
            console.print(f"[yellow]{e} -- chat scoring will be skipped, delta metrics still run.[/yellow]")
            use_llm = False

    results = {}
    for pair in pairs:
        console.rule(f"[bold]{pair}")
        path_a, path_b = _sample_files(pair)
        doc_a, doc_b, items, json_path, md_path = run_pair(
            path_a, path_b, f"{pair}-A", f"{pair}-B", out_dir=RESULTS_DIR / "reports" / pair)

        expected = json.loads((CONFIG.eval_dir / "datasets" / pair / "expected_delta.json").read_text())
        delta_score = score_delta(expected, items)

        qa_path = CONFIG.eval_dir / "datasets" / pair / "qa.jsonl"
        qa_rows = [json.loads(l) for l in qa_path.read_text().splitlines() if l.strip()] if qa_path.exists() else []

        chat_rows = []
        if qa_rows:
            index = RetrievalIndex(doc_a, doc_b, items)
            for row in qa_rows:
                q = row["question"]
                unanswerable = row.get("unanswerable", False)
                kw = row.get("expected_keywords", [])
                if use_llm:
                    ans = answer_question(q, index, llm, top_k=CONFIG.chat_top_k)
                    kw_score = keyword_correctness(kw, ans.text, unanswerable)
                    judge = llm_judge_correctness(q, kw, ans.text, unanswerable, llm)
                    chat_rows.append({
                        "question": q, "answer": ans.text, "grounded": ans.grounded,
                        "citations_valid": ans.citations_valid, "citations_invalid": ans.citations_invalid,
                        "keyword_score": kw_score, "judge_score": judge["score"], "judge_reason": judge["reason"],
                        "cost_usd": ans.llm_cost_usd + judge.get("cost_usd", 0.0),
                    })
                else:
                    chat_rows.append({"question": q, "answer": None, "skipped": True})

        results[pair] = {
            "delta": {
                "precision": delta_score.precision, "recall": delta_score.recall, "f1": delta_score.f1,
                "tp": delta_score.true_positives, "fp": delta_score.false_positives, "fn": delta_score.false_negatives,
                "misses": delta_score.misses, "unexplained": delta_score.unexplained,
            },
            "chat": chat_rows,
        }
    return results


def print_scorecard(results: dict):
    t = Table(title="Delta scorecard")
    t.add_column("pair"); t.add_column("precision", justify="right"); t.add_column("recall", justify="right")
    t.add_column("f1", justify="right"); t.add_column("tp/fp/fn", justify="right")
    for pair, r in results.items():
        d = r["delta"]
        t.add_row(pair, f"{d['precision']:.2f}", f"{d['recall']:.2f}", f"{d['f1']:.2f}",
                   f"{d['tp']}/{d['fp']}/{d['fn']}")
    console.print(t)

    any_chat = any(r["chat"] and not r["chat"][0].get("skipped") for r in results.values())
    if any_chat:
        t2 = Table(title="Chat scorecard")
        t2.add_column("pair"); t2.add_column("question", max_width=40)
        t2.add_column("grounded"); t2.add_column("keyword"); t2.add_column("judge")
        for pair, r in results.items():
            for row in r["chat"]:
                if row.get("skipped"):
                    continue
                t2.add_row(pair, row["question"], "yes" if row["grounded"] else "NO",
                           f"{row['keyword_score']:.2f}",
                           f"{row['judge_score']}" if row["judge_score"] is not None else "?")
        console.print(t2)

    console.print("\n[bold]Candid failure table[/bold]")
    any_failure = False
    for pair, r in results.items():
        for m in r["delta"]["misses"]:
            any_failure = True
            console.print(f"  [red]MISS[/red] [{pair}] delta not found: {m.get('description') or m.get('text_anchor')}")
        for u in r["delta"]["unexplained"]:
            any_failure = True
            console.print(f"  [red]EXTRA[/red] [{pair}] unexplained predicted item: {u['description']}")
        for row in r["chat"]:
            if row.get("skipped"):
                continue
            if row["judge_score"] is not None and row["judge_score"] < 1.0:
                any_failure = True
                console.print(f"  [yellow]WEAK[/yellow] [{pair}] '{row['question']}' -> judge={row['judge_score']} "
                               f"({row['judge_reason']})")
            if not row["grounded"]:
                any_failure = True
                console.print(f"  [red]UNGROUNDED[/red] [{pair}] '{row['question']}' cited "
                               f"{row['citations_invalid']} not present in retrieved context")
    if not any_failure:
        console.print("  none recorded in this run")


def diff_against_previous(new_results: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = RESULTS_DIR / "latest.json"
    if latest_path.exists():
        prev = json.loads(latest_path.read_text())
        console.print("\n[bold]Run-over-run delta[/bold]")
        for pair in new_results:
            if pair not in prev:
                console.print(f"  {pair}: new pair, no prior run")
                continue
            for metric in ("precision", "recall", "f1"):
                old_v = prev[pair]["delta"][metric]
                new_v = new_results[pair]["delta"][metric]
                if old_v != new_v:
                    arrow = "↑" if new_v > old_v else "↓"
                    console.print(f"  {pair}.{metric}: {old_v:.2f} -> {new_v:.2f} {arrow}")
        shutil.copy(latest_path, RESULTS_DIR / "previous.json")
    latest_path.write_text(json.dumps(new_results, indent=2, default=str))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", nargs="*", default=None, help="subset of dataset pairs to run")
    p.add_argument("--no-llm", action="store_true", help="skip chat/LLM-judge scoring (delta metrics only)")
    args = p.parse_args()

    pairs = args.pairs or discover_pairs()
    if not pairs:
        console.print("[red]No eval datasets found under eval/datasets/[/red]")
        sys.exit(1)

    results = run_eval(pairs, use_llm=not args.no_llm)
    print_scorecard(results)
    diff_against_previous(results)


if __name__ == "__main__":
    main()
