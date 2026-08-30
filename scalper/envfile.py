"""Load a local .env without overriding a real environment."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path | None = None) -> Path | None:
    """Load KEY=value lines from .env. Existing os.environ keys win."""
    p = Path(path) if path is not None else Path(__file__).resolve().parent.parent / ".env"
    if not p.is_file():
        return None
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[7:].strip()
        value = value.strip().strip("'").strip('"')
        # Empty shell/systemd values do not block .env (KALSHI_API_KEY= is common).
        if key and not (os.environ.get(key) or "").strip():
            os.environ[key] = value
    return p
