#!/usr/bin/env python3
"""جلب أسعار الذهب التاريخية (COMEX GC=F) من Yahoo Finance -> JSON للداشبورد"""
import json, os, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

def fetch(symbol, range_="5y", interval="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range_}&interval={interval}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def extract(data):
    res = data["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = (q["open"][i], q["high"][i], q["low"][i], q["close"][i])
        if None in (o, h, l, c):
            continue
        rows.append({
            "time": time.strftime("%Y-%m-%d", time.gmtime(t)),
            "open": round(float(o), 2), "high": round(float(h), 2),
            "low": round(float(l), 2), "close": round(float(c), 2),
        })
    # إزالة أي أيام مكررة (آخر wins)
    seen, out = set(), []
    for r in rows:
        if r["time"] not in seen:
            seen.add(r["time"]); out.append(r)
    return out

def main():
    out_dir = "/home/z/my-project/public/gold"
    os.makedirs(out_dir, exist_ok=True)
    data = fetch("GC=F")
    candles = extract(data)
    meta = data["chart"]["result"][0]["meta"]
    last = candles[-1]; prev = candles[-2]
    closes = [c["close"] for c in candles]
    # أقرب إغلاق قبل ~365 يوم تقويمي
    year_ago = (time.strftime("%Y-%m-%d", time.gmtime(time.time() - 365*86400)))
    y_close = next((c["close"] for c in reversed(candles) if c["time"] <= year_ago), candles[0]["close"])
    last52 = candles[-252:] if len(candles) > 252 else candles
    summary = {
        "symbol": "GC=F", "name": "الذهب — عقود COMEX",
        "last": last["close"], "prev_close": prev["close"],
        "chg_1d_pct": round((last["close"]/prev["close"] - 1) * 100, 2),
        "chg_1y_pct": round((last["close"]/y_close - 1) * 100, 2),
        "high_52w": max(c["high"] for c in last52), "low_52w": min(c["low"] for c in last52),
        "market_time": meta.get("regularMarketTime"),
        "currency": meta.get("currency", "USD"),
        "count": len(candles),
        "first_date": candles[0]["time"], "last_date": last["time"],
    }
    with open(os.path.join(out_dir, "gold_daily.json"), "w") as f:
        json.dump({"summary": summary, "candles": candles}, f, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
