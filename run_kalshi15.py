#!/usr/bin/env python3
"""Start KALSHI15 — the campaign / post-only KalshiBot desk.

This is the other bot, not the IOC scalper. Do not run both on real money
against the same BTC 15m book.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scalper.envfile import load_dotenv  # noqa: E402
from scalper.kalshi15 import desk_port, find_root  # noqa: E402

load_dotenv(ROOT / ".env")


def main() -> None:
    bot = find_root()
    if bot is None:
        print("KALSHI15 needs github.com/mattypie314/KalshiBot on this machine.", flush=True)
        print("  git clone https://github.com/mattypie314/KalshiBot.git ~/KalshiBot", flush=True)
        print("  cd ~/KalshiBot && python3 -m pip install -r requirements.txt", flush=True)
        print("Or set KALSHI15_ROOT to that checkout.", flush=True)
        raise SystemExit(2)
    key = (os.environ.get("KALSHI_API_KEY_ID") or os.environ.get("KALSHI_API_KEY") or "").strip()
    if key and not (os.environ.get("KALSHI_API_KEY_ID") or "").strip():
        os.environ["KALSHI_API_KEY_ID"] = key
    host = (os.environ.get("KALSHI15_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    port = str(desk_port())
    print(f"KALSHI15 root          {bot}", flush=True)
    print(f"KALSHI15 desk          http://127.0.0.1:{port}", flush=True)
    print("Leave KALSHI_LIVE unset unless you mean campaign orders.", flush=True)
    print("Do not arm SCALPER real money on BTC at the same time.", flush=True)
    os.environ["PYTHONPATH"] = str(bot) + os.pathsep + os.environ.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "kalshibot", "serve", "--host", host, "--port", port]
    code = subprocess.call(cmd, cwd=str(bot), env=os.environ)
    if code != 0:
        print("If that said No module named kalshibot:", flush=True)
        print(f"  cd {bot} && python3 -m pip install -r requirements.txt", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
