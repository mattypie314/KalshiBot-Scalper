"""Fair YES probability for Kalshi 15-minute up/down crypto contracts.

YES resolves if the 60-second CF Benchmarks RTI average in the last minute of
the window is >= the previous window's 60-second average (floor_strike).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


@dataclass
class VolState:
    sigma_px_per_sqrt_s: float
    sigma_log_1m: float
    sample_n: int


def vol_from_closes(closes: list[float], last_spot: float) -> VolState:
    rets = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a > 0 and b > 0:
            rets.append(math.log(b / a))
    if len(rets) < 8:
        # Quiet fallback: 40 bps per 15 minutes.
        sig_log_15m = 0.004
        sig_1s = sig_log_15m / math.sqrt(15 * 60)
        return VolState(sigma_px_per_sqrt_s=last_spot * sig_1s, sigma_log_1m=sig_log_15m / math.sqrt(15), sample_n=len(rets))
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    sig_1m = math.sqrt(max(var, 1e-16))
    # Convert 1-minute log-vol to per-sqrt-second price vol.
    sig_log_per_sqrt_s = sig_1m / math.sqrt(60.0)
    return VolState(
        sigma_px_per_sqrt_s=last_spot * sig_log_per_sqrt_s,
        sigma_log_1m=sig_1m,
        sample_n=len(rets),
    )


def fair_yes(
    spot: float,
    strike: float,
    sigma_px_per_sqrt_s: float,
    seconds_left: float,
    *,
    locked_avg: float | None = None,
    locked_secs: float = 0.0,
    drift_per_sec: float = 0.0,
) -> float:
    """P(settlement >= strike) under a short-horizon Gaussian / random-walk model."""
    if seconds_left <= 0:
        px = locked_avg if locked_avg is not None else spot
        return 1.0 if px >= strike else 0.0

    sigma = max(sigma_px_per_sqrt_s, spot * 1e-6)

    if seconds_left > 60:
        # Settlement is the last-minute average, centered ~30s before close.
        t = max(seconds_left - 30.0, 1.0)
        mean = spot + drift_per_sec * t
        vol = sigma * math.sqrt(t)
        z = (mean - strike) / vol
        return clamp01(norm_cdf(z))

    remaining = max(seconds_left, 1.0)
    locked_n = min(max(locked_secs, 0.0), 60.0 - remaining)
    if locked_avg is None or locked_n <= 0:
        mean = spot + drift_per_sec * remaining * 0.5
        vol = sigma * math.sqrt(remaining / 3.0)
        z = (mean - strike) / max(vol, 1e-12)
        return clamp01(norm_cdf(z))

    # settlement = (locked_avg * locked_n + future_avg * remaining) / 60
    threshold_future = (strike * 60.0 - locked_avg * locked_n) / remaining
    mean_future = spot + drift_per_sec * remaining * 0.5
    vol_future = sigma * math.sqrt(remaining / 3.0)
    z = (mean_future - threshold_future) / max(vol_future, 1e-12)
    return clamp01(norm_cdf(z))


@dataclass
class Tick:
    ts: float
    spot: float
    yes_bid: float
    yes_ask: float
    fair: float


@dataclass
class SpotHistory:
    ticks: deque = field(default_factory=lambda: deque(maxlen=240))

    def push(self, tick: Tick) -> None:
        self.ticks.append(tick)

    def at_or_before(self, ts: float) -> Tick | None:
        found = None
        for t in self.ticks:
            if t.ts <= ts:
                found = t
            else:
                break
        return found

    def last(self) -> Tick | None:
        return self.ticks[-1] if self.ticks else None

    def drift_per_sec(self, now: float, lookback: float = 90.0) -> float:
        a = self.at_or_before(now - lookback)
        b = self.last()
        if not a or not b or b.ts <= a.ts:
            return 0.0
        raw = (b.spot - a.spot) / (b.ts - a.ts)
        # Shrink toward zero — do not treat a 90s slide as a 15m forecast.
        return raw * 0.35

    def spot_change(self, now: float, lookback: float) -> float | None:
        a = self.at_or_before(now - lookback)
        b = self.last()
        if not a or not b:
            return None
        return b.spot - a.spot

    def mid_change(self, now: float, lookback: float) -> float | None:
        a = self.at_or_before(now - lookback)
        b = self.last()
        if not a or not b:
            return None
        amid = 0.5 * (a.yes_bid + a.yes_ask)
        bmid = 0.5 * (b.yes_bid + b.yes_ask)
        return bmid - amid

    def fair_change(self, now: float, lookback: float) -> float | None:
        a = self.at_or_before(now - lookback)
        b = self.last()
        if not a or not b:
            return None
        return b.fair - a.fair
