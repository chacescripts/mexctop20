# mexctop_bot.py — MEXC Derivatives Top 20 by 7D % (debug version)
import os, requests, datetime, sys

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
BASE = "https://contract.mexc.com/api/v1"

def log(*a):
    print(*a, flush=True)

def list_mexc_usdt_perps():
    url = f"{BASE}/contract/detail"
    log("GET", url)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    items = r.json().get("data", [])
    symbols = [it["symbol"] for it in items
               if it.get("state") == 0 and str(it.get("symbol","")).endswith("_USDT")]
    log(f"Found {len(symbols)} enabled USDT contracts")
    return symbols

def last_8_daily_closes(symbol):
    url = f"{BASE}/contract/kline/{symbol}"
    params = {"interval": "Day1", "limit": 8}
    log("GET", url, params)
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    j = r.json()
    d = j.get("data")

    # Handle two possible shapes:
    # A) dict of lists: {"time":[...], "close":[...], ...}
    # B) list of arrays: [[time, open, high, low, close, volume], ...]
    closes = []
    times = []
    if isinstance(d, dict) and "close" in d and "time" in d:
        times = d.get("time") or []
        closes = d.get("close") or []
        pairs = list(zip(times, closes))
    elif isinstance(d, list) and d and isinstance(d[0], (list, tuple)) and len(d[0]) >= 5:
        # index 0=time, 4=close per MEXC format
        pairs = [(row[0], row[4]) for row in d]
    else:
        log("Unexpected Kline format for", symbol, "payload keys:", (d.keys() if isinstance(d, dict) else type(d)))
        return []

    return pairs

def calc_7d_change(closes):
    if len(closes) < 8: 
        return None
    last = float(closes[-1][1])
    prev = float(closes[-8][1])
    if prev == 0: 
        return None
    return (last/prev - 1.0) * 100.0

def gather_top20():
    symbols = list_mexc_usdt_perps()
    rows = []
    for idx, sym in enumerate(symbols, 1):
        try:
            closes = last_8_daily_closes(sym)
            pct = calc_7d_change(closes)
            if pct is not None:
                rows.append((sym, pct))
        except Exception as e:
            log(f"[WARN] {sym} failed: {e}")
            continue
        if idx % 50 == 0:
            log(f"Scanned {idx}/{len(symbols)} contracts…")
    rows.sort(key=lambda x: x[1], reverse=True)
    log(f"Computed 7D change for {len(rows)} contracts; top 3 preview:", rows[:3])
    return rows[:20]

def format_msg(rows):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📈 **MEXC Derivatives — Top 20 by 7D %** (updated {ts})"]
    for i, (sym, pct) in enumerate(rows, 1):
        pretty = sym.replace("_", "/")
        lines.append(f"{i:>2}. `{pretty}`  7D: {pct:+.2f}%")
    return "\n".join(lines) if rows else "No data."

def post_discord(text):
    log("POST Discord webhook (message length:", len(text), ")")
    r = requests.post(WEBHOOK, json={"content": text}, timeout=30)
    log("Discord status:", r.status_code)
    r.raise_for_status()   # Discord returns 204 on success

if __name__ == "__main__":
    top = gather_top20()
    msg = format_msg(top)
    if not top:
        log("No rows to send; message:", msg)
    post_discord(msg)
