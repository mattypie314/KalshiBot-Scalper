"""HTTP helpers, Kalshi REST, Coinbase/Kraken/Bitstamp spots, Coinbase WebSocket."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .book import Book, parse_book, top_from_market
from .config import ASSETS, BITSTAMP_REST, COINBASE_REST, COINBASE_WS, KALSHI_BASE, KRAKEN_REST


MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
ET = ZoneInfo("America/New_York")
UA = "ScottyScalper3000/1.0"


def current_window_ticker(series: str, now: float | None = None) -> str:
    """KXBTC15M-26AUG281145-45 — close time in US/Eastern, 15-minute clock."""
    dt = datetime.fromtimestamp(now or time.time(), ET)
    mins = dt.hour * 60 + dt.minute
    close_mins = ((mins // 15) + 1) * 15
    extra_days, close_mins = divmod(close_mins, 24 * 60)
    close_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=extra_days, minutes=close_mins
    )
    yy = f"{close_dt.year % 100:02d}"
    mon = MONTHS[close_dt.month - 1]
    dd = f"{close_dt.day:02d}"
    hhmm = f"{close_dt.hour:02d}{close_dt.minute:02d}"
    return f"{series}-{yy}{mon}{dd}{hhmm}-{close_dt.minute:02d}"


def _market_payload(data: Any) -> dict | None:
    if not data:
        return None
    if isinstance(data, dict) and "market" in data:
        return data["market"]
    if isinstance(data, dict) and data.get("ticker"):
        return data
    return None


def http_get(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass
class Spot:
    asset: str
    price: float
    bid: float
    ask: float
    source: str
    ts: float
    sources: dict[str, float] = field(default_factory=dict)


@dataclass
class MarketSnap:
    asset: str
    ticker: str
    event_ticker: str
    title: str
    status: str
    strike: float
    close_ts: float
    open_ts: float
    yes_bid: float
    yes_ask: float
    yes_bid_size: float
    yes_ask_size: float
    last: float
    volume: float
    open_interest: float
    book: Book
    rules: str
    ts: float


class SpotFeed:
    def __init__(self, assets: dict | None = None) -> None:
        self.assets = assets if assets is not None else ASSETS
        self._lock = threading.Lock()
        self._spots: dict[str, Spot] = {}
        self._ws_ok = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._ws_loop, name="coinbase-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get(self, asset: str) -> Spot | None:
        with self._lock:
            return self._spots.get(asset)

    def all(self) -> dict[str, Spot]:
        with self._lock:
            return dict(self._spots)

    def ws_ok(self) -> bool:
        return self._ws_ok

    def poll_rest(self) -> None:
        """Fallback / composite: Coinbase + Kraken + Bitstamp."""
        now = time.time()
        for asset, meta in self.assets.items():
            sources: dict[str, float] = {}
            bid = ask = px = None
            try:
                t = http_get(f"{COINBASE_REST}/products/{meta['coinbase']}/ticker", timeout=5)
                px = _safe_float(t.get("price"))
                bid = _safe_float(t.get("bid"))
                ask = _safe_float(t.get("ask"))
                if px:
                    sources["coinbase"] = px
            except Exception:
                pass
            if meta.get("kraken"):
                try:
                    k = http_get(f"{KRAKEN_REST}?pair={meta['kraken']}", timeout=5)
                    result = (k or {}).get("result") or {}
                    if result:
                        first = next(iter(result.values()))
                        last = _safe_float(first.get("c", [None])[0])
                        if last:
                            sources["kraken"] = last
                except Exception:
                    pass
            if meta.get("bitstamp"):
                try:
                    b = http_get(f"{BITSTAMP_REST}/{meta['bitstamp']}", timeout=5)
                    last = _safe_float(b.get("last"))
                    if last:
                        sources["bitstamp"] = last
                except Exception:
                    pass
            if not sources:
                continue
            composite = sum(sources.values()) / len(sources)
            use_px = px or composite
            with self._lock:
                prev = self._spots.get(asset)
                self._spots[asset] = Spot(
                    asset=asset,
                    price=use_px,
                    bid=bid or (prev.bid if prev else use_px),
                    ask=ask or (prev.ask if prev else use_px),
                    source="composite" if len(sources) > 1 else next(iter(sources)),
                    ts=now,
                    sources=sources,
                )

    def fetch_candles(self, asset: str, seconds: int = 3600) -> list[float]:
        meta = self.assets[asset]
        end = int(time.time())
        start = end - seconds
        url = (
            f"{COINBASE_REST}/products/{meta['coinbase']}/candles"
            f"?granularity=60&start={start}&end={end}"
        )
        rows = http_get(url, timeout=10)
        rows = sorted(rows or [], key=lambda r: r[0])
        return [float(r[4]) for r in rows]

    def _ws_loop(self) -> None:
        try:
            from websocket import WebSocketApp  # type: ignore
        except Exception:
            self._ws_ok = False
            return

        products = [m["coinbase"] for m in self.assets.values()]
        prod_to_asset = {m["coinbase"]: a for a, m in self.assets.items()}

        def on_open(ws):
            sub = {
                "type": "subscribe",
                "product_ids": products,
                "channels": ["ticker"],
            }
            ws.send(json.dumps(sub))
            self._ws_ok = True

        def on_message(ws, message: str):
            try:
                msg = json.loads(message)
            except Exception:
                return
            if msg.get("type") != "ticker":
                return
            asset = prod_to_asset.get(msg.get("product_id", ""))
            if not asset:
                return
            px = _safe_float(msg.get("price"))
            if not px:
                return
            bid = _safe_float(msg.get("best_bid")) or px
            ask = _safe_float(msg.get("best_ask")) or px
            with self._lock:
                prev = self._spots.get(asset)
                sources = dict(prev.sources) if prev else {}
                sources["coinbase"] = px
                # Keep other venues in the composite if we have them.
                if len(sources) > 1:
                    composite = sum(sources.values()) / len(sources)
                    use = 0.65 * px + 0.35 * composite
                else:
                    use = px
                self._spots[asset] = Spot(
                    asset=asset,
                    price=use,
                    bid=bid,
                    ask=ask,
                    source="coinbase-ws",
                    ts=time.time(),
                    sources=sources,
                )

        def on_error(ws, err):
            self._ws_ok = False

        def on_close(ws, *_):
            self._ws_ok = False

        while not self._stop.is_set():
            try:
                ws = WebSocketApp(
                    COINBASE_WS,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                self._ws_ok = False
            if self._stop.is_set():
                break
            time.sleep(2.0)


class KalshiFeed:
    def __init__(self) -> None:
        self._tickers: dict[str, str] = {}
        self._lock = threading.Lock()

    def snapshot_all(self, assets: dict) -> dict[str, MarketSnap | None]:
        now = time.time()
        need_discover = []
        with self._lock:
            for a, meta in assets.items():
                t = self._tickers.get(a)
                if not t:
                    need_discover.append((a, meta["series"]))

        def _disc(item):
            a, series = item
            return a, self.discover_active(series)

        if need_discover:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for a, m in pool.map(_disc, need_discover):
                    if m:
                        with self._lock:
                            self._tickers[a] = m["ticker"]

        def _one(asset_series):
            asset, series = asset_series
            return asset, self.snapshot(asset, series)

        out: dict[str, MarketSnap | None] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_one, (a, m["series"])) for a, m in assets.items()]
            for fut in as_completed(futs):
                try:
                    a, snap = fut.result()
                    out[a] = snap
                    if snap and snap.close_ts <= now:
                        with self._lock:
                            self._tickers.pop(a, None)
                    elif snap:
                        with self._lock:
                            self._tickers[a] = snap.ticker
                except Exception:
                    pass
        return out

    def discover_active(self, series: str) -> dict | None:
        constructed = current_window_ticker(series)
        try:
            m = _market_payload(http_get(f"{KALSHI_BASE}/markets/{urllib.parse.quote(constructed)}"))
            if m and m.get("status") in {"active", "open", "initialized"}:
                if float(m.get("floor_strike") or 0) > 0 or m.get("status") in {"active", "open"}:
                    return m
        except Exception:
            pass
        try:
            data = http_get(
                f"{KALSHI_BASE}/markets?series_ticker={urllib.parse.quote(series)}&status=open&limit=20"
            )
        except Exception:
            return None
        markets = data.get("markets") or []
        now = time.time()
        live = []
        for m in markets:
            if m.get("status") not in {"active", "open"}:
                continue
            close_ts = _parse_ts(m.get("close_time"))
            if close_ts and close_ts > now - 5:
                live.append(m)
        if not live:
            return None
        live.sort(key=lambda m: _parse_ts(m.get("close_time")) or 0)
        for m in live:
            ct = _parse_ts(m.get("close_time")) or 0
            if ct > now:
                return m
        return live[-1]

    def snapshot(self, asset: str, series: str) -> MarketSnap | None:
        m = None
        with self._lock:
            ticker = self._tickers.get(asset)
        if ticker:
            try:
                data = http_get(f"{KALSHI_BASE}/markets/{urllib.parse.quote(ticker)}")
                m = _market_payload(data)
                if not m or m.get("status") not in {"active", "open"}:
                    m = None
            except Exception:
                m = None
        if not m:
            m = self.discover_active(series)
        if not m:
            return None
        ticker = m["ticker"]
        with self._lock:
            self._tickers[asset] = ticker
        return self._snap_from_market(asset, m)

    def snapshot_market(self, asset: str, ticker: str) -> MarketSnap | None:
        """Exact-ticker quote, used to flatten an imported leftover position."""
        try:
            data = http_get(f"{KALSHI_BASE}/markets/{urllib.parse.quote(ticker)}")
            m = _market_payload(data)
        except Exception:
            return None
        if not m:
            return None
        return self._snap_from_market(asset, m)

    def _snap_from_market(self, asset: str, m: dict) -> MarketSnap:
        ticker = m["ticker"]
        book = top_from_market(m)
        try:
            ob = http_get(f"{KALSHI_BASE}/markets/{urllib.parse.quote(ticker)}/orderbook")
            parsed = parse_book((ob or {}).get("orderbook_fp"))
            if parsed.yes_bids or parsed.no_bids:
                book = parsed
        except Exception:
            pass
        close_ts = _parse_ts(m.get("close_time")) or 0.0
        open_ts = _parse_ts(m.get("open_time")) or 0.0
        yes_bid = _safe_float(m.get("yes_bid_dollars")) or book.yes_bid
        yes_ask = _safe_float(m.get("yes_ask_dollars")) or book.yes_ask
        return MarketSnap(
            asset=asset,
            ticker=ticker,
            event_ticker=m.get("event_ticker") or "",
            title=m.get("title") or "",
            status=m.get("status") or "",
            strike=float(m.get("floor_strike") or 0),
            close_ts=close_ts,
            open_ts=open_ts,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            yes_bid_size=book.yes_bid_size or float(m.get("yes_bid_size_fp") or 0),
            yes_ask_size=book.yes_ask_size or float(m.get("yes_ask_size_fp") or 0),
            last=float(m.get("last_price_dollars") or 0),
            volume=float(m.get("volume_fp") or 0),
            open_interest=float(m.get("open_interest_fp") or 0),
            book=book,
            rules=m.get("rules_primary") or "",
            ts=time.time(),
        )


def _parse_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        from datetime import datetime, timezone

        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()
    except Exception:
        return None
