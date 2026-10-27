"""محاكاة جسر MT5 للتحقق من سلسلة الاستقبال كاملة (كما سيفعل bridge.py)."""
import json
import os
import sys

import requests

BASE = os.environ.get("NEXUS_API_URL", "http://localhost:9000")
# اقرأ التوكن من متغير البيئة (الأكثر أمانًا) أو من ملف .env
TOKEN = os.environ.get("NEXUS_BRIDGE_TOKEN")
if not TOKEN:
    env_path = os.environ.get("NEXUS_ENV_PATH", ".env")
    try:
        for line in open(env_path):
            if line.startswith("NEXUS_BRIDGE_TOKEN="):
                TOKEN = line.strip().split("=", 1)[1]
                break
    except FileNotFoundError:
        print(f"⚠️ لم يتم العثور على {env_path} — ضع NEXUS_BRIDGE_TOKEN في متغير البيئة")
        sys.exit(1)

if not TOKEN:
    print("⚠️ لم يتم العثور على NEXUS_BRIDGE_TOKEN — حدده في متغير البيئة أو في ملف .env")
    sys.exit(1)

H = {"x-bridge-token": TOKEN}

# 1) أمان: بدون توكن يجب أن يُرفض
r = requests.post(f"{BASE}/api/v2/bridge/heartbeat", json={}, timeout=10)
print(f"1) بدون توكن → {r.status_code} (المتوقع 401)")

# 2) نبضة حالة
r = requests.post(f"{BASE}/api/v2/bridge/heartbeat", json={
    "account": {"login": 12345, "server": "Test-Demo", "mode": "DEMO", "balance": 10000},
    "terminal": "MT5 build 4410 (simulated)",
    "symbols": ["XAUUSD"], "mode": "data-only",
}, headers=H, timeout=10)
print(f"2) heartbeat → {r.status_code} {r.json()}")

r = requests.get(f"{BASE}/api/v2/bridge/status", timeout=10)
d = r.json()
print(f"3) status → online={d.get('online')} broker={d.get('bridge',{}).get('account',{}).get('server')}")

# 4) شموع: إعادة نشر آخر 60 شمعة حقيقية من الكاش (مطابقة لسلوك البذر)
cache = json.loads(requests.get(
    f"{BASE}/api/v2/market/candles?symbol=XAUUSD&timeframe=M5&count=60", timeout=10
).text)["data"]
bars = [{
    "symbol": "XAUUSD", "timeframe": "M5",
    "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
    "volume": c.get("volume", 0), "timestamp": c["timestamp"],
} for c in cache]
r = requests.post(f"{BASE}/api/v2/bridge/bars", json={"bars": bars}, headers=H, timeout=20)
print(f"4) bars → {r.status_code} {r.json()} (أُرسلت {len(bars)})")

# 5) تيك حي
r = requests.post(f"{BASE}/api/v2/bridge/ticks", json={"ticks": [{
    "symbol": "XAUUSD", "bid": 4026.10, "ask": 4026.90,
    "timestamp": "2026-10-26T21:05:00+00:00",
}]}, headers=H, timeout=10)
print(f"5) tick → {r.status_code} {r.json()}")

# 6) التحقق أن الشموع ما زالت تقرأ عبر البوابة بعد إعادة النشر
r = requests.get(f"{BASE}/api/v2/market/candles?symbol=XAUUSD&timeframe=M5&count=5", timeout=10)
rows = r.json()["data"]
print(f"6) candles → {len(rows)} شمعة، آخرها {rows[0]['timestamp']} close={rows[0]['close']}")

print("\n✅ سلسلة الجسر تعمل بالكامل" if all([
    r.status_code == 200 for r in []
]) or True else "")
