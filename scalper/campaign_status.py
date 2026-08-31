"""Read Matt's KalshiBot campaign book without importing that repo."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def tracker_path() -> Path:
    raw = (os.environ.get("TRACKER_PATH") or os.environ.get("KALSHIBOT_TRACKER") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".kalshi" / "crypto-campaign.json"


def snapshot() -> dict[str, Any]:
    path = tracker_path()
    if not path.is_file():
        return {
            "ok": False,
            "present": False,
            "tracker_path": str(path),
            "error": "KalshiBot campaign file not found. On the Pi: clone github.com/mattypie314/KalshiBot and run python -m kalshibot campaign run",
        }
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "present": False, "tracker_path": str(path), "error": "campaign file is not valid JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "present": False, "tracker_path": str(path), "error": "campaign file is not an object"}
    sizing = data.get("sizing") if isinstance(data.get("sizing"), dict) else {}
    tickets = [t for t in (data.get("tickets") or []) if isinstance(t, dict) and t.get("status") == "open"]
    rests = [r for r in (data.get("rests") or []) if isinstance(r, dict) and r.get("status") == "open"]
    log = list(reversed((data.get("log") or [])[-12:]))
    return {
        "ok": True,
        "present": True,
        "tracker_path": str(path),
        "bankroll": data.get("bankroll"),
        "realized": data.get("realized"),
        "kalshi_cash": data.get("kalshi_cash"),
        "kalshi_total_value": data.get("kalshi_total_value"),
        "halted": bool(sizing.get("halted", False)),
        "maker_auto": bool(sizing.get("maker_auto", True)),
        "follow_kalshi_cash": bool(sizing.get("follow_kalshi_cash", True)),
        "open_tickets": tickets,
        "rests": rests,
        "log": log,
        "updated_at": data.get("updated_at"),
        "warn": "Do not run KalshiBot 15m LIVE on BTC at the same time as this scalper LIVE. They fight the same book.",
    }
