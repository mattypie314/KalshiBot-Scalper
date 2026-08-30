"""Shared keep-alive HTTP pool — avoid a fresh TLS handshake on every tick."""

from __future__ import annotations

import json
from typing import Any

import urllib3

UA = "ScottyScalper3000/1.0"

# One process-wide pool. Reuses TCP+TLS to Kalshi / Coinbase / etc.
_POOL = urllib3.PoolManager(
    num_pools=16,
    maxsize=32,
    headers={"User-Agent": UA, "Accept": "application/json"},
    retries=False,
)


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 8.0,
) -> tuple[int, Any]:
    """Return (status_code, parsed_json_or_dict). Keep-alive via urllib3 pool."""
    to = urllib3.Timeout(connect=min(3.0, timeout), read=timeout)
    resp = _POOL.request(
        method.upper(),
        url,
        body=body,
        headers=headers,
        timeout=to,
        preload_content=True,
    )
    raw = resp.data.decode() if resp.data else ""
    try:
        payload: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"message": raw or f"HTTP {resp.status}"}
    if not isinstance(payload, (dict, list)):
        payload = {"data": payload}
    return int(resp.status), payload


def http_get_json(url: str, timeout: float = 8.0) -> Any:
    code, data = http_json("GET", url, timeout=timeout)
    if code >= 400:
        msg = data.get("message") if isinstance(data, dict) else str(data)
        raise RuntimeError(msg or f"HTTP {code}")
    return data
