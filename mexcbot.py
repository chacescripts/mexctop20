# MEXC Derivatives — LIVE rolling 7D % (current price vs price 168h ago)
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

def hourly_klines(symbol, limit):
    """Return list of (ts, close, volume) in ascending time order."""
    r = requests.get(f"{BASE}/contract/kline/{symbol}",
                     params={"interval":"Min60","limit":limit}, timeout=30)
    r.raise_for_status()
    d = r.json().get("data")
    rows = []
    if isinstance(d, list):
        # [time, open, high, low, close, volume]
        rows = [(row[0], float(row[4]), float(row[5] if len(row)>=6 and row[5] is not None else 0.0))
                for row in d if isinstance(row, (list, tuple)) and len(row) >= 5]
    elif isinstance(d, dict) and "time" in d and "close" in d:
        times  = d["time"]
        closes = [float(x) for x in d["close"]]
        vols   = [float(x) for x in d.get("vol", d.get("volume", [0]*len(times)))]
        rows = list(zip(times, closes, vols))
    rows.sort(key=lambda x: x[0])
    return rows

def base_symbol(sym):
    # "OKB_USDT" -> "OKB"
    return sym.split("_", 1)[0]

def compute_live_7d(symbols, tmap, want_vol_spike=True):
    """
    Returns list of tuples: (symbol, pct7d, vol_spike_pct_or_None)
    pct7d uses live last price vs price 168h ago.
    vol_spike compares sum(volume last 168h) vs prior 168h.
    """
    rows = []
    for i, sym in enumerate(symbols, 1):
        info = tmap.get(sym)
        if not info or info["last"] <= 0:
            continue

        # Pull enough hourly data to compute both price 168h ago and volume spike
        need = 340 if want_vol_spike else 169
        kl = hourly_klines(sym, need)
        if len(kl) < 169:
            continue

        prior_price = kl[-169][1]  # exactly 168 hours back
        if prior_price <= 0:
            continue

        pct = (info["last"]/prior_price - 1.0) * 100.0

        vol_spike = None
        if want_vol_spike and len(kl) >= 336:
            last168 = sum(v for _, __, v in kl[-168:])
            prev168 = sum(v for _, __, v in kl[-336:-168])
            if prev168 > 0:
                vol_spike = (last168/prev168 - 1.0) * 100.0

        rows.append((sym, pct, vol_spike))

        if i % 50 == 0:
            log(f"Processed {i}/{len(symbols)} symbols…")

    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:20]

def format_msg(rows):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"⚡ **MEXC Derivatives — LIVE Top 20 by Rolling 7D %**  \nUpdated {ts}"]
    for i, (sym, pct, vsp) in enumerate(rows, 1):
        name = base_symbol(sym)
        line = f"{i:>2}. {name}  {pct:+.0f}%"
        if vsp is not None:
            line += f"  · Vol {vsp:+.0f}%"
        lines.append(line)
    return "\n".join(lines) if rows else "No data."

def send(msg):
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=30)
    r.raise_for_status()

if __name__ == "__main__":
    symbols = list_usdt_perps()
    tmap = tickers_map()
    if MIN_USD_VOL_24H > 0:
        symbols = [s for s in symbols if tmap.get(s, {}).get("notional24", 0) >= MIN_USD_VOL_24H]
    top = compute_live_7d(symbols, tmap, want_vol_spike=True)
    send(format_msg(top))
