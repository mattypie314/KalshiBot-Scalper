"""Entry / exit signals: lag vs overdone spike. Not a hold-to-expiry model."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ScalperConfig
from .fees import net_edge_after_costs, taker_fee
from .model import SpotHistory, fair_yes


@dataclass
class Signal:
    kind: str  # lag_yes, lag_no, fade_yes, fade_no, none
    side: str  # yes / no  (buy this side)
    edge: float  # net $ per contract after fees, using fair as terminal
    edge_cents: float
    reason: str
    take_price: float
    rest_price: float
    prefer_take: bool
    fair: float
    mid: float


def _mid(bid: float, ask: float) -> float:
    if bid <= 0 or ask <= 0:
        return 0.0
    return 0.5 * (bid + ask)


def evaluate(
    *,
    cfg: ScalperConfig,
    hist: SpotHistory,
    now: float,
    spot: float,
    strike: float,
    yes_bid: float,
    yes_ask: float,
    sigma_px: float,
    seconds_left: float,
    locked_avg: float | None,
    locked_secs: float,
    spread: float,
) -> Signal:
    none = Signal("none", "", 0.0, 0.0, "", 0.0, 0.0, False, 0.0, 0.0)
    if spot <= 0 or strike <= 0 or yes_bid <= 0 or yes_ask <= 0:
        return Signal("none", "", 0.0, 0.0, "no quote", 0.0, 0.0, False, 0.0, 0.0)
    if spread > cfg.max_spread + 1e-9:
        return Signal("none", "", 0.0, 0.0, f"spread {spread:.2f} too wide", 0.0, 0.0, False, 0.0, _mid(yes_bid, yes_ask))

    drift = hist.drift_per_sec(now)
    fair = fair_yes(
        spot,
        strike,
        sigma_px,
        seconds_left,
        locked_avg=locked_avg,
        locked_secs=locked_secs,
        drift_per_sec=drift,
    )
    mid = _mid(yes_bid, yes_ask)

    look = cfg.lag_lookback_s
    d_spot = hist.spot_change(now, look)
    d_fair = hist.fair_change(now, look)
    d_mid = hist.mid_change(now, look)
    d_spot_fast = hist.spot_change(now, cfg.lag_confirm_s)
    d_mid_fast = hist.mid_change(now, cfg.lag_confirm_s)
    d_fair_fast = hist.fair_change(now, cfg.lag_confirm_s)

    if d_spot is None or d_fair is None or d_mid is None:
        return Signal("none", "", 0.0, 0.0, "warming up", 0.0, 0.0, False, fair, mid)

    # Move size in sigma units over the lookback.
    vol_look = max(sigma_px * (look ** 0.5), spot * 1e-8)
    spot_sigma = abs(d_spot) / vol_look

    lag_yes = (d_fair - d_mid)  # fair rose more than Kalshi → buy YES
    lag_no = (d_mid - d_fair)  # Kalshi rose more / fair fell more → buy NO / fade YES

    # Overdone: Kalshi mid jumped hard while spot/fair barely moved.
    overdone_up = False
    overdone_dn = False
    if d_mid_fast is not None and d_spot_fast is not None and d_fair_fast is not None:
        if d_mid_fast >= 0.05 and d_fair_fast < 0.01 and abs(d_spot_fast) < 0.15 * vol_look:
            overdone_up = True
        if d_mid_fast <= -0.05 and d_fair_fast > -0.01 and abs(d_spot_fast) < 0.15 * vol_look:
            overdone_dn = True

    kind = "none"
    side = ""
    take_price = 0.0
    rest_price = 0.0
    reason = "no clear fast edge"
    prefer_take = False

    # Lag has priority when spot actually moved.
    if spot_sigma >= cfg.min_spot_move_sigma and abs(d_fair - d_mid) >= cfg.min_net_edge:
        if d_spot > 0 and lag_yes >= cfg.min_net_edge:
            kind, side = "lag_yes", "yes"
            take_price, rest_price = yes_ask, min(yes_ask, yes_bid + 0.01)
            prefer_take = True  # lag dies in 30–90s; must be in the book now
            reason = (
                f"spot +{d_spot:.4g} ({spot_sigma:.2f}σ) in {look:.0f}s, "
                f"fair {d_fair:+.3f} vs Kalshi {d_mid:+.3f}"
            )
        elif d_spot < 0 and (d_fair - d_mid) <= -cfg.min_net_edge:
            # Fair dropped more than Kalshi → buy NO
            kind, side = "lag_no", "no"
            # Buy NO at no_ask = 1 - yes_bid
            take_price = round(1.0 - yes_bid, 4)
            rest_price = take_price
            prefer_take = True
            reason = (
                f"spot {d_spot:.4g} ({spot_sigma:.2f}σ) in {look:.0f}s, "
                f"fair {d_fair:+.3f} vs Kalshi {d_mid:+.3f}"
            )

    if kind == "none" and overdone_up:
        kind, side = "fade_yes", "no"
        take_price = round(1.0 - yes_bid, 4)
        rest_price = take_price
        prefer_take = True
        reason = f"Kalshi YES spiked {d_mid_fast:+.3f} with no spot follow-through"
    elif kind == "none" and overdone_dn:
        kind, side = "fade_no", "yes"
        take_price, rest_price = yes_ask, yes_ask
        prefer_take = True
        reason = f"Kalshi YES dumped {d_mid_fast:+.3f} with no spot follow-through"

    if kind == "none":
        return Signal("none", "", 0.0, 0.0, reason, 0.0, 0.0, False, fair, mid)

    fill = take_price
    if side == "yes":
        edge_per = fair - fill
    else:
        # Buying NO at take_price; equivalent YES short at 1-take_price = yes_bid
        yes_eq = round(1.0 - fill, 4)
        edge_per = yes_eq - fair

    # After taker fees on a 1-contract round trip (conservative).
    net = net_edge_after_costs(
        fair if side == "yes" else (1.0 - fair),
        fill,
        "yes",
        1.0,
        is_taker=True,
        assumed_exit_move=cfg.target_cents,
    )
    # Recompute more directly: edge_per minus two taker fees.
    fee_in = taker_fee(fill, 1.0)
    fee_out = taker_fee(min(0.99, fill + cfg.target_cents), 1.0)
    net_cents = edge_per - fee_in - fee_out

    if net_cents < cfg.min_net_edge:
        return Signal("none", "", 0.0, 0.0, f"edge after fees {net_cents:.3f} < {cfg.min_net_edge}", 0.0, 0.0, False, fair, mid)
    if fill <= 0.02 or fill >= 0.98:
        return Signal("none", "", 0.0, 0.0, "too close to 0/1 to scalp", 0.0, 0.0, False, fair, mid)

    return Signal(
        kind=kind,
        side=side,
        edge=net_cents,
        edge_cents=net_cents,
        reason=reason,
        take_price=fill,
        rest_price=rest_price,
        prefer_take=prefer_take,
        fair=fair,
        mid=mid,
    )


def exit_reason(
    *,
    cfg: ScalperConfig,
    side: str,
    entry: float,
    yes_bid: float,
    yes_ask: float,
    fair: float,
    held_s: float,
    seconds_left: float,
    thin: bool,
) -> str | None:
    """Pre-decided scalp exit. Never 'I'll just hold it'."""
    if side == "yes":
        mtm = yes_bid - entry
        live_edge = fair - yes_ask
        can_exit = yes_bid
    else:
        # long NO entered at entry; NO bid = 1 - yes_ask
        no_bid = round(1.0 - yes_ask, 4)
        mtm = no_bid - entry
        live_edge = (1.0 - fair) - (1.0 - yes_bid)
        can_exit = no_bid

    if mtm >= cfg.target_cents_min:
        return f"target +{mtm:.3f}"
    if held_s >= cfg.fast_fail_seconds and mtm < cfg.fast_fail_min_move:
        return f"dead scalp {held_s:.0f}s {mtm:+.3f}"
    if held_s >= cfg.max_hold_seconds:
        return f"time stop {held_s:.0f}s {mtm:+.3f}"
    if seconds_left <= cfg.flatten_before_close_s:
        return f"flatten before close ({seconds_left:.0f}s left)"
    if live_edge < 0.01 and mtm >= 0:
        return "edge decayed, scratch"
    if live_edge < -0.02:
        return "edge flipped, get out"
    return None
