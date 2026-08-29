#!/usr/bin/env python3
"""Run Scotty's 15m Crypto Scalper 3000 on BTC only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ["SCALPER_ASSETS"] = "BTC"

from run import main  # noqa: E402


if __name__ == "__main__":
    main()
