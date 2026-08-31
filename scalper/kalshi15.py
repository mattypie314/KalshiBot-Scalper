"""KALSHI15 — Matt's KalshiBot campaign desk (the other bot, not the IOC scalper)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .campaign_status import snapshot

_lock = threading.Lock()
_proc: subprocess.Popen | None = None


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


def log_path() -> Path:
    path = Path.home() / ".kalshi"
    path.mkdir(parents=True, exist_ok=True)
    return path / "kalshi15-serve.log"


def _tail(path: Path, n: int = 12) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def child_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    key = (env.get("KALSHI_API_KEY_ID") or env.get("KALSHI_API_KEY") or "").strip()
    if key:
        env["KALSHI_API_KEY_ID"] = key
    return env


def serve_cmd(root: Path) -> list[str]:
    host = (os.environ.get("KALSHI15_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    return [sys.executable, "-m", "kalshibot", "serve", "--host", host, "--port", str(desk_port())]


def _fail_hint(tail: str, root: Path) -> str:
    low = (tail or "").lower()
    if "no module named" in low and ("uvicorn" in low or "kalshibot" in low):
        return f"Install KALSHI15 deps on the Pi: cd {root} && python3 -m pip install -r requirements.txt"
    if "address already in use" in low:
        return "Port 8000 is already in use. The desk may already be up."
    last = (tail.strip().splitlines() or [""])[-1].strip()
    return last or "KALSHI15 failed to start"


def start_desk(*, wait: float = 5.0) -> dict[str, Any]:
    """Launch `kalshibot serve` in the background. Never sets KALSHI_LIVE."""
    global _proc
    with _lock:
        if desk_up():
            out = board()
            out["ok"] = True
            out["started"] = False
            return out
        root = find_root()
        if root is None:
            return {
                "ok": False,
                "started": False,
                "desk_up": False,
                "root": "",
                "error": "KalshiBot is not on this Pi. Run: git clone https://github.com/mattypie314/KalshiBot.git ~/KalshiBot",
            }
        logp = log_path()
        try:
            logf = open(logp, "ab", buffering=0)
        except OSError as e:
            return {"ok": False, "started": False, "desk_up": False, "error": f"cannot write log: {e}"}
        try:
            _proc = subprocess.Popen(
                serve_cmd(root),
                cwd=str(root),
                env=child_env(root),
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            return {"ok": False, "started": False, "desk_up": False, "error": f"could not start: {e}"}
        deadline = time.time() + max(0.2, float(wait))
        while time.time() < deadline:
            if desk_up():
                out = board()
                out["ok"] = True
                out["started"] = True
                return out
            if _proc.poll() is not None:
                tail = _tail(logp)
                return {
                    "ok": False,
                    "started": False,
                    "desk_up": False,
                    "root": str(root),
                    "error": _fail_hint(tail, root),
                    "log_tail": tail,
                }
            time.sleep(0.15)
        tail = _tail(logp)
        if desk_up():
            out = board()
            out["ok"] = True
            out["started"] = True
            return out
        return {
            "ok": False,
            "started": False,
            "desk_up": False,
            "root": str(root),
            "error": _fail_hint(tail, root),
            "log_tail": tail,
        }
