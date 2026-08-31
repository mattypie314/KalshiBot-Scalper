"""KALSHI15 — Matt's KalshiBot campaign desk (the other bot, not the IOC scalper)."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

from .campaign_status import snapshot


def desk_port() -> int:
    raw = (os.environ.get("KALSHI15_PORT") or os.environ.get("KALSHIBOT_PORT") or "8000").strip()
    try:
        return int(raw)
    except ValueError:
        return 8000


def looks_like_kalshibot(path: Path) -> bool:
    if not path.is_dir():
        return False
    pkg = path / "kalshibot"
    return (pkg / "__init__.py").is_file() or (pkg / "__main__.py").is_file()


def find_root() -> Path | None:
    env = (os.environ.get("KALSHI15_ROOT") or os.environ.get("KALSHIBOT_ROOT") or "").strip()
    here = Path(__file__).resolve().parent.parent
    if env:
        path = Path(env).expanduser()
        return path.resolve() if looks_like_kalshibot(path) else None
    candidates = [
        Path.home() / "KalshiBot",
        here.parent / "KalshiBot",
        here / "KalshiBot",
    ]
    seen: set[Path] = set()
    for raw in candidates:
        try:
            path = raw.expanduser().resolve()
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        if looks_like_kalshibot(path):
            return path
    return None


def desk_up(host: str = "127.0.0.1", port: int | None = None, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port or desk_port())), timeout=timeout):
            return True
    except OSError:
        return False


def board() -> dict[str, Any]:
    snap = snapshot()
    snap["name"] = "KALSHI15"
    snap["desk_up"] = desk_up()
    snap["desk_port"] = desk_port()
    snap["root"] = str(find_root() or "")
    return snap
