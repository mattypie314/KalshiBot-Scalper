"""Signed Kalshi portfolio client for real-money IOC orders."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import kalshi_base
from .fees import taker_fee

UA = "ScottyScalper3000/1.0"


@dataclass
class KalshiCreds:
    key_id: str
    private_pem: str


@dataclass
class LiveFill:
    ok: bool
    qty: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    order_id: str = ""
    remaining: float = 0.0
    error: str = ""


Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict]]


def load_creds() -> KalshiCreds | None:
    key_id = (
        os.environ.get("KALSHI_API_KEY")
        or os.environ.get("KALSHI_API_KEY_ID")
        or os.environ.get("KALSHI_ACCESS_KEY")
        or os.environ.get("KALSHI_KEY_ID")
        or ""
    ).strip()
    pem = (os.environ.get("KALSHI_PRIVATE_KEY") or "").replace("\\n", "\n").strip()
    path = (os.environ.get("KALSHI_PRIVATE_KEY_PATH") or "").strip()
    if not pem and path:
        p = Path(path).expanduser()
        if p.is_file():
            pem = p.read_text().strip()
    if key_id and pem and "BEGIN" in pem:
        return KalshiCreds(key_id=key_id, private_pem=pem)
    return None


def sign_request(private_pem: str, timestamp: str, method: str, path: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    path_no_query = path.split("?", 1)[0]
    message = f"{timestamp}{method.upper()}{path_no_query}".encode()
    sig = key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def _default_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode() or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"message": raw or str(e)}
        payload.setdefault("message", str(e))
        return e.code, payload


def parse_market_positions(data: dict | None) -> list[dict]:
    """Normalize GET /portfolio/positions into {ticker, side, qty, entry, fees}."""
    rows = []
    if isinstance(data, dict):
        rows = data.get("market_positions") or data.get("positions") or []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        qty = _f(row.get("position_fp") or row.get("position") or row.get("quantity"))
        if abs(qty) < 1:
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        side = "yes" if qty > 0 else "no"
        abs_qty = abs(qty)
        exposure = _f(row.get("market_exposure_dollars"))
        if exposure <= 0 and row.get("market_exposure") not in (None, ""):
            exposure = _f(row.get("market_exposure"))
        fees = _f(row.get("fees_paid_dollars"))
        if fees <= 0 and row.get("fees_paid") not in (None, ""):
            fees = _f(row.get("fees_paid"))
        entry = exposure / abs_qty if exposure > 0 else 0.50
        entry = min(max(entry, 0.01), 0.99)
        out.append(
            {
                "ticker": ticker,
                "side": side,
                "qty": abs_qty,
                "entry": entry,
                "fees": max(fees, 0.0),
            }
        )
    return out


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


class KalshiClient:
    def __init__(self, creds: KalshiCreds | None = None, transport: Transport | None = None, base: str = "") -> None:
        self.creds = creds
        self.transport = transport or _default_transport
        self.base = (base or kalshi_base()).rstrip("/")

    @classmethod
    def from_env(cls) -> "KalshiClient":
        return cls(load_creds())

    @property
    def ready(self) -> bool:
        return self.creds is not None

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        if not self.creds:
            raise RuntimeError("Kalshi keys missing")
        rel = path if path.startswith("/") else f"/{path}"
        url = self.base + rel
        sign_path = urllib.parse.urlparse(url).path
        ts = str(int(time.time() * 1000))
        sig = sign_request(self.creds.private_pem, ts, method, sign_path)
        headers = {
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.creds.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }
        body = json.dumps(payload).encode() if payload is not None else None
        return self.transport(method.upper(), url, headers, body)

    def balance(self) -> float:
        code, data = self.request("GET", "/portfolio/balance")
        if code >= 400:
            raise RuntimeError(data.get("message") or data.get("error") or f"balance HTTP {code}")
        if data.get("balance_dollars") not in (None, ""):
            return _f(data.get("balance_dollars"))
        # Official docs: balance is integer cents.
        cents = _f(data.get("balance"))
        return cents / 100.0

    def market_position_count(self) -> int:
        try:
            return len(self.open_positions())
        except Exception:
            return 0

    def open_positions(self) -> list[dict]:
        code, data = self.request("GET", "/portfolio/positions")
        if code >= 400:
            raise RuntimeError(data.get("message") or data.get("error") or f"positions HTTP {code}")
        return parse_market_positions(data)

    def ioc(
        self,
        ticker: str,
        book_side: str,
        qty: float,
        yes_price: float,
        *,
        reduce_only: bool = False,
    ) -> LiveFill:
        """Immediate-or-cancel limit on the YES book. bid=buy YES, ask=sell YES."""
        if book_side not in {"bid", "ask"}:
            return LiveFill(ok=False, error=f"bad side {book_side}")
        if qty < 1 or yes_price <= 0 or yes_price >= 1:
            return LiveFill(ok=False, error="bad live size/price")
        body = {
            "ticker": ticker,
            "client_order_id": str(uuid.uuid4()),
            "side": book_side,
            "count": f"{qty:.2f}",
            "price": f"{yes_price:.4f}",
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
            "reduce_only": bool(reduce_only),
        }
        code, data = self.request("POST", "/portfolio/events/orders", body)
        if code >= 400:
            return LiveFill(ok=False, error=str(data.get("message") or data.get("error") or f"order HTTP {code}"))
        filled = _f(data.get("fill_count"))
        remaining = _f(data.get("remaining_count"))
        avg = _f(data.get("average_fill_price"), yes_price if filled else 0.0)
        fee = _f(data.get("average_fee_paid")) * filled if data.get("average_fee_paid") not in (None, "") else taker_fee(avg or yes_price, filled)
        if filled < 1:
            return LiveFill(
                ok=False,
                qty=filled,
                remaining=remaining,
                order_id=str(data.get("order_id") or ""),
                error="live IOC unfilled",
            )
        return LiveFill(
            ok=True,
            qty=filled,
            price=avg or yes_price,
            fee=fee,
            order_id=str(data.get("order_id") or ""),
            remaining=remaining,
        )
