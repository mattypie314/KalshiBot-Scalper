"""Position sizing and anti-revenge rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import ScalperConfig


@dataclass
class RiskState:
    last_exit_ts: dict[str, float] = field(default_factory=dict)
    last_signal_ts: dict[str, float] = field(default_factory=dict)
    last_skipped_ts: dict[str, float] = field(default_factory=dict)
    traded_tickers: set[str] = field(default_factory=set)
    open_count: int = 0


def size_contracts(
    cfg: ScalperConfig,
    bankroll: float,
    entry_price: float,
    visible_size: float,
    min_depth: float,
) -> tuple[float, str]:
    """Risk 3–5% of bankroll (default 4%), hard cap 10%. Cap to book depth."""
    if entry_price <= 0:
        return 0.0, "bad price"
    risk_px = cfg.risk_frac * bankroll
    cap_px = cfg.hard_cap_frac * bankroll
    notional = min(risk_px, cap_px)
    raw = notional / entry_price
    # Never lift more than 25% of visible size at the touch.
    capped = min(raw, max(visible_size * cfg.min_top_depth_frac, 0.0))
    if visible_size < min_depth:
        return 0.0, f"thin book {visible_size:.0f} < {min_depth:.0f}"
    qty = max(0.0, float(int(capped)))  # whole contracts
    if qty < 1:
        return 0.0, "size rounds to 0"
    return qty, "ok"


def allow_entry(
    cfg: ScalperConfig,
    risk: RiskState,
    asset: str,
    now: float,
    seconds_left: float,
    already_open: bool,
    *,
    ticker: str = "",
    window_age_s: float = 999.0,
) -> str | None:
    if already_open:
        return "already in"
    if risk.open_count >= cfg.max_concurrent:
        return "max concurrent"
    if seconds_left < cfg.no_new_before_close_s:
        return f"{seconds_left:.0f}s to close, no new"
    if window_age_s < cfg.window_warmup_s:
        return "window warmup"
    if cfg.one_trade_per_window and ticker and ticker in risk.traded_tickers:
        return "already traded this window"
    last_x = risk.last_exit_ts.get(asset, 0.0)
    if now - last_x < cfg.cooldown_s:
        return "cooldown after exit"
    last_skip = risk.last_skipped_ts.get(asset, 0.0)
    last_sig = risk.last_signal_ts.get(asset, 0.0)
    # Missed the tick: do not chase the same lag after it has aged.
    if last_skip and now - last_skip < cfg.missed_tick_s and last_sig and now - last_sig < cfg.missed_tick_s:
        return "no chase after missed tick"
    return None
