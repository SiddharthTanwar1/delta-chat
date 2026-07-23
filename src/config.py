"""Central config: everything tunable lives here, sourced from env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "claude-sonnet-5")
    judge_model: str = os.environ.get("JUDGE_MODEL") or os.environ.get("LLM_MODEL", "claude-sonnet-5")

    delta_match_min: float = _float("DELTA_MATCH_MIN", 0.35)
    delta_move_threshold_px: float = _float("DELTA_MOVE_THRESHOLD_PX", 12.0)

    chat_top_k: int = int(os.environ.get("CHAT_TOP_K", "8"))

    price_input_per_1m: float = _float("PRICE_INPUT_PER_1M", 3.00)
    price_output_per_1m: float = _float("PRICE_OUTPUT_PER_1M", 15.00)

    root: Path = ROOT
    traces_dir: Path = ROOT / "traces"
    data_dir: Path = ROOT / "data" / "samples"
    eval_dir: Path = ROOT / "eval"


CONFIG = Config()
CONFIG.traces_dir.mkdir(parents=True, exist_ok=True)
