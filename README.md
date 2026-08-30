# KalshiBot-Scalper

scallllp me!

Live watcher for **any Kalshi 15-minute crypto** contract (BTC, ETH, SOL, XRP, DOGE, BNB, HYPE) — Scotty's 15m Crypto Scalper 3000.

It compares Coinbase/Kraken/Bitstamp **spot** to the Kalshi **Yes/No** book every tick. It only papers a trade when there is a **clear, fast mismatch**: spot already moved and Kalshi has not, or a spike looks overdone.

## Rules (hard)

1. Watch live spot and Kalshi Yes/No at the same time.
2. Enter only on lag or an overdone spike.
3. Size **3–5% of bankroll** (hard cap **10%**).
4. Pre-decide the scalp: **out at +4–8¢**.
5. If it does not move fast (~35s), **get out**. Never turn a scalp into a hope hold.
6. Repeat only when another clear fast edge appears.
7. **Limits only.** Crossing with a limit at the touch is allowed; market-buying and market-selling both sides of a 15-minute book is how fees and spread wipe the edge.
8. Watch depth. Thin books are skipped.
9. Recheck after every spot tick. On 15-minute markets the edge can vanish in 30–90 seconds.
10. No revenge / no chase after a missed tick. Exit when the model edge decays.

Settlement is the 60-second CF Benchmarks RTI average in the last minute. `floor_strike` is the previous window's average. Fair YES is P(settlement ≥ strike) from a short-horizon Gaussian, then **lag vs the book** — not a hold-to-expiry value bet.

Imported from Cursor cloud agent [Scotty's 15m Crypto Scalper 3000](https://cursor.com/agents/bc-01a04901-d2ee-7427-a23b-e4c1456ee4db).

## Run

```bash
python3 -m pip install -r requirements.txt
python3 run.py
```

BTC only (same app — Coinbase/Kalshi feeds for BTC, no ETH/SOL/etc):

```bash
python3 run_btc.py
# or: SCALPER_ASSETS=BTC python3 run.py
```

Dashboard: `http://127.0.0.1:8787` on the machine that is running `python3 run.py`. That address is not your phone or laptop unless the scalper is running there. In Cursor Cloud, open the forwarded **dashboard** port (8787) from the agent Ports panel.

The dashboard is interactive: flip each crypto market on/off, click a card for the book / venues / sparkline, filter and sort the board, pause new entries, flatten a position, and toggle **PAPER ↔ LIVE**. Keyboard: `1–7` select, `P` pause, `M` mute, `F` flatten.

**PAPER** is the default. **LIVE** sends IOC limits to your Kalshi account. The toggle stays locked until `KALSHI_API_KEY` and `KALSHI_PRIVATE_KEY` (or `KALSHI_PRIVATE_KEY_PATH`) **and** `SCALPER_DASHBOARD_TOKEN` are set. Going live asks you to type `LIVE`, then starts **paused** so you have to resume before any real order goes out. Flatten paper positions before switching. Open Kalshi positions are imported (not ignored). Exits are `reduce_only` IOCs; a partial fill shrinks the local size and retries instead of pretending the whole clip is still open.

```bash
export SCALPER_BANKROLL=1000
export SCALPER_PORT=8787
export SCALPER_ASSETS=BTC          # optional; comma list, default is all 7
# required for the LIVE toggle
# export KALSHI_API_KEY="your-key-id"
# export KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
# export SCALPER_DASHBOARD_TOKEN="long-random-string"   # required to arm LIVE; sent as X-Scalper-Token
# optional: export KALSHI_API_BASE=https://external-api.demo.kalshi.co/trade-api/v2
```

## Tests

```bash
python3 -m pytest tests -q
```
