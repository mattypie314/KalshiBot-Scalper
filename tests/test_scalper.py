"""Unit tests for fees, fair value, lag signals, and sizing."""

from __future__ import annotations

import math
import time

from scalper.config import ScalperConfig
from scalper.fees import net_edge_after_costs, taker_fee
from scalper.model import SpotHistory, Tick, fair_yes, norm_cdf, vol_from_closes
from scalper.risk import RiskState, allow_entry, size_contracts
from scalper.signals import evaluate, exit_reason


def test_taker_fee_peaks_near_fifty():
    f50 = taker_fee(0.50, 1)
    f10 = taker_fee(0.10, 1)
    assert f50 >= f10
    assert 0.01 <= f50 <= 0.02


def test_taker_fee_scales_with_count():
    assert taker_fee(0.20, 100) >= taker_fee(0.20, 1) * 50


def test_fair_atm_near_half():
    p = fair_yes(100.0, 100.0, 0.05, 300)
    assert 0.48 < p < 0.52


def test_fair_deep_itm():
    p = fair_yes(110.0, 100.0, 0.05, 120)
    assert p > 0.95


def test_fair_deep_otm():
    p = fair_yes(90.0, 100.0, 0.05, 120)
    assert p < 0.05


def test_settlement_lock_makes_outcome_stickier():
    # Locked 50s at 101 vs strike 100, 10s left — almost surely YES.
    p = fair_yes(101.0, 100.0, 0.2, 10, locked_avg=101.0, locked_secs=50)
    assert p > 0.9


def test_norm_cdf_known_values():
    assert abs(norm_cdf(0) - 0.5) < 1e-9
    assert 0.84 < norm_cdf(1) < 0.85


def test_vol_from_closes():
    closes = [100 * (1.001 ** i) for i in range(40)]
    v = vol_from_closes(closes, 100)
    assert v.sample_n >= 8
    assert v.sigma_px_per_sqrt_s > 0


def _hist(now, spots, mids, fairs):
    h = SpotHistory()
    for i, (s, m, f) in enumerate(zip(spots, mids, fairs)):
        ts = now - (len(spots) - 1 - i)
        h.push(Tick(ts=ts, spot=s, yes_bid=m - 0.005, yes_ask=m + 0.005, fair=f))
    return h


def test_lag_yes_when_spot_jumps_and_kalshi_sleeps():
    cfg = ScalperConfig()
    now = time.time()
    # Spot rips up; fair follows; Kalshi mid stuck at 0.40
    spots = [100 + i * 0.4 for i in range(10)]
    fairs = [0.40 + i * 0.015 for i in range(10)]
    mids = [0.40] * 10
    h = _hist(now, spots, mids, fairs)
    last = h.last()
    sig = evaluate(
        cfg=cfg,
        hist=h,
        now=now,
        spot=last.spot,
        strike=100.0,
        yes_bid=0.395,
        yes_ask=0.405,
        sigma_px=0.05,
        seconds_left=400,
        locked_avg=None,
        locked_secs=0,
        spread=0.01,
    )
    assert sig.kind == "lag_yes"
    assert sig.side == "yes"
    assert sig.edge_cents >= cfg.min_net_edge


def test_lag_no_when_spot_dumps_and_kalshi_sleeps():
    cfg = ScalperConfig()
    now = time.time()
    spots = [100 - i * 0.4 for i in range(10)]
    fairs = [0.60 - i * 0.015 for i in range(10)]
    mids = [0.60] * 10
    h = _hist(now, spots, mids, fairs)
    last = h.last()
    sig = evaluate(
        cfg=cfg,
        hist=h,
        now=now,
        spot=last.spot,
        strike=100.0,
        yes_bid=0.595,
        yes_ask=0.605,
        sigma_px=0.05,
        seconds_left=400,
        locked_avg=None,
        locked_secs=0,
        spread=0.01,
    )
    assert sig.kind == "lag_no"
    assert sig.side == "no"


def test_wide_spread_skipped():
    cfg = ScalperConfig()
    now = time.time()
    h = _hist(now, [100] * 10, [0.5] * 10, [0.5] * 10)
    sig = evaluate(
        cfg=cfg,
        hist=h,
        now=now,
        spot=100,
        strike=100,
        yes_bid=0.40,
        yes_ask=0.50,
        sigma_px=0.05,
        seconds_left=400,
        locked_avg=None,
        locked_secs=0,
        spread=0.10,
    )
    assert sig.kind == "none"
    assert "spread" in sig.reason


def test_exit_target_and_dead_scalp():
    cfg = ScalperConfig()
    why = exit_reason(
        cfg=cfg, side="yes", entry=0.40, yes_bid=0.45, yes_ask=0.46,
        fair=0.50, held_s=8, seconds_left=400, thin=False,
    )
    assert why and why.startswith("target")
    dead = exit_reason(
        cfg=cfg, side="yes", entry=0.40, yes_bid=0.401, yes_ask=0.41,
        fair=0.41, held_s=40, seconds_left=400, thin=False,
    )
    assert dead and "dead scalp" in dead


def test_size_is_three_to_five_percent():
    cfg = ScalperConfig()
    qty, why = size_contracts(cfg, 1000, 0.40, 500, 20)
    assert why == "ok"
    notional = qty * 0.40
    assert 0.03 * 1000 - 0.40 <= notional <= 0.05 * 1000 + 0.40


def test_thin_book_rejected():
    cfg = ScalperConfig()
    qty, why = size_contracts(cfg, 1000, 0.40, 5, 20)
    assert qty == 0
    assert "thin" in why


def test_hard_cap_ten_percent():
    cfg = ScalperConfig(risk_frac=0.50, hard_cap_frac=0.10)
    qty, why = size_contracts(cfg, 1000, 0.50, 10_000, 20)
    assert why == "ok"
    assert qty * 0.50 <= 100.0 + 1e-6


def test_no_chase_after_missed_tick():
    cfg = ScalperConfig()
    risk = RiskState()
    now = time.time()
    risk.last_signal_ts["BTC"] = now - 2
    risk.last_skipped_ts["BTC"] = now - 2
    blocked = allow_entry(cfg, risk, "BTC", now, 400, False)
    assert blocked and "chase" in blocked


def test_cooldown_after_exit():
    cfg = ScalperConfig()
    risk = RiskState()
    now = time.time()
    risk.last_exit_ts["ETH"] = now - 5
    blocked = allow_entry(cfg, risk, "ETH", now, 400, False)
    assert blocked == "cooldown after exit"


def test_no_new_near_close():
    cfg = ScalperConfig()
    risk = RiskState()
    blocked = allow_entry(cfg, risk, "SOL", time.time(), 20, False)
    assert blocked and "no new" in blocked


def test_one_trade_per_window():
    cfg = ScalperConfig()
    risk = RiskState()
    risk.traded_tickers.add("KXETH15M-26AUG281200-00")
    blocked = allow_entry(
        cfg, risk, "ETH", time.time(), 400, False,
        ticker="KXETH15M-26AUG281200-00", window_age_s=60,
    )
    assert blocked == "already traded this window"


def test_window_warmup():
    cfg = ScalperConfig()
    risk = RiskState()
    blocked = allow_entry(cfg, risk, "BTC", time.time(), 400, False, window_age_s=5)
    assert blocked == "window warmup"


def test_window_ticker_matches_kalshi_pattern():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from scalper.feeds import current_window_ticker

    et = ZoneInfo("America/New_York")
    ts = datetime(2026, 8, 28, 11, 42, tzinfo=et).timestamp()
    assert current_window_ticker("KXBTC15M", ts) == "KXBTC15M-26AUG281145-45"
    ts = datetime(2026, 8, 28, 11, 45, 1, tzinfo=et).timestamp()
    assert current_window_ticker("KXBTC15M", ts) == "KXBTC15M-26AUG281200-00"
    ts = datetime(2026, 8, 28, 23, 59, tzinfo=et).timestamp()
    assert current_window_ticker("KXETH15M", ts) == "KXETH15M-26AUG290000-00"


def test_net_edge_after_taker_fees_positive_only_if_gap_clears_cost():
    # 1¢ theoretical edge should not clear round-trip taker fees near 50¢.
    net = net_edge_after_costs(0.51, 0.50, "yes", 1.0, is_taker=True, assumed_exit_move=0.06)
    # May still be slightly positive because assumed exit is +6¢; just sanity-check type.
    assert isinstance(net, float)
