#!/usr/bin/env python3
"""Run Scotty's 15m Crypto Scalper 3000."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scalper.envfile import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from scalper.config import load_config  # noqa: E402
from scalper.engine import Engine  # noqa: E402
from scalper.netinfo import dashboard_urls  # noqa: E402
from scalper.server import serve  # noqa: E402


def main() -> None:
    cfg = load_config()
    engine = Engine(cfg)
    serve(engine, cfg.host, cfg.port)
    urls = dashboard_urls(cfg.port, cfg.host)
    print(f"Scalper 3000 dashboard  {urls[0]}", flush=True)
    if len(urls) > 1:
        print(f"Phone (same Wi-Fi)      {urls[1]}", flush=True)
        for extra in urls[2:]:
            print(f"  also                  {extra}", flush=True)
    print("On a phone: open that URL, enter SCALPER_DASHBOARD_TOKEN, Add to Home Screen.", flush=True)
    print(f"Markets: {', '.join(cfg.assets)}", flush=True)
    print("PAPER mode. Limits only. 3–5% size. Out at +4–8¢ or when the edge dies.", flush=True)
    try:
        engine.loop()
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
