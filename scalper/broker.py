"""Paper broker. Live Kalshi orders stay off unless SCALPER_LIVE=1 and keys exist."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Fill:
    ts: float
    asset: str
    ticker: str
    side: str
    action: str  # buy / sell
    price: float
    qty: float
    fee: float
    is_taker: bool
    reason: str


@dataclass
class Position:
    asset: str
    ticker: str
    side: str  # yes / no
    qty: float
    entry: float
    entry_ts: float
    fees: float
    target: float
    reason_in: str
    kind: str


@dataclass
class PaperBroker:
    cash: float
    realized: float = 0.0
    fees_paid: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)

    def buy(self, pos: Position, is_taker: bool, fee: float, reason: str) -> Fill:
        cost = pos.entry * pos.qty + fee
        self.cash -= cost
        self.fees_paid += fee
        self.positions[pos.asset] = pos
        fill = Fill(
            ts=pos.entry_ts,
            asset=pos.asset,
            ticker=pos.ticker,
            side=pos.side,
            action="buy",
            price=pos.entry,
            qty=pos.qty,
            fee=fee,
            is_taker=is_taker,
            reason=reason,
        )
        self.fills.append(fill)
        return fill

    def close(self, asset: str, price: float, fee: float, reason: str, is_taker: bool = True) -> dict | None:
        pos = self.positions.pop(asset, None)
        if not pos:
            return None
        proceeds = price * pos.qty - fee
        self.cash += proceeds
        self.fees_paid += fee
        pnl = (price - pos.entry) * pos.qty - pos.fees - fee
        self.realized += pnl
        fill = Fill(
            ts=time.time(),
            asset=asset,
            ticker=pos.ticker,
            side=pos.side,
            action="sell",
            price=price,
            qty=pos.qty,
            fee=fee,
            is_taker=is_taker,
            reason=reason,
        )
        self.fills.append(fill)
        rec = {
            "id": str(uuid.uuid4())[:8],
            "asset": asset,
            "ticker": pos.ticker,
            "kind": pos.kind,
            "side": pos.side,
            "qty": pos.qty,
            "entry": pos.entry,
            "exit": price,
            "pnl": pnl,
            "hold_s": fill.ts - pos.entry_ts,
            "reason_in": pos.reason_in,
            "reason_out": reason,
            "ts": fill.ts,
        }
        self.trades.append(rec)
        return rec
