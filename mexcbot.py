# MEXC Derivatives — LIVE rolling 3D / 7D / 20D % leaderboards
# current price (from /contract/ticker) vs hourly-kline prices 72h, 168h, 480h ago
import os, requests, datetime

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
BASE = "https://contract.mexc.com/api/v1"

# Filter out illiquid contracts by approx USD notional over last 24h (amount24 * lastPrice)
MIN_USD_VOL_24H = 50000   # set to 0 to disable

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
        sym   = t.get("symbol")
        last  = float(t.get("lastPrice") or 0)
        amt24 = float(t.get("amount24") or 0)
        out[sym] = {"last": last, "notional24": last * amt24}
    return out

def hourly_klines(symbol, limit):
    """Return list of (ts, close) ascending by time."""
    r = requests.get(f"{BASE}/contract/kline/{symbol}",
                     params={"interval":"Min60","limit":limit}, timeout=30)
    r.raise_for_status()
    d = r.json().get("data")
    rows = []
    if isinstance(d, list):
        # [time, open, high, low, close, volume]
        rows = [(row[0], float(row[4])) for row in d
                if isinstance(row, (list, tuple)) and len(row) >= 5]
    elif isinstance(d, dict) and "time" in d and "close" in d:
        rows = list(zip(d["time"], [float(x) for x in d["close"]]))
    rows.sort(key=lambda x: x[0])
    return rows

def base_symbol(sym):
    # "OKB_USDT" -> "OKB"
    return sym.split("_", 1)[0]

def compute_changes(symbols, tmap):
    """
    For each symbol, compute rolling % change for:
      3D (72h), 7D (168h), 20D (480h)
    Returns three dicts: {sym: pct}, one per horizon.
    """
    top3, top7, top20 = {}, {}, {}
    # Need up to 481 hours of history to reach 480h-ago reference point (+ some buffer not required)
    need = 481
    for i, sym in enumerate(symbols, 1):
        last = tmap.get(sym, {}).get("last", 0.0)
        if last <= 0:
            continue

        kl = hourly_klines(sym, need)  # last closed hours; live price comes from ticker
        n = len(kl)
        if n >= 73:   # 72h ago → index -73
            base72 = kl[-73][1]
            if base72 > 0:
                top3[sym] = (last / base72 - 1.0) * 100.0
        if n >= 169:  # 168h ago → index -169
            base168 = kl[-169][1]
            if base168 > 0:
                top7[sym] = (last / base168 - 1.0) * 100.0
        if n >= 481:  # 480h ago → index -481
            base480 = kl[-481][1]
            if base480 > 0:
                top20[sym] = (last / base480 - 1.0) * 100.0

        if i % 50 == 0:
            log(f"Processed {i}/{len(symbols)} symbols…")

    return top3, top7, top20

def leaderboard(pcts_dict, tmap, k=20):
    """Return list of (BASE, pct) sorted desc by pct."""
    rows = []
    for sym, pct in pcts_dict.items():
        rows.append((base_symbol(sym), pct))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:k]

def pad(txt, width):
    return (txt + " " * width)[:width]

def format_table(top3, top7, top20):
    """
    Build a 3-column text table. Each column lists Top 20:
    'RANK. TICKER  +NNN%'
    """
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"⚡ **MEXC Derivatives — LIVE Rolling Changes**  \nUpdated {ts}\n"
    col_w = 18  # column width for neat alignment

    # Header row
    out = [header, "```"]
    out.append(pad("3D Top 20", col_w) + pad("7D Top 20", col_w) + pad("20D Top 20", col_w))

    # Determine max rows (should be 20 each, but guard)
    max_rows = max(len(top3), len(top7), len(top20), 20)

    for i in range(max_rows):
        c1 = f"{i+1:>2}. {top3[i][0]} {top3[i][1]:+ .0f}%" if i < len(top3) else ""
        c2 = f"{i+1:>2}. {top7[i][0]} {top7[i][1]:+ .0f}%" if i < len(top7) else ""
        c3 = f"{i+1:>2}. {top20[i][0]} {top20[i][1]:+ .0f}%" if i < len(top20) else ""
        out.append(pad(c1, col_w) + pad(c2, col_w) + pad(c3, col_w))

    out.append("```")
    return "\n".join(out)

def send(msg):
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=30)
    r.raise_for_status()

if __name__ == "__main__":
    symbols = list_usdt_perps()
    tmap = tickers_map()

    # Liquidity filter
    if MIN_USD_VOL_24H > 0:
        symbols = [s for s in symbols if tmap.get(s, {}).get("notional24", 0) >= MIN_USD_VOL_24H]

    # Compute LIVE rolling changes
    p3, p7, p20 = compute_changes(symbols, tmap)

    # Build top 20 lists per horizon
    top3  = leaderboard(p3, tmap, k=20)
    top7  = leaderboard(p7, tmap, k=20)
    top20 = leaderboard(p20, tmap, k=20)

    # Send the 3-column table
    send(format_table(top3, top7, top20))
