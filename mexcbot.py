# mexctop_bot.py — LIVE rolling 7D %, base symbol + 0dp, optional volume spike
import os, requests, datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
BASE = "https://contract.mexc.com/api/v1"

# Tuning
MIN_USD_VOL_24H = 50000     # filter illiquid; set 0 to disable
MAX_SYMBOLS     = 200       # scan top-N by 24h notional (faster)
REQUEST_TIMEOUT = 20
RETRY = Retry(total=3, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])

def sess():
    s = requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) Safari/537.36"})
    s.mount("https://", HTTPAdapter(max_retries=RETRY))
    return s

def list_usdt_perps(s):
    r = s.get(f"{BASE}/contract/detail", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    items = r.json().get("data", [])
    return [it["symbol"] for it in items if it.get("state")==0 and str(it.get("symbol","")).endswith("_USDT")]

def tickers_map(s):
    r = s.get(f"{BASE}/contract/ticker", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    out = {}
    for t in r.json().get("data", []):
        sym  = t.get("symbol")
        last = float(t.get("lastPrice") or 0)
        amt24 = float(t.get("amount24") or 0)
        out[sym] = {"last": last, "notional24": last * amt24}
    return out

def hourly_klines(s, symbol, limit):
    # Returns list of (ts_ms, close, volume) oldest->newest
    r = s.get(f"{BASE}/contract/kline/{symbol}", params={"interval":"Min60", "limit":limit}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    d = r.json().get("data")
    rows = []
    if isinstance(d, list):
        # [time, open, high, low, close, volume]
        rows = [(row[0], float(row[4]), float(row[5] if len(row)>=6 and row[5] is not None else 0.0))
                for row in d if isinstance(row,(list,tuple)) and len(row)>=5]
    elif isinstance(d, dict) and "time" in d and "close" in d:
        times  = d["time"]
        closes = [float(x) for x in d["close"]]
        vols   = [float(x) for x in d.get("vol", d.get("volume", [0]*len(times)))]
        rows = list(zip(times, closes, vols))
    rows.sort(key=lambda x: x[0])
    return rows

def compute_metrics(s, symbols, tmap):
    """Compute rolling 7D price change and 7D vs prior-7D volume spike."""
    results = []
    for i, sym in enumerate(symbols, 1):
        info = tmap.get(sym)
        if not info or info["last"] <= 0:
            continue
        # Need 14 days of hourly to get last 168h and prior 168h + a buffer
        rows = hourly_klines(s, sym, limit=340)  # ~14d+ buffer
        if len(rows) < 169:
            continue
        # price 168h ago = close at index -169 (or simply first of the last 169)
        last_price = info["last"]
        prior_price = rows[-169][1]  # exactly 168 hours back
        if prior_price <= 0:
            continue
        pct7d = (last_price/prior_price - 1.0) * 100.0

        # Volume spike: sum last 168h vs previous 168h
        if len(rows) >= 336:
            last168  = sum(v for _,__,v in rows[-168:])
            prev168  = sum(v for _,__,v in rows[-336:-168])
            vol_spike_pct = None
            if prev168 > 0:
                vol_spike_pct = (last168/prev168 - 1.0) * 100.0
        else:
            vol_spike_pct = None

        results.append((sym, pct7d, vol_spike_pct))
    # sort by price pct descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:20]

def base_symbol(sym):
    # "OKB_USDT" -> "OKB"
    return sym.split("_", 1)[0]

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
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

if __name__ == "__main__":
    s = sess()
    symbols = list_usdt_perps(s)
    tmap = tickers_map(s)

    # Liquidity filter + cap to top-N by notional
    if MIN_USD_VOL_24H > 0:
        symbols = [x for x in symbols if tmap.get(x,{}).get("notional24",0) >= MIN_USD_VOL_24H]
    symbols = sorted(symbols, key=lambda x: tmap.get(x,{}).get("notional24",0), reverse=True)[:MAX_SYMBOLS]

    top = compute_metrics(s, symbols, tmap)
    send(format_msg(top))
