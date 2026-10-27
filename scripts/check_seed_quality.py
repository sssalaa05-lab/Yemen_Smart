"""فحص جودة سلسلة OneRoyal المبذورة (dupes / gaps / قفزات سعرية) عبر API الخدمة."""
import json
import urllib.request
from datetime import datetime

URL = "http://localhost:9001/api/data/ohlcv/XAUUSD/M5?limit=3000"
with urllib.request.urlopen(URL, timeout=30) as resp:
    bars = json.loads(resp.read().decode())

bars.sort(key=lambda b: b["timestamp"])
ts = [b["timestamp"] for b in bars]
closes = [float(b["close"]) for b in bars]

print("bars:", len(bars))
print("range:", ts[0], "→", ts[-1])
print("dupes:", len(ts) - len(set(ts)))
print("price range: %.2f → %.2f" % (min(closes), max(closes)))

# فجوات > 5 دقائق (عدا عطلة نهاية الأسبوع: الجمعة 21:00Z+ / السبت / الأحد قبل 22:00Z)
gaps = []
for i in range(1, len(ts)):
    t0 = datetime.fromisoformat(ts[i - 1].replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(ts[i].replace("Z", "+00:00"))
    dt = (t1 - t0).total_seconds() / 60
    if dt > 5.01:
        wd = t0.weekday()  # 4=Fri 5=Sat 6=Sun
        weekend = (wd == 4 and t0.hour >= 21) or wd == 5 or (wd == 6 and t1.hour < 22)
        if not weekend:
            gaps.append((ts[i - 1], ts[i], dt))
print("unexpected gaps (>5min خارج العطلة):", len(gaps))
for g in gaps[:6]:
    print("  ", g)

# قفزات سعرية شاذة (>40$ في شمعة واحدة = خلط مصادر محتمل)
jumps = [(ts[i], closes[i - 1], closes[i]) for i in range(1, len(closes)) if abs(closes[i] - closes[i - 1]) > 40]
print("price jumps >40$/bar:", len(jumps))
for j in jumps[:6]:
    print("  ", j)

# آخر 3 شموع
print("latest:", [(t, c) for t, c in list(zip(ts, closes))[-3:]])
