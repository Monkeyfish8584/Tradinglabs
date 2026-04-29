from __future__ import annotations

import ast
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def main() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    required_tokens = [
        "prepare_tradingview_ohlc",
        "compute_daily_attack_stats",
        "compute_ger40_morning_stats",
        "Previous Day High/Low Attack",
    ]
    for token in required_tokens:
        if token not in source:
            raise AssertionError(f"Expected token missing from app.py: {token}")

    print("Pure-Python smoke test passed (AST parse + key token checks).")


if __name__ == "__main__":
    main()
