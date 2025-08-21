# mexctop_bot.py — MEXC Derivatives Top 20 by 7D % (no API key needed)
import os, requests, datetime

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
BASE = "https://contract.mexc.com/api/v1"

def list_mexc_usdt_perps():
    r = requests.get(f"{BASE}/contract/detail", timeout=30)
    r.raise_for_status()
    items = r.json().get("data", [])
    # Keep enabled contracts (state == 0) and USDT-margined symbols like BTC_USDT
    return [it["symbol"] for it in items if it.get("state") == 0 and it.get("symbol","").endswith("_USDT")]

def last_8_daily_closes(symbol):
    # Day1 candles; limit=8 gives us 8 most recent daily closes
    r = requests.get(f"{BASE}/contract/kline/{symbol}", params={"interval":"Day1", "limit":8}, timeout=30)
    r.raise_for_status()
    d = r.json().get("data", {})
    closes = d.get("close") or []
    times  = d.get("time") or []
    return list(zip(times, closes))

def calc_7d_change(closes):
    # Need at least 8 closes: today vs 7 days ago (8th from end)
    if len(closes) < 8: return None
    last = float(closes[-1][1])
    prev = float(closes[-8][1])
    if prev == 0: return None
    return (last/prev - 1.0) * 100.0

def gather_top20():
    symbols = list_mexc_usdt_perps()
    rows = []
    for sym in symbols:
        try:
            closes = last_8_daily_closes(sym)
            pct = calc_7d_change(closes)
            if pct is not None:
                rows.append((sym, pct))
        except Exception:
            continue
    rows.sort(key=lambda x: x[1], reverse=True)  # most positive first
    return rows[:20]

def format_msg(rows):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📈 **MEXC Derivatives — Top 20 by 7D %** (updated {ts})"]
    for i, (sym, pct) in enumerate(rows, 1):
        # make it look like standard pair name
        pretty = sym.replace("_", "/")
        lines.append(f"{i:>2}. `{pretty}`  7D: {pct:+.2f}%")
    return "\n".join(lines) if rows else "No data."

def post_discord(text):
    r = requests.post(WEBHOOK, json={"content": text}, timeout=30)
    r.raise_for_status()

if __name__ == "__main__":
    top = gather_top20()
    post_discord(format_msg(top))
