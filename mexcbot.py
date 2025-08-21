# MEXC Derivatives — LIVE rolling 7D % (uses current price vs price 168h ago)
import os, requests, datetime

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
BASE = "https://contract.mexc.com/api/v1"

# Drop illiquid symbols (approx USD notional in last 24h). Set 0 to disable.
MIN_USD_VOL_24H = 50000

def log(*a): print(*a, flush=True)

def list_usdt_perps():
    r = requests.get(f"{BASE}/contract/detail", timeout=30)
    r.raise_for_status()
    items = r.json().get("data", [])
    return [it["symbol"] for it in items
            if it.get("state") == 0 and str(it.get("symbol","")).endswith("_USDT")]

def tickers_map():
    """Return dict: symbol -> dict(lastPrice, notional24)"""
    r = requests.get(f"{BASE}/contract/ticker", timeout=30)
    r.raise_for_status()
    out = {}
    for t in r.json().get("data", []):
        sym = t.get("symbol")
        last = float(t.get("lastPrice") or 0)
        amt24 = float(t.get("amount24") or 0)
        out[sym] = {"last": last, "notional24": last * amt24}
    return out

def price_168h_ago(symbol):
    """Get close price 168 hours ago from hourly klines."""
    # Need 169 points: current hour back to T-168h
    r = requests.get(f"{BASE}/contract/kline/{symbol}",
                     params={"interval":"Min60","limit":169}, timeout=30)
    r.raise_for_status()
    d = r.json().get("data")
    rows = []
    if isinstance(d, list):
        # row: [time, open, high, low, close, volume]
        rows = [(row[0], float(row[4])) for row in d if isinstance(row, (list,tuple)) and len(row) >= 5]
    elif isinstance(d, dict) and "time" in d and "close" in d:
        rows = list(zip(d["time"], [float(x) for x in d["close"]]))
    rows.sort(key=lambda x: x[0])  # ascending
    if len(rows) < 169:  # not enough history
        return None
    # index 0..168 (169 items). The first element is ~168h ago.
    return rows[0][1]

def compute_live_7d(symbols, tmap):
    rows = []
    for i, sym in enumerate(symbols, 1):
        info = tmap.get(sym)
        if not info or info["last"] <= 0:
            continue
        base = price_168h_ago(sym)
        if base and base > 0:
            pct = (info["last"]/base - 1.0) * 100.0
            rows.append((sym, pct))
        if i % 50 == 0:
            log(f"Processed {i}/{len(symbols)} symbols…")
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:20]

def format_msg(rows):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"⚡ **MEXC Derivatives — LIVE Top 20 by Rolling 7D %**  \nUpdated {ts}"]
    for i, (sym, pct) in enumerate(rows, 1):
        lines.append(f"{i:>2}. `{sym.replace('_','/')}`  7D: {pct:+.2f}%")
    return "\n".join(lines) if rows else "No data."

def send(msg):
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=30)
    r.raise_for_status()

if __name__ == "__main__":
    symbols = list_usdt_perps()
    tmap = tickers_map()
    if MIN_USD_VOL_24H > 0:
        symbols = [s for s in symbols if tmap.get(s, {}).get("notional24", 0) >= MIN_USD_VOL_24H]
    top = compute_live_7d(symbols, tmap)
    send(format_msg(top))
