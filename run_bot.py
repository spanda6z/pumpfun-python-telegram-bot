#!/usr/bin/env python3
"""Entry point for Railway — runs single_file_bot.py."""
import runpy
from pathlib import Path

target = Path(__file__).resolve().parent / "single_file_bot.py"
if not target.exists():
    raise SystemExit(
        "single_file_bot.py is missing.\n"
        "Add it from: https://github.com/spanda6z/pumpfun-telegram-bot/blob/main/python/single_file_bot.py"
    )
runpy.run_path(str(target), run_name="__main__")
