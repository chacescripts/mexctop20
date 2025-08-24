# MEXC Derivatives — LIVE rolling 3D / 7D / 20D % leaderboards
# (sectioned output, two-column text, bold exclusives)
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
    """Return list of (ts, close) in ascending time order."""
    r = requests.get(f"{BASE}/contract/kline/{symbol}",
                     params={"interval":"Min60","limit":limit}, timeout=30)
    r.raise_for_status()
    d = r.json().get("data")
    rows = []
    if isinstance(d, list):
        rows = [(row[0], float(row[4])) for row in d
                if isinstance(row, (list, tuple)) and len(row) >= 5]
    elif isinstance(d, dict) and "time" in d and "close" in d:
        rows = list(zip(d["time"], [float(x) for x in d["close"]]))
    rows.sort(key=lambda x: x[0])  # ascending
    return rows

def base_symbol(sym):
    # "OKB_USDT" -> "OKB"
    return sym.split("_", 1)[0]

# ---------- compute 3D / 7D / 20D live changes ----------
def compute_changes(symbols, tmap):
    p3, p7, p20 = {}, {}, {}
    need = 481  # enough history to reach 480h-ago baseline
    for i, sym in enumerate(symbols, 1):
        info = tmap.get(sym)
        last = info["last"] if info else 0.0
        if last <= 0:
            continue

        kl = hourly_klines(sym, need)
        n = len(kl)
        if n >= 73:   # 72h ago: index -73
            base72 = kl[-73][1]
            if base72 > 0:
                p3[sym] = (last / base72 - 1.0) * 100.0
        if n >= 169:  # 168h ago: index -169
            base168 = kl[-169][1]
            if base168 > 0:
                p7[sym] = (last / base168 - 1.0) * 100.0
        if n >= 481:  # 480h ago: index -481
            base480 = kl[-481][1]
            if base480 > 0:
                p20[sym] = (last / base480 - 1.0) * 100.0

        if i % 50 == 0:
            log(f"Processed {i}/{len(symbols)} symbols…")
    return p3, p7, p20

def leaderboard(pct_map, k=20):
    rows = [(base_symbol(sym), pct) for sym, pct in pct_map.items()]
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:k]

def fmt_pct(x): 
    return f"{x:+.0f}%"

def format_section(title, rows, exclusive_names, ticker_col_w=10, pct_col_w=6):
    """
    Plain Markdown (no code fences) so **bold** works.
    Two columns: ticker (left-padded to ticker_col_w), percent (right-padded to pct_col_w).
    """
    lines = [f"**{title}**"]
    for name, pct in rows:
        # Bold ticker only if it's exclusive to this section
        show = f"**{name}**" if name in exclusive_names else name
        # pad based on raw ticker length so spacing stays consistent
        pad_spaces = " " * max(ticker_col_w - len(name), 1)
        pct_str = fmt_pct(pct).rjust(pct_col_w)
        lines.append(f"{show}{pad_spaces}{pct_str}")
    return "\n".join(lines)

def format_message(top3, top7, top20):
    # Build exclusivity sets based on displayed base tickers
    set3  = {n for n, _ in top3}
    set7  = {n for n, _ in top7}
    set20 = {n for n, _ in top20}
    ex3   = set3  - (set7 | set20)
    ex7   = set7  - (set3 | set20)
    ex20  = set20 - (set3 | set7)

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"⚡ **MEXC Derivatives — LIVE Rolling Changes**\nUpdated {ts}\n"
    parts = [
        format_section("3D Top 20",  top3,  ex3),
        "",
        format_section("7D Top 20",  top7,  ex7),
        "",
        format_section("20D Top 20", top20, ex20),
    ]
    return header + "\n".join(parts)

def send(msg):
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=30)
    r.raise_for_status()

# ---------- main ----------
if __name__ == "__main__":
    symbols = list_usdt_perps()
    tmap = tickers_map()

    if MIN_USD_VOL_24H > 0:
        symbols = [s for s in symbols if tmap.get(s, {}).get("notional24", 0) >= MIN_USD_VOL_24H]

    p3, p7, p20 = compute_changes(symbols, tmap)
    top3  = leaderboard(p3, 20)
    top7  = leaderboard(p7, 20)
    top20 = leaderboard(p20, 20)

    send(format_message(top3, top7, top20))
