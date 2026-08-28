"""Kalshi quadratic fees. Taker on crossing; maker typically 0 on crypto 15m."""

from __future__ import annotations

import math


def _round_up_cents(raw: float) -> float:
    if raw <= 0:
        return 0.0
    return math.ceil(raw * 100 - 1e-12) / 100.0


def taker_fee(price: float, count: float, multiplier: float = 1.0) -> float:
    """fee = round_up(M * 0.07 * C * P * (1-P))."""
    p = min(max(price, 0.0), 1.0)
    raw = multiplier * 0.07 * count * p * (1.0 - p)
    return _round_up_cents(raw)


def maker_fee(price: float, count: float, multiplier: float = 0.0) -> float:
    """Maker fee on crypto 15m is typically 0 unless the series lists a maker multiplier."""
    if multiplier <= 0:
        return 0.0
    p = min(max(price, 0.0), 1.0)
    raw = multiplier * 0.0175 * count * p * (1.0 - p)
    return _round_up_cents(raw)


def round_trip_cost(
    entry: float,
    exit_px: float,
    count: float,
    *,
    entry_is_taker: bool,
    exit_is_taker: bool,
    taker_mult: float = 1.0,
    maker_mult: float = 0.0,
) -> float:
    e = taker_fee(entry, count, taker_mult) if entry_is_taker else maker_fee(entry, count, maker_mult)
    x = taker_fee(exit_px, count, taker_mult) if exit_is_taker else maker_fee(exit_px, count, maker_mult)
    return e + x


def net_edge_after_costs(
    fair: float,
    fill: float,
    side: str,
    count: float,
    *,
    is_taker: bool,
    taker_mult: float = 1.0,
    maker_mult: float = 0.0,
    exit_is_taker: bool = True,
    assumed_exit_move: float = 0.06,
) -> float:
    """Expected net $ per contract-path, using fair as the short-horizon terminal mid."""
    if side == "yes":
        gross = fair - fill
        exit_px = min(0.99, fill + assumed_exit_move)
    else:
        gross = fill - fair
        exit_px = max(0.01, fill - assumed_exit_move)
    costs = round_trip_cost(
        fill,
        exit_px,
        count,
        entry_is_taker=is_taker,
        exit_is_taker=exit_is_taker,
        taker_mult=taker_mult,
        maker_mult=maker_mult,
    )
    return gross * count - costs
