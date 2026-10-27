"""تطهير DuckDB من شموع synthetic القديمة + تصفير كاشات الميزات في Redis.

المنطق: التغذية الاصطناعية القديمة كانت حول 2350$ للذهب، والحقيقية (GC=F) ~4026$.
أي شمعة XAUUSD بـ close < 3500 = اصطناعية بيقين عملي. تُحذف مع كاشات الميزات
والإشارات القديمة ليعاد بناء كل الإحصاءات من بيانات حقيقية نقية فقط.
"""
import sys

DB = "/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main/data/nexus.duckdb"

# ── 1) DuckDB ────────────────────────────────────────────────────────────────
import duckdb
con = duckdb.connect(DB)

before = con.execute(
    "SELECT timeframe, COUNT(*) FROM ohlcv WHERE symbol='XAUUSD' GROUP BY timeframe"
).fetchall()
print("before:", before)

for tbl, col in [("ohlcv", "close"), ("ticks", "bid")]:
    try:
        n = con.execute(
            f"DELETE FROM {tbl} WHERE symbol='XAUUSD' AND {col} < 3500"
        ).fetchone() if False else None
        con.execute(f"DELETE FROM {tbl} WHERE symbol='XAUUSD' AND {col} < 3500")
        cnt = con.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE symbol='XAUUSD'"
        ).fetchone()[0]
        print(f"{tbl}: purged synthetic, remaining XAUUSD rows = {cnt}")
    except Exception as e:
        print(f"{tbl}: {e}")

after = con.execute(
    "SELECT timeframe, COUNT(*), MIN(close), MAX(close) FROM ohlcv "
    "WHERE symbol='XAUUSD' GROUP BY timeframe"
).fetchall()
print("after:", after)
con.close()

# ── 2) Redis ────────────────────────────────────────────────────────────────
import redis
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

purged = []
patterns = [
    "nexus:features:*", "features:*", "stream:features",
    "nexus:ohlcv:XAUUSD:*", "nexus:signal*", "stream:signals*",
    "nexus:ml:*", "nexus:genai:brief:*",
]
for p in patterns:
    keys = list(r.scan_iter(match=p, count=200))
    # لا نمس مفاتيح الإعدادات والاستراتيجيات والصحة
    keys = [k for k in keys if "runtime:settings" not in k and "strategy" not in k
            and "health" not in k and "news" not in k]
    if keys:
        r.delete(*keys)
        purged += keys
print(f"redis purged {len(purged)} keys")
for k in purged[:12]:
    print("  -", k)
print("DONE")
