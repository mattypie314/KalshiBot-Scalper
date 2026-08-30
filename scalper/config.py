"""Scalper policy. Numbers are the user's rules, not suggestions."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .envfile import load_dotenv

__all__ = [
    "ASSETS",
    "KALSHI_BASE",
    "kalshi_base",
    "ScalperConfig",
    "asset_for_ticker",
    "load_config",
    "load_dotenv",
    "parse_asset_allowlist",
]


ASSETS = {
    "BTC": {
        "series": "KXBTC15M",
        "coinbase": "BTC-USD",
        "kraken": "XBTUSD",
        "bitstamp": "btcusd",
        "index": "BRTI",
        "min_depth": 80.0,
        "tick": 0.01,
    },
    "ETH": {
        "series": "KXETH15M",
        "coinbase": "ETH-USD",
        "kraken": "ETHUSD",
        "bitstamp": "ethusd",
        "index": "ETHRTI",
        "min_depth": 25.0,
        "tick": 0.01,
    },
    "SOL": {
        "series": "KXSOL15M",
        "coinbase": "SOL-USD",
        "kraken": "SOLUSD",
        "bitstamp": "solusd",
        "index": "SOLRTI",
        "min_depth": 20.0,
        "tick": 0.01,
    },
    "XRP": {
        "series": "KXXRP15M",
        "coinbase": "XRP-USD",
        "kraken": "XRPUSD",
        "bitstamp": "xrpusd",
        "index": "XRPRTI",
        "min_depth": 20.0,
        "tick": 0.01,
    },
    "DOGE": {
        "series": "KXDOGE15M",
        "coinbase": "DOGE-USD",
        "kraken": "DOGEUSD",
        "bitstamp": "dogeusd",
        "index": "DOGerti",
        "min_depth": 15.0,
        "tick": 0.01,
    },
    "BNB": {
        "series": "KXBNB15M",
        "coinbase": "BNB-USD",
        "kraken": None,
        "bitstamp": None,
        "index": "BNBRTI",
        "min_depth": 15.0,
        "tick": 0.01,
    },
    "HYPE": {
        "series": "KXHYPE15M",
        "coinbase": "HYPE-USD",
        "kraken": None,
        "bitstamp": None,
        "index": "HYPERI",
        "min_depth": 15.0,
        "tick": 0.01,
    },
}

# CF Benchmarks ids are not required for the Coinbase/Kraken proxy.
ASSETS["DOGE"]["index"] = "DOGerti"


def kalshi_base() -> str:
    return os.environ.get(
        "KALSHI_API_BASE", "https://external-api.kalshi.com/trade-api/v2"
    ).rstrip("/")


KALSHI_BASE = kalshi_base()
COINBASE_REST = "https://api.exchange.coinbase.com"
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
KRAKEN_REST = "https://api.kraken.com/0/public/Ticker"
BITSTAMP_REST = "https://www.bitstamp.net/api/v2/ticker"


@dataclass
class ScalperConfig:
    bankroll: float = 1000.0
    risk_frac: float = 0.04  # 4% of bankroll, inside 3–5%
    risk_frac_min: float = 0.03
    risk_frac_max: float = 0.05
    hard_cap_frac: float = 0.10
    min_net_edge: float = 0.04  # 4¢ after fees + half-spread
    min_net_edge_pct: float = 0.05  # 5% of capital at risk
    target_cents_min: float = 0.04
    target_cents_max: float = 0.08
    target_cents: float = 0.06
    max_hold_seconds: float = 70.0
    fast_fail_seconds: float = 35.0
    fast_fail_min_move: float = 0.02
    lag_lookback_s: float = 8.0
    lag_confirm_s: float = 3.0
    min_spot_move_sigma: float = 0.55
    cooldown_s: float = 25.0
    missed_tick_s: float = 8.0
    max_concurrent: int = 2
    max_spread: float = 0.03
    flatten_before_close_s: float = 25.0
    no_new_before_close_s: float = 40.0
    window_warmup_s: float = 20.0
    one_trade_per_window: bool = True
    min_top_depth_frac: float = 0.25  # never take more than 25% of visible size
    poll_s: float = 0.2  # decision loop; floor is 0.15s in Engine.loop
    live_cross_ticks: int = 1  # LIVE IOC: cross N ticks through the book to fill
    live: bool = False
    host: str = "0.0.0.0"
    port: int = 8787
    dashboard_token: str = ""
    fee_multiplier: float = 1.0
    maker_fee_multiplier: float = 0.0  # resting crypto 15m is typically maker-free
    assets: dict = field(default_factory=lambda: dict(ASSETS))


def asset_for_ticker(ticker: str, assets: dict | None = None) -> str | None:
    """Map KXBTC15M-… to BTC using the configured series prefixes."""
    text = (ticker or "").strip().upper()
    if not text:
        return None
    table = assets if assets is not None else ASSETS
    best = ""
    best_len = -1
    for name, meta in table.items():
        series = str((meta or {}).get("series") or "").strip().upper()
        if not series:
            continue
        if text == series or text.startswith(series + "-"):
            if len(series) > best_len:
                best = name
                best_len = len(series)
    return best or None


def parse_asset_allowlist(raw: str | None = None) -> dict:
    """Subset of ASSETS from SCALPER_ASSETS (comma-separated). Empty defaults to BTC."""
    text = (raw if raw is not None else os.environ.get("SCALPER_ASSETS", "")).strip()
    if not text:
        return {"BTC": ASSETS["BTC"]}
    names: list[str] = []
    for part in text.replace(";", ",").split(","):
        name = part.strip().upper()
        if not name:
            continue
        if name in {"ALL", "*"}:
            return dict(ASSETS)
        if name not in ASSETS:
            known = ", ".join(ASSETS)
            raise ValueError(f"unknown SCALPER_ASSETS name {name!r}; known: {known}")
        if name not in names:
            names.append(name)
    if not names:
        return {"BTC": ASSETS["BTC"]}
    return {name: ASSETS[name] for name in names}


def load_config() -> ScalperConfig:
    return ScalperConfig(
        bankroll=float(os.environ.get("SCALPER_BANKROLL", "1000")),
        live=os.environ.get("SCALPER_LIVE", "0") in {"1", "true", "TRUE", "yes"},
        host=os.environ.get("SCALPER_HOST", "0.0.0.0"),
        port=int(os.environ.get("SCALPER_PORT", "8787")),
        dashboard_token=os.environ.get("SCALPER_DASHBOARD_TOKEN", "").strip(),
        poll_s=float(os.environ.get("SCALPER_POLL_S", "0.2")),
        live_cross_ticks=int(os.environ.get("SCALPER_LIVE_CROSS_TICKS", "1")),
        assets=parse_asset_allowlist(),
    )
