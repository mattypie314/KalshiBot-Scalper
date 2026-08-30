# KalshiBot-Scalper

scallllp me!

Live watcher for Kalshi 15-minute crypto. **BTC is the default.** ETH, SOL, XRP, DOGE, BNB, and HYPE are opt-in.

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

That is the BTC-only bot. The startup line should say `Markets: BTC`. `python3 run_btc.py` does the same thing.

All seven markets:

```bash
SCALPER_ASSETS=ALL python3 run.py
```

Dashboard: `http://127.0.0.1:8787` on the machine that is running `python3 run.py`. That address is not your phone or laptop unless the scalper is running there. In Cursor Cloud, open the forwarded **dashboard** port (8787) from the agent Ports panel. Startup also prints a **Phone (same Wi-Fi)** URL when the bot is bound to `0.0.0.0` (the default).

The dashboard is interactive: flip each crypto market on/off, click a card for the book / venues / sparkline, filter and sort the board, pause new entries, flatten a position, and toggle **PAPER ↔ LIVE**. Keyboard: `1–7` select, `P` pause, `M` mute, `F` flatten.

**PAPER** is the default. **LIVE** sends IOC limits to your Kalshi account. The toggle stays locked until `KALSHI_API_KEY` and `KALSHI_PRIVATE_KEY` (or `KALSHI_PRIVATE_KEY_PATH`) **and** `SCALPER_DASHBOARD_TOKEN` are set. Going live asks you to type `LIVE`, then starts **paused** so you have to resume before any real order goes out. Flatten paper positions before switching. Open Kalshi positions are imported (not ignored). Exits are `reduce_only` IOCs; a partial fill shrinks the local size and retries instead of pretending the whole clip is still open.

```bash
export SCALPER_BANKROLL=1000
export SCALPER_PORT=8787
export SCALPER_ASSETS=BTC          # default; use ALL or BTC,ETH for more
# required for the LIVE toggle
# export KALSHI_API_KEY="your-key-id"
# export KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
# export SCALPER_DASHBOARD_TOKEN="long-random-string"   # required to arm LIVE; sent as X-Scalper-Token
# optional: export KALSHI_API_BASE=https://external-api.demo.kalshi.co/trade-api/v2
```

`python3 run.py` also reads a local `.env` if present (not committed). Use that for demo keys. Leave `KALSHI_API_BASE` unset for real cash.

## Phone

The bot stays on the PC / Pi / VPS. The phone is only the dashboard.

1. Keep `python3 run.py` (or the systemd unit) running on that machine.
2. On the same Wi-Fi, open the **Phone (same Wi-Fi)** URL printed at startup — `http://<that-machine's-LAN-IP>:8787`. Windows: `ipconfig` → IPv4. Mac/Linux: `ip addr`, or just use the printed line.
3. Type `SCALPER_DASHBOARD_TOKEN` once. The dashboard stores it on the phone so Safari/Chrome restarts keep you in.
4. **iPhone home-screen app (Safari only):** type the token first so the icon remembers it. Tap **Share** (the box with the arrow) → **Add to Home Screen** → **Add**. Open **Scalper** from the home screen, not from Safari — no address bar. Chrome on iPhone will not make a real home-screen app.
5. Android: browser menu → **Add to Home screen**.

The board shows an **Add to Home Screen** tip on a phone until you dismiss it. Dismiss it after you add the icon.

Away from home: use Tailscale (or another VPN) and open `http://<tailscale-ip>:8787`. Do **not** port-forward `:8787` to the public internet. If you add the home-screen icon on Wi-Fi (`http://192.168.x.x:8787`) it will not open over Tailscale — add a second icon from the Tailscale URL if you need both.

Optional first-load bookmark on a **private** network: `http://192.168.x.x:8787/?token=YOUR_TOKEN`. The page saves the token and strips it from the address bar. Do not put a production token in a public or shared URL.

The dashboard stays locked without the token. LIVE still requires typing `LIVE`, then Resume.

## Tests

```bash
python3 -m pytest tests -q
```
