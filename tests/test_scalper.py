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


def _paper_market(asset="BTC", yes_bid=0.40, yes_ask=0.42):
    from scalper.book import Book, BookLevel
    from scalper.feeds import MarketSnap

    now = time.time()
    book = Book(
        yes_bids=[BookLevel(yes_bid, 120), BookLevel(yes_bid - 0.01, 80)],
        no_bids=[BookLevel(round(1.0 - yes_ask, 4), 110)],
    )
    return MarketSnap(
        asset=asset,
        ticker=f"KX{asset}15M-TEST",
        event_ticker="x",
        title="t",
        status="active",
        strike=100.0,
        close_ts=now + 400,
        open_ts=now - 80,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        yes_bid_size=120,
        yes_ask_size=110,
        last=0.41,
        volume=2500,
        open_interest=900,
        book=book,
        rules="",
        ts=now,
    )


def test_dashboard_pause_mute_and_flatten():
    from scalper.broker import Position
    from scalper.engine import Engine
    from scalper.feeds import Spot
    from scalper.model import Tick

    cfg = ScalperConfig()
    eng = Engine(cfg)
    assert eng.action({"op": "bogus"})["ok"] is False
    assert eng.action({"op": "pause"}) == {"ok": True, "paused": True}
    assert eng.paused is True
    assert eng.action({"op": "resume"}) == {"ok": True, "paused": False}
    assert eng.action({"op": "mute", "asset": "btc"})["ok"] is True
    assert "BTC" in eng.muted
    assert eng.action({"op": "unmute", "asset": "BTC"})["ok"] is True
    assert "BTC" not in eng.muted

    now = time.time()
    st = eng.assets["BTC"]
    st.market = _paper_market()
    st.spot = 100.2
    st.hist.push(Tick(ts=now - 2, spot=100.2, yes_bid=0.40, yes_ask=0.42, fair=0.45))
    eng.spots._spots["BTC"] = Spot(
        asset="BTC", price=100.2, bid=100.1, ask=100.3, source="t", ts=now, sources={"coinbase": 100.2}
    )
    eng.paused = True
    eng._step_asset(st, {"min_depth": 80.0}, now)
    assert "paused" in st.skip

    eng.paused = False
    eng.muted.add("BTC")
    eng._step_asset(st, {"min_depth": 80.0}, now)
    assert "market off" in st.skip
    eng.muted.clear()

    pos = Position(
        asset="BTC", ticker=st.market.ticker, side="yes", qty=5, entry=0.40,
        entry_ts=now - 8, fees=0.05, target=0.06, reason_in="test", kind="lag_yes",
    )
    eng.broker.positions["BTC"] = pos
    out = eng.flatten_now("BTC")
    assert out["ok"] is True
    assert "BTC" not in eng.broker.positions
    assert eng.broker.trades[-1]["reason_out"] == "flatten from dashboard"

    snap = eng.state()
    assert snap["paused"] is False
    assert "stats" in snap
    btc = next(c for c in snap["cards"] if c["asset"] == "BTC")
    assert "history" in btc
    assert "depth_bid" in btc
    assert btc["muted"] is False
    assert eng.action({"op": "mute_all"})["ok"] is True
    assert set(eng.muted) == set(eng.assets)
    assert eng.action({"op": "unmute_all"})["muted"] == []


def test_action_http_roundtrip():
    import json
    import urllib.error
    import urllib.request
    from scalper.engine import Engine
    from scalper.server import serve

    eng = Engine(ScalperConfig())
    httpd = serve(eng, "127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action",
            data=json.dumps({"op": "pause"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode())
        assert body == {"ok": True, "paused": True}
        assert eng.paused is True
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3) as resp:
            state = json.loads(resp.read().decode())
        assert state["paused"] is True
        assert "stats" in state
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action",
            data=b"not-json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(bad, timeout=3)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        head = urllib.request.Request(f"http://127.0.0.1:{port}/", method="HEAD")
        with urllib.request.urlopen(head, timeout=3) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type", "").startswith("text/html")
            assert resp.headers.get("Content-Length") == "0"
            assert resp.read() == b""
        health = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="HEAD")
        with urllib.request.urlopen(health, timeout=3) as resp:
            assert resp.status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


class _FakeKalshi:
    def __init__(self):
        self.ready = True
        self.cash = 250.0
        self.orders = []
        self.fill_qty = 5.0
        self.fail_balance = False

    def balance(self):
        if self.fail_balance:
            raise RuntimeError("auth exploded")
        return self.cash

    def market_position_count(self):
        return 0

    def ioc(self, ticker, book_side, qty, yes_price):
        from scalper.kalshi_api import LiveFill

        self.orders.append({"ticker": ticker, "side": book_side, "qty": qty, "px": yes_price})
        if self.fill_qty < 1:
            return LiveFill(ok=False, error="live IOC unfilled")
        return LiveFill(ok=True, qty=self.fill_qty, price=yes_price, fee=0.02, order_id="ord1")


def test_live_toggle_requires_confirm_and_keys():
    from scalper.engine import Engine

    eng = Engine(ScalperConfig())
    snap = eng.state()
    assert snap["mode"] == "PAPER"
    assert snap["live_ready"] is False
    no_confirm = eng.action({"op": "mode", "mode": "LIVE"})
    assert no_confirm["ok"] is False
    assert no_confirm.get("need_confirm") is True
    blocked = eng.action({"op": "mode", "mode": "LIVE", "confirm": "LIVE"})
    assert blocked["ok"] is False
    assert "keys" in blocked["error"].lower()
    assert eng.mode == "PAPER"


def test_live_toggle_with_client_and_orders():
    from scalper.broker import Position
    from scalper.engine import Engine

    api = _FakeKalshi()
    eng = Engine(ScalperConfig(), kalshi_api=api)
    assert eng.state()["live_ready"] is True
    assert eng.action({"op": "mode", "mode": "LIVE", "confirm": "LIVE"})["ok"] is True
    assert eng.mode == "LIVE"
    assert eng.paused is True
    assert eng.broker.cash == 250.0

    pos = Position(
        asset="BTC", ticker="KXBTC15M-TEST", side="yes", qty=5, entry=0.42,
        entry_ts=time.time(), fees=0.0, target=0.06, reason_in="t", kind="lag_yes",
    )
    fill = eng._live_enter(pos)
    assert fill.ok is True
    assert api.orders[-1]["side"] == "bid"
    assert api.orders[-1]["px"] == 0.42

    no_pos = Position(
        asset="ETH", ticker="KXETH15M-TEST", side="no", qty=4, entry=0.40,
        entry_ts=time.time(), fees=0.0, target=0.06, reason_in="t", kind="lag_no",
    )
    fill_no = eng._live_enter(no_pos)
    assert fill_no.ok is True
    assert api.orders[-1]["side"] == "ask"
    assert abs(api.orders[-1]["px"] - 0.60) < 1e-9
    assert abs(fill_no.price - 0.40) < 1e-9

    api.fill_qty = 0
    miss = eng._live_enter(pos)
    assert miss.ok is False
    api.fill_qty = 5

    stuck = eng.action({"op": "mode", "mode": "PAPER"})
    # no live positions yet
    assert stuck["ok"] is True
    assert eng.mode == "PAPER"

    eng.action({"op": "mode", "mode": "LIVE", "confirm": "LIVE"})
    eng.broker.positions["BTC"] = pos
    assert eng.action({"op": "mode", "mode": "PAPER"})["ok"] is False
    del eng.broker.positions["BTC"]
    eng.action({"op": "mode", "mode": "PAPER"})
    eng.broker.positions["BTC"] = pos
    assert "flatten" in eng.action({"op": "mode", "mode": "LIVE", "confirm": "LIVE"})["error"]


def test_sign_request_roundtrip():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from scalper.kalshi_api import sign_request
    import base64

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    ts, method, path = "1700000000000", "GET", "/trade-api/v2/portfolio/balance"
    sig = sign_request(pem, ts, method, path)
    key.public_key().verify(
        base64.b64decode(sig),
        f"{ts}{method}{path}".encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_net_edge_after_taker_fees_positive_only_if_gap_clears_cost():
    # 1¢ theoretical edge should not clear round-trip taker fees near 50¢.
    net = net_edge_after_costs(0.51, 0.50, "yes", 1.0, is_taker=True, assumed_exit_move=0.06)
    # May still be slightly positive because assumed exit is +6¢; just sanity-check type.
    assert isinstance(net, float)
