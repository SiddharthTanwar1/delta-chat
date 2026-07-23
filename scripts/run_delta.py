"""`make run` -- ingest a PID pair and produce a delta report. No chat, no
LLM call needed; this is the fast, deterministic half of the pipeline.

Usage: python scripts/run_delta.py --pair native_pdf
       python scripts/run_delta.py --pid-a A.pdf --pid-b B.pdf --out-dir reports/adhoc
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from src.config import CONFIG
from src.pipeline import run_pair


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pair", help="Sample pair name under data/samples/")
    p.add_argument("--pid-a"); p.add_argument("--pid-b")
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    if args.pair:
        base = CONFIG.data_dir / args.pair
        a = glob.glob(str(base / "A.*")); b = glob.glob(str(base / "B.*"))
        if not a or not b:
            sys.exit(f"No sample pair found at {base}")
        path_a, path_b = Path(a[0]), Path(b[0])
        pid_a, pid_b = f"{args.pair}-A", f"{args.pair}-B"
        out_dir = args.out_dir or CONFIG.root / "reports" / args.pair
    elif args.pid_a and args.pid_b:
        path_a, path_b = Path(args.pid_a), Path(args.pid_b)
        pid_a, pid_b = path_a.stem, path_b.stem
        out_dir = args.out_dir or CONFIG.root / "reports" / "adhoc"
    else:
        sys.exit("Provide either --pair NAME or both --pid-a and --pid-b")

    doc_a, doc_b, items, json_path, md_path = run_pair(path_a, path_b, pid_a, pid_b, out_dir)
    print(f"\n{len(items)} changes detected -> {md_path}\n")
    print(md_path.read_text())


if __name__ == "__main__":
    main()
