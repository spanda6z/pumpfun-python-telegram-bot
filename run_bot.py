#!/usr/bin/env python3
"""Assemble payload and run the Pump.fun Telegram bot."""
from pathlib import Path
import base64, runpy, tempfile

here = Path(__file__).resolve().parent
parts = sorted(here.glob("bot_payload_*.txt"), key=lambda p: int(p.stem.split("_")[-1]))
b64 = "".join(p.read_text().strip() for p in parts)
code = base64.b64decode(b64).decode()
path = Path(tempfile.gettempdir()) / "pumpfun_single_file_bot.py"
path.write_text(code)
runpy.run_path(str(path), run_name="__main__")
