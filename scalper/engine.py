"""Main scalper loop: watch every tick, trade only a clear fast edge, get out."""

from __future__ import annotations

import traceback
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .book import Book
from .broker import PaperBroker, Position
from .config import ASSETS, ScalperConfig
from .fees import taker_fee
from .feeds import KalshiFeed, MarketSnap, SpotFeed
from .model import SpotHistory, Tick, VolState, fair_yes, vol_from_closes
from .risk import RiskState, allow_entry, size_contracts
from .signals import Signal, evaluate, exit_reason


@dataclass
class AssetState:
    asset: str
    market: MarketSnap | None = None
    spot: float = 0.0
    sources: dict = field(default_factory=dict)
    vol: VolState | None = None
    hist: SpotHistory = field(default_factory=SpotHistory)
    fair: float = 0.0
    signal: Signal | None = None
    seconds_left: float = 0.0
    locked_avg: float | None = None
    locked_secs: float = 0.0
    settlement_ticks: deque = field(default_factory=lambda: deque(maxlen=120))
    last_error: str = ""
    skip: str = ""


class Engine:
    def __init__(self, cfg: ScalperConfig) -> None:
        self.cfg = cfg
        self.spots = SpotFeed()
        self.kalshi = KalshiFeed()
        self.broker = PaperBroker(cash=cfg.bankroll)
        self.risk = RiskState()
        self.assets: dict[str, AssetState] = {a: AssetState(asset=a) for a in ASSETS}
        self.log: deque[dict] = deque(maxlen=250)
        self.started = time.time()
        self.tick_n = 0
        self.last_vol_refresh = 0.0
        self.last_rest_spot = 0.0
        self.running = False
        self.mode = "PAPER"
        if cfg.live:
            self.note("LIVE requested but no Kalshi keys in this environment — staying PAPER", "warn")

    def note(self, msg: str, level: str = "info", **extra: Any) -> None:
        self.log.appendleft({"ts": time.time(), "level": level, "msg": msg, **extra})

    def start(self) -> None:
        self.running = True
        self.spots.start()
        self.note("Scalper 3000 online. Paper trading. Limits only. 3–5% size. No hope holds.")
        self._refresh_vol()
        self.spots.poll_rest()

    def stop(self) -> None:
        self.running = False
        self.spots.stop()

    def _refresh_vol(self) -> None:
        for asset, st in self.assets.items():
            try:
                closes = self.spots.fetch_candles(asset, seconds=45 * 60)
                last = closes[-1] if closes else st.spot or 1.0
                st.vol = vol_from_closes(closes, last)
            except Exception as e:
                st.last_error = f"vol: {e}"
                if st.vol is None:
                    st.vol = vol_from_closes([], st.spot or 1.0)
        self.last_vol_refresh = time.time()

    def step(self) -> None:
        now = time.time()
        self.tick_n += 1
        if now - self.last_vol_refresh > 60:
            try:
                self._refresh_vol()
            except Exception:
                pass
        if now - self.last_rest_spot > 12:
            try:
                self.spots.poll_rest()
            except Exception:
                pass
            self.last_rest_spot = now

        self.risk.open_count = len(self.broker.positions)

        snaps = {}
        try:
            snaps = self.kalshi.snapshot_all(ASSETS)
        except Exception as e:
            self.note(f"kalshi batch: {e}", "error")

        for asset, meta in ASSETS.items():
            st = self.assets[asset]
            if asset in snaps and snaps[asset]:
                st.market = snaps[asset]
            try:
                self._step_asset(st, meta, now)
            except Exception as e:
                st.last_error = str(e)
                if self.tick_n % 20 == 0:
                    self.note(f"{asset} error: {e}", "error")

    def _step_asset(self, st: AssetState, meta: dict, now: float) -> None:
        spot_obj = self.spots.get(st.asset)
        mkt = st.market
        if spot_obj:
            st.spot = spot_obj.price
            st.sources = spot_obj.sources
        if not st.market or st.spot <= 0:
            st.skip = "waiting for market/spot"
            return

        mkt = st.market
        st.seconds_left = mkt.close_ts - now
        sigma = (st.vol.sigma_px_per_sqrt_s if st.vol else st.spot * 0.004 / (15 * 60) ** 0.5)

        # Settlement-window lock: average of spots once we're inside the last 60s.
        if 0 < st.seconds_left <= 60:
            st.settlement_ticks.append((now, st.spot))
            pts = [p for t, p in st.settlement_ticks if t >= mkt.close_ts - 60]
            if pts:
                st.locked_avg = sum(pts) / len(pts)
                st.locked_secs = float(len(pts))
        elif st.seconds_left > 60:
            st.settlement_ticks.clear()
            st.locked_avg = None
            st.locked_secs = 0.0

        drift = st.hist.drift_per_sec(now)
        st.fair = fair_yes(
            st.spot,
            mkt.strike,
            sigma,
            st.seconds_left,
            locked_avg=st.locked_avg,
            locked_secs=st.locked_secs,
            drift_per_sec=drift,
        )
        st.hist.push(
            Tick(
                ts=now,
                spot=st.spot,
                yes_bid=mkt.yes_bid,
                yes_ask=mkt.yes_ask,
                fair=st.fair,
            )
        )
        book: Book = mkt.book
        spread = book.spread if (book.yes_bids and book.no_bids) else max(mkt.yes_ask - mkt.yes_bid, 0.0)

        sig = evaluate(
            cfg=self.cfg,
            hist=st.hist,
            now=now,
            spot=st.spot,
            strike=mkt.strike,
            yes_bid=mkt.yes_bid,
            yes_ask=mkt.yes_ask,
            sigma_px=sigma,
            seconds_left=st.seconds_left,
            locked_avg=st.locked_avg,
            locked_secs=st.locked_secs,
            spread=spread,
        )
        st.signal = sig

        # Exits first.
        pos = self.broker.positions.get(st.asset)
        if pos:
            if pos.ticker != mkt.ticker:
                self._flatten(st, "contract rolled", mkt, taker=True)
                return
            why = exit_reason(
                cfg=self.cfg,
                side=pos.side,
                entry=pos.entry,
                yes_bid=mkt.yes_bid,
                yes_ask=mkt.yes_ask,
                fair=st.fair,
                held_s=now - pos.entry_ts,
                seconds_left=st.seconds_left,
                thin=False,
            )
            # Only flatten for a missing exit quote — thin books are an entry filter, not a panic exit.
            if pos.side == "yes" and mkt.yes_bid <= 0:
                why = why or "no bid to exit"
            if pos.side == "no" and mkt.yes_ask <= 0:
                why = why or "no ask to cover"
            if why:
                self._flatten(st, why, mkt, taker=True)
            st.skip = ""
            return

        if sig.kind == "none":
            st.skip = sig.reason or "no edge"
            return

        self.risk.last_signal_ts[st.asset] = now
        blocked = allow_entry(
            self.cfg,
            self.risk,
            st.asset,
            now,
            st.seconds_left,
            already_open=False,
            ticker=mkt.ticker,
            window_age_s=now - mkt.open_ts if mkt.open_ts else 999.0,
        )
        if blocked:
            self.risk.last_skipped_ts[st.asset] = now
            st.skip = blocked
            return

        if sig.side == "yes":
            visible = book.size_at_or_better_yes_ask(sig.take_price) or mkt.yes_ask_size
        else:
            visible = book.size_at_or_better_yes_bid(round(1.0 - sig.take_price, 4)) or mkt.yes_bid_size

        qty, why_sz = size_contracts(self.cfg, self._equity(), sig.take_price, visible, meta["min_depth"])
        if qty < 1:
            self.risk.last_skipped_ts[st.asset] = now
            st.skip = why_sz
            return

        fee = taker_fee(sig.take_price, qty, self.cfg.fee_multiplier)
        pos = Position(
            asset=st.asset,
            ticker=mkt.ticker,
            side=sig.side,
            qty=qty,
            entry=sig.take_price,
            entry_ts=now,
            fees=fee,
            target=self.cfg.target_cents,
            reason_in=f"{sig.kind}: {sig.reason}",
            kind=sig.kind,
        )
        self.broker.buy(pos, is_taker=True, fee=fee, reason=pos.reason_in)
        self.risk.traded_tickers.add(mkt.ticker)
        self.risk.open_count = len(self.broker.positions)
        st.skip = ""
        self.note(
            f"IN {st.asset} {sig.side.upper()} x{qty:.0f} @ {sig.take_price:.2f}  "
            f"edge {sig.edge_cents:.3f}  {sig.reason}",
            "trade",
            asset=st.asset,
        )

    def _flatten(self, st: AssetState, reason: str, mkt: MarketSnap, taker: bool) -> None:
        pos = self.broker.positions.get(st.asset)
        if not pos:
            return
        if pos.side == "yes":
            px = mkt.yes_bid
        else:
            px = round(1.0 - mkt.yes_ask, 4)
        if px <= 0:
            st.skip = "no bid to exit"
            return
        fee = taker_fee(px, pos.qty, self.cfg.fee_multiplier) if taker else 0.0
        rec = self.broker.close(st.asset, px, fee, reason, is_taker=taker)
        self.risk.last_exit_ts[st.asset] = time.time()
        self.risk.open_count = len(self.broker.positions)
        if rec:
            self.note(
                f"OUT {st.asset} {pos.side.upper()} @ {px:.2f}  pnl {rec['pnl']:+.2f}  {reason}",
                "trade",
                asset=st.asset,
            )

    def _equity(self) -> float:
        eq = self.broker.cash
        for asset, pos in self.broker.positions.items():
            st = self.assets.get(asset)
            if not st or not st.market:
                eq += pos.entry * pos.qty
                continue
            if pos.side == "yes":
                mark = st.market.yes_bid
            else:
                mark = round(1.0 - st.market.yes_ask, 4)
            eq += mark * pos.qty
        return eq

    def state(self) -> dict:
        now = time.time()
        cards = []
        for asset, st in self.assets.items():
            m = st.market
            sig = st.signal
            pos = self.broker.positions.get(asset)
            cards.append(
                {
                    "asset": asset,
                    "spot": st.spot,
                    "sources": st.sources,
                    "strike": m.strike if m else None,
                    "spot_vs_strike": (st.spot - m.strike) if m else None,
                    "spot_vs_strike_bps": ((st.spot - m.strike) / m.strike * 10000) if m and m.strike else None,
                    "ticker": m.ticker if m else None,
                    "yes_bid": m.yes_bid if m else None,
                    "yes_ask": m.yes_ask if m else None,
                    "yes_bid_size": m.yes_bid_size if m else None,
                    "yes_ask_size": m.yes_ask_size if m else None,
                    "spread": (m.yes_ask - m.yes_bid) if m else None,
                    "last": m.last if m else None,
                    "volume": m.volume if m else None,
                    "oi": m.open_interest if m else None,
                    "fair": st.fair,
                    "mid": (0.5 * (m.yes_bid + m.yes_ask)) if m else None,
                    "seconds_left": st.seconds_left,
                    "sigma_1m_bps": (st.vol.sigma_log_1m * 10000) if st.vol else None,
                    "signal": {
                        "kind": sig.kind if sig else "none",
                        "side": sig.side if sig else "",
                        "edge": sig.edge_cents if sig else 0,
                        "reason": sig.reason if sig else st.skip,
                        "take": sig.take_price if sig else None,
                    },
                    "skip": st.skip,
                    "error": st.last_error,
                    "depth_bid": [
                        {"px": lvl.price, "sz": lvl.size} for lvl in (m.book.yes_bids[:6] if m else [])
                    ],
                    "depth_ask": [
                        {"px": round(1.0 - lvl.price, 4), "sz": lvl.size}
                        for lvl in (m.book.no_bids[:6] if m else [])
                    ],
                    "position": None
                    if not pos
                    else {
                        "side": pos.side,
                        "qty": pos.qty,
                        "entry": pos.entry,
                        "held_s": now - pos.entry_ts,
                        "target": pos.target,
                        "mtm": (
                            ((m.yes_bid if pos.side == "yes" else round(1.0 - m.yes_ask, 4)) - pos.entry)
                            if m
                            else 0
                        ),
                    },
                }
            )
        return {
            "ok": True,
            "mode": self.mode,
            "now": now,
            "uptime_s": now - self.started,
            "tick": self.tick_n,
            "ws_ok": self.spots.ws_ok(),
            "bankroll": self.cfg.bankroll,
            "cash": self.broker.cash,
            "equity": self._equity(),
            "realized": self.broker.realized,
            "fees_paid": self.broker.fees_paid,
            "open": len(self.broker.positions),
            "cards": cards,
            "trades": list(reversed(self.broker.trades[-40:])),
            "log": list(self.log)[:80],
            "rules": {
                "size": "3–5% of bankroll (hard cap 10%)",
                "edge": "≥4¢ and ≥5% net after fees",
                "target": "+4–8¢ then out",
                "dead": "out in ~35s if it does not move",
                "orders": "limits only; never market both sides",
                "chase": "no revenge / no chase after a missed tick",
            },
        }

    def loop(self) -> None:
        self.start()
        while self.running:
            t0 = time.time()
            try:
                self.step()
            except Exception:
                self.note(traceback.format_exc(), "error")
            dt = time.time() - t0
            time.sleep(max(0.15, self.cfg.poll_s - dt))
